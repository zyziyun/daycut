"""Adapter over the real ``vstudio.batch`` package (the engine repo, read-only).

Long-running ``run`` goes through the CLI in a subprocess (``python -m vstudio.batch run --batch DIR``): it holds
the batch's run lock, can be interrupted (SIGINT -> resumable) and its stdout is streamed as SSE ``log`` events.
Short operations call the batch modules in-process so the desk gets structured results without parsing text:
plan.plan_batch, estimate.estimate, cli.status_rows, review.collect / apply_decisions, package.package.
"""
import os
import re
import signal
import subprocess
import sys
import threading
import time

from .common import rebase, safe_name, BadRequest, batch_id, need, read_json, sha1_json, write_json

EXIT_STATUS = {0: "ok", 1: "done-with-failures", 2: "over-budget", 3: "paused", 4: "pilot-waits", 6: "busy"}


class RealEngine:
    mode = "real"

    def __init__(self, data_dir, registry, bus, python=None, engine_path=None):
        import vstudio.batch  # noqa: F401  (fail fast -> the server reports the engine as not starting)
        self.data_dir = data_dir
        self.reg = registry
        self.bus = bus
        self.python = python or sys.executable
        self.engine_path = engine_path
        self.procs = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ helpers
    def _dir(self, bid):
        b = self.reg.get(bid)
        if not b:
            raise KeyError(f"unknown batch {bid}")
        return b["dir"]

    def dir_of(self, bid):
        return self._dir(bid)

    def _store(self, bid):
        from vstudio.batch.store import Store
        return Store(self._dir(bid))

    def _env(self):
        env = dict(os.environ)
        lib = os.path.join(self.engine_path, "lib") if self.engine_path else None
        if lib:
            env["PYTHONPATH"] = lib + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["PYTHONUNBUFFERED"] = "1"
        for k in ("DESK_TOKEN",):
            env.pop(k, None)
        return env

    # ------------------------------------------------------------------ info
    def health(self):
        import vstudio
        try:
            from vstudio import media
            ffmpeg = media.ffmpeg_bin()
        except Exception as e:  # noqa: BLE001  (missing ffmpeg must not break health)
            ffmpeg = f"unavailable: {e}"
        try:                     # the engine's one encoder setting (VSTUDIO_H264_ENCODER / persona), video-studio >= eedca6c
            from vstudio import h264
            enc, eff = h264.encoder(), h264.effective_encoder()
        except Exception:  # noqa: BLE001  (older engine: only the desk-side variable existed)
            enc = os.environ.get("VSTUDIO_H264_ENCODER") or os.environ.get("DESK_H264_ENCODER") or "libx264"
            eff = None
        return dict(mode=self.mode, engine_path=self.engine_path,
                    vstudio=getattr(vstudio, "__file__", None), python=self.python, ffmpeg=ffmpeg,
                    h264_encoder=enc, h264_effective=eff)

    def recipes(self):
        from vstudio.batch import recipes as R
        from vstudio.batch import stages  # noqa: F401  (registers the built-in recipes)
        return [dict(name=n, description=R.REGISTRY[n].description, stages=[s.name for s in R.REGISTRY[n].order()])
                for n in R.names()]

    def list_batches(self):
        out = []
        for b in self.reg.all():
            ent = dict(id=b["id"], dir=b["dir"], name=b.get("name"), running=self.running(b["id"]))
            try:
                st = self._store(b["id"])
                try:
                    jobs = st.jobs()
                    ent.update(name=st.spec.get("name") or b.get("name"), recipe=st.spec.get("recipe"),
                               state=st.state(), package=st.meta("package"), pause_reason=st.meta("pause_reason"),
                               counts=_counts(jobs))
                finally:
                    st.close()
            except (FileNotFoundError, OSError) as e:
                ent.update(state="missing", error=str(e))
            out.append(ent)
        return out

    def roots(self):
        out = []
        for b in self.reg.all():
            out.append(b["dir"])
            try:
                st = self._store(b["id"])
                try:
                    p = st.meta("package") or {}
                    if p.get("dir"):
                        out.append(p["dir"])
                    for k in ("source", "folder"):
                        v = (st.spec.get("inputs") or {}).get(k)
                        if v:
                            out.append(os.path.dirname(v) if k == "source" else v)
                finally:
                    st.close()
            except (FileNotFoundError, OSError):
                pass
        return sorted(set(out))

    # ------------------------------------------------------------------ plan
    def create_batch(self, body):
        name = body["name"]
        spec = dict(name=name, recipe=body["recipe"], inputs={})
        if body.get("source"):
            spec["inputs"]["source"] = body["source"]
        if body.get("folder"):
            spec["inputs"]["folder"] = body["folder"]
        if body.get("segments"):
            spec["segments"] = body["segments"]
        spec["defaults"] = dict(platforms=body.get("platforms") or ["xiaohongshu:full"])
        if body.get("budget"):
            spec["budget"] = body["budget"]
        if body.get("schedule"):
            spec["schedule"] = body["schedule"]
        if body.get("planner"):
            spec["planner"] = body["planner"]
        if body.get("client_dir"):                 # only sent when the engine has the `client` command
            spec["client"] = body["client_dir"]
        spec_path = os.path.join(self.data_dir, "specs", f"{safe_name(name)}.json")
        write_json(spec_path, spec)
        base = os.path.dirname(body.get("source") or body.get("folder").rstrip(os.sep))
        bdir = body.get("out_dir") or os.path.join(base, f"batch-{name}")
        from vstudio.batch.plan import plan_batch
        r = plan_batch(spec_path, bdir, None, None, echo=False)
        ent = self.reg.add(r["batch_dir"], name)
        self.bus.publish("batches")
        return dict(id=ent["id"], dir=r["batch_dir"], spec=spec_path,
                    jobs=r["jobs"], created=r["created"], updated=r["updated"], dropped=r["dropped"])

    def import_batch(self, path):
        from vstudio.batch.store import DB_NAME
        need(os.path.exists(os.path.join(path, DB_NAME)), f"no {DB_NAME} in {path}")
        st = self._store_at(path)
        try:
            name = st.spec.get("name") or os.path.basename(path)
        finally:
            st.close()
        ent = self.reg.add(path, name)
        self.bus.publish("batches")
        return ent

    def _store_at(self, path):
        from vstudio.batch.store import Store
        return Store(path)

    # ------------------------------------------------------------------ status / estimate
    def status(self, bid):
        from vstudio.batch.cli import status_rows
        st = self._store(bid)
        try:
            rows = status_rows(st)
            spec = st.spec
            meta = dict(id=bid, dir=st.dir, name=spec.get("name"), recipe=spec.get("recipe"), state=st.state(),
                        pause_reason=st.meta("pause_reason"), package=st.meta("package"),
                        pilot_jobs=st.meta("pilot_jobs") or [], budget=spec.get("budget") or {},
                        platforms=(spec.get("defaults") or {}).get("platforms") or [], running=self.running(bid))
            extra = {j["id"]: j for j in st.jobs()}
            for r in rows:
                j = extra.get(r["id"]) or {}
                p = j.get("params") or {}
                r["title"] = p.get("title") or ""
                r["platforms"] = p.get("platforms") or []
                r["item"] = j.get("item")
                r["variant"] = j.get("variant")
                qr = j.get("qc_reasons") if isinstance(j.get("qc_reasons"), dict) else {}
                r["qc_red"] = qr.get("red") or []
                r["qc_warn"] = qr.get("warn") or []
                r["review_reason"] = j.get("review_reason")
            return dict(meta=meta, jobs=rows)
        finally:
            st.close()

    def estimate(self, bid):
        from vstudio.batch import estimate as EST
        from vstudio.batch.run import load_recipe, resolve_limits
        st = self._store(bid)
        try:
            spec = st.spec
            est = EST.estimate(st, load_recipe(spec), spec, resolve_limits(spec))
            est["text"] = EST.format_estimate(est)
            return est
        finally:
            st.close()

    def events(self, bid, n=50, job=None):
        st = self._store(bid)
        try:
            return st.events(n, job=job)
        finally:
            st.close()

    # ------------------------------------------------------------------ run (subprocess)
    def running(self, bid):
        p = self.procs.get(bid)
        return bool(p and p.poll() is None)

    def run(self, bid, opts):
        bdir = self._dir(bid)
        cmd = [self.python, "-m", "vstudio.batch", "run", "--batch", bdir]
        if opts.get("pilot"):
            cmd += ["--pilot", str(int(opts["pilot"]))]
        for flag in ("confirm_pilot", "resume", "retry_failed"):
            if opts.get(flag):
                cmd.append("--" + flag.replace("_", "-"))
        if opts.get("jobs"):
            cmd += ["--jobs", ",".join(opts["jobs"])]
        return self._spawn(bid, cmd)

    def spawn_rerun(self, bid, jid):
        """v0.2 ``job rerun`` (only the stages made stale by ``job edit``); streamed like ``run``."""
        return self._spawn(bid, [self.python, "-m", "vstudio.batch", "job", "rerun", "--batch", self._dir(bid),
                                 "--job", jid])

    def _spawn(self, bid, cmd):
        bdir = self._dir(bid)
        with self._lock:
            if self.running(bid):
                raise BadRequest("this batch is already running")
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 env=self._env(), cwd=bdir, text=True, bufsize=1, start_new_session=True)
            self.procs[bid] = p
        self.bus.publish("run-start", batch=bid, cmd=cmd[3:])
        threading.Thread(target=self._pump, args=(bid, p), daemon=True).start()
        threading.Thread(target=self._poll_status, args=(bid, p), daemon=True).start()
        return dict(started=True, pid=p.pid)

    def _pump(self, bid, p):
        for line in p.stdout:
            self.bus.publish("log", batch=bid, line=line.rstrip("\n")[:2000])
        code = p.wait()
        self.bus.publish("run-exit", batch=bid, code=code, status=EXIT_STATUS.get(code, f"exit {code}"))
        self._push_status(bid)

    def _poll_status(self, bid, p):
        last = None
        while p.poll() is None:
            time.sleep(1.5)
            last = self._push_status(bid, last)

    def _push_status(self, bid, last=None):
        try:
            s = self.status(bid)
        except Exception:  # noqa: BLE001
            return last
        sig = sha1_json([(j["id"], j["state"], j["progress"], j["stage"], j["qc"]) for j in s["jobs"]]
                        + [s["meta"]["state"], s["meta"]["running"]])
        if sig != last:
            self.bus.publish("status", batch=bid, status=s)
        return sig

    def cancel(self, bid):
        p = self.procs.get(bid)
        if not p or p.poll() is not None:
            return dict(cancelled=False)
        try:
            os.killpg(p.pid, signal.SIGINT)      # the run is resumable: stale `running` rows go back to pending
        except OSError:
            p.terminate()
        return dict(cancelled=True)

    def shutdown(self):
        for bid in list(self.procs):
            self.cancel(bid)

    # ------------------------------------------------------------------ review
    def review_items(self, bid):
        from vstudio.batch import review
        st = self._store(bid)
        try:
            items = review.collect(st)
        finally:
            st.close()
        bdir = self._dir(bid)
        rdir = os.path.join(bdir, "review")
        for it in items:                      # collect() returns paths relative to <batch>/review -> absolute
            for k in ("sheet", "snippet"):
                if it.get(k):
                    it[k] = os.path.normpath(os.path.join(rdir, it[k]))
            it["files"] = [os.path.normpath(os.path.join(rdir, f)) for f in it.get("files") or [] if f]
            for k in ("sheet", "snippet"):
                it[k] = rebase(it.get(k), bdir)
            it["files"] = [rebase(f, bdir) for f in it["files"]]
        return items

    def apply_review(self, bid, decisions):
        from vstudio.batch import review
        r = review.apply_decisions(self._dir(bid), decisions)
        self._push_status(bid)
        return dict(approved=r["approved"], rejected=r["rejected"], replied=r["replied"],
                    skipped=[list(x) for x in r["skipped"]])

    # ------------------------------------------------------------------ package
    def package(self, bid, opts):
        from vstudio.batch.package import package
        r = package(self._dir(bid), per_day=opts.get("per_day"), start=opts.get("start"), times=opts.get("times"))
        self._push_status(bid)
        return r

    def manifest(self, bid):
        st = self._store(bid)
        try:
            p = st.meta("package") or {}
        finally:
            st.close()
        if not p.get("dir"):
            return dict(manifest=None, dir=None, verify=dict(ok=False, reason="not packaged yet"))
        man = read_json(os.path.join(p["dir"], "manifest.json"))
        return dict(manifest=man, dir=p["dir"], verify=verify_manifest(man))

    # ------------------------------------------------------------------ job detail
    def job(self, bid, jid):
        d = self._job_legacy(bid, jid)
        try:                                       # newer engines: captions + source transcript for in-review edits
            from vstudio.batch import api
            if hasattr(api, "job_detail"):
                full = api.job_detail(self._dir(bid), jid)
                for k in ("captions", "transcript", "recipe"):
                    if k in full:
                        d[k] = full[k]
                if isinstance(full.get("edit"), dict):
                    d["engine_edit"] = full["edit"]
        except Exception:  # noqa: BLE001  (the legacy view is enough for review)
            pass
        bdir, m = self._dir(bid), d.get("media") or {}
        for k in ("master", "sheet", "snippet"):
            m[k] = rebase(m.get(k), bdir)
        for e in m.get("exports") or []:
            for k in ("file", "cover", "post"):
                e[k] = rebase(e.get(k), bdir)
        return d

    def _job_legacy(self, bid, jid):
        st = self._store(bid)
        try:
            j = st.job(jid)
            if not j:
                raise KeyError(f"unknown job {jid}")
            rows = st.stage_rows(jid)
            evs = st.events(30, job=jid)
        finally:
            st.close()
        stages = [dict(name=k, state=r["state"], seconds=r["seconds"], error=r["error"], cached=bool(r["cached"]),
                       attempts=r["attempts"]) for k, r in rows.items()]
        out = lambda s: (rows.get(s) or {}).get("out") or {}  # noqa: E731
        cl, cm, ex, pv = out("cleanup"), out("compose"), out("export"), out("preview")
        reply = (j["params"] or {}).get("cleanup_reply") or ""
        return dict(job={k: j[k] for k in ("id", "item", "variant", "state", "qc", "qc_reasons", "review",
                                           "review_reason", "pilot", "sample", "cost", "params")},
                    stages=stages, events=evs, cleanup=_cleanup_view(cl, reply),
                    media=dict(master=cm.get("master"), sheet=pv.get("sheet"), snippet=pv.get("snippet"),
                               exports=[dict(platform=e.get("platform"), orientation=e.get("orientation"),
                                             file=e.get("file"), cover=e.get("cover"), post=e.get("post"),
                                             duration=e.get("duration")) for e in ex.get("exports") or []]))


