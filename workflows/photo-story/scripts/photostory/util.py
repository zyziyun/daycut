"""Small numeric / image helpers shared by every module (no global state)."""
import math
import re

import numpy as np
from PIL import Image

CJK_RE = re.compile(r"[⺀-鿿가-힯＀-￯]")


def ease(u):
    """Cosine ease-in-out, clamped to [0, 1]."""
    return 0.5 - 0.5 * math.cos(math.pi * min(max(u, 0), 1))


def has_cjk(text):
    return bool(CJK_RE.search(text or ""))


def layer(w, h):
    return Image.new("RGBA", (int(w), int(h)), (0, 0, 0, 0))


def to_arr(im):
    return np.asarray(im).astype(np.float32)


def paste_rgba(dst, rgba, x, y, alpha=1.0):
    """Composite rgba (float32, 0-255) onto float32 RGB dst at (x, y), clipped to the edges."""
    x, y = int(x), int(y)
    h, w = rgba.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, dst.shape[1]), min(y + h, dst.shape[0])
    if x1 <= x0 or y1 <= y0 or alpha <= 0:
        return
    src = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    a = src[..., 3:4] * (alpha / 255)
    reg = dst[y0:y1, x0:x1]
    reg *= (1 - a)
    reg += src[..., :3] * a


def cover(im, w, h, c=(0.5, 0.5), z=1.0):
    """Crop+resize a PIL image to exactly w x h around framing centre c with extra zoom z."""
    w, h = int(w), int(h)
    s = max(w / im.width, h / im.height) * z
    cw, ch = w / s, h / s
    cx = min(max(c[0] * im.width, cw / 2), im.width - cw / 2)
    cy = min(max(c[1] * im.height, ch / 2), im.height - ch / 2)
    box = (max(0.0, cx - cw / 2), max(0.0, cy - ch / 2), min(im.width, cx + cw / 2), min(im.height, cy + ch / 2))
    return im.resize((w, h), Image.LANCZOS, box=box)


def crop_focus(im, c, z):
    """Cut the part of the image around framing centre c at zoom z (keeps the image's aspect)."""
    if z <= 1.0:
        return im
    w, h = im.width / z, im.height / z
    x = min(max(c[0] * im.width - w / 2, 0), im.width - w)
    y = min(max(c[1] * im.height - h / 2, 0), im.height - h)
    return im.crop((int(x), int(y), int(x + w), int(y + h)))


def crop_aspect(im, c, z, aspect):
    """Crop to a given aspect (w/h) around c at zoom z (used by the cover)."""
    w = im.width / z
    h = w / aspect
    if h > im.height / z:
        h = im.height / z
        w = h * aspect
    x = min(max(c[0] * im.width - w / 2, 0), im.width - w)
    y = min(max(c[1] * im.height - h / 2, 0), im.height - h)
    return im.crop((int(x), int(y), int(x + w), int(y + h)))


def hex_rgb(v):
    if isinstance(v, (tuple, list)):
        return tuple(int(x) for x in v[:3])
    v = str(v).lstrip("#")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))
