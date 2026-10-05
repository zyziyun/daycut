"""Text layers: bilingual subtitles (**highlight**, balanced no-orphan wrapping), picture labels,
running header with section progress, chapter cards. All return float32 RGBA arrays."""
import math
import re

import numpy as np
from PIL import Image, ImageDraw

from .ctx import font, font_for
from .util import has_cjk, layer, to_arr

_D = ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def runs(text):
    """'a **b** c' -> [('a ', False), ('b', True), (' c', False)]"""
    return [(p, k % 2 == 1) for k, p in enumerate(text.split("**")) if p]


def wrap(d, text, f, maxw, cjk):
    """Greedy wrap that keeps **highlight** markers balanced on every line."""
    toks = list(text) if cjk else re.split(r"(\s+)", text)
    lines, cur = [], ""
    for tk in toks:
        test = cur + tk
        if d.textlength(test.replace("**", ""), font=f) > maxw and cur.strip():
            lines.append(cur.rstrip())
            cur = tk.lstrip()
        else:
            cur = test
    if cur.strip():
        lines.append(cur)
    out, open_ = [], False
    for ln in lines:
        if open_:
            ln = "**" + ln
        open_ = ln.count("**") % 2 == 1
        if open_:
            ln += "**"
        out.append(ln)
    return out


def bwrap(d, text, f, maxw, cjk):
    """Balanced wrap: same line count as greedy, but lines of similar length (no 1-word orphan)."""
    lines = wrap(d, text, f, maxw, cjk)
    if len(lines) < 2:
        return lines
    target = d.textlength(text.replace("**", ""), font=f) / len(lines)
    for slack in range(0, int(maxw - target), 12):
        cand = wrap(d, text, f, target + slack + 20, cjk)
        if len(cand) == len(lines):
            return cand
    return lines


def draw_runs(C, d, x, y, line, f, base, stroke):
    for p, hi in runs(line):
        d.text((x, y), p, font=f, fill=(C.GOLD if hi else base) + (255,), stroke_width=stroke,
               stroke_fill=(0, 0, 0, 210))
        x += d.textlength(p, font=f)


def make_sub(C, en, zh):
    """EN line(s) on top, 中文 below, centred in the subtitle band. Either may be empty."""
    zh = (zh or "").rstrip("，。、：；")
    en = en or ""
    fe = font_for(en, C.t(56), "sans-bold", "cjk-bold")
    fz = font("cjk-bold", C.t(66))
    lay = layer(C.W, C.SUB_H)
    d = ImageDraw.Draw(lay)
    m = C.t(140)
    le = bwrap(d, en, fe, C.W - m, has_cjk(en)) if en else []
    lz = bwrap(d, zh, fz, C.W - m, True) if zh else []
    LE, LZ = C.t(70), C.t(82)
    G = C.t(14) if le and lz else 0
    stroke = max(1, round(2 * C.S + 0.3))
    y = (lay.height - (LE * len(le) + G + LZ * len(lz))) // 2 - C.t(6)
    for ln in le:
        draw_runs(C, d, (C.W - d.textlength(ln.replace("**", ""), font=fe)) / 2, y, ln, fe, C.pal["sub_en"], stroke)
        y += LE
    y += G
    for ln in lz:
        draw_runs(C, d, (C.W - d.textlength(ln.replace("**", ""), font=fz)) / 2, y, ln, fz, C.pal["sub_zh"], stroke)
        y += LZ
    return to_arr(lay)


def sub_backdrop(C):
    """Soft dark gradient behind subtitles when they are overlaid on the picture (landscape)."""
    h = C.SUB_H
    a = (np.linspace(0, 1, h) ** 1.4 * 200).astype(np.float32)
    arr = np.zeros((h, C.W, 4), np.float32)
    arr[..., 3] = a[:, None]
    return arr


def make_label(C, text):
    """Rounded dark tag with an accent tick, bottom-left of the picture."""
    f = font_for(text, C.b(38), "sans", "cjk")
    tw = int(_D.textlength(text, font=f))
    h, pad = C.b(74), C.b(30)
    lay = layer(tw + 2 * pad, h)
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle((0, 0, tw + 2 * pad - 1, h - 1), C.b(14), fill=(18, 14, 10, 185))
    d.rectangle((0, int(h * 0.22), C.b(5), int(h * 0.78)), fill=C.GOLD + (255,))
    d.text((pad + C.b(2), h / 2), text, font=f, fill=(242, 234, 220, 255), anchor="lm")
    return to_arr(lay)


def make_tag(C, txt):
    f = font_for(txt, C.b(40), "sans-bold", "cjk-bold")
    tw = int(_D.textlength(txt, font=f))
    h, pad = C.b(76), C.b(30)
    lay = layer(tw + 2 * pad, h)
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle((0, 0, tw + 2 * pad - 1, h - 1), C.b(16), fill=(20, 14, 10, 200))
    d.text((pad, h / 2), txt, font=f, fill=C.GOLD + (255,), anchor="lm")
    return to_arr(lay)


