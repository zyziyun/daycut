"""Themed overlay furniture (RGBA PIL images) + HTML/CSS snippets for HyperFrames projects.

    from vstudio import overlays as O
    O.notes_panel("三个要点", ["第一点", "第二点【重点】"])          # theme = persona.brand.panel_theme
    O.callout("这里是关键"), O.chip("标签"), O.badge("精彩预告"), O.stamp("亲测", 8)
    O.node_card("第二部分", eyebrow="NEXT"), O.chapter_card(2, 5, "主题：小标题")
    O.progress_bar(chapters, t, total, style="refined", width=1080)   # per-frame strip
    O.progress_static(chapters, total, width=1920)                     # PNG + ffmpeg drawbox for a static pass
    O.hf_progress(chapters, start, total, geo) / O.hf_cue_css(...)     # HyperFrames / GSAP snippets

Themes: notes-red (dark card, accent header, highlight 记笔记 tag), notes-yellow (paper card, highlight header),
teal (dark card, teal rail + outline, longform style), navy (brand ground card, gold title).
`scale` multiplies every size (1.0 = designed for a 1920-wide landscape frame; use ~1.5 for 1080x1920).
"""
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from .config import persona
from .draw import (brand, draw_runs, load_font, rgb, rgba, rounded_rect, shadow, text_layer, text_width, wrap)

THEMES = ("notes-red", "notes-yellow", "teal", "navy")


def notes_tag_default():
    return ((persona().get("overlays") or {}).get("notes_tag")) or "记笔记 ↓"


def get_theme(name=None) -> dict:
    """Resolved colours for a theme name (default persona.brand.panel_theme)."""
    name = name or (persona().get("brand") or {}).get("panel_theme") or "notes-red"
    if isinstance(name, dict):
        return name
    B = brand()
    dark = (16, 18, 24)
    if name == "notes-yellow":
        return dict(name=name, layout="header", card=(255, 250, 232, 246), header=B["highlight"] + (255,),
                    header_text=(28, 28, 32, 255), tag_bg=B["accent"] + (255,), tag_text=(255, 255, 255, 255),
                    text=(34, 34, 40, 255), hl=B["accent"] + (255,), dot=B["accent"] + (255,), accent=B["accent"],
                    outline=None, bubble=(255, 255, 255, 242), bubble_text=(34, 34, 40, 255), chip_fill=B["highlight"],
                    chip_text=(28, 28, 32))
    if name == "teal":
        T = B.get("teal", rgb("#2DD4BF"))
        lf = persona().get("longform") or {}
        if lf.get("accent"):
            T = rgb(lf["accent"])
        return dict(name=name, layout="rail", card=(13, 13, 16, 235), header=None, header_text=(236, 238, 242, 255),
                    tag_bg=None, tag_text=T + (255,), text=(220, 220, 224, 255), hl=T + (255,), dot=T + (255,),
                    accent=T, outline=T + (255,), bubble=(13, 13, 16, 235), bubble_text=(240, 240, 244, 255),
                    chip_fill=T, chip_text=(10, 10, 12))
    if name == "navy":
        G = B.get("highlight_alt", rgb("#F4D35E"))
        return dict(name=name, layout="header", card=B["ground"] + (242,), header=tuple(min(255, c + 22) for c in B["ground"]) + (255,),
                    header_text=G + (255,), tag_bg=G + (255,), tag_text=(20, 20, 24, 255), text=B["ink"] + (255,),
                    hl=G + (255,), dot=B["accent"] + (255,), accent=B["accent"], outline=(255, 255, 255, 40),
                    bubble=B["ground"] + (236,), bubble_text=B["ink"] + (255,), chip_fill=G, chip_text=(20, 20, 24))
    # notes-red (default)
    return dict(name="notes-red", layout="header", card=dark + (240,), header=B["accent"] + (255,),
                header_text=(255, 255, 255, 255), tag_bg=B["highlight"] + (255,), tag_text=(20, 20, 20, 255),
                text=(245, 246, 250, 255), hl=B["highlight"] + (255,), dot=B["accent"] + (255,), accent=B["accent"],
                outline=None, bubble=(18, 20, 26, 235), bubble_text=(255, 255, 255, 255), chip_fill=B["accent"],
                chip_text=(255, 255, 255))


def _s(v, scale):
    return max(1, int(round(v * scale)))


