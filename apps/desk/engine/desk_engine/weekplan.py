"""「这周的素材 → 一周的帖子」: one drop (a folder or several recordings) -> a week of scheduled posts.

Nothing new underneath: the existing pieces run one after the other, and this module only remembers where she is.

  planning   intake.start(words, inputs)            the plan card's planner (vstudio.intake plan)
  ready      the plan + estimate are back            she reads it; 「做这周的片子」 = run
  making     intake.apply(run=False) + a full run    every clip (not only the pilot), checkpoints answered with their
                                                     defaults (``vstudio.project run --auto all``)
  review     the run parked at a "needs you" step    the publish check (each clip approved before it goes out) is
                                                     never auto-answered: she approves in the review / Inbox, then
                                                     the project finishes and the week is laid out
  preview    calendar.plan(platform_defaults)        the clips laid out over the week as a preview (dashed cards on
                                                     the 发布 board); nothing is written
  scheduled  calendar.add_many(drafts)               one undo (the board's own undo: unschedule the ids)
  failed | dismissed

Her words do double duty: "weekdays 8pm, Xiaohongshu and Shorts" names the platforms the plan makes versions for
and the posting rule (schedule_text.parse); whatever the words leave open comes from the platform's default rule
and the account's usual time. Store: ``<DESK_DATA_DIR>/weekplans/<id>.json``.
"""
import hashlib
import json
import os
import re
import threading
import time

from . import schedule_text
from .common import need, read_json, write_json