def _counts(jobs):
    c = {}
    for j in jobs:
        c[j["state"]] = c.get(j["state"], 0) + 1
    c["total"] = len(jobs)
    c["green"] = sum(j["qc"] == "green" for j in jobs)
    c["red"] = sum(j["qc"] == "red" for j in jobs)
    return c


_REPLY = re.compile(r"(全部确认|全确认|全删|all[- ]?confirm|approve[- ]?all|不删|保留|keep|不要删|确认|同意|删除|删|approve|cut|yes)"
                    r"\s*[:：]?\s*([\d\s,，、\-–~]*)", re.I)


def _parse_reply_local(text):
    """Copy of vstudio.cleanup.parse_reply (mock mode has no vstudio; real mode prefers the engine's own)."""
    res = dict(approve=set(), keep=set(), all_confirm=False)
    for kw, nums in _REPLY.findall(text or ""):
        k = kw.lower().replace(" ", "-")
        if k in ("全部确认", "全确认", "全删", "all-confirm", "allconfirm", "approve-all", "approveall"):
            res["all_confirm"] = True
            continue
        ids = set()
        for a, b in re.findall(r"(\d+)\s*(?:[\-–~]\s*(\d+))?", nums):
            ids |= set(range(int(a), int(b or a) + 1))
        (res["keep"] if k in ("不删", "保留", "keep", "不要删") else res["approve"]).update(ids)
    return res


