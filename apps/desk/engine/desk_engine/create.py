"""Create page (创作) routes: /api/create/* -> the engine's ``vstudio.create`` (SPEC §2).

Real mode: every call runs ``python -m vstudio.create <cmd> --json`` (CliRunner.sibling, like intake.py); long jobs
(plan, ideas, bible revise, episodes add, run, handoff, record ingest) are background subprocesses with
``--json-events`` streamed to /api/stream as ``create`` events, polled at GET create/jobs/<id>.
Without the engine every route answers ``create.engine-missing`` (503): nothing is ever made by anything else.
(The desk's own tests run the same commands in process with fake services: engine/tests/fixtures/desk_mock.)

Nothing here runs until the desk calls it (the Create flag off = never called = zero cost). Money: a finals run is
refused here unless it carries an estimate id + an 8-hex confirm code + max_cny, and the engine checks again.

Routes (GET / POST, Bearer auth like everything else):
  GET  formats | providers | series | series/<sid> | episodes/<eid> | episodes/<eid>/estimate?stage=&only=
       | episodes/<eid>/prompts | runs?series= | spend?series= | jobs/<id>
  POST plan {prompt, format?, budget_cny?, platforms?, lang?, mode? auto|template} -> {job} (steps: create.step)      series {draft}       sample {lang}
       providers/<id>/test     series/<sid>/bible {instruction}|{patch}    series/<sid>/ideas {n}
       series/<sid>/episodes {idea_ids}   series/<sid>/settings {budget_cny?, platforms?, routing?}
       episodes/<eid>/shots/<no> {source}  episodes/<eid>/route {instruction, apply?}
       episodes/<eid>/run {stage, estimate_id?, confirm_code?, max_cny?, allow_unknown?, only?} -> {job} | 409
       episodes/<eid>/stop   episodes/<eid>/takes/<no> {take}   episodes/<eid>/import {files[]}
       episodes/<eid>/handoff {languages[], schedule} -> {job}; done: {project_id, clip, posts}
       record/ingest {session_dir, target project:talkinghead|assembled|edit|shot:EID/NO, series?} -> {job}    record/recover    spend/cap {cap_cny}
  Plugins (docs/PLUGINS.md):
  GET  plugins?lang=          POST plugins/<kind>:<id> {enabled?, settings?}
  POST import {path, importer?, format?, lang?} -> {job}; done: {series, episode, n}     import/sniff {path}
       episodes/<eid>/import-board {path, importer?} -> {job}
       episodes/<eid>/make {only?, lanes?} -> {job} (plugin: / agent: shots in parallel lanes; stop = episodes/<eid>/stop)
"""
import json
import os
import re
import signal
import subprocess
import threading
import time
import uuid

from .common import BadRequest, batch_id, need

SID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
SHOT_RE = re.compile(r"^\d{2,3}$")
SOURCE_RE = re.compile(r"^(cloud|manual|local):[a-z0-9-]+(/[\w.\-]+)?$|^(record|card)$|^reuse:[a-z0-9-]+/\d{2,3}$"
                       r"|^(plugin|agent):[a-z][a-z0-9-]{1,40}$")
PLUGIN_KEY_RE = re.compile(r"^(importer|shot-provider|agent-runner):[a-z][a-z0-9-]{1,40}$")
CODE_RE = re.compile(r"^[0-9a-f]{8}$")
EST_RE = re.compile(r"^est-[0-9a-f]{10}$")
JOB_RE = re.compile(r"^[0-9a-f]{12}$")
PROVIDER_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
LANGS = ("zh", "en", "fr")
STAGES = ("stills", "animatic", "drafts", "finals")
PLATFORM_RE = re.compile(r"^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$")
PLAN_LIMIT_S = float(os.environ.get("DESK_CREATE_PLAN_LIMIT_S") or 260)   # the engine gives up at 200 s itself
FORMATS = ("series-ad", "product-spot", "interview", "talk-show", "sketch", "record")


class Refused(BadRequest):
    """An engine refusal ({code, params}) -> HTTP 409/404/400 with the code for the UI's own words."""

    def __init__(self, code, params=None, status=409):
        super().__init__(code)
        self.status = status
        self.doc = dict(code=code, params=params or {})


def _sid(v):
    need(isinstance(v, str) and SID_RE.match(v), "bad series id")
    return v


