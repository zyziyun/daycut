"""Per-shot overlays, applied after the shot frame and before the transition.
Coordinates are 0-1 fractions of the picture box.

    fx=("develop",)   photo develops from a pale warm wash
    fx=("shimmer",)   gold light sweep across the frame
    fx=("dust",)      floating dust motes
    fx=("prick",)     pounce-holes appear along the image's edges (cartoon pricking)
    fx=("sketch",)    pencil -> colour reveal (implemented in shots.ImageShot)
    hl=(cx,cy,rx,ry)  red-pen circle + dim outside      (hl_t = start as fraction of shot)
    tri=((x,y)*3)     composition triangle drawn on     (tri_label="Pyramid · 金字塔构图")
    loupe=[(x,y),..]  magnifier travelling along a path
    tl=year | (a,b)   timeline bar sweeping to a year / across a range (spec TIMELINE)
    count=(n,"EN","中") big number counting up with a caption
"""
import math
import random

import cv2
import numpy as np
from PIL import ImageDraw

from .ctx import font, font_for
from .subtitles import make_tag
from .util import ease, layer, paste_rgba, to_arr


def _cache(C):
    if not hasattr(C, "_ov"):
        C._ov = {}
    return C._ov


# ------------------------------------------------------------------ timeline bar
def _tl_geom(C):
    return C.b(34), int(C.BOX_W * 140 / 1620), C.BOX_W - int(C.BOX_W * 140 / 1620)


def _tl_range(C, tl):
    T = C.TIMELINE
    a = T.get("start", tl[0] if isinstance(tl, (tuple, list)) else tl - 10)
    b = T.get("end", tl[1] if isinstance(tl, (tuple, list)) else tl)
    return a, b


def _timeline_base(C, a, b):
    key = ("tl", a, b)
    cache = _cache(C)
    if key in cache:
        return cache[key]
    y0, x0, x1 = _tl_geom(C)
    lay = layer(C.BOX_W, C.b(230))
    d = ImageDraw.Draw(lay)
    d.rounded_rectangle((C.b(60), y0, C.BOX_W - C.b(60), y0 + C.b(180)), C.b(22), fill=(14, 11, 8, 190))
    y = y0 + C.b(120)
    d.line((x0, y, x1, y), fill=(200, 186, 160, 255), width=C.b(4))
    fs = font("sans", C.b(30))
    ticks = C.TIMELINE.get("ticks", [a, b])
    labels = C.TIMELINE.get("labels", [a, b])
    for yr in ticks:
        x = x0 + (yr - a) / max(1e-6, b - a) * (x1 - x0)
        r = C.b(7)
        d.ellipse((x - r, y - r, x + r, y + r), fill=(200, 186, 160, 255))
        if yr in labels:
            d.text((x, y + C.b(14)), str(yr), font=fs, fill=(200, 186, 160, 255), anchor="ma")
    cache[key] = to_arr(lay)
    return cache[key]


def _year_label(C, txt):
    key = ("yr", txt)
    cache = _cache(C)
    if key not in cache:
        lay = layer(C.b(260), C.b(80))
        ImageDraw.Draw(lay).text((C.b(130), C.b(40)), txt, font=font("serif-italic", C.b(64)), fill=C.GOLD + (255,), anchor="mm")
        cache[key] = to_arr(lay)
    return cache[key]


def _count_label(C, n, en, zh):
    key = ("cnt", n, en, zh)
    cache = _cache(C)
    if key not in cache:
        w, h = C.b(900), C.b(460)
        lay = layer(w, h)
        d = ImageDraw.Draw(lay)
        d.text((w / 2, C.b(190)), str(n), font=font("serif-italic", C.b(300)), fill=C.GOLD + (255,), anchor="mm",
               stroke_width=C.b(3), stroke_fill=(20, 14, 10, 220))
        cap = " · ".join(x for x in (en, zh) if x)
        if cap:
            d.text((w / 2, C.b(390)), cap, font=font_for(cap, C.b(52), "sans-bold", "cjk-bold"), fill=(250, 244, 230, 255),
                   anchor="mm", stroke_width=C.b(3), stroke_fill=(20, 14, 10, 220))
        cache[key] = to_arr(lay)
    return cache[key]


def _tag(C, txt):
    key = ("tag", txt)
    cache = _cache(C)
    if key not in cache:
        cache[key] = make_tag(C, txt)
    return cache[key]


