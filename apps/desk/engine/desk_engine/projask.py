"""Project-level 「让 AI 改」: one request for every clip of a project page ("remove the series label from all clips").

Runs in the background as a job with staged progress (read N clips -> check -> ask the model -> plan), elapsed time,
a fallback notice when the routed AI times out / fails, and Cancel (kills the engine process group, so the
Claude Code / Codex CLI it started dies too):

  POST /api/outputs/<item>/project-ask {prompt, clips?, context?}  -> {job}
  GET  /api/project-ask/<job>                                      -> {state, stages, notices, elapsed, result?}
  POST /api/project-ask/<job>/stop                                 -> {ok}
  POST /api/outputs/<item>/regenerate {items}                      -> re-run recipe items (needs_rerender action)

Engine: ``python -m vstudio.project ai --project P --instruction T --outputs a,b --json-events --timeout S``
(one model call, grouped per output, needs_rerender for burned text on flattened outputs without a model call).
Without it (older engine, batches, no engine) the desk answers with the same shape: a rule check for burned-in
text (flattened clips) and the desk's rule proposals per clip.
"""
import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time

from .common import need

ENGINE_TIMEOUT = float(os.environ.get("DESK_AI_TIMEOUT") or 120)      # per provider (the engine falls back after it)
WATCHDOG_GRACE = 30.0                                                 # whole call: 3 providers x timeout + grace


def _m(code, en, zh, **params):
    return dict(code=code, message=en, message_zh=zh, params=params)


# ------------------------------------------------------------------ the cheap classifier (mirrors vstudio.project.projai)
_REMOVE = r"去掉|去除|删掉|删除|拿掉|移除|抹掉|不要|隐藏|取消|remove|delete|drop|hide|get rid of|take (?:out|off)|strip"
_REPLACE = r"改成|换成|替换|改为|改叫|replace|rename"
_TEXT_NOUN = (r"文字|字样|标题|小标题|标签|角标|水印|编号|序号|系列名|大字|字卡|logo|\btext\b|\btitle\b|\blabel\b|\btag\b|"
              r"watermark|numbering")
_CAPTION = r"字幕|caption|subtitle"
_RESTYLE = r"样式|颜色|字体|字号|大小|大一点|小一点|大些|小些|描边|位置|style|font|colou?r|size|bigger|smaller|position"
_EDIT_WORDS = (r"开头|结尾|片头|片尾|停顿|气口|口误|重复|这段|这里|\d+\s*秒|音乐|bgm|配乐|进度条|效果|特效|转场|intro|outro|"
               r"pause|silence|music|filler|seconds?|progress bar|effect|transition")
_FILL = r"都|全都|全部|所有|这些|上面的|画面上的|的|一下|掉|all|the|every|from|of|clips?"
_SEP = r"[，,、/／\s]+|和|与|及|以及|还有|\band\b"
_FILLERS = {"嗯", "啊", "呃", "额", "那个", "就是", "然后", "其实", "um", "uh", "like"}


def _targets(text):
    q = re.findall(r"[「“\"『'‘]([^」”\"』'’]{1,40})[」”\"』'’]", text)
    if q:
        return [x.strip() for x in q if x.strip()]
    m = (re.search(rf"把(.{{1,60}}?)(?:都|全都|全部)?(?:{_REMOVE}|{_REPLACE})", text, re.I)
         or re.search(rf"(?:{_REMOVE})\s*(.{{1,60}}?)(?:[。！!？?；;]|$)", text, re.I))
    if not m:
        return []
    out = []
    for tok in re.split(_SEP, m.group(1)):
        tok = re.sub(rf"^(?:{_FILL})+|(?:{_FILL})+$", "", tok.strip(), flags=re.I).strip(" .。")
        if tok:
            out.append(tok)
    return out


def _stems(targets):
    out = []
    for t in targets:
        s = re.sub(r"\s*(?:#|No\.?|第)?\s*[0-9０-９]+\s*(?:期|集|篇|号)?$", "", t).strip(" -_·.")
        if len(s) >= 2 and s not in out:
            out.append(s)
    return out


