"""Intake: one sentence + dropped files -> an AI plan card -> projects (``python -m vstudio.intake``, the engine's
references/INTAKE.md). Plans are slow (inventory + ASR + a model call), so the desk runs them as background jobs:

  start(prompt, inputs, platforms, lang)  -> {id}   GET -> {id, state running|done|error, step, progress, plan, error,
                                                          prompt, inputs, lang}
  revise(id, prompt, lang) -> same job, state running again (the plan keeps its revisions)
``lang``: the desk's UI language (en | zh-CN | fr): the planner writes the card's questions, risks and reasons in it
(``--ui-lang``), whatever language the request, the materials or the platforms are in.
  apply(id, plan?, run)  -> {projects [{dir, name, recipe}], series}; ``run`` starts each pilot in the background

Projects from Home (``mode``): the request is a project the moment it is sent - Home is free for the next one and
All projects lists it (``open()``: every request not made into projects yet, newest first) while it plans. ``mode``
``autopilot`` (the desk's default): when the plan is ready it is applied at once (``vstudio.intake apply
--autopilot``) and every project runs whole on autopilot (no pilot, no plan to confirm; the engine decides each
checkpoint and records why). ``ask``: the plan waits in All projects for her Start (today's plan card, then a pilot of
one). A request's job record (``<id>.job.json``: state, step, mode, error, applied) survives a restart; one that was
planning when the desk quit is a failure she can try again. ``discard(id)``: she drops a plan (nothing was made).

Real engine: ``vstudio.intake plan|revise|apply --json`` (plan JSON kept in ``<DESK_DATA_DIR>/intake/<id>.json``),
pilots via ``vstudio.project run --dir D --pilot 1``. While a plan / revision runs, the engine's ``--json-events``
become the job's ``progress`` (what the card shows instead of a spinner): {stage scan | probe | listen | faces |
transcribe | model | write, file, i, n, done_s, total_s, cached, provider, files, reused, seen [stages so far], at}. An
engine without ``--json-events`` plans as before, with no progress. When the engine's intake does not answer its probe, a plan /
revise / apply fails with ``intake.unavailable`` and the reason (the card offers Try again, which probes again):
nothing is ever planned, applied or run by anything else. (The desk's tests use the in-memory planner in
engine/tests/fixtures/desk_mock.)
"""
import hashlib
import os
import re
import threading
import time

from .common import BadRequest, need, read_json, write_json

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
TEXT = {".pdf", ".docx", ".pptx", ".md", ".txt", ".srt", ".vtt", ".ass", ".json"}

# in display order (international first, then Chinese): the plan lists platforms in this order
PLATFORMS = [("tiktok", "tiktok", "TikTok"), ("youtube|油管", "youtube-shorts", "YouTube"),
             ("小红书|xiaohongshu|rednote", "xiaohongshu", "小红书"), ("抖音|douyin", "douyin", "抖音"),
             ("视频号|channels", "shipinhao", "视频号"), ("b站|B站|bilibili", "bilibili", "B 站")]
# the desk's UI languages -> the planner's ``--ui-lang``
UI_LANGS = {"en": "en", "zh-CN": "zh", "zh": "zh", "fr": "fr"}


def ui_lang(lang):
    """A UI language from the request body -> the planner's code (None: the planner follows the request's)."""
    need(lang is None or lang in UI_LANGS, f"lang: {' | '.join(UI_LANGS)}")
    return UI_LANGS.get(lang) if lang else None


def material(path, probe=None):
    ext = os.path.splitext(path)[1].lower()
    kind = "video" if ext in VIDEO else "audio" if ext in AUDIO else "image" if ext in IMAGE else \
        "text" if ext in TEXT else "folder" if os.path.isdir(path) else "file"
    m = dict(path=path, name=os.path.basename(path.rstrip(os.sep)), kind=kind, ext=ext)
    if kind == "video" and probe:
        m.update({k: v for k, v in (probe(path) or {}).items() if v})
    if kind == "folder":
        n = 0
        for _dp, _dns, fns in os.walk(path):
            n += len([f for f in fns if not f.startswith(".")])
            if n > 2000:
                break
        m["files"] = n
    name = m["name"].lower()
    m["role"] = ("finished-edit" if re.search(r"final|成片|export", name) else "lecture" if re.search(r"课|lecture|lesson", name)
                 else "call" if re.search(r"zoom|meet|call|播客", name) else "talking-head" if kind == "video"
                 else "photo" if kind == "image" else "doc" if kind == "text" else kind)
    return m


