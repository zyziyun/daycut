"""Platform profiles: canvas, UI safe zones, caption style, length / loudness / encode guidance, cover
and post-copy limits for 小红书, 抖音, TikTok, YouTube, YouTube Shorts and B站.

    from vstudio import platform as P
    p = P.profile("xiaohongshu", "vertical")      # Profile(w=1080, h=1440, ...); persona overrides merged
    P.safe_box(p)        -> (x0, y0, x1, y1)        UI-free area (top bar / bottom description / side buttons)
    P.caption_box(p)     -> (x0, y0, x1, y1)        where burned captions go
    P.cover_size(p)      -> (w, h)
    P.fit_text_size(p, "一行字幕")  -> {"size": 64, "lines": [...]}
    P.list_profiles()    -> ["xiaohongshu:vertical", "xiaohongshu:full", ...]

Every number is either sourced or marked "convention" in references/PLATFORMS.md. Platforms change their
UI often: treat safe zones as conservative defaults and override them in persona.local.yaml
(``platforms.<name>.<field>`` or ``platforms.<name>.orientations.<orientation>.<field>``, deep-merged).

Back-compat with older persona keys: ``platforms.<name>.title_max`` (also read by vstudio.publish),
``cover_aspect`` and ``safe_zone: {top, bottom, right_lower_keepout}`` (y coordinates on a 1080x1920
canvas; applied to the 1920-tall orientation).
"""
import copy
from dataclasses import asdict, dataclass, field

ALIASES = {"xhs": "xiaohongshu", "rednote": "xiaohongshu", "小红书": "xiaohongshu", "dy": "douyin", "抖音": "douyin",
           "yt": "youtube", "shorts": "youtube-shorts", "yt-shorts": "youtube-shorts", "youtube_shorts": "youtube-shorts",
           "b站": "bilibili", "bili": "bilibili", "tt": "tiktok"}
ORIENT_ALIASES = {"v": "vertical", "portrait": "vertical", "3:4": "vertical", "feed": "vertical",
                  "9:16": "full", "fullscreen": "full", "h": "horizontal", "landscape": "horizontal", "16:9": "horizontal"}

# ----------------------------------------------------------------------------------- shared blocks
_VERT_CAPTION = dict(size=[52, 72], max_chars_zh=14, max_chars_en=32, max_lines=2, stroke=0.09)
_HORZ_CAPTION = dict(size=[44, 60], max_chars_zh=22, max_chars_en=48, max_lines=2, stroke=0.08)
_LOUD = dict(lufs=-14.0, tp=-1.5)        # repo default (persona audio.loudness_lufs); see PLATFORMS.md