def classify(text):
    t = text or ""
    remove, replace = re.search(_REMOVE, t, re.I), re.search(_REPLACE, t, re.I)
    noun, caption = bool(re.search(_TEXT_NOUN, t, re.I)), bool(re.search(_CAPTION, t, re.I))
    if caption and re.search(_RESTYLE, t, re.I) and not remove and not replace:
        return dict(kind="caption-restyle", targets=[], stems=[], noun=True)
    if not (remove or replace):
        return dict(kind=None, targets=[], stems=[], noun=noun)
    targets = _targets(t) or (["字幕"] if caption else [])
    if not targets and not noun:
        return dict(kind=None, targets=[], stems=[], noun=False)
    if re.search(_EDIT_WORDS, " ".join(targets) or t, re.I) and not noun:
        return dict(kind=None, targets=targets, stems=[], noun=False)
    return dict(kind="text-replace" if replace and not remove else "text-remove", targets=targets,
                stems=_stems(targets) or targets, noun=noun or caption)


def _norm(s):
    return re.sub(r"[\s，,。.、！!？?：:；;\"'「」“”]+", "", str(s or "")).lower()


def _source_hits(d, stems, limit=24):
    hits = []
    keys = [s for s in stems if s]
    if not keys:
        return hits
    for root, dirs, files in os.walk(d):
        depth = os.path.relpath(root, d).count(os.sep) + (0 if root == d else 1)
        dirs[:] = [x for x in sorted(dirs) if not x.startswith(".") and x not in ("node_modules", "__pycache__", "state")
                   and depth < 3]
        for fn in sorted(files):
            if os.path.splitext(fn)[1].lower() not in (".py", ".json", ".yaml", ".yml", ".sh", ".js", ".ts") or \
                    fn.endswith(".asr.json"):
                continue
            p = os.path.join(root, fn)
            try:
                if os.path.getsize(p) > 512 * 1024:
                    continue
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if any(k in line for k in keys):
                            hits.append(dict(file=os.path.relpath(p, d), line=i, text=line.strip()[:160]))
                            if len(hits) >= limit:
                                return hits
            except OSError:
                continue
    return hits


def _desk_paths(e, clips, cls, zh):
    """needs_rerender paths for the desk implementation (same shape as the engine's)."""
    stems = cls.get("stems") or []
    out = []
    if e["kind"] in ("project", "batch"):
        items = [c["id"] for c in clips]
        out.append(dict(kind="regenerate", items=items,
                        message=_m("path-regenerate", "regenerate these clips through the recipe", "用配方重新生成这几条",
                                   n=len(items)),
                        actions=[dict(kind="regenerate", items=items,
                                      label=_m("act-regenerate", "Regenerate these clips", "重新生成这几条", n=len(items)))]))
    hits = _source_hits(e["dir"], stems) if e["kind"] == "work" else []
    if hits:
        label = "、".join(f"「{s}」" for s in stems)
        names = ", ".join(c["title"] for c in clips)
        where = "; ".join(f"{h['file']}:{h['line']}" for h in hits[:8])
        prompt = (f"在 {e['dir']} 里，把画面上烧进去的{label}去掉，然后用 work/ 里的脚本重新渲染这几条：{names}。文字出现在：{where}。"
                  if zh else f"In {e['dir']}, remove the burned-in {', '.join(stems)} and re-render these clips with "
                  f"the scripts in work/: {names}. The text is set in: {where}.")
        acts = [dict(kind="copy-prompt", prompt=prompt,
                     label=_m("act-copy-prompt", "Copy instructions for Claude Code", "复制给 Claude Code 的指令"))]
        for f in list(dict.fromkeys(h["file"] for h in hits))[:3]:
            h = next(x for x in hits if x["file"] == f)
            acts.append(dict(kind="open-file", file=os.path.join(e["dir"], f), line=h["line"],
                             label=_m("act-open-file", f"Open {os.path.basename(f)}", f"打开 {os.path.basename(f)}",
                                      file=os.path.basename(f), line=h["line"])))
        out.append(dict(kind="rerender-scripts", files=hits, prompt=prompt, actions=acts,
                        message=_m("path-rerender-scripts", "this folder has the scripts that made the clips: change "
                                   "the text there and re-render", "这个文件夹里有做这些片子的脚本：在脚本里去掉这段文字再重新渲染",
                                   n=len(hits))))
    if not out:
        f = (clips[0]["files"][0]["path"] if clips and clips[0].get("files") else e["dir"])
        out.append(dict(kind="re-export", message=_m(
            "path-re-export", "no source pipeline is kept for these clips: re-export them without the text from the "
            "editor they were made in (or cover it with a title band here)",
            "这些片子没有保留可重渲染的源工程：请在做它们的剪辑软件里去掉文字后重新导出（或在这里用标题条盖住）"),
            actions=[dict(kind="reveal", file=f, label=_m("act-reveal", "Show in folder", "在文件夹中显示"))]))
    return out


