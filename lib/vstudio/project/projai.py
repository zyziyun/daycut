"""Project-level AI edits: ``python -m vstudio.project ai --project P --instruction T [--outputs all|a,b]``.

One request for every output of a project / work folder ("remove the series label from all clips"):

  1. read      every targeted output (resolve + edit doc; cached transcripts only, nothing transcribed)
  2. check     a cheap rule check before any model call (``precheck``): a request to remove / replace text that is
               burned into a flattened output, or to restyle burned captions, can never be done by the editor.
               Those outputs get a structured ``needs_rerender`` answer right away (no model call, < 2 s): which
               outputs, why, and the real path - re-render from the folder's work scripts (the lines that hold
               the text are listed), "regenerate" through the recipe, or re-export from the original editor -
               each with actions the desk shows as buttons. Text WE added (title band, an effect's text, an added
               caption) is removed with plain ops, also without the model.
  3. ask       the rest goes to ONE model call (task ``output_edit``) with every output's summary; the reply is
               grouped per output and every op is validated against that output's capabilities (``normalize``).
  4. plan      -> {answer changes | needs_rerender | mixed | nothing, groups [{output, proposed, dropped}],
               needs_rerender {...}, apply_all {outputs, ops}, provider, fallback, seconds, model_called}
               The rule answer is sent as a `partial` event before the model call and kept if the call fails.

``timeout`` (default 120 s) bounds each provider; a timed-out / failed provider falls back along the route's chain
(``llm.complete``), reported live (``on_event`` {event: fallback}) and in the result (``fallback``).
Nothing is applied here: the desk applies a group with ``output edit`` (one undo step per output).
"""
import json
import os
import re
import time

from vstudio.batch.util import read_json

from . import outputs as O

DEFAULT_TIMEOUT = 120.0
MAX_OUTPUTS = 40

# --------------------------------------------------------------------------- the cheap classifier
_REMOVE = r"去掉|去除|删掉|删除|拿掉|移除|抹掉|不要|别要|隐藏|取消|remove|delete|drop|hide|get rid of|take (?:out|off)|strip"
_REPLACE = r"改成|换成|替换|改为|改叫|replace|rename|change\s+.{1,40}?\s+to\b"
_TEXT_NOUN = (r"文字|字样|标题|小标题|标签|角标|水印|编号|序号|系列名|系列标|大字|字卡|贴字|logo|kicker|"
              r"\btext\b|\btitle\b|\blabel\b|\btag\b|watermark|numbering|series (?:name|label|tag)")
_CAPTION = r"字幕|caption|subtitle"
_RESTYLE = (r"样式|颜色|字体|字号|大小|大一点|小一点|大些|小些|粗|描边|位置|往上|往下|挪|换个|style|font|colou?r|size|"
            r"bigger|smaller|bold|outline|position|move")
# things a cut / trim / effect request names - never burned text
_EDIT_WORDS = (r"开头|结尾|片头|片尾|停顿|气口|口误|口头禅|重复|这段|这里|这部分|前\s*\d|后\s*\d|\d+\s*秒|音乐|bgm|配乐|背景音|"
               r"进度条|效果|特效|转场|黑屏|空白|废话|intro|outro|pause|silence|music|filler|seconds?|\d+\s*s\b|"
               r"progress bar|effect|transition")
_FILL = r"都|全都|全部|所有|这些|那些|上面的|画面上的|画面里的|里面的|的|一下|掉|给我|帮我|请|all|the|every|from|of|clips?"
_SEP = r"[，,、/／\s]+|和|与|及|以及|跟|还有|\band\b"


def _cjk(s):
    return bool(re.search(r"[一-鿿]", s or ""))