# name -> common fields + per-orientation fields. Coordinates are px on that orientation's canvas.
# safe: margins {top, bottom, left, right} + optional right_lower {w, from_y} keep-out (button column).
# caption.band: [y0, y1] of the caption block. length: seconds. encode: media.delivery_args kwargs.
PLATFORMS = {
    "xiaohongshu": dict(
        label="小红书 RedNote", default="vertical",
        title_max=20, title_count="xhs", desc_max=1000,
        hashtags=dict(style="inline", max=10, note="#话题 at the end of the body; counts toward 1000"),
        chapters=dict(supported=False, note="no native chapters; a 时间线 list in the body is the convention",
                      label_max=14),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[30, 180], max=900, min=5),
        orientations=dict(
            vertical=dict(w=1080, h=1440, aspect="3:4",
                          safe=dict(top=60, bottom=150, left=48, right=48, right_lower=dict(w=120, from_y=900)),
                          caption=dict(_VERT_CAPTION, band=[1080, 1270]),
                          cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1240], feed_crop=None),
                          cover_aspect="3:4"),
            full=dict(w=1080, h=1920, aspect="9:16",
                      safe=dict(top=240, bottom=260, left=60, right=60, right_lower=dict(w=160, from_y=960)),
                      caption=dict(_VERT_CAPTION, band=[1420, 1640]),
                      cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1240], feed_crop=None),
                      cover_aspect="3:4"),
            horizontal=dict(w=1920, h=1080, aspect="16:9", feed_crop="4:3",
                            safe=dict(top=60, bottom=60, left=280, right=280),
                            caption=dict(_HORZ_CAPTION, band=[880, 1030], max_chars_zh=18),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[300, 80, 1620, 1000], feed_crop="4:3"),
                            cover_aspect="16:9"),
        )),
    "douyin": dict(
        label="抖音 Douyin", default="vertical",
        title_max=55, title_count="chars", desc_max=1000,
        hashtags=dict(style="inline", max=10, note="#话题 / @ inside the caption text; counts toward the 1000 limit"),
        chapters=dict(supported=False, note="auto 章节 on some long videos only; not author-controlled"),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[15, 60], max=900, min=3),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=160, bottom=440, left=60, right=150, right_lower=dict(w=180, from_y=900)),
                          caption=dict(_VERT_CAPTION, band=[1240, 1460]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680],
                                     feed_crop="3:4"),
                          cover_aspect="9:16"),
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=60, bottom=90, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1920, h=1080, aspect="16:9", title_safe=[240, 60, 1680, 1020], feed_crop="4:3"),
                            cover_aspect="16:9"),
        )),
    "tiktok": dict(
        label="TikTok", default="vertical",
        title_max=55, title_count="chars", desc_max=4000,
        hashtags=dict(style="inline", max=30, note="in the caption; counts toward 4000 (2200 via API)"),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=20, maxrate="12M", bufsize="24M"),
        length=dict(sweet=[21, 60], max=600, min=3),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=130, bottom=484, left=60, right=140),
                          caption=dict(_VERT_CAPTION, band=[1200, 1420]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 1020, 1680],
                                     feed_crop="3:4"),
                          cover_aspect="9:16"),
        )),
    "youtube": dict(
        label="YouTube", default="horizontal",
        title_max=100, title_count="chars", desc_max=5000,
        hashtags=dict(style="description", max=15, note="first 3 show above the title; >60 = all ignored"),
        chapters=dict(supported=True, min_count=3, min_len=10, first_zero=True),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[420, 1200], max=43200, min=1),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=54, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[880, 1020]),
                            cover=dict(w=1280, h=720, aspect="16:9", title_safe=[40, 40, 1100, 620], feed_crop=None,
                                       max_bytes=2_000_000),
                            cover_aspect="16:9"),
        )),
    "youtube-shorts": dict(
        label="YouTube Shorts", default="vertical",
        title_max=100, title_count="chars", desc_max=5000,
        hashtags=dict(style="description", max=3),
        chapters=dict(supported=False),
        loudness=dict(_LOUD), fps=dict(default=30, max=60),
        encode=dict(crf=18, maxrate="16M", bufsize="32M"),
        length=dict(sweet=[20, 60], max=180, min=3),
        orientations=dict(
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=180, bottom=390, left=60, right=120),
                          caption=dict(_VERT_CAPTION, band=[1260, 1480]),
                          cover=dict(w=1080, h=1920, aspect="9:16", title_safe=[60, 240, 960, 1530], feed_crop=None),
                          cover_aspect="9:16"),
        )),
    "bilibili": dict(
        label="B站 Bilibili", default="horizontal",
        title_max=80, title_count="chars", desc_max=2000,
        hashtags=dict(style="tags_line", max=10, tag_max=20, note="separate tag field, <=10 tags, <=20 chars each"),
        chapters=dict(supported=True, min_count=2, min_len=5, first_zero=True,
                      note="分段章节 set in the uploader; timestamps in the description also link"),
        loudness=dict(_LOUD), fps=dict(default=30, max=120),
        encode=dict(crf=18, maxrate="24M", bufsize="24M"),
        length=dict(sweet=[180, 900], max=36000, min=10),
        orientations=dict(
            horizontal=dict(w=1920, h=1080, aspect="16:9",
                            safe=dict(top=54, bottom=80, left=96, right=96),
                            caption=dict(_HORZ_CAPTION, band=[870, 1010]),
                            cover=dict(w=1146, h=717, aspect="16:10", title_safe=[100, 40, 1046, 640], feed_crop=None),
                            cover_aspect="16:10"),
            vertical=dict(w=1080, h=1920, aspect="9:16",
                          safe=dict(top=200, bottom=420, left=60, right=150),
                          caption=dict(_VERT_CAPTION, band=[1260, 1480]),
                          cover=dict(w=1080, h=1440, aspect="3:4", title_safe=[60, 120, 1020, 1240], feed_crop=None),
                          cover_aspect="3:4"),
        )),
}


