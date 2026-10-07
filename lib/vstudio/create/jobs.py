"""Run a ladder stage for an episode: stills -> animatic -> drafts -> finals (the only paid one).

    run(eid, stage, estimate_id=None, confirm_code=None, max_cny=None, allow_unknown=False, only=None, on_event=None)

finals = the spend gate first (costs.verify + costs.check + provider quotes), then:
  * hardest shots first; when 2 of the first 3 hard units fail (error or failed generation) the run pauses and
    asks (``create.hard-shots-failed``) before anything else is submitted;
  * ``submit`` is called once per unit, ever. A timeout after the request left = ``unknown-charge`` (ledger row,
    alert with "Check <service>" / "Try again · ≈ ¥X" - a new estimate + confirm for that one shot); a rejected
    request = ``failed`` (not charged). Nothing is resubmitted automatically;
  * every submit is in spend.jsonl + the month counter before polling starts; task ids go to work/ai/state.json
    (generate.py's format) at once, so a crash never leads to a second submit;
  * concurrency per service = min(the service's own limit, Fleet's ``api:<service>`` resource class);
  * the run never spends past ``max_cny`` (the approved amount) even if the estimate was low.
manual (即梦) units get a prompt sheet and wait for the files; record units wait for the recorder; card / reuse
shots are made in post.
"""
import contextlib
import fcntl
import glob
import os
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import costs, formats as F, providers as PR, routing, store, stills, storyboard
from .i18n import CreateError, msg

STAGES = ("stills", "animatic", "drafts", "finals")
_locks = {}
_glock = threading.Lock()
POLL_EVERY = float(os.environ.get("VSTUDIO_CREATE_POLL_S", "10"))
POLL_LIMIT = float(os.environ.get("VSTUDIO_CREATE_POLL_LIMIT_S", "1800"))


def lock(eid):
    with _glock:
        return _locks.setdefault(eid, threading.RLock())