def _targets(text):
    """The text she wants gone / replaced: quoted strings, else the object of 把…去掉 / remove …."""
    q = re.findall(r"[「“\"『'‘]([^」”\"』'’]{1,40})[」”\"』'’]", text)
    if q:
        return [x.strip() for x in q if x.strip()]
    m = (re.search(rf"把(.{{1,60}}?)(?:都|全都|全部)?(?:{_REMOVE}|{_REPLACE})", text, re.I)
         or re.search(rf"(?:{_REMOVE})\s*(?:掉)?\s*(.{{1,60}}?)(?:[。！!？?；;]|$|这|，这|, ?(?:this|it))", text, re.I))
    if not m:
        return []
    obj = m.group(1)
    out = []
    for tok in re.split(_SEP, obj):
        tok = re.sub(rf"^(?:{_FILL})+|(?:{_FILL})+$", "", tok.strip(), flags=re.I).strip(" .。")
        if tok:
            out.append(tok)
    return out


def _stems(targets):
    """'副业复盘01', '02', '03' -> ['副业复盘']: numbering stripped, bare numbers dropped."""
    out = []
    for t in targets:
        s = re.sub(r"\s*(?:#|No\.?|第)?\s*[0-9０-９]+\s*(?:期|集|篇|号)?$", "", t).strip(" -_·.")
        if len(s) >= 2 and s not in out:
            out.append(s)
    return out


def classify(text):
    """Instruction -> {kind: text-remove | text-replace | caption-restyle | None, targets, stems, noun}."""
    t = text or ""
    remove = re.search(_REMOVE, t, re.I)
    replace = re.search(_REPLACE, t, re.I)
    noun = bool(re.search(_TEXT_NOUN, t, re.I))
    caption = bool(re.search(_CAPTION, t, re.I))
    if caption and re.search(_RESTYLE, t, re.I) and not remove and not replace:
        return dict(kind="caption-restyle", targets=[], stems=[], noun=True)
    if not (remove or replace):
        return dict(kind=None, targets=[], stems=[], noun=noun)
    targets = _targets(t)
    if caption and not targets:
        targets = ["字幕" if _cjk(t) else "captions"]
    if not targets and not noun:
        return dict(kind=None, targets=[], stems=[], noun=False)
    if re.search(_EDIT_WORDS, " ".join(targets) or t, re.I) and not noun:
        return dict(kind=None, targets=targets, stems=[], noun=False)
    return dict(kind="text-replace" if replace and not remove else "text-remove", targets=targets,
                stems=_stems(targets) or targets, noun=noun, captions=caption)


# --------------------------------------------------------------------------- per-output facts (fast: no media work)
def _cached_words(doc):
    tr = read_json(os.path.join(doc.dir, "transcript.json"), None)
    if isinstance(tr, dict) and tr.get("sig") == doc.d.get("source_sig"):
        return tr.get("words") or []
    for c in (doc.rec["file"] + ".asr.json", os.path.splitext(doc.rec["file"])[0] + ".asr.json"):
        d = read_json(c, None)
        if isinstance(d, dict):
            W = []
            for seg in d.get("segments") or []:
                W += [dict(w=str(w.get("word") or w.get("w") or "").strip(), t=float(w.get("start", w.get("t", 0))),
                           te=float(w.get("end", w.get("te", 0)))) for w in seg.get("words") or []]
            W = W or [dict(w=str(w.get("word") or w.get("w") or ""), t=float(w.get("start", w.get("t", 0))),
                           te=float(w.get("end", w.get("te", 0)))) for w in d.get("words") or []]
            if W:
                return W
    return []


def _norm(s):
    return re.sub(r"[\s，,。.、！!？?：:；;\"'「」“”]+", "", str(s or "")).lower()


def _ours(st, stems):
    """Text this editor added (title band, effect text params, added captions) that matches -> ops removing it."""
    ops = []
    keys = [_norm(x) for x in stems if _norm(x)]

    def hit(v):
        v = _norm(v)
        return bool(v) and any(k in v or v in k for k in keys)
    if st.get("title") and hit((st["title"] or {}).get("text")):
        ops.append(dict(op="title", text=""))
    for e in st.get("effects") or []:
        if any(isinstance(v, str) and hit(v) for v in (e.get("params") or {}).values()):
            ops.append(dict(op="effect_remove", id=e["id"]))
    for a in (st.get("captions") or {}).get("added") or []:
        if hit(a.get("text")):
            ops.append(dict(op="caption_remove", cue=a["id"]))
    return ops


