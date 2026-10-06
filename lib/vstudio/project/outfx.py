"""Effects a finished output can get in a second-pass edit (``python -m vstudio.project output ...``).

Every entry is a row of the effects registry (``vstudio.effects.REGISTRY``; the id IS the registry id, so the
catalogue can never name an effect the registry does not have) plus what the output editor needs: a zh / en
label, the stage that renders it, a params schema (JSON-Schema subset: type, default, minimum, maximum, enum,
x-zh, required) and, for the frame pass, a layer class that draws one instance on a BGR frame.

    from vstudio.project import outfx as FX
    FX.catalogue()                              # -> [{id, labels, kind, stage, params, default_dur, ...}]
    FX.resolve("stamp")                         # alias -> "stacking-stamps" (None when unknown)
    clean, warns = FX.validate("pop-words", {"text": "重点", "size": 3})   # coerced + clamped
    layer = FX.make_layer(inst, W, H, safe)     # frame-pass layer; layer.draw(img_bgr, t_local, dur)
    FX.thumbnail("quote-card", out_png)         # a sample frame with the effect drawn on it

Stages (what re-renders when an instance changes; see outrender):
  frame     PIL / numpy layer drawn per frame (overlays, cards, punch-in, progress bar, red box)
  audio     mixed into the audio stem (SFX, music bed)
  timeline  ffmpeg on the cut timeline (transitions at cut joins, grade, end fade)

Positions are fractions of the canvas (x, y = the centre), so the same instance re-lays out on a 3:4, 9:16 or
16:9 export; layers are clamped into the platform safe box.
"""
import math
import os

import numpy as np
from PIL import Image, ImageDraw

from vstudio import draw as D
from vstudio import overlays as O

POS = dict(x={"type": "number", "default": 0.5, "minimum": 0.0, "maximum": 1.0, "x-zh": "水平位置"},
           y={"type": "number", "default": 0.4, "minimum": 0.0, "maximum": 1.0, "x-zh": "垂直位置"})


def _pos(x=0.5, y=0.4):
    return dict(x=dict(POS["x"], default=x), y=dict(POS["y"], default=y))


def _num(default, lo, hi, zh):
    return {"type": "number", "default": default, "minimum": lo, "maximum": hi, "x-zh": zh}


def _str(default, zh, required=False, enum=None):
    d = {"type": "string", "default": default, "x-zh": zh}
    if required:
        d["required"] = True
    if enum:
        d["enum"] = list(enum)
    return d


ANIMS = ("pop", "slam", "slide", "fade", "none")
COLOR = {"type": "string", "default": None, "x-zh": "颜色 (#RRGGBB, 空 = 品牌色)", "format": "color"}


def _sfx_names():
    try:
        from vstudio import audio
        return sorted(audio.sfx_bank().keys())
    except Exception:  # noqa: BLE001
        return ["pop", "whoosh", "stamp", "ding", "thud", "swoosh", "sparkle", "riser", "impact"]


def _transitions():
    from vstudio import xfade
    return list(xfade.names())


