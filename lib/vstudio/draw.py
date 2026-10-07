"""PIL drawing primitives shared by overlays, covers and subtitle strips.

    from vstudio.draw import load_font, wrap, wrap_draw, text_layer, rounded_rect, shadow, alpha_paste
    f = load_font("cjk-bold", 48)
    lines = wrap("用 Claude Code 做一个讲解视频", f, 600)      # latin runs kept whole, no 1-char orphan
    strip = text_layer("这是【重点】", f)                      # RGBA, stroke + soft shadow, 【】 in brand.highlight

Colours default to persona.brand; markup defaults to persona.subtitles.highlight_markup (【】).
"""
import os
import re
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import MissingAsset, font, persona

WHITE = (255, 255, 255, 255)
BRAND_DEFAULTS = dict(accent="#FF2442", highlight="#FFD60A", ink="#ECEEF2", ground="#0B1020",
                      dim="#969EB2", highlight_alt="#F4D35E", accent_soft="#FF5A72", teal="#2DD4BF")


# ---------------------------------------------------------------- colours
def rgb(c):
    """'#RRGGBB' | 'RRGGBB' | (r,g,b[,a]) -> (r,g,b)."""
    if isinstance(c, (list, tuple)):
        return tuple(int(v) for v in c[:3])
    c = str(c).lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def rgba(c, a=255):
    if isinstance(c, (list, tuple)) and len(c) == 4:
        return tuple(int(v) for v in c)
    return rgb(c) + (int(a),)


def brand(**override) -> dict:
    """persona.brand merged over defaults, as RGB tuples (keys: accent, highlight, ink, ground, dim, ...).

    accent / highlight follow the active design theme (vstudio.theme): its accent and its keyword colour over
    video. A persona brand.accent / highlight still wins when no theme is chosen (legacy ``classic``); once a
    theme is chosen anywhere (persona style.theme, client, recipe, output edit) the theme's pair wins."""
    from . import theme as _TH
    T = _TH.current()
    b = dict(BRAND_DEFAULTS)
    b.update(accent=T["accent"], highlight=T["over_emph"])
    pb = {k: v for k, v in ((persona().get("brand") or {}).items()) if isinstance(v, (str, list, tuple))}
    if T.get("source") not in ("legacy", "default"):
        pb.pop("accent", None)
        pb.pop("highlight", None)
    b.update(pb)
    b.update({k: v for k, v in override.items() if v is not None})
    out = {}
    for k, v in b.items():
        try:
            out[k] = rgb(v)
        except (ValueError, TypeError):
            pass                                       # e.g. panel_theme: "notes-red"
    return out


def markup() -> str:
    m = (persona().get("subtitles") or {}).get("highlight_markup") or "【】"
    return m if len(m) == 2 else "【】"


_STARS = re.compile(r"\*\*(.+?)\*\*")


def std_markup(text: str, mk: str = None) -> str:
    """``**term**`` -> the persona markup (``【term】``), so every drawing helper accepts both styles
    (as ``subs.parse_highlight`` does)."""
    a, b = mk or markup()
    if "**" not in text or a == "*":
        return text
    return _STARS.sub(lambda m: a + m.group(1) + b, text)


# ---------------------------------------------------------------- fonts / measuring
@lru_cache(maxsize=256)
def load_font(role: str = "cjk-bold", size: int = 40):
    """Truetype font for a vstudio role (cjk, cjk-bold, serif, serif-italic, mono, mono-bold) or a file path.
    Falls back to Pillow's default font (with a warning) if the role is not installed."""
    size = max(1, int(round(size)))
    try:
        path = role if os.path.exists(str(role)) else font(role)
        return ImageFont.truetype(path, size)
    except (MissingAsset, OSError):
        if role.endswith("-bold") or role.endswith("-italic") or role.startswith("cjk"):
            fb = "cjk-bold" if "bold" in role else "cjk"
            try:
                f = ImageFont.truetype(font(fb), size)
                if fb != role:   # e.g. cjk-serif not installed: say so instead of silently drawing Sans
                    print(f"vstudio.draw: font role '{role}' missing (run ./install.sh); using '{fb}'")
                return f
            except (MissingAsset, OSError):
                pass
        print(f"vstudio.draw: font role '{role}' missing (run ./install.sh); using Pillow default")
        return ImageFont.load_default(size=size)


