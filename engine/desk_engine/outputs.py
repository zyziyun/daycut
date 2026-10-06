"""Outputs: every finished clip of a project / batch / work folder, its player data and second-pass editing.

Engine contract: ``python -m vstudio.project output list|show|edit|ai|render|undo|redo|effects --json`` (engine
references/OUTPUT_EDIT.md). The desk probes ``output --help`` once; when the verbs exist every call for a project /
work folder goes to the engine. Otherwise (mock mode, an older engine, or an owner the engine does not know, such
as a plain vstudio.batch folder) this module's implementation runs with the SAME op vocabulary, step-based
undo / redo and ``{code, params, message, message_zh}`` descriptions, so the UI does not care which one answered.

The desk always returns one normalised document per clip (``show``):
  {id, item, title, state, output_id, file, files, cover, post, duration, fps, w, h, mode, caps, caps_notes,
   words, waveform, captions [{id, start, end, text, added, removed}], effects [{id, effect, start, end, params,
   label {en, zh}}], trim {start, end} | null, cuts [{start, end, index}], speed, title_band, cover_edit, exports
   [{target, layout}], steps [{id, at, by, describe [...]}], undo, redo, renders [{target, quality, file, fresh}],
   warnings, engine real|desk}

The desk implementation keeps its edit log in ``<DESK_DATA_DIR>/outputs/<key>.json`` (never in the creator's
folder) and cannot re-render: ``render`` reports ``simulated: true`` with the same files.
"""
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time

from . import works as WK
from .common import BadRequest, need, read_json, write_json

OPS = ("trim", "cut", "cut_remove", "speed", "loudness", "captions", "caption_text", "caption_style", "caption_add",
       "caption_remove", "caption_placement", "title", "effect_add", "effect_update", "effect_remove", "cover",
       "export_add", "export_remove", "reset")
TARGET_RE = re.compile(r"^([a-z][a-z-]{1,30}(:[a-z]{3,12})?|\d{1,2}:\d{1,2})$")


class EngineMessage(BadRequest):
    """An engine refusal with its code (exit 5 + {ok: false, code, params, message, message_zh})."""

    def __init__(self, doc):
        super().__init__(doc.get("message") or doc.get("error") or doc.get("code") or "engine error")
        self.doc = {k: doc.get(k) for k in ("code", "params", "message", "message_zh")}


def _m(code, en, zh, **params):
    return dict(code=code, params=params, message=en, message_zh=zh)


# ------------------------------------------------------------------ effects catalogue (desk copy of the engine's)
def _num(default, lo, hi, zh):
    return dict(type="number", default=default, minimum=lo, maximum=hi, **{"x-zh": zh})


def _str(default, zh, enum=None, required=False, fmt=None):
    d = dict(type="string", default=default, **{"x-zh": zh})
    if enum:
        d["enum"] = enum
    if required:
        d["required"] = True
    if fmt:
        d["format"] = fmt
    return d


EFFECTS = [
    dict(id="pop-words", label=dict(en="Pop word", zh="弹出大字"), category="text", stage="frame", default_dur=1.2,
         description=dict(en="Big stroked word with a bounce", zh="一个大字 / 短词带描边弹出（重点词）"),
         params=dict(text=_str("", "文字", required=True), color=_str(None, "颜色", fmt="color"),
                     size=_num(0.11, 0.04, 0.25, "字号"), anim=_str("pop", "动画", ["pop", "slam", "slide", "fade", "none"]))),
    dict(id="stacking-stamps", label=dict(en="Stamp", zh="印章"), category="highlight", stage="frame", default_dur=1.5,
         description=dict(en="A stamp slams in (tested / key point)", zh="白底描边印章砸入（亲测 / 划重点）"),
         params=dict(text=_str("", "文字", required=True), angle=_num(8, -30, 30, "角度"), scale=_num(1.0, 0.4, 3.0, "大小"))),
    dict(id="punch-in", label=dict(en="Punch-in zoom", zh="推镜放大"), category="camera", stage="frame", default_dur=3.0,
         description=dict(en="Scales up for a window, then back", zh="画面缓推放大一段时间再回来（强调一句话）"),
         params=dict(scale=_num(1.14, 1.02, 1.4, "放大倍数"), hold=_str("return", "结束方式", ["return", "stay"]))),
    dict(id="quote-card", label=dict(en="Quote card", zh="金句卡"), category="text", stage="frame", default_dur=3.0,
         description=dict(en="A card with a key sentence", zh="一张金句卡片"),
         params=dict(text=_str("", "文字", required=True), speaker=_str("", "说话人"))),
    dict(id="callout-bubble", label=dict(en="Callout", zh="标注气泡 / 箭头"), category="highlight", stage="frame",
         default_dur=2.5, description=dict(en="A bubble with an arrow", zh="带箭头的标注气泡"),
         params=dict(text=_str("", "文字", required=True))),
    dict(id="chapter-card", label=dict(en="Chapter card", zh="章节卡"), category="structure", stage="frame",
         default_dur=1.5, description=dict(en="A chapter title card", zh="章节标题卡"),
         params=dict(title=_str("", "标题", required=True))),
    dict(id="notes-panel", label=dict(en="Notes panel", zh="记笔记面板"), category="text", stage="frame", default_dur=4.0,
         description=dict(en="Key points on a side card", zh="屏幕一侧出现要点卡片"),
         params=dict(title=_str("", "标题"), bullets=_str("", "要点（一行一条）"))),
    dict(id="overlay-images", label=dict(en="Sticker / tag", zh="贴纸 / 标签"), category="highlight", stage="frame",
         default_dur=2.0, description=dict(en="A sticker, tag or badge", zh="贴纸、标签或角标"),
         params=dict(text=_str("", "文字"), style=_str("tag", "样式", ["tag", "chip", "badge", "star", "image"]))),
    dict(id="badge", label=dict(en="Corner badge", zh="角标"), category="highlight", stage="frame", default_dur=3.0,
         description=dict(en="A small corner label (e.g. picked)", zh="角落里的小标签（如「精选」）"),
         params=dict(text=_str("精选", "文字"))),
    dict(id="red-box", label=dict(en="Highlight box", zh="框选高亮"), category="highlight", stage="frame",
         default_dur=2.0, description=dict(en="A box around the key part", zh="一个框圈出画面里的重点"),
         params=dict(color=_str("#FF3B30", "颜色", fmt="color"))),
    dict(id="progress-bar-pil", label=dict(en="Progress bar", zh="进度条"), category="structure", stage="frame",
         default_dur=0, whole=True, description=dict(en="A progress bar with chapters", zh="底部进度条，可带章节"),
         params=dict(style=_str("line", "样式", ["line", "chapters"]))),
    dict(id="sfx-placement", label=dict(en="Sound effect", zh="音效"), category="audio", stage="audio", default_dur=0.5,
         description=dict(en="A short sound effect", zh="一个短音效"),
         params=dict(name=_str("ding", "音效", ["ding", "whoosh", "pop", "click"]), gain=_num(0.0, -24, 6, "音量"))),
    dict(id="music-bed", label=dict(en="Background music", zh="背景音乐"), category="audio", stage="audio",
         default_dur=0, whole=True, description=dict(en="Music under the voice, ducked", zh="人声下面的背景音乐，自动压低"),
         params=dict(duck_db=_num(-12, -30, 0, "压低"))),
    dict(id="xfade-joins", label=dict(en="Transition", zh="转场"), category="transition", stage="timeline",
         default_dur=0.4, description=dict(en="A transition at a cut", zh="剪切点的转场"),
         params=dict(transition=_str("fade", "转场", ["fade", "flash", "dip", "slide"]))),
    dict(id="end-fade", label=dict(en="End fade", zh="结尾淡出"), category="transition", stage="timeline",
         default_dur=0, whole=True, description=dict(en="Fade out at the end", zh="结尾淡出"),
         params=dict(duration=_num(0.8, 0.2, 3.0, "时长"))),
    dict(id="vlog-grade", label=dict(en="Colour grade", zh="调色"), category="grade", stage="timeline", default_dur=0,
         whole=True, description=dict(en="Warmer, punchier colour", zh="更暖、更有层次的色调"),
         params=dict(sat=_num(1.1, 0.5, 1.6, "饱和度"), warm=_num(0.1, -0.5, 0.5, "暖色"))),
]
EFFECT_BY_ID = {e["id"]: e for e in EFFECTS}
ALIASES = {"pop-word": "pop-words", "弹字": "pop-words", "弹出大字": "pop-words", "印章": "stacking-stamps",
           "推近": "punch-in", "progress-bar": "progress-bar-pil", "进度条": "progress-bar-pil"}


