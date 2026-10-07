"""Themed overlay furniture (RGBA PIL images) + HTML/CSS snippets for HyperFrames projects.

    from vstudio import overlays as O
    O.notes_panel("三个要点", ["第一点", "第二点【重点】"])          # theme = persona.brand.panel_theme
    O.callout("这里是关键"), O.chip("标签"), O.badge("精彩预告"), O.stamp("亲测", 8)
    O.node_card("第二部分", eyebrow="NEXT"), O.chapter_card(2, 5, "主题：小标题")
    O.progress_bar(chapters, t, total, style="refined", width=1080)   # per-frame strip
    O.progress_static(chapters, total, width=1920)                     # PNG + ffmpeg drawbox for a static pass
    O.hf_progress(chapters, start, total, geo) / O.hf_cue_css(...)     # HyperFrames / GSAP snippets

Panel themes: paper (default: the design theme's light card, small label + thin rule; vstudio.theme), notes-red
(dark card, accent header, highlight 记笔记 tag; the legacy ``classic`` look), notes-yellow (paper card, highlight
header), teal (dark card, teal rail + outline, longform style), navy (brand ground card, gold title). A design theme
name (editorial, mono, soft, night, xhs-pop, classic) is accepted too and gives that theme's panel.
Themed blocks (read vstudio.theme tokens): title_band, quote_block, notes_chip, marker_line, chapter_rule,
counter, lower_third. Rules: references/STYLE_RULES.md.
`scale` multiplies every size (1.0 = designed for a 1920-wide landscape frame; use ~1.5 for 1080x1920).
"""
import json

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import theme as TH
from .config import persona
from .draw import (brand, draw_runs, emph_layer, load_font, rgb, rgba, rounded_rect, shadow, text_layer, text_width,
                   wrap)

THEMES = ("paper", "notes-red", "notes-yellow", "teal", "navy") + tuple(TH.names())


def notes_tag_default():
    return ((persona().get("overlays") or {}).get("notes_tag")) or "记笔记 ↓"


def paper_theme(T=None) -> dict:
    """The panel colours of a design theme (light card, small accent label, thin rule; dark card on night)."""
    T = T or TH.current()
    c = lambda k, a=255: TH.rgba(T, k, a)
    acc = TH.rgb(T, "accent")
    card_a = int(255 * float(T["card_alpha"]))
    return dict(name="paper", layout="paper", design=T["name"], card=TH.rgb(T, "card") + (card_a,), header=None,
                header_text=c("card_ink"), tag_bg=None, tag_text=acc + (255,), text=c("card_ink"),
                text2=c("ink2"), hl=acc + (255,), dot=acc + (255,), accent=acc, outline=None, rule=c("rule"),
                bubble=TH.rgb(T, "card") + (card_a,), bubble_text=c("card_ink"), chip_fill=acc,
                chip_text=TH.rgb(T, "accent_ink"), radius=int(T["radius"]), shadow=tuple(T["shadow"]))


def get_theme(name=None) -> dict:
    """Resolved panel colours for a panel theme name, a design theme name or a dict. Default: the persona's
    brand.panel_theme while no design theme is chosen (legacy), else the active design theme's paper panel."""
    if isinstance(name, dict):
        return name
    T = TH.current()
    if not name:
        if T.get("source") in ("legacy", "default"):
            name = (persona().get("brand") or {}).get("panel_theme")
        if not name:
            name = "notes-red" if T["notes"] == "header" else "paper"
    if name not in ("notes-red", "notes-yellow", "teal", "navy", "paper"):
        c = TH.canonical(name)
        if c:
            T = TH.resolve(c)
            name = "notes-red" if T["notes"] == "header" else "paper"
    if name == "paper":
        return paper_theme(T)
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

    if T["layout"] == "paper":
        return _notes_paper(title, bullets, T, W, scale, tag, keywords)
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


def _label_text(tag):
    return str(tag or "").replace("↓", "").replace("→", "").strip()


def tracked_width(text, f, track):
    size = getattr(f, "size", 20)
    return sum(text_width(ch, f) for ch in text) + max(0, len(text) - 1) * size * track


def draw_tracked(d, xy, text, f, fill, track=0.12):
    """Letter-spaced small label (eyebrows, 本段 / 记笔记 labels); returns the x after the text."""
    x, y = xy
    size = getattr(f, "size", 20)
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += text_width(ch, f) + size * track
    return x - size * track