_D0 = ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def plain(text: str) -> str:
    """Text with highlight markup removed (what is actually drawn)."""
    m = markup()
    return std_markup(text, m).replace(m[0], "").replace(m[1], "")


def text_width(text: str, f) -> float:
    return _D0.textlength(plain(text), font=f)


def text_size(text: str, f):
    """(width, line height) of a single line; height = ascent + descent so mixed lines align."""
    asc, desc = f.getmetrics()
    return int(round(text_width(text, f))), asc + desc


def is_cjk(ch: str) -> bool:
    return ord(ch) >= 0x2E80


def has_cjk(text: str) -> bool:
    return any(is_cjk(c) for c in text)


# ---------------------------------------------------------------- wrapping
_LATIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9%/+.\-'_&#@:]*")
NO_LINE_START = set("，。、？！：；）」』】》〉”’,.!?:;)]}%…～·")
NO_LINE_END = set("（「『【《〈“‘([{")


def tokens(text: str, keep_phrases: bool = None):
    """Wrap units. Latin/number runs stay whole ("3b1b", "v2.1"); in CJK text a run of latin words joined by
    single spaces ("Claude Code") is one unit. Closing punctuation sticks to the token before it, opening
    punctuation / markup to the token after it."""
    if keep_phrases is None:
        keep_phrases = has_cjk(text)
    raw, i = [], 0
    while i < len(text):
        m = _LATIN.match(text, i)
        if m:
            raw.append(m.group()); i = m.end()
        elif text[i].isspace():
            j = i
            while j < len(text) and text[j].isspace():
                j += 1
            raw.append(" "); i = j
        else:
            raw.append(text[i]); i += 1
    if keep_phrases:                                       # "Claude" " " "Code" -> "Claude Code"
        merged = []
        for t in raw:
            if (len(merged) >= 2 and _LATIN.fullmatch(t) and merged[-1] == " " and _LATIN.match(merged[-2])):
                merged.pop(); merged[-1] += " " + t
            else:
                merged.append(t)
        raw = merged
    out = []
    for t in raw:
        if out and t[0] in NO_LINE_START and out[-1] != " ":
            out[-1] += t
        elif out and out[-1][-1] in NO_LINE_END:
            out[-1] += t
        else:
            out.append(t)
    return out


def _greedy(toks, f, max_w):
    lines, cur = [], []
    for t in toks:
        w = text_width("".join(cur + [t]).strip(), f)
        if cur and w > max_w and "".join(cur).strip():
            lines.append(cur); cur = [] if t == " " else [t]
        else:
            cur.append(t)
    if "".join(cur).strip():
        lines.append(cur)
    return lines


def _split_wide(toks, f, max_w):
    """Phrases wider than the line are split back into words. A single latin word wider than the line stays
    whole (it overflows: callers shrink the font - never "mak / es"); any other over-wide run splits by char."""
    out = []
    for t in toks:
        core = t.rstrip("".join(NO_LINE_START))            # closing punctuation may hang past the edge
        if text_width(core or t, f) <= max_w:
            out.append(t)
        elif " " in t.strip():
            parts = t.split(" ")
            for k, p in enumerate(parts):
                out += ([" "] if k else []) + _split_wide([p], f, max_w)
        elif _LATIN.match(t):
            out.append(t)
        else:
            out += list(t)
    return out


def fits(lines, f, max_w) -> bool:
    """Every line within ``max_w`` px (a shrink loop around ``wrap`` checks this: a long word never splits)."""
    return all(text_width(ln, f) <= max_w for ln in lines)


def _is_orphan(line_toks) -> bool:
    s = plain("".join(line_toks)).strip()
    core = "".join(c for c in s if c not in NO_LINE_START and c not in NO_LINE_END)
    return len(core) == 1 and is_cjk(core)


def _balance_markup(lines):
    a, b = markup()
    out, open_ = [], False
    for ln in lines:
        if open_:
            ln = a + ln
        depth = 0
        for c in ln:
            depth += (c == a) - (c == b)
        open_ = depth > 0
        out.append(ln + b if open_ else ln)
    return out