ID_RE = re.compile(r"^[0-9a-f]{12}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
PLATFORM_RE = re.compile(r"^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$")
LIVE = ("planning", "ready", "making", "review", "preview")
DONE = ("done", "delivered", "packaged")

# the request when she only drops files (the planner reads it; the UI shows it in her language)
DEFAULT_WORDS = {"en": "Make this week's posts from these recordings", "zh-CN": "把这些素材做成这周要发的帖子",
                 "fr": "Fais les publications de la semaine avec ces enregistrements"}


def _want(rule, platforms):
    """How many clips a week of posts needs: the posting days x posts a day (the defaults when she says nothing)."""
    if rule and rule.get("days") is not None:
        days = rule["days"]
    else:
        days = sorted(set().union(*[schedule_text.default_rule(p)["days"] for p in platforms])) if platforms else range(7)
    return max(1, min(14, len(list(days)) * int((rule or {}).get("per_day") or 1)))


class WeekPlans:
    def __init__(self, data_dir, bus, intake, calendar, history, runner=None, spawn=None):
        """``runner``: the engine CLI runner (None when the engine is not available: making clips is refused).
        ``spawn``: how a run is started (pilot.spawn: detached, logged to the project's desk-pilot.* files)."""
        from . import pilot
        self.dir = os.path.join(data_dir, "weekplans")
        self.bus, self.intake, self.calendar, self.history = bus, intake, calendar, history
        self.runner = runner
        self._spawn = spawn or pilot.spawn
        self._checked = {}                       # project dir -> when its pending checks were last asked
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ store
    def _path(self, wid):
        need(isinstance(wid, str) and ID_RE.match(wid), "bad week plan id")
        return os.path.join(self.dir, f"{wid}.json")

    def _load(self, wid):
        rec = read_json(self._path(wid), None)
        if not isinstance(rec, dict):
            raise KeyError(f"no week plan {wid}")
        return rec

    def _save(self, rec):
        rec["updated"] = time.time()
        write_json(self._path(rec["id"]), rec)
        if self.bus:
            self.bus.publish("weekplan", id=rec["id"], state=rec["state"])
        return rec

    # ------------------------------------------------------------------ start
    def start(self, b):
        need(isinstance(b, dict), "body must be an object")
        inputs = b.get("inputs")
        need(isinstance(inputs, list) and 0 < len(inputs) <= 200, "inputs: the folder or files to use")
        text = b.get("text") or ""
        need(isinstance(text, str) and len(text) <= 300, "text: up to 300 chars")
        for k in ("start", "today"):
            need(b.get(k) is None or (isinstance(b[k], str) and DAY_RE.match(b[k])), f"{k}: YYYY-MM-DD")
        pfs = b.get("platforms") or []
        need(isinstance(pfs, list) and len(pfs) <= 12 and all(isinstance(p, str) and PLATFORM_RE.match(p) for p in pfs),
             "platforms: [platform id]")
        times = b.get("times") or {}
        need(isinstance(times, dict) and all(isinstance(v, str) and HM_RE.match(v) for v in times.values()),
             "times: {platform: HH:MM}")
        lang = b.get("lang") if b.get("lang") in DEFAULT_WORDS else "en"
        rule = schedule_text.parse(text) if text.strip() else None
        plats = (rule or {}).get("platforms") or [p.split(":")[0] for p in pfs] or ["xiaohongshu"]
        want = _want(rule, plats)
        words = text.strip() or DEFAULT_WORDS[lang]
        # the planner reads one extra line: a week's worth of standalone clips (it still decides what is in them)
        prompt = f"{words}\n（一周的发布量：切成 {want} 条能单独发的短视频切片）"
        iid = self.intake.start(prompt, inputs, [f"{p}:vertical" if p == "xiaohongshu" else p for p in plats],
                                lang)["id"]
        wid = hashlib.sha1(f"{iid}{time.time()}{os.urandom(4).hex()}".encode()).hexdigest()[:12]
        rec = dict(id=wid, intake=iid, text=text.strip(), words=words, rule=rule, platforms=plats, times=times,
                   start=b.get("start"), today=b.get("today"), inputs=len(inputs), want=want, state="planning",
                   created=time.time(), projects=[], preview=None, scheduled=[], error=None)
        os.makedirs(self.dir, exist_ok=True)
        return self._view(self._save(rec))

    # ------------------------------------------------------------------ read (and move on when a step finished)
    def get(self, wid):
        with self._lock:
            rec = self._advance(self._load(wid))
        return self._view(rec)

    def active(self):
        """Week plans still going (newest first): Home and 发布 pick them up again after a restart."""
        out = []
        if os.path.isdir(self.dir):
            for f in sorted(os.listdir(self.dir)):
                if f.endswith(".json") and ID_RE.match(f[:-5]):
                    rec = read_json(os.path.join(self.dir, f), None)
                    if isinstance(rec, dict) and rec.get("state") in LIVE + ("failed",):
                        out.append(rec["id"])
        recs = []
        for wid in out:
            try:
                recs.append(self.get(wid))
            except (KeyError, OSError):
                continue
        return dict(plans=sorted(recs, key=lambda r: -(r.get("created") or 0)))

    def _view(self, rec):
        v = {k: rec.get(k) for k in ("id", "intake", "text", "words", "rule", "platforms", "times", "start", "today",
                                     "inputs", "want", "state", "created", "updated", "projects", "preview",
                                     "scheduled", "error", "error_code", "progress", "failed", "review")}
        v["rules"] = self._rules(rec)
        if rec["state"] in ("planning", "ready"):
            j = self.intake.get(rec["intake"])
            v["plan"] = j.get("plan")
            v["step"] = j.get("step")
        return v

    @staticmethod
    def _rules(rec):
        """What each platform will get: her words, else the account's usual time, else the platform default."""
        rule = rec.get("rule") or {}
        out = []
        for pf in rec.get("platforms") or []:
            d = schedule_text.default_rule(pf)
            out.append(dict(platform=pf, days=rule.get("days") if rule.get("days") is not None else d["days"],
                            time=rule.get("time") or (rec.get("times") or {}).get(pf) or d["time"],
                            per_day=int(rule.get("per_day") or 1)))
        return out

    def _advance(self, rec):
        st = rec["state"]
        if st == "planning":
            try:
                j = self.intake.get(rec["intake"])
            except KeyError:
                return self._save(dict(rec, state="failed", error_code="unknown", error="plan lost"))
            if j.get("state") == "done" and j.get("plan"):
                return self._save(dict(rec, state="ready"))
            if j.get("state") == "error":
                return self._save(dict(rec, state="failed", error_code=j.get("error_code") or "unknown",
                                       error=j.get("error")))
            if j.get("state") == "stopped":
                return self._save(dict(rec, state="dismissed"))
        elif st in ("making", "review"):
            rows = self._project_rows(rec)
            if not rows:
                return rec
            finished = [r for r in rows if r["state"] in ("done", "failed")]
            prog = round(sum(r["progress"] for r in rows) / len(rows), 2)
            if prog != rec.get("progress"):
                rec = dict(rec, progress=prog)
            review = [dict(item=r["item"], name=r["name"], dir=r["dir"]) for r in rows if r["state"] == "review"]
            if review and not [r for r in rows if r["state"] == "running"]:
                if self._resume_answered(review):
                    return self._save(dict(rec, state="making", review=[]))   # all checked: the run finishes
                if st != "review" or review != rec.get("review"):
                    return self._save(dict(rec, state="review", review=review))
                return rec
            if st == "review" and [r for r in rows if r["state"] == "running"]:
                return self._save(dict(rec, state="making", review=[]))     # approved: the run goes on
            if len(finished) == len(rows):
                failed = [r for r in rows if r["state"] == "failed"]
                rec = dict(rec, failed=[dict(item=r["item"], name=r["name"], failure=r.get("failure")) for r in failed])
                if len(failed) == len(rows):
                    f = (failed[0].get("failure") or {})
                    return self._save(dict(rec, state="failed", error_code=f.get("code") or "unknown",
                                           error=f.get("error")))
                return self._save(self._lay_out(dict(rec, state="preview")))
            if rec.get("progress") != prog:
                return self._save(rec)
        return rec

    def _project_rows(self, rec):
        """The projects this week plan made, as the history sees them -> [{item, name, state, progress, failure}]."""
        dirs = {os.path.realpath(p["dir"]): p for p in rec.get("projects") or [] if p.get("dir")}
        if not dirs:
            return []
        out = []
        try:
            items = self.history.list()["items"]
        except Exception:  # noqa: BLE001
            return []
        for e in items:
            real = os.path.realpath(e.get("dir") or "")
            if real not in dirs:
                continue
            live = e.get("live") or {}
            if e.get("status") == "failed" or live.get("state") == "failed":
                state, prog = "failed", 1.0
            elif live.get("state") == "waiting" and live.get("needs_you") and not e.get("pilot"):
                state, prog = "review", float(live.get("progress") or 0)
            elif live.get("state") in ("running", "waiting") or (e.get("pilot") and live.get("state") != "done"):
                state, prog = "running", float(live.get("progress") or 0)
            elif e.get("status") in DONE or live.get("state") == "done":
                state, prog = "done", 1.0
            else:
                state, prog = "running", float(live.get("progress") or 0)
            out.append(dict(item=e["id"], name=e.get("name"), dir=e.get("dir"), state=state, progress=prog,
                            failure=e.get("failure")))
        return out

    def _resume_answered(self, review):
        """A project parked at its review check whose clips she has all decided (approved / sent back, in the
        review or the Inbox: those answers do not run anything) gets its run going again -> True when one was
        resumed. ``vstudio.project status --json``: every item still ``waiting`` must carry her ``review``
        decision. Asked at most every 10 s per project."""
        if self.runner is None:
            return False
        resumed = False
        now = time.time()
        for r in review:
            d = r["dir"]
            if now - self._checked.get(d, 0) < 10:
                continue
            self._checked[d] = now
            doc = self.runner.sibling("vstudio.project").json(["status", "--dir", d, "--json"], timeout=120)
            waiting = [it for it in doc.get("items") or [] if it.get("waiting")]
            if waiting and all(it.get("review") for it in waiting):
                py = self.runner.python
                self._spawn(py, self.runner.env, d, bus=self.bus,
                            args=[py, "-m", "vstudio.project", "run", "--dir", d, "--auto", "all", "--json-events"])
                resumed = True
        return resumed

    # ------------------------------------------------------------------ run
    NEEDS_ENGINE = "Making the clips needs the Reelfold engine (vstudio.intake + vstudio.project); it is not available"

    def run(self, wid):
        """「做这周的片子」: the plan becomes projects (vstudio.intake apply) and every clip is made: one
        ``vstudio.project run --auto all`` per project (checkpoints answered with their defaults), not only a pilot."""
        need(self.runner is not None and self.intake.real(), self.NEEDS_ENGINE)
        with self._lock:
            rec = self._advance(self._load(wid))
            need(rec["state"] == "ready", "the plan is not ready yet")
            r = self.intake.apply(rec["intake"], plan=self._with_week_platforms(rec), run=False)
            projects = [p for p in r.get("projects") or [] if p.get("dir")]
            need(projects, "the plan made no project")
            rec = self._save(dict(rec, state="making", projects=projects, progress=0.0, started=time.time()))
        py = self.runner.python
        for p in projects:
            self._spawn(py, self.runner.env, p["dir"], bus=self.bus,
                        args=[py, "-m", "vstudio.project", "run", "--dir", p["dir"], "--auto", "all", "--json-events"])
        if self.bus:
            self.bus.publish("batches")
        return self._view(rec)

    def _with_week_platforms(self, rec):
        """The plan with a version for every platform the week posts to (a planner may name fewer than she asked
        for: the week would then post a file made for another platform)."""
        plan = json.loads(json.dumps(self.intake.get(rec["intake"])["plan"]))
        for proj in plan.get("projects") or []:
            prm = proj.get("params")
            if not isinstance(prm, dict) or not isinstance(prm.get("platforms"), list):
                continue
            have = {str(p).split(":")[0] for p in prm["platforms"]}
            prm["platforms"] += [f"{p}:vertical" if p == "xiaohongshu" else p for p in rec["platforms"] if p not in have]
        return plan

    # ------------------------------------------------------------------ the week
    def _lay_out(self, rec):
        """The made clips over the week (calendar.plan with the platform defaults), never written."""
        items = {r["item"] for r in self._project_rows(rec) if r["state"] == "done"}
        queue = [q for q in self.calendar.list()["queue"] if q["item"] in items]
        if not queue:
            return dict(rec, preview=dict(ok=False, reason="no_clips", drafts=[], adjustments=[], start=rec.get("start")))
        start = rec.get("start") or self.calendar_start(rec)
        p = self.calendar.plan(dict(text=rec.get("text") or "", start=start, today=rec.get("today"),
                                    platforms=rec["platforms"], times=rec.get("times") or {},
                                    clips=[dict(item=q["item"], clip=q["clip"]) for q in queue],
                                    platform_defaults=True))
        p.pop("rule", None)
        return dict(rec, preview=p)

    @staticmethod
    def calendar_start(rec):
        import datetime as dt
        d = dt.date.fromisoformat(rec.get("today")) if rec.get("today") else dt.date.today()
        return (d - dt.timedelta(days=d.weekday())).isoformat()

    def reword(self, wid, text, today=None, start=None):
        """She says it differently ("weekdays 8pm, only Xiaohongshu"): the same clips, laid out again."""
        need(isinstance(text, str) and len(text) <= 300, "text: up to 300 chars")
        for v in (today, start):
            need(v is None or (isinstance(v, str) and DAY_RE.match(v)), "today / start: YYYY-MM-DD")
        with self._lock:
            rec = self._advance(self._load(wid))
            need(rec["state"] in ("preview", "ready", "making", "review"), "nothing to lay out")
            rule = schedule_text.parse(text) if text.strip() else None
            if text.strip() and not rule["understood"]:
                return dict(self._view(rec), ok=False, reason="not_understood")
            plats = (rule or {}).get("platforms") or rec["platforms"]
            want = _want(rule, plats)
            rec = dict(rec, text=text.strip(), rule=rule, platforms=plats, today=today or rec.get("today"),
                       start=start or rec.get("start"))
            if rec["state"] == "preview":
                rec = self._lay_out(rec)
            elif rec["state"] == "ready" and want != rec.get("want"):
                # not made yet: the plan follows (a week of 5 posts = 5 clips)
                self.intake.revise(rec["intake"], f"一周 {want} 条。{text.strip()}")
                rec = dict(rec, want=want, state="planning")
            return dict(self._view(self._save(rec)), ok=True)

    def confirm(self, wid):
        """The one primary button: the previewed posts go on the board (one undo: unschedule ``ids``)."""
        with self._lock:
            rec = self._load(wid)
            need(rec["state"] == "preview" and (rec.get("preview") or {}).get("ok"), "no week to confirm")
            drafts = rec["preview"]["drafts"]
            r = self.calendar.add_many([dict(item=d["item"], clip=d["clip"], platform=d["platform"], at=d["at"])
                                        for d in drafts])
            rec = self._save(dict(rec, state="scheduled", scheduled=r["ids"]))
        return dict(self._view(rec), ids=r["ids"])

    def dismiss(self, wid):
        """Put it away (planning stops; made clips stay in the queue, nothing is deleted)."""
        with self._lock:
            rec = self._load(wid)
            if rec["state"] == "planning":
                try:
                    self.intake.stop(rec["intake"])
                except Exception:  # noqa: BLE001
                    pass
            rec = self._save(dict(rec, state="dismissed"))
        return self._view(rec)