# id -> spec. kind: overlay | camera | fullframe | progress | box | audio | join | look | end
SPECS = {
    "pop-words": dict(
        zh="弹出大字", en="Pop word", kind="overlay", stage="frame", default_dur=1.2, anim="pop",
        what_zh="一个大字 / 短词带描边弹出（重点词）",
        params=dict(text=_str("", "文字", True), color=COLOR, size=_num(0.11, 0.04, 0.25, "字号 (画面短边比例)"),
                    angle=_num(-4, -30, 30, "角度"), anim=_str("pop", "动画", enum=ANIMS), **_pos(0.5, 0.42)),
        sample=dict(text="重点")),
    "stacking-stamps": dict(
        zh="印章", en="Stamp", kind="overlay", stage="frame", default_dur=1.5, anim="slam",
        what_zh="白底描边印章从 2.2 倍砸入（亲测 / 划重点）",
        params=dict(text=_str("", "文字", True), angle=_num(8, -30, 30, "角度"), scale=_num(1.0, 0.4, 3.0, "大小"),
                    anim=_str("slam", "动画", enum=ANIMS), **_pos(0.72, 0.3)),
        sample=dict(text="亲测")),
    "punch-in": dict(
        zh="推镜放大", en="Punch-in zoom", kind="camera", stage="frame", default_dur=3.0,
        what_zh="画面缓推放大一段时间再回来（强调一句话）",
        params=dict(scale=_num(1.14, 1.02, 1.4, "放大倍数"), in_dur=_num(0.45, 0.1, 2.0, "推入时长"),
                    out_dur=_num(0.5, 0.1, 2.0, "拉回时长"), hold=_str("return", "结束方式", enum=("return", "stay")),
                    **_pos(0.5, 0.38)),
        sample=dict(scale=1.2)),
    "quote-card": dict(
        zh="金句卡", en="Quote card", kind="overlay", stage="frame", default_dur=3.0, anim="slide",
        what_zh="引号金句卡片 + 说话人",
        params=dict(text=_str("", "金句", True), speaker=_str("", "说话人"), width=_num(0.84, 0.4, 0.96, "宽度"),
                    theme=_str(None, "主题", enum=O.THEMES), anim=_str("slide", "动画", enum=ANIMS), **_pos(0.5, 0.3)),
        sample=dict(text="把复杂的事情讲简单", speaker="Speaker A")),
    "callout-bubble": dict(
        zh="标注气泡 / 箭头", en="Callout (+ arrow)", kind="overlay", stage="frame", default_dur=2.5, anim="slide",
        what_zh="说明气泡，可加一根指向画面某点的箭头",
        params=dict(text=_str("", "文字", True), arrow_x=_num(None, 0.0, 1.0, "箭头指向 x (空 = 无箭头)"),
                    arrow_y=_num(None, 0.0, 1.0, "箭头指向 y"), theme=_str(None, "主题", enum=O.THEMES),
                    anim=_str("slide", "动画", enum=ANIMS), **_pos(0.5, 0.3)),
        sample=dict(text="这里是关键", arrow_x=0.75, arrow_y=0.55)),
    "chapter-card": dict(
        zh="章节卡", en="Chapter card", kind="fullframe", stage="frame", default_dur=1.6, anim="fade",
        what_zh="整屏章节卡（02 / 05 + 标题）",
        params=dict(title=_str("", "标题", True), index=_num(1, 1, 99, "序号"), total=_num(0, 0, 99, "总数 (0 = 不显示)"),
                    accent=COLOR),
        sample=dict(title="第二部分：怎么做", index=2, total=3)),
    "notes-panel": dict(
        zh="记笔记面板", en="Notes panel", kind="overlay", stage="frame", default_dur=4.0, anim="slide",
        what_zh="标题 + 要点的笔记卡片",
        params=dict(title=_str("", "标题", True), bullets={"type": "array", "items": {"type": "string"},
                                                          "default": [], "x-zh": "要点"},
                    theme=_str(None, "主题", enum=O.THEMES), width=_num(0.8, 0.4, 0.95, "宽度"),
                    anim=_str("slide", "动画", enum=ANIMS), **_pos(0.5, 0.3)),
        sample=dict(title="三个要点", bullets=["先定目标", "再拆步骤", "【每天复盘】"])),
    "overlay-images": dict(
        zh="贴纸 / 标签", en="Sticker / label", kind="overlay", stage="frame", default_dur=2.0, anim="pop",
        what_zh="图片贴纸，或文字标签（chip / badge / tag）",
        params=dict(image=_str(None, "图片 (PNG 路径)"), text=_str("", "文字"),
                    style=_str("tag", "样式", enum=("tag", "chip", "badge", "star", "image")),
                    color=COLOR, scale=_num(1.0, 0.2, 4.0, "大小"), angle=_num(0, -45, 45, "角度"),
                    anim=_str("pop", "动画", enum=ANIMS), **_pos(0.8, 0.2)),
        sample=dict(text="新手必看", style="tag")),
    "badge": dict(
        zh="角标", en="Badge", kind="overlay", stage="frame", default_dur=3.0, anim="slide",
        what_zh="实心圆角标（精彩预告 / 精选）",
        params=dict(text=_str("", "文字", True), color=COLOR, scale=_num(1.0, 0.4, 3.0, "大小"),
                    anim=_str("slide", "动画", enum=ANIMS), **_pos(0.2, 0.12)),
        sample=dict(text="精彩预告")),
    "red-box": dict(
        zh="框选高亮", en="Red box", kind="box", stage="frame", default_dur=2.0, anim="pop",
        what_zh="圆角描边框圈出画面一块区域",
        params=dict(x=_num(0.5, 0.0, 1.0, "中心 x"), y=_num(0.5, 0.0, 1.0, "中心 y"), w=_num(0.4, 0.02, 1.0, "宽"),
                    h=_num(0.12, 0.02, 1.0, "高"), color=COLOR, width=_num(6, 2, 24, "线宽 (px, 1080 宽)"),
                    anim=_str("pop", "动画", enum=ANIMS)),
        sample=dict(x=0.5, y=0.55, w=0.6, h=0.12)),
    "progress-bar-pil": dict(
        zh="进度条", en="Progress bar", kind="progress", stage="frame", default_dur=None,
        what_zh="章节进度条（整条视频，可分章节）",
        params=dict(style=_str("refined", "样式", enum=("classic", "refined")),
                    chapters={"type": "array", "default": [], "x-zh": "章节 [{start, end, label}] (源时间秒)",
                              "items": {"type": "object"}},
                    y=_num(0.9, 0.0, 1.0, "垂直位置"), theme=_str(None, "主题", enum=O.THEMES)),
        sample=dict(chapters=[dict(start=0, end=4, label="问题"), dict(start=4, end=8, label="方法"),
                              dict(start=8, end=12, label="总结")])),
    "sfx-placement": dict(
        zh="音效", en="Sound effect", kind="audio", stage="audio", default_dur=0.5,
        what_zh="在某个时间点加一个合成音效（pop / whoosh / ding ...）",
        params=dict(name=_str("pop", "音效", enum=_sfx_names()), gain=_num(1.0, 0.0, 3.0, "音量倍数"))),
    "music-bed": dict(
        zh="背景音乐", en="Music bed", kind="audio", stage="audio", default_dur=None,
        what_zh="铺背景音乐，人声处自动压低",
        params=dict(file=_str(None, "音乐文件", True), duck_db=_num(-10, -30, 0, "压低 dB"),
                    music_lufs=_num(-30, -45, -14, "音乐响度 LUFS"))),
    "xfade-joins": dict(
        zh="转场", en="Transition", kind="join", stage="timeline", default_dur=0.4,
        what_zh="剪辑点上的转场（淡化 / 推移 / 闪白 ...）；不在剪辑点时做一次闪 / 黑场过渡",
        params=dict(transition=_str("fade", "转场", enum=_transitions()), duration=_num(0.4, 0.1, 1.5, "时长"))),
    "end-fade": dict(
        zh="结尾淡出", en="End fade", kind="end", stage="timeline", default_dur=None,
        what_zh="结尾画面和声音淡出（从不淡入，首帧不黑）",
        params=dict(duration=_num(1.0, 0.2, 4.0, "时长"))),
    "vlog-grade": dict(
        zh="调色", en="Grade", kind="look", stage="timeline", default_dur=None,
        what_zh="整片调色：饱和度 / 对比度 / 暖色",
        params=dict(sat=_num(1.12, 0.5, 1.6, "饱和度"), contrast=_num(1.05, 0.7, 1.4, "对比度"),
                    warm={"type": "boolean", "default": True, "x-zh": "暖色"})),
}

