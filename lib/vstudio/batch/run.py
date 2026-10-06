"""The scheduler: per-job stage DAGs on resource-class queues, durable and resumable.

* Resource classes with concurrency limits (``asr``, ``cpu``, ``cpu-render``, ``browser``, ``face``, ``io``,
  ``api:<name>``); defaults sized from this machine's cores / memory, overridden by spec ``concurrency`` and
  ``run --concurrency asr=1,cpu-render=2``.
* Durable: every stage transition is a row in batch.db before / after it runs. After a crash or Ctrl-C the
  next ``run`` turns stale ``running`` rows back into ``pending`` and continues from the last finished stage.
* Idempotent: a stage's key hashes its version, its params and its deps' keys (+ their content digests). A
  stage re-runs only when the key changed (e.g. a new cleanup reply) or its outputs were cleaned away.
  Shared stages (probe / extract / asr of a source) are stored once in ``cache/`` and reused by every job.
* Retries for transient errors only (timeouts, connection resets, 429 / 5xx, ``TransientError``), with
  exponential backoff; deterministic errors fail the job at once; ``paid`` stages are never re-submitted.
* Circuit breaker: the batch pauses when the failure rate of this run's finished jobs exceeds
  ``breaker.max_fail_rate`` (default 0.3 after ``min_jobs`` 4), the QC red rate exceeds ``max_red_rate``
  (default off), the API spend passes ``budget.max_usd``, or (``--pilot N``) any pilot job fails or goes red.
  ``run --resume`` clears the pause. On a pause no new job and no expensive stage starts, but jobs already under
  way finish their cheap post-render stages (``verify`` / ``qc`` / ``preview``, ``Stage.drain``) so an exported
  job is never left without its QC / preview; whatever is still open when the run exits is marked
  ``interrupted`` (never a stale ``running``) and picked up by the next ``run``.
* ``--pilot N``: run N jobs end to end, then stop in state ``pilot-review``; the full run needs
  ``--confirm-pilot`` after a human looked at them (``review``).
* ``on_event(dict)`` (``run --json-events``: one JSON object per line on stdout) gets the progress stream:
  ``run-start`` {jobs, limits, total_stages}, ``stage-start`` / ``stage-done`` (seconds, cached) / ``stage-retry`` /
  ``stage-fail``, ``job-done`` {state, qc}, ``progress`` {done_stages, total_stages, jobs_done, jobs_total},
  ``pause`` {reason}, ``log`` {msg}, ``run-end`` {status, exit_code}. Every event has ``event`` and ``ts``.
"""
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from . import estimate as EST
from . import recipes as RC
from .store import Store
from .util import du, now, sha1_json

RESOURCES = ("asr", "cpu", "cpu-render", "browser", "face", "io", "api:*")


class TransientError(RuntimeError):
    """Raise from a stage for a failure worth retrying (rate limit, flaky network, busy device)."""


class BatchBusy(RuntimeError):
    pass


def _mem_gb():
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError, AttributeError):
        return 16.0