def wrap(text: str, f, max_w: float, balance: bool = False, max_lines: int = None):
    """CJK-aware wrap -> list of lines (markup kept and balanced per line).

    balance=True keeps the greedy line count but evens line lengths (subtitles, titles).
    Never ends with a lone CJK character: one more token is pulled down from the line above.
    ``**term**`` markup is accepted and returned as the persona markup (``【term】``)."""
    text = std_markup(text)
    toks = _split_wide(tokens(text), f, max_w)
    lines = _greedy(toks, f, max_w)
    if balance and len(lines) > 1:
        total = text_width(text.strip(), f)
        target = total / len(lines)
        step = max(4, int(getattr(f, "size", 40) * 0.25))
        for extra in range(0, int(max_w - target) + step, step):
            cand = _greedy(toks, f, min(max_w, target + extra))
            if len(cand) == len(lines):
                lines = cand
                break
    if len(lines) >= 2 and _is_orphan(lines[-1]):
        prev = [t for t in lines[-2]]
        while prev and prev[-1] == " ":
            prev.pop()
        if len(prev) > 1:
            moved = prev.pop()
            cand = [moved] + lines[-1]
            if text_width("".join(cand).strip(), f) <= max_w:
                lines[-2], lines[-1] = prev, cand
    out = ["".join(ln).strip() for ln in lines]
    out = _balance_markup(out)
    if max_lines and len(out) > max_lines:
        out = out[:max_lines]
        out[-1] = out[-1].rstrip("，。、,. ") + "…"
    return out


def runs(text: str, keywords=None, mk: str = None):
    """'普通【重点】文本' (or '普通**重点**文本') -> [('普通', False), ('重点', True), ('文本', False)].
    keywords also highlight."""
    a, b = mk or markup()
    text = std_markup(text, (a, b))
    out, cur, hi = [], "", False
    for c in text:
        if c == a and not hi:
            if cur: out.append((cur, False))
            cur, hi = "", True
        elif c == b and hi:
            if cur: out.append((cur, True))
            cur, hi = "", False
        else:
            cur += c
    if cur:
        out.append((cur, hi))
    if keywords:
        kw = [k for k in keywords if k]
        if kw:
            rx = re.compile("(" + "|".join(re.escape(k) for k in sorted(kw, key=len, reverse=True)) + ")")
            split = []
            for t, h in out:
                if h:
                    split.append((t, h)); continue
                i = 0
                for m in rx.finditer(t):
                    if m.start() > i: split.append((t[i:m.start()], False))
                    split.append((m.group(), True)); i = m.end()
                if i < len(t): split.append((t[i:], False))
            out = split
    return out


def draw_runs(d, xy, line, f, fill=WHITE, hl_fill=None, keywords=None, **kw):
    """Draw one line with highlight runs; returns the x after the last run."""
    x, y = xy
    hl = hl_fill or rgba(brand()["highlight"])
    for t, h in runs(line, keywords):
        d.text((x, y), t, font=f, fill=hl if h else fill, **kw)
        x += d.textlength(t, font=f)
    return x


def wrap_draw(d, xy, text, f, max_w, fill=WHITE, hl_fill=None, line_gap=1.25, align="left",
              balance=False, max_lines=None, keywords=None, **kw):
    """Wrap + draw (highlight-aware). align: left | center (x is the centre) | right (x is the right edge).
    Returns the y below the last line."""
    x, y = xy
    lh = int(round(sum(f.getmetrics()) * line_gap))
    for ln in wrap(text, f, max_w, balance=balance, max_lines=max_lines):
        w = text_width(ln, f)
        lx = x - w / 2 if align == "center" else (x - w if align == "right" else x)
        draw_runs(d, (lx, y), ln, f, fill, hl_fill, keywords, **kw)
        y += lh
    return y


def fit_font(text, role, size, max_w, min_size=18, step=2):
    """Largest font of `role` <= size whose single-line width fits max_w."""
    f = load_font(role, size)
    while size > min_size and text_width(text, f) > max_w:
        size -= step; f = load_font(role, size)
    return f


# ---------------------------------------------------------------- shapes / compositing
def rounded_rect(size, radius, fill, outline=None, width=0):
    w, h = int(size[0]), int(size[1])
    im = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, h - 1], int(radius), fill=rgba(fill) if fill is not None else None,
                                         outline=rgba(outline) if outline is not None else None, width=int(width))
    return im