# ------------------------------------------------------------------ media facts (ffprobe, cached)
_probe_cache = {}
_probe_lock = threading.Lock()


def _ffprobe():
    for p in (os.environ.get("DESK_FFPROBE"), shutil.which("ffprobe"), "/opt/homebrew/bin/ffprobe",
              "/usr/local/bin/ffprobe"):
        if p and os.path.exists(p):
            return p
    return None


def probe(path):
    """-> {w, h, fps, duration} (empty when ffprobe is missing or the file is not a video)."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    key = (path, st.st_mtime, st.st_size)
    with _probe_lock:
        if key in _probe_cache:
            return _probe_cache[key]
    out = {}
    fp = _ffprobe()
    if fp:
        try:
            r = subprocess.run([fp, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height,r_frame_rate:format=duration", "-of", "json", path],
                               capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
            doc = json.loads(r.stdout or "{}")
            s = (doc.get("streams") or [{}])[0]
            num, _, den = (s.get("r_frame_rate") or "0/1").partition("/")
            fps = float(num) / float(den or 1) if float(den or 1) else None
            out = dict(w=s.get("width"), h=s.get("height"), fps=round(fps, 3) if fps else None,
                       duration=float((doc.get("format") or {}).get("duration") or 0) or None)
        except (OSError, ValueError, subprocess.SubprocessError, ZeroDivisionError):
            out = {}
    with _probe_lock:
        _probe_cache[key] = out
    return out


# ------------------------------------------------------------------ transcripts
def _words_from_asr(doc):
    words = []
    if isinstance(doc, dict):
        for seg in doc.get("segments") or []:
            for w in seg.get("words") or []:
                t, te = w.get("start", w.get("t")), w.get("end", w.get("te"))
                txt = (w.get("word") or w.get("w") or "").strip()
                if txt and t is not None and te is not None:
                    words.append(dict(w=txt, t=round(float(t), 3), te=round(float(te), 3)))
        if not words:
            for w in doc.get("words") or []:
                t, te = w.get("start", w.get("t")), w.get("end", w.get("te"))
                txt = (w.get("word") or w.get("w") or "").strip()
                if txt and t is not None and te is not None:
                    words.append(dict(w=txt, t=round(float(t), 3), te=round(float(te), 3)))
    words.sort(key=lambda w: w["t"])
    return words


def _asr_for(file, workdir=None, extra=()):
    cands = list(extra) + [file + ".asr.json", os.path.splitext(file)[0] + ".asr.json"]
    if workdir:
        cands += [os.path.join(workdir, n) for n in ("exports/xiaohongshu-vertical.mp4.asr.json", "clean.asr.json")]
    for c in cands:
        if c and os.path.exists(c):
            w = _words_from_asr(read_json(c, None))
            if w:
                return w
    return []


def waveform(words, duration, n=None):
    """A speech-shaped envelope from the word timings (deterministic; ~8 bars per second)."""
    if not duration:
        return []
    n = n or int(min(2400, max(240, duration * 8)))
    out = []
    for i in range(n):
        t = (i + 0.5) * duration / n
        speaking = any(w["t"] - 0.05 <= t <= w["te"] + 0.05 for w in words) if words else True
        h = int(hashlib.sha1(f"{i}".encode()).hexdigest()[:4], 16) / 65535
        out.append(round((0.35 + 0.6 * h) if speaking else 0.04 + 0.05 * h, 3))
    return out


# ------------------------------------------------------------------ listing (one clip per output)
def _batch_clips(bdir):
    """jobs/<id>/export/manifest.json of a batch (or a project's state/) -> clips."""
    import sqlite3
    states = {}
    try:
        con = sqlite3.connect(f"file:{os.path.join(bdir, 'batch.db')}?mode=ro", uri=True, timeout=1.0)
        try:
            for jid, st, qc, rv in con.execute("SELECT id, state, qc, review FROM jobs ORDER BY ord, id"):
                states[jid] = dict(state=st, qc=qc, review=rv)
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        pass
    out = []
    jobs_dir = os.path.join(bdir, "jobs")
    ids = list(states) or (sorted(os.listdir(jobs_dir)) if os.path.isdir(jobs_dir) else [])
    for jid in ids:
        jdir = os.path.join(jobs_dir, jid)
        man = read_json(os.path.join(jdir, "export", "manifest.json"), None) or {}
        job = read_json(os.path.join(jdir, "job.json"), None) or {}
        params = job.get("params") or {}
        files, cover, post = [], None, None
        for e in man.get("exports") or []:
            if not isinstance(e, dict) or not e.get("file"):
                continue
            hits = []
            for dp, _dns, fns in os.walk(os.path.join(jdir, "export")):
                if e["file"] in fns:
                    hits.append(os.path.join(dp, e["file"]))
            if not hits:
                continue
            p = hits[0]
            asp = WK.aspect_of(e.get("w"), e.get("h")) or WK.aspect_from_name(p) or "原尺寸"
            if not any(f["aspect"] == asp for f in files):
                files.append(dict(path=p, aspect=asp, w=e.get("w"), h=e.get("h"), fps=e.get("fps"),
                                  duration=e.get("duration"), platform=f"{e.get('platform')}:{e.get('orientation')}",
                                  safe_box=e.get("safe_box"), caption_box=e.get("caption_box")))
            if not cover and e.get("cover") and os.path.exists(os.path.join(os.path.dirname(p), e["cover"])):
                cover = os.path.join(os.path.dirname(p), e["cover"])
            if not post and e.get("post") and os.path.exists(os.path.join(os.path.dirname(p), e["post"])):
                try:
                    with open(os.path.join(os.path.dirname(p), e["post"]), encoding="utf-8") as f:
                        post = WK.parse_post_single(f.read(20000))
                except OSError:
                    pass
        st = states.get(jid) or {}
        state = st.get("state") or ("done" if files else "queued")
        if not cover:
            sheet = os.path.join(jdir, "preview", "sheet.jpg")
            cover = sheet if os.path.exists(sheet) else None
        out.append(dict(id=jid, title=params.get("title") or jid, state=state, qc=st.get("qc"),
                        review=st.get("review"), files=files, cover=cover,
                        post=post or (dict(title=params.get("title") or "", body=params.get("body") or "",
                                           tags=params.get("tags") or []) if params.get("title") else None),
                        duration=next((f["duration"] for f in files if f.get("duration")), None), extra=False,
                        jobdir=jdir))
    return out


def list_clips(entry):
    """A history entry (kind batch | project | work, dir) -> clips."""
    kind, d = entry["kind"], entry["dir"]
    if kind == "work":
        return WK.clips(d, probe=probe)
    store = os.path.join(d, "state") if kind == "project" else d
    return _batch_clips(store)


def _public_clip(c):
    return {k: v for k, v in c.items() if k not in ("jobdir", "workdir")}


# ------------------------------------------------------------------ op validation (desk side, before the engine)
def validate_ops(ops):
    need(isinstance(ops, list) and 0 < len(ops) <= 50, "ops: 1-50 edits")
    need(len(json.dumps(ops, ensure_ascii=False)) < 20000, "ops: too large")
    out = []
    for o in ops:
        need(isinstance(o, dict) and o.get("op") in OPS, f"op: {' | '.join(OPS)}")
        for k, v in o.items():
            need(isinstance(k, str) and re.match(r"^[a-z_]{1,24}$", k), "bad op field")
            if isinstance(v, float):
                need(math.isfinite(v), f"{k}: number")
        for k in ("start", "end", "t", "value", "duration"):
            if o.get(k) is not None:
                need(isinstance(o[k], (int, float)) and not isinstance(o[k], bool) and -1 <= o[k] <= 36000, f"{k}: seconds")
        if o["op"] in ("export_add", "export_remove"):
            need(isinstance(o.get("target"), str) and TARGET_RE.match(o["target"]), "target: 3:4 | 9:16 | 16:9 | platform")
        if o["op"] == "effect_add":
            need(isinstance(o.get("effect"), str) and 0 < len(o["effect"]) <= 40, "effect: id")
        out.append(dict(o))
    return out


# ------------------------------------------------------------------ the desk implementation (same vocabulary)
def _new_state():
    return dict(trim=[None, None], cuts=[], speed=1.0, captions=dict(enabled=False, style={}, overrides={}, removed=[],
                                                                       added=[], placement=None),
                title=None, effects=[], cover=None, exports=[], seq=0)


def apply_op(state, o, base):
    """One op on the desk state -> (describe, value). Raises EngineMessage like the engine would."""
    op = o["op"]
    dur = base["duration"] or 1e9
    mode = base["mode"]

    def t_(v, name):
        if v is None:
            return None
        if not (0 <= float(v) <= dur + 0.05):
            raise EngineMessage(_m("bad-time", f"{name} is outside the clip", f"{name} 超出成片长度", field=name))
        return round(float(v), 3)
    if op == "trim":
        a, z = t_(o.get("start"), "start"), t_(o.get("end"), "end")
        if a is not None and z is not None and z - a < 0.5:
            raise EngineMessage(_m("too-short", "the kept part is too short", "保留的部分太短"))
        state["trim"] = [a, z]
        return _m("op-trim", f"trim to {a or 0:g}s - {z if z is not None else dur:g}", "裁剪首尾", start=a, end=z), None
    if op == "cut":
        a, z = t_(o.get("start"), "start"), t_(o.get("end"), "end")
        if a is None or z is None or z - a < 0.05:
            raise EngineMessage(_m("bad-time", "end must be after start", "结束要晚于开始"))
        state["cuts"] = sorted(state["cuts"] + [dict(start=a, end=z, why=o.get("why") or "")], key=lambda c: c["start"])
        return _m("op-cut", f"cut {a:g}s - {z:g}s", f"剪掉 {a:g}–{z:g} 秒", start=a, end=z), None
    if op == "cut_remove":
        i = o.get("index")
        if not isinstance(i, int) or not 0 <= i < len(state["cuts"]):
            raise EngineMessage(_m("unknown-cut", "no such cut", "没有这处剪切", index=i))
        c = state["cuts"].pop(i)
        return _m("op-cut-remove", f"restore {c['start']:g}s - {c['end']:g}s", "恢复一处剪切", index=i), None
    if op == "speed":
        v = float(o.get("value") or 1.0)
        if not 0.5 <= v <= 2.5:
            raise EngineMessage(_m("bad-param", "speed: 0.5-2.5", "速度：0.5–2.5", field="value"))
        state["speed"] = v
        return _m("op-speed", f"speed {v:g}x", f"速度 {v:g} 倍", value=v), None
    if op in ("caption_text", "captions"):
        if mode != "pipeline":
            raise EngineMessage(_m("captions-not-ours", "burned-in captions cannot be changed",
                                   "字幕已经烧进画面，不能改字"))
        if op == "captions":
            state["captions"]["enabled"] = bool(o.get("enabled"))
            return _m("op-captions", "captions on" if o.get("enabled") else "captions off", "字幕开关"), None
        cue, text = o.get("cue"), (o.get("text") or "").strip()
        if not text:
            raise EngineMessage(_m("empty-text", "the caption is empty", "字幕是空的"))
        if not any(str(c["id"]) == str(cue) for c in base["captions"]):
            raise EngineMessage(_m("unknown-cue", "no such caption", "没有这条字幕", cue=cue))
        state["captions"]["overrides"][str(cue)] = text
        return _m("op-caption-text", "edit a caption", "改字幕", cue=cue), None
    if op == "caption_style":
        st = o.get("style") if isinstance(o.get("style"), dict) else {}
        clean = {}
        for k, v in st.items():
            if k == "size" and isinstance(v, (int, float)):
                clean[k] = min(1.8, max(0.6, float(v)))
            elif k in ("color", "highlight", "stroke_color", "box_color") and isinstance(v, str) and \
                    re.match(r"^#[0-9A-Fa-f]{6}$", v):
                clean[k] = v
            elif k == "position" and v in ("bottom", "middle", "top"):
                clean[k] = v
            elif k == "keywords" and isinstance(v, list):
                clean[k] = [str(x)[:30] for x in v[:20]]
        state["captions"]["style"].update(clean)
        return _m("op-caption-style", "caption style", "字幕样式"), (dict(warning="style-added-only")
                                                                  if mode != "pipeline" else None)
    if op == "caption_add":
        a, z = t_(o.get("start"), "start"), t_(o.get("end"), "end")
        text = (o.get("text") or "").strip()
        if not text or a is None or z is None:
            raise EngineMessage(_m("empty-text", "the caption is empty", "字幕是空的"))
        cid = f"a{len(state['captions']['added']) + 1}"
        state["captions"]["added"].append(dict(id=cid, start=a, end=z, text=text[:200]))
        return _m("op-caption-add", f"add a caption at {a:g}s", f"在 {a:g} 秒加字幕", start=a, end=z), dict(id=cid)
    if op == "caption_remove":
        cue = str(o.get("cue"))
        before = len(state["captions"]["added"])
        state["captions"]["added"] = [c for c in state["captions"]["added"] if c["id"] != cue]
        if len(state["captions"]["added"]) == before:
            if mode != "pipeline":
                raise EngineMessage(_m("captions-not-ours", "burned-in captions cannot be removed", "烧进画面的字幕不能删"))
            state["captions"]["removed"].append(cue)
        return _m("op-caption-remove", "remove a caption", "删一条字幕", cue=cue), None
    if op == "caption_placement":
        if mode == "pipeline":
            raise EngineMessage(_m("placement-pipeline", "placement is for finished files only", "只有成片才需要设置字幕位置"))
        state["captions"]["placement"] = dict(mode=o.get("mode") or "mask")
        return _m("op-caption-placement", "caption placement", "字幕位置"), None
    if op == "title":
        txt = (o.get("text") or "").strip()
        state["title"] = dict(text=txt[:60], sub=(o.get("sub") or "")[:60]) if txt else None
        return _m("op-title", "title band" if txt else "remove the title band", "标题条" if txt else "去掉标题条",
                  text=txt), None
    if op == "effect_add":
        eid = ALIASES.get(o["effect"], o["effect"])
        fx = EFFECT_BY_ID.get(eid)
        if not fx:
            raise EngineMessage(_m("unknown-effect", f"unknown effect {o['effect']}", f"没有这个效果：{o['effect']}",
                                   effect=o["effect"]))
        a = t_(o.get("start") or 0, "start")
        z = o.get("end")
        z = t_(min(float(z), dur), "end") if z is not None else \
            round(min(dur, a + float(o.get("duration") or fx["default_dur"] or 0)), 3)
        params = {}
        for k, sch in fx["params"].items():
            v = (o.get("params") or {}).get(k, sch.get("default"))
            if sch.get("type") == "number" and v is not None:
                v = min(sch["maximum"], max(sch["minimum"], float(v)))
            if sch.get("enum") and v not in sch["enum"]:
                v = sch.get("default")
            params[k] = v
        missing = [k for k, sch in fx["params"].items() if sch.get("required") and not params.get(k)]
        if missing:
            raise EngineMessage(_m("bad-param", f"{missing[0]} is required",
                                   f"需要填写{fx['params'][missing[0]]['x-zh']}", field=missing[0]))
        state["seq"] += 1
        fid = o.get("id") or f"fx{state['seq']}"
        if any(e["id"] == fid for e in state["effects"]):
            raise EngineMessage(_m("duplicate-effect", "duplicate effect id", "效果编号重复", id=fid))
        state["effects"].append(dict(id=fid, effect=eid, start=a, end=max(a, z), params=params))
        return _m("op-effect-add", f"add {fx['label']['en']} at {a:g}s", f"在 {a:g} 秒加{fx['label']['zh']}",
                  effect=eid, start=a, end=z), dict(id=fid)
    if op in ("effect_update", "effect_remove"):
        e = next((x for x in state["effects"] if x["id"] == o.get("id")), None)
        if not e:
            raise EngineMessage(_m("unknown-effect-instance", "no such effect", "没有这个效果", id=o.get("id")))
        if op == "effect_remove":
            state["effects"] = [x for x in state["effects"] if x is not e]
            return _m("op-effect-remove", "remove an effect", "删掉一个效果", id=e["id"], effect=e["effect"]), None
        if o.get("shift") is not None:
            sh = float(o["shift"])
            e["start"], e["end"] = round(e["start"] + sh, 3), round(e["end"] + sh, 3)
        if o.get("start") is not None:
            e["start"] = t_(o["start"], "start")
        if o.get("end") is not None:
            e["end"] = t_(o["end"], "end")
        if isinstance(o.get("params"), dict):
            e["params"] = dict(e["params"], **{k: v for k, v in o["params"].items() if k in e["params"]})
        return _m("op-effect-update", "change an effect", "调整效果", id=e["id"], effect=e["effect"]), None
    if op == "cover":
        if o.get("clear"):
            state["cover"] = None
        else:
            state["cover"] = dict(t=t_(o.get("t") or 0, "t"), text=(o.get("text") or "")[:60], style=o.get("style") or "card")
        return _m("op-cover", "new cover", "换封面", t=(state["cover"] or {}).get("t")), None
    if op in ("export_add", "export_remove"):
        tg = o["target"]
        state["exports"] = [x for x in state["exports"] if x["target"] != tg]
        if op == "export_add":
            state["exports"].append(dict(target=tg, layout=o.get("layout") or "auto"))
        return _m(f"op-{op.replace('_', '-')}", f"{'add' if op == 'export_add' else 'remove'} {tg}",
                  f"{'加' if op == 'export_add' else '去掉'} {tg} 版本", target=tg), None
    if op == "loudness":
        return _m("op-loudness", "loudness", "响度", lufs=o.get("lufs")), None
    if op == "reset":
        state.clear()
        state.update(_new_state())
        return _m("op-reset", "back to the original", "恢复原片"), None
    raise EngineMessage(_m("unknown-op", f"unknown op {op}", f"不认识的操作 {op}", op=op))


class Outputs:
    """Clip listing + the output editor, via the engine command when it exists, else the desk implementation."""

    def __init__(self, data_dir, history, runner=None, bus=None):
        self.dir = os.path.join(data_dir, "outputs")
        self.history, self.runner, self.bus = history, runner, bus
        self._real = None
        self._lock = threading.Lock()
        self._lists = {}

    # ---------------------------------------------------------- capability
    def real(self):
        """True when ``python -m vstudio.project output`` exists (probed once)."""
        if self._real is None:
            ok = False
            if self.runner is not None:
                try:
                    txt = self.runner.sibling("vstudio.project").text(["output", "--help"])
                    ok = all(re.search(rf"\b{v}\b", txt) for v in ("show", "edit", "render", "undo")) and \
                        "invalid choice" not in txt
                except Exception:  # noqa: BLE001
                    ok = False
            self._real = ok
        return self._real

    def _cli(self, args, timeout=600):
        from .caps import CliError
        try:
            return self.runner.sibling("vstudio.project").json(["output", *args, "--json"], timeout=timeout)
        except CliError as e:
            doc = getattr(e, "doc", None)
            if isinstance(doc, dict) and doc.get("code"):
                raise EngineMessage(doc) from e
            raise

    def _engine_list(self, e):
        """``output list`` for a project / work folder (cached per owner for a few seconds) -> {abs file: id}."""
        if not self.real() or e["kind"] == "batch":
            return None
        k = os.path.realpath(e["dir"])
        hit = self._lists.get(k)
        if hit and time.time() - hit[0] < 5:
            return hit[1]
        try:
            doc = self._cli(["list", "--project", e["dir"]], timeout=120)
            m = {os.path.realpath(o["file"]): o["id"] for o in doc.get("outputs") or [] if o.get("file") and o.get("id")}
        except Exception:  # noqa: BLE001  (unknown owner / older engine: the desk implementation answers)
            m = None
        self._lists[k] = (time.time(), m)
        return m

    # ---------------------------------------------------------- lookup
    def _entry(self, item_id):
        return self.history.find(item_id)

    def clips(self, item_id):
        e = self._entry(item_id)
        cl = list_clips(e)
        self.history.allow_media([f["path"] for c in cl for f in c["files"]] + [c["cover"] for c in cl if c.get("cover")])
        return dict(item=item_id, kind=e["kind"], clips=[_public_clip(c) for c in cl],
                    confirm=WK.confirmations(e["dir"]) if e["kind"] == "work" else [])

    def _clip(self, item_id, clip_id):
        need(isinstance(clip_id, str) and WK.CLIP_ID_RE.match(clip_id) and ".." not in clip_id, "bad clip id")
        e = self._entry(item_id)
        for c in list_clips(e):
            if c["id"] == clip_id:
                return e, c
        raise KeyError(f"no clip {clip_id}")

    def _output_id(self, e, c):
        """The engine's output id for the clip's primary file (None: the desk implementation answers)."""
        m = self._engine_list(e)
        if not m or not c["files"]:
            return None
        return m.get(os.path.realpath(c["files"][0]["path"]))

    def _state_path(self, e, clip_id):
        key = hashlib.sha1(f"{os.path.realpath(e['dir'])}\0{clip_id}".encode()).hexdigest()[:16]
        return os.path.join(self.dir, f"{key}.json")

    def _desk(self, e, clip_id):
        st = read_json(self._state_path(e, clip_id), None)
        return st if isinstance(st, dict) and "state" in st else dict(state=_new_state(), steps=[], redo=[], renders=[])

    def _save(self, e, clip_id, st):
        write_json(self._state_path(e, clip_id), st)

    # ---------------------------------------------------------- the clip facts both paths share
    def _base(self, e, c):
        main = c["files"][0] if c["files"] else None
        file = main["path"] if main else None
        info = probe(file) if file else {}
        dur = (main or {}).get("duration") or info.get("duration") or c.get("duration") or 0
        words = _asr_for(file, c.get("workdir") or (os.path.join(e["dir"], "work", "clips", c.get("letter") or "")
                                                     if c.get("letter") else None)) if file else []
        dur = dur or (words[-1]["te"] if words else 0)
        jobdir = c.get("jobdir")
        captions, mode = [], "flattened"
        if jobdir:
            cues = read_json(os.path.join(jobdir, "compose", "cues.json"), None)
            rows = cues.get("cues") if isinstance(cues, dict) else cues
            for i, q in enumerate(rows or []):
                if isinstance(q, dict):
                    txt = q.get("text") if isinstance(q.get("text"), str) else "".join(q.get("lines") or [])
                    captions.append(dict(id=str(q.get("i", i)), start=q.get("start", q.get("t0", 0)),
                                         end=q.get("end", q.get("t1", 0)), text=txt))
            mode = "pipeline" if captions else "flattened"
            if not words:
                words = _words_from_asr(read_json(os.path.join(jobdir, "compose", "out", "final.mp4.asr.json"), None))
        return dict(id=c["id"], title=c["title"], state=c["state"], file=file, files=c["files"], cover=c.get("cover"),
                    post=c.get("post"), duration=dur, fps=(main or {}).get("fps") or info.get("fps") or 30,
                    w=(main or {}).get("w") or info.get("w"), h=(main or {}).get("h") or info.get("h"),
                    words=words, captions=captions, mode=mode,
                    safe_box=(main or {}).get("safe_box"), caption_box=(main or {}).get("caption_box"))

    @staticmethod
    def _caps(mode, has_file, has_words):
        pipe = mode == "pipeline"
        caps = dict(mode=mode, trim=has_file, cut=has_file and has_words, cut_snap="words" if has_words else None,
                    speed=has_file, loudness=has_file, effects=has_file, title_band=has_file, cover=has_file,
                    export=has_file, undo=True, ai=True, captions_ours=pipe, caption_text=pipe, caption_style=True,
                    caption_restyle_burned=False, caption_toggle=pipe, caption_add=has_file,
                    caption_placements=[] if pipe else ["band", "mask"], relayout="reframe-file", audio=has_file)
        notes = [] if pipe else [_m("flattened", "edits are applied on top of the finished file (no clean master)",
                                    "在成片上叠加编辑（没有干净母版）"),
                                 _m("captions-add-only", "captions can only be added, in a band layout or over a "
                                    "mask; burned-in text cannot be restyled",
                                    "字幕只能新增（字幕条布局或遮罩上），已烧录的文字不能改样式")]
        return caps, notes

    def _normalise(self, base, eng, item_id, words=None):
        """Engine ``show`` (or the desk state) + the clip facts -> the desk document."""
        out = dict(base, item=item_id)
        o = eng.get("output") or {}
        st = eng.get("state") or {}
        tl = eng.get("timeline") or {}
        dur = o.get("duration") or base["duration"]
        segs = tl.get("segments") or []
        trim = st.get("trim") or [None, None]
        out["trim"] = None if not trim or trim == [None, None] else dict(
            start=trim[0] if trim[0] is not None else 0, end=trim[1] if trim[1] is not None else dur)
        cuts = [dict(start=c.get("start"), end=c.get("end"), index=i) for i, c in enumerate(st.get("cuts") or [])
                if isinstance(c, dict)]
        if not cuts and len(segs) > 1:
            cuts = [dict(start=a[1], end=b[0], index=i) for i, (a, b) in enumerate(zip(segs, segs[1:])) if b[0] - a[1] > 0.02]
        out["cuts"] = cuts
        if eng.get("captions") is not None:
            out["captions"] = [dict(id=str(c.get("id")), start=c.get("start"), end=c.get("end"), text=c.get("text"),
                                    added=bool(c.get("added")), removed=bool(c.get("removed")))
                               for c in eng["captions"] if isinstance(c, dict)]
        out["caption_style"] = (st.get("captions") or {}).get("style") or {}
        by = {x["id"]: x for x in EFFECTS}
        effs = eng.get("effects") if eng.get("effects") is not None else st.get("effects") or []
        out["effects"] = [dict(id=x.get("id"), effect=x.get("effect"), start=x.get("start"), end=x.get("end"),
                               params=x.get("params") or {},
                               label=x.get("label") or (by.get(x.get("effect")) or {}).get("label") or
                               dict(en=x.get("effect"), zh=x.get("effect"))) for x in effs]
        out["speed"] = st.get("speed") or 1.0
        out["title_band"] = st.get("title")
        out["cover_edit"] = st.get("cover")
        out["exports"] = st.get("exports") or []
        hist = eng.get("history") or {}
        out["steps"] = [dict(id=s_.get("id"), at=s_.get("at"), by=s_.get("by"), describe=s_.get("describe") or [])
                        for s_ in hist.get("steps") or []]
        out["undo"], out["redo"] = hist.get("undo", len(out["steps"])), hist.get("redo", 0)
        out["renders"] = eng.get("renders") or []
        out["caps"] = eng.get("caps") or {}
        out["caps_notes"] = eng.get("caps_notes") or []
        out["warnings"] = eng.get("warnings") or []
        out["mode"] = o.get("mode") or base["mode"]
        out["duration"] = dur
        out["fps"] = o.get("fps") or base["fps"]
        if words:
            out["words"] = words
        out["waveform"] = waveform(out["words"], dur)
        return out

    def show(self, item_id, clip_id):
        e, c = self._clip(item_id, clip_id)
        base = self._base(e, c)
        oid = self._output_id(e, c)
        if oid:
            eng = self._cli(["show", "--project", e["dir"], "--output", oid])
            tr = read_json(os.path.join((eng.get("paths") or {}).get("dir") or "/nonexistent", "transcript.json"), None)
            words = [dict(w=w["w"], t=w["t"], te=w["te"]) for w in (tr or {}).get("words") or []] \
                if isinstance(tr, dict) else None
            doc = self._normalise(base, eng, item_id, words or None)
            doc.update(engine="real", output_id=oid)
        else:
            st = self._desk(e, clip_id)
            caps, notes = self._caps(base["mode"], bool(base["file"]), bool(base["words"]))
            sc = st["state"]["captions"]
            capdocs = [dict(c_, added=False, removed=c_["id"] in sc["removed"], text=sc["overrides"].get(c_["id"], c_["text"]))
                       for c_ in base["captions"]] + [dict(c_, added=True, removed=False) for c_ in sc["added"]]
            fresh_key = len(st["steps"])
            eng = dict(output=dict(mode=base["mode"], duration=base["duration"], fps=base["fps"]), state=st["state"],
                       captions=capdocs, effects=None, caps=caps, caps_notes=notes,
                       history=dict(steps=st["steps"], undo=len(st["steps"]), redo=len(st["redo"])),
                       renders=[dict({k: v for k, v in r.items() if k != "key"}, fresh=r.get("key") == fresh_key,
                                     simulated=True) for r in st.get("renders") or []])
            doc = self._normalise(base, eng, item_id)
            doc.update(engine="desk", output_id=None)
        paths = [f["path"] for f in doc.get("files") or []] + [doc.get("cover")] + \
            [r.get("file") for r in doc.get("renders") or []]
        self.history.allow_media([p for p in paths if p])
        return doc

    # ---------------------------------------------------------- edit / undo / redo / render
    def _adopt_on_first_edit(self, e):
        """「转成项目」 happens transparently: a plain work folder gets its record on the first edit."""
        if e["kind"] == "work" and not os.path.exists(WK.record_path(e["dir"])):
            try:
                self.history.adopt(e["id"])
            except Exception:  # noqa: BLE001  (read-only folder: the edit log lives in the desk data dir anyway)
                pass

    def edit(self, item_id, clip_id, ops, by="user"):
        e, c = self._clip(item_id, clip_id)
        ops = validate_ops(ops)
        self._adopt_on_first_edit(e)
        oid = self._output_id(e, c)
        if oid:
            r = self._cli(["edit", "--project", e["dir"], "--output", oid, "--ops", json.dumps(ops, ensure_ascii=False)])
            self._publish(item_id, clip_id)
            return dict(ok=True, step=r.get("step"), values=r.get("values"), warnings=r.get("warnings") or [])
        base = self._base(e, c)
        with self._lock:
            st = self._desk(e, clip_id)
            work = json.loads(json.dumps(st["state"]))
            describe, values, warnings = [], [], []
            for o in ops:                                    # all or nothing
                d, v = apply_op(work, o, base)
                describe.append(d)
                values.append(v)
                if isinstance(v, dict) and v.get("warning"):
                    warnings.append(_m(v["warning"], "style applies to added captions only", "样式只作用于新增的字幕"))
            step = dict(id=f"s{len(st['steps']) + 1}-{hashlib.sha1(json.dumps(ops).encode()).hexdigest()[:6]}",
                        at=time.strftime("%Y-%m-%dT%H:%M:%S"), by=by, note=None, ops=ops, describe=describe,
                        before=st["state"])
            st["state"] = work
            st["steps"].append(step)
            st["redo"] = []
            self._save(e, clip_id, st)
        self._publish(item_id, clip_id)
        return dict(ok=True, step={k: v for k, v in step.items() if k != "before"}, values=values, warnings=warnings)

    def undo(self, item_id, clip_id, steps=1, redo=False):
        e, c = self._clip(item_id, clip_id)
        need(isinstance(steps, int) and not isinstance(steps, bool) and 0 < steps <= 200, "steps: 1-200")
        oid = self._output_id(e, c)
        if oid:
            for _ in range(steps):
                self._cli(["redo" if redo else "undo", "--project", e["dir"], "--output", oid])
            self._publish(item_id, clip_id)
            return dict(ok=True)
        base = self._base(e, c)
        with self._lock:
            st = self._desk(e, clip_id)
            for _ in range(steps):
                if redo:
                    if not st["redo"]:
                        raise EngineMessage(_m("nothing-to-redo", "nothing to redo", "没有可以重做的"))
                    s_ = st["redo"].pop()
                    s_["before"] = st["state"]
                    work = json.loads(json.dumps(st["state"]))
                    for o in s_["ops"]:
                        apply_op(work, o, base)
                    st["state"] = work
                    st["steps"].append(s_)
                else:
                    if not st["steps"]:
                        raise EngineMessage(_m("nothing-to-undo", "nothing to undo", "没有可以撤销的"))
                    s_ = st["steps"].pop()
                    st["state"] = s_["before"]
                    st["redo"].append(s_)
            self._save(e, clip_id, st)
        self._publish(item_id, clip_id)
        return dict(ok=True)

    def render(self, item_id, clip_id, quality="preview", targets="primary"):
        e, c = self._clip(item_id, clip_id)
        need(quality in ("preview", "final"), "quality: preview | final")
        need(isinstance(targets, str) and re.match(r"^[a-z0-9:,_-]{1,200}$", targets), "targets: primary | all | list")
        oid = self._output_id(e, c)
        if oid:
            r = self._cli(["render", "--project", e["dir"], "--output", oid, "--quality", quality, "--targets", targets],
                          timeout=3 * 3600)
            files = [dict(target=x.get("target"), file=x.get("file"), cover=x.get("cover"), cached=x.get("cached"))
                     for x in r.get("targets") or []]
            self.history.allow_media([f["file"] for f in files if f.get("file")])
            self._publish(item_id, clip_id)
            return dict(ok=True, targets=files, simulated=False, seconds=r.get("seconds"))
        with self._lock:
            st = self._desk(e, clip_id)
            files = [dict(target=f["aspect"], file=f["path"], cover=c.get("cover"), cached=False)
                     for f in c["files"][: (None if targets == "all" else 1)]]
            st["renders"] = [dict(target=f["target"], quality=quality, file=f["file"], key=len(st["steps"]))
                             for f in files]
            self._save(e, clip_id, st)
        self._publish(item_id, clip_id)
        return dict(ok=True, targets=files, simulated=True)

    # ---------------------------------------------------------- 让 AI 改 (natural language -> proposed ops)
    def ask(self, item_id, clip_id, prompt):
        need(isinstance(prompt, str) and 0 < len(prompt.strip()) <= 500, "prompt: 1-500 chars")
        e, c = self._clip(item_id, clip_id)
        oid = self._output_id(e, c)
        note = None
        if oid:
            try:
                r = self._cli(["ai", "--project", e["dir"], "--output", oid, "--instruction", prompt], timeout=600)
                props = [dict(id=f"p{i + 1}", op=p.get("normalized") or p.get("op"), describe=p.get("describe"),
                              why=p.get("why")) for i, p in enumerate(r.get("proposed") or []) if isinstance(p, dict)]
                return dict(summary=r.get("summary"), proposals=props, dropped=r.get("dropped") or [],
                            warnings=r.get("warnings") or [], engine="real")
            except EngineMessage as m:
                if m.doc.get("code") not in ("llm-failed", "llm-bad-json"):
                    raise
                note = m.doc                                  # no working model: the desk rules still help
        r = propose(self.show(item_id, clip_id), prompt)
        if note:
            r["warnings"] = [note] + r.get("warnings", [])
        return r

    def effects(self):
        if self.real():
            try:
                doc = self._cli(["effects", "--no-thumbs"], timeout=60)
                if isinstance(doc, dict) and isinstance(doc.get("effects"), list):
                    return dict(effects=doc["effects"], engine="real")
            except Exception:  # noqa: BLE001
                pass
        return dict(effects=EFFECTS, engine="desk")

    def _publish(self, item_id, clip_id):
        if self.bus:
            self.bus.publish("output-edit", item=item_id, clip=clip_id)


# ------------------------------------------------------------------ rule-based proposals (no model)
def _find_word(words, needle):
    """Where the transcript (joined) contains ``needle`` -> (start, end) seconds."""
    if not needle:
        return None
    joined, idx = "", []
    for i, w in enumerate(words):
        for _ch in w["w"]:
            idx.append(i)
        joined += w["w"]
    k = joined.find(needle)
    if k < 0:
        k = joined.find(needle[: max(2, len(needle) // 2)])
        if k < 0:
            return None
        needle = needle[: max(2, len(needle) // 2)]
    a, z = idx[k], idx[min(len(idx) - 1, k + len(needle) - 1)]
    return words[a]["t"], words[z]["te"]


def propose(doc, prompt):
    """Natural language -> {summary, proposals [{id, op, describe, why}], warnings} over the clip's transcript. The
    engine's model (``output ai``) replaces this; these rules cover the common asks when no model answers."""
    p = prompt.strip()
    words = doc.get("words") or []
    dur = doc.get("duration") or (words[-1]["te"] if words else 0)
    props, warnings = [], []
    quoted = re.findall(r"[「“\"『']([^」”\"』']{1,40})[」”\"』']", p)

    def add(op, d, why):
        props.append(dict(id=f"p{len(props) + 1}", op=op, describe=d, why=why))

    if re.search(r"开头|开始|从|start", p, re.I) and (quoted or re.search(r"太慢|拖|啰嗦|快一点|slow", p, re.I)):
        hit = _find_word(words, quoted[0]) if quoted else None
        start = hit[0] if hit else min(2.0, dur / 4 if dur else 2.0)
        end = (doc.get("trim") or {}).get("end") or dur
        add(dict(op="trim", start=round(start, 3), end=round(end, 3)),
            _m("op-trim", f"start at {start:.1f}s", f"开头前移 {start:.1f} 秒", start=round(start, 3), end=round(end, 3)),
            _m("why-start-at", "start right at the quoted line" if hit else "skip the slow opening",
               f"从「{quoted[0]}」直接开始" if hit else "去掉开头没进入正题的部分", quote=quoted[0] if hit else ""))
    if re.search(r"紧凑|停顿|气口|节奏快|tight|pause", p, re.I) and words:
        gaps = [(a["te"] + 0.08, b["t"] - 0.08) for a, b in zip(words, words[1:]) if b["t"] - a["te"] > 0.6]
        for a, z in gaps[:12]:
            add(dict(op="cut", start=round(a, 3), end=round(z, 3)),
                _m("op-cut", f"cut a pause at {a:.1f}s", f"去掉 {a:.1f} 秒处的停顿", start=round(a, 3), end=round(z, 3)),
                _m("why-pause", "a pause longer than 0.6 s", "超过 0.6 秒的停顿"))
        if not gaps:
            warnings.append(_m("no-pauses", "no long pauses found", "没有找到明显的停顿"))
    if re.search(r"弹|强调|突出|pop", p, re.I):
        m = re.search(r"[「“\"『']([^」”\"』']{1,20})[」”\"』']\s*(?:弹|强调|突出)", p) or \
            re.search(r"(?:弹字|弹出|强调|突出|pop)\s*[：:]?\s*[「“\"『']?([^」”\"』'，,。\s]{1,20})", p, re.I)
        word = (m.group(1) if m else "").strip()
        hit = _find_word(words, word) if word else None
        if hit:
            add(dict(op="effect_add", effect="pop-words", start=hit[0], end=round(hit[0] + 1.2, 3),
                     params=dict(text=word)),
                _m("op-effect-add", f"add Pop word at {hit[0]:.1f}s", f"在 {hit[0]:.1f} 秒加弹出大字「{word}」",
                   effect="pop-words", start=hit[0], end=round(hit[0] + 1.2, 3)),
                _m("why-pop", "pops when the word is said", "说到这个词时弹出来", word=word))
        elif word:
            warnings.append(_m("word-not-found", f"“{word}” is not in the transcript", f"逐字稿里没有找到「{word}」",
                               word=word))
    if re.search(r"字幕.*(大|小|颜色|黄|白)|caption.*(bigger|smaller|colou?r)", p, re.I):
        if (doc.get("caps") or {}).get("captions_ours"):
            size = 1.2 if re.search(r"大|bigger", p) else 0.85
            add(dict(op="caption_style", style=dict(size=size)), _m("op-caption-style", "caption style", "字幕样式"),
                _m("why-style", "as asked", "按你说的调整"))
        else:
            warnings.append(_m("captions-add-only", "burned-in captions cannot be restyled",
                               "字幕已经烧进画面，不能改样式"))
    if re.search(r"封面|cover", p, re.I):
        t = round(min(dur * 0.3, 8.0), 2) if dur else 0
        add(dict(op="cover", t=t, text=(doc.get("post") or {}).get("title") or doc.get("title") or ""),
            _m("op-cover", "new cover", "换封面", t=t), _m("why-cover", "a clearer frame", "换一帧更清楚的"))
    if re.search(r"抖音|9[:：比]16|竖屏|douyin", p, re.I):
        add(dict(op="export_add", target="9:16"), _m("op-export-add", "add 9:16", "加 9:16 版本", target="9:16"),
            _m("why-douyin", "Douyin and Channels use 9:16", "抖音 / 视频号用 9:16"))
    if re.search(r"推近|放大|zoom", p, re.I):
        hit = _find_word(words, quoted[0]) if quoted else None
        t = hit[0] if hit else (dur / 2 if dur else 0)
        add(dict(op="effect_add", effect="punch-in", start=round(t, 3), end=round(min(dur or t + 3, t + 3), 3)),
            _m("op-effect-add", f"add Punch-in zoom at {t:.1f}s", f"在 {t:.1f} 秒加推镜放大", effect="punch-in",
               start=round(t, 3), end=round(t + 3, 3)), _m("why-zoom", "stress this line", "强调这句话"))
    if not props and not warnings:
        warnings.append(_m("not-understood", "try: start at “…”, tighter, pop “…”, new cover, Douyin version",
                           "这句我还没看懂。可以试试：从「…」开始 / 再紧凑一点 / 把「…」弹出来 / 换个封面 / 出抖音版"))
    return dict(summary=None, proposals=props, dropped=[], warnings=warnings, engine="desk")
