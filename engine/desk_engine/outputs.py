"""Outputs: every finished clip of a project / batch / work folder, its player data and second-pass editing.

Engine contract (being built as ``python -m vstudio.project output ...``, references/OUTPUT_EDIT.md in the engine
repo). The desk probes ``python -m vstudio.project output --help`` once; when the verbs exist every call goes to the
engine, otherwise this module's faithful implementation runs (mock mode, or an engine without the command):

  output show    --dir D --output ID --json             -> the show document (below)
  output edit    --dir D --output ID --op JSON --json   -> {ok, version, ops, op}
  output edit    --dir D --output ID --ask TEXT --dry-run --json   -> {summary_zh, proposals [{id, label, why, ops}]}
  output render  --dir D --output ID [--platforms a,b] --json      -> {ok, version, files [{aspect, path}], simulated}
  output undo    --dir D --output ID [--n N] --json     -> {ok, version, ops}
  output effects --json                                 -> {effects [{id, label, category, what, params, preview}]}

Show document: {id, title, file, files [{aspect, path, w, h}], cover, post {title, body, tags}, duration, fps, w, h,
words [{w, t, te}], captions [{i, t, te, text}], caption_style, effects [{id, effect, label, start, end, params}],
trim {start, end} | null, cuts [{start, end}], cover_edit {t, title, subtitle}, export {platforms}, ops [{n, op,
args, label, at}], version, rendered {version, files, at, simulated} | null, dirty, caps {trim, cut, captions
editable|flattened|none, effects, cover, export [aspects]}, notes {captions}, waveform [0..1], engine real|desk}.

Edit ops: trim {start, end} | cut {start, end} | caption {i, text} | caption_style {size, color, keyword_color,
position} | keyword {word, color} | effect_add {effect, start, end, params} | effect_move {id, start, end} |
effect_set {id, params} | effect_remove {id} | cover {t, title, subtitle} | export {platforms}.

The desk implementation keeps its edit log in ``<DESK_DATA_DIR>/outputs/<key>.json`` (never in the creator's
folder) and cannot re-render: ``render`` records a version with ``simulated: true`` and the same files.
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
from .common import need, read_json, write_json

OPS = ("trim", "cut", "caption", "caption_style", "keyword", "effect_add", "effect_move", "effect_set",
       "effect_remove", "cover", "export")
ASPECTS = ("3:4", "9:16", "16:9")
PLATFORM_ASPECT = {"xiaohongshu:vertical": "3:4", "xiaohongshu:full": "9:16", "douyin": "9:16", "tiktok": "9:16",
                   "youtube-shorts": "9:16", "bilibili": "16:9", "youtube": "16:9", "shipinhao": "9:16"}

# ------------------------------------------------------------------ effects catalogue (zh labels)
EFFECTS = [
    dict(id="pop-word", label="弹字", category="文字", what="一个词弹出来强调，带缩放和描边",
         params=[dict(key="text", label="文字", type="text", default=""),
                 dict(key="color", label="颜色", type="color", default="#FFD60A"),
                 dict(key="size", label="大小", type="range", min=0.6, max=2.0, step=0.1, default=1.0)],
         default_len=1.2, preview="pop"),
    dict(id="keyword-highlight", label="关键词变色", category="文字", what="字幕里的关键词换一种颜色",
         params=[dict(key="color", label="颜色", type="color", default="#2DD4BF")], default_len=2.0, preview="glow"),
    dict(id="notes-panel", label="记笔记面板", category="文字", what="屏幕一侧出现要点卡片",
         params=[dict(key="text", label="要点", type="text", default="")], default_len=4.0, preview="slide"),
    dict(id="bubble", label="气泡", category="文字", what="对话气泡里的一句补充",
         params=[dict(key="text", label="文字", type="text", default="")], default_len=2.5, preview="pop"),
    dict(id="chapter-card", label="章节卡", category="文字", what="一张章节标题卡，适合分段",
         params=[dict(key="text", label="标题", type="text", default="")], default_len=1.5, preview="fade"),
    dict(id="punch-in", label="推近", category="镜头", what="画面慢慢推近再回来，强调一句话",
         params=[dict(key="scale", label="放大倍数", type="range", min=1.05, max=1.4, step=0.01, default=1.14)],
         default_len=3.0, preview="zoom"),
    dict(id="punch-and-stay", label="推近停住", category="镜头", what="一下推近并停在那里，适合金句",
         params=[dict(key="scale", label="放大倍数", type="range", min=1.05, max=1.4, step=0.01, default=1.16)],
         default_len=2.0, preview="zoom"),
    dict(id="freeze-zoom", label="定格放大", category="镜头", what="定格一帧，把重点放大给人看",
         params=[dict(key="scale", label="放大倍数", type="range", min=1.2, max=3.0, step=0.1, default=1.8)],
         default_len=2.0, preview="zoom"),
    dict(id="highlight-box", label="高亮框", category="画面", what="一个框圈出画面里的重点",
         params=[dict(key="color", label="颜色", type="color", default="#FFD60A")], default_len=2.0,
         preview="glow"),
    dict(id="screenshot-card", label="截图卡片", category="画面", what="一张截图以 3D 卡片飞入并高亮",
         params=[dict(key="image", label="图片", type="text", default="")], default_len=3.0, preview="slide"),
    dict(id="picked-badge", label="精选标识", category="画面", what="角落里标出「精选」",
         params=[dict(key="text", label="文字", type="text", default="精选")], default_len=3.0, preview="fade"),
    dict(id="progress-bar", label="进度条", category="画面", what="底部进度条，可带章节",
         params=[], default_len=0, preview="bar", whole=True),
    dict(id="light-leak", label="漏光", category="氛围", what="暖色漏光扫过，适合转场",
         params=[dict(key="strength", label="强度", type="range", min=0.2, max=1.0, step=0.1, default=0.6)],
         default_len=0.8, preview="flash"),
    dict(id="film-grain", label="胶片颗粒", category="氛围", what="细微的胶片颗粒和暗角",
         params=[dict(key="strength", label="强度", type="range", min=0.1, max=1.0, step=0.1, default=0.4)],
         default_len=0, preview="fade", whole=True),
    dict(id="flash", label="闪白", category="转场", what="一下闪白，切换话题",
         params=[], default_len=0.3, preview="flash"),
    dict(id="mosaic", label="打码", category="隐私", what="遮住画面里的一块（人脸、名字）",
         params=[dict(key="kind", label="样式", type="select", options=["马赛克", "模糊", "小猫贴纸"], default="马赛克")],
         default_len=3.0, preview="fade"),
    dict(id="sfx-ding", label="音效：叮", category="声音", what="一个轻提示音，配合弹字",
         params=[dict(key="volume", label="音量", type="range", min=0.1, max=1.0, step=0.1, default=0.6)],
         default_len=0.4, preview="pulse"),
    dict(id="bgm-duck", label="音乐让一让", category="声音", what="说话时背景音乐自动压低",
         params=[dict(key="depth", label="压低", type="range", min=0.2, max=0.9, step=0.1, default=0.6)],
         default_len=0, preview="pulse", whole=True),
]
EFFECT_IDS = {e["id"] for e in EFFECTS}
EFFECT_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")

FLATTENED_NOTE = "这条的字幕已经烧进画面，不能改字或换样式；裁剪、加效果、换封面都可以。"
NO_CAPTIONS_NOTE = "这条没有字幕。"


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


def _asr_for(file, workdir=None):
    cands = [file + ".asr.json", os.path.splitext(file)[0] + ".asr.json"]
    if workdir:
        cands += [os.path.join(workdir, n) for n in ("exports/xiaohongshu-vertical.mp4.asr.json", "clean.asr.json")]
    for c in cands:
        if os.path.exists(c):
            doc = read_json(c, None)
            w = _words_from_asr(doc)
            if w:
                return w
    return []


def _cues_from_words(words, max_chars=14):
    cues, cur = [], []
    for w in words:
        cur.append(w)
        text = "".join(x["w"] for x in cur)
        if len(text) >= max_chars or re.search(r"[，。！？,.!?]$", w["w"]):
            cues.append(dict(i=len(cues), t=cur[0]["t"], te=cur[-1]["te"], text=text))
            cur = []
    if cur:
        cues.append(dict(i=len(cues), t=cur[0]["t"], te=cur[-1]["te"], text="".join(x["w"] for x in cur)))
    return cues


def waveform(words, duration, n=240):
    """A speech-shaped envelope from the word timings (deterministic; the engine's show has the real one)."""
    if not duration:
        return []
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
                        txt = f.read(20000)
                    lines = [ln for ln in txt.splitlines()]
                    tags = [t.lstrip("#") for ln in lines if re.fullmatch(r"\s*(#\S+\s*)+", ln or "x") for t in ln.split()]
                    body = "\n".join(ln for ln in lines[1:] if not re.fullmatch(r"\s*(#\S+\s*)+", ln or "x")).strip()
                    post = dict(title=(lines[0].lstrip("# ").strip() if lines else ""), body=body, tags=tags)
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


# ------------------------------------------------------------------ the desk implementation
def _fmt(t):
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:04.1f}"