# ---------------------------------------------------------------- notes panel
def notes_panel(title, bullets, theme=None, width=620, scale=1.0, tag=None, keywords=None):
    """记笔记 panel: title + wrapped bullets (【】 / keywords highlighted). Returns RGBA (no shadow;
    use draw.shadow for one). A bullet starting with spaces is drawn as a continuation (no dot)."""
    T = get_theme(theme)
    tag = notes_tag_default() if tag is None else tag
    W = _s(width, scale)
    ft, fb, ftag = load_font("cjk-bold", _s(34, scale)), load_font("cjk", _s(30, scale)), load_font("cjk-bold", _s(24, scale))
    PX, PY, GAP, DOT = _s(24, scale), _s(20, scale), _s(14, scale), _s(10, scale)
    asc, desc = fb.getmetrics(); lh = int((asc + desc) * 1.08)
    tx = PX + DOT + _s(14, scale); maxw = W - tx - PX
    wrapped = [(b.startswith(" "), wrap(b.strip(), fb, maxw)) for b in bullets]
    nlines = sum(len(w) for _, w in wrapped)
    body_h = PY * 2 + nlines * lh + max(0, len(bullets) - 1) * GAP
    tagw = int(text_width(tag, ftag)) + _s(24, scale) if tag else 0

    if T["layout"] == "header":
        HEAD = _s(70, scale)
        H = HEAD + body_h
        r = _s(18, scale)
        im = rounded_rect((W, H), r, T["card"], outline=T.get("outline"), width=_s(2, scale) if T.get("outline") else 0)
        d = ImageDraw.Draw(im)
        d.rounded_rectangle([0, 0, W - 1, HEAD + r], r, fill=T["header"])
        d.rectangle([0, HEAD, W - 1, HEAD + r], fill=T["card"])
        tag_x = W - tagw - PX
        ftt = load_font("cjk-bold", _s(34, scale)); size = _s(34, scale)
        while size > 16 and PX + text_width(title, ftt) > (tag_x - _s(12, scale) if tag else W - PX):
            size -= 2; ftt = load_font("cjk-bold", size)
        a2, d2 = ftt.getmetrics()
        d.text((PX, (HEAD - a2 - d2) // 2), title, font=ftt, fill=T["header_text"])
        if tag:
            th = _s(40, scale); ty = (HEAD - th) // 2
            d.rounded_rectangle([tag_x, ty, tag_x + tagw, ty + th], _s(12, scale), fill=T["tag_bg"])
            d.text((tag_x + tagw / 2, ty + th / 2), tag, font=ftag, fill=T["tag_text"], anchor="mm")
        y = HEAD + PY
    else:  # rail: accent outline, left bar, eyebrow tag, title
        ftag2 = load_font("cjk", _s(24, scale))
        top = _s(22, scale); tag_h = (sum(ftag2.getmetrics()) + _s(8, scale)) if tag else 0
        tsz = _s(34, scale)
        title_lines = wrap(title, ft, W - PX * 2 - _s(6, scale))
        tlh = int(sum(ft.getmetrics()) * 1.1)
        HEAD = top + tag_h + tlh * len(title_lines) + _s(6, scale)
        H = HEAD + body_h
        im = rounded_rect((W, H), _s(18, scale), T["card"], outline=T["outline"], width=_s(2, scale))
        d = ImageDraw.Draw(im)
        d.rectangle([0, _s(18, scale), _s(6, scale), H - _s(18, scale)], fill=T["accent"] + (255,))
        x0 = PX + _s(4, scale)
        if tag:
            d.text((x0, top), tag, font=ftag2, fill=T["tag_text"])
        for k, ln in enumerate(title_lines):
            d.text((x0, top + tag_h + k * tlh), ln, font=ft, fill=T["header_text"])
        y = HEAD + PY // 2
        tx += _s(4, scale)
        del tsz
    for cont, lines in wrapped:
        if not cont:
            cy = y + (asc + desc) // 2
            d.ellipse([PX + (_s(4, scale) if T["layout"] == "rail" else 0), cy - DOT // 2,
                       PX + DOT + (_s(4, scale) if T["layout"] == "rail" else 0), cy + DOT // 2], fill=T["dot"])
        for ln in lines:
            draw_runs(d, (tx, y), ln, fb, T["text"], T["hl"], keywords)
            y += lh
        y += GAP
    return im


# ---------------------------------------------------------------- small furniture
def callout(text, theme=None, max_w=560, scale=1.0, keywords=None):
    """Speech-bubble note with an accent rail (dark on dark themes, white on notes-yellow)."""
    T = get_theme(theme)
    f = load_font("cjk-bold", _s(34, scale))
    PX, PY, BAR, GAP = _s(26, scale), _s(18, scale), _s(8, scale), _s(14, scale)
    lines = wrap(text, f, _s(max_w, scale))
    asc, desc = f.getmetrics(); lh = asc + desc; lg = _s(8, scale)
    tw = max(int(text_width(ln, f)) for ln in lines)
    W = PX + BAR + GAP + tw + PX
    H = len(lines) * lh + (len(lines) - 1) * lg + PY * 2
    im = rounded_rect((W, H), _s(16, scale), T["bubble"])
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([PX // 2, _s(12, scale), PX // 2 + BAR, H - _s(12, scale)], BAR // 2, fill=T["accent"] + (255,))
    y = PY
    for ln in lines:
        draw_runs(d, (PX // 2 + BAR + GAP + PX // 2, y), ln, f, T["bubble_text"], T["hl"], keywords)
        y += lh + lg
    return im


def chip(text, style="outline", theme=None, scale=1.0, color=None, size=30, radius=None, min_width=None, padx=18):
    """Pill label. style: outline (thin border, on dark plates) | filled (theme chip colour) |
    star (highlight fill, dark text) | tag (flush name tag, small radius, black + accent border) | ghost (translucent).
    radius / min_width / padx (design px, scaled): override the corner radius (default: full pill, tag 10),
    the minimum width (tag default 230) and the horizontal padding."""
    T = get_theme(theme); B = brand()
    f = load_font("cjk-bold" if style in ("filled", "star", "tag") else "cjk", _s(size, scale))
    asc, desc = f.getmetrics()
    padx, h = _s(padx, scale), asc + desc + _s(16, scale)
    w = int(text_width(text, f)) + 2 * padx
    if min_width is None and style == "tag":
        min_width = 230
    if min_width:
        w = max(w, _s(min_width, scale))
    r = int(round(radius * scale)) if radius is not None else (_s(10, scale) if style == "tag" else h // 2)
    col = rgb(color) if color is not None else None
    if style == "filled":
        im = rounded_rect((w, h), r, (col or T["chip_fill"]) + (255,)); tc = T["chip_text"] + (255,)
    elif style == "star":
        im = rounded_rect((w, h), r, (col or B["highlight_alt"]) + (255,)); tc = (17, 17, 17, 255)
    elif style == "tag":
        im = rounded_rect((w, h), r, (0, 0, 0, 255), outline=(col or T["accent"]) + (220,), width=_s(2, scale))
        tc = (255, 255, 255, 255)
    elif style == "ghost":
        im = rounded_rect((w, h), r, (16, 20, 34, 210), outline=(255, 255, 255, 56), width=_s(2, scale))
        tc = (col or B["ink"]) + (255,)
    else:
        c = (col or B["ink"]) + (255,)
        im = rounded_rect((w, h), r, None, outline=c, width=_s(2, scale)); tc = c
    ImageDraw.Draw(im).text((w / 2, h / 2), text, font=f, fill=tc, anchor="mm")
    return im


def badge(text, theme=None, scale=1.0, size=32, color=None):
    """Filled accent pill (hook badge: 精彩预告 / 高光预告)."""
    T = get_theme(theme)
    f = load_font("cjk-bold", _s(size, scale))
    asc, desc = f.getmetrics()
    w, h = int(text_width(text, f)) + _s(56, scale), asc + desc + _s(26, scale)
    im = rounded_rect((w, h), h // 2, (rgb(color) if color else T["accent"]) + (242,))
    ImageDraw.Draw(im).text((w / 2, h / 2), text, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return im


def stamp(text, angle=8, theme=None, scale=1.0, size=56):
    """Rubber stamp: white plate, thick accent border + accent text, rotated."""
    T = get_theme(theme)
    f = load_font("cjk-bold", _s(size, scale))
    asc, desc = f.getmetrics()
    w, h = int(text_width(text, f)) + _s(56, scale), asc + desc + _s(28, scale)
    im = rounded_rect((w, h), _s(12, scale), (255, 255, 255, 215), outline=T["accent"] + (255,), width=_s(7, scale))
    ImageDraw.Draw(im).text((w / 2, h / 2), text, font=f, fill=T["accent"] + (255,), anchor="mm")
    return im.rotate(angle, expand=True, resample=Image.BICUBIC) if angle else im


def tag(text, angle=0, theme=None, scale=1.0, size=54, fill=None, text_fill=(255, 255, 255)):
    """Solid rounded tag (cover 亲测 tag, 记笔记 corner tag), optionally rotated."""
    T = get_theme(theme)
    f = load_font("cjk-bold", _s(size, scale))
    asc, desc = f.getmetrics()
    w, h = int(text_width(text, f)) + _s(60, scale) * size // 54, asc + desc + _s(22, scale)
    im = rounded_rect((w, h), _s(16, scale), (rgb(fill) if fill is not None else T["accent"]) + (255,))
    ImageDraw.Draw(im).text((w / 2, h / 2), text, font=f, fill=rgba(text_fill), anchor="mm")
    return im.rotate(angle, expand=True, resample=Image.BICUBIC) if angle else im


def node_card(title, eyebrow="", theme=None, scale=1.0, min_w=620, max_w=960):
    """Section card shown over an internal jump: dark plate, accent outline, short rule, eyebrow, title."""
    T = get_theme(theme)
    fe, ft = load_font("cjk-bold", _s(30, scale)), load_font("cjk-bold", _s(56, scale))
    w = max(text_width(title, ft), text_width(eyebrow, fe)) + _s(120, scale)
    w = int(min(max(w, _s(min_w, scale)), _s(max_w, scale)))
    if text_width(title, ft) > w - _s(96, scale):
        ft = load_font("cjk-bold", _s(44, scale))
    h = _s(216, scale)
    im = rounded_rect((w, h), _s(24, scale), (10, 12, 16, 247), outline=T["accent"] + (235,), width=_s(3, scale))
    d = ImageDraw.Draw(im)
    d.rectangle([_s(48, scale), _s(60, scale), _s(120, scale), _s(65, scale)], fill=T["accent"] + (255,))
    if eyebrow:
        d.text((_s(48, scale), _s(86, scale)), eyebrow, font=fe, fill=T["accent"] + (255,))
    d.text((_s(48, scale), _s(128 if eyebrow else 100, scale)), title, font=ft, fill=(255, 255, 255, 255))
    return im


def with_accent(theme, accent):
    """Theme dict with its accent (rail, outline, highlight, dot, chip, tag) replaced by ``accent``."""
    T = dict(get_theme(theme))
    if accent is None:
        return T
    a = rgb(accent)
    T.update(accent=a, hl=a + (255,), dot=a + (255,), chip_fill=a)
    if T.get("outline") is not None and T.get("name") == "teal":
        T["outline"] = a + (255,)
    if T.get("name") == "teal":
        T["tag_text"] = a + (255,)
    return T


def chapter_card(index, total, title, size=(1920, 1080), theme=None, ground=None, accent=None, title_frac=0.075,
                 max_lines=3):
    """Full-frame chapter card (opaque RGBA): '02 / 05' in accent, 'Main：sub' -> grey kicker + big title,
    accent rule. Type scales with the card: the title is ``title_frac`` of the frame height (7.5%:
    81 px at 1080, 144 px at 1920 tall), number and kicker ~45% of it, shrunk only if the longest
    word would not fit; the whole block (number, kicker, title, rule) is centred vertically and the
    left-aligned block is centred horizontally. accent: per-video accent override."""
    T = with_accent(theme, accent); B = brand()
    W, H = size
    bg = rgb(ground) if ground else B["ground"]
    im = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(im)
    margin = int(W * (0.09 if W >= H else 0.08))
    max_w = W - 2 * margin
    sep = next((p for p in ("：", ": ", "｜", " | ") if p in title), None)
    main, sub = title.split(sep, 1) if sep else (title, "")
    big = sub or main
    ts = max(12, int(round(H * title_frac)))
    while True:
        ftl = load_font("cjk-bold", ts)
        lines = wrap(big, ftl, max_w, balance=True)
        if (len(lines) <= max_lines and max(text_width(ln, ftl) for ln in lines) <= max_w) or ts <= 24:
            break
        ts = int(ts * 0.92)
    ss = max(10, int(round(ts * 0.45)))
    fi = load_font("cjk", ss)
    lh = int(sum(ftl.getmetrics()) * 1.15)
    num = f"{index:02d} / {total:02d}" if total else f"{index:02d}"
    gap1 = int(ts * 0.55)                                 # number -> kicker/title
    gap2 = int(ts * 0.25)                                 # kicker -> title
    rule_gap, rule_h, rule_w = int(ts * 0.38), max(2, int(ts * 0.1)), int(ts * 2.3)
    nh = sum(fi.getmetrics())
    block_h = nh + gap1 + (nh + gap2 if sub else 0) + len(lines) * lh + rule_gap + rule_h
    block_w = max([text_width(ln, ftl) for ln in lines] + [text_width(num, fi), text_width(main, fi) if sub else 0])
    x = int(max(margin, (W - block_w) / 2))
    y = int((H - block_h) / 2)
    d.text((x, y), num, font=fi, fill=T["accent"] + (255,))
    y += nh + gap1
    if sub:
        d.text((x, y), main, font=fi, fill=B["dim"] + (255,))
        y += nh + gap2
    for k, ln in enumerate(lines):
        draw_runs(d, (x - max(1, ts // 40), y + k * lh), ln, ftl, B["ink"] + (255,), T["hl"])
    yr = y + len(lines) * lh + rule_gap
    d.rectangle([x, yr, x + rule_w, yr + rule_h], fill=T["accent"] + (255,))
    return im


# ---------------------------------------------------------------- progress bars
def _norm_chapters(chapters):
    out = []
    for c in chapters:
        if isinstance(c, dict):
            out.append((float(c["start"]), float(c["end"]), c.get("label", c.get("title", ""))))
        else:
            out.append((float(c[0]), float(c[1]), str(c[2])))
    return out


def progress_bar(chapters, t, total=None, style="classic", width=1080, x0=None, x1=None, scale=None, theme=None):
    """Chapter progress strip at time t (same clock as chapter times). Returns RGBA of size (width, h).

    classic: thin track, chapter ticks, labels under each segment, accent fill + white knob, active label
             as an accent pill (notes-board).
    refined: one rounded segment per chapter with gaps, accent->amber gradient fill with glow, white knob,
             and a '01 / 05  label' pill under the bar (精剪)."""
    T = get_theme(theme); B = brand()
    ch = _norm_chapters(chapters)
    total = float(total if total is not None else (ch[-1][1] if ch else 1.0))
    s = scale if scale is not None else width / 1080.0
    x0 = _s(64, s) if x0 is None else x0
    x1 = width - _s(64, s) if x1 is None else x1
    span = x1 - x0
    fl = load_font("cjk-bold", _s(28, s))
    if style == "refined":
        H = _s(96, s); y0 = _s(12, s); ph = _s(7, s); gap = _s(10, s)
        strip = Image.new("RGBA", (width, H), (0, 0, 0, 0)); d = ImageDraw.Draw(strip)
        dur = sum(b - a for a, b, _ in ch) or 1.0
        avail = span - gap * (len(ch) - 1)
        c0, c1 = np.array(B["accent"], float), np.array(rgb("#FFB84D"), float)
        grad = (c0[None] + (c1 - c0)[None] * np.linspace(0, 1, max(1, span))[:, None]).astype(np.uint8)
        x, segs, cur = x0, [], 0
        for a, b, _ in ch:
            w = avail * (b - a) / dur; segs.append((x, x + w)); x += w + gap
        for i, ((a, b, _), (xa, xb)) in enumerate(zip(ch, segs)):
            d.rounded_rectangle([xa - 1, y0 - 1, xb + 1, y0 + ph + 2], ph // 2 + 1, fill=(0, 0, 0, 70))
            d.rounded_rectangle([xa, y0, xb, y0 + ph], ph // 2, fill=(255, 255, 255, 110))
            if t >= a:
                p = 1.0 if t >= b else (t - a) / max(1e-6, b - a)
                if t < b:
                    cur = i
                xe = xa + (xb - xa) * p
                if xe - xa > 2:
                    wd = int(xe - xa) + 1
                    arr = np.zeros((ph + 1, wd, 4), np.uint8)
                    lo = int(xa - x0); g = grad[lo:lo + wd]
                    arr[:, :g.shape[0], :3] = g[None]; arr[..., 3] = 255
                    m = Image.new("L", (wd, ph + 1), 0)
                    ImageDraw.Draw(m).rounded_rectangle([0, 0, wd - 1, ph], ph // 2, fill=255)
                    fi = Image.fromarray(arr); fi.putalpha(m); strip.alpha_composite(fi, (int(xa), y0))
        if ch and t >= ch[-1][1]:
            cur = len(ch) - 1
        glow = np.array(strip.filter(ImageFilter.GaussianBlur(6))).astype(np.float32); glow[..., 3] *= 0.8
        out = Image.alpha_composite(Image.fromarray(glow.astype(np.uint8)), strip)
        if ch:
            a, b, lab = ch[cur]; xa, xb = segs[cur]
            xe = xa + (xb - xa) * min(1, max(0, (t - a) / max(1e-6, b - a)))
            r = _s(8, s)
            ImageDraw.Draw(out).ellipse([xe - r, y0 + ph / 2 - r, xe + r, y0 + ph / 2 + r], fill=(255, 255, 255, 255))
            out.alpha_composite(chapter_label(cur, len(ch), lab, s), (max(0, x0 - _s(4, s)), y0 + _s(22, s)))
        return out
    # classic
    H = _s(84, s); by = _s(14, s); th = _s(9, s)
    out = Image.new("RGBA", (width, H), (0, 0, 0, 0)); d = ImageDraw.Draw(out)
    d.rounded_rectangle([x0, by, x1, by + th], th // 2, fill=(255, 255, 255, 110))
    X = lambda v: x0 + span * min(1.0, max(0.0, v / total))
    for a, b, lab in ch:
        if a > 0:
            d.rectangle([X(a) - 1, by - 1, X(a) + 1, by + th + 1], fill=(30, 30, 30, 200))
    xe = X(t)
    if xe > x0:
        d.rounded_rectangle([x0, by, xe, by + th], th // 2, fill=T["accent"] + (255,))
    for a, b, lab in ch:
        cx = (X(a) + X(b)) / 2; ly = by + th + _s(26, s)
        if a <= t < b or (t >= total and b >= total):
            pill = chip(lab, "filled", {**T, "chip_fill": T["accent"], "chip_text": (255, 255, 255)}, scale=s, size=28)
            out.alpha_composite(pill, (int(max(0, min(width - pill.width, cx - pill.width / 2))),
                                       int(min(H - pill.height, ly - pill.height / 2))))
        else:
            d.text((cx, ly), lab, font=fl, fill=(255, 255, 255, 235), anchor="mm", stroke_width=_s(3, s),
                   stroke_fill=(0, 0, 0, 160))
    r = _s(12, s)
    d.ellipse([xe - r, by + th / 2 - r, xe + r, by + th / 2 + r], fill=(255, 255, 255, 255))
    return out


def chapter_label(i, n, label, scale=1.0):
    """'01 / 05  label' pill on a translucent plate (refined progress bar, chapter callouts)."""
    s = scale
    f1, f2 = load_font("cjk-bold", _s(28, s)), load_font("cjk-bold", _s(30, s))
    num, tot = f"{i + 1:02d}", f" / {n:02d}"
    w1, w2, w3 = text_width(num, f1), text_width(label, f2), text_width(tot, f1)
    h = _s(50, s)
    im = rounded_rect((int(w1 + w2 + w3 + _s(62, s)), h), h // 2, (10, 10, 14, 120))
    d = ImageDraw.Draw(im)
    d.text((_s(20, s), h / 2), num, font=f1, fill=(255, 196, 90, 255), anchor="lm")
    d.text((_s(20, s) + w1, h / 2), tot, font=f1, fill=(255, 255, 255, 120), anchor="lm")
    d.text((_s(20, s) + w1 + w3 + _s(16, s), h / 2), label, font=f2, fill=(255, 255, 255, 240), anchor="lm")
    return im


def progress_fill(x, y, w, h, dur, color, t0=0.0, fps=30, inp="[in]", out="[out]", head=None, prefix="pf",
                  enable=True):
    """ffmpeg filtergraph that grows a ``color`` fill bar w x h at (x, y) from 0 to full width over
    [t0, t0 + dur] (output seconds), plus an optional white playhead ``head=(hw, hh)`` centred on the
    fill's edge. Works per frame: colour sources + ``overlay`` x expressions (``drawbox`` evaluates its
    expressions once - and its ``t`` is the box thickness - so a drawbox fill never moves).
    With inp="[in]"/out="[out]" it is a complete ``-vf`` string; pass labels for a -filter_complex.
    From talkinghead ``build_filter.py`` (the fix for the static-fill bug)."""
    c = color if isinstance(color, str) else "0x%02X%02X%02X" % tuple(color[:3])
    P = f"min(1,max(0,(t-{t0:.3f})/{max(dur, 1e-3):.3f}))"
    en = f":enable='gte(t,{t0:.3f})'" if enable and t0 > 0 else ""
    g = [f"color=c=black@0:s={w}x{h}:r={fps},format=rgba[{prefix}cv]",
         f"color=c={c}:s={w}x{h}:r={fps},format=rgba[{prefix}col]",
         f"[{prefix}cv][{prefix}col]overlay=x='-{w}+{P}*{w}':eof_action=pass:shortest=1[{prefix}fill]"]
    last = f"[{prefix}fill]"
    if head:
        hw, hh = head
        g.append(f"color=c=white:s={hw}x{hh}:r={fps},format=rgba[{prefix}head]")
        g.append(f"{inp}{last}overlay=x={x}:y={y}:shortest=1{en}[{prefix}a]")
        g.append(f"[{prefix}a][{prefix}head]overlay=x='{x}+{P}*{w}-{hw / 2:g}':y={y + h / 2 - hh / 2:g}:shortest=1{en}{out}")
    else:
        g.append(f"{inp}{last}overlay=x={x}:y={y}:shortest=1{en}{out}")
    return ";".join(g)


def progress_static(chapters, total, width=1920, y=1000, x0=80, bar_w=None, scale=None, theme=None, t0=0.0,
                    speed=1.0, fps=30, head=False):
    """Static assets for an ffmpeg overlay pass (no per-frame Python):
    {"bar": RGBA (dim track, ticks, labels), "bar_xy": (0, y), "active": [(RGBA, x, y, start, end)],
     "fill": complete ``-vf`` graph ([in] -> [out]) that grows the accent fill with t,
     "fill_graph": fn(inp, out, t0=t0, speed=speed) -> the same for a -filter_complex,
     "drawbox": alias of "fill" (kept for old callers; it used to be a drawbox that never animated)}.
    Chapter times are in the same clock as `total`; t0 = output second where that clock's 0 plays,
    speed = playback speed of that part (the fill spans total/speed output seconds). head=True adds
    a white playhead."""
    T = get_theme(theme)
    s = scale if scale is not None else width / 1920.0
    bar_w = bar_w or (width - 2 * x0)
    ch = _norm_chapters(chapters)
    BY, BH, TT, TH, LY = _s(22, s), _s(5, s), _s(17, s), _s(15, s), _s(40, s)
    pos = lambda v: x0 + v / total * bar_w
    bar = Image.new("RGBA", (width, _s(80, s)), (0, 0, 0, 0)); d = ImageDraw.Draw(bar)
    d.rectangle([x0, BY, x0 + bar_w, BY + BH], fill=(255, 255, 255, 95))
    for a, _, _ in ch + [(total, total, "")]:
        xx = int(round(pos(a))); d.rectangle([xx - 1, TT, xx + 1, TT + TH], fill=(255, 255, 255, 235))
    fl, fa = load_font("cjk", _s(22, s)), load_font("cjk-bold", _s(26, s))
    active = []
    for a, b, lab in ch:
        cx = (pos(a) + pos(b)) / 2
        d.text((cx, LY), lab, font=fl, fill=(255, 255, 255, 235), anchor="mt", stroke_width=_s(3, s), stroke_fill=(0, 0, 0, 210))
        w = int(text_width(lab, fa)) + _s(16, s); h = sum(fa.getmetrics()) + _s(12, s)
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((w / 2, h / 2), lab, font=fa, fill=T["accent"] + (255,), anchor="mm",
                                stroke_width=_s(4, s), stroke_fill=(255, 255, 255, 255))
        active.append((im, int(round(cx - w / 2)), y + LY + (sum(fl.getmetrics()) - h) // 2, a, b))
    hexc = "0x%02X%02X%02X" % tuple(T["accent"])
    hd = (_s(12, s), _s(15, s)) if head else None

    def fill_graph(inp="[in]", out="[out]", t0=t0, speed=speed, prefix="pf"):
        return progress_fill(x0, y + BY, int(round(bar_w)), BH, total / speed, hexc, t0=t0, fps=fps, inp=inp,
                             out=out, head=hd, prefix=prefix)
    fill = fill_graph()
    return {"bar": bar, "bar_xy": (0, y), "active": active, "fill": fill, "fill_graph": fill_graph, "drawbox": fill}


# ---------------------------------------------------------------- HyperFrames / HTML snippets
HF_GEO = {
    "horizontal": dict(W=1920, H=1080, scrim_t=990, scrim_h=90, bar_l=80, bar_t=1046, bar_w=1760, chap_t=1012,
                       cue_lr=160, cue_t=922, cue_fs=50, chap_fs=22),
    "vertical": dict(W=1080, H=1920, scrim_t=1580, scrim_h=120, bar_l=60, bar_t=1640, bar_w=960, chap_t=1606,
                     cue_lr=60, cue_t=820, cue_fs=54, chap_fs=24),
}


def _geo(geo):
    if isinstance(geo, str):
        return dict(HF_GEO[geo])
    g = dict(HF_GEO["horizontal" if (geo or {}).get("W", 1920) >= (geo or {}).get("H", 1080) else "vertical"])
    g.update(geo or {})
    return g


def hf_progress(chapters, start, total, geo="horizontal", font_family="CJK", track_index=8, timeline_var="tl"):
    """Progress bar + chapter labels on a bottom scrim (labels are unreadable over bright footage without it).
    Returns {"css", "html", "js"}; js expects a paused GSAP timeline named `timeline_var`.
    `start`..`total` is the bar span in composition seconds; chapters are (start, end, label) in the same clock."""
    g = _geo(geo); B = brand()
    acc = "#%02X%02X%02X" % B["accent"]; acc2 = "#%02X%02X%02X" % B.get("accent_soft", B["accent"])
    css = f"""#bar-scrim {{ position: absolute; left: 0; right: 0; top: {g["scrim_t"]}px; height: {g["scrim_h"]}px; background: linear-gradient(to bottom, rgba(5,8,16,0), rgba(5,8,16,.72) 55%, rgba(5,8,16,.85)); }}
#bar {{ position: absolute; left: {g["bar_l"]}px; top: {g["bar_t"]}px; width: {g["bar_w"]}px; height: 4px; background: rgba(255,255,255,.22); border-radius: 2px; }}
#bar-fill {{ position: absolute; left: 0; top: 0; width: {g["bar_w"]}px; height: 4px; background: var(--accent, {acc}); border-radius: 2px; transform-origin: 0 50%; }}
.tick {{ position: absolute; top: -5px; width: 2px; height: 14px; background: rgba(255,255,255,.75); }}
.chap {{ position: absolute; top: {g["chap_t"]}px; font: 400 {g["chap_fs"]}px "{font_family}"; color: rgba(255,255,255,.9); transform: translateX(-50%); text-shadow: 0 1px 4px rgba(0,0,0,.9); white-space: nowrap; }}
"""
    html = (f'<div id="barwrap" class="clip full" data-start="{start:.3f}" data-duration="{total - start:.3f}" '
            f'data-track-index="{track_index}" style="pointer-events:none">\n'
            f'  <div id="bar-scrim"></div><div id="bar"><div id="bar-fill"></div></div><div id="chaps"></div>\n</div>')
    data = dict(H=start, TOTAL=total, BAR_L=g["bar_l"], BAR_W=g["bar_w"], ACC2=acc2,
                CHAP=[[round(a, 3), round(b, 3), lab] for a, b, lab in _norm_chapters(chapters)])
    js = f"""(function () {{
const P = {json.dumps(data, ensure_ascii=False)};
const chaps = document.querySelector("#chaps"), bar = document.querySelector("#bar"), span = P.TOTAL - P.H;
const X = (t) => P.BAR_L + (t - P.H) / span * P.BAR_W;
P.CHAP.forEach(([s, e, label], i) => {{
  if (i) {{ const tk = document.createElement("div"); tk.className = "tick"; tk.style.left = (X(s) - P.BAR_L) + "px"; bar.appendChild(tk); }}
  const c = document.createElement("div"); c.className = "chap"; c.id = "chap" + i; c.textContent = label;
  c.style.left = ((X(s) + X(e)) / 2) + "px"; chaps.appendChild(c);
  {timeline_var}.to(c, {{ color: P.ACC2, fontWeight: 700, scale: 1.12, duration: 0.2 }}, s);
  {timeline_var}.to(c, {{ color: "rgba(255,255,255,0.9)", fontWeight: 400, scale: 1, duration: 0.2 }}, e);
}});
{timeline_var}.fromTo("#bar-fill", {{ scaleX: 0 }}, {{ scaleX: 1, duration: span, ease: "none" }}, P.H);
}})();
"""
    return {"css": css, "html": html, "js": js}


def hf_cue_css(geo="horizontal", font_family="CJK", highlight=None):
    """Subtitle cue CSS: centred bold line with a hard outline + soft shadow; <em> = highlighted term."""
    g = _geo(geo); B = brand()
    hl = highlight or "#%02X%02X%02X" % B["highlight"]
    return (f'.cue {{ position: absolute; left: {g["cue_lr"]}px; right: {g["cue_lr"]}px; top: {g["cue_t"]}px; '
            f'text-align: center; font: 700 {g["cue_fs"]}px/1.2 "{font_family}"; color: #fff; opacity: 0; '
            f'text-shadow: 0 3px 0 rgba(0,0,0,.85), 0 0 18px rgba(0,0,0,.55), 2px 0 0 #000, -2px 0 0 #000, 0 -2px 0 #000; }}\n'
            f'.cue em {{ font-style: normal; color: var(--highlight, {hl}); }}\n')


def cue_html(text):
    """Escape a cue and turn 【term】 markup into <em>term</em>."""
    import html as _h
    from .draw import markup
    a, b = markup()
    return _h.escape(text).replace(a, "<em>").replace(b, "</em>")