def _spoken(words, stems):
    joined = _norm("".join(w["w"] for w in words or []))
    return bool(joined) and any(_norm(s) and _norm(s) in joined for s in stems)


_FILLERS = {"嗯", "啊", "呃", "额", "那个", "就是", "然后", "其实", "对吧", "um", "uh", "like", "you know"}


def _burned_evidence(cls, words, source_hits):
    """A flattened output really carries this text in the picture (not in what is said): a text noun (标题 /
    水印 / label ...), the text found in the folder's own scripts, or a transcript that does not contain it."""
    stems = cls.get("stems") or []
    if _spoken(words, stems) or all(_norm(s) in _FILLERS for s in stems):
        return False
    return bool(cls.get("noun") or cls.get("captions") or source_hits or
                (words and any(len(_norm(s)) >= 2 for s in stems)))


# --------------------------------------------------------------------------- where the burned text comes from
_TEXT_EXT = {".py", ".json", ".yaml", ".yml", ".txt", ".md", ".ass", ".srt", ".vtt", ".toml", ".js", ".ts", ".html",
             ".css", ".sh"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".vstudio", "cache", "frames", "renders", "state"}


def _source_hits(d, stems, limit=24):
    """Lines in the folder's own scripts / configs that hold the text (work scripts, clip definitions) and the
    entry scripts that render -> (hits [{file, line, text}], scripts [rel])."""
    hits, scripts, seen = [], [], 0
    keys = [s for s in stems if s]
    for root, dirs, files in os.walk(d):
        rel_root = os.path.relpath(root, d)
        depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
        dirs[:] = [x for x in sorted(dirs) if x not in _SKIP_DIRS and not x.startswith(".") and depth < 3]
        for fn in sorted(files):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _TEXT_EXT or fn.endswith(".asr.json") or fn.startswith("."):
                continue
            p = os.path.join(root, fn)
            rel = os.path.relpath(p, d)
            try:
                if os.path.getsize(p) > 512 * 1024:
                    continue
            except OSError:
                continue
            seen += 1
            if seen > 600:
                return hits, scripts
            if ext in (".py", ".sh", ".js") and (rel.startswith("work" + os.sep) or rel.startswith("scripts" + os.sep)):
                scripts.append(rel)
            if not keys or ext in (".md", ".txt"):
                continue                                           # notes / post copy: not what draws the picture
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if any(k in line for k in keys):
                            hits.append(dict(file=rel, line=i, text=line.strip()[:160]))
                            if len(hits) >= limit:
                                return hits, scripts
            except OSError:
                continue
    return hits, scripts