def _notes_paper(title, bullets, P, W, scale, tag, keywords):
    """Paper notes card: small accent label, title, hairline rule, bullets (keywords the theme's way)."""
    T = TH.resolve(P.get("design")) if P.get("design") else TH.current()
    PX, PT, PB = _s(30, scale), _s(24, scale), _s(26, scale)
    fl = load_font(T["font_label"], _s(22, scale))
    ft = load_font(T["font_strong"], _s(34, scale))
    fb = load_font(T["font_body"], _s(30, scale))
    fe = load_font(T["font_strong"], _s(30, scale))
    lab = _label_text(tag)
    inner = W - 2 * PX
    tlines = wrap(title, ft, inner, balance=True) if title else []
    tlh = int(sum(ft.getmetrics()) * 1.22)
    DOT, GAP = _s(7, scale), _s(12, scale)
    bx = PX + DOT + _s(14, scale)
    blocks = []
    for b in bullets:
        cont = b.startswith(" ")
        im = emph_layer(b.strip(), fb, T, surface="paper", fill=P["text"], emph_font=fe, max_w=W - bx - PX,
                        line_gap=1.3, pad=0, keywords=keywords)
        blocks.append((cont, im))
    lab_h = (sum(fl.getmetrics()) + _s(12, scale)) if lab else 0
    rule_gap = _s(16, scale)
    H = PT + lab_h + tlh * len(tlines) + (rule_gap * 2 + P_rule_w(scale) if blocks else 0) \
        + sum(im.height for _, im in blocks) + GAP * max(0, len(blocks) - 1) + PB
    if not blocks:
        H -= _s(6, scale)
    r = _s(P.get("radius", 14), scale)
    im = rounded_rect((W, H), r, P["card"])
    d = ImageDraw.Draw(im)
    y = PT
    if lab:
        d.ellipse([PX, y + _s(8, scale), PX + _s(8, scale), y + _s(16, scale)], fill=P["accent"] + (255,))
        draw_tracked(d, (PX + _s(16, scale), y - _s(2, scale)), lab, fl, P["accent"] + (255,), T["label_track"])
        y += lab_h
    for ln in tlines:
        draw_runs(d, (PX, y), ln, ft, P["header_text"], P["header_text"])
        y += tlh
    if blocks:
        y += rule_gap - _s(6, scale)
        d.rectangle([PX, y, W - PX, y + P_rule_w(scale) - 1], fill=P["rule"])
        y += P_rule_w(scale) + rule_gap
        asc = sum(fb.getmetrics())
        for cont, b in blocks:
            if not cont:
                cy = y + asc // 2
                d.ellipse([PX, cy - DOT // 2, PX + DOT, cy + DOT // 2], fill=P["dot"])
            im.alpha_composite(b, (bx, int(y)))
            y += b.height + GAP
    return im


def P_rule_w(scale):
    return max(1, _s(2, scale))


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


def stamp(text, angle=None, theme=None, scale=1.0, size=56):
    """Stamp in the design theme's style. ``outline`` (default themes): a quiet label - thin ink / accent border,
    paper fill, upright. ``plate`` (classic): white plate, thick accent border + accent text, rotated 8 deg.
    angle None = the theme's angle."""
    D = TH.current() if theme is None or theme in THEMES[:5] else TH.resolve(theme)
    st = D["stamp"]
    if angle is None:
        angle = float(st.get("angle") or 0)
    if st.get("style") == "label":                     # quiet card label: accent dot + tracked ink text, no border
        f = load_font(D["font_strong"], _s(size * 0.54, scale))
        asc, desc = f.getmetrics()
        tw = tracked_width(text, f, 0.08)
        dot = _s(size * 0.1, scale)
        PX = _s(size * 0.36, scale)
        w, h = int(tw + dot * 2 + PX * 2 + _s(size * 0.2, scale)), asc + desc + _s(size * 0.42, scale)
        im = rounded_rect((w, h), _s(min(10, D["radius"]), scale), TH.rgb(D, "card") + (int(255 * st.get("fill_alpha", 0.95)),))
        d = ImageDraw.Draw(im)
        cy = h / 2
        d.ellipse([PX, cy - dot, PX + 2 * dot, cy + dot], fill=TH.rgba(D, st.get("color") or "accent"))
        draw_tracked(d, (PX + 2 * dot + _s(size * 0.2, scale), (h - asc - desc) / 2 - _s(1, scale)), text, f,
                     TH.rgba(D, "card_ink"), 0.08)
        return im.rotate(angle, expand=True, resample=Image.BICUBIC) if angle else im
    if st.get("style") != "plate":
        col = TH.rgb(D, st.get("color") or "ink")
        f = load_font(D["font_strong"], _s(size * 0.82, scale))
        asc, desc = f.getmetrics()
        w = int(tracked_width(text, f, 0.06)) + _s(52, scale)
        h = asc + desc + _s(30, scale)
        im = rounded_rect((w, h), _s(min(10, D["radius"]), scale), TH.rgb(D, "card") + (int(255 * st.get("fill_alpha", 0.92)),),
                          outline=col + (255,), width=max(1, _s(st.get("border", 2), scale)))
        d = ImageDraw.Draw(im)
        tw = tracked_width(text, f, 0.06)
        draw_tracked(d, ((w - tw) / 2, (h - asc - desc) / 2 - _s(1, scale)), text, f, col + (255,), 0.06)
        return im.rotate(angle, expand=True, resample=Image.BICUBIC) if angle else im
    T = get_theme(theme if theme in THEMES[:5] else None)
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
    D = TH.current()
    if not TH.is_classic(D):                            # theme card, accent rule + eyebrow, ink title
        im = rounded_rect((w, h), _s(D["radius"], scale), TH.rgb(D, "card") + (int(255 * D["card_alpha"]),))
        d = ImageDraw.Draw(im)
        acc = TH.rgb(D, "accent") + (255,)
        d.rectangle([_s(48, scale), _s(60, scale), _s(104, scale), _s(62, scale)], fill=acc)
        if eyebrow:
            draw_tracked(d, (_s(48, scale), _s(80, scale)), eyebrow, load_font(D["font_label"], _s(26, scale)), acc,
                         D["label_track"])
        d.text((_s(48, scale), _s(128 if eyebrow else 100, scale)), title, font=ft, fill=TH.rgba(D, "card_ink"))
        return im
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
    D = TH.current()
    if not TH.is_classic(D) and not ground:             # paper card: theme paper, ink title, accent number + rule
        B = dict(B, ink=TH.rgb(D, "ink"), dim=TH.rgb(D, "ink2"), ground=TH.rgb(D, "paper"))
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

    line:    (theme default) a hairline track in the theme's rule colour, accent fill, small gaps between
             chapters, no knob / glow; the current chapter as a small grey label when the theme asks for it.
    classic: thin track, chapter ticks, labels under each segment, accent fill + white knob, active label
             as an accent pill (notes-board).
    refined: one rounded segment per chapter with gaps, accent->amber gradient fill with glow, white knob,
             and a '01 / 05  label' pill under the bar (精剪)."""
    if style in (None, "auto", "theme"):
        style = TH.current()["progress"].get("style") or "line"
    if style == "line":
        return progress_line(chapters, t, total, width=width, x0=x0, x1=x1, scale=scale)
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
                       cue_lr=160, cue_t=922, cue_fs=50, chap_fs=22,
                       top_scrim_t=0, top_scrim_h=96, top_bar_t=30, top_chap_t=44),
    "vertical": dict(W=1080, H=1920, scrim_t=1580, scrim_h=120, bar_l=60, bar_t=1640, bar_w=960, chap_t=1606,
                     cue_lr=60, cue_t=820, cue_fs=54, chap_fs=24,
                     top_scrim_t=110, top_scrim_h=150, top_bar_t=160, top_chap_t=176),
}


def _label_w(label, fs):
    """Rough rendered width (px) of a chapter label: CJK 1 em, other 0.56 em, +12 % for the active scale."""
    return sum(fs if ord(c) >= 0x2E80 else 0.56 * fs for c in str(label)) * 1.12


def _shorten(label, max_w, fs):
    label = str(label)
    if _label_w(label, fs) <= max_w:
        return label
    for n in range(len(label) - 1, 1, -1):
        cand = label[:n].rstrip() + "…"
        if _label_w(cand, fs) <= max_w:
            return cand
    return label[:2] + "…" if len(label) > 2 else label


def layout_chapter_labels(chapters, start, total, bar_l, bar_w, fs, gap=12, max_rows=2):
    """Collision handling for chapter labels centred on their chapter span of a progress bar.

    Overlapping labels are (1) shortened with "…" to their own span, then (2) staggered onto a second
    row, then (3) merged (the shorter chapter's label hidden). Returns (labels, rows, notes) where
    notes lists what was done (empty when nothing collided)."""
    ch = _norm_chapters(chapters)
    span = max(1e-9, total - start)
    X = lambda t: bar_l + (t - start) / span * bar_w  # noqa: E731
    cx = [(X(a) + X(b)) / 2 for a, b, _ in ch]
    labels = [str(lab) for _, _, lab in ch]
    rows = [0] * len(ch)
    notes = []

    def clash(i, j, labs):
        return abs(cx[j] - cx[i]) < (_label_w(labs[i], fs) + _label_w(labs[j], fs)) / 2 + gap

    if not any(clash(i, i + 1, labels) for i in range(len(ch) - 1)):
        return labels, rows, notes
    for i, (a, b, _) in enumerate(ch):                          # 1. shorten to the own span
        near = (i and clash(i - 1, i, labels)) or (i + 1 < len(ch) and clash(i, i + 1, labels))
        if near:
            new = _shorten(labels[i], max(X(b) - X(a) - gap, 2.2 * fs), fs)
            if new != labels[i]:
                notes.append(f"shortened {labels[i]!r} -> {new!r}")
                labels[i] = new
    if max_rows > 1:                                            # 2. stagger
        for i in range(1, len(ch)):
            if rows[i - 1] == 0 and clash(i - 1, i, labels):
                rows[i] = 1
        if any(rows):
            notes.append(f"staggered {sum(rows)} label(s) onto a second row")
    for i in range(len(ch)):                                    # 3. merge what still collides on a row
        for j in range(i + 1, len(ch)):
            if rows[i] == rows[j] and labels[i] and labels[j] and clash(i, j, labels):
                k = i if (ch[i][1] - ch[i][0]) < (ch[j][1] - ch[j][0]) else j
                notes.append(f"hid label {labels[k]!r} (chapter too short)")
                labels[k] = ""
    return labels, rows, notes


def _geo(geo):
    if isinstance(geo, str):
        return dict(HF_GEO[geo])
    g = dict(HF_GEO["horizontal" if (geo or {}).get("W", 1920) >= (geo or {}).get("H", 1080) else "vertical"])
    g.update(geo or {})
    return g


def hf_progress(chapters, start, total, geo="horizontal", font_family="CJK", track_index=8, timeline_var="tl",
                position="bottom", collisions="auto"):
    """Progress bar + chapter labels on a scrim (labels are unreadable over bright footage without it).
    Returns {"css", "html", "js"} (+ "notes": collision fixes); js expects a paused GSAP timeline named
    `timeline_var`. `start`..`total` is the bar span in composition seconds; chapters are (start, end, label)
    in the same clock.
    position: "bottom" (scrim fades up from the bottom, labels above the bar) or "top" (scrim fades down
    from ``top_scrim_t``, labels under the bar; geo keys top_scrim_t/top_scrim_h/top_bar_t/top_chap_t).
    collisions: "auto" shortens / staggers / merges labels that would overlap (``layout_chapter_labels``)
    and warns; "off" places them as given."""
    import warnings
    g = _geo(geo); B = brand()
    top = position == "top"
    if position not in ("top", "bottom"):
        raise ValueError("position must be 'top' or 'bottom'")
    if top:
        g.update(scrim_t=g["top_scrim_t"], scrim_h=g["top_scrim_h"], bar_t=g["top_bar_t"], chap_t=g["top_chap_t"])
    acc = "#%02X%02X%02X" % B["accent"]; acc2 = "#%02X%02X%02X" % B.get("accent_soft", B["accent"])
    grad = "to top" if top else "to bottom"
    css = f"""#bar-scrim {{ position: absolute; left: 0; right: 0; top: {g["scrim_t"]}px; height: {g["scrim_h"]}px; background: linear-gradient({grad}, rgba(5,8,16,0), rgba(5,8,16,.72) 55%, rgba(5,8,16,.85)); }}
#bar {{ position: absolute; left: {g["bar_l"]}px; top: {g["bar_t"]}px; width: {g["bar_w"]}px; height: 4px; background: rgba(255,255,255,.22); border-radius: 2px; }}
#bar-fill {{ position: absolute; left: 0; top: 0; width: {g["bar_w"]}px; height: 4px; background: var(--accent, {acc}); border-radius: 2px; transform-origin: 0 50%; }}
.tick {{ position: absolute; top: -5px; width: 2px; height: 14px; background: rgba(255,255,255,.75); }}
.chap {{ position: absolute; top: {g["chap_t"]}px; font: 400 {g["chap_fs"]}px "{font_family}"; color: rgba(255,255,255,.9); transform: translateX(-50%); text-shadow: 0 1px 4px rgba(0,0,0,.9); white-space: nowrap; }}
"""
    html = (f'<div id="barwrap" class="clip full" data-start="{start:.3f}" data-duration="{total - start:.3f}" '
            f'data-track-index="{track_index}" style="pointer-events:none">\n'
            f'  <div id="bar-scrim"></div><div id="bar"><div id="bar-fill"></div></div><div id="chaps"></div>\n</div>')
    ch = _norm_chapters(chapters)
    labels, rows, notes = [lab for _, _, lab in ch], [0] * len(ch), []
    if collisions == "auto":
        labels, rows, notes = layout_chapter_labels(ch, start, total, g["bar_l"], g["bar_w"], g["chap_fs"])
        if notes:
            warnings.warn("hf_progress chapter labels: " + "; ".join(notes), stacklevel=2)
    data = dict(H=start, TOTAL=total, BAR_L=g["bar_l"], BAR_W=g["bar_w"], ACC2=acc2,
                CHAP=[[round(a, 3), round(b, 3), lab] for (a, b, _), lab in zip(ch, labels)])
    if any(rows):
        data["ROWS"] = rows
        data["ROW_DY"] = round(g["chap_fs"] * 1.3 * (1 if top else -1), 1)
    js = f"""(function () {{
const P = {json.dumps(data, ensure_ascii=False)};
const chaps = document.querySelector("#chaps"), bar = document.querySelector("#bar"), span = P.TOTAL - P.H;
const X = (t) => P.BAR_L + (t - P.H) / span * P.BAR_W;
P.CHAP.forEach(([s, e, label], i) => {{
  if (i) {{ const tk = document.createElement("div"); tk.className = "tick"; tk.style.left = (X(s) - P.BAR_L) + "px"; bar.appendChild(tk); }}
  const c = document.createElement("div"); c.className = "chap"; c.id = "chap" + i; c.textContent = label;
  c.style.left = ((X(s) + X(e)) / 2) + "px"; chaps.appendChild(c);
  if (P.ROWS && P.ROWS[i]) c.style.marginTop = (P.ROWS[i] * P.ROW_DY) + "px";
  {timeline_var}.to(c, {{ color: P.ACC2, fontWeight: 700, scale: 1.12, duration: 0.2 }}, s);
  {timeline_var}.to(c, {{ color: "rgba(255,255,255,0.9)", fontWeight: 400, scale: 1, duration: 0.2 }}, e);
}});
{timeline_var}.fromTo("#bar-fill", {{ scaleX: 0 }}, {{ scaleX: 1, duration: span, ease: "none" }}, P.H);
}})();
"""
    return {"css": css, "html": html, "js": js, "notes": notes}


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


# ---------------------------------------------------------------- themed blocks (vstudio.theme tokens)
def _T(theme=None):
    return TH.resolve(theme) if theme is not None else TH.current()


def progress_line(chapters, t, total=None, width=1080, x0=None, x1=None, scale=None, theme=None, on_video=False):
    """Hairline progress (theme ``progress``): track in rule colour (white 35% on video), fill in accent / ink,
    2 px gaps between chapters; label of the current chapter in ink2 when ``progress.label``."""
    T = _T(theme)
    pr = T["progress"]
    ch = _norm_chapters(chapters) if chapters else []
    total = float(total if total is not None else (ch[-1][1] if ch else 1.0)) or 1.0
    if not ch:
        ch = [(0.0, total, "")]
    s = scale if scale is not None else width / 1080.0
    x0 = _s(64, s) if x0 is None else x0
    x1 = width - _s(64, s) if x1 is None else x1
    th = max(2, _s(pr.get("height", 4), s))
    lab = bool(pr.get("label")) and any(c[2] for c in ch)
    fl = load_font(T["font_body"], _s(22, s))
    H = th + (_s(44, s) if lab else _s(4, s))
    im = Image.new("RGBA", (width, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    track = (255, 255, 255, 90) if on_video else TH.rgba(T, pr.get("track") or "rule")
    fill = TH.rgba(T, pr.get("fill") or "accent")
    gap = _s(4, s) if len(ch) > 1 else 0
    dur = sum(b - a for a, b, _ in ch) or 1.0
    avail = (x1 - x0) - gap * (len(ch) - 1)
    x, cur = x0, 0
    for i, (a, b, _l) in enumerate(ch):
        w = avail * (b - a) / dur
        d.rectangle([x, 0, x + w, th - 1], fill=track)
        if t >= a:
            p = 1.0 if t >= b else (t - a) / max(1e-6, b - a)
            if t < b:
                cur = i
            if p > 0:
                d.rectangle([x, 0, x + w * p, th - 1], fill=fill)
        x += w + gap
    if lab:
        d.text((x0, th + _s(12, s)), str(ch[cur][2]), font=fl, fill=TH.rgba(T, "ink2"))
    return im


def title_band(text, W, H, theme=None, color=None, band_color=None, sub=None, size=1.0, align=None, alpha=None):
    """Title band (RGBA W x H): theme paper, title in the theme's title face; a 【keyword】 is emphasised the
    theme's way (marker band / accent / underline). Explicit color / band_color win."""
    T = _T(theme)
    band = rgb(band_color) if band_color else TH.rgb(T, "paper")
    a = 255 if alpha is None else int(alpha)
    im = Image.new("RGBA", (int(W), int(H)), band + (a,))
    text = str(text or "")
    if not text.strip():
        return im
    sz = int(H * (0.36 if sub else 0.42) * float(size or 1.0))
    maxw = int(W * 0.86)
    while sz > 18:
        f = load_font(T["font_title"], sz)
        if text_width(text, f) <= maxw:
            break
        sz -= 2
    f = load_font(T["font_title"], sz)
    lay = emph_layer(text, f, T, surface="paper", fill=color, pad=int(sz * 0.2), line_gap=1.2)
    fs = load_font(T["font_body"], max(14, int(sz * 0.42))) if sub else None
    sl = emph_layer(str(sub), fs, T, surface="paper", fill=TH.rgba(T, "ink2"), pad=int(sz * 0.1)) if sub else None
    tot = lay.height + (sl.height if sl else 0)
    y = (H - tot) // 2
    al = align or T.get("title_align") or "center"
    xx = (lambda w: (W - w) // 2) if al == "center" else (lambda w: int(W * 0.07))
    im.alpha_composite(lay, (max(0, xx(lay.width)), max(0, y)))
    if sl:
        im.alpha_composite(sl, (max(0, xx(sl.width)), max(0, y + lay.height)))
    return im


def quote_block(lines, width, theme=None, card=False, speaker=None, scale=1.0, sweep=1.0, size=80, label=None):
    """Typographic quote (RGBA): ``lines`` = str or [str | (text, role)] with role main | sub. Weight contrast
    (main in the theme's quote face, sub in body ink2), a hanging opening quote in ink2 outside the text column,
    a short accent rule above, keywords the theme's way. card=True puts it on the theme card (for use over video).
    Classic themes keep the old big coloured mark."""
    T = _T(theme)
    if isinstance(lines, str):
        lines = [lines]
    rows = [(x, "main") if isinstance(x, str) else (x[0], x[1]) for x in lines]
    u = scale
    pad = _s(44, u) if card else 0
    hang = _s(size * 0.55, u)
    col_w = int(width - 2 * pad - hang)
    fm = load_font(T["font_quote"], _s(size, u))
    fsub = load_font(T["font_body"], _s(size * 0.46, u))
    fe = load_font(T["font_quote"], _s(size, u))
    blocks = []
    for txt, role in rows:
        if role == "sub":
            blocks.append((role, emph_layer(txt, fsub, T, surface="paper", fill=TH.rgba(T, "ink2"), max_w=col_w,
                                            line_gap=1.4, pad=0, sweep=sweep)))
        else:
            blocks.append((role, emph_layer(txt, fm, T, surface="paper", fill=TH.rgba(T, "card_ink" if card else "ink"),
                                            emph_font=fe, max_w=col_w, line_gap=1.22, pad=0, sweep=sweep)))
    fl = load_font(T["font_label"], _s(22, u))
    rule_h = max(2, _s(3, u))
    top = rule_h + _s(28, u)
    if label:
        top += sum(fl.getmetrics()) + _s(10, u)
    gaps = [(_s(26, u) if blocks[i][0] != blocks[i - 1][0] else _s(10, u)) for i in range(1, len(blocks))]
    sp_h = (sum(fsub.getmetrics()) + _s(22, u)) if speaker else 0
    H = pad * 2 + top + sum(b.height for _, b in blocks) + sum(gaps) + sp_h
    W = int(width)
    if card:
        im = rounded_rect((W, H), _s(T["radius"], u), TH.rgb(T, "card") + (int(255 * T["card_alpha"]),))
    else:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = pad + hang
    y = pad
    acc = TH.rgb(T, "accent")
    if T["quote"] == "glyph":                          # legacy: big coloured mark
        fq = load_font("cjk-bold", _s(size * 1.9, u))
        d.text((pad, y - _s(size * 0.35, u)), "“", font=fq, fill=acc + (255,))
    else:
        d.rectangle([x, y, x + _s(56, u), y + rule_h - 1], fill=acc + (255,))
    y += rule_h + _s(28, u)
    if label:
        draw_tracked(d, (x, y), label, fl, acc + (255,), T["label_track"])
        y += sum(fl.getmetrics()) + _s(10, u)
    first_main = True
    for i, (role, b) in enumerate(blocks):
        if i:
            y += gaps[i - 1]
        if role == "main" and first_main and T["quote"] != "glyph":
            # hanging punctuation: the opening mark sits in the margin, aligned to the first line's cap height
            fq = load_font(T["font_quote"], _s(size, u))
            qw = text_width("“", fq)
            d.text((x - qw - _s(size * 0.04, u), y - _s(size * 0.02, u)), "“", font=fq, fill=TH.rgba(T, "ink2", 0.55))
            first_main = False
        im.alpha_composite(b, (int(x), int(y)))
        y += b.height
    if speaker:
        y += _s(22, u)
        d.text((x, y), "— " + str(speaker), font=fsub, fill=TH.rgba(T, "ink2"))
    return im


def notes_chip(label, title, width, height=None, theme=None, scale=1.0, flush="left", alpha=None):
    """Section card (本段 / 记笔记 + one or two lines) for a corner of the video: theme card, small accent label
    with a dot, title in strong ink. flush left: square left edge (it runs off the frame), rounded right."""
    T = _T(theme)
    u = scale
    PX, PT = _s(26, u), _s(20, u)
    fl = load_font(T["font_label"], _s(22, u))
    lab = _label_text(label)
    inner = int(width - PX * 2)
    sz = _s(34, u)
    while sz > _s(22, u):
        ft = load_font(T["font_strong"], sz)
        ls = wrap(title, ft, inner, balance=True, max_lines=2)
        if all(text_width(x, ft) <= inner for x in ls):
            break
        sz -= 2
    lh = int(sz * 1.36)
    lab_h = sum(fl.getmetrics()) + _s(10, u) if lab else 0
    H = int(height or (PT * 2 + lab_h + lh * len(ls)))
    r = _s(T["radius"], u)
    a = int(255 * (T["card_alpha"] if alpha is None else alpha))
    im = Image.new("RGBA", (int(width), H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x0 = -r if flush == "left" else 0
    d.rounded_rectangle([x0, 0, width - 1, H - 1], r, fill=TH.rgb(T, "card") + (a,))
    y = (H - lab_h - lh * len(ls)) / 2
    acc = TH.rgb(T, "accent") + (255,)
    if lab:
        d.ellipse([PX, y + _s(7, u), PX + _s(8, u), y + _s(15, u)], fill=acc)
        draw_tracked(d, (PX + _s(16, u), y - _s(3, u)), lab, fl, acc, T["label_track"])
        y += lab_h
    for x in ls:
        draw_runs(d, (PX, y), x, ft, TH.rgba(T, "card_ink"), TH.rgba(T, "card_ink"))
        y += lh
    return im


def marker_line(text, size, theme=None, sweep=1.0, surface="paper", max_w=None, align="left", role=None):
    """One keyword line with a marker that sweeps in (sweep 0-1) behind the 【keyword】 (whole line if no markup)."""
    T = _T(theme)
    if "【" not in str(text) and "**" not in str(text):
        text = "【" + str(text) + "】"
    f = load_font(role or T["font_strong"], int(size))
    return emph_layer(text, f, T, surface=surface, sweep=sweep, max_w=max_w, align=align, emphasis="marker"
                      if surface == "paper" else None)


def chapter_rule(label, title=None, width=900, theme=None, progress=1.0, scale=1.0, surface="paper", index=None):
    """Thin chapter marker: a hairline that draws across (progress 0-1), a small tracked label above it (``02``
    and the chapter name), optional title below in strong ink. On video: white text with a soft shadow."""
    T = _T(theme)
    u = scale
    video = surface == "video"
    fl = load_font(T["font_label"], _s(24, u))
    ft = load_font(T["font_title"], _s(46, u))
    lab = (f"{int(index):02d}  " if index is not None else "") + _label_text(label)
    ink = (255, 255, 255, 255) if video else TH.rgba(T, "ink")
    acc = (255, 255, 255, 230) if video else TH.rgba(T, "accent")
    rule = (255, 255, 255, 150) if video else TH.rgba(T, "rule")
    lab_h = sum(fl.getmetrics())
    t_h = int(sum(ft.getmetrics()) * 1.1) if title else 0
    H = lab_h + _s(14, u) + max(2, _s(2, u)) + (_s(18, u) + t_h if title else 0) + _s(8, u)
    im = Image.new("RGBA", (int(width), H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    p = min(1.0, max(0.0, float(progress)))
    draw_tracked(d, (0, 0), lab, fl, acc, T["label_track"])
    y = lab_h + _s(14, u)
    rw = int(width * p)
    if rw > 0:
        d.rectangle([0, y, rw, y + max(2, _s(2, u)) - 1], fill=rule)
        d.rectangle([0, y, min(rw, _s(56, u)), y + max(2, _s(2, u)) - 1], fill=acc)
    if title:
        y += max(2, _s(2, u)) + _s(18, u)
        d.text((0, y), str(title), font=ft, fill=ink)
    if video:
        sh, pad = shadow(im, blur=_s(6, u), offset=(0, _s(2, u)), alpha=120)
        return sh
    return im


def counter_text(value, t, dur=0.9, decimals=None, prefix="", suffix=""):
    """The number a gentle counter shows ``t`` s in (ease-out over ``dur``; integer unless decimals)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    u = min(1.0, max(0.0, t / dur)) if dur > 0 else 1.0
    e = 1 - (1 - u) ** 3
    dec = decimals if decimals is not None else (0 if float(v).is_integer() else 1)
    x = v * e
    s = f"{x:,.{dec}f}"
    return f"{prefix}{s}{suffix}"


def counter(value, t=99.0, label=None, theme=None, size=120, dur=0.9, prefix="", suffix="", surface="paper",
            decimals=None):
    """Gentle number counter (RGBA): the figure counts up with ease-out (tabular width reserved for the final
    value, so nothing jitters), unit / label in small ink2 under it, a short accent rule."""
    T = _T(theme)
    video = surface == "video"
    fn = load_font(T["font_title"], int(size))
    fl = load_font(T["font_body"], max(14, int(size * 0.24)))
    final = counter_text(value, 99, dur, decimals, prefix, suffix)
    cur = counter_text(value, t, dur, decimals, prefix, suffix)
    W = int(max(text_width(final, fn), text_width(str(label or ""), fl))) + int(size * 0.2)
    asc, desc = fn.getmetrics()
    lab_h = sum(fl.getmetrics()) + int(size * 0.12) if label else 0
    H = asc + desc + int(size * 0.18) + lab_h + int(size * 0.1)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    ink = (255, 255, 255, 255) if video else TH.rgba(T, "ink")
    d.text((W - text_width(final, fn) - int(size * 0.1) + (text_width(final, fn) - text_width(cur, fn)), 0), cur,
           font=fn, fill=ink)
    y = asc + desc + int(size * 0.06)
    d.rectangle([int(size * 0.1), y, int(size * 0.1) + int(size * 0.4), y + max(2, int(size * 0.025))],
                fill=TH.rgba(T, "accent") if not video else (255, 255, 255, 220))
    if label:
        d.text((int(size * 0.1), y + int(size * 0.12)), str(label), font=fl,
               fill=(255, 255, 255, 220) if video else TH.rgba(T, "ink2"))
    if video:
        return shadow(im, blur=max(2, int(size * 0.05)), offset=(0, 2), alpha=110)[0]
    return im


def lower_third(name, role=None, theme=None, scale=1.0, width=None):
    """Name super: theme card, name in strong ink, role in ink2, a short accent rule at the left."""
    T = _T(theme)
    u = scale
    fn = load_font(T["font_strong"], _s(38, u))
    fr = load_font(T["font_body"], _s(26, u))
    PX, PY = _s(30, u), _s(20, u)
    w = int(width or (max(text_width(name, fn), text_width(role or "", fr)) + PX * 2 + _s(16, u)))
    h = PY * 2 + sum(fn.getmetrics()) + (sum(fr.getmetrics()) + _s(6, u) if role else 0)
    im = rounded_rect((w, h), _s(min(T["radius"], 12), u), TH.rgb(T, "card") + (int(255 * T["card_alpha"]),))
    d = ImageDraw.Draw(im)
    d.rectangle([PX, PY + _s(4, u), PX + _s(3, u), h - PY - _s(4, u)], fill=TH.rgba(T, "accent"))
    d.text((PX + _s(16, u), PY), name, font=fn, fill=TH.rgba(T, "card_ink"))
    if role:
        d.text((PX + _s(16, u), PY + sum(fn.getmetrics()) + _s(6, u)), role, font=fr, fill=TH.rgba(T, "ink2"))
    return im