# ------------------------------------------------------------------ jobs
class ProjectAsk:
    def __init__(self, outputs, bus=None):
        self.o, self.bus = outputs, bus
        self.jobs = {}
        self._lock = threading.Lock()
        self._engine_ai = None

    def engine_has_ai(self):
        """``python -m vstudio.project ai`` exists (probed once)."""
        if self._engine_ai is None:
            ok = False
            if self.o.runner is not None and self.o.real():
                try:
                    txt = self.o.runner.sibling("vstudio.project").text(["ai", "--help"])
                    ok = "--instruction" in txt and "--outputs" in txt and "invalid choice" not in txt
                except Exception:  # noqa: BLE001
                    ok = False
            self._engine_ai = ok
        return self._engine_ai

    # ---------------------------------------------------------- API
    def start(self, item_id, prompt, clips=None, context=None):
        need(isinstance(prompt, str) and 0 < len(prompt.strip()) <= 500, "prompt: 1-500 chars")
        need(clips is None or (isinstance(clips, list) and 0 < len(clips) <= 60 and all(isinstance(x, str) for x in clips)),
             "clips: clip ids")
        need(context is None or (isinstance(context, dict) and len(json.dumps(context)) < 4000), "context: an object")
        e = self.o._entry(item_id)
        from .outputs import list_clips
        allc = [c for c in list_clips(e) if not c.get("extra") and c.get("files") and
                c.get("state") not in ("queued", "running")]
        if clips:
            allc = [c for c in allc if c["id"] in clips]
        need(allc, "no finished clips to change")
        job = hashlib.sha1(f"{item_id}{prompt}{time.time()}".encode()).hexdigest()[:10]
        j = dict(job=job, item=item_id, prompt=prompt.strip(), state="running", stages=[], notices=[], partial=None,
                 started=time.time(), result=None, error=None, proc=None, stop=threading.Event(),
                 timeout=ENGINE_TIMEOUT, clips=[c["id"] for c in allc])
        with self._lock:
            self.jobs[job] = j
            for k in [k for k, v in self.jobs.items() if v["state"] != "running" and time.time() - v["started"] > 3600]:
                self.jobs.pop(k, None)
        threading.Thread(target=self._run, args=(j, e, allc, context), daemon=True).start()
        return dict(ok=True, job=job, clips=j["clips"], timeout=j["timeout"])

    def get(self, job):
        need(isinstance(job, str) and re.match(r"^[0-9a-f]{10}$", job), "job: an id")
        j = self.jobs.get(job)
        if not j:
            raise KeyError(f"no project ask {job}")
        return self._public(j)

    def stop(self, job):
        need(isinstance(job, str) and re.match(r"^[0-9a-f]{10}$", job), "job: an id")
        j = self.jobs.get(job)
        if not j:
            raise KeyError(f"no project ask {job}")
        j["stop"].set()
        killed = self._kill(j)
        if j["state"] == "running":
            j["state"] = "cancelled"
            self._emit(j, event="cancelled")
        return dict(ok=True, job=job, killed=killed)

    def regenerate(self, item_id, items):
        need(isinstance(items, list) and 0 < len(items) <= 60 and all(isinstance(x, str) and re.match(r"^[\w.-]{1,128}$", x)
                                                                   for x in items), "items: item ids")
        e = self.o._entry(item_id)
        if e["kind"] == "project" and self.o.runner is not None and self.o.real():
            subprocess.Popen([self.o.runner.python, "-m", "vstudio.project", "run", "--dir", e["dir"], "--items",
                              ",".join(items), "--json"], env=self.o.runner.env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return dict(ok=True, started=True, items=items)
        return dict(ok=True, started=False, simulated=True, items=items)

    # ---------------------------------------------------------- internals
    def _public(self, j):
        return {k: v for k, v in j.items() if k not in ("proc", "stop")} | dict(
            elapsed=round((j.get("ended") or time.time()) - j["started"], 1))

    def _emit(self, j, **ev):
        if self.bus:
            self.bus.publish("project-ask", item=j["item"], job=j["job"], **ev)

    def _stage(self, j, stage, **kw):
        j["stages"].append(dict(stage=stage, at=round(time.time() - j["started"], 2), **kw))
        self._emit(j, event="stage", stage=stage, **kw)

    def _kill(self, j):
        p = j.get("proc")
        if p is None or p.poll() is not None:
            return False
        from .proc import kill_tree
        kill_tree(p, signal.SIGTERM)                  # the engine + the model CLI it started
        try:
            p.wait(timeout=3)
        except subprocess.TimeoutExpired:
            kill_tree(p, getattr(signal, "SIGKILL", signal.SIGTERM))
        return True

    def _finish(self, j, result=None, error=None):
        if j["state"] != "running":                   # cancelled meanwhile: keep it cancelled
            return
        j["ended"] = time.time()
        if error:
            j.update(state="failed", error=error)
            self._emit(j, event="failed", error=error)
        else:
            j.update(state="done", result=result)
            self._emit(j, event="done", answer=result.get("answer"))

    def _run(self, j, e, clips, context):
        try:
            ids = {}
            if e["kind"] != "batch" and self.engine_has_ai():
                for c in clips:
                    oid = self.o._output_id(e, c)
                    if oid:
                        ids[oid] = c
            if ids and len(ids) == len(clips):
                self._run_engine(j, e, ids, context)
            else:
                self._run_desk(j, e, clips, context)
        except Exception as ex:  # noqa: BLE001
            doc = getattr(ex, "doc", None)
            self._finish(j, error=doc if isinstance(doc, dict) and doc.get("code") else
                         _m("ask-failed", str(ex)[:300], "AI 修改失败", error=str(ex)[:300]))

    def command(self, e, j, ids, context):
        """The engine command (tests replace it)."""
        r = self.o.runner
        cmd = [r.python, "-m", "vstudio.project", "ai", "--project", e["dir"], "--instruction", j["prompt"],
               "--outputs", ",".join(ids), "--json-events", "--timeout", f"{j['timeout']:g}"]
        if context:
            cmd += ["--context", json.dumps(context, ensure_ascii=False)]
        return cmd, r.env

    def _run_engine(self, j, e, ids, context):
        cmd, env = self.command(e, j, list(ids), context)
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, text=True,
                             env=env, start_new_session=True)
        j["proc"] = p
        if j["stop"].is_set():
            self._kill(j)
        # watchdog: every provider has its own timeout + fallback; past that, the whole call is stopped
        limit = j["timeout"] * 3 + WATCHDOG_GRACE
        def watchdog():
            if p.poll() is None and not j["stop"].is_set():
                j["notices"].append(dict(kind="watchdog", seconds=limit))
                self._kill(j)
        wd = threading.Timer(limit, watchdog)
        wd.daemon = True
        wd.start()
        result, fail = None, None
        for line in p.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("event") == "stage":
                self._stage(j, ev.get("stage"), n=ev.get("n"), provider=ev.get("provider"))
            elif ev.get("event") == "partial":         # the rule answer, before the model call: shown at once
                j["partial"] = self._map(dict(needs_rerender=ev.get("needs_rerender")), ids)["needs_rerender"]
                self._emit(j, event="partial")
            elif ev.get("event") == "fallback":
                n = dict(kind="fallback", **{"from": ev.get("from")}, to=ev.get("to"), code=ev.get("code"),
                         at=round(time.time() - j["started"], 2))
                j["notices"].append(n)
                self._emit(j, event="fallback", **{k: v for k, v in n.items() if k != "kind"})
            elif ev.get("event") == "done":
                result = ev.get("result")
            elif ev.get("event") == "failed":
                fail = {k: ev.get(k) for k in ("code", "message", "message_zh", "params")}
        p.wait()
        wd.cancel()
        if j["stop"].is_set():
            return
        if result:
            self._finish(j, self._map(result, ids))
        elif any(n["kind"] == "watchdog" for n in j["notices"]):
            self._finish(j, error=_m("ask-timeout", f"no answer after {int(limit)} s: stopped", f"{int(limit)} 秒没有回答，已停止",
                                     seconds=int(limit)))
        else:
            self._finish(j, error=fail or _m("ask-failed", f"the engine exited {p.returncode}", "AI 修改失败",
                                             code=p.returncode))

    @staticmethod
    def _map(r, ids):
        """Engine output ids -> desk clip ids (groups, needs_rerender)."""
        def cid(oid):
            c = ids.get(oid)
            return c["id"] if c else None
        groups = []
        for g in r.get("groups") or []:
            c = cid(g.get("output"))
            if not c:
                continue
            props = [dict(id=f"p{i + 1}", op=p.get("normalized") or p.get("op"), describe=p.get("describe"),
                          why=p.get("why")) for i, p in enumerate(g.get("proposed") or []) if isinstance(p, dict)]
            groups.append(dict(clip=c, title=ids[g["output"]]["title"], mode=g.get("mode"), proposals=props,
                               dropped=g.get("dropped") or [], summary=g.get("summary"), source=g.get("source")))
        nr = r.get("needs_rerender")
        if isinstance(nr, dict):
            cl = [cid(x) for x in nr.get("outputs") or []]
            nr = dict(nr, clips=[x for x in cl if x], titles=[ids[x]["title"] for x in nr.get("outputs") or [] if x in ids])
        return dict(answer=r.get("answer"), groups=groups, needs_rerender=nr, summary=r.get("summary"),
                    warnings=r.get("warnings") or [], provider=r.get("provider"), model=r.get("model"),
                    routed=r.get("routed"), fallback=r.get("fallback"), failed=r.get("failed"), cost_usd=r.get("cost_usd"),
                    seconds=r.get("seconds"), model_called=bool(r.get("model_called")), engine="real")

    def _run_desk(self, j, e, clips, context):
        from .outputs import propose
        self._stage(j, "read", n=len(clips))
        docs = []
        for c in clips:
            if j["stop"].is_set():
                return
            docs.append((c, self.o.show(j["item"], c["id"])))
        self._stage(j, "check", n=len(docs))
        cls = classify(j["prompt"])
        zh = bool(re.search(r"[一-鿿]", j["prompt"]))
        groups, blocked, ask = [], [], []
        for c, d in docs:
            flat = d.get("mode") != "pipeline"
            if cls["kind"] == "caption-restyle" and flat:
                blocked.append(c)
                continue
            if cls["kind"] in ("text-remove", "text-replace"):
                keys = [_norm(s) for s in cls["stems"] if _norm(s)]
                tb = (d.get("title_band") or {}).get("text") if isinstance(d.get("title_band"), dict) else None
                if tb and any(k in _norm(tb) for k in keys) and cls["kind"] == "text-remove":
                    groups.append(dict(clip=c["id"], title=c["title"], mode=d.get("mode"), source="rules", dropped=[],
                                       summary=None, proposals=[dict(id="p1", op=dict(op="title", text=""),
                                                                     describe=_m("op-title", "remove the title band",
                                                                                 "去掉标题条"), why=None)]))
                    continue
                said = _norm("".join(w["w"] for w in d.get("words") or []))
                spoken = bool(said) and any(k in said for k in keys)
                filler = all(k in _FILLERS for k in keys)
                if flat and not spoken and not filler:
                    blocked.append(c)
                    continue
            ask.append((c, d))
        if ask:
            self._stage(j, "ask", n=len(ask), provider="rules")
            delay = float(os.environ.get("DESK_PROJECT_ASK_DELAY") or 0)        # e2e: a slow model, to cancel
            end = time.time() + delay
            while time.time() < end:
                if j["stop"].is_set():
                    return
                time.sleep(0.05)
            for c, d in ask:
                r = propose(d, j["prompt"], None)
                if r.get("proposals"):
                    groups.append(dict(clip=c["id"], title=c["title"], mode=d.get("mode"), source="rules",
                                       proposals=r["proposals"], dropped=[], summary=None))
        if j["stop"].is_set():
            return
        self._stage(j, "plan", n=len(groups))
        nr = None
        if blocked:
            stems = cls.get("stems") or []
            if cls["kind"] == "caption-restyle":
                reason = _m("burned-captions-restyle", "the captions are burned into these clips (no clean master), so "
                            "their style cannot be changed here", "这些片子的字幕是烧进画面的（没有干净母版），这里改不了字幕样式",
                            n=len(blocked))
            else:
                label = "、".join(f"「{s}」" for s in stems)
                reason = _m("burned-text", f"{', '.join(stems) or 'the text'} is burned into the picture of these clips "
                            "(flattened files, no clean master), so the editor cannot remove or replace it",
                            f"{label or '这段文字'}是烧进画面里的（成片已合成、没有干净母版），编辑器去不掉也换不了",
                            text=", ".join(stems), n=len(blocked))
            nr = dict(clips=[c["id"] for c in blocked], titles=[c["title"] for c in blocked], code=reason["code"],
                      reason=reason, targets=stems, rule=True, paths=_desk_paths(e, blocked, cls, zh))
        has = [g for g in groups if g["proposals"]]
        answer = "mixed" if has and nr else "changes" if has else "needs_rerender" if nr else "nothing"
        warnings = [] if has or nr else [_m("not-understood", "try: tighter, 1.2x, a progress bar, a Douyin version",
                                            "这句我还没看懂。可以试试：再紧凑一点 / 1.2 倍速 / 加进度条 / 出抖音版")]
        self._finish(j, dict(answer=answer, groups=groups, needs_rerender=nr, summary=None, warnings=warnings,
                             provider="rules", model=None, fallback=None, cost_usd=0.0,
                             seconds=round(time.time() - j["started"], 2), model_called=False, engine="desk"))