def _paths(d, kind, recs, cls, zh):
    """The real ways to get the change: re-render from the work scripts, regenerate via the recipe, or re-export."""
    stems = cls.get("stems") or []
    label = "、".join(f"「{s}」" for s in stems) if zh else ", ".join(f"“{s}”" for s in stems)
    out = []
    if kind == "project":
        items = sorted({r["item"] for r in recs if r.get("item")})
        cmd = f"python -m vstudio.project run --dir {d} --items {','.join(items)}"
        out.append(dict(kind="regenerate", items=items, command=cmd,
                        message=O.msg("path-regenerate", "regenerate these clips through the recipe (change the "
                                      "parameter that adds the text first)", "用配方重新生成这几条（先改掉加这段文字的参数）",
                                      n=len(items)),
                        actions=[dict(kind="regenerate", items=items,
                                      label=O.msg("act-regenerate", "Regenerate these clips", "重新生成这几条",
                                                  n=len(items)))]))
    hits, scripts = _source_hits(d, stems, limit=60) if kind == "work" else ([], [])
    tags = {p for r in recs for p in os.path.relpath(os.path.dirname(r["file"]), d).split(os.sep)
            if p not in (".", "final", "exports", "out")}             # final/v2/A.mp4 -> work/v2/ scripts first
    hits.sort(key=lambda h: (0 if tags & set(h["file"].split(os.sep)) else 1))
    hits = hits[:24]
    if kind == "work" and (hits or scripts):
        files = list(dict.fromkeys(h["file"] for h in hits))
        names = ", ".join(os.path.splitext(os.path.basename(r["file"]))[0] for r in recs)
        where = "; ".join(f"{h['file']}:{h['line']}" for h in hits[:8])
        if zh:
            how = "按要求替换" if cls.get("kind") == "text-replace" else "不要再加"
            prompt = (f"在 {d} 里，把画面上烧进去的{label or '这段文字'}去掉（{how}），"
                      f"然后用 work/ 里的脚本重新渲染这几条：{names}。"
                      + (f"文字出现在：{where}。" if where else "")
                      + "渲染完覆盖 final/ 里对应的成片，保持其他一切不变。")
        else:
            prompt = (f"In {d}, remove the burned-in {label or 'text'} from the picture"
                      f"{' (replace it as asked)' if cls.get('kind') == 'text-replace' else ''}, then re-render these "
                      f"clips with the scripts in work/: {names}."
                      + (f" The text is set in: {where}." if where else "")
                      + " Overwrite the matching files in final/ and keep everything else the same.")
        acts = [dict(kind="copy-prompt", prompt=prompt,
                     label=O.msg("act-copy-prompt", "Copy instructions for Claude Code", "复制给 Claude Code 的指令"))]
        for f in files[:3]:
            h = next(x for x in hits if x["file"] == f)
            acts.append(dict(kind="open-file", file=os.path.join(d, f), line=h["line"],
                             label=O.msg("act-open-file", f"Open {os.path.basename(f)}", f"打开 {os.path.basename(f)}",
                                         file=os.path.basename(f), line=h["line"])))
        out.append(dict(kind="rerender-scripts", files=hits, scripts=scripts[:20], prompt=prompt,
                        message=O.msg("path-rerender-scripts", "this folder has the scripts that made the clips: "
                                      "change the text there and re-render", "这个文件夹里有做这些片子的脚本：在脚本里去掉这段文字再重新渲染",
                                      n=len(hits)),
                        actions=acts))
    if not out:
        out.append(dict(kind="re-export", message=O.msg(
            "path-re-export", "no source pipeline is kept for these clips: re-export them without the text from the "
            "editor they were made in (or cover it with a title band here)",
            "这些片子没有保留可重渲染的源工程：请在做它们的剪辑软件里去掉文字后重新导出（或在这里用标题条盖住）"),
            actions=[dict(kind="reveal", file=recs[0]["file"] if recs else d,
                          label=O.msg("act-reveal", "Show in folder", "在文件夹中显示"))]))
    return out


# --------------------------------------------------------------------------- the model call
SYSTEM = """You edit SEVERAL finished short videos of one project at once, by proposing edit operations as JSON per
output. You never render anything.
Rules:
- One group per output that needs changes; only the outputs listed. A request about "all clips" applies to each.
- Use only the ops listed and only effect ids from the effect catalogue (never invent an effect, op or param).
- Times are seconds on each output's ORIGINAL timeline; positions are fractions of the canvas.
- Respect each output's capability flags. A flattened output (no clean master) cannot remove, replace or restyle
  text that is burned into the picture: list such outputs in needs_rerender with the reason instead of ops.
- Prefer few, purposeful ops.
Return {"summary": "<one sentence>", "groups": [{"output": "<id>", "ops": [{"op": ...}], "summary": "..."}],
"needs_rerender": {"outputs": ["<id>"], "why": "..."}}."""

SCHEMA = {"type": "object", "properties": {
    "summary": {"type": "string"},
    "groups": {"type": "array", "items": {"type": "object", "properties": {
        "output": {"type": "string"}, "ops": {"type": "array", "items": {"type": "object"}},
        "summary": {"type": "string"}}, "required": ["output", "ops"]}},
    "needs_rerender": {"type": "object", "properties": {"outputs": {"type": "array", "items": {"type": "string"}},
                                                        "why": {"type": "string"}}}},
    "required": ["groups"]}