def shadow(im, blur=14, offset=(0, 8), alpha=90, color=(0, 0, 0)):
    """Drop shadow under an RGBA image -> (bigger RGBA image, pad). Paste at (x - pad, y - pad)."""
    if isinstance(offset, (int, float)):
        offset = (0, offset)
    pad = int(blur * 3 + max(abs(offset[0]), abs(offset[1])))
    big = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, tuple(color) + (0,))
    sh.putalpha(im.split()[3].point(lambda v: v * alpha // 255))
    big.paste(sh, (pad + int(offset[0]), pad + int(offset[1])), sh)
    big = big.filter(ImageFilter.GaussianBlur(blur))
    big.alpha_composite(im, (pad, pad))
    return big, pad


def to_rgba_array(im):
    return np.asarray(im.convert("RGBA")) if isinstance(im, Image.Image) else np.asarray(im)


def alpha_paste(dst, src, xy, opacity=1.0, center=False, scale=1.0, bgr=False):
    """Composite an RGBA overlay onto dst, clipped to its bounds.

    dst: PIL image (modified in place, RGBA or RGB) or numpy HxWx3/4 (uint8 or float, modified in place;
    bgr=True when it is an OpenCV frame). src: PIL RGBA or numpy RGBA. xy is the top-left (or centre)."""
    if opacity <= 0:
        return dst
    a = to_rgba_array(src)
    if scale != 1.0:
        a = np.asarray(Image.fromarray(a.astype(np.uint8)).resize(
            (max(1, int(a.shape[1] * scale)), max(1, int(a.shape[0] * scale))), Image.BILINEAR))
    h, w = a.shape[:2]
    x, y = xy
    if center:
        x, y = x - w / 2, y - h / 2
    x, y = int(round(x)), int(round(y))
    if isinstance(dst, Image.Image):
        if opacity < 1:
            a = a.copy(); a[..., 3] = (a[..., 3].astype(np.float32) * opacity).astype(np.uint8)
        layer = Image.fromarray(a.astype(np.uint8), "RGBA")
        if dst.mode == "RGBA":
            dst.paste(Image.alpha_composite(dst.crop((x, y, x + w, y + h)), layer), (x, y))
        else:
            dst.paste(layer, (x, y), layer)
        return dst
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return dst
    patch = a[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32)
    al = patch[..., 3:4] / 255.0 * opacity
    col = patch[..., :3][..., ::-1] if bgr else patch[..., :3]
    roi = dst[y0:y1, x0:x1, :3].astype(np.float32)
    out = col * al + roi * (1 - al)
    dst[y0:y1, x0:x1, :3] = out if dst.dtype != np.uint8 else np.clip(out + 0.5, 0, 255).astype(np.uint8)
    return dst


def text_layer(text, f, fill=WHITE, hl_fill=None, stroke=6, stroke_fill=(20, 20, 20, 255), shadow_alpha=150,
               pad=16, keywords=None, max_w=None, line_gap=1.15, align="center"):
    """Stroked text strip (RGBA PIL) with soft drop shadow. `text` may hold 【】 markup or be a list of
    (text, colour) runs. With max_w the text is wrapped (balanced) and lines centred."""
    if isinstance(text, (list, tuple)):
        lines_runs = [[(t, rgba(c)) for t, c in text]]
    else:
        hl = rgba(hl_fill) if hl_fill is not None else rgba(brand()["highlight"])
        lines = wrap(text, f, max_w, balance=True) if max_w else [text]
        lines_runs = [[(t, hl if h else rgba(fill)) for t, h in runs(ln, keywords)] for ln in lines]
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * line_gap)
    widths = [sum(_D0.textlength(t, font=f) for t, _ in lr) for lr in lines_runs]
    W = int(max(widths or [1])) + 2 * (pad + stroke)
    H = lh * (len(lines_runs) - 1) + asc + desc + 2 * (pad + stroke)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr, ds = ImageDraw.Draw(im), ImageDraw.Draw(sh)
    for k, (lr, lw) in enumerate(zip(lines_runs, widths)):
        x = pad + stroke + ((W - 2 * (pad + stroke) - lw) / 2 if align == "center" else 0)
        y = pad + stroke + k * lh
        for t, col in lr:
            if shadow_alpha:
                ds.text((x + 3, y + 4), t, font=f, fill=(0, 0, 0, shadow_alpha), stroke_width=stroke,
                        stroke_fill=(0, 0, 0, shadow_alpha))
            dr.text((x, y), t, font=f, fill=col, stroke_width=stroke, stroke_fill=rgba(stroke_fill))
            x += dr.textlength(t, font=f)
    if shadow_alpha:
        return Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)), im)
    return im