def default_limits(cores=None, mem_gb=None):
    """Concurrency per resource class. 10 cores / 32 GB -> asr 1, cpu 5, cpu-render 3, browser 2, face 2, io 4,
    api:* 4. ffmpeg / x264 is itself multi-threaded, so cpu-render stays at cores / 3; whisper (mlx) owns the GPU,
    so one ASR at a time; MediaPipe / headless Chrome are memory-bound."""
    cores = cores or os.cpu_count() or 4
    mem = mem_gb if mem_gb is not None else _mem_gb()
    return {"asr": 1, "cpu": max(1, cores // 2), "cpu-render": max(1, cores // 3),
            "browser": 2 if mem >= 16 else 1, "face": 2 if mem >= 24 else 1, "io": 4, "api:*": 4}


def parse_limits(text):
    out = {}
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = int(v)
    return out


def resolve_limits(spec, overrides=None):
    lim = default_limits()
    lim.update({k: int(v) for k, v in (spec.get("concurrency") or {}).items()})
    lim.update(overrides or {})
    return lim


def limit_for(limits, res):
    if res in limits:
        return limits[res]
    if res.startswith("api:"):
        return limits.get("api:*", 4)
    return limits.get("cpu", 2)


_TRANSIENT = re.compile(r"\b(429|500|502|503|504|529)\b|rate.?limit|timed? ?out|temporar|try again|connection "
                        r"(reset|refused|aborted)|overloaded|resource (temporarily )?(busy|unavailable)", re.I)
_TRANSIENT_TYPES = {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
                    "OverloadedError", "ServiceUnavailableError"}


def is_transient(exc):
    if isinstance(exc, (TransientError, TimeoutError, ConnectionError, subprocess.TimeoutExpired)):
        return True
    if type(exc).__name__ in _TRANSIENT_TYPES:
        return True
    return bool(_TRANSIENT.search(str(exc)[:2000]))


def stage_satisfied_rows(rows):
    return {k for k, r in rows.items() if r["state"] in ("done", "skipped")}


def stage_key(st, job, spec, dep_rows):
    deps = []
    for d in st.deps:
        r = dep_rows.get(d) or {}
        deps.append([d, r.get("key") if r.get("state") != "skipped" else "skip", (r.get("out") or {}).get("digest")])
    return sha1_json([st.name, st.version, st.params(job, spec), deps])


def files_exist(out):
    return all(os.path.exists(f) for f in (out or {}).get("files") or [])


def job_dict(row):
    return dict(id=row["id"], params=row["params"] or {}, recipe=row["recipe"], item=row.get("item"),
                variant=row.get("variant"))


def load_recipe(spec):
    for p in spec.get("plugin_paths") or ():
        if p not in sys.path:
            sys.path.insert(0, p)
    return RC.get(spec["recipe"], spec.get("plugins"))


def _jsonable(out):
    return json.loads(json.dumps(out or {}, default=str, ensure_ascii=False))


class Runner:
    def __init__(self, batch_dir, pilot=None, limits=None, confirm_pilot=False, resume=False, retry_failed=False,
                 only=None, backoff=None, poll=0.05, echo=True, on_event=None):
        self.dir = os.path.abspath(batch_dir)
        self.on_event = on_event
        self.n_total = self.n_done = self.jobs_total = 0
        self.pilot, self.confirm_pilot, self.resume = pilot, confirm_pilot, resume
        self.retry_failed, self.only, self.poll, self.echo = retry_failed, only, poll, echo
        self.store = Store(self.dir)
        self.spec = self.store.spec
        self.recipe = load_recipe(self.spec)
        self.order = self.recipe.order()
        self.limits = resolve_limits(self.spec, limits)
        r = self.spec.get("retry") or {}
        self.backoff = float(r.get("backoff", 2.0) if backoff is None else backoff)
        br = self.spec.get("breaker") or {}
        self.br = dict(max_fail_rate=float(br.get("max_fail_rate", 0.3)), min_jobs=int(br.get("min_jobs", 4)),
                       max_red_rate=br.get("max_red_rate"))
        self.inflight, self.count, self.peak = {}, defaultdict(int), defaultdict(int)
        self.finished, self.ran, self.cached = [], [], []
        self.pause_reason = None

    # ------------------------------------------------------------- helpers
    def say(self, msg):
        if self.echo:
            print(f"[batch] {msg}", flush=True, file=sys.stderr if self.on_event else sys.stdout)
        self.emit("log", msg=str(msg))

    def emit(self, kind, **f):
        if self.on_event:
            try:
                self.on_event(dict(event=kind, ts=round(now(), 3), **f))
            except Exception:  # noqa: BLE001  (a broken consumer never stops the batch)
                pass

    def _progress(self):
        self.emit("progress", done_stages=self.n_done, total_stages=self.n_total,
                  jobs_done=len(self.finished), jobs_total=self.jobs_total)

    def _set(self, jid, st, **f):
        self.store.set_stage(jid, st, **f)
        self.rows.setdefault(jid, {})[st] = self.store.stage(jid, st)

    def _dir(self, st, jid, key):
        if st.shared:
            return os.path.join(self.dir, "cache", st.name, key[:16])
        return os.path.join(self.dir, "jobs", jid, st.name)

    def pause(self, reason):
        if self.pause_reason:
            return
        self.pause_reason = reason
        self.store.set_meta("state", "paused")
        self.store.set_meta("pause_reason", reason)
        self.store.log("pause", reason)
        self.emit("pause", reason=reason)
        self.say(f"PAUSED: {reason}")

    # ------------------------------------------------------------- setup
    def _recover(self):
        n = 0
        for jid, rows in self.store.all_stage_rows().items():
            for st, r in rows.items():
                if r["state"] == "running":
                    self.store.set_stage(jid, st, state="pending", not_before=0)
                    n += 1
        for a in self.store.arts():
            if a["state"] == "running":
                self.store.drop_art(a["stage"], a["key"])
        if n:
            self.store.log("resume", f"{n} interrupted stage(s) back to pending")
            self.say(f"resuming: {n} interrupted stage(s) will re-run from their last finished input")

    def _select(self):
        states = ["planned", "running", "interrupted"] + (["failed"] if self.retry_failed else [])
        if self.only:                                  # explicitly named jobs are re-checked even when done
            states += ["done"]                         # (unchanged stages are cache hits)
        jobs = self.store.jobs(states)
        if self.only:
            jobs = [j for j in jobs if j["id"] in self.only]
        if self.retry_failed:
            for j in jobs:
                if j["state"] == "failed":
                    for st, r in self.store.stage_rows(j["id"]).items():
                        if r["state"] == "failed":
                            self.store.set_stage(j["id"], st, state="pending", attempts=0, not_before=0, error=None)
                    self.store.set_job(j["id"], state="planned", qc=None, qc_reasons=None)
        if self.pilot:
            prev = [j["id"] for j in self.store.jobs() if j.get("pilot")]
            if prev:                                   # a resumed / repeated pilot keeps its jobs (done ones re-check)
                jobs = [j for j in self.store.jobs(states + ["done"]) if j["id"] in prev][:int(self.pilot)]
            else:
                jobs = jobs[:int(self.pilot)]
            for j in jobs:
                self.store.set_job(j["id"], pilot=1)
            self.store.set_meta("pilot_jobs", [j["id"] for j in jobs])
        return jobs

    # ------------------------------------------------------------- main
    def run(self):
        lockf = open(os.path.join(self.dir, "run.lock"), "w")
        try:
            fcntl.flock(lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise BatchBusy(f"another `run` is active on {self.dir}")
        lockf.write(str(os.getpid()))
        lockf.flush()
        try:
            return self._run()
        finally:
            fcntl.flock(lockf, fcntl.LOCK_UN)
            lockf.close()

    def _result(self, status, code, **kw):
        self.emit("run-end", status=status, exit_code=code, finished=self.finished, pause_reason=self.pause_reason)
        return dict(status=status, exit_code=code, ran=self.ran, cached=self.cached, peak=dict(self.peak),
                    finished=self.finished, pause_reason=self.pause_reason, **kw)

    def _run(self):
        state = self.store.state()
        if state == "paused" and not self.resume:
            r = self.store.meta("pause_reason")
            self.say(f"batch is paused ({r}); fix the cause, then `run --resume`")
            return self._result("paused", 3, reason=r)
        if state == "pilot-review" and not self.pilot and not self.confirm_pilot:
            self.say("pilot finished and waits for review: look at `review`, then `run --confirm-pilot`")
            return self._result("pilot-review", 4)
        self._recover()
        jobs = self._select()
        if not jobs:
            self.say("nothing to run")
            return self._result("idle", 0)
        est = EST.estimate(self.store, self.recipe, self.spec, self.limits, jobs=jobs)
        if not est["budget"]["ok"]:
            msg = "; ".join(est["budget"]["over"])
            self.store.log("refused", f"over budget: {msg}")
            self.say(f"REFUSED: over budget - {msg} (raise `budget:` in the spec or plan fewer jobs)")
            return self._result("over-budget", 2, estimate=est)
        self.store.set_meta("state", "running")
        self.store.set_meta("pause_reason", None)
        self.rows = self.store.all_stage_rows()
        self.active = {}
        for j in jobs:
            self.active[j["id"]] = job_dict(j)
            self.store.set_job(j["id"], state="running")
        self.jobs_total, self.n_total = len(jobs), len(jobs) * len(self.order)
        self.emit("run-start", jobs=[j["id"] for j in jobs], pilot=bool(self.pilot), limits=dict(self.limits),
                  total_stages=self.n_total, stages=[st.name for st in self.order])
        self.say(f"{len(jobs)} job(s){' (pilot)' if self.pilot else ''}; limits "
                 + ", ".join(f"{k}={v}" for k, v in self.limits.items()))
        workers = max(1, min(64, sum(self.limits.values())))
        self.pool = ThreadPoolExecutor(max_workers=workers)
        try:
            while True:
                waits = self._dispatch(drain=bool(self.pause_reason))
                if not self.inflight:
                    if self.pause_reason or not self.active:
                        break
                    if not waits:                       # nothing runnable and nothing coming: done / stuck
                        for jid in list(self.active):
                            self._finish_job(jid, "failed", [f"blocked: no runnable stage"])
                        break
                    time.sleep(max(0.0, min(min(waits) - now(), 1.0)) or self.poll)
                    continue
                done, _ = wait(list(self.inflight), timeout=self.poll, return_when=FIRST_COMPLETED)
                for f in done:
                    self._complete(f)
        except BaseException:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self._interrupt("run stopped (interrupt / error)")
            if not self.pause_reason:
                self.store.set_meta("state", "interrupted")
            raise
        self.pool.shutdown(wait=True)
        self._interrupt(f"paused: {self.pause_reason}" if self.pause_reason else "run ended")
        failed = [f for f in self.finished if f["state"] == "failed"]
        if self.pause_reason:
            return self._result("paused", 3)
        if self.pilot:
            self.store.set_meta("state", "pilot-review")
            self.say(f"pilot of {len(jobs)} done: run `review`, look at them, then `run --confirm-pilot`")
            return self._result("pilot-review", 0)
        self.store.set_meta("state", "ran")
        self.say(f"done: {len(self.finished) - len(failed)} finished, {len(failed)} failed")
        return self._result("done" if not failed else "done-with-failures", 1 if failed else 0)

    # ------------------------------------------------------------- scheduling
    def _scan(self, job):
        """-> ("complete" | "failed" | "open", ready [(stage, key)], wait-until list)."""
        rows = self.rows.setdefault(job["id"], {})
        sat, ready, waits = set(), [], []
        t = now()
        for st in self.order:
            if not st.enabled(job, self.spec):
                r = rows.get(st.name)
                if not r or r["state"] != "skipped":
                    self._set(job["id"], st.name, state="skipped", key=None, out={}, error=None)
                    self._count(job["id"], st.name, "skipped")
                sat.add(st.name)
                continue
            if not all(d in sat for d in st.deps):
                continue
            key = stage_key(st, job, self.spec, {d: rows.get(d) for d in st.deps})
            r = rows.get(st.name)
            if r and r["state"] == "done" and r["key"] == key:
                sat.add(st.name)
                self._count(job["id"], st.name, "unchanged")
                continue
            if r and r["state"] == "running":
                waits.append(t + self.poll)
                continue
            if r and r["state"] == "failed" and r["key"] == key:
                return "failed", [], []
            if r and (r["not_before"] or 0) > t:
                waits.append(r["not_before"])
                continue
            ready.append((st, key))
        if len(sat) == len(self.order):
            return "complete", [], []
        return "open", ready, waits

    def _count(self, jid, stage, how, **f):
        """Progress: each (job, stage) counts once per run (done, cached, unchanged or skipped)."""
        seen = self.__dict__.setdefault("_seen", set())
        if (jid, stage) in seen:
            return
        seen.add((jid, stage))
        self.n_done += 1
        if how in ("cached", "done"):
            self.emit("stage-done", job=jid, stage=stage, cached=how == "cached", **f)
        self._progress()

    def _interrupt(self, why):
        """Jobs still open when the run exits -> ``interrupted`` (and their running stage rows -> pending), so
        ``status`` never shows a stale ``running``; the next ``run`` picks them up."""
        for jid in list(self.active):
            for st, r in (self.store.stage_rows(jid) or {}).items():
                if r["state"] == "running":
                    self.store.set_stage(jid, st, state="pending", not_before=0, error="interrupted")
            self.store.set_job(jid, state="interrupted")
            self.store.log("job", f"interrupted ({why})", jid)
            del self.active[jid]

    def _post_render(self, jid):
        """Every non-drain stage of the job is finished: only the cheap tail (verify / qc / preview) is left."""
        rows = self.rows.get(jid, {})
        return all((rows.get(st.name) or {}).get("state") in ("done", "skipped") for st in self.order if not st.drains())

    def _dispatch(self, drain=False):
        """Start every runnable stage. drain (paused): only ``Stage.drains()`` stages, only for jobs that already
        whose expensive stages are all finished (an untouched or half-rendered job never continues while paused)."""
        waits = []
        for jid in list(self.active):
            job = self.active[jid]
            for _ in range(len(self.order) + 1):       # cache hits / skips can unlock the next stage at once
                state, ready, w = self._scan(job)
                if state == "complete":
                    self._job_complete(jid)
                    break
                if state == "failed":
                    r = next((x for x in self.rows[jid].values() if x["state"] == "failed"), {})
                    self._finish_job(jid, "failed", [f"{r.get('stage')}: {r.get('error')}"])
                    break
                waits += w
                progressed = False
                if drain:
                    ready = [(st, key) for st, key in ready if st.drains()] if self._post_render(jid) else []
                for st, key in ready:
                    out = self._start(job, st, key)
                    if out == "hit":
                        progressed = True
                    elif out == "wait":
                        waits.append(now() + self.poll)
                if not progressed:
                    break
        return waits

    def _start(self, job, st, key):
        jid, rows = job["id"], self.rows[job["id"]]
        for d in st.deps:                              # outputs cleaned away (storage hygiene) -> rebuild them
            r = rows.get(d)
            if r and r["state"] == "done" and not files_exist(r["out"]):
                self._set(jid, d, state="pending", not_before=0)
                dst = self.recipe.stage(d)
                if dst.shared:
                    self.store.drop_art(d, r["key"])
                return "wait"
        res = st.resource_of(job, self.spec)
        if self.count[res] >= limit_for(self.limits, res):
            return "wait"
        if st.shared:
            a = self.store.art(st.name, key)
            if a and a["state"] == "done":
                if files_exist(a["out"]):
                    self._set(jid, st.name, state="done", key=key, out=a["out"], cached=1, finished=now(),
                              seconds=0, error=None)
                    self.cached.append((jid, st.name))
                    self._count(jid, st.name, "cached", seconds=0.0)
                    return "hit"
                self.store.drop_art(st.name, key)
            elif a and a["state"] == "running":
                return "wait"
        d = self._dir(st, jid, key)
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d, exist_ok=True)
        if st.shared:
            self.store.set_art(st.name, key, state="running", dir=d, owner=jid)
        r = rows.get(st.name) or {}
        self._set(jid, st.name, state="running", key=key, started=now(), attempts=(r.get("attempts") or 0) + 1,
                  error=None, cached=0)
        inputs = {dd: (rows.get(dd) or {}).get("out") or {} for dd in st.deps}
        ctx = RC.Ctx(job, self.spec, d, inputs, self.dir)
        fut = self.pool.submit(_call, st.fn, ctx)
        self.inflight[fut] = (jid, st, res, key, d)
        self.emit("stage-start", job=jid, stage=st.name, resource=res, attempt=(r.get("attempts") or 0) + 1)
        self.count[res] += 1
        self.peak[res] = max(self.peak[res], self.count[res])
        return "started"

    def _complete(self, fut):
        jid, st, res, key, d = self.inflight.pop(fut)
        self.count[res] -= 1
        job = self.active.get(jid)
        try:
            out, secs, logs = fut.result()
        except BaseException as e:  # noqa: BLE001
            self._failed(jid, st, key, e)
            return
        out = _jsonable(out)
        out.setdefault("files", [])
        nbytes = du(d)
        self._set(jid, st.name, state="done", key=key, out=out, finished=now(), seconds=round(secs, 3), error=None,
                  cached=0)
        if st.shared:
            self.store.set_art(st.name, key, state="done", out=out)
        self.ran.append((jid, st.name))
        for m in logs:
            self.store.log("log", m, jid, st.name)
        cost = float(out.get("cost_usd") or 0.0)
        if cost:
            j = self.store.job(jid)
            self.store.set_job(jid, cost=(j["cost"] or 0) + cost)
            mx = (self.spec.get("budget") or {}).get("max_usd")
            if mx is not None and sum(float(x["cost"] or 0) for x in self.store.jobs()) > float(mx):
                self.pause(f"API spend passed budget.max_usd ${float(mx):.2f}")
        if job is not None:
            try:
                EST.record(self.store, st.name, res, secs, float(st.units(job, self.spec) or 0.0), nbytes)
            except Exception as e:  # noqa: BLE001  (a bench write must never fail a stage)
                self.store.log("warn", f"bench not recorded: {e}", jid, st.name)
        if st.name == "qc" and out.get("status") in ("green", "red"):
            self.store.set_job(jid, qc=out["status"], qc_reasons=dict(red=out.get("reasons") or [],
                                                                       warn=out.get("warnings") or []),
                               sample=1 if out.get("sample") else 0)
        self.store.log("done", f"{st.name} {secs:.1f}s", jid, st.name)
        self.say(f"{jid}: {st.name} done ({secs:.1f}s)")
        self._count(jid, st.name, "done", seconds=round(secs, 2), cost_usd=float(out.get("cost_usd") or 0.0))

    def _failed(self, jid, st, key, e):
        r = self.rows[jid].get(st.name) or {}
        att = r.get("attempts") or 1
        err = f"{type(e).__name__}: {e}"[:2000]
        if st.shared:
            self.store.drop_art(st.name, key)
        if is_transient(e) and not st.paid and att <= st.retries:
            delay = self.backoff * (2 ** (att - 1))
            self._set(jid, st.name, state="pending", error=err, not_before=now() + delay)
            self.store.log("retry", f"{st.name} attempt {att} transient ({err}); retry in {delay:.1f}s", jid, st.name)
            self.emit("stage-retry", job=jid, stage=st.name, attempt=att, delay=delay, error=err)
            self.say(f"{jid}: {st.name} transient error, retry {att}/{st.retries} in {delay:.1f}s")
            return
        self._set(jid, st.name, state="failed", error=err, finished=now())
        self.store.log("fail", f"{st.name}: {err}", jid, st.name)
        self.emit("stage-fail", job=jid, stage=st.name, error=err)
        self.say(f"{jid}: {st.name} FAILED - {err}")
        self._finish_job(jid, "failed", [f"{st.name}: {err}"])

    def _job_complete(self, jid):
        j = self.store.job(jid)
        self._finish_job(jid, "done", None, qc=j.get("qc"))

    def _finish_job(self, jid, state, reasons, qc=None):
        if jid not in self.active:
            return
        del self.active[jid]
        f = dict(state=state)
        if state == "failed":
            f.update(qc="red", qc_reasons=dict(red=reasons or [], warn=[]))
        self.store.set_job(jid, **f)
        j = self.store.job(jid)
        self.finished.append(dict(id=jid, state=state, qc=j.get("qc"), pilot=bool(j.get("pilot"))))
        self.store.log("job", f"{state} qc={j.get('qc')}", jid)
        self.emit("job-done", job=jid, state=state, qc=j.get("qc"), reasons=reasons or [])
        self._progress()
        self._breaker(jid)

    def _breaker(self, jid):
        last = self.finished[-1]
        if self.pilot and (last["state"] == "failed" or last["qc"] == "red"):
            why = "failed" if last["state"] == "failed" else "went red in QC"
            self.pause(f"pilot job {jid} {why} - fix the recipe / spec before running the rest")
            return
        n = len(self.finished)
        if n < self.br["min_jobs"]:
            return
        fails = sum(f["state"] == "failed" for f in self.finished)
        if fails / n > self.br["max_fail_rate"]:
            self.pause(f"failure rate {fails}/{n} > {self.br['max_fail_rate']:.0%}")
            return
        if self.br["max_red_rate"] is not None:
            reds = sum(f["qc"] == "red" and f["state"] != "failed" for f in self.finished)
            if reds / n > float(self.br["max_red_rate"]):
                self.pause(f"QC red rate {reds}/{n} > {float(self.br['max_red_rate']):.0%}")


def runner_active(batch_dir):
    """True while a ``run`` holds the batch lock (a job row saying ``running`` is real only then)."""
    path = os.path.join(os.path.abspath(batch_dir), "run.lock")
    if not os.path.exists(path):
        return False
    with open(path, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


def _call(fn, ctx):
    t = time.time()
    out = fn(ctx) or {}
    return out, time.time() - t, ctx.logs


def run_batch(batch_dir, **kw):
    r = Runner(batch_dir, **kw)
    try:
        return r.run()
    finally:
        r.store.close()