def _summary(rec, doc, st):
    caps, _ = O.capabilities(rec, doc.d if rec["mode"] == "flattened" else None)
    rows = O._cue_rows(rec, st)
    if rows:
        lines = [f"[{r['id']}] {r['start']:.1f}-{r['end']:.1f} {r['text']}" for r in rows if not r["removed"]][:60]
    else:
        W = _cached_words(doc)
        lines = []
        if W:
            from vstudio import subs
            lines = [f"{c.start:.1f}-{c.end:.1f} {c.text}" for c in subs.cues_from_words(W, max_chars=24)][:60]
    keep = ("mode", "captions_ours", "caption_text", "caption_restyle_burned", "caption_add", "burned_captions",
            "relayout", "audio")
    return dict(id=rec["id"], title=rec.get("title"), duration=round(rec["info"]["duration"], 2),
                canvas=[rec["info"]["w"], rec["info"]["h"]], caps={k: caps.get(k) for k in keep},
                state=dict(trim=st["trim"], cuts=len(st["cuts"]), speed=st["speed"], title=st["title"],
                           effects=[dict(id=e["id"], effect=e["effect"], start=e["start"]) for e in st["effects"]]),
                transcript=lines)


def _validate(doc, st, raw_ops):
    proposed, dropped, cur = [], [], st
    for op in raw_ops or []:
        if not isinstance(op, dict):
            dropped.append(dict(op=op, error=O.msg("bad-op", "not an object", "不是对象")))
            continue
        clean = {k: v for k, v in op.items() if k not in ("why", "reason", "description", "output")}
        try:
            n, _, w = O.normalize(doc, cur, clean)
        except O.OutputError as e:
            dropped.append(dict(op=op, error=e.info))
            continue
        cur = O.fold(cur, n)
        proposed.append(dict(op=clean, normalized=n, describe=O.describe(n), why=op.get("why") or op.get("reason"),
                             warnings=w))
    return proposed, dropped


def _pick(rows, outputs):
    if outputs in (None, "", "all", ["all"]):
        return rows
    want = outputs if isinstance(outputs, list) else [x.strip() for x in str(outputs).split(",") if x.strip()]
    out = []
    for w in want:
        r = O._match(rows, w)
        if not r:
            raise O.OutputError("unknown-output", f"no output {w!r} (output list --json shows the ids)",
                                f"没有成片 {w!r}", output=w, known=[x["id"] for x in rows][:50])
        if r not in out:
            out.append(r)
    return out