ALIASES = {
    "pop": "pop-words", "pop-word": "pop-words", "popword": "pop-words", "弹出大字": "pop-words", "大字": "pop-words",
    "stamp": "stacking-stamps", "stamp-hf": "stacking-stamps", "印章": "stacking-stamps",
    "punch": "punch-in", "zoom": "punch-in", "punch-and-stay": "punch-in", "推镜": "punch-in", "放大": "punch-in",
    "quote": "quote-card", "金句": "quote-card", "金句卡": "quote-card",
    "callout": "callout-bubble", "callout-arrow": "callout-bubble", "arrow": "callout-bubble", "气泡": "callout-bubble",
    "箭头": "callout-bubble",
    "chapter": "chapter-card", "章节": "chapter-card", "章节卡": "chapter-card",
    "notes": "notes-panel", "panel": "notes-panel", "记笔记": "notes-panel", "笔记": "notes-panel",
    "sticker": "overlay-images", "label": "overlay-images", "tag": "overlay-images", "贴纸": "overlay-images",
    "标签": "overlay-images", "角标": "badge",
    "box": "red-box", "highlight-box": "red-box", "框": "red-box", "框选": "red-box",
    "progress": "progress-bar-pil", "progress-bar": "progress-bar-pil", "progress-ffmpeg": "progress-bar-pil",
    "hf-progress": "progress-bar-pil", "进度条": "progress-bar-pil",
    "sfx": "sfx-placement", "sound": "sfx-placement", "sfx-bank": "sfx-placement", "音效": "sfx-placement",
    "music": "music-bed", "bgm": "music-bed", "配乐": "music-bed", "背景音乐": "music-bed",
    "transition": "xfade-joins", "xfade": "xfade-joins", "转场": "xfade-joins", "light-leak": "xfade-joins",
    "fade-out": "end-fade", "淡出": "end-fade",
    "grade": "vlog-grade", "look": "vlog-grade", "调色": "vlog-grade",
}


