"""Intake: one sentence + dropped files -> an AI plan card -> projects (``python -m vstudio.intake``, the engine's
references/INTAKE.md). Plans are slow (inventory + ASR + a model call), so the desk runs them as background jobs:

  start(prompt, inputs)  -> {id}      GET  -> {id, state running|done|error, step, plan, error, prompt, inputs}
  revise(id, prompt)     -> same job, state running again (the plan keeps its revisions)
  apply(id, plan?, run)  -> {projects [{dir, name, recipe}], series}; ``run`` starts each pilot in the background

Real engine: ``vstudio.intake plan|revise|apply --json`` (plan JSON kept in ``<DESK_DATA_DIR>/intake/<id>.json``),
pilots via ``vstudio.project run --dir D --pilot 1``. Mock mode (or no ``vstudio.intake``): a rule planner with the
same plan shape (version 1, projects[].items.rows, estimate, questions, summary_zh) and a simulated pilot that
writes ``.vstudio/status.json`` heartbeats like a real run, so the 进行中 lane and the inbox behave the same.
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time

from .common import need, read_json, write_json

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
AUDIO = {".wav", ".mp3", ".m4a", ".aac", ".flac"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
TEXT = {".pdf", ".docx", ".pptx", ".md", ".txt", ".srt", ".vtt", ".ass", ".json"}

PLATFORMS = [("小红书", "xiaohongshu", "小红书"), ("抖音", "douyin", "抖音"), ("视频号", "shipinhao", "视频号"),
             ("b站|B站|bilibili", "bilibili", "B 站"), ("youtube|油管", "youtube-shorts", "YouTube"),
             ("tiktok", "tiktok", "TikTok")]
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


def _fmt_t(s):
    s = max(0, int(round(s)))
    return f"{s // 60}:{s % 60:02d}"


def rule_plan(prompt, inputs, probe=None, plan_id=None, defaults=None):
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
    m = re.search(r"([0-9]+|[一两二三四五六七八九十])\s*条", text)
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
    name = ((video or mats[0])["name"].rsplit(".", 1)[0] if mats else "新项目")[:24]
    name = re.sub(r"[_-]?(final|成片)$", "", name, flags=re.I) or name
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
        questions.append(dict(id="q1", project="p1", text=f"第 {k} 条只有 {int(r['params']['range'][1] - r['params']['range'][0])} 秒，"
                                                         f"比建议的最短 {int(min_s)} 秒短一点。先做第 1 条给你看，满意再做剩下的。",
                              options=["保持", "加长到 45 秒"], default="保持"))
    src = f"一条 {_fmt_t(dur)} 的视频" if video else (f"{len(mats)} 个文件" if mats else "你的描述")
    summary = (f"这是{src}。我会做出 {count} 条{label}，每条 {int(min_s)}–{int(max_s)} 秒，"
               f"出{'、'.join(zh for _, zh in plats)} {' 和 '.join(aspects)} {'两个版本' if len(aspects) > 1 else '版本'}，配封面和文案。")
    pid = plan_id or hashlib.sha1(f"{prompt}{inputs}{time.time()}".encode()).hexdigest()[:12]
    return dict(version=1, kind="vstudio.intake.plan", id=pid, created=time.strftime("%Y-%m-%dT%H:%M:%S"),
                prompt=prompt, client=None, revisions=[],
                planner=dict(provider="rules", model=None, route="desk", fallback=True, cost_usd=0, seconds=0.1),
                analysis=dict(inputs=list(inputs), totals=dict(files=len(mats))), materials=mats, projects=[proj],
                series=None, questions=questions, risks=[], warnings=[], estimate=est, run=dict(pilot=1, auto=[]),
                summary_zh=summary)


def rule_revise(plan, prompt):
    """Follow-ups the desk understands without a model: 只要 <平台> / N 条 / 每条 N 秒内 / 不要 9:16."""
    p = json.loads(json.dumps(plan))
    changes = []
    for proj in p["projects"]:
        prm = proj["params"]
        plats = [(pid, zh) for pat, pid, zh in PLATFORMS if re.search(pat, prompt, re.I)]
        if plats and re.search(r"只要|只发|只做", prompt):
            prm["platforms"] = [f"{pid}:vertical" if pid == "xiaohongshu" else pid for pid, _ in plats]
            changes.append("平台：" + "、".join(zh for _, zh in plats))
        m = re.search(r"([0-9]+|[一两二三四五六七八九十])\s*条", prompt)
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


def _slug(name, i):
    s = re.sub(r"[^\w一-鿿-]+", "-", name).strip("-")[:40]
    return f"{i + 1:02d}-{s or 'project'}"


class Intake:
    def __init__(self, data_dir, bus, runner=None, mode="mock", probe=None, defaults=None):
        self.dir = os.path.join(data_dir, "intake")
        self.bus, self.runner, self.mode, self.probe = bus, runner, mode, probe
        self.defaults = defaults or (lambda: {})
        self.jobs = {}
        self._lock = threading.Lock()
        self._real = None

    def real(self):
        if self._real is None:
            ok = False
            if self.mode == "real" and self.runner is not None:
                try:
                    txt = self.runner.sibling("vstudio.intake").text(["--help"])
                    ok = "plan" in txt and "apply" in txt and "No module named" not in txt
                except Exception:  # noqa: BLE001
                    ok = False
            self._real = ok
        return self._real

    def _path(self, pid):
        return os.path.join(self.dir, f"{pid}.json")

    def _set(self, pid, **kw):
        with self._lock:
            self.jobs[pid] = dict(self.jobs.get(pid) or {}, **kw)
            job = dict(self.jobs[pid])
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

    # ---------------------------------------------------------- plan / revise
    def start(self, prompt, inputs):
        pid = hashlib.sha1(f"{prompt}\0{inputs}\0{time.time()}".encode()).hexdigest()[:12]
        self._set(pid, id=pid, state="running", step="analyze", prompt=prompt, inputs=inputs, plan=None, error=None,
                  started=time.time())
        threading.Thread(target=self._plan, args=(pid, prompt, inputs), daemon=True).start()
        return dict(id=pid)

    def _plan(self, pid, prompt, inputs):
        try:
            if self.real():
                out = self._path(pid)
                os.makedirs(self.dir, exist_ok=True)
                args = ["plan", "--prompt", prompt, "--out", out, "--json"]
                if inputs:
                    args += ["--inputs", *inputs]
                self._set(pid, step="plan")
                plan = self.runner.sibling("vstudio.intake").json(args, timeout=1800)
                plan["id"] = plan.get("id") or pid
                plan["desk_id"] = pid
                write_json(out, plan)
            else:
                time.sleep(float(os.environ.get("DESK_MOCK_STEP", "0.25")))
                self._set(pid, step="plan")
                plan = rule_plan(prompt, inputs, self.probe, pid, self.defaults())
                write_json(self._path(pid), plan)
            self._set(pid, state="done", step="done", plan=plan)
        except Exception as e:  # noqa: BLE001
            self._set(pid, state="error", error=str(e)[:500])

    def revise(self, pid, prompt):
        j = self.get(pid)
        need(j.get("plan"), "the plan is not ready yet")
        self._set(pid, state="running", step="revise", error=None)

        def go():
            try:
                if self.real():
                    p = self.runner.sibling("vstudio.intake").json(["revise", "--plan", self._path(pid), "--prompt",
                                                                    prompt, "--in-place", "--json"], timeout=900)
                else:
                    time.sleep(float(os.environ.get("DESK_MOCK_STEP", "0.25")) / 2)
                    p = rule_revise(j["plan"], prompt)
                    write_json(self._path(pid), p)
                self._set(pid, state="done", step="done", plan=p)
            except Exception as e:  # noqa: BLE001
                self._set(pid, state="error", error=str(e)[:500])
        threading.Thread(target=go, daemon=True).start()
        return dict(id=pid)

    # ---------------------------------------------------------- apply (+ pilot)
    def apply(self, pid, plan=None, run=True, out_root=None):
        j = self.get(pid)
        need(j.get("plan") or plan, "the plan is not ready yet")
        if plan is not None:                       # the creator edited rows / params on the card
            need(isinstance(plan, dict) and plan.get("kind") == "vstudio.intake.plan" and isinstance(plan.get("projects"), list),
                 "plan: a vstudio.intake.plan document")
            write_json(self._path(pid), plan)
        plan = plan or j["plan"]
        home = os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"))
        out_root = out_root or os.path.join(home, "projects", pid)
        if self.real():
            doc = self.runner.sibling("vstudio.intake").json(["apply", "--plan", self._path(pid), "--out", out_root,
                                                              "--json"], timeout=900)
            projects = [dict(dir=p.get("dir"), name=p.get("name"), recipe=p.get("recipe"))
                        for p in doc.get("projects") or [] if isinstance(p, dict)]
            if run:
                for p in projects:
                    if p["dir"]:
                        self._spawn_pilot(p["dir"])
        else:
            projects = self._mock_apply(plan, out_root, home, run)
        self._set(pid, applied=projects)
        if self.bus:
            self.bus.publish("batches")
        return dict(ok=True, projects=projects, series=plan.get("series"))

    def _spawn_pilot(self, d):
        log = open(os.path.join(d, "desk-pilot.log"), "ab")  # noqa: SIM115  (handed to the child)
        subprocess.Popen([self.runner.python, "-m", "vstudio.project", "run", "--dir", d, "--pilot", "1",
                          "--json-events"], stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=self.runner.env,
                         start_new_session=True)

    def _mock_apply(self, plan, out_root, home, run):
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
                            plan=plan["id"]))
            with open(os.path.join(d, "PLAN.md"), "w", encoding="utf-8") as f:
                f.write(f"# {proj['name']}\n\n{plan.get('summary_zh', '')}\n")
            reg = [r for r in reg if not (isinstance(r, dict) and r.get("dir") == d)]
            reg.append(dict(dir=d, name=proj["name"], recipe=proj["recipe"], series=None, client=None,
                            created=time.strftime("%Y-%m-%dT%H:%M:%S"), kind="work"))
            projects.append(dict(dir=d, name=proj["name"], recipe=proj["recipe"]))
            if run:
                threading.Thread(target=self._mock_pilot, args=(d, proj), daemon=True).start()
        write_json(reg_path, reg)
        return projects

    def _mock_pilot(self, d, proj):
        """A simulated pilot: heartbeats like vstudio.batch.livestatus, then 'waiting' (needs you) after item 1."""
        import socket
        step = float(os.environ.get("DESK_MOCK_STEP", "0.25"))
        started = time.time()
        n = proj["items"]["count"]
        for k, stage in enumerate(("读素材", "选段", "去停顿", "加字幕", "导出")):
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
        if self.bus:
            self.bus.publish("batches")