def plan(d, instruction, outputs=None, context=None, provider=None, model=None, timeout=DEFAULT_TIMEOUT,
         on_event=None):
    """See the module doc. ``on_event(dict)``: stage events {event: stage, stage: read | check | ask | plan, n,
    provider} and {event: fallback, from, to, code}."""
    from vstudio import llm
    t0 = time.time()

    def emit(**ev):
        if on_event:
            try:
                on_event(dict(ev, elapsed=round(time.time() - t0, 2)))
            except Exception:  # noqa: BLE001
                pass
    if not isinstance(instruction, str) or not instruction.strip():
        raise O.OutputError("bad-param", "--instruction is required", "需要 --instruction", name="instruction")
    if context is not None and (not isinstance(context, dict) or len(json.dumps(context, default=str)) > 4000):
        raise O.OutputError("bad-context", "context is a small JSON object", "上下文需要一个小的 JSON 对象")
    d, kind = O._owner(d)
    rows = O.list_outputs(d)["outputs"]
    picked = _pick(rows, outputs)[:MAX_OUTPUTS]
    if not picked:
        raise O.OutputError("no-outputs", "this project has no finished outputs yet", "这个项目还没有成片")
    emit(event="stage", stage="read", n=len(picked))
    loaded = []
    for r in picked:
        rec, doc = O._load(d, r["id"])
        rec["item"] = r.get("item")
        loaded.append((rec, doc, doc.state()))
    zh = _cjk(instruction)

    # ---- 2. the cheap check (no model)
    emit(event="stage", stage="check", n=len(loaded))
    cls = classify(instruction)
    text_ask = cls["kind"] in ("text-remove", "text-replace")
    evidence = _source_hits(d, cls["stems"], limit=1)[0] if kind == "work" and text_ask else []
    groups, blocked, ask = [], [], []
    for rec, doc, st in loaded:
        if cls["kind"] == "caption-restyle":
            if rec["mode"] == "flattened" and not st["captions"]["added"]:
                blocked.append(rec)
                continue
        elif cls["kind"] in ("text-remove", "text-replace"):
            ours = _ours(st, cls["stems"])
            if ours and cls["kind"] == "text-remove":
                prop, drop = _validate(doc, st, ours)
                groups.append(dict(output=rec["id"], title=rec.get("title"), mode=rec["mode"], proposed=prop,
                                   dropped=drop, summary=None, source="rules"))
                continue
            if rec["mode"] == "flattened" and _burned_evidence(cls, _cached_words(doc), evidence):
                blocked.append(rec)
                continue
        ask.append((rec, doc, st))

    needs = None
    if blocked:
        stems = cls.get("stems") or []
        label = "、".join(f"「{s}」" for s in stems) if stems else ""
        if cls["kind"] == "caption-restyle":
            reason = O.msg("burned-captions-restyle", "the captions are burned into these clips (no clean master), so "
                           "their style cannot be changed here", "这些片子的字幕是烧进画面的（没有干净母版），这里改不了字幕样式",
                           n=len(blocked))
        else:
            reason = O.msg("burned-text", f"{', '.join(stems) or 'the text'} is burned into the picture of these "
                           "clips (flattened files, no clean master), so the editor cannot remove or replace it",
                           f"{label or '这段文字'}是烧进画面里的（成片已合成、没有干净母版），编辑器去不掉也换不了",
                           text=", ".join(stems), n=len(blocked))
        needs = dict(outputs=[r["id"] for r in blocked], titles=[r.get("title") for r in blocked], code=reason["code"],
                     reason=reason, targets=stems, rule=True, paths=_paths(d, kind, blocked, cls, zh))

    # ---- 3. one model call for the rest
    used, cost, summary, warns, model_called = dict(provider="rules", model=None), 0.0, None, [], False
    if ask:
        route = llm.route("output_edit", provider, model)
        if route.provider == "none":
            for rec, doc, st in ask:
                prop, drop = _validate(doc, st, O._rule_ops(instruction, rec["info"]["duration"]))
                if prop or drop:
                    groups.append(dict(output=rec["id"], title=rec.get("title"), mode=rec["mode"], proposed=prop,
                                       dropped=drop, summary=None, source="rules"))
            warns.append(O.msg("no-model", "no model is configured for task output_edit: only literal phrases were "
                               "understood", "没有配置 output_edit 模型，只理解了字面指令"))
        else:
            if needs or groups:                      # the rule answer shows right away; the model works on the rest
                emit(event="partial", needs_rerender=needs, groups=[g["output"] for g in groups])
            emit(event="stage", stage="ask", n=len(ask), provider=route.provider)
            fx = [dict(id=r["id"], zh=r["label"]["zh"], en=r["label"]["en"], stage=r["stage"],
                       params=sorted(r["params"])) for r in O.FX.catalogue()]
            ctx = dict(outputs=[_summary(rec, doc, st) for rec, doc, st in ask], ops=O.OP_DOC, effects=fx)
            if context:
                ctx["focus"] = context
            prompt = (f"Instruction from the creator (applies to the whole project):\n{instruction}\n\nContext (JSON):\n"
                      + json.dumps(ctx, ensure_ascii=False, default=str))
            model_called = True
            r, j = None, {}
            try:
                r = llm.complete("output_edit", SYSTEM, prompt, schema=SCHEMA, provider=provider, model=model,
                                 max_tokens=8000, timeout=timeout, cli_timeout=timeout,
                                 on_fallback=lambda fb: emit(event="fallback", **fb))
                j = r.get("json") if isinstance(r.get("json"), dict) else {}
                if not isinstance(j.get("groups"), list):
                    raise O.OutputError("llm-bad-json", "the model did not return {groups: [...]}",
                                        "模型没有返回分组修改", provider=r.get("provider"))
            except Exception as e:  # noqa: BLE001
                fail = e if isinstance(e, O.OutputError) else O.llm_failed(e, route.provider)
                if not (needs or groups):
                    raise fail from e
                warns.append(fail.info)               # keep what the rule check answered
                used = dict(provider=(r or {}).get("provider") or route.provider, model=(r or {}).get("model"),
                            routed=route.provider, fallback=(r or {}).get("fallback"),
                            failed=dict(provider=route.provider, code=llm.failure_code(e)))
                r = None
            if r is not None:
                emit(event="stage", stage="plan", n=len(ask))
                summary = j.get("summary")
                cost = r.get("cost_usd") or 0.0
                used = dict(provider=r.get("provider"), model=r.get("model"), routed=route.provider,
                            fallback=r.get("fallback"))
            by_id = {rec["id"]: (rec, doc, st) for rec, doc, st in ask}
            for g in j.get("groups") or []:
                if not isinstance(g, dict):
                    continue
                hit = by_id.get(g.get("output")) or next(
                    (v for k, v in by_id.items() if O._match([dict(id=k, file=v[0]["file"])], str(g.get("output")))),
                    None)
                if not hit:
                    warns.append(O.msg("unknown-output", f"the model named an unknown output {g.get('output')!r}",
                                       "模型给了不存在的成片", output=g.get("output")))
                    continue
                rec, doc, st = hit
                prop, drop = _validate(doc, st, g.get("ops"))
                groups.append(dict(output=rec["id"], title=rec.get("title"), mode=rec["mode"], proposed=prop,
                                   dropped=drop, summary=g.get("summary"), source="model"))
            nr = j.get("needs_rerender") if isinstance(j.get("needs_rerender"), dict) else None
            more = [by_id[x][0] for x in (nr or {}).get("outputs") or [] if x in by_id]
            more = [x for x in more if not any(g["output"] == x["id"] and g["proposed"] for g in groups)]
            if more:
                why = str(nr.get("why") or "")[:300]
                reason = O.msg("model-needs-rerender", why or "these clips need a re-render for this change",
                               why or "这个修改需要重新渲染这几条", why=why)
                if needs:
                    needs["outputs"] += [x["id"] for x in more]
                    needs["titles"] += [x.get("title") for x in more]
                else:
                    needs = dict(outputs=[x["id"] for x in more], titles=[x.get("title") for x in more],
                                 code=reason["code"], reason=reason, targets=cls.get("stems") or [], rule=False,
                                 paths=_paths(d, kind, more, cls, zh))

    groups = [g for g in groups if g["proposed"] or g["dropped"]]
    order = {r["id"]: i for i, r in enumerate(picked)}
    groups.sort(key=lambda g: order.get(g["output"], 1e9))
    for g in groups:
        g["ops"] = [p["op"] for p in g["proposed"]]
    has = [g for g in groups if g["proposed"]]
    answer = "mixed" if has and needs else "changes" if has else "needs_rerender" if needs else "nothing"
    return dict(ok=True, scope="project", dir=d, kind=kind, instruction=instruction, answer=answer,
                outputs=[dict(id=rec["id"], title=rec.get("title"), mode=rec["mode"]) for rec, _, _ in loaded],
                groups=groups, needs_rerender=needs,
                apply_all=dict(outputs=[g["output"] for g in has], ops=sum(len(g["proposed"]) for g in has)),
                classified=cls["kind"], model_called=model_called, summary=summary, warnings=warns, cost_usd=cost,
                seconds=round(time.time() - t0, 2), **used)