def resolve(name):
    """An effect id / alias / zh label -> the catalogue id, or None (never a guess outside the catalogue)."""
    if not name:
        return None
    n = str(name).strip()
    if n in SPECS:
        return n
    low = n.lower()
    if low in SPECS:
        return low
    if low in ALIASES:
        return ALIASES[low]
    for k, s in SPECS.items():
        if n in (s["zh"], s["en"]) or low == s["en"].lower():
            return k
    return None


def _registry():
    from vstudio import effects
    return effects.REGISTRY


def catalogue(thumbs=False, thumb_dir=None):
    """The output-edit effect catalogue: [{id, label {en, zh}, description {en, zh}, kind, stage, category, params,
    required, default_dur, energy, max_uses, pitfalls, aliases, thumbnail}]; registry fields come from the registry
    row (``labels`` / ``what`` / ``what_zh`` are kept as aliases of label / description)."""
    reg = _registry()
    out = []
    for k, s in SPECS.items():
        r = reg[k]
        row = dict(id=k, registry_id=k, label=dict(en=s["en"], zh=s["zh"]), labels=dict(en=s["en"], zh=s["zh"]),
                   description=dict(en=r["what"], zh=s["what_zh"]), what=r["what"], what_zh=s["what_zh"], kind=s["kind"],
                   stage=s["stage"], category=r["category"], params=s["params"],
                   required=[p for p, d in s["params"].items() if d.get("required")],
                   default_dur=s["default_dur"], energy=r["energy"], max_uses=r["max_uses"], when=r["when"],
                   pitfalls=r["pitfalls"], aliases=sorted(a for a, v in ALIASES.items() if v == k), thumbnail=None)
        if thumbs:
            try:
                row["thumbnail"] = thumbnail(k, os.path.join(thumb_dir or _thumb_dir(), f"{k}.png"))
            except Exception as e:  # noqa: BLE001  (a missing font must not hide the catalogue)
                row["thumbnail_error"] = str(e)[:160]
        out.append(row)
    return out


def _thumb_dir():
    from vstudio.config import cache_dir
    return cache_dir("output_fx")


def _coerce(name, d, v):
    t = d.get("type")
    if v is None:
        return None
    if t == "number":
        v = float(v)
        if not math.isfinite(v):
            raise ValueError("not a finite number")
        lo, hi = d.get("minimum"), d.get("maximum")
        if lo is not None and v < lo:
            return lo, f"{name}={v:g} raised to {lo:g}"
        if hi is not None and v > hi:
            return hi, f"{name}={v:g} lowered to {hi:g}"
        return v
    if t == "boolean":
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on", "是")
        return bool(v)
    if t == "array":
        if isinstance(v, str):
            import re
            v = [x.strip() for x in re.split(r"[|｜\n]", v) if x.strip()]
        if not isinstance(v, (list, tuple)):
            raise ValueError("expected a list")
        return list(v)
    if t == "string":
        if isinstance(v, (dict, list)):
            raise ValueError("expected text")
        v = str(v)
        if d.get("enum") and v not in d["enum"]:
            raise ValueError(f"one of {', '.join(map(str, d['enum'][:12]))}")
        return v
    return v


def validate(eid, params, partial=False):
    """-> (clean params with defaults filled, warnings). Unknown params are dropped (warned), values coerced /
    clamped, bad enum values reset to the default. Raises ValueError for an unknown effect or a missing required
    param (``partial``: a patch, required params are not checked and defaults are not filled)."""
    k = resolve(eid)
    if not k:
        raise ValueError(f"unknown effect {eid!r} (output effects --json lists them)")
    spec = SPECS[k]["params"]
    clean, warns = ({} if partial else {p: d.get("default") for p, d in spec.items()}), []
    for p, v in (params or {}).items():
        if p not in spec:
            warns.append(f"{k}: unknown param {p!r} dropped")
            continue
        try:
            r = _coerce(p, spec[p], v)
        except (TypeError, ValueError) as e:
            warns.append(f"{k}: {p}: {e}; kept {'the old value' if partial else 'the default'}")
            continue
        if isinstance(r, tuple):
            r, w = r
            warns.append(f"{k}: {w}")
        clean[p] = r
    if not partial:
        for p, d in spec.items():
            if d.get("required") and clean.get(p) in (None, "", []):
                raise ValueError(f"{k}: {p} is required ({d.get('x-zh', p)})")
        if k == "music-bed" and not os.path.exists(str(clean.get("file") or "")):
            raise ValueError(f"music-bed: no file {clean.get('file')!r}")
        if k == "overlay-images" and clean.get("style") == "image" and not os.path.exists(str(clean.get("image") or "")):
            raise ValueError(f"overlay-images: style image needs an existing image file, got {clean.get('image')!r}")
        if k == "overlay-images" and not clean.get("image") and not clean.get("text"):
            raise ValueError("overlay-images: text or image is required")
    return clean, warns


