"""Shot-to-shot transitions inside the picture box. P = outgoing frame, N = incoming, p = 0..1."""
import math

import cv2
import numpy as np

from .util import ease

# default durations (seconds); a shot's tr=<kind> picks one, the first shot has none
TRD = dict(fade=0.4, push=0.42, whip=0.32, flash=0.5, zoom=0.45, iris=0.55, leak=0.7,
           ink=0.6, blinds=0.55, tear=0.55, slideup=0.45, cut=0.0)
KINDS = tuple(TRD)


def scale_about(C, img, s):
    M = np.float32([[s, 0, C.BOX_W / 2 * (1 - s)], [0, s, C.BOX_H / 2 * (1 - s)]])
    return cv2.warpAffine(img, M, (C.BOX_W, C.BOX_H), borderMode=cv2.BORDER_REFLECT)


def transition(C, P, N, p, kind):
    e = ease(p)
    W, H = C.BOX_W, C.BOX_H
    if kind in ("push", "whip"):
        off = int(W * e)
        f = np.empty_like(N)
        f[:, :W - off] = P[:, off:]
        f[:, W - off:] = N[:, :off]
        if kind == "whip":                       # horizontal motion blur peaking mid-way
            k = int(110 * W / 1620 * math.sin(math.pi * p)) | 1
            if k > 2:
                f = cv2.blur(f, (k, 1))
        return f
    if kind == "flash":
        white = np.array([255, 246, 232], np.float32)
        return P * (1 - 2 * p) + white * (2 * p) if p < 0.5 else white * (2 - 2 * p) + N * (2 * p - 1)
    if kind == "zoom":
        return scale_about(C, P, 1 + 0.3 * e) * (1 - e) + scale_about(C, N, 1.18 - 0.18 * e) * e
    if kind == "iris":
        r = e * C.DIST.max() * 1.02
        m = np.clip((r - C.DIST) / C.b(24) + 0.5, 0, 1)[..., None]
        return P * (1 - m) + N * m
    if kind == "leak":
        return np.minimum(255, P * (1 - e) + N * e + C.LEAK * (0.9 * math.sin(math.pi * p)))
    if kind == "ink":
        m = np.clip((e * 1.3 - C.INK) / 0.09, 0, 1)[..., None]
        return P * (1 - m) + N * m
    if kind == "blinds":
        out = P.copy()
        n = 9
        sw = W / n
        for i in range(n):
            pi = ease(min(1, max(0, p * 1.7 - i * 0.08)))
            x = int(i * sw)
            w = int(sw * pi) + (1 if pi > 0 else 0)
            out[:, x:x + w] = N[:, x:x + w]
        return out
    if kind == "slideup":
        off = int(H * (1 - e))
        out = P * (1 - 0.5 * e)
        out[off:] = N[:H - off]
        return out
    if kind == "tear":
        edge = W * (1.08 - 1.25 * e) + C.JAG
        d = C.XX - edge[:, None]
        out = np.where((d > 0)[..., None], N, P * (1 - 0.35 * np.clip(1 + d / C.b(60), 0, 1)[..., None]))
        band = ((d > 0) & (d < C.b(16)))[..., None]
        return np.where(band, np.array([242, 236, 224], np.float32), out)
    return P * (1 - e) + N * e                     # fade (default)
