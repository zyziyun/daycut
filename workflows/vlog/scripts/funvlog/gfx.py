"""Text and graphics for the fun travel vlog, drawn per frame on BGR numpy frames (PIL layers via vstudio.draw).

Elements (all placed inside platform.safe_box; captions are vstudio.export.caption_overlay in caption_box):
  TitlePop     scale-bounce (out-back 0.3 -> 1), holds >= 1.2 s (A1), shrinks out
  LocationTag  pin icon + place name on a dark pill, slides in from the left edge of the safe box
  DayStamp     "DAY n" rubber stamp (overlays.stamp) slammed in 1.8x -> 1x, top-right
  DateStamp    camcorder date/time (mono, amber) just above the caption band
  WordPop      one kinetic word on a beat: 0.25 -> 1.15 -> 1, holds, pops out (no emoji)
  MapCard      stylised route card: dots from lat/lon (equirectangular) or xy, arcs drawn progressively,
               pins pop as the path reaches them (no network tiles)
  EndCard      background dims, main line pops, sub line fades in, holds to the end
Every element knows its ``box`` (final on-screen rect, canvas px) so tests and reports can check placement.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
import math

import numpy as np
from PIL import Image, ImageDraw

from vstudio import draw as D
from vstudio import overlays as O


# ----------------------------------------------------------------------------- easing
def clamp01(u):
    return max(0.0, min(1.0, float(u)))


def out_cubic(u):
    u = clamp01(u)
    return 1 - (1 - u) ** 3


def in_cubic(u):
    return clamp01(u) ** 3


def out_back(u, s=1.70158):
    u = clamp01(u) - 1
    return u * u * ((s + 1) * u + s) + 1


def _rgba_arr(im):
    return np.asarray(im.convert("RGBA"))


def _scaled(arr, s):
    if abs(s - 1.0) < 1e-3:
        return arr
    import cv2
    h, w = arr.shape[:2]
    return cv2.resize(arr, (max(1, int(w * s)), max(1, int(h * s))),
                      interpolation=cv2.INTER_LINEAR if s > 1 else cv2.INTER_AREA)


def _paste(img, arr, cx, cy, scale=1.0, alpha=1.0):
    a = _scaled(arr, scale)
    D.alpha_paste(img, a, (cx - a.shape[1] / 2, cy - a.shape[0] / 2), opacity=alpha, bgr=True)


class Element:
    kind = "element"

    def __init__(self, t0, t1):
        self.t0, self.t1 = float(t0), float(t1)
        self.box = None

    def active(self, t):
        return self.t0 <= t < self.t1

    def info(self):
        d = dict(kind=self.kind, t0=round(self.t0, 3), t1=round(self.t1, 3),
                 box=[int(v) for v in self.box] if self.box else None)
        if getattr(self, "note", None):
            d["note"] = self.note
        return d

    def move(self, dy):
        """Shift the element vertically by dy canvas px (layout collision resolution)."""
        raise NotImplementedError(self.kind)

    def _shift_box(self, dy):
        x0, y0, x1, y1 = self.box
        self.box = (x0, y0 + dy, x1, y1 + dy)


CORNER_KINDS = ("location", "day", "date")


def _overlap(a, b, pad=0.0):
    return a[0] < b[2] + pad and b[0] < a[2] + pad and a[1] < b[3] + pad and b[1] < a[3] + pad


def resolve_collisions(els, g, gap=None):
    """Corner elements (location tag, DAY stamp, date stamp) never overlap on screen while both are visible,
    whatever their kinds. Settled in order location -> day -> date (then by start time); a later one that
    collides is moved below the obstacle (or above it when below would leave the safe box); if neither fits,
    it waits until the obstacle has left. Returns the list of adjustments (also in each element's note)."""
    gap = int(12 * g.unit) if gap is None else gap
    prio = {k: i for i, k in enumerate(CORNER_KINDS)}
    todo = sorted([e for e in els if e.kind in CORNER_KINDS and e.box], key=lambda e: (prio[e.kind], e.t0))
    placed, moves = [], []
    sx0, sy0, sx1, sy1 = g.safe
    for e in todo:
        for _ in range(8):
            hit = next((o for o in placed if o.t0 < e.t1 and e.t0 < o.t1 and _overlap(o.box, e.box, gap / 2)), None)
            if hit is None:
                break
            h = e.box[3] - e.box[1]
            below = hit.box[3] + gap - e.box[1]
            above = hit.box[1] - gap - e.box[3]
            if e.box[3] + below <= sy1:
                dy = below
            elif e.box[1] + above >= sy0:
                dy = above
            else:
                dy = None
            if dy is not None and h > 0:
                e.move(dy)
                moves.append(dict(kind=e.kind, dy=round(dy), because=hit.kind))
                e.note = f"moved {round(dy):+d}px clear of {hit.kind}"
            else:                                         # no room: wait for the obstacle to leave
                d = hit.t1 + 0.05 - e.t0
                e.t0 += d
                e.t1 += d
                moves.append(dict(kind=e.kind, dt=round(d, 3), because=hit.kind))
                e.note = f"delayed {d:.2f}s after {hit.kind}"
        placed.append(e)
    return moves


class Geometry:
    """Canvas, safe box, caption box and a size unit derived from a platform profile."""

    def __init__(self, prof, safe, caption):
        self.W, self.H = prof.w, prof.h
        self.safe = safe
        self.caption = caption
        self.vertical = self.H > self.W
        self.unit = min(self.W, self.H) / 1080.0          # 1.0 on 1080-wide vertical / 1080-tall horizontal
        self.brand = D.brand()

    @property
    def sw(self):
        return self.safe[2] - self.safe[0]

    @property
    def sh(self):
        return self.safe[3] - self.safe[1]


# ----------------------------------------------------------------------------- title
class TitlePop(Element):
    kind = "title"

    def __init__(self, g, text, t0, hold=1.6, sub=None):
        super().__init__(t0, t0 + 0.35 + hold + 0.2)
        self.g, self.hold = g, hold
        size = int(g.H * (0.075 if g.vertical else 0.1))
        f = D.fit_font(text, "cjk-bold", size, g.sw * 0.92, min_size=int(size * 0.5))
        acc = g.brand["accent"]
        main = D.text_layer(text, f, fill=(255, 255, 255, 255), stroke=max(4, f.size // 12),
                            stroke_fill=acc + (255,), shadow_alpha=160, pad=10)
        layers = [main]
        if sub:
            fs = D.fit_font(sub, "cjk-bold", int(f.size * 0.42), g.sw * 0.8, min_size=18)
            asc, desc = fs.getmetrics()
            w, h = int(D.text_width(sub, fs)) + int(fs.size * 1.2), asc + desc + int(fs.size * 0.5)
            pill = D.rounded_rect((w, h), h // 2, g.brand["highlight"] + (245,))
            ImageDraw.Draw(pill).text((w / 2, h / 2), sub, font=fs, fill=(20, 20, 24, 255), anchor="mm")
            layers.append(pill)
        W = max(l.width for l in layers)
        Ht = sum(l.height for l in layers) + (int(f.size * 0.1) if sub else 0)
        im = Image.new("RGBA", (W, Ht), (0, 0, 0, 0))
        y = 0
        for l in layers:
            im.alpha_composite(l, ((W - l.width) // 2, y))
            y += l.height + int(f.size * 0.1)
        self.arr = _rgba_arr(im)
        self.cx = (g.safe[0] + g.safe[2]) / 2
        self.cy = g.safe[1] + g.sh * (0.36 if g.vertical else 0.42)
        h, w = self.arr.shape[:2]
        self.box = (self.cx - w / 2, self.cy - h / 2, self.cx + w / 2, self.cy + h / 2)

    def draw(self, img, t):
        u = t - self.t0
        if u < 0.35:
            s, a = 0.3 + 0.7 * out_back(u / 0.35, 2.2), clamp01(u / 0.12)
        elif u < 0.35 + self.hold:
            s, a = 1.0, 1.0
        else:
            v = clamp01((u - 0.35 - self.hold) / 0.2)
            s, a = 1.0 - 0.15 * in_cubic(v), 1.0 - v
        _paste(img, self.arr, self.cx, self.cy, s, a)


# ----------------------------------------------------------------------------- location tag
def pin_icon(size, color):
    s = int(size)
    im = Image.new("RGBA", (s, int(s * 1.35)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = s / 2
    d.ellipse([0, 0, s - 1, s - 1], fill=color + (255,))
    d.polygon([(s * 0.14, r * 1.35), (s * 0.86, r * 1.35), (s / 2, s * 1.33)], fill=color + (255,))
    d.ellipse([s * 0.3, s * 0.3, s * 0.7, s * 0.7], fill=(255, 255, 255, 255))
    return im


class LocationTag(Element):
    kind = "location"

    def __init__(self, g, place, t0, hold=1.8):
        super().__init__(t0, t0 + 0.35 + hold + 0.25)
        self.g, self.hold = g, hold
        size = int(g.H * (0.04 if g.vertical else 0.05))
        f = D.fit_font(place, "cjk-bold", size, g.sw * 0.7, min_size=int(size * 0.6))
        asc, desc = f.getmetrics()
        pin = pin_icon(f.size * 0.85, g.brand["accent"])
        pad = int(f.size * 0.45)
        tw = int(D.text_width(place, f))
        h = max(asc + desc, pin.height) + pad
        w = pad + pin.width + int(pad * 0.6) + tw + pad + int(pad * 0.4)
        pill = D.rounded_rect((w, h), h // 2, (14, 16, 22, 215))
        pill.alpha_composite(pin, (pad, (h - pin.height) // 2))
        ImageDraw.Draw(pill).text((pad + pin.width + int(pad * 0.6), h / 2), place, font=f,
                                  fill=(255, 255, 255, 255), anchor="lm")
        im, p = D.shadow(pill, blur=8, offset=(0, 4), alpha=110)
        self.arr, self.pad = _rgba_arr(im), p
        self.x_end = g.safe[0] + int(12 * g.unit) - p
        self.y = g.safe[1] + int(24 * g.unit) - p
        self.box = (self.x_end + p, self.y + p, self.x_end + p + w, self.y + p + h)

    def move(self, dy):
        self.y += dy
        self._shift_box(dy)

    def draw(self, img, t):
        u = t - self.t0
        w = self.arr.shape[1]
        if u < 0.35:
            x = self.x_end - (1 - out_cubic(u / 0.35)) * (w + self.x_end + 10)
        elif u < 0.35 + self.hold:
            x = self.x_end
        else:
            x = self.x_end - in_cubic((u - 0.35 - self.hold) / 0.25) * (w + self.x_end + 10)
        D.alpha_paste(img, self.arr, (x, self.y), bgr=True)


# ----------------------------------------------------------------------------- day stamp
class DayStamp(Element):
    kind = "day"

    def __init__(self, g, label, t0, hold=1.8):
        super().__init__(t0, t0 + hold + 0.2)
        self.g, self.hold = g, hold
        size = int(g.H * (0.042 if g.vertical else 0.055))
        st = O.stamp(label, angle=-8, size=size)
        self.arr = _rgba_arr(st)
        h, w = self.arr.shape[:2]
        self.cx = g.safe[2] - int(16 * g.unit) - w / 2
        self.cy = g.safe[1] + int(24 * g.unit) + h / 2
        self.box = (self.cx - w / 2, self.cy - h / 2, self.cx + w / 2, self.cy + h / 2)

    def move(self, dy):
        self.cy += dy
        self._shift_box(dy)

    def draw(self, img, t):
        u = t - self.t0
        if u < 0.12:
            s, a = 1.8 - 0.8 * in_cubic(u / 0.12), clamp01(u / 0.06)
        elif u < self.hold:
            s, a = 1.0, 1.0
        else:
            s, a = 1.0, 1.0 - clamp01((u - self.hold) / 0.2)
        _paste(img, self.arr, self.cx, self.cy, s, a)


# ----------------------------------------------------------------------------- date stamp
class DateStamp(Element):
    kind = "date"

    def __init__(self, g, text, t0, t1):
        super().__init__(t0, max(t1, t0 + 1.0))
        size = int(g.H * (0.026 if g.vertical else 0.034))
        f = D.load_font("mono-bold", size)
        L = D.text_layer(text, f, fill=(255, 176, 56, 255), stroke=2, stroke_fill=(40, 20, 0, 200),
                         shadow_alpha=150, pad=6)
        self.arr = _rgba_arr(L)
        h, w = self.arr.shape[:2]
        x0 = g.safe[0] + int(12 * g.unit)
        y1 = min(g.caption[1], g.safe[3]) - int(10 * g.unit)
        self.xy = (x0, y1 - h)
        self.box = (x0, y1 - h, x0 + w, y1)

    def move(self, dy):
        self.xy = (self.xy[0], self.xy[1] + dy)
        self._shift_box(dy)

    def draw(self, img, t):
        u = t - self.t0
        a = clamp01(u / 0.1) * clamp01((self.t1 - t) / 0.1)
        D.alpha_paste(img, self.arr, self.xy, opacity=a, bgr=True)


# ----------------------------------------------------------------------------- word pop
class WordPop(Element):
    kind = "word"

    def __init__(self, g, word, t0, hold, k=0):
        super().__init__(t0, t0 + hold + 0.1)
        self.hold = hold
        size = int(g.H * (0.085 if g.vertical else 0.12))
        f = D.fit_font(word, "cjk-bold", size, g.sw * 0.85, min_size=int(size * 0.5))
        L = D.text_layer(word, f, fill=g.brand["highlight"] + (255,), stroke=max(4, f.size // 10),
                         stroke_fill=(16, 16, 20, 255), shadow_alpha=170, pad=10)
        L = L.rotate(4 if k % 2 == 0 else -4, expand=True, resample=Image.BICUBIC)
        self.arr = _rgba_arr(L)
        h, w = self.arr.shape[:2]
        self.cx = (g.safe[0] + g.safe[2]) / 2
        self.cy = g.safe[1] + g.sh * 0.5
        self.box = (self.cx - w / 2, self.cy - h / 2, self.cx + w / 2, self.cy + h / 2)

    def draw(self, img, t):
        u = t - self.t0
        if u < 0.08:
            s = 0.25 + 0.9 * out_cubic(u / 0.08)
            a = 1.0
        elif u < 0.16:
            s, a = 1.15 - 0.15 * out_cubic((u - 0.08) / 0.08), 1.0
        elif u < self.hold:
            s, a = 1.0, 1.0
        else:
            v = clamp01((u - self.hold) / 0.1)
            s, a = 1.0 + 0.3 * v, 1.0 - v
        _paste(img, self.arr, self.cx, self.cy, s, a)


# ----------------------------------------------------------------------------- map route card
def project(places):
    """[{name, lat, lon} | {name, xy: [0..1, 0..1]}] -> [(name, x, y)] in 0..1 (y down)."""
    if all("xy" in p for p in places):
        return [(p["name"], float(p["xy"][0]), float(p["xy"][1])) for p in places]
    lat = np.array([float(p["lat"]) for p in places])
    lon = np.array([float(p["lon"]) for p in places])
    k = math.cos(math.radians(float(lat.mean())))
    xs, ys = lon * k, -lat
    w, h = max(xs.max() - xs.min(), 1e-6), max(ys.max() - ys.min(), 1e-6)
    s = max(w, h)
    cx, cy = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
    return [(p["name"], 0.5 + (x - cx) / s, 0.5 + (y - cy) / s) for p, x, y in zip(places, xs, ys)]


def _bezier(p0, p1, bend, n=48):
    (x0, y0), (x1, y1) = p0, p1
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    cx, cy = mx - dy / L * bend * L, my + dx / L * bend * L
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * np.array([x0, y0]) + 2 * (1 - t) * t * np.array([cx, cy]) + t ** 2 * np.array([x1, y1])


class MapCard(Element):
    kind = "map"

    def info(self):
        d = super().info()
        d["labels"] = [dict(name=n, box=[int(v) for v in b]) for (n, _, _), b in zip(self.pts, self.label_boxes)]
        return d

    def __init__(self, g, places, t0, t1, title=None):
        super().__init__(t0, t1)
        self.g = g
        if g.vertical:
            cw = int(g.sw * 0.9)
            ch = int(cw * 0.78)
        else:
            ch = int(g.sh * 0.68)
            cw = int(ch * 1.35)
        self.cw, self.ch = cw, ch
        self.cx = (g.safe[0] + g.safe[2]) / 2
        self.cy = g.safe[1] + g.sh * (0.42 if g.vertical else 0.5)
        self.box = (self.cx - cw / 2, self.cy - ch / 2, self.cx + cw / 2, self.cy + ch / 2)
        B = g.brand
        base = D.rounded_rect((cw, ch), int(28 * g.unit), B["ground"] + (248,))
        d = ImageDraw.Draw(base)
        step = int(48 * g.unit)
        for x in range(step, cw, step):
            d.line([(x, 8), (x, ch - 8)], fill=(255, 255, 255, 18), width=1)
        for y in range(step, ch, step):
            d.line([(8, y), (cw - 8, y)], fill=(255, 255, 255, 18), width=1)
        fs = D.load_font("cjk-bold", int(30 * g.unit))
        d.text((int(28 * g.unit), int(22 * g.unit)), title or "ROUTE", font=fs, fill=B["highlight"] + (255,))
        self.base = base
        pad = 0.16
        pts = project(places)
        iw, ih = cw * (1 - 2 * pad), ch * (1 - 2 * pad) - 20 * g.unit
        s = min(iw, ih)
        ox, oy = (cw - s) / 2, (ch - s) / 2 + 14 * g.unit
        self.pts = [(n, ox + x * s, oy + y * s) for n, x, y in pts]
        segs = [_bezier(a[1:], b[1:], 0.22 * (1 if i % 2 == 0 else -1))
                for i, (a, b) in enumerate(zip(self.pts, self.pts[1:]))]
        self.path = np.concatenate(segs) if segs else np.array([[p[1], p[2]] for p in self.pts])
        seglen = np.r_[0, np.cumsum(np.hypot(*np.diff(self.path, axis=0).T))] if len(self.path) > 1 else np.zeros(1)
        self.cum = seglen
        self.total = float(seglen[-1]) or 1.0
        # arrival fraction of each place along the path
        self.arrive = [0.0] + [float(self.cum[min(len(self.cum) - 1, 48 * (i + 1) - 1)]) / self.total
                               for i in range(len(self.pts) - 1)]
        self.font = D.load_font("cjk-bold", int(30 * g.unit))
        self.labels = self._place_labels(int(14 * g.unit))
        dur = t1 - t0
        # the route finishes >= 1.25 s before the card leaves, so the last pin + label hold >= 1 s (A1)
        self.draw_from, self.draw_to = 0.35, max(0.6, min(dur * 0.7, dur - 1.25))
        self.pin_times = [t0 + self.draw_from + a * (self.draw_to - self.draw_from) for a in self.arrive]
        self._cache = {}

    def _place_labels(self, r):
        """Label top-left per place. Every label is placed (never dropped): candidates below, above, right,
        left, then the diagonals, then the same at 2x distance; the first one clear of the pins, the labels
        already placed and the route line wins; if none is clear, the one with the least overlap (labels and
        pins weigh far more than the line). Always inside the card."""
        asc, desc = self.font.getmetrics()
        lh = asc + desc
        pins = [(x - r, y - r, x + r, y + r) for _, x, y in self.pts]
        path = self.path if len(self.path) else np.zeros((0, 2))
        placed, out = [], []

        def area(b, o):
            w = min(b[2], o[2]) - max(b[0], o[0])
            h = min(b[3], o[3]) - max(b[1], o[1])
            return w * h if w > 0 and h > 0 else 0.0

        for name, x, y in self.pts:
            tw = D.text_width(name, self.font)
            cands = []
            for k in (1.0, 2.0):
                g_ = (r + 4) * k
                cands += [(x - tw / 2, y + g_), (x - tw / 2, y - g_ - lh), (x + r * k + 6, y - lh / 2),
                          (x - r * k - 6 - tw, y - lh / 2), (x + g_, y + g_ * 0.6), (x - g_ - tw, y + g_ * 0.6),
                          (x + g_, y - g_ * 0.6 - lh), (x - g_ - tw, y - g_ * 0.6 - lh)]
            best, best_cost = None, None
            for cx, cy in cands:
                cx = min(max(cx, 10), self.cw - tw - 10)
                cy = min(max(cy, int(22 * self.g.unit) + lh + 4), self.ch - lh - 10)   # below the title row
                b = (cx, cy, cx + tw, cy + lh)
                hard = sum(area(b, o) for o in pins + placed)
                line = int(((path[:, 0] > b[0]) & (path[:, 0] < b[2]) & (path[:, 1] > b[1]) & (path[:, 1] < b[3])).sum())
                cost = hard * 100.0 + line
                if best_cost is None or cost < best_cost - 1e-9:
                    best, best_cost = (cx, cy), cost
                if cost == 0:
                    break
            placed.append((best[0], best[1], best[0] + tw, best[1] + lh))
            out.append(best)
        self.label_boxes = placed
        return out

    def _frame(self, p):
        key = round(p, 3)
        if key in self._cache:
            return self._cache[key]
        p = key                                               # draw exactly what the cache key says
        g, B = self.g, self.g.brand
        im = self.base.copy()
        d = ImageDraw.Draw(im)
        upto = p * self.total
        n = int(np.searchsorted(self.cum, upto, side="right"))
        pts = [tuple(v) for v in self.path[:max(1, n)]]
        lw = max(3, int(7 * g.unit))
        if len(pts) > 1:
            d.line(pts, fill=(255, 255, 255, 235), width=lw + 4, joint="curve")
            d.line(pts, fill=B["accent"] + (255,), width=lw, joint="curve")
        r = int(14 * g.unit)
        for (name, x, y), a, (tx, ty) in zip(self.pts, self.arrive, self.labels):
            if p + 1e-6 >= a:
                d.ellipse([x - r, y - r, x + r, y + r], fill=B["accent"] + (255,), outline=(255, 255, 255, 255),
                          width=max(2, r // 3))
                d.text((tx, ty), name, font=self.font, fill=(255, 255, 255, 255),
                       stroke_width=2, stroke_fill=(0, 0, 0, 200))
        if 0 < p < 1 and len(pts):
            hx, hy = pts[-1]
            d.ellipse([hx - r * 0.7, hy - r * 0.7, hx + r * 0.7, hy + r * 0.7], fill=B["highlight"] + (255,))
        arr = _rgba_arr(im)
        if len(self._cache) < 400:
            self._cache[key] = arr
        return arr

    def draw(self, img, t):
        u = t - self.t0
        p = clamp01((u - self.draw_from) / max(1e-3, self.draw_to - self.draw_from))
        p = 1 - (1 - p) ** 2                                  # path eases out as it arrives
        arr = self._frame(p)
        if u < 0.35:
            dy, a = (1 - out_cubic(u / 0.35)) * self.ch * 0.4, out_cubic(u / 0.35)
        elif t > self.t1 - 0.25:
            v = clamp01((t - (self.t1 - 0.25)) / 0.25)
            dy, a = in_cubic(v) * self.ch * 0.3, 1 - v
        else:
            dy, a = 0.0, 1.0
        img[:] = (img.astype(np.float32) * (1 - 0.35 * a)).astype(np.uint8)
        D.alpha_paste(img, arr, (self.cx - self.cw / 2, self.cy - self.ch / 2 + dy), opacity=a, bgr=True)


# ----------------------------------------------------------------------------- end card
class EndCard(Element):
    kind = "end"

    def __init__(self, g, text, t0, t1, sub=None):
        super().__init__(t0, t1)
        size = int(g.H * (0.06 if g.vertical else 0.085))
        f = D.fit_font(text, "cjk-bold", size, g.sw * 0.9, min_size=int(size * 0.5))
        self.main = _rgba_arr(D.text_layer(text, f, fill=(255, 255, 255, 255), stroke=max(3, f.size // 14),
                                           stroke_fill=(10, 10, 14, 255), shadow_alpha=160, pad=10))
        self.sub = None
        if sub:
            fs = D.fit_font(sub, "cjk-bold", int(f.size * 0.5), g.sw * 0.8, min_size=18)
            self.sub = _rgba_arr(D.text_layer(sub, fs, fill=g.brand["highlight"] + (255,), stroke=3,
                                              stroke_fill=(10, 10, 14, 255), shadow_alpha=120, pad=8))
        self.cx = (g.safe[0] + g.safe[2]) / 2
        self.cy = g.safe[1] + g.sh * 0.45
        h, w = self.main.shape[:2]
        hs, ws = (self.sub.shape[:2] if self.sub is not None else (0, 0))
        self.sub_cy = self.cy + h / 2 + hs / 2
        self.box = (self.cx - max(w, ws) / 2, self.cy - h / 2, self.cx + max(w, ws) / 2, self.cy + h / 2 + hs)

    def draw(self, img, t):
        u = t - self.t0
        dim = 0.55 * clamp01(u / 0.4)
        img[:] = (img.astype(np.float32) * (1 - dim)).astype(np.uint8)
        s = 0.5 + 0.5 * out_back(u / 0.4, 1.9) if u < 0.4 else 1.0
        _paste(img, self.main, self.cx, self.cy, s, clamp01(u / 0.15))
        if self.sub is not None:
            _paste(img, self.sub, self.cx, self.sub_cy, 1.0, clamp01((u - 0.3) / 0.25))