def spec(eid):
    return SPECS[resolve(eid)]


# --------------------------------------------------------------------------- animation helpers
def ease_out_back(u, s=1.70158):
    u = min(1.0, max(0.0, u)) - 1.0
    return 1.0 + (s + 1) * u ** 3 + s * u ** 2


def ease_in_out(u):
    u = min(1.0, max(0.0, u))
    return 0.5 - 0.5 * math.cos(math.pi * u)


def anim_state(anim, t, dur, inn=0.22, out=0.18):
    """(scale, opacity, dy_px_frac) of an overlay ``t`` s into its window of ``dur`` s."""
    if anim == "none":
        return 1.0, 1.0, 0.0
    fade_out = min(1.0, max(0.0, (dur - t) / out)) if dur else 1.0
    if anim == "pop":
        u = t / inn
        return (0.6 + 0.4 * ease_out_back(u)) if u < 1 else 1.0, min(1.0, u * 2) * fade_out, 0.0
    if anim == "slam":
        u = t / 0.18
        return (2.2 - 1.2 * ease_in_out(u)) if u < 1 else 1.0, min(1.0, u * 1.6) * fade_out, 0.0
    if anim == "slide":
        u = min(1.0, t / 0.3)
        return 1.0, ease_in_out(u) * fade_out, (1 - ease_in_out(u)) * 0.0125
    u = min(1.0, t / 0.25)                               # fade
    return 1.0, u * fade_out, 0.0


# --------------------------------------------------------------------------- layers
class Layer:
    """One effect instance on a W x H canvas. ``draw(img, t, dur)``: img = BGR uint8 frame (modified in place),
    t = seconds since the instance start (edited timeline), dur = its edited duration."""
    camera = False

    def __init__(self, inst, W, H, safe=None):
        self.inst, self.W, self.H = inst, int(W), int(H)
        self.p = dict(inst.get("params") or {})
        self.safe = tuple(safe) if safe else (W * 0.05, H * 0.05, W * 0.95, H * 0.95)
        self.u = min(W, H) / 1080.0                      # design px (1080 short side) -> canvas px
        self.oscale = 1.5 * self.u                       # vstudio.overlays sizes are designed for 1920 landscape

    def draw(self, img, t, dur):
        raise NotImplementedError