def limit_runs(rs, n):
    """Keep at most ``n`` emphasised runs (the first ones) in a list of (text, emphasised) runs; 0 = all."""
    if not n:
        return rs
    out, k = [], 0
    for t, h in rs:
        if h:
            k += 1
        out.append((t, h and k <= n))
    return out


def emph_layer(text, f, T=None, surface="paper", fill=None, emph_font=None, max_w=None, align="left",
               line_gap=1.32, sweep=1.0, pad=None, keywords=None, emphasis=None, accent=None, max_lines=None):
    """Theme-aware text block (RGBA PIL): 【keyword】 runs are emphasised the theme's way.

    surface paper: ink text, no stroke; emphasis ``marker`` (a soft highlighter band behind the lower part of the
    run), ``color`` (accent text) or ``underline`` (thin accent bar). surface video: theme over-video ink with a
    thin stroke + soft shadow, keywords in the theme's over-video colour. At most ``T.emph_per_line`` keywords per
    line are emphasised (STYLE_RULES S2). emph_font: a heavier font for emphasised runs (weight contrast).
    sweep: 0-1, how far the marker / underline has drawn in (marker-sweep effect)."""
    from . import theme as _TH
    T = T or _TH.current()
    mode = emphasis or T["emphasis"]
    video = surface == "video"
    size = getattr(f, "size", 40)
    ink = rgba(fill) if fill is not None else _TH.rgba(T, "over_ink" if video else "ink")
    acc = rgb(accent) if accent is not None else _TH.rgb(T, "accent")
    emph_col = (_TH.rgb(T, "over_emph") if video else acc) + (255,)
    stroke = max(1, int(round(size * float(T.get("over_stroke_w") or 0)))) if video else 0
    pad = int(size * 0.3) + stroke if pad is None else pad
    ef = emph_font or f
    if isinstance(text, (list, tuple)):
        lines = list(text)
    else:
        lines = wrap(text, f, max_w, balance=True, max_lines=max_lines) if max_w else std_markup(str(text)).split("\n")
    per = int(T.get("emph_per_line") or 0)
    L = [limit_runs(runs(ln, keywords), per) for ln in lines]
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * line_gap)
    widths = [sum(_D0.textlength(t, font=ef if h else f) for t, h in lr) for lr in L]
    W = int(max(widths or [1])) + 2 * pad
    H = lh * (len(L) - 1) + asc + desc + 2 * pad
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    marks = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dm, dt = ImageDraw.Draw(marks), ImageDraw.Draw(base)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)) if video and T.get("over_shadow") else None
    ds = ImageDraw.Draw(sh) if sh is not None else None
    mcol = _TH.rgb(T, "marker")
    malpha = float(T.get("marker_alpha") or 1.0)
    sw = min(1.0, max(0.0, float(sweep)))
    for k, (lr, lw) in enumerate(zip(L, widths)):
        x = pad + ((W - 2 * pad - lw) / 2 if align == "center" else ((W - 2 * pad - lw) if align == "right" else 0))
        y = pad + k * lh
        for t, h in lr:
            fo = ef if h else f
            w = _D0.textlength(t, font=fo)
            if h and not video and mode in ("marker", "underline") and sw > 0:
                if mode == "marker":
                    y0, y1 = y + asc * 0.50, y + asc + desc * 0.30
                    x0 = x - size * 0.06
                    x1 = x0 + (w + size * 0.12) * sw
                    dm.rounded_rectangle([x0, y0, x1, y1], int(size * 0.06), fill=mcol + (int(255 * malpha),))
                else:
                    y0 = y + asc + desc * 0.15
                    x1 = x + w * sw
                    dm.rectangle([x, y0, x1, y0 + max(2, size * 0.07)], fill=acc + (255,))
            col = emph_col if (h and (video or mode == "color")) else ink
            if ds is not None:
                a = int(T.get("over_shadow") or 0)
                ds.text((x + size * 0.03, y + size * 0.05), t, font=fo, fill=(0, 0, 0, a), stroke_width=stroke,
                        stroke_fill=(0, 0, 0, a))
            dt.text((x, y), t, font=fo, fill=col, stroke_width=stroke,
                    stroke_fill=_TH.rgba(T, "over_stroke", 0.85) if stroke else None)
            x += w
    out = marks
    if sh is not None:
        out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(max(2, size // 14))))
    return Image.alpha_composite(out, base)


def bilingual_layer(primary, secondary, f1, f2=None, fill=WHITE, fill2=(203, 213, 225, 255), max_w=None,
                    gap=0, stroke=5, stroke_fill=(0, 0, 0, 235), shadow_alpha=0, pad=13, line_gap=1.2, **kw):
    """Two stacked, centred subtitle rows (primary above, e.g. Chinese; secondary below, e.g. English)
    as one RGBA strip; each row is a balanced-wrapped ``text_layer`` (max_w) and the rows sit ``gap``
    px apart (their pads overlap). f2 defaults to f1 at ~76% size. Empty secondary -> primary only.
    From call-clips ``render_landscape.render_sub``."""
    if f2 is None:
        f2 = load_font("cjk", max(8, int(getattr(f1, "size", 40) * 0.76)))
    common = dict(max_w=max_w, stroke=stroke, stroke_fill=stroke_fill, shadow_alpha=shadow_alpha, pad=pad,
                  line_gap=line_gap, **kw)
    rows = [text_layer(primary, f1, fill=fill, **common)] if primary else []
    if secondary:
        rows.append(text_layer(secondary, f2, fill=fill2, **common))
    if not rows:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    step = lambda r: r.height - 2 * pad + gap
    w = max(r.width for r in rows)
    im = Image.new("RGBA", (w, sum(step(r) for r in rows) - gap + 2 * pad), (0, 0, 0, 0))
    y = 0
    for r in rows:
        im.alpha_composite(r, ((w - r.width) // 2, y))
        y += step(r)
    return im


def vgradient_mask(w, h, power=1.6, reverse=False):
    """L mask ramping 0->255 down the height (alpha fades)."""
    col = (np.linspace(0, 1, max(1, h)) ** power * 255).astype(np.uint8)
    if reverse:
        col = col[::-1]
    return Image.fromarray(np.repeat(col[:, None], max(1, w), 1), "L")


def hgradient_mask(w, h, power=1.6, reverse=False):
    row = (np.linspace(0, 1, max(1, w)) ** power * 255).astype(np.uint8)
    if reverse:
        row = row[::-1]
    return Image.fromarray(np.repeat(row[None, :], max(1, h), 0), "L")


def to_pil(img, bgr=None):
    """PIL / numpy (RGB, or BGR when bgr=True or it came from cv2) / path -> PIL RGB."""
    if isinstance(img, Image.Image):
        return img
    if isinstance(img, (str, os.PathLike)):
        return Image.open(img).convert("RGB")
    a = np.asarray(img)
    if a.ndim == 2:
        return Image.fromarray(a.astype(np.uint8), "L").convert("RGB")
    if bgr:
        a = a[..., [2, 1, 0] + ([3] if a.shape[2] == 4 else [])]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- redaction
def _redact_frame(frame, rects, mode="blur", color=None, factor=16):
    """In place on a numpy frame (H, W, C): 'blur' (1/factor downscale, upscale, blur: no glyph
    survives), 'pixelate' (blocks of ``factor`` px), 'cover' (fill with ``color`` or the region's
    median colour)."""
    from PIL import Image as _I
    H, W = frame.shape[:2]
    C = frame.shape[2] if frame.ndim == 3 else 1
    for r in rects:
        x, y, w, h = (int(round(v)) for v in r[:4])
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        reg = frame[y0:y1, x0:x1]
        if mode == "cover":
            if color is not None:
                c = np.asarray(rgb(color) if isinstance(color, str) else color, float)[:C]
            else:
                c = np.median(reg.reshape(-1, C), axis=0)
            reg[:] = c.astype(frame.dtype)
            continue
        sw, sh = max(1, (x1 - x0) // factor), max(1, (y1 - y0) // factor)
        try:
            import cv2
            small = cv2.resize(reg, (sw, sh), interpolation=cv2.INTER_AREA)
            if mode == "pixelate":
                reg[:] = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST).reshape(reg.shape)
            else:
                reg[:] = cv2.GaussianBlur(cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR),
                                          (0, 0), 3).reshape(reg.shape)
        except ImportError:
            im = _I.fromarray(np.ascontiguousarray(reg).squeeze())
            small = im.resize((sw, sh), _I.BOX)
            if mode == "pixelate":
                big = small.resize((x1 - x0, y1 - y0), _I.NEAREST)
            else:
                big = small.resize((x1 - x0, y1 - y0), _I.BILINEAR).filter(ImageFilter.GaussianBlur(3))
            reg[:] = np.asarray(big).reshape(reg.shape)
    return frame


def redact_rects(frame_or_video, rects, mode="blur", out=None, color=None, factor=16, start=None, end=None,
                 encode_args=None):
    """Hide rectangles (name labels, bookmark bars, e-mails) in a frame or a whole video.

    frame_or_video: numpy frame (H, W, 3|4, any channel order; changed IN PLACE and returned) or a
    video path (then ``out`` is required; ffmpeg crop/scale/boxblur/overlay or drawbox graph, audio
    copied, ``media.delivery_args`` video). rects: [(x, y, w, h), ...] in px.
    mode: "blur" (default; 1/16 downscale + blur), "pixelate" (blocks), "cover" (``color`` or, for a
    frame, each region's median colour; for a video the median of a middle frame).
    start/end: video only, seconds during which the rects are hidden (default: the whole video).
    (call-clips ``layout.mask_names``.) Returns the frame or ``out``."""
    if mode not in ("blur", "pixelate", "cover"):
        raise ValueError("mode must be 'blur', 'pixelate' or 'cover'")
    if not isinstance(frame_or_video, (str, os.PathLike)):
        return _redact_frame(frame_or_video, rects, mode, color, factor)
    from . import media
    if out is None:
        raise ValueError("redact_rects(video, ...) needs out=")
    src = os.fspath(frame_or_video)
    rects = [[int(round(v)) for v in r[:4]] for r in rects]
    if not rects:
        media.run(["ffmpeg", "-y", "-i", src, "-c", "copy", os.fspath(out)])
        return out
    en = ""
    if start is not None or end is not None:
        en = f":enable='between(t,{float(start or 0):.3f},{float(end if end is not None else 1e9):.3f})'"
    info = media.probe(src)
    W, H = info.get("display_w") or info.get("w"), info.get("display_h") or info.get("h")
    rects = [[max(0, x), max(0, y), min(w, W - max(0, x)), min(h, H - max(0, y))] for x, y, w, h in rects]
    rects = [r for r in rects if r[2] > 1 and r[3] > 1]
    if mode == "cover":
        cols = []
        if color is None:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                png = os.path.join(td, "f.png")
                media.grab_frame(src, (info.get("duration") or 0) / 2, png)
                fr = np.asarray(Image.open(png).convert("RGB"))
            for x, y, w, h in rects:
                c = np.median(fr[y:y + h, x:x + w].reshape(-1, 3), axis=0).astype(int)
                cols.append("0x%02X%02X%02X" % tuple(c))
        else:
            c = rgb(color) if isinstance(color, str) else tuple(color)[:3]
            cols = ["0x%02X%02X%02X" % tuple(c)] * len(rects)
        graph = "[0:v]" + ",".join(f"drawbox=x={x}:y={y}:w={w}:h={h}:color={c}:t=fill{en}"
                                   for (x, y, w, h), c in zip(rects, cols)) + "[v]"
    else:
        n = len(rects)
        parts = [f"[0:v]split={n + 1}[b0]" + "".join(f"[s{i}]" for i in range(n))]
        for i, (x, y, w, h) in enumerate(rects):
            sw, sh = max(2, w // factor), max(2, h // factor)
            post = f"scale={w}:{h}:flags=neighbor" if mode == "pixelate" else f"scale={w}:{h},boxblur=3:1"
            parts.append(f"[s{i}]crop={w}:{h}:{x}:{y},scale={sw}:{sh}:flags=area,{post}[r{i}]")
        for i, (x, y, w, h) in enumerate(rects):
            parts.append(f"[b{i}][r{i}]overlay={x}:{y}{en}[b{i + 1}]")
        graph = ";".join(parts).rsplit(f"[b{n}]", 1)[0] + "[v]"
    args = list(encode_args) if encode_args is not None else media.delivery_args(audio=None)
    media.run(["ffmpeg", "-y", "-i", src, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?", *args,
               "-c:a", "copy", os.fspath(out)])
    return out