def _shot(v):
    need(isinstance(v, str) and SHOT_RE.match(v), "bad shot number")
    return v


def _money(v, name):
    need(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100000, f"{name}: 0..100000")
    return float(v)


def _text(v, name, hi=2000):
    need(isinstance(v, str) and 0 < len(v.strip()) <= hi and "\0" not in v, f"{name}: 1-{hi} characters")
    return v.strip()


def _abs(v, name):
    need(isinstance(v, str) and 0 < len(v) < 4096 and os.path.isabs(v) and "\0" not in v, f"{name}: absolute path")
    return os.path.normpath(v)


class CreateApi:
    def __init__(self, data_dir, bus, runner=None, mode="real", history=None, calendar=None, outputs=None):
        self.data_dir, self.bus, self.runner, self.mode = data_dir, bus, runner, mode
        self.history, self.calendar, self.outputs = history, calendar, outputs
        self.jobs = {}
        self.used = False
        self.recovered = []
        self._lock = threading.Lock()
        self._inbox_cache = (0.0, [])

    # ---------------------------------------------------------------- engine access
    def real(self):
        return self.mode == "real" and self.runner is not None

    def _base(self):
        return ["--json"]

    def _need_engine(self):
        if not self.real():
            raise Refused("create.engine-missing", dict(error="the video engine is not running"), status=503)

    def call(self, args, timeout=180):
        self.used = True
        self._need_engine()
        doc = self.runner.sibling("vstudio.create").json(self._base() + args, timeout=timeout)
        return self._check(doc)

    @staticmethod
    def _check(doc):
        if isinstance(doc, dict) and isinstance(doc.get("error"), dict) and doc["error"].get("code"):
            e = doc["error"]
            raise Refused(e["code"], e.get("params") or {}, int(e.get("status") or 409))
        return doc

    def job(self, kind, args, meta=None, after=None, limit=None):
        """Background job: -> {job}. ``after(result)`` runs here when it succeeds (calendar, history). ``limit``:
        seconds before a real-mode job's process is stopped (``create.job-timeout``) - a job never spins forever."""
        self.used = True
        jid = uuid.uuid4().hex[:12]
        rec = dict(id=jid, kind=kind, state="running", started=time.time(), meta=meta or {}, events=[],
                   result=None, error=None)
        with self._lock:
            self.jobs[jid] = rec
            for old in sorted(self.jobs.values(), key=lambda j: j["started"])[:-50]:
                self.jobs.pop(old["id"], None)

        def on_event(ev):
            ev = dict(ev, job=jid, job_kind=kind)
            rec["events"] = (rec["events"] + [ev])[-30:]
            self.bus.publish("create", **{k: v for k, v in ev.items() if k not in ("type", "kind")})

        def go():
            try:
                res = self._run_job(args, on_event, limit)
                if after:
                    res = after(res) or res
                rec.update(state="done", result=res)
            except Refused as e:
                rec.update(state="error", error=e.doc)
            except Exception as e:  # noqa: BLE001
                rec.update(state="error", error=dict(code="create.failed", params=dict(error=str(e)[:300])))
            rec["finished"] = time.time()
            self.bus.publish("create", event="create.job", job=jid, job_kind=kind, state=rec["state"],
                             error=rec["error"])
        threading.Thread(target=go, daemon=True).start()
        return dict(job=jid, kind=kind)

    def _run_job(self, args, on_event, limit=None):
        self._need_engine()
        r = self.runner
        cmd = [r.python, "-m", "vstudio.create", "--json-events", *args]
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", env=r.env, stdin=subprocess.DEVNULL, start_new_session=True)
        tail = []

        def drain():
            # stderr is read while stdout is: a child whose log outgrows the pipe (about 4 KB on Windows: progress
            # bars, warnings) would otherwise block on it while we wait for stdout - a job that never ends
            for line in p.stderr:
                tail.append(line.rstrip())
                del tail[:-20]
        t_err = threading.Thread(target=drain, daemon=True)
        t_err.start()
        killed = []
        watchdog = None
        if limit:
            def stop():
                killed.append(1)
                from .proc import kill_tree               # its own session: the model CLI it started goes too
                try:
                    kill_tree(p, getattr(signal, "SIGKILL", signal.SIGTERM))
                except OSError:
                    pass
            watchdog = threading.Timer(limit, stop)
            watchdog.daemon = True
            watchdog.start()
        result = None
        for line in p.stdout:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if "result" in doc and len(doc) == 1:
                result = doc["result"]
            elif doc.get("event"):
                on_event(doc)
        p.wait()
        t_err.join(timeout=5)
        p.stdout.close()
        err = "\n".join(tail)
        if watchdog:
            watchdog.cancel()
        if killed:
            raise Refused("create.job-timeout", dict(seconds=int(limit)), 504)
        if result is None:
            raise Refused("create.failed", dict(error=(err or "").strip().splitlines()[-1:] or ["no output"]), 500)
        return self._check(result)

    def get_job(self, jid):
        need(JOB_RE.match(jid or ""), "bad job id")
        j = self.jobs.get(jid)
        if not j:
            raise KeyError("no such job")
        return {k: v for k, v in j.items()}

    # ---------------------------------------------------------------- folders
    def roots(self):
        if not self.used:
            return []
        try:
            from vstudio.batch.clients import home
            vh = home()
        except ImportError:
            vh = os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio")
        out = [os.path.join(vh, "series"), os.path.join(vh, "recordings")]
        return [p for p in out if os.path.isdir(p)]

    def recordings_root(self):
        try:
            from vstudio.batch.clients import home
            return os.path.join(home(), "recordings")
        except ImportError:
            return os.path.join(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"), "recordings")

    # ---------------------------------------------------------------- after-hooks
    def _after_handoff(self, res, schedule):
        d = res.get("dir")
        if not d:
            return res
        res["project_id"] = batch_id(d)
        posts = []
        if schedule and self.calendar is not None:
            for p in res.get("posts") or []:
                for plat in p.get("platforms") or []:
                    try:
                        posts.append(self.calendar.add(dict(item=res["project_id"], clip=res.get("clip"),
                                                            platform=plat, at=p["at"])))
                    except Exception as e:  # noqa: BLE001  (a clip the calendar cannot see yet: report, keep going)
                        posts.append(dict(error=str(e)[:200], platform=plat, at=p["at"]))
        res["calendar"] = posts
        return res

    def _after_ingest(self, res):
        if res.get("project_dir"):
            res["project_id"] = batch_id(os.path.join(res["project_dir"], "state"))
        if res.get("output") and res.get("dir"):         # target edit: the take is its own clip (an adopted work)
            from .works import clip_key
            res["item"] = batch_id(res["dir"])
            res["clip"] = clip_key(res["output"])
            if self.bus is not None:
                self.bus.publish("batches")
        return res

    # ---------------------------------------------------------------- inbox (only once Create was used)
    def inbox_items(self):
        if not self.used:
            return []
        t, cached = self._inbox_cache
        if time.time() - t < 5:
            return cached
        items = []
        try:
            view = self.call(["making"], timeout=60)
        except Exception:  # noqa: BLE001
            return cached
        import hashlib

        def key(*p):
            return hashlib.sha1("\0".join(map(str, p)).encode()).hexdigest()[:16]
        for r in view.get("rows") or []:
            proj = dict(id=None, name=r.get("title"), kind="create", thumb=None, type="aigc")
            href = f"#/create/e/{r['id']}"
            if r.get("pick"):
                items.append(dict(key=key(r["id"], "pick", r["pick"]), kind="create", group="choose", project=proj,
                                  code="create.pick-takes", params=dict(n=r["pick"], title=r.get("title") or ""),
                                  text=None, minutes=max(1, r["pick"]), source="create", href=href + "/takes",
                                  at=time.time()))
            for f in (r.get("make") or {}).get("failed") or []:
                items.append(dict(key=key(r["id"], "make", f["no"], f.get("code")), kind="create", group="other",
                                  project=proj, code=f.get("code") or "create.agent.failed",
                                  params={k: str(v) for k, v in (f.get("params") or {}).items()}, text=None,
                                  minutes=1, source="create", href=href + "/storyboard", at=time.time()))
            for w in (r.get("make") or {}).get("waiting") or []:
                items.append(dict(key=key(r["id"], "wait", w["no"]), kind="create", group="choose", project=proj,
                                  code=w.get("code") or "create.plugin.external",
                                  params={k: str(v) for k, v in (w.get("params") or {}).items()}, text=None,
                                  minutes=2, source="create", href=href + "/storyboard", at=time.time()))
            if r.get("paused"):
                items.append(dict(key=key(r["id"], "paused"), kind="create", group="spend", project=proj,
                                  code="create.hard-shots-failed", params=r["paused"].get("params") or {}, text=None,
                                  minutes=1, source="create", href=href + "/storyboard", at=time.time()))
        for a in view.get("alerts") or []:
            if a.get("code") == "create.unknown-charge":
                p = a.get("params") or {}
                items.append(dict(key=key(a.get("episode"), a.get("at")), kind="create", group="spend",
                                  project=dict(id=None, name=f"Ep. {a.get('episode_no')}", kind="create", thumb=None),
                                  code="create.unknown-charge", params=dict(provider=p.get("provider"),
                                                                            shots=", ".join(p.get("shots") or [])),
                                  text=None, minutes=1, source="create",
                                  href=f"#/create/s/{a.get('series')}/making", at=a.get("at")))
        for rec in self.recovered:
            items.append(dict(key=key("rec", rec.get("id")), kind="create", group="other",
                              project=dict(id=None, name=rec.get("id"), kind="create", thumb=None),
                              code="create.recording-recovered", params=dict(name=rec.get("id")), text=None,
                              minutes=1, source="create", href="#/create/record", at=time.time()))
        self._inbox_cache = (time.time(), items)
        return items

    # ---------------------------------------------------------------- routes
    def route(self, method, parts, query, body):
        b = body if isinstance(body, dict) else {}
        q = lambda k: (query.get(k) or [None])[0]  # noqa: E731
        p = parts
        if method == "GET":
            if p == ["formats"]:
                return self.call(["formats"])
            if p == ["providers"]:
                return self.call(["providers", "--detect"])
            if p == ["series"]:
                return self.call(["series", "list"])
            if len(p) == 2 and p[0] == "series":
                return self.call(["series", "show", _sid(p[1])])
            if len(p) == 2 and p[0] == "episodes":
                return self.call(["board", "show", _sid(p[1])])
            if len(p) == 3 and p[0] == "episodes" and p[2] == "estimate":
                stage = q("stage") or "finals"
                need(stage in STAGES, "stage: stills | animatic | drafts | finals")
                args = ["estimate", _sid(p[1]), "--stage", stage]
                only = q("only")
                if only:
                    args += ["--only", ",".join(_shot(x) for x in only.split(",")[:50])]
                return self.call(args)
            if len(p) == 3 and p[0] == "episodes" and p[2] == "prompts":
                return self.call(["prompts", _sid(p[1])])
            if p == ["runs"]:
                s = q("series")
                return self.call(["making"] + (["--series", _sid(s)] if s else []))
            if p == ["spend"]:
                s = q("series")
                return self.call(["spend"] + (["--series", _sid(s)] if s else []))
            if len(p) == 2 and p[0] == "jobs":
                return self.get_job(p[1])
            if p == ["plugins"]:
                lang = q("lang") or "en"
                need(lang in LANGS, "lang")
                return self.call(["plugins", "list", "--lang", lang])
        if method != "POST":
            raise KeyError("not found")
        if p == ["plan"]:
            args = ["plan"]
            if b.get("prompt"):
                args += ["--prompt", _text(b["prompt"], "prompt")]
            if b.get("format") is not None:
                need(b["format"] in FORMATS, "format: " + " | ".join(FORMATS))
                args += ["--format", b["format"]]
            need(b.get("prompt") or b.get("format"), "prompt or format required")
            if b.get("budget_cny") is not None:
                args += ["--budget", str(_money(b["budget_cny"], "budget_cny"))]
            if b.get("platforms"):
                pl = b["platforms"]
                need(isinstance(pl, list) and len(pl) <= 8 and all(isinstance(x, str) and PLATFORM_RE.match(x) for x in pl),
                     "platforms")
                args += ["--platforms", ",".join(pl)]
            if b.get("lang"):
                need(b["lang"] in ("en", "zh", "fr"), "lang")
                args += ["--lang", b["lang"]]
            if b.get("mode") is not None:
                need(b["mode"] in ("auto", "template"), "mode: auto | template")
                args += ["--mode", b["mode"]]
            return self.job("plan", args, limit=PLAN_LIMIT_S)
        if len(p) == 2 and p[0] == "plugins":
            need(PLUGIN_KEY_RE.match(p[1] or ""), "plugin: <kind>:<id>")
            out = None
            if "settings" in b:
                st = b["settings"]
                need(isinstance(st, dict) and len(json.dumps(st)) < 4000, "settings: an object")
                cmd = st.get("command")
                need(cmd is None or (isinstance(cmd, list) and 0 < len(cmd) <= 30 and
                                     all(isinstance(x, str) and 0 < len(x) < 500 and "\0" not in x for x in cmd)),
                     "settings.command: [argv...]")
                lanes = st.get("lanes")
                need(lanes is None or (isinstance(lanes, int) and 1 <= lanes <= 8), "settings.lanes: 1..8")
                out = self.call(["plugins", "set", p[1], "--settings-json", json.dumps(st)])
            if "enabled" in b:
                need(isinstance(b["enabled"], bool), "enabled: true | false")
                out = self.call(["plugins", "enable" if b["enabled"] else "disable", p[1]])
            need(out is not None, "enabled or settings")
            return out
        if p == ["import", "sniff"]:
            return self.call(["import", _abs(b.get("path"), "path"), "--sniff"])
        if p == ["import"]:
            args = ["import", _abs(b.get("path"), "path")]
            if b.get("importer"):
                need(PROVIDER_RE.match(str(b["importer"])), "importer")
                args += ["--importer", b["importer"]]
            if b.get("format"):
                need(b["format"] in FORMATS, "format")
                args += ["--format", b["format"]]
            if b.get("lang"):
                need(b["lang"] in LANGS, "lang")
                args += ["--lang", b["lang"]]
            return self.job("import", args, meta=dict(name=os.path.basename(args[1])), limit=300)
        if p == ["series"]:
            d = b.get("draft")
            need(isinstance(d, dict) and d.get("format") in FORMATS and isinstance(d.get("bible"), dict),
                 "draft: a plan result")
            raw = json.dumps(d, ensure_ascii=False)
            need(len(raw) < 200000, "draft too large")
            return self.call(["series", "new", "--draft-json", raw])
        if p == ["sample"]:
            lang = b.get("lang") or "en"
            need(lang in ("en", "zh", "fr"), "lang")
            return self.call(["sample", "--lang", lang], timeout=120)
        if len(p) == 3 and p[0] == "providers" and p[2] == "test":
            need(PROVIDER_RE.match(p[1]), "bad service id")
            rows = self.call(["providers", "--detect"]).get("providers") or []
            hit = next((x for x in rows if x.get("id") == p[1]), None)
            if not hit:
                raise KeyError("no such service")
            return dict(ok=bool(hit.get("ready")), code=hit.get("code"), params=hit.get("params") or {})
        if len(p) == 3 and p[0] == "series":
            sid = _sid(p[1])
            if p[2] == "bible":
                if b.get("patch") is not None:
                    need(isinstance(b["patch"], dict), "patch: object")
                    return self.call(["bible", "revise", sid, "--patch-json", json.dumps(b["patch"], ensure_ascii=False)])
                return self.job("bible", ["bible", "revise", sid, "--instruction", _text(b.get("instruction"), "instruction")])
            if p[2] == "ideas":
                n = b.get("n", 4)
                need(isinstance(n, int) and 1 <= n <= 8, "n: 1..8")
                return self.job("ideas", ["ideas", sid, "--n", str(n)])
            if p[2] == "episodes":
                ids = b.get("idea_ids")
                need(isinstance(ids, list) and 0 < len(ids) <= 10 and all(isinstance(i, str) and re.match(r"^i\d{1,3}$", i)
                                                                          for i in ids), "idea_ids: 1-10 ideas")
                return self.job("episodes", ["episodes", "add", sid, "--ideas", ",".join(ids)], meta=dict(series=sid))
            if p[2] == "settings":
                args = ["series", "set", sid]
                if "budget_cny" in b:
                    args += ["--budget", "none" if b["budget_cny"] is None else str(_money(b["budget_cny"], "budget_cny"))]
                return self.call(args)
        if len(p) >= 3 and p[0] == "episodes":
            eid = _sid(p[1])
            if len(p) == 4 and p[2] == "shots":
                src = b.get("source")
                need(isinstance(src, str) and SOURCE_RE.match(src), "source: cloud:<service>/<model> | manual:<site> | "
                                                                   "local:<runtime> | record | card | reuse:<ep>/<shot>")
                return self.call(["board", "set", eid, "--shot", _shot(p[3]), "--source", src])
            if p[2:] == ["route"]:
                args = ["board", "route", eid, "--instruction", _text(b.get("instruction"), "instruction", 500)]
                if b.get("apply") is True:
                    args.append("--apply")
                return self.call(args)
            if p[2:] == ["run"]:
                stage = b.get("stage")
                need(stage in STAGES, "stage: stills | animatic | drafts | finals")
                args = ["run", eid, "--stage", stage]
                only = b.get("only")
                if only is not None:
                    need(isinstance(only, list) and 0 < len(only) <= 50, "only: shot numbers")
                    args += ["--only", ",".join(_shot(x) for x in only)]
                if stage == "finals":
                    est, code, mx = b.get("estimate_id"), b.get("confirm_code"), b.get("max_cny")
                    if not (isinstance(est, str) and EST_RE.match(est) and isinstance(code, str) and CODE_RE.match(code)
                            and mx is not None):
                        raise Refused("create.confirm-required", {}, 409)
                    args += ["--estimate", est, "--confirm", code, "--max-cny", str(_money(mx, "max_cny"))]
                    if b.get("allow_unknown") is True:
                        args.append("--allow-unknown")
                    self.call(args + ["--check"])                 # 409 now, before any job starts
                    if b.get("hard_first") is False:
                        args.append("--no-early-stop")
                return self.job("run", args, meta=dict(episode=eid, stage=stage))
            if p[2:] == ["stop"]:
                return self.call(["stop", eid])
            if p[2:] == ["import-board"]:
                args = ["import", _abs(b.get("path"), "path"), "--into", eid]
                if b.get("importer"):
                    need(PROVIDER_RE.match(str(b["importer"])), "importer")
                    args += ["--importer", b["importer"]]
                return self.job("import", args, meta=dict(episode=eid), limit=300)
            if p[2:] == ["make"]:
                args = ["make", eid]
                only = b.get("only")
                if only is not None:
                    need(isinstance(only, list) and 0 < len(only) <= 300, "only: shot numbers")
                    args += ["--only", ",".join(_shot(x) for x in only)]
                if b.get("lanes") is not None:
                    need(isinstance(b["lanes"], int) and 1 <= b["lanes"] <= 8, "lanes: 1..8")
                    args += ["--lanes", str(b["lanes"])]
                return self.job("make", args, meta=dict(episode=eid))
            if len(p) == 4 and p[2] == "takes":
                take = b.get("take")
                need(isinstance(take, str) and 0 < len(take) < 4096 and "\0" not in take, "take")
                return self.call(["takes", "pick", eid, "--shot", _shot(p[3]), "--take", take])
            if p[2:] == ["import"]:
                files = b.get("files")
                need(isinstance(files, list) and 0 < len(files) <= 50, "files: 1-50 paths")
                return self.call(["takes", "import", eid, *[_abs(f, "file") for f in files]])
            if p[2:] == ["handoff"]:
                langs = b.get("languages") or []
                need(isinstance(langs, list) and len(langs) <= 3 and all(x in LANGS for x in langs), "languages: zh en fr")
                schedule = b.get("schedule", True) is not False
                args = ["handoff", eid] + (["--languages", ",".join(langs)] if langs else [])
                return self.job("handoff", args, meta=dict(episode=eid),
                                after=lambda r: self._after_handoff(r, schedule))
        if p == ["record", "ingest"]:
            d = _abs(b.get("session_dir"), "session_dir")
            root = os.path.realpath(self.recordings_root())
            need(os.path.realpath(d).startswith(root + os.sep), "session_dir: a recorder session")
            tgt = b.get("target") or "project:talkinghead"
            need(tgt in ("project:talkinghead", "assembled", "edit") or re.match(r"^shot:[a-z0-9][a-z0-9-]{0,47}/\d{2,3}$", tgt), "target")
            args = ["record", "ingest", d, "--target", tgt]
            if b.get("series"):
                args += ["--series", _sid(b["series"])]
            return self.job("ingest", args, meta=dict(session=os.path.basename(d)), after=self._after_ingest)
        if p == ["record", "recover"]:
            res = self.call(["record", "recover"], timeout=600)
            self.recovered += res.get("recovered") or []
            return res
        if p == ["spend", "cap"]:
            return self.call(["spend", "--set-cap", str(_money(b.get("cap_cny"), "cap_cny"))])
        raise KeyError("not found")