def _fit(text, role, size, maxw):
    f = font_for(text, size, role, "cjk")
    while size > 10 and _D.textlength(text, font=f) > maxw:
        size -= 1
        f = font_for(text, size, role, "cjk")
    return f


class Header:
    """Section names (current one highlighted) + per-section progress bars + bilingual title."""

    def __init__(self, C):
        self.C = C
        hs = C.HS
        n = len(C.SECTIONS)
        self.x0, x1, self.g = C.t(70), C.W - C.t(70), max(4, C.t(14))
        self.sw = (x1 - self.x0 - self.g * (n - 1)) / n
        self.bar_y = int(56 * hs)
        self.bar_h = max(3, int(7 * hs))
        self.layers = [self._make(k) for k in range(n)]

    def _make(self, cur):
        C, hs = self.C, self.C.HS
        lay = layer(C.W, C.HDR)
        d = ImageDraw.Draw(lay)
        for k, name in enumerate(C.SECTIONS):
            col = C.GOLD if k == cur else (150, 140, 125) if k < cur else (95, 90, 82)
            fl = _fit(name, "cjk", max(14, 28 * hs), self.sw)
            d.text((self.x0 + k * (self.sw + self.g), int(74 * hs)), name, font=fl, fill=col + (255,))
        y = int(118 * hs)
        if C.TITLE_ZH:
            ft = _fit(C.TITLE_ZH, "cjk-serif", 80 * hs, C.W - 2 * self.x0)
            d.text((C.W / 2, y), C.TITLE_ZH, font=ft, fill=C.pal["ink"] + (255,), anchor="mt")
            y = d.textbbox((C.W / 2, y), C.TITLE_ZH, font=ft, anchor="mt")[3] + int(16 * hs)
        if C.TITLE_EN:
            fe = font_for(C.TITLE_EN, max(12, 34 * hs), "serif-italic", "cjk")
            d.text((C.W / 2, min(y, C.HDR - int(46 * hs))), C.TITLE_EN, font=fe, fill=(190, 172, 140, 255), anchor="mt")
        return to_arr(lay)

    def draw(self, frame, sec, gt, sec_bounds):
        from .util import paste_rgba
        paste_rgba(frame, self.layers[sec], 0, 0)
        y0, y1 = self.bar_y, self.bar_y + self.bar_h
        for j in range(len(self.C.SECTIONS)):
            sx = int(self.x0 + j * (self.sw + self.g))
            frame[y0:y1, sx:int(sx + self.sw)] = (70, 64, 56)
            if j < sec:
                fill = 1.0
            elif j == sec:
                fill = (gt - sec_bounds[j]) / max(1e-6, sec_bounds[j + 1] - sec_bounds[j])
            else:
                fill = 0
            if fill > 0:
                frame[y0:y1, sx:sx + int(self.sw * min(fill, 1))] = self.C.GOLD


def make_chapter(C, s):
    """Full-box chapter card: number, accent rule, 中文 + English section names over a dark band."""
    W, H = C.BOX_W, C.BOX_H
    lay = layer(W, H)
    d = ImageDraw.Draw(lay)
    d.rectangle((0, 0, W, H), fill=(8, 6, 4, 120))
    bh = min(H, C.b(560))
    band = Image.new("L", (W, bh), 0)
    bd = ImageDraw.Draw(band)
    for y in range(bh):
        bd.line((0, y, W, y), fill=int(150 * math.sin(math.pi * y / bh)))
    lay.paste(Image.new("RGBA", (W, bh), (8, 6, 4, 255)), (0, H // 2 - bh // 2), band)
    d = ImageDraw.Draw(lay)
    name, name_en = C.SECTIONS[s], C.SECTIONS_EN[s] if s < len(C.SECTIONS_EN) else ""
    fn = font("serif-italic", C.b(120))
    fz = _fit(name, "cjk-serif", C.b(120), W * 0.9)
    fe = font_for(name_en, C.b(54), "serif-italic", "cjk")
    num = f"{s:02d}"
    cy = H // 2
    d.text(((W - d.textlength(num, font=fn)) / 2, cy - C.b(270)), num, font=fn, fill=C.GOLD + (255,))
    d.line((W / 2 - C.b(90), cy - C.b(115), W / 2 + C.b(90), cy - C.b(115)), fill=C.GOLD + (255,), width=max(1, C.b(3)))
    d.text(((W - d.textlength(name, font=fz)) / 2, cy - C.b(90)), name, font=fz, fill=(250, 244, 232, 255))
    if name_en:
        d.text(((W - d.textlength(name_en, font=fe)) / 2, cy + C.b(60)), name_en, font=fe, fill=(214, 198, 168, 255))
    return to_arr(lay)