def _slug(name, i):
    s = re.sub(r"[^\w一-鿿-]+", "-", name).strip("-")[:40]
    return f"{i + 1:02d}-{s or 'project'}"


# Checkpoints a plan from the desk answers with its default (vstudio.intake --auto): the composer promises "only asks
# you when something needs a human", so the opening (default: none), the filler cuts (the safe ones) and the cover
# (the suggested frame) are not questions unless her request is about them. All three can be changed afterwards on
# the clip. Review before publishing always stays hers.
AUTO = ("hook", "filler", "cover")
_ASKS_FOR = {"hook": r"hook|opening|cold open|teaser|开场|开头|高光预告|预告",
             "cover": r"cover|thumbnail|封面|缩略图",
             "filler": r"(confirm|确认).{0,12}(filler|口癖|气口)"}


def auto_checkpoints(prompt):
    """The checkpoints answered with their default for this request (``AUTO`` minus what she asked about)."""
    return [c for c in AUTO if not re.search(_ASKS_FOR[c], prompt or "", re.I)]


class Unavailable(RuntimeError):
    """The engine's intake (``python -m vstudio.intake``) did not answer: nothing is planned or applied."""


class Intake:
    def __init__(self, data_dir, bus, runner=None, mode="real", probe=None, defaults=None, sample=None):
        self.dir = os.path.join(data_dir, "intake")
        self.bus, self.runner, self.mode, self.probe = bus, runner, mode, probe
        self.sample = sample
        self.defaults = defaults or (lambda: {})
        self.jobs = {}
        self._procs = {}               # plan id -> running engine children (stop kills them)
        self._lock = threading.Lock()
        self._real = None
        self._why = None
        self._streams = None           # the engine's plan / revise take --json-events (probed once)
        self._load_jobs()

    JOB_KEYS = ("id", "state", "step", "prompt", "inputs", "error", "error_code", "error_provider", "started",
                "seconds", "platforms", "lang", "mode", "sample_name", "applied", "discarded", "failed_apply",
                "failed_revise", "name")

    def _job_path(self, pid):
        return os.path.join(self.dir, f"{pid}.job.json")

    def _load_jobs(self):
        """Requests from Home (``mode`` set) live on across a restart: All projects keeps listing the open ones."""
        if not os.path.isdir(self.dir):
            return
        cut = time.time() - 30 * 86400
        for f in os.listdir(self.dir):
            if not f.endswith(".job.json"):
                continue
            j = read_json(os.path.join(self.dir, f), None)
            if not isinstance(j, dict) or not re.match(r"^[0-9a-f]{12}$", str(j.get("id") or "")) or \
                    (j.get("started") or 0) < cut:
                continue
            if j.get("state") == "running":    # the desk quit while it planned / applied: say so, offer Try again
                j.update(state="error", error="the app was closed while this was being planned", error_code="stopped")
            self.jobs[j["id"]] = j

    def real(self):
        """The engine's intake answers its probe (``vstudio.intake --help`` lists plan / apply). Probed once; a
        failed probe is probed again on the next Try again (``_need_engine``)."""
        if self._real is None:
            ok, why = False, None
            if self.mode == "real" and self.runner is not None:
                try:
                    txt = self.runner.sibling("vstudio.intake").text(["--help"])
                    ok = "plan" in txt and "apply" in txt and "No module named" not in txt
                    why = None if ok else (txt.strip().splitlines() or ["no plan / apply command"])[-1]
                except Exception as e:  # noqa: BLE001
                    why = str(e)
            else:
                why = "no engine"
            self._real, self._why = ok, why
        return self._real

    def _need_engine(self):
        if not self.real():
            self._real = self._streams = None       # a hiccup: the next try probes again
            raise Unavailable(f"the planning engine (vstudio.intake) did not answer: {self._why or 'unknown'}")

    def streams(self):
        """The engine's ``plan`` reports progress (``--json-events``); an older engine plans without it."""
        if self._streams is None:
            try:
                self._streams = "--json-events" in self.runner.sibling("vstudio.intake").text(["plan", "--help"])
            except Exception:  # noqa: BLE001
                self._streams = False
        return self._streams

    def _run(self, pid, args, timeout):
        """``vstudio.intake <args> --json`` -> its plan document; progress events go to the job as they come."""
        r = self.runner.sibling("vstudio.intake")
        track = self._procs.setdefault(pid, [])
        if self.streams():
            done = r.events([*args, "--json-events"], lambda ev: self._progress(pid, ev), timeout=timeout, track=track)
            return done.get("plan") or {}
        return r.json(args, timeout=timeout, track=track)

    def _progress(self, pid, ev):
        """One engine event -> the job's ``progress``: a ``stage`` event says what it is doing now (the previous
        step's details go), a ``progress`` event moves the current step's counter."""
        with self._lock:
            cur = dict((self.jobs.get(pid) or {}).get("progress") or {})
        stage = ev.get("stage")
        if not stage:
            return
        if ev.get("event") == "progress":
            if stage != cur.get("stage"):
                return
            cur.update({k: ev[k] for k in ("done_s", "total_s") if ev.get(k) is not None})
        elif ev.get("event") == "stage":
            seen = list(cur.get("seen") or [])
            if stage not in seen:
                seen.append(stage)
            files = ev.get("files") if stage == "scan" and ev.get("files") is not None else cur.get("files")
            reused = cur.get("reused") or bool(stage == "transcribe" and ev.get("cached"))
            cur = {k: ev.get(k) for k in ("stage", "file", "i", "n", "kind", "done_s", "total_s", "cached",
                                          "provider", "model") if ev.get(k) is not None}
            cur["seen"] = seen
            if files is not None:
                cur["files"] = files
            if reused:
                cur["reused"] = True
        else:
            return
        cur["at"] = time.time()
        self._set(pid, progress=cur)

    def _path(self, pid):
        return os.path.join(self.dir, f"{pid}.json")

    def _set(self, pid, **kw):
        with self._lock:
            if (self.jobs.get(pid) or {}).get("state") == "stopped" and kw.get("state") in ("done", "error"):
                return dict(self.jobs[pid])          # stopped by her: a late answer / the kill's error is dropped
            self.jobs[pid] = dict(self.jobs.get(pid) or {}, **kw)
            job = dict(self.jobs[pid])
        if job.get("mode") and set(kw) - {"progress"}:
            os.makedirs(self.dir, exist_ok=True)
            write_json(self._job_path(pid), {k: job.get(k) for k in self.JOB_KEYS if job.get(k) is not None})
        if self.bus:
            self.bus.publish("intake", id=pid, state=job.get("state"))
        return job

    def get(self, pid):
        need(re.match(r"^[0-9a-f]{12}$", pid or ""), "bad plan id")
        j = self.jobs.get(pid)
        if not j:
            plan = read_json(self._path(pid), None)
            if not plan:
                raise KeyError(f"no plan {pid}")
            j = dict(id=pid, state="done", plan=plan, prompt=plan.get("prompt"), inputs=plan.get("analysis", {}).get("inputs"))
        elif j.get("plan") is None and j.get("state") != "running":
            plan = read_json(self._path(pid), None)       # a request read back after a restart: its plan file
            if plan:
                with self._lock:
                    self.jobs[pid] = j = dict(j, plan=plan)
        return dict(j)

    def recent(self, n=8):
        """Recent prompts (newest first) for the composer's history."""
        out = []
        if os.path.isdir(self.dir):
            files = sorted((f for f in os.listdir(self.dir) if f.endswith(".json")),
                           key=lambda f: -os.path.getmtime(os.path.join(self.dir, f)))
            for f in files[:n * 2]:
                p = read_json(os.path.join(self.dir, f), None) or {}
                if p.get("prompt") and p["prompt"] not in [x["prompt"] for x in out]:
                    out.append(dict(id=p.get("id"), prompt=p["prompt"], at=p.get("created")))
                if len(out) >= n:
                    break
        return out

    def open(self):
        """Requests from Home that are not projects yet (planning, a plan waiting for her Start, a failure), newest
        first: what All projects lists above the projects."""
        out = []
        for j in list(self.jobs.values()):
            if not j.get("mode") or j.get("applied") or j.get("discarded") or j.get("state") == "stopped":
                continue
            plan = j.get("plan") or {}
            names = [p.get("name") for p in plan.get("projects") or [] if p.get("name")]
            out.append(dict(id=j["id"], state=j.get("state"), step=j.get("step"), mode=j["mode"],
                            prompt=j.get("prompt"), inputs=j.get("inputs") or [], started=j.get("started"),
                            progress=j.get("progress"), error_code=j.get("error_code"), error=j.get("error"),
                            name=j.get("name") or (names[0] if names else None), projects=len(names) or None,
                            failed_apply=bool(j.get("failed_apply"))))
        out.sort(key=lambda x: -(x.get("started") or 0))
        return dict(items=out)

    def inbox_items(self):
        """For the Inbox: a plan that waits for her Start (ask me first) and a request that failed - the only two
        moments a request from Home needs her before it is a project."""
        out = []
        for r in self.open()["items"]:
            if r["state"] not in ("done", "error"):
                continue
            ready = r["state"] == "done"
            out.append(dict(key=f"plan-{r['id']}-{r['state']}", kind="plan" if ready else "failed",
                            group="choose" if ready else "other",
                            project=dict(id=None, name=r.get("name") or (r.get("prompt") or "")[:60], kind="plan",
                                         thumb=None, type="other"),
                            code="inbox.planReady" if ready else "inbox.planFailed",
                            params=dict(name=r.get("name") or (r.get("prompt") or "")[:60]), text=None, minutes=1,
                            source="intake", href=f"#/projects?sel={r['id']}", at=r.get("started") or time.time()))
        return out

    def discard(self, pid):
        """She drops a request that is not a project yet (a plan she does not want, a failure): it leaves All
        projects; nothing was made, nothing is deleted."""
        j = self.get(pid)
        need(not j.get("applied"), "this request is already a project")
        if j.get("state") == "running":
            self.stop(pid)
        self._set(pid, discarded=True)
        if self.bus:
            self.bus.publish("batches")
        return dict(ok=True, id=pid)

    # ---------------------------------------------------------- plan / revise
    def start(self, prompt, inputs, platforms=None, lang=None, mode=None, sample_name=None):
        """``platforms``: the composer's platform chip (used when the request names none); ``lang``: the UI's
        language, the one the card's questions are written in. ``mode``: autopilot | ask (a project from Home, see
        the module doc; None: a plan card of its own, e.g. the week plan's); ``sample_name``: the built-in sample's
        projects are named so (labelled and deletable)."""
        lang = ui_lang(lang)
        need(mode in (None, "autopilot", "ask"), "mode: autopilot | ask")
        need(sample_name is None or (isinstance(sample_name, str) and 0 < len(sample_name) <= 80), "sample_name")
        need(platforms is None or (isinstance(platforms, list) and len(platforms) <= 20 and
                                   all(isinstance(p, str) and re.match(r"^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$", p)
                                       for p in platforms)), "platforms: platform ids")
        pid = hashlib.sha1(f"{prompt}\0{inputs}\0{time.time()}".encode()).hexdigest()[:12]
        self._set(pid, id=pid, state="running", step="analyze", prompt=prompt, inputs=inputs, plan=None, error=None,
                  started=time.time(), op_started=time.time(), seconds=None, platforms=platforms or None,
                  progress=None, lang=lang, mode=mode, sample_name=sample_name)
        if mode and self.bus:
            self.bus.publish("batches")
        threading.Thread(target=self._plan, args=(pid, prompt, inputs), daemon=True).start()
        return dict(id=pid)

    def _platform_hint(self, pid, prompt):
        """The chip's platforms as words the planner reads, when the request itself names no platform."""
        plats = (self.jobs.get(pid) or {}).get("platforms") or []
        if not plats or any(re.search(pat, prompt, re.I) for pat, _p, _z in PLATFORMS):
            return prompt
        names = [next((zh for _pt, p2, zh in PLATFORMS if p2 == p.split(":")[0]), p.split(":")[0]) for p in plats]
        return f"{prompt}\n（发布到：{'、'.join(dict.fromkeys(names))}）"

    def _plan(self, pid, prompt, inputs):
        try:
            self._need_engine()
            plan = self._engine_plan(pid, prompt, inputs)
        except Exception as e:  # noqa: BLE001
            self._fail(pid, e)
            return
        names = [p.get("name") for p in plan.get("projects") or [] if p.get("name")]
        auto = (self.jobs.get(pid) or {}).get("mode") == "autopilot"
        self._set(pid, state="running" if auto else "done", step="apply" if auto else "done", plan=plan,
                  seconds=self._took(pid), name=names[0] if names else None)
        if auto:
            self._auto_apply(pid)
        elif self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")

    def _auto_apply(self, pid):
        """Autopilot: the plan is made into its projects and each runs whole, no Start to press."""
        if (self.jobs.get(pid) or {}).get("state") == "stopped":
            return
        try:
            self.apply(pid, run=True)
            self._set(pid, state="done", step="done", failed_apply=None)
        except Exception as e:  # noqa: BLE001
            self._set(pid, failed_apply=True)
            self._fail(pid, e)

    def _engine_plan(self, pid, prompt, inputs):
        out = self._path(pid)
        os.makedirs(self.dir, exist_ok=True)
        args = ["plan", "--prompt", self._platform_hint(pid, prompt), "--out", out, "--json"]
        auto = auto_checkpoints(prompt)
        if auto:
            args += ["--auto", ",".join(auto)]
        if inputs:
            args += ["--inputs", *inputs]
        args += self._lang_args(pid)
        self._set(pid, step="plan")
        plan = self._run(pid, args, timeout=1800)
        plan["id"] = plan.get("id") or pid
        plan["desk_id"] = pid
        write_json(out, plan)
        return plan

    def _lang_args(self, pid):
        lang = (self.jobs.get(pid) or {}).get("lang")
        return ["--ui-lang", lang] if lang else []

    def retry(self, pid):
        """「再试一次」 on a failed plan card: the same request (plan, or the revision that failed) again."""
        j = self.get(pid)
        need(j.get("state") == "error", "only a failed plan can be tried again")
        if j.get("failed_revise"):
            return self.revise(pid, j["failed_revise"])
        if j.get("failed_apply") and j.get("plan"):
            self._set(pid, state="running", step="apply", error=None, error_code=None, error_provider=None)
            threading.Thread(target=self._auto_apply, args=(pid,), daemon=True).start()
            return dict(id=pid)
        self._set(pid, state="running", step="analyze", error=None, error_code=None, error_provider=None,
                  op_started=time.time(), seconds=None, progress=None)
        threading.Thread(target=self._plan, args=(pid, j.get("prompt") or "", j.get("inputs") or []),
                         daemon=True).start()
        return dict(id=pid)

    def revise(self, pid, prompt, lang=None):
        """``lang``: as ``start`` (default: the language the plan was made in)."""
        lang = ui_lang(lang)
        j = self.get(pid)
        need(j.get("plan"), "the plan is not ready yet")
        if lang:
            self._set(pid, lang=lang)
        self._set(pid, state="running", step="revise", error=None, error_code=None, error_provider=None,
                  failed_revise=None, op_started=time.time(), seconds=None, progress=None)

        def go():
            try:
                self._need_engine()
                p = self._engine_revise(pid, j["plan"], prompt)
                self._set(pid, state="done", step="done", plan=p, seconds=self._took(pid))
            except Exception as e:  # noqa: BLE001
                self._set(pid, failed_revise=prompt)
                self._fail(pid, e)
        threading.Thread(target=go, daemon=True).start()
        return dict(id=pid)

    def _engine_revise(self, pid, plan, prompt):
        return self._run(pid, ["revise", "--plan", self._path(pid), "--prompt", prompt, "--in-place", "--json",
                               *self._lang_args(pid)], timeout=900)

    def _took(self, pid):
        """Seconds the plan / revision really took (reading the files and the AI call), for the card."""
        j = self.jobs.get(pid) or {}
        t0 = j.get("op_started") or j.get("started")
        return round(time.time() - t0, 1) if t0 else None

    def _fail(self, pid, e):
        """A plain reason code for the card (pilot.classify) and the error without paths."""
        from . import pilot
        txt = str(e)
        code = "intake" if isinstance(e, Unavailable) else pilot.classify(txt)
        j = self._set(pid, state="error", error=pilot.scrub(txt, 500), error_code=code,
                      error_provider=None if isinstance(e, Unavailable) else pilot.provider_of(txt))
        if j.get("mode") and self.bus:              # a request from Home: All projects and the Inbox say so
            self.bus.publish("batches")
            self.bus.publish("inbox")

    def stop(self, pid):
        """「停止」 while planning / revising: ends the engine (and the model CLI it started); the composer is back."""
        from .caps import kill_tracked
        j = self.get(pid)
        killed = kill_tracked(self._procs.get(pid) or [])
        if j.get("state") == "running":
            self._set(pid, state="stopped", step="stopped", error=None)
        return dict(ok=True, id=pid, killed=killed)

    # ---------------------------------------------------------- apply (+ pilot)
    def apply(self, pid, plan=None, run=True, out_root=None):
        """``run``: start the projects (on autopilot when the request was sent that way, else a pilot of one)."""
        j = self.get(pid)
        need(j.get("plan") or plan, "the plan is not ready yet")
        need(not j.get("applied"), "this plan is already made into projects")
        if plan is None and j.get("sample_name"):     # the sample's projects carry the sample's name
            src = j["plan"]
            many = len(src.get("projects") or []) > 1
            plan = dict(src, projects=[dict(p, name=f"{j['sample_name']} {k + 1}" if many else j["sample_name"])
                                       for k, p in enumerate(src.get("projects") or [])])
        if plan is not None:                       # the creator edited rows / params on the card
            need(isinstance(plan, dict) and plan.get("kind") == "vstudio.intake.plan" and isinstance(plan.get("projects"), list),
                 "plan: a vstudio.intake.plan document")
            write_json(self._path(pid), plan)
        plan = plan or j["plan"]
        home = os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"))
        out_root = out_root or os.path.join(home, "projects", pid)
        try:
            self._need_engine()
        except Unavailable as e:
            raise BadRequest(f"{e}. Nothing was made; try again.") from e
        projects = self._engine_apply(pid, plan, out_root, run, autopilot=j.get("mode") == "autopilot")
        if self.sample is not None and self.sample.uses_sample(j.get("inputs")):
            self.sample.mark([p["dir"] for p in projects])
        self._set(pid, applied=projects)
        if self.bus:
            self.bus.publish("batches")
        return dict(ok=True, projects=projects, series=plan.get("series"))

    def _engine_apply(self, pid, plan, out_root, run, autopilot=False):
        doc = self.runner.sibling("vstudio.intake").json(["apply", "--plan", self._path(pid), "--out", out_root,
                                                          "--json", *(["--autopilot"] if autopilot else [])],
                                                         timeout=900)
        projects = [dict(dir=p.get("dir"), name=p.get("name"), recipe=p.get("recipe"))
                    for p in doc.get("projects") or [] if isinstance(p, dict)]
        if run:
            lang = (self.jobs.get(pid) or {}).get("lang")
            for p in projects:
                if p["dir"]:
                    self._spawn_pilot(p["dir"], autopilot=autopilot, lang=lang)
        return projects

    def _spawn_pilot(self, d, provider=None, autopilot=False, lang=None):
        """The project's first run: on autopilot the whole project, else a pilot of one (``pilot.run_args``)."""
        from . import pilot
        pilot.spawn(self.runner.python, self.runner.env, d, provider=provider, bus=self.bus,
                    args=pilot.run_args(self.runner.python, d, autopilot, lang))

    def retry_pilot(self, d, provider=None):
        """「换 Codex 重试」/「重试」 after a failed pilot: the same run, every model task on ``provider``."""
        from . import pilot
        need(provider is None or provider in pilot.PROVIDERS, f"provider: {' | '.join(pilot.PROVIDERS)}")
        need(os.path.isdir(d), "no such project folder")
        try:
            self._need_engine()
        except Unavailable as e:
            raise BadRequest(f"{e}. Nothing was run; try again.") from e
        self._spawn_pilot(d, provider)
        if self.bus:
            self.bus.publish("batches")
            self.bus.publish("inbox")
        return dict(ok=True, provider=provider)
