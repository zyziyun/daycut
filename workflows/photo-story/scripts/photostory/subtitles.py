"""Text layers: bilingual subtitles (**highlight**, balanced no-orphan wrapping), picture labels,
running header with section progress, chapter cards. All return float32 RGBA arrays."""
import math

import numpy as np
from PIL import Image, ImageDraw

from vstudio.subs import balanced_wrap, parse_highlight, strip_markup

from .ctx import font, font_for
from .util import has_cjk as has_cjk_text, layer, to_arr

_D = ImageDraw.Draw(Image.new("RGBA", (1, 1)))


def bwrap(d, text, f, maxw):
    """Pixel-measured balanced wrap (fewest lines, similar lengths, no 1-char orphan, latin words whole);
    **highlight** / 【】 markers are closed and reopened on every line."""
    return balanced_wrap(text, maxw, measure=lambda t: d.textlength(t, font=f))


def draw_runs(C, d, x, y, line, f, base, stroke):
    for p, hi in parse_highlight(line):
        d.text((x, y), p, font=f, fill=(C.GOLD if hi else base) + (255,), stroke_width=stroke,
               stroke_fill=(0, 0, 0, 210))
        x += d.textlength(p, font=f)


def make_sub(C, en, zh):
    """EN line(s) on top, 中文 below, centred in the subtitle band. Either may be empty."""
    zh = (zh or "").rstrip("，。、：；")
    en = en or ""
    if C.prof is not None:
        return _make_sub_fit(C, en, zh)
    fe = font_for(en, C.t(56), "sans-bold", "cjk-bold")
    fz = font("cjk-bold", C.t(66))
    lay = layer(C.W, C.SUB_H)
    d = ImageDraw.Draw(lay)
    m = C.t(140)
    le = bwrap(d, en, fe, C.W - m) if en else []
    lz = bwrap(d, zh, fz, C.W - m) if zh else []
    LE, LZ = C.t(70), C.t(82)
    G = C.t(14) if le and lz else 0
    stroke = max(1, round(2 * C.S + 0.3))
    y = (lay.height - (LE * len(le) + G + LZ * len(lz))) // 2 - C.t(6)
    for ln in le:
        draw_runs(C, d, (C.W - d.textlength(strip_markup(ln), font=fe)) / 2, y, ln, fe, C.pal["sub_en"], stroke)
        y += LE
    y += G
    for ln in lz:
        draw_runs(C, d, (C.W - d.textlength(strip_markup(ln), font=fz)) / 2, y, ln, fz, C.pal["sub_zh"], stroke)
        y += LZ
    return to_arr(lay)


def _sub_lines(C, d, en, zh, k, maxw, title=False):
    """Font sizes scaled by k -> (fe, fz, le, lz, LE, LZ, G, total height)."""
    if title:      # music mode: 中文 serif first, English italic below
        zs, es = C.ZH_SIZE * k, C.ZH_SIZE * k * 0.62
        fz = font_for(zh, zs, "cjk-serif", "cjk-serif")
        fe = font_for(en, es, "serif-italic", "cjk")
    else:
        zs, es = C.ZH_SIZE * k, C.ZH_SIZE * k * 56 / 66
        fz = font("cjk-bold", zs)
        fe = font_for(en, es, "sans-bold", "cjk-bold")
    le = bwrap(d, en, fe, maxw) if en else []
    lz = bwrap(d, zh, fz, maxw) if zh else []
    LE, LZ = int(round(es * 1.25)), int(round(zs * (1.5 if title else 1.24)))
    G = int(round(zs * (0.32 if title else 0.21))) if le and lz else 0
    return fe, fz, le, lz, LE, LZ, G, LE * len(le) + G + LZ * len(lz)


def _make_sub_fit(C, en, zh, title=False):
    """Platform layout: bilingual cue fitted into the caption box (width and band height); the 中文 size
    starts from the profile's caption size range and shrinks until both languages fit."""
    x0, _, x1, _ = C.CAP
    lay = layer(C.W, C.SUB_H)
    d = ImageDraw.Draw(lay)
    maxw = x1 - x0
    k = 1.0
    while True:
        fe, fz, le, lz, LE, LZ, G, tot = _sub_lines(C, d, en, zh, k, maxw, title)
        if (tot <= C.SUB_H * 0.94 and len(le) <= 2 and len(lz) <= 2) or k < 0.55:
            break
        k -= 0.05
    stroke = 0 if title else max(1, round(2 * C.S + 0.3))
    y = (lay.height - tot) // 2
    order = [(lz, fz, C.pal["sub_zh"], LZ), (le, fe, (214, 198, 168) if title else C.pal["sub_en"], LE)] if title \
        else [(le, fe, C.pal["sub_en"], LE), (lz, fz, C.pal["sub_zh"], LZ)]
    for j, (lines, f, col, lh) in enumerate(order):
        if j == 1:
            y += G
        for ln in lines:
            draw_runs(C, d, (x0 + x1 - d.textlength(strip_markup(ln), font=f)) / 2, y, ln, f, col, stroke)
            y += lh
    return to_arr(lay)


def make_title_text(C, en, zh):
    """MODE "music": a spec line as quiet title text (中文 serif + English italic), no speech-style stroke."""
    zh = (zh or "").rstrip("，。、：；")
    return _make_sub_fit(C, en or "", zh, title=True)