class ImageLayer(Layer):
    """An RGBA image placed at (x, y) centre, clamped into the safe box, animated (pop / slam / slide / fade)."""
    anim_default = "pop"

    def image(self):
        raise NotImplementedError

    def setup(self):
        im = self.image()
        mw, mh = (self.safe[2] - self.safe[0]), (self.safe[3] - self.safe[1])
        if im.width > mw or im.height > mh:
            k = min(mw / im.width, mh / im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        self.rgba = np.asarray(im.convert("RGBA"))
        self._scaled = {}
        h, w = self.rgba.shape[:2]
        cx, cy = float(self.p.get("x", 0.5)) * self.W, float(self.p.get("y", 0.4)) * self.H
        cx = min(max(cx, self.safe[0] + w / 2), self.safe[2] - w / 2) if w < mw else (self.safe[0] + self.safe[2]) / 2
        cy = min(max(cy, self.safe[1] + h / 2), self.safe[3] - h / 2) if h < mh else (self.safe[1] + self.safe[3]) / 2
        self.cx, self.cy = cx, cy

    def scaled(self, s):
        q = round(s, 2)
        if q == 1.0:
            return self.rgba
        if q not in self._scaled:
            h, w = self.rgba.shape[:2]
            self._scaled[q] = np.asarray(Image.fromarray(self.rgba).resize(
                (max(1, int(w * q)), max(1, int(h * q))), Image.BILINEAR))
        return self._scaled[q]

    def draw(self, img, t, dur):
        if not hasattr(self, "rgba"):
            self.setup()
        s, op, dy = anim_state(self.p.get("anim") or self.anim_default, t, dur)
        if op <= 0.01:
            return img
        a = self.scaled(s)
        D.alpha_paste(img, a, (self.cx, self.cy + dy * self.H), opacity=op, center=True, bgr=True)
        return img


class PopWords(ImageLayer):
    def image(self):
        size = max(16, int(float(self.p.get("size") or 0.11) * min(self.W, self.H)))
        f = D.load_font("cjk-bold", size)
        col = self.p.get("color") or D.brand()["highlight"]
        im = D.text_layer(str(self.p["text"]), f, fill=D.rgba(col), stroke=max(3, size // 12),
                          max_w=int(self.W * 0.86))
        ang = float(self.p.get("angle") or 0)
        return im.rotate(ang, expand=True, resample=Image.BICUBIC) if ang else im


class Stamp(ImageLayer):
    anim_default = "slam"

    def image(self):
        return O.stamp(str(self.p["text"]), angle=float(self.p.get("angle") or 0),
                       scale=self.oscale * float(self.p.get("scale") or 1.0))


class QuoteCard(ImageLayer):
    anim_default = "slide"

    def image(self):
        T = O.get_theme(self.p.get("theme"))
        W = int(self.W * float(self.p.get("width") or 0.84))
        u = self.u
        fq = D.load_font("cjk-bold", max(14, int(52 * u)))
        fm = D.load_font("serif", max(14, int(120 * u)))
        fs = D.load_font("cjk", max(12, int(30 * u)))
        pad = int(44 * u)
        lines = D.wrap(str(self.p["text"]), fq, W - 2 * pad, balance=True)
        lh = int(sum(fq.getmetrics()) * 1.25)
        sp = str(self.p.get("speaker") or "")
        H = pad * 2 + int(70 * u) + lh * len(lines) + (int(54 * u) if sp else 0)
        im = D.rounded_rect((W, H), int(26 * u), T["bubble"])
        d = ImageDraw.Draw(im)
        d.text((pad - int(6 * u), pad - int(40 * u)), "“", font=fm, fill=T["accent"] + (255,))
        y = pad + int(70 * u)
        for ln in lines:
            D.draw_runs(d, (pad, y), ln, fq, T["bubble_text"], T["hl"])
            y += lh
        if sp:
            d.text((pad, y + int(10 * u)), "— " + sp, font=fs, fill=D.brand().get("teal", (45, 212, 191)) + (255,))
        return D.shadow(im, blur=int(12 * u) or 1, offset=(0, int(8 * u)))[0]


class Callout(ImageLayer):
    anim_default = "slide"

    def image(self):
        return O.callout(str(self.p["text"]), theme=self.p.get("theme"), scale=self.oscale)

    def draw(self, img, t, dur):
        if not hasattr(self, "rgba"):
            self.setup()
        ax, ay = self.p.get("arrow_x"), self.p.get("arrow_y")
        if ax is not None and ay is not None:
            _, op, _ = anim_state("fade", t, dur)
            if op > 0.01:
                self._arrow(img, op, float(ax) * self.W, float(ay) * self.H)
        return super().draw(img, t, dur)

    def _arrow(self, img, op, tx, ty):
        import cv2
        h, w = self.rgba.shape[:2]
        # start on the bubble edge facing the target
        sx = min(max(tx, self.cx - w / 2), self.cx + w / 2)
        sy = min(max(ty, self.cy - h / 2), self.cy + h / 2)
        if abs(sx - tx) + abs(sy - ty) < 8:
            return
        col = tuple(int(c) for c in O.get_theme(self.p.get("theme"))["accent"][::-1])
        th = max(3, int(7 * self.u))
        over = img.copy()
        cv2.arrowedLine(over, (int(sx), int(sy)), (int(tx), int(ty)), col, th, cv2.LINE_AA, tipLength=0.12)
        cv2.addWeighted(over, op, img, 1 - op, 0, dst=img)


class Notes(ImageLayer):
    anim_default = "slide"

    def image(self):
        w = int(self.W * float(self.p.get("width") or 0.8) / self.oscale)
        im = O.notes_panel(str(self.p["title"]), [str(b) for b in (self.p.get("bullets") or [])],
                           theme=self.p.get("theme"), width=max(200, w), scale=self.oscale)
        return D.shadow(im, blur=max(1, int(12 * self.u)), offset=(0, int(8 * self.u)))[0]


class Sticker(ImageLayer):
    def image(self):
        st = self.p.get("style") or "tag"
        sc = float(self.p.get("scale") or 1.0)
        if self.p.get("image") and (st == "image" or not self.p.get("text")):
            im = Image.open(self.p["image"]).convert("RGBA")
            k = 0.3 * min(self.W, self.H) * sc / max(im.width, im.height)
            im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
        elif st == "badge":
            im = O.badge(str(self.p["text"]), scale=self.oscale * sc, color=self.p.get("color"))
        elif st in ("chip", "star"):
            im = O.chip(str(self.p["text"]), style="filled" if st == "chip" else "star", scale=self.oscale * sc,
                        color=self.p.get("color"))
        else:
            im = O.tag(str(self.p["text"]), scale=self.oscale * sc * 0.7, fill=self.p.get("color"))
        ang = float(self.p.get("angle") or 0)
        return im.rotate(ang, expand=True, resample=Image.BICUBIC) if ang else im


class Badge(ImageLayer):
    anim_default = "slide"

    def image(self):
        return O.badge(str(self.p["text"]), scale=self.oscale * float(self.p.get("scale") or 1.0),
                       color=self.p.get("color"))


class RedBox(Layer):
    def draw(self, img, t, dur):
        import cv2
        s, op, _ = anim_state(self.p.get("anim") or "pop", t, dur)
        if op <= 0.01:
            return img
        cx, cy = float(self.p["x"]) * self.W, float(self.p["y"]) * self.H
        w, h = float(self.p["w"]) * self.W * s, float(self.p["h"]) * self.H * s
        col = D.rgb(self.p.get("color") or D.brand()["accent"])[::-1]
        th = max(2, int(float(self.p.get("width") or 6) * self.W / 1080))
        over = img.copy()
        r = int(min(w, h) * 0.12)
        x0, y0, x1, y1 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
        for (a, b), (c, d_) in (((x0 + r, y0), (x1 - r, y0)), ((x0 + r, y1), (x1 - r, y1)),
                                ((x0, y0 + r), (x0, y1 - r)), ((x1, y0 + r), (x1, y1 - r))):
            cv2.line(over, (a, b), (c, d_), col, th, cv2.LINE_AA)
        for (ccx, ccy), ang in (((x0 + r, y0 + r), 180), ((x1 - r, y0 + r), 270), ((x1 - r, y1 - r), 0),
                                ((x0 + r, y1 - r), 90)):
            cv2.ellipse(over, (ccx, ccy), (r, r), ang, 0, 90, col, th, cv2.LINE_AA)
        cv2.addWeighted(over, op, img, 1 - op, 0, dst=img)
        return img


class ChapterCard(Layer):
    def draw(self, img, t, dur):
        if not hasattr(self, "card"):
            im = O.chapter_card(int(self.p.get("index") or 1), int(self.p.get("total") or 0), str(self.p["title"]),
                                size=(self.W, self.H), accent=self.p.get("accent"))
            self.card = np.asarray(im.convert("RGB"))[..., ::-1].copy()
        k = 0.25
        op = min(1.0, t / k, max(0.0, (dur - t) / k)) if dur else 1.0
        if op >= 0.999:
            img[:] = self.card
        elif op > 0:
            img[:] = (self.card.astype(np.float32) * op + img.astype(np.float32) * (1 - op) + 0.5).astype(np.uint8)
        return img


class PunchIn(Layer):
    camera = True

    def factor(self, t, dur):
        s = float(self.p.get("scale") or 1.14)
        a, b = float(self.p.get("in_dur") or 0.45), float(self.p.get("out_dur") or 0.5)
        u = ease_in_out(t / a) if a > 0 else 1.0
        if self.p.get("hold") != "stay" and dur:
            u = min(u, ease_in_out((dur - t) / b) if b > 0 else 1.0)
        return 1.0 + (s - 1.0) * max(0.0, u)

    def draw(self, img, t, dur):
        import cv2
        z = self.factor(t, dur)
        if z <= 1.0005:
            return img
        ox, oy = float(self.p.get("x", 0.5)) * self.W, float(self.p.get("y", 0.38)) * self.H
        M = np.float32([[z, 0, ox * (1 - z)], [0, z, oy * (1 - z)]])
        # keep the zoomed frame covering the canvas (no border): clamp the translation
        M[0, 2] = min(0.0, max(self.W * (1 - z), M[0, 2]))
        M[1, 2] = min(0.0, max(self.H * (1 - z), M[1, 2]))
        img[:] = cv2.warpAffine(img, M, (self.W, self.H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        return img


class Progress(Layer):
    """Whole-clip chapter progress bar; ``draw`` gets the edited clock via ``t`` (instance starts at 0)."""

    def __init__(self, inst, W, H, safe=None):
        super().__init__(inst, W, H, safe)
        self.total = None
        self.chapters = inst.get("_chapters_edit") or []
        self._cache = {}

    def draw(self, img, t, dur):
        total = dur or 1.0
        chs = self.chapters or [(0.0, total, "")]
        q = round(t * 10) / 10.0
        if q not in self._cache:
            if len(self._cache) > 64:
                self._cache.clear()
            x0, x1 = int(self.safe[0]), int(self.safe[2])
            try:
                strip = O.progress_bar(chs, q, total, style=self.p.get("style") or "refined", width=self.W, x0=x0, x1=x1,
                                       theme=self.p.get("theme"))
            except Exception:  # noqa: BLE001  (labels that do not fit: a plain bar)
                strip = O.progress_bar([(0.0, total, "")], q, total, style="classic", width=self.W, x0=x0, x1=x1)
            self._cache[q] = np.asarray(strip.convert("RGBA"))
        a = self._cache[q]
        y = float(self.p.get("y") or 0.9) * self.H - a.shape[0] / 2
        y = min(max(y, self.safe[1]), self.safe[3] - a.shape[0])
        D.alpha_paste(img, a, (0, y), bgr=True)
        return img


LAYERS = {"pop-words": PopWords, "stacking-stamps": Stamp, "quote-card": QuoteCard, "callout-bubble": Callout,
          "notes-panel": Notes, "overlay-images": Sticker, "badge": Badge, "red-box": RedBox,
          "chapter-card": ChapterCard, "punch-in": PunchIn, "progress-bar-pil": Progress}


def make_layer(inst, W, H, safe=None):
    cls = LAYERS.get(inst["effect"])
    return cls(inst, W, H, safe) if cls else None


# --------------------------------------------------------------------------- thumbnails
def _sample_bg(W, H):
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    x = np.linspace(0, 1, W, dtype=np.float32)[None, :, None]
    a = np.array([60, 48, 40], np.float32)
    b = np.array([120, 96, 70], np.float32)
    img = a + (b - a) * (0.6 * y + 0.4 * x)
    img = np.broadcast_to(img, (H, W, 3)).copy()
    # a soft "face" disc so camera / box effects read
    yy, xx = np.mgrid[0:H, 0:W]
    m = ((xx - W * 0.5) ** 2 / (W * 0.18) ** 2 + (yy - H * 0.38) ** 2 / (H * 0.12) ** 2) < 1
    img[m] = img[m] * 0.5 + np.array([150, 170, 200], np.float32) * 0.5
    return np.clip(img, 0, 255).astype(np.uint8)


def thumbnail(eid, out, size=(360, 640)):
    """A sample frame (BGR canvas ``size``) with one instance of the effect at the middle of its window ->
    PNG ``out``. Audio / timeline effects get a labelled card. Cached: an existing file is reused."""
    k = resolve(eid)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return out
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    W, H = size
    s = SPECS[k]
    img = _sample_bg(W, H)
    if k in LAYERS:
        params, _ = validate(k, dict(s.get("sample") or {}))
        inst = dict(effect=k, params=params, start=0.0, end=4.0)
        if k == "progress-bar-pil":
            inst["_chapters_edit"] = [(c["start"], c["end"], c["label"]) for c in params["chapters"]]
            make_layer(inst, W, H).draw(img, 6.0, 12.0)
        else:
            dur = s["default_dur"] or 2.0
            make_layer(inst, W, H).draw(img, dur * 0.6 if k != "punch-in" else 1.0, dur)
        im = Image.fromarray(img[..., ::-1])
    else:
        im = Image.fromarray(img[..., ::-1]).convert("RGBA")
        f = D.load_font("cjk-bold", int(W * 0.1))
        lab = D.text_layer(s["zh"], f, stroke=3)
        im.alpha_composite(lab, ((W - lab.width) // 2, (H - lab.height) // 2))
        im = im.convert("RGB")
    im.save(out)
    return out
