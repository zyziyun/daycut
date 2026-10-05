"""B-roll for plain 口播: user clips / images / screenshots inserted at sentence anchors while the voice
continues. Used by compose.py (config list ``BROLL``); PIL/numpy only, drawn per frame.

    BROLL = [
      dict(t0=S(3), t1=E(3), src="broll/demo.mp4", mode="cut"),            # full cut-away, voice continues
      dict(t0=S(5), t1=E(6), src="broll/page.png", mode="pip",             # picture-in-picture card
           highlight=[(S(5, .5), .42, .50), (S(6, .2), .61, .68)]),        # (t, y0, y1) rows, fractions of the image
      dict(t0=S(8), t1=E(8), src="broll/chart.png", mode="split", side="top"),   # split screen
    ]

Keys: t0/t1 body seconds (sid anchors), src (video or image; relative to the config folder), mode
cut | pip | split, ss (video start second, default 0), loop (video, default True), fit cover | contain | card
(default: cover for video and wide images; card for tall images, PiP images and images with highlights), scroll (images taller than the box: True scrolls top
to bottom over the window, or follows the highlighted rows), highlight [(t, y0, y1[, x0, x1])] marker
rows that wipe in at t (screenshot-card idea), label (small badge on the card), side top|bottom|left|right
(split), pos auto|tl|tr|bl|br (pip; auto avoids the face), w (pip width fraction of the canvas).
"""
import os
import numpy as np
import cv2
from PIL import Image, ImageDraw

IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


class Source:
    """Random-access-ish frame source: an image (static RGB float) or a video (sequential reads cached)."""

    def __init__(self, path, ss=0.0, loop=True):
        self.path, self.ss, self.loop = path, float(ss), loop
        self.is_img = path.lower().endswith(IMG_EXT)
        if self.is_img:
            self.img = np.asarray(Image.open(path).convert("RGB"), np.float32)
            self.w, self.h = self.img.shape[1], self.img.shape[0]
        else:
            self.cap = cv2.VideoCapture(path)
            if not self.cap.isOpened():
                raise FileNotFoundError(path)
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
            self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
            self.w, self.h = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.last, self.cur = -1, None

    def frame(self, dt):
        if self.is_img:
            return self.img
        i = int(round((self.ss + max(0.0, dt)) * self.fps))
        i = i % self.n if self.loop else min(i, self.n - 1)
        if i == self.last and self.cur is not None:
            return self.cur
        if i != self.last + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, bgr = self.cap.read()
        if ok:
            self.cur = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
        elif self.cur is None:
            self.cur = np.zeros((self.h, self.w, 3), np.float32)
        self.last = i
        return self.cur