def sub_backdrop(C):
    """Soft dark gradient behind subtitles when they are overlaid on the picture (landscape)."""
    h = C.SUB_H if C.prof is None else C.H - C.SUB_Y0 + int(0.35 * C.SUB_H)   # platform: band to the bottom edge
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
    """Section names (current one highlighted) + per-section progress bars + bilingual title.
    Portrait: names + bars on top, title centred below. Landscape: title left, sections right."""

    def __init__(self, C):
        self.C = C
        hs = C.HS
        n = len(C.SECTIONS)
        self.oy = C.HDR_Y0
        x0, x1 = max(C.t(70), C.SAFE[0]), min(C.W - C.t(70), C.SAFE[2])
        self.tx0, self.tx1 = x0, x1
        self.wide = not C.portrait
        self.g = max(4, C.t(14))
        if self.wide:
            hc = C.HDR - self.oy
            self.title_w = self._title_w(hc)
            self.x0 = max(x0 + self.title_w + int(0.05 * C.W), int(x0 + (x1 - x0) * 0.42))
            self.sw = (x1 - self.x0 - self.g * (n - 1)) / n
            self.bar_y = self.oy + int(0.36 * hc)
            self.bar_h = max(3, int(0.04 * hc))
        else:
            self.x0 = x0
            self.sw = (x1 - self.x0 - self.g * (n - 1)) / n
            self.bar_y = self.oy + int(56 * hs)
            self.bar_h = max(3, int(7 * hs))
        self.layers = [self._make(k) for k in range(n)]

    def _title_fonts(self, hc):
        C = self.C
        fz = font_for(C.TITLE_ZH, 0.30 * hc, "cjk-serif", "cjk-serif") if C.TITLE_ZH else None
        fe = font_for(C.TITLE_EN, 0.15 * hc, "serif-italic", "cjk") if C.TITLE_EN else None
        return fz, fe

    def _title_w(self, hc):
        fz, fe = self._title_fonts(hc)
        w = max([_D.textlength(self.C.TITLE_ZH, font=fz) if fz else 0,
                 _D.textlength(self.C.TITLE_EN, font=fe) if fe else 0])
        return int(min(w, (self.tx1 - self.tx0) * 0.5))

    def _make(self, cur):
        C, hs, oy = self.C, self.C.HS, self.oy
        lay = layer(C.W, C.HDR)
        d = ImageDraw.Draw(lay)
        if self.wide:
            hc = C.HDR - oy
            for k, name in enumerate(C.SECTIONS):
                col = C.GOLD if k == cur else (150, 140, 125) if k < cur else (95, 90, 82)
                fl = _fit(name, "cjk", max(14, 0.17 * hc), self.sw)
                d.text((self.x0 + k * (self.sw + self.g), self.bar_y + self.bar_h + int(0.08 * hc)), name, font=fl,
                       fill=col + (255,))
            fz, fe = self._title_fonts(hc)
            mw = self.title_w
            y = oy + int(0.22 * hc)
            if fz:
                fz = _fit(C.TITLE_ZH, "cjk-serif", fz.size, mw)
                d.text((self.tx0, y), C.TITLE_ZH, font=fz, fill=C.pal["ink"] + (255,))
                y = d.textbbox((self.tx0, y), C.TITLE_ZH, font=fz)[3] + int(0.08 * hc)
            if fe:
                fe = _fit(C.TITLE_EN, "serif-italic", fe.size, mw) if not has_cjk_text(C.TITLE_EN) else fe
                d.text((self.tx0, y), C.TITLE_EN, font=fe, fill=(190, 172, 140, 255))
            return to_arr(lay)
        size = max(14, 28 * hs) if C.prof is None else max(28 * hs, 0.017 * C.H)   # platform: readable on a phone
        extra = 0 if C.prof is None else max(0.0, size - 28 * hs) * 1.2              # push the title below them
        for k, name in enumerate(C.SECTIONS):
            col = C.GOLD if k == cur else (150, 140, 125) if k < cur else (95, 90, 82)
            fl = _fit(name, "cjk", size, self.sw)
            d.text((self.x0 + k * (self.sw + self.g), oy + int(74 * hs)), name, font=fl, fill=col + (255,))
        y = oy + int(118 * hs + extra)
        if C.TITLE_ZH:
            ft = _fit(C.TITLE_ZH, "cjk-serif", 80 * hs - extra * 0.6, self.tx1 - self.tx0)
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
    fz = _fit(name, "cjk-serif", C.b(120), min(W * 0.9, (C.SAFE[2] - C.SAFE[0]) * 0.92))
    fe = font_for(name_en, C.b(54), "serif-italic", "cjk")
    num = f"{s:02d}"
    cy = H // 2
    d.text(((W - d.textlength(num, font=fn)) / 2, cy - C.b(270)), num, font=fn, fill=C.GOLD + (255,))
    d.line((W / 2 - C.b(90), cy - C.b(115), W / 2 + C.b(90), cy - C.b(115)), fill=C.GOLD + (255,), width=max(1, C.b(3)))
    d.text(((W - d.textlength(name, font=fz)) / 2, cy - C.b(90)), name, font=fz, fill=(250, 244, 232, 255))
    if name_en:
        d.text(((W - d.textlength(name_en, font=fe)) / 2, cy + C.b(60)), name_en, font=fe, fill=(214, 198, 168, 255))
    return to_arr(lay)