def op_label(op, a, effects_by_id=None):
    eff = (effects_by_id or {}).get(a.get("effect")) if isinstance(a, dict) else None
    if op == "trim":
        return f"保留 {_fmt(a['start'])}–{_fmt(a['end'])}"
    if op == "cut":
        return f"剪掉 {_fmt(a['start'])}–{_fmt(a['end'])}"
    if op == "caption":
        return f"改字幕：{a.get('text', '')[:16]}"
    if op == "caption_style":
        return "改字幕样式"
    if op == "keyword":
        return f"关键词变色：{a.get('word', '')}"
    if op == "effect_add":
        return f"加{(eff or {}).get('label', a.get('effect'))}" + (f"「{a['params'].get('text')}」" if
                                                                   (a.get("params") or {}).get("text") else "") + \
            f" @ {_fmt(a['start'])}"
    if op == "effect_move":
        return f"移动效果到 {_fmt(a['start'])}"
    if op == "effect_set":
        return "调整效果参数"
    if op == "effect_remove":
        return "删掉一个效果"
    if op == "cover":
        return "换封面" + (f"：{a.get('title')}" if a.get("title") else "")
    if op == "export":
        return "导出尺寸：" + " / ".join(a.get("platforms") or [])
    return op


def validate_op(b):
    """One edit op from the UI -> (op, args). Raises BadRequest."""
    need(isinstance(b, dict), "op must be an object")
    op = b.get("op")
    need(op in OPS, f"op: {' | '.join(OPS)}")

    def num(k, lo=0.0, hi=36000.0):
        v = b.get(k)
        need(isinstance(v, (int, float)) and not isinstance(v, bool) and lo <= v <= hi and math.isfinite(v),
             f"{k}: number {lo}..{hi}")
        return round(float(v), 3)

    def text(k, n=200, required=False):
        v = b.get(k, "")
        need(isinstance(v, str) and len(v) <= n and (v.strip() or not required), f"{k}: text (max {n})")
        return v

    def params(v):
        need(v is None or (isinstance(v, dict) and len(v) <= 20), "params: object")
        out = {}
        for k, x in (v or {}).items():
            need(isinstance(k, str) and re.match(r"^[a-z][a-z0-9_]{0,30}$", k), "params: bad key")
            need(x is None or isinstance(x, (bool, int, float)) or (isinstance(x, str) and len(x) <= 200),
                 f"params.{k}: number / text")
            out[k] = x
        return out

    def color(k):
        v = b.get(k)
        need(v is None or (isinstance(v, str) and re.match(r"^#[0-9A-Fa-f]{6}$", v)), f"{k}: #RRGGBB")
        return v

    if op in ("trim", "cut"):
        a = dict(start=num("start"), end=num("end"))
        need(a["end"] - a["start"] >= 0.05, "end must be after start")
        return op, a
    if op == "caption":
        i = b.get("i")
        need(isinstance(i, int) and not isinstance(i, bool) and 0 <= i < 100000, "i: caption index")
        return op, dict(i=i, text=text("text", 200, True))
    if op == "caption_style":
        out = {}
        if b.get("size") is not None:
            out["size"] = num("size", 0.5, 2.0)
        for k in ("color", "keyword_color"):
            if b.get(k) is not None:
                out[k] = color(k)
        if b.get("position") is not None:
            need(b["position"] in ("bottom", "middle", "top"), "position: bottom | middle | top")
            out["position"] = b["position"]
        need(out, "nothing to change")
        return op, out
    if op == "keyword":
        return op, dict(word=text("word", 30, True), color=color("color") or "#2DD4BF")
    if op == "effect_add":
        eff = b.get("effect")
        need(isinstance(eff, str) and EFFECT_RE.match(eff), "effect: id")
        a = dict(effect=eff, start=num("start"), end=num("end"), params=params(b.get("params")))
        need(a["end"] >= a["start"], "end must be after start")
        return op, a
    if op in ("effect_move", "effect_set", "effect_remove"):
        eid = b.get("id")
        need(isinstance(eid, str) and re.match(r"^e\d{1,6}$", eid), "id: effect id")
        if op == "effect_move":
            a = dict(id=eid, start=num("start"), end=num("end"))
            need(a["end"] >= a["start"], "end must be after start")
            return op, a
        if op == "effect_set":
            return op, dict(id=eid, params=params(b.get("params")))
        return op, dict(id=eid)
    if op == "cover":
        return op, dict(t=None if b.get("t") is None else num("t"), title=text("title", 60),
                        subtitle=text("subtitle", 60))
    pl = b.get("platforms")
    need(isinstance(pl, list) and 0 < len(pl) <= 3 and all(p in ASPECTS for p in pl), "platforms: 3:4 | 9:16 | 16:9")
    return op, dict(platforms=list(dict.fromkeys(pl)))