def cover_fit(img, w, h, fy=0.5):
    """Scale + crop to fill w x h (vertical crop position fy: 0 top .. 1 bottom)."""
    s = max(w / img.shape[1], h / img.shape[0])
    r = cv2.resize(img, (max(w, int(round(img.shape[1] * s))), max(h, int(round(img.shape[0] * s)))),
                   interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    x0 = (r.shape[1] - w) // 2; y0 = int((r.shape[0] - h) * fy)
    return r[y0:y0 + h, x0:x0 + w]


def blur_fill(img, w, h, dim=0.45):
    small = cv2.resize(cover_fit(img, max(8, w // 16), max(8, h // 16)), None, fx=1, fy=1)
    return cv2.resize(cv2.GaussianBlur(small, (0, 0), 2), (w, h), interpolation=cv2.INTER_CUBIC) * dim


def ease(u):
    u = min(1.0, max(0.0, u)); return u * u * (3 - 2 * u)


def round_mask(w, h, r):
    m = np.zeros((h, w), np.uint8)
    cv2.rectangle(m, (r, 0), (w - r, h), 255, -1); cv2.rectangle(m, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(m, (cx, cy), r, 255, -1, cv2.LINE_AA)
    return (cv2.GaussianBlur(m, (3, 3), 0) / 255.0)[..., None]


def paste_card(dst, card, x, y, r=28, shadow=0.55, border=None, alpha=1.0):
    """Rounded card with a soft shadow into dst (float RGB, in place)."""
    h, w = card.shape[:2]; H, W = dst.shape[:2]
    x, y = int(round(x)), int(round(y))
    m = round_mask(w, h, max(4, r))
    if shadow:
        sh = np.zeros((H, W), np.float32)
        ys0, xs0 = max(0, y + 16), max(0, x)
        ys1, xs1 = min(H, y + 16 + h), min(W, x + w)
        if ys1 > ys0 and xs1 > xs0:
            sh[ys0:ys1, xs0:xs1] = m[ys0 - y - 16:ys1 - y - 16, xs0 - x:xs1 - x, 0]
            sh = cv2.GaussianBlur(sh, (0, 0), 20) * shadow * alpha
            dst *= (1 - sh[..., None])
    if border is not None:
        card = card.copy()
        bm = round_mask(w, h, max(4, r)) - np.pad(round_mask(w - 6, h - 6, max(2, r - 3)), ((3, 3), (3, 3), (0, 0)))
        card = card * (1 - bm) + np.array(border, np.float32) * bm
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    mm = m[y0 - y:y1 - y, x0 - x:x1 - x] * alpha
    dst[y0:y1, x0:x1] = dst[y0:y1, x0:x1] * (1 - mm) + card[y0 - y:y1 - y, x0 - x:x1 - x] * mm


class Item:
    def __init__(self, d, layout, hl_color):
        self.d = d
        self.t0, self.t1 = float(d["t0"]), float(d["t1"])
        self.mode = d.get("mode", "cut")
        if self.mode not in ("cut", "pip", "split"):
            raise ValueError(f"BROLL mode {self.mode!r}: cut | pip | split")
        self.src = Source(d["src"], d.get("ss", 0.0), d.get("loop", True))
        self.L = layout
        self.hl = [tuple(h) for h in d.get("highlight", [])]
        self.hl_color = np.array(hl_color, np.float32)
        # images: tall ones (screenshots, pages) or PiP -> card with scroll/highlights; others fill (cover)
        tall = self.src.is_img and self.src.h > 1.2 * self.src.w
        self.fit = d.get("fit") or ("card" if self.src.is_img and (tall or self.mode == "pip" or self.hl) else "cover")
        self.screen = self.src.is_img and self.fit == "card"
        self.rect = None                       # pip rect, chosen once (face-aware) by compose

    # ---------------------------------------------------------------- screenshot view (scroll + highlights)
    def view(self, dt, w, h, b):
        """w x h RGB view of the source at dt seconds into the window (b = body time for highlights)."""
        img = self.src.frame(dt)
        if not self.screen:
            return cover_fit(img, w, h, 0.5) if self.fit == "cover" else self._contain(img, w, h)
        s = w / img.shape[1]
        full_h = img.shape[0] * s
        if full_h <= h + 1:
            return self._contain(img, w, h, b)
        # scroll: follow the current highlight row, else top -> bottom over the window
        span = full_h - h
        dur = max(1e-3, self.t1 - self.t0)
        if self.hl and self.d.get("scroll", True) != "linear":
            cur = [r for r in self.hl if r[0] <= b] or [self.hl[0]]
            r = cur[-1]; prev = cur[-2] if len(cur) > 1 else None
            tgt = lambda rr: np.clip((rr[1] + rr[2]) / 2 * full_h - h / 2, 0, span)
            y = tgt(r) if prev is None else tgt(prev) + (tgt(r) - tgt(prev)) * ease((b - r[0]) / 0.6)
        elif self.d.get("scroll", True):
            y = span * ease((b - self.t0) / dur)
        else:
            y = 0.0
        y0 = int(y / s); y1 = min(img.shape[0], y0 + int(np.ceil(h / s)) + 1)
        crop = img[y0:y1]
        out = cv2.resize(crop, (w, int(round(crop.shape[0] * s))), interpolation=cv2.INTER_AREA)[:h]
        if out.shape[0] < h:
            out = np.pad(out, ((0, h - out.shape[0]), (0, 0), (0, 0)))
        self._marks(out, b, full_h, y, w)
        return out

    def _contain(self, img, w, h, b=None):
        s = min(w / img.shape[1], h / img.shape[0])
        r = cv2.resize(img, (max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s))), interpolation=cv2.INTER_AREA)
        out = np.full((h, w, 3), 245.0, np.float32) if self.screen else blur_fill(img, w, h)
        oy, ox = (h - r.shape[0]) // 2, (w - r.shape[1]) // 2
        out[oy:oy + r.shape[0], ox:ox + r.shape[1]] = r
        if b is not None:
            self._marks(out, b, r.shape[0], -oy, r.shape[1], ox)
        return out

    def _marks(self, out, b, full_h, y_off, w, x_off=0):
        """Highlighter rows: multiply-blend a marker band that wipes in left -> right over 0.35 s."""
        for r in self.hl:
            if b < r[0]:
                continue
            u = ease((b - r[0]) / 0.35)
            fx0, fx1 = (r[3], r[4]) if len(r) >= 5 else (0.02, 0.98)
            y0 = int(r[1] * full_h - y_off); y1 = int(r[2] * full_h - y_off)
            x0 = int(x_off + fx0 * w); x1 = int(x0 + (fx1 - fx0) * w * u)
            y0, y1 = max(0, y0), min(out.shape[0], y1)
            if y1 > y0 and x1 > x0:
                band = out[y0:y1, x0:x1]
                out[y0:y1, x0:x1] = band * (0.55 + 0.45 * self.hl_color / 255.0)
                cv2.rectangle(out, (x0, y1 - 3), (x1, y1), tuple(float(c) for c in self.hl_color * 0.8), -1)


def load(cfg_list, layout, hl_color=(255, 214, 10)):
    return [Item(d, layout, hl_color) for d in (cfg_list or [])]


def active(items, b):
    for it in items:
        if it.t0 <= b < it.t1:
            return it
    return None


def badge_layer(text, font):
    """Small dark label pill (RGBA numpy) for a card corner."""
    from vstudio import draw as D
    w = int(D.text_width(text, font)) + 40
    im = D.rounded_rect((w, int(font.size * 1.7)), int(font.size * 0.85), (15, 15, 18, 225))
    ImageDraw.Draw(im).text((w / 2, im.height / 2), text, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return np.asarray(im)


def exists(cfg_list):
    return [d["src"] for d in (cfg_list or []) if not os.path.exists(d["src"])]