def overlays(C, sh, f, lt):
    BW, BH = C.BOX_W, C.BOX_H
    dur = sh["end"] - sh["start"]
    fx = sh.get("fx", ())
    if "develop" in fx:
        q = ease(lt / (0.7 * dur))
        gray = f.mean(2, keepdims=True) * np.array([1.05, 0.97, 0.85], np.float32)
        f[:] = f * q + (gray * 0.35 + np.array([246, 240, 228], np.float32) * 0.65) * (1 - q)
    if "shimmer" in fx:
        pos = -0.3 + 1.6 * ((lt - 0.25 * dur) / 1.3)
        if -0.3 < pos < 1.3:
            m = np.exp(-((C.DIAG - pos) / 0.05) ** 2)[..., None]
            f += m * np.array([110, 90, 50], np.float32)
    if "tri" in sh:
        q = ease((lt - 0.2 * dur) / (0.45 * dur))
        pts = [(int(x * BW), int(y * BH)) for x, y in sh["tri"]]
        pts.append(pts[0])
        segs = list(zip(pts[:-1], pts[1:]))
        total = q * len(segs)
        for i, (a, b) in enumerate(segs):
            s = min(1, max(0, total - i))
            if s > 0:
                e = (int(a[0] + (b[0] - a[0]) * s), int(a[1] + (b[1] - a[1]) * s))
                cv2.line(f, a, e, C.GOLD, C.b(8), cv2.LINE_AA)
        if q > 0.95:
            tag = _tag(C, sh.get("tri_label", "Pyramid · 金字塔构图"))
            paste_rgba(f, tag, int(np.clip(pts[0][0] - tag.shape[1] / 2, C.b(20), BW - tag.shape[1] - C.b(20))),
                       max(C.b(20), pts[0][1] - C.b(110)), min(1, (q - 0.95) * 20))
    if "prick" in fx:
        if "_pts" not in sh:
            g = cv2.cvtColor(np.clip(f, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
            e = cv2.Canny(cv2.GaussianBlur(g, (0, 0), 3.0), 35, 90)
            m = int(0.06 * BW)
            e[:m] = 0; e[-m:] = 0; e[:, :m] = 0; e[:, -m:] = 0
            ys, xs = np.nonzero(e)
            idx = np.random.default_rng(1).permutation(len(xs))[:sh.get("prick_n", 1500)]
            order = np.argsort(xs[idx] + ys[idx] * 0.3)
            sh["_pts"] = list(zip(xs[idx][order], ys[idx][order]))
        q = ease((lt - 0.12 * dur) / (0.55 * dur))
        for x, y in sh["_pts"][:int(len(sh["_pts"]) * q)]:
            cv2.circle(f, (int(x), int(y)), C.b(6), (255, 236, 190), -1, cv2.LINE_AA)
            cv2.circle(f, (int(x), int(y)), C.b(3), (25, 18, 12), -1, cv2.LINE_AA)
    if "hl" in sh:
        cx, cy, rx, ry = sh["hl"]
        cx, cy, rx, ry = cx * BW, cy * BH, rx * BW, ry * BH
        q = ease((lt - sh.get("hl_t", 0.3) * dur) / 0.8)
        if q > 0:
            d = ((C.XX - cx) / rx) ** 2 + ((C.YY - cy) / ry) ** 2
            inside = np.clip((1.25 - d) / 0.35, 0, 1)[..., None]
            f *= 1 - q * 0.5 * (1 - inside)
            ang = int(395 * q)
            red = C.pal["mark"]
            cv2.ellipse(f, (int(cx), int(cy)), (int(rx * 1.05), int(ry * 1.05)), -8, -100, -100 + ang, red, C.b(10), cv2.LINE_AA)
            cv2.ellipse(f, (int(cx + C.b(5)), int(cy - C.b(4))), (int(rx * 1.1), int(ry * 1.0)), -4, -96,
                        -96 + int(ang * 0.92), red, C.b(4), cv2.LINE_AA)
    if "loupe" in sh:
        path = list(sh["loupe"])
        if len(path) == 1:
            path = path * 2
        u = ease((lt - 0.15 * dur) / (0.75 * dur))
        seg = u * (len(path) - 1)
        i = min(int(seg), len(path) - 2)
        s = seg - i
        px = (path[i][0] + (path[i + 1][0] - path[i][0]) * s) * BW
        py = (path[i][1] + (path[i + 1][1] - path[i][1]) * s) * BH
        a = min(1, (lt - 0.05 * dur) / 0.4)
        if a > 0:
            R, mag = C.b(250), sh.get("loupe_mag", 2.3)
            r = R / mag
            x0, y0 = int(np.clip(px - r, 0, BW - 2 * r)), int(np.clip(py - r, 0, BH - 2 * r))
            crop = cv2.resize(f[y0:y0 + int(2 * r), x0:x0 + int(2 * r)], (2 * R, 2 * R), interpolation=cv2.INTER_CUBIC)
            yy, xx = np.mgrid[0:2 * R, 0:2 * R]
            m = (np.clip(R - np.sqrt((xx - R) ** 2 + (yy - R) ** 2), 0, 1) * a)[..., None]
            cx, cy = int(np.clip(px, R, BW - R)), int(np.clip(py, R, BH - R))
            cv2.line(f, (cx + int(R * 0.7), cy + int(R * 0.7)), (cx + int(R * 1.35), cy + int(R * 1.35)),
                     (60, 40, 26), C.b(34), cv2.LINE_AA)
            cv2.circle(f, (cx + C.b(10), cy + C.b(14)), R + C.b(8), (0, 0, 0), C.b(26), cv2.LINE_AA)
            reg = f[cy - R:cy + R, cx - R:cx + R]
            reg[:] = reg * (1 - m) + crop * m
            cv2.circle(f, (cx, cy), R, C.GOLD, C.b(12), cv2.LINE_AA)
            cv2.circle(f, (cx - C.b(70), cy - C.b(80)), C.b(40), (255, 255, 255), C.b(2), cv2.LINE_AA)
    if "tl" in sh:
        tl = sh["tl"]
        A, B = _tl_range(C, tl)
        a_yr, b_yr = (A, tl) if not isinstance(tl, (tuple, list)) else tl
        q = ease((lt - 0.25) / 1.1)
        yr = a_yr + (b_yr - a_yr) * q
        alpha = min(1, lt / 0.3, (dur - lt) / 0.3)
        if alpha > 0:
            paste_rgba(f, _timeline_base(C, A, B), 0, 0, alpha)
            y0, x0, x1 = _tl_geom(C)
            x = x0 + (yr - A) / max(1e-6, B - A) * (x1 - x0)
            y = y0 + C.b(120)
            cv2.line(f, (x0, y), (int(x), y), C.GOLD, C.b(6), cv2.LINE_AA)
            cv2.circle(f, (int(x), y), C.b(16), C.GOLD, -1, cv2.LINE_AA)
            fmt = C.TIMELINE.get("format", "{:d}")
            paste_rgba(f, _year_label(C, fmt.format(int(round(yr)))), int(x) - C.b(130), y - C.b(100), alpha)
    if "count" in sh:
        n, en, zh = (tuple(sh["count"]) + ("", ""))[:3]
        q = ease((lt - 0.2) / 1.0)
        a = min(1, (lt - 0.1) / 0.3, (dur - lt) / 0.3)
        if a > 0:
            d = ((C.XX - BW / 2) / (BW * 0.45)) ** 2 + ((C.YY - BH * 0.62) / (BH * 0.22)) ** 2
            f *= 1 - a * 0.45 * np.clip(1.2 - d, 0, 1)[..., None]
            lab = _count_label(C, int(round(n * q)), en, zh)
            paste_rgba(f, lab, BW // 2 - lab.shape[1] // 2, int(BH * 0.62) - C.b(230), a)
    if "dust" in fx:
        r = random.Random(sum(map(ord, sh["src"])) % 1000)
        for _ in range(55):
            x0, y0, sp, ph, sz = r.random() * BW, r.random() * BH, r.uniform(15, 45), r.random() * 6, r.uniform(1.5, 4.5)
            x = (x0 + 30 * C.bs * math.sin(lt * 0.7 + ph)) % BW
            y = (y0 - sp * C.bs * lt) % BH
            b = 0.5 + 0.5 * math.sin(lt * 2 + ph)
            cv2.circle(f, (int(x), int(y)), max(1, int(sz * C.bs)), (255 * b, 238 * b, 205 * b), -1, cv2.LINE_AA)
    return f