@contextlib.contextmanager
def submit_lock(eid):
    """This thread's episode lock + a file lock, so two desk processes (double click, two windows) cannot both
    pass the spend gate with the same OK."""
    with lock(eid):
        d = store.episode_dir(eid)
        with open(os.path.join(d, ".submit.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)


def context(eid):
    ep = store.load_episode(eid)
    s = store.load_series_file(ep["series"])
    fmt = F.get(store.create_meta(s)["format"])
    bible = store.load_bible(ep["series"])
    return ep, s, fmt, bible


def plan(ep, s, fmt, only=None):
    connected = PR.connected()
    routes, warns = routing.resolve(ep, s, fmt, connected)
    if only:
        keep = set(only)
        sub = dict(ep, shots=[x for x in ep.get("shots") or [] if x["no"] in keep])
        routes = [r for r in routes if r["no"] in keep]
        units = routing.units(sub, routes)
    else:
        units = routing.units(ep, routes)
    return routes, units, warns


def estimate(eid, stage="finals", only=None, save=True):
    if stage not in STAGES:
        raise CreateError("bad-input", field="stage")
    with lock(eid):
        ep, s, fmt, _ = context(eid)
        only = _only(ep, only)
        routes, units, warns = plan(ep, s, fmt, only)
        est = costs.build(ep, s, stage, routes, units)
        est["only"] = only
        est.update(costs.context(est, s, ep["series"]))
        est["warnings"] = warns
        if save and stage == "finals":
            keep = dict(sorted((ep.get("estimates") or {}).items(), key=lambda kv: kv[1].get("created", 0))[-4:])
            keep[est["id"]] = {k: v for k, v in est.items() if k not in ("budget", "month", "warnings")}
            ep["estimates"] = keep
            store.save_episode(ep)
        return est


def _only(ep, only):
    if not only:
        return None
    nos = {x["no"] for x in ep.get("shots") or []}
    only = sorted({store.need_shot(n) for n in only})
    if any(n not in nos for n in only):
        raise CreateError("bad-input", field="only")
    return only


# --------------------------------------------------------------------------- gate
def gate(eid, estimate_id, confirm_code, max_cny, allow_unknown=False, only=None):
    """All of SPEC §1.5 or a CreateError - with no side effects."""
    ep, s, fmt, bible = context(eid)
    only = _only(ep, only)
    routes, units, _ = plan(ep, s, fmt, only)
    fresh = costs.build(ep, s, "finals", routes, units)
    est = costs.verify(ep, estimate_id, confirm_code, max_cny, fresh)
    if (est.get("only") or None) != only:
        raise CreateError("plan-changed", status=409)
    paid = [u for u in units if u["kind"] in ("cloud", "mcp")]
    if not paid and not any(u["kind"] == "manual" for u in units):
        raise CreateError("nothing-to-make", status=409)
    pids = sorted({u["provider"] for u in paid})
    ready = {p: PR.get(p).status().get("ready", False) for p in pids}
    balances = {}
    for p in pids:
        if ready[p]:
            b = PR.get(p).balance()
            if b is not None:
                balances[p] = b
    chk = costs.check(est, s, ep["series"], allow_unknown, balances, ready)
    if not chk["ok"]:
        c = chk["codes"][0]
        raise CreateError(c["code"], status=409, codes=chk["codes"], **c["params"])
    for u in paid:
        p = PR.get(u["provider"])
        job = build_job(ep, bible, u)
        q = p.quote(job)
        if q is not None:
            mine = costs.price_job(u["provider"], u["model"], u["seconds"])["cny"] or 0
            if q > mine * 1.05 + 1e-6:
                raise CreateError("price-changed", status=409, provider=u["provider"], quoted=q, estimated=mine,
                                  shots=u["shots"])
    return ep, s, fmt, bible, est, routes, units


# --------------------------------------------------------------------------- jobs for a unit
def build_job(ep, bible, unit):
    """The ai-video Job for one unit: the episode's ai-video project, only this unit's shots, this model."""
    from .providers.aivideo import plan_module
    PL = plan_module()
    path = os.path.join(store.work_dir(ep), "project.yaml")
    if not os.path.exists(path):
        storyboard.write_aivideo(ep, bible)
    cfg = PL.load(path)
    cfg["model"] = unit["model"]
    cfg["provider"] = unit["provider"]
    cfg["shots"] = [dict(sh, unit=unit["id"]) for sh in cfg["shots"] if str(sh["id"]) in unit["shots"]]
    if not cfg["shots"]:
        cfg["shots"] = [dict(id=no, dur=2, chars=[], action="") for no in unit["shots"]]
    u = PL.compile_units(cfg, pad=0.0 if len(unit["shots"]) == 1 else 0.5)[0]
    job = PL.unit_job(cfg, u)
    e = costs.entry(unit["provider"], unit["model"]) or {}
    job.unit = unit["id"]
    job.resolution = e.get("resolution") or job.resolution
    job.duration = costs.snap(e, unit["seconds"], job.resolution) if e else unit["seconds"]
    if e.get("api_model"):              # the service's own model id when it differs from Reelfold's key
        job.model = os.environ.get(e.get("api_model_env") or "", "") or e["api_model"]
    job.extra = dict(job.extra or {}, rationale=f"Shot {', '.join(unit['shots'])} of the user's own short.")
    if PR.fake_mode() and unit.get("hard"):
        job.extra["fake_takes"] = 2
    return job


def _state_path(ep):
    return os.path.join(store.work_dir(ep), "state.json")


def _takes_dir(ep):
    d = os.path.join(store.work_dir(ep), "takes")
    os.makedirs(d, exist_ok=True)
    return d


class Run:
    """One finals run over an episode's units (thread-safe episode updates; every transition saved)."""

    def __init__(self, ep, bible, est, units, max_cny, on_event=None):
        self.ep, self.bible, self.est, self.units = ep, bible, est, units
        self.max_cny = float(max_cny)
        self.on_event = on_event or (lambda e: None)
        self.eid, self.sid = ep["id"], ep["series"]
        self.lk = lock(self.eid)
        self.spent = 0.0
        self.rid = (ep.get("run") or {}).get("id") or f"r{int(time.time())}"

    # ------------------------------------------------------------ bookkeeping
    def save(self):
        with self.lk:
            store.save_episode(self.ep)

    def emit(self, **ev):
        ev.setdefault("event", "create.progress")
        ev.update(episode=self.eid, series=self.sid, ts=time.time())
        try:
            self.on_event(ev)
        except Exception:  # noqa: BLE001
            pass

    def set_unit(self, uid, **f):
        with self.lk:
            self.ep["run"]["units"].setdefault(uid, {}).update(f)
            self.save()
        self.emit(unit=uid, **{k: v for k, v in f.items() if k in ("state", "code")})

    def alert(self, code, **params):
        with self.lk:
            self.ep["run"].setdefault("alerts", []).append(dict(msg(code, **params), at=time.time()))
            self.save()

    def stopped(self):
        return os.path.exists(os.path.join(store.work_dir(self.ep), "STOP"))

    def state_json(self, tid, unit, est_cny):
        p = _state_path(self.ep)
        with self.lk:
            st = store.read_json(p, None) or {"pending": {}, "takes": {}, "spent_estimate": 0.0, "failed": {}}
            if tid:
                st["pending"][tid] = {"unit": unit["id"], "provider": unit["provider"], "est": est_cny,
                                      "at": store.stamp()}
                st["spent_estimate"] = round(st.get("spent_estimate", 0) + (est_cny or 0), 2)
            store.write_json(p, st)

    def state_done(self, tid, unit, files, failed=None):
        p = _state_path(self.ep)
        with self.lk:
            st = store.read_json(p, None) or {"pending": {}, "takes": {}, "spent_estimate": 0.0, "failed": {}}
            st["pending"].pop(tid, None)
            for f in files:
                st["takes"].setdefault(unit["id"], []).append({"file": os.path.basename(f), "task": tid})
            if failed:
                st["failed"][unit["id"]] = failed
            store.write_json(p, st)

    # ------------------------------------------------------------ one unit
    def one(self, unit):
        if self.stopped():
            self.set_unit(unit["id"], state="stopped")
            return "stopped"
        p = PR.get(unit["provider"])
        price = costs.price_job(unit["provider"], unit["model"], unit["seconds"])
        cny = float(price["cny"] or 0)
        with self.lk:
            if self.spent + cny > self.max_cny + 1e-6:
                self.alert("max-too-low", max_cny=self.max_cny, need=round(self.spent + cny, 1), shots=unit["shots"])
                self.ep["run"]["units"].setdefault(unit["id"], {}).update(state="skipped", code="create.max-too-low")
                self.save()
                return "skipped"
            self.spent = round(self.spent + cny, 2)
        job = build_job(self.ep, self.bible, unit)
        self.set_unit(unit["id"], state="submitting", provider=unit["provider"], shots=unit["shots"], cny=cny)
        base = dict(episode=self.eid, shots=unit["shots"], unit=unit["id"], provider=unit["provider"],
                    model=unit["model"], est_cny=cny, credits=price.get("native_units"), run=self.rid)
        try:
            tid = p.submit(job)                                   # PAID - exactly once
        except PR.SubmitTimeout as e:
            costs.ledger_append(self.sid, dict(base, task_id=None, status="unknown-charge", error=str(e)[:200]))
            self.alert("unknown-charge", provider=unit["provider"], shots=unit["shots"], cny=cny, unit=unit["id"])
            self.set_unit(unit["id"], state="unknown-charge", code="create.unknown-charge")
            return "unknown"
        except CreateError:
            with self.lk:
                self.spent = round(self.spent - cny, 2)
            raise
        except Exception as e:  # noqa: BLE001  (rejected before acceptance: not charged)
            with self.lk:
                self.spent = round(self.spent - cny, 2)
            costs.ledger_append(self.sid, dict(base, est_cny=0, task_id=None, status="rejected", error=str(e)[:200]))
            self.set_unit(unit["id"], state="failed", code="create.shot-failed", error=str(e)[:200])
            return "failed"
        costs.ledger_append(self.sid, dict(base, task_id=tid, status="submitted"))
        self.state_json(tid, unit, cny)
        self.set_unit(unit["id"], state="running", task=tid)
        t0 = time.time()
        while True:
            try:
                r = p.poll(tid)
            except Exception as e:  # noqa: BLE001  (poll errors after retries: leave it pending, user can collect)
                self.set_unit(unit["id"], state="unknown-charge", code="create.poll-failed", error=str(e)[:200])
                return "unknown"
            if r["status"] in ("done", "failed") or time.time() - t0 > POLL_LIMIT:
                break
            time.sleep(POLL_EVERY if not PR.fake_mode() else 0.05)
        if r["status"] != "done":
            self.state_done(tid, unit, [], failed=str(r.get("raw"))[:200])
            self.set_unit(unit["id"], state="failed", code="create.shot-failed")
            return "failed"
        urls = list(r.get("urls") or [])
        if PR.fake_mode() and (job.extra or {}).get("fake_takes", 1) > 1 and urls:
            urls = urls * int(job.extra["fake_takes"])
        files = []
        d = _takes_dir(self.ep)
        for url in urls:
            n = len(glob.glob(os.path.join(d, f"{unit['id']}_v*.*"))) + 1
            path = os.path.join(d, f"{unit['id']}_v{n}.mp4")
            try:
                p.download(url, path)
                files.append(path)
            except Exception as e:  # noqa: BLE001
                self.alert("download-failed", provider=unit["provider"], shots=unit["shots"], error=str(e)[:120])
        self.state_done(tid, unit, files)
        with self.lk:
            for no in unit["shots"]:
                lst = self.ep.setdefault("takes", {}).setdefault(no, [])
                for f in files:
                    lst.append(dict(file=f, unit=unit["id"], provider=unit["provider"], model=unit["model"],
                                    task=tid, at=store.stamp()))
                if len(lst) == 1:
                    self.ep.setdefault("picks", {})[no] = lst[0]["file"]
            self.save()
        self.set_unit(unit["id"], state="done" if files else "failed", n_takes=len(files))
        return "done" if files else "failed"

    # ------------------------------------------------------------ the batch
    def pool(self, units):
        from vstudio.batch.run import default_limits, limit_for
        lim = default_limits()
        by = {}
        for u in units:
            by.setdefault(u["provider"], []).append(u)
        results = {}

        def lane(pid, us):
            n = max(1, min(int(PR.info(pid).get("concurrency") or 1), limit_for(lim, f"api:{pid}")))
            with ThreadPoolExecutor(max_workers=n) as ex:
                for u, res in zip(us, ex.map(self.one, us)):
                    results[u["id"]] = res

        threads = [threading.Thread(target=lane, args=(pid, us), daemon=True) for pid, us in by.items()]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results


def run_finals(eid, estimate_id, confirm_code, max_cny, allow_unknown=False, only=None, on_event=None,
               hard_first=True, early_stop=True):
    with submit_lock(eid):              # gate + "this OK is used" in one step: a double click submits once
        ep, s, fmt, bible, est, routes, units = gate(eid, estimate_id, confirm_code, max_cny, allow_unknown, only)
        ep = store.load_episode(eid)
        ep["estimates"][est["id"]]["used"] = store.stamp()
        try:
            os.remove(os.path.join(store.work_dir(ep), "STOP"))
        except OSError:
            pass
        ep["run"] = dict(id=f"r{int(time.time())}", stage="finals", state="running", estimate=est["id"],
                         approved_cny=float(max_cny), started=store.stamp(), units={}, alerts=[],
                         order=[], only=only)
        ep.setdefault("approved", []).append(dict(estimate=est["id"], code=confirm_code, max_cny=float(max_cny),
                                                  at=store.stamp()))
        ep["state"] = "making"
        ep.setdefault("ladder", {})["finals"] = "running"
        store.save_episode(ep)
    paid = [u for u in units if u["kind"] in ("cloud", "mcp")]
    manual = [u for u in units if u["kind"] == "manual"]
    if manual:
        write_manual_sheets(ep, bible, manual)
    order = sorted(paid, key=lambda u: (u.get("hard_rank", 99), u["shots"][0])) if hard_first else list(paid)
    R = Run(ep, bible, est, order, max_cny, on_event)
    R.ep["run"]["order"] = [u["id"] for u in order]
    for u in order:
        R.ep["run"]["units"][u["id"]] = dict(state="queued", provider=u["provider"], shots=u["shots"], hard=u["hard"])
    for u in manual:
        R.ep["run"]["units"][u["id"]] = dict(state="manual-waiting", provider=u["provider"], shots=u["shots"])
    R.save()
    R.emit(event="create.stage", stage="finals", state="running", total=len(order))
    hard = [u for u in order if u["hard"]][:3] if early_stop else []
    if hard:
        res = R.pool(hard)
        bad = [u for u in hard if res.get(u["id"]) in ("failed", "unknown")]
        if len(bad) >= 2:
            with R.lk:
                R.ep["run"]["state"] = "paused"
                R.ep["run"]["paused"] = msg("hard-shots-failed", shots=[no for u in bad for no in u["shots"]])
                R.ep["ladder"]["finals"] = "paused"
                R.save()
            R.emit(event="create.stage", stage="finals", state="paused", code="create.hard-shots-failed")
            return summary(eid)
    rest = [u for u in order if u not in hard]
    R.pool(rest)
    with R.lk:
        units_st = R.ep["run"]["units"]
        R.ep["run"]["state"] = "stopped" if R.stopped() else "done"
        R.ep["run"]["spent_cny"] = R.spent
        R.ep["run"]["finished"] = store.stamp()
        R.ep["ladder"]["finals"] = "pick" if needs_pick(R.ep) else (
            "waiting" if any(v["state"] in ("manual-waiting",) for v in units_st.values()) else "done")
        R.save()
    R.emit(event="create.done", stage="finals", state=R.ep["run"]["state"])
    return summary(eid)


def needs_pick(ep):
    return any(len(v) > 1 and not (ep.get("picks") or {}).get(no) for no, v in (ep.get("takes") or {}).items())


def summary(eid):
    ep = store.load_episode(eid)
    return dict(ok=True, episode=eid, run={k: v for k, v in (ep.get("run") or {}).items()},
                ladder=ep.get("ladder"), takes={k: len(v) for k, v in (ep.get("takes") or {}).items()})


def stop(eid):
    ep = store.load_episode(eid)
    p = os.path.join(store.work_dir(ep), "STOP")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(store.stamp())
    return dict(ok=True, episode=eid, stopping=True)


# --------------------------------------------------------------------------- free stages
def run_stills(eid, on_event=None):
    with lock(eid):
        ep = store.load_episode(eid)
        d = os.path.join(store.work_dir(ep), "stills")
        s = store.load_series_file(ep["series"])
        fmt = F.get(store.create_meta(s)["format"])
        routes, _ = routing.resolve(ep, s, fmt, PR.connected())
        kinds = {r["no"]: (r["provider"] if r["kind"] in ("cloud", "mcp", "manual") else r["kind"]) for r in routes}
        cast = [c.get("id") for c in store.load_bible(ep["series"]).get("cast") or []]
        for i, shot in enumerate(ep.get("shots") or []):
            shot["still"] = stills.placeholder(shot, os.path.join(d, f"{shot['no']}.jpg"),
                                               kind=kinds.get(shot["no"], "local"), cast=cast)
            if on_event and i % 4 == 0:
                on_event(dict(event="create.progress", stage="stills", episode=eid, done=i, total=len(ep["shots"])))
        ep.setdefault("ladder", {})["stills"] = "done"
        store.save_episode(ep)
    return dict(ok=True, episode=eid, stage="stills", n=len(ep.get("shots") or []))


def run_animatic(eid, on_event=None):
    with lock(eid):
        ep = store.load_episode(eid)
        if (ep.get("ladder") or {}).get("stills") != "done":
            run_stills(eid)
            ep = store.load_episode(eid)
        out = os.path.join(store.work_dir(ep), "animatic.mp4")
        ff = shutil.which("ffmpeg")
        if ff and ep.get("shots"):
            lst = os.path.join(store.work_dir(ep), "animatic.txt")
            with open(lst, "w", encoding="utf-8") as f:
                for s in ep["shots"]:
                    f.write(f"file '{s['still']}'\nduration {float(s.get('dur') or 2):.2f}\n")
                f.write(f"file '{ep['shots'][-1]['still']}'\n")
            try:
                subprocess.run([ff, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-vf",
                                "scale=360:640,format=yuv420p", "-r", "24", "-c:v", "libx264", "-preset", "ultrafast",
                                out], check=True, capture_output=True, timeout=300)
            except (subprocess.SubprocessError, OSError):
                out = None
        else:
            out = None
        ep["animatic"] = out
        ep.setdefault("ladder", {})["animatic"] = "done"
        store.save_episode(ep)
    return dict(ok=True, episode=eid, stage="animatic", file=out)


def run_drafts(eid, on_event=None):
    """Local drafts: phase 2 (the adapters only detect). Marks the step skipped with the reason."""
    from .providers.local_rapidmlx import enabled
    with lock(eid):
        ep = store.load_episode(eid)
        ep.setdefault("ladder", {})["drafts"] = "skipped"
        ep["drafts_note"] = msg("local-off", phase=2, enabled=enabled())
        store.save_episode(ep)
    return dict(ok=True, episode=eid, stage="drafts", skipped=True, code="create.local-off")


def run(eid, stage, estimate_id=None, confirm_code=None, max_cny=None, allow_unknown=False, only=None,
        on_event=None, early_stop=True):
    store.need_eid(eid)
    if stage == "finals":
        return run_finals(eid, estimate_id, confirm_code, max_cny, allow_unknown, only, on_event, early_stop=early_stop)
    if stage == "stills":
        return run_stills(eid, on_event)
    if stage == "animatic":
        return run_animatic(eid, on_event)
    if stage == "drafts":
        return run_drafts(eid, on_event)
    raise CreateError("bad-input", field="stage")


# --------------------------------------------------------------------------- takes
def write_manual_sheets(ep, bible, units):
    """即梦: one prompt per unit to copy into the site; YOU press Generate there; save as <unit>_v1.mp4."""
    j = PR.get("jimeng") if not PR.fake_mode() else None
    parts = ["# 即梦 prompts\n\nPaste each prompt into jimeng.com, press Generate yourself, and save the download as "
             "`<unit>_v1.mp4` (Reelfold picks the files up).\n"]
    for u in units:
        job = build_job(ep, bible, u)
        parts.append(j.sheet(job) if j else f"## {u['id']}\n\n```\n{job.prompt}\n```\n")
    path = os.path.join(store.work_dir(ep), "sheets", "PROMPTS.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def manual_prompts(eid):
    ep, s, fmt, bible = context(eid)
    routes, units, _ = plan(ep, s, fmt)
    out = []
    for u in units:
        if u["kind"] == "manual":
            out.append(dict(unit=u["id"], shots=u["shots"], prompt=build_job(ep, bible, u).prompt,
                            seconds=u["seconds"]))
    return out


def pick(eid, no, take):
    no = store.need_shot(no)
    with lock(eid):
        ep = store.load_episode(eid)
        files = [t["file"] for t in (ep.get("takes") or {}).get(no) or []]
        cand = [f for f in files if f == take or os.path.basename(f) == take]
        if not cand:
            raise CreateError("bad-input", field="take")
        ep.setdefault("picks", {})[no] = cand[0]
        if (ep.get("ladder") or {}).get("finals") == "pick" and not needs_pick(ep):
            ep["ladder"]["finals"] = "done"
        store.save_episode(ep)
    return dict(ok=True, episode=eid, shot=no, take=cand[0], ladder=ep.get("ladder"))


def import_takes(eid, files):
    """Manual downloads named <unit>_*.mp4 or <shot>_*.mp4 -> takes (copied, never moved)."""
    out = []
    with lock(eid):
        ep = store.load_episode(eid)
        d = _takes_dir(ep)
        nos = [s["no"] for s in ep.get("shots") or []]
        for f in files or []:
            base = os.path.basename(f)
            key = base.split("_")[0].split(".")[0]
            no = key[1:] if key.startswith("u") and key[1:] in nos else key if key in nos else None
            if not no or not os.path.isfile(f):
                continue
            n = len(glob.glob(os.path.join(d, f"u{no}_v*.*"))) + 1
            dst = os.path.join(d, f"u{no}_v{n}{os.path.splitext(base)[1].lower() or '.mp4'}")
            shutil.copy2(f, dst)
            lst = ep.setdefault("takes", {}).setdefault(no, [])
            lst.append(dict(file=dst, unit=f"u{no}", provider="manual", at=store.stamp()))
            if len(lst) == 1:
                ep.setdefault("picks", {})[no] = dst
            out.append(dict(shot=no, file=dst))
        store.save_episode(ep)
    return dict(ok=True, imported=out)


def set_source(eid, no, source):
    no = store.need_shot(no)
    routing.check_source(source)
    with lock(eid):
        ep = store.load_episode(eid)
        shot = next((s for s in ep.get("shots") or [] if s["no"] == no), None)
        if not shot:
            raise CreateError("not-found", status=404, what="shot", id=no)
        shot["source"] = routing.parse(source)["source"] if source not in ("cheapest",) else None
        store.save_episode(ep)
    return shot