def fold(base, ops):
    """Apply the op log to the base document -> the edited view (pure; used by show and by the tests)."""
    doc = dict(base)
    effects, cuts, captions = [], [], [dict(c) for c in base.get("captions") or []]
    style = dict(base.get("caption_style") or {})
    keywords = []
    trim, cover, export = None, dict(base.get("cover_edit") or {}), dict(base.get("export") or {})
    n_eff = 0
    for o in ops:
        op, a = o["op"], o["args"]
        if op == "trim":
            trim = dict(start=a["start"], end=a["end"])
        elif op == "cut":
            cuts.append(dict(start=a["start"], end=a["end"]))
        elif op == "caption":
            for c in captions:
                if c["i"] == a["i"]:
                    c["text"] = a["text"]
        elif op == "caption_style":
            style.update(a)
        elif op == "keyword":
            keywords = [k for k in keywords if k["word"] != a["word"]] + [dict(a)]
        elif op == "effect_add":
            n_eff = max([n_eff] + [int(e["id"][1:]) for e in effects])
            eid = a.get("id") or f"e{n_eff + 1}"
            effects.append(dict(id=eid, effect=a["effect"], start=a["start"], end=a["end"], params=dict(a["params"])))
        elif op == "effect_move":
            for e in effects:
                if e["id"] == a["id"]:
                    e.update(start=a["start"], end=a["end"])
        elif op == "effect_set":
            for e in effects:
                if e["id"] == a["id"]:
                    e["params"] = dict(e["params"], **a["params"])
        elif op == "effect_remove":
            effects = [e for e in effects if e["id"] != a["id"]]
        elif op == "cover":
            cover = dict(cover, **{k: v for k, v in a.items() if v is not None})
        elif op == "export":
            export = dict(platforms=a["platforms"])
    cuts.sort(key=lambda c: c["start"])
    doc.update(effects=effects, cuts=cuts, captions=captions, caption_style=style, keywords=keywords, trim=trim,
               cover_edit=cover, export=export)
    return doc