@dataclass
class Profile:
    name: str
    orientation: str
    label: str
    w: int
    h: int
    aspect: str
    safe: dict
    caption: dict
    cover: dict
    cover_aspect: str
    title_max: float
    title_count: str
    desc_max: int
    hashtags: dict
    chapters: dict
    loudness: dict
    fps: dict
    encode: dict
    length: dict
    feed_crop: str = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self):
        return f"{self.name}:{self.orientation}"

    @property
    def size(self):
        return self.w, self.h

    def to_dict(self):
        return asdict(self)


_FIELDS = set(Profile.__dataclass_fields__) - {"name", "orientation", "extra"}


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def canonical(name):
    n = str(name).strip().lower()
    return ALIASES.get(n, n)


def _persona_platform(name):
    try:
        from .config import persona
        p = (persona().get("platforms") or {}).get(name) or {}
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def _legacy_safe_zone(sz, w, h):
    """persona safe_zone {top, bottom, right_lower_keepout} (y coordinates, 1080x1920) -> safe dict."""
    out = {}
    if "top" in sz:
        out["top"] = int(sz["top"])
    if "bottom" in sz:
        b = int(sz["bottom"])
        out["bottom"] = h - b if b > h / 2 else b          # coordinate (1660) or margin (260)
    for k in ("left", "right"):
        if k in sz:
            out[k] = int(sz[k])
    if sz.get("right_lower_keepout"):
        out["right_lower"] = dict(w=int(sz["right_lower_keepout"]), from_y=h // 2)
    return out


def profile(name, orientation=None, overrides=None, use_persona=True) -> Profile:
    """Profile for ``name`` ("xiaohongshu", "douyin", "tiktok", "youtube", "youtube-shorts", "bilibili"
    or an alias) and ``orientation`` ("vertical", "full", "horizontal"; default per platform).
    Merge order: built-in common <- built-in orientation <- persona platforms.<name> <- persona
    platforms.<name>.orientations.<o> <- ``overrides``."""
    if ":" in str(name) and orientation is None:
        name, orientation = str(name).split(":", 1)
    name = canonical(name)
    if name not in PLATFORMS:
        raise KeyError(f"unknown platform {name!r}; one of {sorted(PLATFORMS)}")
    base = PLATFORMS[name]
    o = ORIENT_ALIASES.get(str(orientation).lower(), str(orientation).lower()) if orientation else base["default"]
    if o not in base["orientations"]:
        if o == "full" and "vertical" in base["orientations"] and base["orientations"]["vertical"]["h"] == 1920:
            o = "vertical"
        elif o == "vertical" and "full" in base["orientations"]:
            o = "full"
        else:
            raise KeyError(f"{name} has no {o!r} orientation; one of {sorted(base['orientations'])}")
    d = {k: v for k, v in base.items() if k not in ("orientations", "default")}
    d = _merge(d, base["orientations"][o])
    if use_persona:
        pp = dict(_persona_platform(name))
        per_o = (pp.pop("orientations", None) or {}).get(o) or {}
        legacy = pp.pop("safe_zone", None)
        if legacy and d["h"] == 1920:
            d["safe"] = _merge(d["safe"], _legacy_safe_zone(legacy, d["w"], d["h"]))
        if "cover_aspect" in pp and pp["cover_aspect"] != d.get("cover_aspect"):
            pp.pop("cover_aspect")      # a single legacy aspect can't describe every orientation; keep built-in
        d = _merge(d, pp)
        d = _merge(d, per_o)
    d = _merge(d, overrides or {})
    extra = {k: d.pop(k) for k in list(d) if k not in _FIELDS}
    return Profile(name=name, orientation=o, extra=extra, **d)


def list_profiles():
    """["xiaohongshu:vertical", ...] - every platform:orientation pair."""
    return [f"{n}:{o}" for n, p in PLATFORMS.items() for o in p["orientations"]]


def parse_targets(spec):
    """"xiaohongshu:vertical,douyin,youtube" -> [Profile, ...]."""
    out = []
    for item in (spec if isinstance(spec, (list, tuple)) else str(spec).split(",")):
        item = item.strip()
        if item:
            n, _, o = item.partition(":")
            out.append(profile(n, o or None))
    return out


# ----------------------------------------------------------------------------------- geometry
def safe_box(p: Profile):
    """(x0, y0, x1, y1): the area free of the platform's UI margins (top bar, bottom description,
    side buttons). The lower-right button keep-out is returned separately by ``keepouts``."""
    s = p.safe
    return (int(s.get("left", 0)), int(s.get("top", 0)), int(p.w - s.get("right", 0)), int(p.h - s.get("bottom", 0)))


def keepouts(p: Profile):
    """Extra keep-out rects [(x0, y0, x1, y1)] (e.g. the like/comment column on the lower right)."""
    rl = p.safe.get("right_lower")
    return [(p.w - int(rl["w"]), int(rl.get("from_y", p.h // 2)), p.w, p.h)] if rl else []


def caption_box(p: Profile):
    """(x0, y0, x1, y1) for burned captions: the caption band, inside the safe box, symmetric around
    the canvas centre and clear of any lower-right button column."""
    x0, y0, x1, y1 = safe_box(p)
    b0, b1 = p.caption["band"]
    b0, b1 = max(b0, y0), min(b1, y1)
    for kx0, ky0, kx1, ky1 in keepouts(p):
        if ky0 < b1 and ky1 > b0:
            x1 = min(x1, kx0)
    m = max(x0, p.w - x1)                    # keep it centred: same margin both sides
    return (int(m), int(b0), int(p.w - m), int(b1))


def cover_size(p: Profile):
    return int(p.cover["w"]), int(p.cover["h"])


def cover_title_safe(p: Profile):
    """Title-safe rect on the cover; for covers shown as a centre crop in the feed (feed_crop) it is
    intersected with that crop."""
    x0, y0, x1, y1 = p.cover.get("title_safe") or (0, 0, *cover_size(p))
    fc = p.cover.get("feed_crop")
    if fc:
        W, H = cover_size(p)
        aw, ah = (float(v) for v in fc.split(":"))
        if W / H > aw / ah:
            cw = H * aw / ah; x0, x1 = max(x0, (W - cw) / 2), min(x1, (W + cw) / 2)
        else:
            ch = W * ah / aw; y0, y1 = max(y0, (H - ch) / 2), min(y1, (H + ch) / 2)
    return (int(x0), int(y0), int(x1), int(y1))


def feed_crop_box(p: Profile):
    """(x0, y0, x1, y1) of the part of the VIDEO frame the feed shows (e.g. 小红书 horizontal -> centre
    4:3), or the full canvas."""
    if not p.feed_crop:
        return (0, 0, p.w, p.h)
    aw, ah = (float(v) for v in p.feed_crop.split(":"))
    if p.w / p.h > aw / ah:
        cw = p.h * aw / ah
        return (int((p.w - cw) / 2), 0, int((p.w + cw) / 2), p.h)
    ch = p.w * ah / aw
    return (0, int((p.h - ch) / 2), p.w, int((p.h + ch) / 2))


# ----------------------------------------------------------------------------------- text
def _has_cjk(text):
    return any(ord(c) >= 0x2E80 for c in text)


def title_len(p: Profile, title: str) -> float:
    if p.title_count == "xhs":
        from .config import xhs_len
        return xhs_len(title)
    return float(len(title))


def check_text(p: Profile, title=None, body=None, tags=None):
    """Warnings for title / description / tag limits of this profile."""
    w = []
    if title:
        n = title_len(p, title)
        if n > p.title_max:
            w.append(f"title {n:g}/{p.title_max:g} ({p.name})")
    if body and p.desc_max and len(body) > p.desc_max:
        w.append(f"description {len(body)}/{p.desc_max} chars ({p.name})")
    if tags:
        mx = p.hashtags.get("max")
        if mx and len(tags) > mx:
            w.append(f"{len(tags)} tags > {mx} ({p.name})")
        tm = p.hashtags.get("tag_max")
        if tm:
            w += [f"tag '{t}' > {tm} chars" for t in tags if len(t) > tm]
    return w


def check_length(p: Profile, seconds: float):
    """Warnings when a duration is over the hard max or outside the sweet spot."""
    L, w = p.length, []
    if L.get("max") and seconds > L["max"]:
        w.append(f"duration {seconds:.1f}s over the {p.name} max {L['max']}s")
    elif L.get("min") and seconds < L["min"]:
        w.append(f"duration {seconds:.1f}s under the {p.name} minimum {L['min']}s")
    lo, hi = L.get("sweet") or (0, 1e9)
    if not w and not lo <= seconds <= hi:
        w.append(f"duration {seconds:.1f}s outside the {p.name} sweet spot {lo}-{hi}s (guidance)")
    return w


def fit_text_size(p: Profile, text: str, role="cjk-bold", fit_height=True):
    """Largest caption font size in the profile's range at which ``text`` wraps into at most
    ``max_lines`` lines that fit ``caption_box`` width, the per-line char limit (zh or en by
    content) and (fit_height, default) the caption band HEIGHT as ``export.caption_overlay`` stacks the
    rows. Lines are wrapped by whichever of pixel width / char limit binds first, so a long CJK line
    is split instead of failing the char check.
    Returns dict(size, lines, fits, height). Falls back to the min size (fits=False) when it can't fit."""
    from . import draw
    from .subs import text_width as cjk_w, balanced_wrap, caption_block_height
    x0, y0, x1, y1 = caption_box(p)
    cap = p.caption
    lo, hi = (int(v) for v in cap["size"])
    max_lines = int(cap.get("max_lines", 2))
    cjk = _has_cjk(text)
    max_chars = cap["max_chars_zh"] if cjk else cap["max_chars_en"]
    stroke_frac = float(cap.get("stroke", 0.08))
    chars = (lambda s: cjk_w(draw.plain(s))) if cjk else (lambda s: len(draw.plain(s)))  # noqa: E731

    def attempt(size, cap_lines=None):
        f = draw.load_font(role, size)
        avail = (x1 - x0) - 2 * int(size * stroke_frac) - 8
        meas = lambda s: max(draw.text_width(s, f) / max(1.0, avail), chars(s) / max(1, max_chars))  # noqa: E731
        lines = balanced_wrap(text.strip(), 1.0, measure=meas, max_lines=cap_lines)
        if cap_lines and len(lines) > cap_lines:
            lines = lines[:cap_lines]
        width_ok = all(draw.text_width(ln, f) <= avail for ln in lines)
        chars_ok = all(chars(ln) <= max_chars for ln in lines)
        h = caption_block_height(len(lines), f, max(2, int(size * stroke_frac)))
        ok = len(lines) <= max_lines and width_ok and chars_ok and (not fit_height or h <= y1 - y0)
        return dict(size=size, lines=lines, fits=bool(ok), height=h)

    for size in range(hi, lo - 1, -2):
        r = attempt(size)
        if r["fits"]:
            return r
    r = attempt(lo, max_lines)
    r["fits"] = False
    return r


def _wrap(text, f, avail, max_lines=None):
    """Pixel-measured balanced wrap (breaks after punctuation, latin words whole, no orphans); markup kept."""
    from . import draw
    from .subs import balanced_wrap
    lines = balanced_wrap(text.strip(), avail, measure=lambda s: draw.text_width(s, f), max_lines=max_lines)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    return lines


def summary(p: Profile) -> str:
    sb, cb = safe_box(p), caption_box(p)
    return (f"{p.key:28s} {p.w}x{p.h} safe={sb} caption={cb} cover={cover_size(p)} "
            f"title<={p.title_max:g} len {p.length.get('sweet')}/{p.length.get('max')}s "
            f"{p.loudness['lufs']} LUFS/{p.loudness['tp']} dBTP")


if __name__ == "__main__":
    for k in list_profiles():
        print(summary(profile(k)))
