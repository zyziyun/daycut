"""The test engine's intake: a rule planner with the shape of ``vstudio.intake plan --json`` (version 1,
projects[].items.rows, estimate, questions, summary_zh) and a simulated pilot that writes ``.vstudio/status.json``
heartbeats like a real run, so Home's Running lane and the Inbox behave the same. Tests only.

  DESK_MOCK_STEP         seconds per simulated stage (default 0.25)
  DESK_MOCK_PLAN_DELAY   extra seconds before a plan is ready (a slow model)
  DESK_MOCK_PILOT_FAIL   auth: the pilot fails at 选段 like an expired Claude Code login, unless retried with another
                         provider
  DESK_MOCK_INTAKE_DOWN  n: the first n probes of the planning engine fail (a hiccup: the card's Try again works)
  DESK_MOCK_PLAN_FAIL    n: the first n plans fail like a planner that timed out (the error event of the real CLI)

Like the real planner: a request with no files is planned from its words (an explainer for "科普 / explain ..."), a
request that cuts footage but has none waits for it (``needs`` intake.need.footage, no project), one that names
Notion with no Notion link / exported notes waits for them (intake.need.notion) - see vstudio.intake.sources.

Autopilot (a request sent with mode autopilot): the simulated run makes every clip (no pilot stop, no question),
writes each finished clip into ``final/`` (a tiny real video + cover) and records what it decided in
``.vstudio/mock-autopilot.json`` (``MockAutopilot`` serves it like ``vstudio.project decisions``). Runs go through the
desk's run queue (``pilot.QUEUE``), so a third project waits in line like a real one.
"""
import hashlib
import json
import os
import re
import threading
import time

from desk_engine import pilot as P
from desk_engine.common import read_json, write_json
from desk_engine.intake import PLATFORMS, Intake, _slug, material


RECIPES = [  # (pattern, recipe, zh label, role)
    (r"切片|切成|剪成.*条|拆成|单独发|剪出来", "longform-to-short", "切片", "slices"),
    (r"课|系列|分集|课程", "longform-to-short", "切片", "slices"),
    (r"讲解|科普|3b1b|explainer", "explainer", "讲解视频", "explainer"),
    (r"短剧|AI ?视频|aigc|生成", "ai-video", "AI 短剧", "aigc"),
    (r"vlog|旅行|旅游|卡点", "vlog", "Vlog", "vlog"),
    (r"文艺|照片|photo|故事", "photo-story", "照片故事", "photo-story"),
    (r"播客|访谈|对谈|podcast", "call-clips", "播客切片", "podcast"),
    (r"宣传|promo", "promo-recut", "宣传片", "promo"),
    (r"脚本|稿", "preproduction", "脚本", "script"),
    (r"口播|精剪|去口癖|剪干净", "talkinghead", "口播精剪", "talkinghead"),
]
CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _num(s):
    if s is None:
        return None
    if s.isdigit():
        return int(s)
    return CN_NUM.get(s)


def _fmt_t(s):
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


# the short-clip question in each --ui-lang, as the real planner writes it in the language it is asked for
SHORT_Q = {
    "zh": ("第 {k} 条只有 {n} 秒，比建议的最短 {m} 秒短一点。先做第 1 条给你看，满意再做剩下的。", ["保持", "加长到 45 秒"]),
    "en": ("Clip {k} is only {n} s, a bit under the suggested {m} s minimum. Clip 1 comes first for you to check.",
           ["Keep it", "Lengthen to 45 s"]),
    "fr": ("Le clip {k} ne dure que {n} s, un peu moins que le minimum conseillé de {m} s. Le clip 1 passe d'abord.",
           ["Garder", "Allonger à 45 s"]),
}