class Outputs:
    """Clip listing + the output editor, via the engine command when it exists, else the desk implementation."""

    def __init__(self, data_dir, history, runner=None, bus=None):
        self.dir = os.path.join(data_dir, "outputs")
        self.history, self.runner, self.bus = history, runner, bus
        self._real = None
        self._lock = threading.Lock()

    # ---------------------------------------------------------- capability
    def real(self):
        """True when ``python -m vstudio.project output`` exists (probed once)."""
        if self._real is None:
            ok = False
            if self.runner is not None:
                try:
                    txt = self.runner.sibling("vstudio.project").text(["output", "--help"])
                    ok = bool(re.search(r"\bshow\b", txt) and re.search(r"\bedit\b", txt) and
                              re.search(r"\brender\b", txt) and "invalid choice" not in txt)
                except Exception:  # noqa: BLE001
                    ok = False
            self._real = ok
        return self._real

    def _cli(self, args, timeout=600):
        return self.runner.sibling("vstudio.project").json(["output", *args, "--json"], timeout=timeout)

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
        need(isinstance(clip_id, str) and WK.CLIP_ID_RE.match(clip_id), "bad clip id")
        e = self._entry(item_id)
        for c in list_clips(e):
            if c["id"] == clip_id:
                return e, c
        raise KeyError(f"no clip {clip_id}")

    def _state_path(self, e, clip_id):
        key = hashlib.sha1(f"{os.path.realpath(e['dir'])}\0{clip_id}".encode()).hexdigest()[:16]
        return os.path.join(self.dir, f"{key}.json")

    def _state(self, e, clip_id):
        st = read_json(self._state_path(e, clip_id), None)
        return st if isinstance(st, dict) else dict(ops=[], undone=[], version=0, rendered=None)

    def _save(self, e, clip_id, st):
        write_json(self._state_path(e, clip_id), st)

    # ---------------------------------------------------------- show
    def _base(self, e, c):
        main = c["files"][0] if c["files"] else None
        file = main["path"] if main else None
        info = probe(file) if file else {}
        dur = (main or {}).get("duration") or info.get("duration") or c.get("duration") or 0
        words = _asr_for(file, c.get("workdir") or (os.path.join(e["dir"], "work", "clips", c.get("letter") or "")
                                                     if c.get("letter") else None)) if file else []
        dur = dur or (words[-1]["te"] if words else 0)
        jobdir = c.get("jobdir")
        captions, editable = [], False
        if jobdir:
            cues = read_json(os.path.join(jobdir, "compose", "cues.json"), None)
            rows = cues.get("cues") if isinstance(cues, dict) else cues
            for i, q in enumerate(rows or []):
                if isinstance(q, dict):
                    txt = q.get("text") if isinstance(q.get("text"), str) else "".join(q.get("lines") or [])
                    captions.append(dict(i=q.get("i", i), t=q.get("start", q.get("t0", 0)), te=q.get("end", q.get("t1", 0)),
                                         text=txt))
            editable = bool(captions)
            if not words:
                words = _words_from_asr(read_json(os.path.join(jobdir, "compose", "out", "final.mp4.asr.json"), None))
        if not captions and words:
            captions = _cues_from_words(words)
        capmode = "editable" if editable else ("flattened" if e["kind"] == "work" and captions else
                                               ("flattened" if captions else "none"))
        return dict(id=c["id"], title=c["title"], state=c["state"], file=file, files=c["files"], cover=c.get("cover"),
                    post=c.get("post"), duration=dur, fps=(main or {}).get("fps") or info.get("fps") or 30,
                    w=(main or {}).get("w") or info.get("w"), h=(main or {}).get("h") or info.get("h"),
                    words=words, captions=captions, caption_style=dict(size=1.0, color="#FFFFFF",
                                                                         keyword_color="#FFD60A", position="bottom"),
                    cover_edit=dict(t=None, title=(c.get("post") or {}).get("title") or c["title"], subtitle=""),
                    export=dict(platforms=[f["aspect"] for f in c["files"] if f["aspect"] in ASPECTS] or ["3:4"]),
                    safe_box=(main or {}).get("safe_box"), caption_box=(main or {}).get("caption_box"),
                    caps=dict(trim=bool(file), cut=bool(file) and bool(words), captions=capmode,
                              effects=bool(file), cover=bool(file), export=list(ASPECTS)),
                    notes=dict(captions=FLATTENED_NOTE if capmode == "flattened" else
                               (NO_CAPTIONS_NOTE if capmode == "none" else None)),
                    waveform=waveform(words, dur))

    def show(self, item_id, clip_id):
        e, c = self._clip(item_id, clip_id)
        if self.real():
            doc = self._cli(["show", "--dir", e["dir"], "--output", clip_id])
            doc = dict(doc, engine="real", item=item_id)
        else:
            base = self._base(e, c)
            st = self._state(e, clip_id)
            doc = fold(base, st["ops"])
            by_id = {x["id"]: x for x in EFFECTS}
            for x in doc["effects"]:
                x["label"] = (by_id.get(x["effect"]) or {}).get("label", x["effect"])
            last_render_n = (st.get("rendered") or {}).get("n", 0)
            doc.update(ops=[dict(o, label=op_label(o["op"], o["args"], by_id)) for o in st["ops"]],
                       version=st["version"], rendered=st.get("rendered"), engine="desk", item=item_id,
                       dirty=bool(st["ops"]) and (st["ops"][-1]["n"] > last_render_n),
                       can_redo=bool(st.get("undone")))
        paths = [f["path"] for f in doc.get("files") or []] + [doc.get("cover")] + \
            [f.get("path") for f in ((doc.get("rendered") or {}).get("files") or [])]
        self.history.allow_media([p for p in paths if p])
        return doc

    # ---------------------------------------------------------- edit / undo / render
    def _adopt_on_first_edit(self, e):
        """「转成项目」 happens transparently: a plain work folder gets its record on the first edit."""
        if e["kind"] == "work" and not os.path.exists(WK.record_path(e["dir"])):
            try:
                self.history.adopt(e["id"])
            except Exception:  # noqa: BLE001  (read-only folder: the edit log lives in the desk data dir anyway)
                pass

    def edit(self, item_id, clip_id, ops):
        e, c = self._clip(item_id, clip_id)
        need(isinstance(ops, list) and 0 < len(ops) <= 50, "ops: 1-50 edits")
        checked = [validate_op(o) for o in ops]
        self._adopt_on_first_edit(e)
        if self.real():
            last = None
            for op, a in checked:
                last = self._cli(["edit", "--dir", e["dir"], "--output", clip_id, "--op",
                                  json.dumps(dict(a, op=op), ensure_ascii=False)])
            self._publish(item_id, clip_id)
            return dict(last or {}, ok=True)
        base = self._base(e, c)
        with self._lock:
            st = self._state(e, clip_id)
            for op, a in checked:
                if op == "caption" or op == "caption_style":
                    need(base["caps"]["captions"] == "editable", FLATTENED_NOTE if base["caps"]["captions"] == "flattened"
                         else NO_CAPTIONS_NOTE)
                if op in ("trim", "cut", "effect_add", "effect_move"):
                    need(a["start"] <= (base["duration"] or 1e9) + 0.05, "start is after the end of the clip")
                if op == "effect_add":
                    need(a["effect"] in EFFECT_IDS, f"unknown effect {a['effect']}")
                    cur = fold(base, st["ops"])["effects"]
                    a = dict(a, id=f"e{max([0] + [int(x['id'][1:]) for x in cur]) + 1}")
                if op in ("effect_move", "effect_set", "effect_remove"):
                    need(any(x["id"] == a["id"] for x in fold(base, st["ops"])["effects"]), f"no effect {a['id']}")
                n = max([0] + [o["n"] for o in st["ops"]] + [o["n"] for o in st.get("undone") or []]) + 1
                st["ops"].append(dict(n=n, op=op, args=a, at=time.strftime("%Y-%m-%dT%H:%M:%S")))
            st["undone"] = []
            st["version"] = st.get("version", 0)
            self._save(e, clip_id, st)
        self._publish(item_id, clip_id)
        return dict(ok=True, ops=st["ops"], version=st["version"])

    def undo(self, item_id, clip_id, n=None):
        e, _c = self._clip(item_id, clip_id)
        if self.real():
            args = ["undo", "--dir", e["dir"], "--output", clip_id] + (["--n", str(n)] if n else [])
            r = self._cli(args)
            self._publish(item_id, clip_id)
            return r
        with self._lock:
            st = self._state(e, clip_id)
            need(st["ops"], "nothing to undo")
            if n is None:
                gone = [st["ops"].pop()]
            else:
                gone = [o for o in st["ops"] if o["n"] >= n]
                need(gone, f"no edit {n}")
                st["ops"] = [o for o in st["ops"] if o["n"] < n]
            st["undone"] = (st.get("undone") or []) + gone
            self._save(e, clip_id, st)
        self._publish(item_id, clip_id)
        return dict(ok=True, ops=st["ops"], undone=[o["n"] for o in gone], version=st["version"])

    def render(self, item_id, clip_id, platforms=None):
        e, c = self._clip(item_id, clip_id)
        if platforms is not None:
            need(isinstance(platforms, list) and all(p in ASPECTS for p in platforms), "platforms: 3:4 | 9:16 | 16:9")
        if self.real():
            args = ["render", "--dir", e["dir"], "--output", clip_id] + \
                (["--platforms", ",".join(platforms)] if platforms else [])
            r = self._cli(args, timeout=3 * 3600)
            self._publish(item_id, clip_id)
            return r
        with self._lock:
            st = self._state(e, clip_id)
            st["version"] = st.get("version", 0) + 1
            want = platforms or fold(self._base(e, c), st["ops"])["export"].get("platforms") or []
            files = [dict(aspect=f["aspect"], path=f["path"]) for f in c["files"] if not want or f["aspect"] in want] or \
                [dict(aspect=f["aspect"], path=f["path"]) for f in c["files"]]
            st["rendered"] = dict(version=st["version"], n=max([0] + [o["n"] for o in st["ops"]]), files=files,
                                  at=time.strftime("%Y-%m-%dT%H:%M:%S"), simulated=True, ops=len(st["ops"]))
            self._save(e, clip_id, st)
        self._publish(item_id, clip_id)
        return dict(ok=True, version=st["version"], files=files, simulated=True)

    # ---------------------------------------------------------- 让 AI 改 (natural language -> proposed ops)
    def ask(self, item_id, clip_id, prompt):
        need(isinstance(prompt, str) and 0 < len(prompt.strip()) <= 500, "prompt: 1-500 chars")
        e, c = self._clip(item_id, clip_id)
        if self.real():
            return self._cli(["edit", "--dir", e["dir"], "--output", clip_id, "--ask", prompt, "--dry-run"],
                             timeout=600)
        doc = fold(self._base(e, c), self._state(e, clip_id)["ops"])
        return propose(doc, prompt)

    def effects(self):
        if self.real():
            try:
                doc = self._cli(["effects"], timeout=60)
                if isinstance(doc, dict) and isinstance(doc.get("effects"), list):
                    return dict(doc, engine="real")
            except Exception:  # noqa: BLE001
                pass
        return dict(effects=EFFECTS, engine="desk")

    def _publish(self, item_id, clip_id):
        if self.bus:
            self.bus.publish("output-edit", item=item_id, clip=clip_id)