def _cleanup_view(cl, reply):
    """Cleanup EDLs of a job -> words + edits with their effective cut state under the current reply."""
    try:
        from vstudio.cleanup import parse_reply
    except ImportError:
        parse_reply = _parse_reply_local
    r = parse_reply(reply) if reply else dict(approve=set(), keep=set(), all_confirm=False)
    parts = []
    for part in ("hook", "body"):
        path = cl.get(part)
        E = read_json(path) if path else None
        if not E:
            continue
        edits = []
        for e in E.get("edits") or []:
            eid = e["id"]
            if e["action"] == "auto":
                cut = eid not in r["keep"]
            elif e["action"] == "confirm":
                cut = (eid in r["approve"] or r["all_confirm"]) and eid not in r["keep"]
            else:
                cut = False
            edits.append(dict(id=eid, t0=e["t0"], t1=e["t1"], kind=e["kind"], text=e.get("text", ""),
                              action=e["action"], reason=e.get("reason", ""), confidence=e.get("confidence"),
                              words=e.get("words") or [], cut=cut))
        parts.append(dict(part=part, words=[dict(w=w["w"], t=w["t"], te=w["te"]) for w in E.get("words") or []],
                          edits=edits, stats=E.get("stats")))
    return dict(reply=reply, parts=parts)


def verify_manifest(man):
    """Recompute the package confirmation code exactly as vstudio.batch.package does."""
    if not isinstance(man, dict) or "items" not in man:
        return dict(ok=False, reason="no manifest")
    try:
        from vstudio.batch.util import sha1_json as engine_sha1
    except ImportError:                    # mock mode: same algorithm, local copy
        engine_sha1 = sha1_json
    code = engine_sha1(dict(batch=man.get("batch"), schedule=man.get("schedule"), items=man.get("items")))[:12]
    ok = code == man.get("confirmation_code")
    return dict(ok=ok, code=code, stored=man.get("confirmation_code"), items=len(man.get("items") or []),
                reason=None if ok else "manifest changed after packaging (code mismatch)")


__all__ = ["RealEngine", "verify_manifest", "batch_id"]