def rule_plan(prompt, inputs, probe=None, plan_id=None, defaults=None, ui_lang=None):
    """The desk's rule planner (mock mode): same shape as ``vstudio.intake plan --json``."""
    defaults = defaults or {}
    mats = [dict(material(p, probe), id=f"f{i + 1}") for i, p in enumerate(inputs)]
    text = prompt or ""
    recipe, label, typ = "talkinghead", "口播精剪", "talkinghead"
    for pat, rid, lab, t in RECIPES:
        if re.search(pat, text, re.I):
            recipe, label, typ = rid, lab, t
            break
    else:
        if any(m["kind"] == "image" for m in mats) and not any(m["kind"] == "video" for m in mats):
            recipe, label, typ = "photo-story", "照片故事", "photo-story"
    plats = [(pid, zh) for pat, pid, zh in PLATFORMS if re.search(pat, text, re.I)]
    if not plats:
        dp = defaults.get("platforms") or ["xiaohongshu:vertical"]
        plats = [(p.split(":")[0], next((zh for _pt, pid, zh in PLATFORMS if pid == p.split(":")[0]), p)) for p in dp]
    m = re.search(r"([0-9]+|[一两二三四五六七八九十])\s*(?:条|clips?\b|videos?\b|shorts?\b)", text, re.I)
    count = _num(m.group(1)) if m else None
    m = re.search(r"每条\s*([0-9]+)\s*秒", text)
    max_s = float(m.group(1)) if m else (75.0 if re.search(r"一分钟|1 ?分钟", text) else 90.0)
    min_s = 45.0 if max_s >= 60 else max(15.0, max_s / 2)
    video = next((x for x in mats if x["kind"] == "video"), None)
    dur = (video or {}).get("duration") or 600.0
    if count is None:
        count = 1 if recipe == "talkinghead" else max(1, min(24, int(dur // ((min_s + max_s) / 2))))
    aspects = ["3:4", "9:16"] if any(p == "xiaohongshu" for p, _ in plats) else ["9:16"]
    if re.search(r"不要\s*9[:：]16", text):
        aspects = [a for a in aspects if a != "9:16"] or ["3:4"]
    rows = []
    span = dur / max(count, 1)
    for i in range(count):
        a = i * span + span * 0.15
        ln = min(max_s, max(min_s, span * 0.6))
        if i == count - 1 and count > 1:
            ln = min_s - 2                      # the deliberate short one: a question for the creator
        rows.append(dict(id=f"s{i + 1:02d}", params=dict(range=[round(a, 1), round(min(dur, a + ln), 1)],
                                                         title=f"第 {i + 1} 条"),
                         why="一段能独立成立的观点"))
    short = [r for r in rows if r["params"]["range"][1] - r["params"]["range"][0] < min_s]
    machine = round(max(1.0, sum(r["params"]["range"][1] - r["params"]["range"][0] for r in rows) / 60 * 3.2), 1)
    est = dict(machine_min=machine, wall_min=round(machine / 2 + 2, 1), api_usd=round(dur / 60 * 0.01, 2),
               storage_mb=int(machine * 90), measured=False, paid_steps=[])
    name = ((video or mats[0])["name"].rsplit(".", 1)[0] if mats else (prompt or "新项目").split("\n")[0])[:24]
    name = re.sub(r"[_-]?(final|成片)$", "", name, flags=re.I) or name
    if not video and recipe not in ("explainer", "ai-video", "preproduction"):
        m2 = re.search(r"([0-9]+|[一两二三四五六七八九十])\s*集", text)
        count = _num(m2.group(1)) if m2 else (count if re.search(r"条|clips?|videos?", text, re.I) else 1)
    proj = dict(id="p1", recipe=recipe, recipe_label=label, type=typ,
                name=f"{name} · {count} 条{label if count > 1 else ''}".strip(), why="按你说的做",
                materials=[x["id"] for x in mats], inputs={"video": [video["path"]]} if video else {},
                items=dict(method="focus" if count > 1 else "single", count=count, rows=rows),
                params=dict(platforms=[f"{p}:vertical" if p == "xiaohongshu" else p for p, _ in plats],
                            aspects=aspects, max_s=max_s, min_s=min_s,
                            cleanup_profile=defaults.get("cleanup_profile") or "tight"),
                param_sources=dict(platforms="prompt" if re.search("|".join(p for p, _a, _b in PLATFORMS), text, re.I)
                                   else "persona"),
                checkpoints=[dict(id="filler", kind="filler-confirm", label="确认剪辑改动", needs_you=True, auto="default"),
                             dict(id="cover", kind="cover-pick", label="选封面", needs_you=True, auto="default")],
                estimate=est, outputs=dict(platforms=[p for p, _ in plats], videos=count * len(aspects)))
    questions = []
    if short:
        r = short[0]
        k = rows.index(r) + 1
        text, options = SHORT_Q[ui_lang or "zh"]
        questions.append(dict(id="q1", project="p1", options=options, default=options[0],
                              text=text.format(k=k, n=int(r["params"]["range"][1] - r["params"]["range"][0]),
                                               m=int(min_s))))
    src = f"一条 {_fmt_t(dur)} 的视频" if video else (f"{len(mats)} 个文件" if mats else "你的描述")
    summary = (f"这是{src}。我会做出 {count} 条{label}，每条 {int(min_s)}–{int(max_s)} 秒，"
               f"出{'、'.join(zh for _, zh in plats)} {' 和 '.join(aspects)} {'两个版本' if len(aspects) > 1 else '版本'}，配封面和文案。")
    pid = plan_id or hashlib.sha1(f"{prompt}{inputs}{time.time()}".encode()).hexdigest()[:12]
    needs = []
    media = [x for x in mats if x["kind"] in ("video", "image", "audio", "folder")]
    words = re.search(r"讲解|科普|explain|短剧|AI ?视频|脚本|稿|series|系列", prompt or "", re.I)
    if not media and not words and re.search(r"剪|切|口播|cut|edit|clips?|podcast|播客|vlog", prompt or "", re.I):
        needs.append(dict(code="intake.need.footage", params={}, message="Add the recordings you want cut",
                          message_zh="把要剪的录像拖进来"))
    has_notes = any(x["path"].lower().endswith((".md", ".html", ".htm")) or x["kind"] == "folder" for x in mats)
    if re.search(r"notion", prompt or "", re.I) and not re.search(r"notion\.(so|site)/", prompt or "", re.I) and not has_notes:
        needs.append(dict(code="intake.need.notion", params={}, message="Which Notion pages?",
                          message_zh="要用哪些 Notion 页面？"))
    if not media and not needs and recipe not in ("explainer", "ai-video", "preproduction"):
        recipe, label, typ = "explainer", "讲解视频", "explainer"
        proj.update(recipe=recipe, recipe_label=label, type=typ)
    if any(n["code"] == "intake.need.footage" for n in needs):
        summary = needs[0]["message_zh"]
    return dict(version=1, kind="vstudio.intake.plan", id=pid, created=time.strftime("%Y-%m-%dT%H:%M:%S"),
                prompt=prompt, client=None, revisions=[],
                planner=dict(provider="rules", model=None, route="desk", fallback=True, cost_usd=0, seconds=0.1),
                analysis=dict(inputs=list(inputs), totals=dict(files=len(mats))), materials=mats,
                projects=[] if any(n["code"] == "intake.need.footage" for n in needs) else [proj],
                series=None, questions=questions, risks=[], warnings=[], estimate=est, run=dict(pilot=1, auto=[]),
                summary_zh=summary, summary_lang="zh", **({"ui_lang": ui_lang} if ui_lang else {}),
                **({"needs": needs} if needs else {}))


def rule_revise(plan, prompt):
    """Follow-ups the desk understands without a model: 只要 <平台> / N 条 / 每条 N 秒内 / 不要 9:16."""
    p = json.loads(json.dumps(plan))
    changes = []
    for proj in p["projects"]:
        prm = proj["params"]
        plats = [(pid, zh) for pat, pid, zh in PLATFORMS if re.search(pat, prompt, re.I)]
        if plats and re.search(r"只要|只发|只做|only", prompt, re.I):
            prm["platforms"] = [f"{pid}:vertical" if pid == "xiaohongshu" else pid for pid, _ in plats]
            changes.append("平台：" + "、".join(zh for _, zh in plats))
        m = re.search(r"([0-9]+|[一两二三四五六七八九十])\s*(?:条|clips?\b)", prompt, re.I)
        if m and _num(m.group(1)):
            n = _num(m.group(1))
            rows = proj["items"]["rows"]
            proj["items"]["rows"] = rows[:n] if n <= len(rows) else rows + [
                dict(id=f"s{i + 1:02d}", params=dict(range=list(rows[-1]["params"]["range"]), title=f"第 {i + 1} 条"),
                     why="补一条") for i in range(len(rows), n)]
            proj["items"]["count"] = n
            changes.append(f"{n} 条")
        m = re.search(r"每条\s*([0-9]+)\s*秒", prompt)
        if m:
            prm["max_s"] = float(m.group(1))
            prm["min_s"] = min(prm.get("min_s", 45.0), prm["max_s"] / 2)
            for r in proj["items"]["rows"]:
                a, z = r["params"]["range"]
                r["params"]["range"] = [a, round(min(z, a + prm["max_s"]), 1)]
            changes.append(f"每条 {m.group(1)} 秒内")
        if re.search(r"不要\s*9[:：]16", prompt):
            prm["aspects"] = [a for a in prm.get("aspects", []) if a != "9:16"] or ["3:4"]
            changes.append("不要 9:16")
        proj["outputs"]["videos"] = proj["items"]["count"] * len(prm.get("aspects") or [1])
    if not changes:
        p["warnings"] = list(p.get("warnings") or []) + [f"没看懂「{prompt}」，方案没改。"]
    else:
        p["questions"] = [q for q in p.get("questions") or [] if not re.search(r"条", prompt)] if \
            re.search(r"条", prompt) else p.get("questions") or []
        p["summary_zh"] = re.sub(r"(。改了：.*)?$", "", p["summary_zh"]) + "。改了：" + "，".join(changes) + "。"
        p["summary_zh"] = p["summary_zh"].replace("。。", "。")
    p["revisions"] = list(p.get("revisions") or []) + [dict(prompt=prompt, at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                            changes=changes)]
    return p


def record_pilot(d, ok, error=None, provider=None):
    """The same files a real pilot leaves behind (``desk_engine.pilot``: the run log + desk-pilot.json)."""
    with open(os.path.join(d, P.LOG), "a", encoding="utf-8") as f:
        if ok:
            f.write(json.dumps(dict(event="project-end", status="pilot-review", exit_code=4)) + "\n")
        else:
            f.write(json.dumps(dict(ok=False, error=error, type="ProjectError"), ensure_ascii=False) + "\n")
    write_json(os.path.join(d, P.REC), dict(pid=None, started=time.time(), offset=0, exit=4 if ok else 5,
                                          finished=time.time(), provider=provider))


MOCK_AP = "mock-autopilot.json"


def mock_autopilot(d):
    """The simulated project's autopilot record: {on, decisions [like vstudio.project decisions], ask}."""
    return read_json(os.path.join(d, ".vstudio", MOCK_AP), {}) or {}


class MockIntake(Intake):
    """``Intake`` with the rule planner and the simulated pilot in place of ``python -m vstudio.intake``."""

    def real(self):
        if self._real is None:
            self._probes = getattr(self, "_probes", 0) + 1
            down = self._probes <= int(os.environ.get("DESK_MOCK_INTAKE_DOWN") or 0)
            self._real, self._why = (False, "vstudio.intake: exit 1: database is locked") if down else (True, None)
        return self._real

    def _simulate_progress(self, pid, inputs, step):
        """The engine's --json-events of a plan, simulated: scan, read each file, transcribe the first video (in
        ``ticks`` moves), ask the model, write the plan."""
        ev = lambda stage, event="stage", **kw: self._progress(pid, dict(event=event, stage=stage, **kw))  # noqa: E731
        ev("scan", inputs=len(inputs))
        ev("scan", inputs=len(inputs), files=len(inputs))
        video = None
        for i, p in enumerate(inputs):
            m = material(p, self.probe)
            ev("probe", file=m["name"], i=i + 1, n=len(inputs), kind=m["kind"])
            time.sleep(step / 4)
            if m["kind"] == "video" and video is None:
                video = m
        if video:
            total = float(video.get("duration") or 600.0)
            ticks = int(os.environ.get("DESK_MOCK_ASR_TICKS") or 6)
            ev("transcribe", file=video["name"], total_s=total, done_s=0)
            for k in range(1, ticks + 1):
                time.sleep(step / 4)
                ev("transcribe", "progress", file=video["name"], done_s=round(total * k / ticks, 1), total_s=total)
        ev("model", provider="claude-code")
        time.sleep(step)                                   # the model call

    _plan_fails = 0

    def _engine_plan(self, pid, prompt, inputs):
        step = float(os.environ.get("DESK_MOCK_STEP", "0.25"))
        self._set(pid, step="plan")
        self._simulate_progress(pid, inputs, step)
        if MockIntake._plan_fails < int(os.environ.get("DESK_MOCK_PLAN_FAIL") or 0):
            MockIntake._plan_fails += 1
            from desk_engine.caps import CliError
            raise CliError("vstudio.intake plan exited 1: TimeoutError: claude-code: timed out after 235 s",
                           dict(event="error", error="TimeoutError: claude-code: timed out after 235 s", code=None))
        if (self.jobs.get(pid) or {}).get("ignore_needs"):
            plats = (self.jobs.get(pid) or {}).get("platforms")
            plan = rule_plan(prompt, inputs, self.probe, pid, dict(self.defaults(), **({"platforms": plats} if plats else {})),
                             (self.jobs.get(pid) or {}).get("lang"))
            plan.pop("needs", None)
            write_json(self._path(pid), plan)
            return plan
        time.sleep(float(os.environ.get("DESK_MOCK_PLAN_DELAY", "0")))
        plats = (self.jobs.get(pid) or {}).get("platforms")
        plan = rule_plan(prompt, inputs, self.probe, pid, dict(self.defaults(), **({"platforms": plats} if plats else {})),
                         (self.jobs.get(pid) or {}).get("lang"))
        self._progress(pid, dict(event="stage", stage="write"))
        write_json(self._path(pid), plan)
        return plan

    def _engine_revise(self, pid, plan, prompt):
        time.sleep(float(os.environ.get("DESK_MOCK_STEP", "0.25")) / 2)
        p = rule_revise(plan, prompt)
        write_json(self._path(pid), p)
        return p

    def _engine_apply(self, pid, plan, out_root, run, autopilot=False):
        home = os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"))
        return self._mock_apply(plan, out_root, home, run, autopilot)

    def _spawn_pilot(self, d, provider=None, autopilot=False, lang=None):
        rec = read_json(os.path.join(d, ".vstudio", "work.json"), {}) or {}
        proj = dict(name=rec.get("title") or os.path.basename(d), items=dict(count=int(rec.get("count") or 3)))
        autopilot = autopilot or mock_autopilot(d).get("on")
        self._queue_run(d, proj, provider, autopilot)

    def _queue_run(self, d, proj, provider=None, autopilot=False, start_at=0):
        """A simulated run through the desk's run queue (``pilot.QUEUE``): queued when the slots are taken."""
        def start(done):
            write_json(os.path.join(d, P.REC), dict(pid=os.getpid(), started=time.time(), exit=None, provider=provider))

            def go():
                try:
                    if autopilot:
                        self._mock_autopilot(d, proj, start_at, provider)
                    else:
                        self._mock_pilot(d, proj, provider)
                finally:
                    done()
                    if self.bus:
                        self.bus.publish("batches")
            threading.Thread(target=go, daemon=True).start()
        if not P.QUEUE.submit(d, start):
            write_json(os.path.join(d, P.REC), dict(pid=None, queued=True, queued_at=time.time(), exit=None,
                                                    provider=provider))
            if self.bus:
                self.bus.publish("batches")

    _apply_lock = threading.Lock()                # requests applied at once write one projects.json

    def _mock_apply(self, plan, out_root, home, run, autopilot=False):
        with self._apply_lock:
            projects = self._mock_create(plan, out_root, home, autopilot)
        if run:
            for p_, proj in zip(projects, plan["projects"]):
                self._queue_run(p_["dir"], proj, autopilot=autopilot)
        return projects

    def _mock_create(self, plan, out_root, home, autopilot=False):
        projects = []
        reg_path = os.path.join(home, "projects.json")
        reg = read_json(reg_path, []) or []
        for i, proj in enumerate(plan["projects"]):
            d = os.path.join(out_root, _slug(proj["name"], i))
            os.makedirs(os.path.join(d, ".vstudio"), exist_ok=True)
            write_json(os.path.join(d, ".vstudio", "work.json"),
                       dict(kind="work", title=proj["name"], recipe=proj["recipe"], type=proj.get("type") or "other",
                            outputs=[], covers=[], posts=[], sheets=[], notes=[], sources=[], client=None,
                            created=time.strftime("%Y-%m-%dT%H:%M:%S"), updated=time.strftime("%Y-%m-%dT%H:%M:%S"),
                            plan=plan["id"], count=proj["items"]["count"]))
            with open(os.path.join(d, "PLAN.md"), "w", encoding="utf-8") as f:
                f.write(f"# {proj['name']}\n\n{plan.get('summary_zh', '')}\n")
            reg = [r for r in reg if not (isinstance(r, dict) and r.get("dir") == d)]
            reg.append(dict(dir=d, name=proj["name"], recipe=proj["recipe"], series=None, client=None,
                            created=time.strftime("%Y-%m-%dT%H:%M:%S"), kind="work"))
            projects.append(dict(dir=d, name=proj["name"], recipe=proj["recipe"]))
            write_json(os.path.join(d, ".vstudio", MOCK_AP), dict(on=bool(autopilot), decisions=[], ask=[]))
        write_json(reg_path, reg)
        return projects

    def _mock_autopilot(self, d, proj, start_at=0, provider=None):
        """The whole project, no question: each clip goes through the stages, lands in final/ and the decisions the
        engine would have taken are recorded (one AI call for the unsure cuts, the rules for the rest).
        ``DESK_MOCK_PILOT_FAIL=auth``: fails at the first model call like an expired Claude Code login (a retry with
        another provider runs)."""
        import socket
        from .engine import MockEngine
        step = float(os.environ.get("DESK_MOCK_STEP", "0.25"))
        n = int(proj["items"]["count"])
        started = time.time()
        if os.environ.get("DESK_MOCK_PILOT_FAIL") and provider in (None, "claude-code"):
            write_json(os.path.join(d, ".vstudio", "status.json"),
                       dict(status="failed", stage="segment_plan", progress=0.05, message="", started=started,
                            heartbeat=time.time(), pid=os.getpid(), host=socket.gethostname(), updated_by="desk-mock"))
            record_pilot(d, False, "plan-segments failed (exit 5): claude CLI: Failed to authenticate. "
                              "API Error: 401 {\"type\":\"error\"} see /Users/someone/.claude/logs/x.log",  # check-skill: allow
                              provider="claude-code")
            if self.bus:
                self.bus.publish("inbox")
            return
        stages = ("asr", "cleanup", "subs", "compose", "export", "qc", "copy")
        os.makedirs(os.path.join(d, "final"), exist_ok=True)
        for k in range(start_at, n):
            if not mock_autopilot(d).get("on", True) and k > start_at:
                # switched to "ask me first" while it ran: this clip is done, the rest waits for her
                write_json(os.path.join(d, ".vstudio", "status.json"),
                           dict(status="waiting", stage="review", progress=round(k / n, 2), message=f"{k}/{n}",
                                started=started, heartbeat=time.time(), pid=os.getpid(), host=socket.gethostname(),
                                needs_you=True, updated_by="desk-mock"))
                return
            item = f"s{k + 1:02d}"
            for j, stage in enumerate(stages):
                # what the real batch runner writes (vstudio.batch.run._live_fields): "<job>:<stage>", "k/n jobs",
                # the coded line and the time left - the desk words it ("Clip 1 of 3 · Transcribe · about 1 min left")
                write_json(os.path.join(d, ".vstudio", "status.json"),
                           dict(status="running", stage=f"{item}:{stage}", progress=round((k + j / len(stages)) / n, 3),
                                message=f"{k}/{n} jobs", jobs_done=k, jobs_total=n, live_code="jobs",
                                live_params=dict(done=k, total=n), eta=int(((n - k) * len(stages) - j) * step),
                                started=started, heartbeat=time.time(), pid=os.getpid(), host=socket.gethostname(),
                                updated_by="desk-mock"))
                with open(os.path.join(d, P.LOG), "a", encoding="utf-8") as f:   # the run's events (「看过程」)
                    f.write(json.dumps(dict(event="stage-start", ts=time.time(), job=item, stage=stage)) + "\n")
                if self.bus:
                    self.bus.publish("batches")
                time.sleep(step)
            name = f"{k + 1:02d}_clip"
            MockEngine._mock_video(None, os.path.join(d, "final", f"{name}.mp4"))
            MockEngine._mock_cover(None, os.path.join(d, "final", f"{name}_cover.jpg"))
            with open(os.path.join(d, P.LOG), "a", encoding="utf-8") as f:
                f.write(json.dumps(dict(event="job-done", ts=time.time(), job=item, state="done")) + "\n")
            ap = mock_autopilot(d)
            ap["decisions"] = [x for x in ap.get("decisions") or [] if x.get("item") != item] + [
                dict(checkpoint="filler", kind="filler-confirm", item=item, by="ai", provider="claude-code",
                     reason="Cut the ums, kept the pause before the punchline", reason_code="ai",
                     params=dict(cut=3, kept=1, n=4), labels=dict(en="Confirm filler cuts", zh="确认去口癖"),
                     at=time.strftime("%Y-%m-%dT%H:%M:%S")),
                dict(checkpoint="cover", kind="cover-pick", item=item, by="rules", reason="the best-scored frame",
                     reason_code="cover-best", params=dict(pick=0), labels=dict(en="Pick the cover", zh="选封面"),
                     at=time.strftime("%Y-%m-%dT%H:%M:%S"))]
            write_json(os.path.join(d, ".vstudio", MOCK_AP), ap)
        write_json(os.path.join(d, ".vstudio", "status.json"),
                   dict(status="done", stage="done", progress=1.0, message=f"done: {n} jobs", started=started,
                        heartbeat=time.time(), finished=time.time(), pid=os.getpid(), host=socket.gethostname(),
                        updated_by="desk-mock"))
        with open(os.path.join(d, P.LOG), "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(event="project-end", status="done", exit_code=0)) + "\n")
        write_json(os.path.join(d, P.REC), dict(pid=None, started=started, offset=0, exit=0, finished=time.time()))

    def _mock_pilot(self, d, proj, provider=None):
        """A simulated pilot: heartbeats like vstudio.batch.livestatus, then 'waiting' (needs you) after item 1.
        ``DESK_MOCK_PILOT_FAIL=auth`` (tests): fails at 选段 like an expired Claude Code login, unless retried
        with another provider."""
        import socket
        step = float(os.environ.get("DESK_MOCK_STEP", "0.25"))
        started = time.time()
        n = proj["items"]["count"]
        fail = os.environ.get("DESK_MOCK_PILOT_FAIL") if provider in (None, "claude-code") else None
        for k, stage in enumerate(("读素材", "选段", "去停顿", "加字幕", "导出")):
            if fail and k == 1:
                write_json(os.path.join(d, ".vstudio", "status.json"),
                           dict(status="failed", stage=stage, progress=0.1, message="", started=started,
                                heartbeat=time.time(), pid=os.getpid(), host=socket.gethostname(),
                                updated_by="desk-mock"))
                record_pilot(d, False, "plan-segments failed (exit 5): claude CLI: Failed to authenticate. "
                                  "API Error: 401 {\"type\":\"error\"} see /Users/someone/.claude/logs/x.log",  # check-skill: allow
                                  provider="claude-code")
                if self.bus:
                    self.bus.publish("batches")
                    self.bus.publish("inbox")
                return
            write_json(os.path.join(d, ".vstudio", "status.json"),
                       dict(status="running", stage=stage, progress=round((k + 1) / 6, 2),
                            message=f"第 1 条：{stage}", eta=int((5 - k) * step * 4), started=started,
                            heartbeat=time.time(), pid=os.getpid(), host=socket.gethostname(), updated_by="desk-mock"))
            if self.bus:
                self.bus.publish("batches")
            time.sleep(step * 4)
        write_json(os.path.join(d, ".vstudio", "status.json"),
                   dict(status="waiting", stage="试看", progress=round(1 / max(n, 1), 2),
                        message="第 1 条做好了，等你看一眼", started=started, heartbeat=time.time(), pid=os.getpid(),
                        host=socket.gethostname(), needs_you=True, updated_by="desk-mock"))
        record_pilot(d, True, provider=provider)
        if self.bus:
            self.bus.publish("batches")