# ------------------------------------------------------------------ rule-based proposals (desk implementation)
def _find_word(words, needle):
    """The first word index where the transcript (joined) contains ``needle`` -> (start, end) seconds."""
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
    """Natural language -> proposals [{id, label, why, ops}] over the clip's transcript (desk rules; the engine's
    model replaces this when ``output edit --ask`` exists)."""
    p = prompt.strip()
    words = doc.get("words") or []
    dur = doc.get("duration") or (words[-1]["te"] if words else 0)
    props, notes = [], []
    quoted = re.findall(r"[「“\"']([^」”\"']{1,40})[」”\"']", p)

    def add(label, why, ops):
        props.append(dict(id=f"p{len(props) + 1}", label=label, why=why, ops=ops))

    if re.search(r"开头|开始|从", p) and (quoted or re.search(r"太慢|拖|啰嗦|快一点", p)):
        hit = _find_word(words, quoted[0]) if quoted else None
        start = hit[0] if hit else min(2.0, dur / 4 if dur else 2.0)
        end = (doc.get("trim") or {}).get("end") or dur
        add(f"开头前移 {start:.1f} 秒", f"从「{quoted[0]}」直接开始" if hit else "去掉开头没进入正题的部分",
            [dict(op="trim", start=round(start, 3), end=round(end, 3))])
    if re.search(r"紧凑|停顿|气口|节奏快", p) and words:
        gaps = [(a["te"] + 0.08, b["t"] - 0.08) for a, b in zip(words, words[1:]) if b["t"] - a["te"] > 0.6]
        if gaps:
            add(f"去掉 {len(gaps)} 处停顿", "每处超过 0.6 秒的停顿缩到很短",
                [dict(op="cut", start=round(a, 3), end=round(z, 3)) for a, z in gaps[:20]])
        else:
            notes.append("没有找到明显的停顿。")
    if re.search(r"弹|强调|突出", p):
        m = re.search(r"[「“\"']([^」”\"']{1,20})[」”\"']\s*(?:弹|强调|突出)", p) or \
            re.search(r"(?:弹字|弹出|强调|突出)\s*[：:]?\s*[「“\"']?([^」”\"'，,。\s]{1,20})", p)
        word = (m.group(1) if m else "").strip()
        hit = _find_word(words, word) if word else None
        if hit:
            add(f"「{word}」弹字", "在说到这个词时弹出来",
                [dict(op="effect_add", effect="pop-word", start=hit[0], end=round(hit[0] + 1.2, 3),
                      params=dict(text=word, color="#FFD60A"))])
        elif word:
            notes.append(f"逐字稿里没有找到「{word}」。")
    if re.search(r"字幕.*(大|小|颜色|黄|白)", p):
        if (doc.get("caps") or {}).get("captions") == "editable":
            size = 1.2 if "大" in p else 0.85 if "小" in p else 1.0
            add("字幕样式", "按你说的调整字幕", [dict(op="caption_style", size=size)])
        else:
            notes.append((doc.get("notes") or {}).get("captions") or FLATTENED_NOTE)
    if re.search(r"封面", p):
        t = round(min(dur * 0.3, 8.0), 2) if dur else 0
        add("换封面", f"用 {_fmt(t)} 这一帧，标题不变", [dict(op="cover", t=t, title=(doc.get("cover_edit") or {}).get("title", ""))])
    if re.search(r"抖音|9[:：比]16|竖屏", p):
        cur = (doc.get("export") or {}).get("platforms") or []
        add("加一个 9:16 版本", "抖音 / 视频号用 9:16", [dict(op="export", platforms=list(dict.fromkeys(cur + ["9:16"])))])
    if re.search(r"推近|放大|zoom", p, re.I):
        hit = _find_word(words, quoted[0]) if quoted else None
        t = hit[0] if hit else (dur / 2 if dur else 0)
        add("推近强调", "在这句话上慢慢推近", [dict(op="effect_add", effect="punch-in", start=round(t, 3),
                                              end=round(min(dur or t + 3, t + 3), 3), params=dict(scale=1.14))])
    m = re.search(r"(?:最后|结尾).*(?:(\d+)\s*秒)", p)
    if m and dur:
        cut = float(m.group(1))
        add(f"去掉最后 {cut:g} 秒", "结尾收得更干净",
            [dict(op="trim", start=(doc.get("trim") or {}).get("start") or 0, end=round(max(0.5, dur - cut), 3))])
    if not props and not notes:
        notes.append("这句我还没看懂。可以试试：「从『…』开始」「再紧凑一点」「把『…』弹出来」「换个封面」「出抖音版」。")
    summary = "；".join(x["label"] for x in props) if props else ""
    return dict(summary_zh=(f"我准备这样改：{summary}。" if summary else "") + " ".join(notes), proposals=props,
                engine="desk")
