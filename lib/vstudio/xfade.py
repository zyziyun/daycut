"""Cross-engine transition bridge: one transition name, three engines.

Engines
  hyperframes  GSAP on scene wrapper divs. The 11 ``hf.TRANSITIONS`` are delegated to
               ``hf.scene_transitions``; whip / flash / fadeblack / light-leak / slideup / wipe / cut get
               their own GSAP snippet here (``hf_transitions``).
  ffmpeg       an ``xfade`` transition. Built-in names where ffmpeg has a close one, otherwise a
               ``custom`` expression (whip, light-leak, blocks, ink, blinds, zoomout).
               ``ffmpeg_transition(name)`` is the value for ``cut.xfade_assemble(transition=...)``;
               ``ffmpeg_expr(name, duration, offset)`` is a full ``xfade=...`` filter snippet.
  pil-frame    ``blend(name, a, b, p)`` on two same-size float frames (H, W, 3), p in 0..1. numpy only.
               p <= 0 returns a copy of A, p >= 1 a copy of B, exactly.

Every name has all three engines; ``coverage()`` says how faithful each one is
("exact" = same look, "near" = same idea with a small visual difference, "approx" = closest stand-in)
and ``gaps()`` says what is missing. ``python -m vstudio.xfade`` prints the matrix.

    from vstudio import xfade, cut
    asm = cut.xfade_assemble(pieces, xfade=0.4, transition=xfade.ffmpeg_transition("whip"))
    f = xfade.blend("light-leak", A, B, 0.5)                      # photo-story / talkinghead / vlog frames
    tx = xfade.hf_transitions([("whip", "w-a", "w-b", 12.0, 0.4)])  # {"css","html","js"} like vstudio.hf

Custom ffmpeg expressions assume 8-bit YUV input (what ``xfade_assemble`` produces: ``format=yuv420p``)
and are evaluated per pixel, so they are slower than built-ins (roughly 1.5 s per 1080p frame for
light-leak and 2.5 s for whip, the heaviest; ``taps=3`` cuts whip by ~40 %). Keep them on short
joins. They never use st()/ld(): xfade's slice threads share those registers (shows up as noise).
"""
import functools
import math
import re
import subprocess

import numpy as np

__all__ = ["NAMES", "ALIASES", "SPECS", "resolve", "spec", "names", "blend", "ffmpeg_transition",
           "ffmpeg_expr", "ffmpeg_builtins", "hf_type", "hf_transitions", "coverage", "gaps",
           "coverage_markdown", "default_duration"]

ENGINES = ("hyperframes", "ffmpeg", "pil-frame")

# ---------------------------------------------------------------------------------------------
# helpers shared by the PIL implementations
# ---------------------------------------------------------------------------------------------


def _ease(u):
    """Cosine ease-in-out on [0, 1] (photo-story's ``util.ease``)."""
    u = min(max(float(u), 0.0), 1.0)
    return 0.5 - 0.5 * math.cos(math.pi * u)


def _peak(a, b, peak):
    if peak is not None:
        return float(peak)
    m = max(float(np.max(a)) if a.size else 0.0, float(np.max(b)) if b.size else 0.0)
    return 1.0 if m <= 1.0 else 255.0


def _rgb(c, peak):
    return np.array(c, np.float32) * (peak / 255.0)


@functools.lru_cache(maxsize=16)
def _grid(h, w):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    return xx, yy


def _box_blur_x(img, r):
    """Horizontal box blur, radius r px (edge-clamped). Cheap stand-in for a motion / gaussian blur."""
    r = int(r)
    if r < 1:
        return img
    pad = np.pad(img, ((0, 0), (r + 1, r), (0, 0)), mode="edge")
    c = np.cumsum(pad, axis=1, dtype=np.float64)
    out = (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)
    return out.astype(np.float32)


def _box_blur(img, r):
    """Separable 2-pass box blur ~ gaussian of sigma ~ r/1.7."""
    r = int(r)
    if r < 1:
        return img
    x = _box_blur_x(img, r)
    return np.swapaxes(_box_blur_x(np.swapaxes(x, 0, 1), r), 0, 1)


def _resample(img, sx, sy=None, cx=0.5, cy=0.5, dx=0.0, dy=0.0, fill=None):
    """Scale ``img`` by (sx, sy) about (cx, cy) (fractions of the frame), then shift by (dx, dy) px.
    Bilinear. Pixels that come from outside the source take ``fill`` (None = edge clamp)."""
    sy = sx if sy is None else sy
    h, w = img.shape[:2]
    xx, yy = _grid(h, w)
    X = (xx - dx - cx * w) / max(sx, 1e-4) + cx * w
    Y = (yy - dy - cy * h) / max(sy, 1e-4) + cy * h
    outside = (X < -0.5) | (X > w - 0.5) | (Y < -0.5) | (Y > h - 0.5)
    X = np.clip(X, 0, w - 1)
    Y = np.clip(Y, 0, h - 1)
    x0 = np.floor(X).astype(np.int32)
    y0 = np.floor(Y).astype(np.int32)
    x1 = np.minimum(x0 + 1, w - 1)
    y1 = np.minimum(y0 + 1, h - 1)
    fx = (X - x0)[..., None]
    fy = (Y - y0)[..., None]
    top = img[y0, x0] * (1 - fx) + img[y0, x1] * fx
    bot = img[y1, x0] * (1 - fx) + img[y1, x1] * fx
    out = (top * (1 - fy) + bot * fy).astype(np.float32)
    if fill is not None:
        out[outside] = fill
    return out


@functools.lru_cache(maxsize=8)
def _lowfreq(h, w, seed, cells):
    """Smooth 0..1 noise field (bilinear-upsampled random grid), deterministic."""
    r = np.random.default_rng(seed)
    gh = max(2, int(round(cells * h / max(w, 1))) + 2)
    gw = cells + 2
    g = r.random((gh, gw)).astype(np.float32)
    ys = np.linspace(0, gh - 1.001, h)
    xs = np.linspace(0, gw - 1.001, w)
    tmp = np.stack([np.interp(xs, np.arange(gw), row) for row in g])
    out = np.stack([np.interp(ys, np.arange(gh), col) for col in tmp.T], axis=1)
    return out.astype(np.float32)


@functools.lru_cache(maxsize=8)
def _ink_field(h, w):
    f = _lowfreq(h, w, 3, 5) * 0.7 + _lowfreq(h, w, 5, 24) * 0.3
    return ((f - f.min()) / (f.max() - f.min() + 1e-6)).astype(np.float32)


@functools.lru_cache(maxsize=8)
def _pixel_noise(h, w):
    return np.random.default_rng(7).random((h, w)).astype(np.float32)


@functools.lru_cache(maxsize=8)
def _leak_mask(h, w):
    """Warm light-leak texture, 0..1 per channel (same blobs as photo-story ``looks.make_leak``)."""
    xx, yy = _grid(h, w)
    im = np.zeros((h, w, 3), np.float32)
    for (cx, cy, rad, col) in LEAK_BLOBS:
        d = np.sqrt((xx - cx * w) ** 2 + (yy - cy * h) ** 2) / (rad * w)
        im += np.clip(1 - d, 0, 1)[..., None] ** 2 * (np.array(col, np.float32) / 255.0)
    return im


@functools.lru_cache(maxsize=8)
def _jag(h, w):
    r = np.random.default_rng(11)
    j = np.cumsum(r.normal(0, 6, h))
    k = max(1, h // 120)
    j = np.convolve(np.pad(j, k, mode="edge"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    j = (j - j.mean()) / (np.abs(j - j.mean()).max() + 1e-6) * 45 + r.normal(0, 3, h)
    return (j * w / 1620.0).astype(np.float32)


LEAK_BLOBS = ((0.15, 0.25, 0.7, (255, 140, 40)), (0.85, 0.65, 0.6, (255, 70, 30)),
              (0.55, 0.10, 0.45, (255, 210, 120)))
BLOCK_COLOR = (0x11, 0x1A, 0x33)      # hf.scene_transitions default block_color
FLASH_WHITE = (255, 246, 232)         # photo-story warm white
PAPER = (242, 236, 224)

# ---------------------------------------------------------------------------------------------
# PIL-frame implementations: fn(a, b, p, e, pk, **opts) with 0 < p < 1, e = eased p, pk = peak value
# ---------------------------------------------------------------------------------------------


def _p_fade(a, b, p, e, pk):
    return a * (1 - e) + b * e


def _p_blur(a, b, p, e, pk, radius=0.009):
    r = radius * a.shape[1] * math.sin(math.pi * p)
    return _box_blur(a, r) * (1 - e) + _box_blur(b, r) * e


def _p_focus(a, b, p, e, pk, radius=0.014):
    w = a.shape[1]
    e2 = _ease((p - 0.3) / 0.7)
    out = _box_blur(_resample(a, 1 + 0.04 * e), radius * w * e)
    inn = _box_blur(_resample(b, 0.97 + 0.03 * e2), radius * w * (1 - e2))
    return out * (1 - e2) + inn * e2


def _push(a, b, e, axis):
    n = a.shape[axis]
    off = int(round(n * e))
    f = np.empty_like(a)
    if axis == 1:
        f[:, :n - off] = a[:, off:]
        f[:, n - off:] = b[:, :off]
    else:
        f[:n - off] = a[off:]
        f[n - off:] = b[:off]
    return f


def _p_push(a, b, p, e, pk):
    return _box_blur_x(_push(a, b, e, 1), 0.002 * a.shape[1] * math.sin(math.pi * p))


def _p_vpush(a, b, p, e, pk):
    h = a.shape[0]
    off = int(round(h * e))
    f = np.empty_like(a)
    f[:h - off] = a[off:] * (1 - 0.6 * e)
    f[h - off:] = b[:off]
    return f


def _p_whip(a, b, p, e, pk, blur=0.034):
    return _box_blur_x(_push(a, b, e, 1), blur * a.shape[1] * math.sin(math.pi * p))


def _p_iris(a, b, p, e, pk, cx=0.5, cy=0.45, soft=0.015):
    h, w = a.shape[:2]
    xx, yy = _grid(h, w)
    dist = np.sqrt((xx - cx * w) ** 2 + (yy - cy * h) ** 2)
    r = e * float(dist.max()) * 1.02
    m = np.clip((r - dist) / (soft * min(h, w)) + 0.5, 0, 1)[..., None]
    return a * (1 - m) + b * m


def _p_zoom(a, b, p, e, pk):
    return _resample(a, 1 + 0.3 * e) * (1 - e) + _resample(b, 1.18 - 0.18 * e) * e


def _p_zoomout(a, b, p, e, pk):
    black = _rgb((0, 0, 0), pk)
    e2 = _ease((p - 0.3) / 0.7)
    out = _box_blur(_resample(a, 1 - 0.14 * e, fill=black), 0.003 * a.shape[1] * e)
    return out * (1 - e2) + _resample(b, 1.08 - 0.08 * e2) * e2


def _p_flip(a, b, p, e, pk):
    black = _rgb((0, 0, 0), pk)
    if p < 0.5:
        sx = math.cos(_ease(p * 2) * math.pi / 2)
        src = a
    else:
        sx = math.sin(_ease(p * 2 - 1) * math.pi / 2)
        src = b
    return _resample(src, max(sx, 1e-3), 1.0, fill=black) * (0.2 + 0.8 * sx)


def _p_blocks(a, b, p, e, pk, n=8, color=BLOCK_COLOR, stagger=0.03):
    h, w = a.shape[:2]
    hd = 0.5 - (n - 1) * stagger
    base = (a if p < 0.5 else b).copy()
    yy = (np.arange(h, dtype=np.float32) + 0.5) / h
    col = np.minimum((np.arange(w) * n) // w, n - 1)
    cover = np.array([_ease((p - i * stagger) / hd) for i in range(n)], np.float32)[col]
    uncover = np.array([_ease((p - 0.5 - i * stagger) / hd) for i in range(n)], np.float32)[col]
    panel = (yy[:, None] < cover[None, :]) & (yy[:, None] >= uncover[None, :])
    base[panel] = _rgb(color, pk)
    return base


def _p_chroma(a, b, p, e, pk):
    w = a.shape[1]
    k = (8, -12, 6, -4, 0)[min(4, int(p * 5))] * w / 1920.0
    step = math.floor(min(p, 0.999) * 5 + 1) / 5.0          # steps(5)-like crossfade
    inn = _resample(b, 1.0, dx=18 * w / 1920.0 * (1 - e))
    f = a * (1 - step) + inn * step
    if abs(k) >= 0.5:
        s = int(round(k))
        f = f.copy()
        f[..., 0] = np.roll(f[..., 0], s, axis=1)
        f[..., 2] = np.roll(f[..., 2], -s, axis=1)
    return f


def _p_flash(a, b, p, e, pk, color=FLASH_WHITE):
    white = _rgb(color, pk)
    if p < 0.5:
        return a * (1 - 2 * p) + white * (2 * p)
    return white * (2 - 2 * p) + b * (2 * p - 1)


def _p_fadeblack(a, b, p, e, pk):
    return a * max(0.0, 1 - 2 * p) if p < 0.5 else b * (2 * p - 1)


def _p_leak(a, b, p, e, pk, strength=0.9):
    leak = _leak_mask(*a.shape[:2]) * pk
    return np.minimum(pk, a * (1 - e) + b * e + leak * (strength * math.sin(math.pi * p)))


def _p_ink(a, b, p, e, pk):
    m = np.clip((e * 1.3 - _ink_field(*a.shape[:2])) / 0.09, 0, 1)[..., None]
    return a * (1 - m) + b * m


def _p_blinds(a, b, p, e, pk, n=9):
    out = a.copy()
    w = a.shape[1]
    sw = w / n
    for i in range(n):
        pi = _ease(p * 1.7 - i * 0.08)
        x = int(i * sw)
        ww = int(sw * pi) + (1 if pi > 0 else 0)
        out[:, x:x + ww] = b[:, x:x + ww]
    return out


def _p_tear(a, b, p, e, pk):
    h, w = a.shape[:2]
    xx, _ = _grid(h, w)
    edge = w * (1.08 - 1.25 * e) + _jag(h, w)
    d = xx - edge[:, None]
    bs = w / 1620.0
    out = np.where((d > 0)[..., None], b, a * (1 - 0.35 * np.clip(1 + d / (60 * bs), 0, 1)[..., None]))
    band = ((d > 0) & (d < 16 * bs))[..., None]
    return np.where(band, _rgb(PAPER, pk), out).astype(np.float32)


def _p_slideup(a, b, p, e, pk):
    h = a.shape[0]
    off = int(round(h * (1 - e)))
    out = a * (1 - 0.5 * e)
    out[off:] = b[:h - off]
    return out


def _p_cut(a, b, p, e, pk):
    return (a if p < 0.5 else b).copy()


def _p_wipe(a, b, p, e, pk, soft=0.004):
    h, w = a.shape[:2]
    xx, _ = _grid(h, w)
    m = np.clip((xx - w * (1 - e)) / max(1.0, soft * w) + 0.5, 0, 1)[..., None]
    return a * (1 - m) + b * m


def _p_dissolve(a, b, p, e, pk):
    m = (_pixel_noise(*a.shape[:2]) < p)[..., None]
    return np.where(m, b, a).astype(np.float32)


def _p_pixelize(a, b, p, e, pk, max_block=0.05):
    h, w = a.shape[:2]
    k = math.sin(math.pi * p)
    blk = max(1, int(round(k * max_block * min(h, w))))
    f = a * (1 - e) + b * e
    if blk <= 1:
        return f
    hh, ww = -(-h // blk) * blk, -(-w // blk) * blk
    pad = np.pad(f, ((0, hh - h), (0, ww - w), (0, 0)), mode="edge")
    m = pad.reshape(hh // blk, blk, ww // blk, blk, 3).mean(axis=(1, 3))
    return np.repeat(np.repeat(m, blk, 0), blk, 1)[:h, :w].astype(np.float32)


def _p_radial(a, b, p, e, pk, soft=0.01):
    h, w = a.shape[:2]
    xx, yy = _grid(h, w)
    ang = (np.arctan2(xx - w / 2, -(yy - h / 2)) / (2 * math.pi)) % 1.0
    m = np.clip((e - ang) / soft + 0.5, 0, 1)[..., None]
    return a * (1 - m) + b * m


# ---------------------------------------------------------------------------------------------
# ffmpeg custom expressions (xfade transition=custom). P runs 1 -> 0, so q = 1 - P runs 0 -> 1.
# ---------------------------------------------------------------------------------------------

def _sampler(src):
    """Per-plane sample of input A or B at (x, y) of the current plane."""
    s = src.lower()
    return lambda x, y: (f"if(eq(PLANE,0),{s}0({x},{y}),if(eq(PLANE,1),{s}1({x},{y}),"
                         f"if(eq(PLANE,2),{s}2({x},{y}),{s}3({x},{y}))))")


def _yuv(rgb):
    """8-bit limited-range BT.709 Y, U, V of an sRGB triple."""
    r, g, b = (c / 255.0 for c in rgb)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    u = (b - y) / 1.8556
    v = (r - y) / 1.5748
    return int(round(16 + 219 * y)), int(round(128 + 224 * u)), int(round(128 + 224 * v))


def _plane(yv, uv, vv, av="255"):
    return f"if(eq(PLANE,0),{yv},if(eq(PLANE,1),{uv},if(eq(PLANE,2),{vv},{av})))"


# No st()/ld(): xfade runs slice threads that share the expression's variable registers, so stored
# values race between threads (noise). Every sub-expression is inlined instead.
_q = "(1-P)"
_e = "(0.5-0.5*cos(PI*(1-P)))"


def _ez(x):
    return f"(0.5-0.5*cos(PI*clip({x},0,1)))"


def _x_whip(taps=5, blur=0.034):
    A, B = _sampler("a"), _sampler("b")
    terms = []
    for k in range(taps):
        off = (k - (taps - 1) / 2) / max(1, (taps - 1) / 2)
        x = f"clip(X+W*{_e}+{off:.3f}*{blur}*W*sin(PI*{_q}),0,2*W-1)"
        terms.append(f"if(lt({x},W),{A(x, 'Y')},{B(x + '-W', 'Y')})")
    return f"({'+'.join(terms)})/{taps}"


def _x_leak(strength=0.9):
    m = "+".join(f"{w:.2f}*pow(clip(1-hypot(X/W-{cx},(Y/H-{cy})*H/W)/{r},0,1),2)"
                 for (cx, cy, r, _), w in zip(LEAK_BLOBS, (1.0, 0.8, 0.9)))
    k = f"({strength}*sin(PI*{_q})*min(1,{m}))"
    base = f"(A*(1-{_e})+B*{_e})"
    return _plane(f"clip({base}+200*{k},0,255)", f"clip({base}-40*{k},0,255)",
                  f"clip({base}+45*{k},0,255)", base)


def _x_blocks(n=8, color=BLOCK_COLOR, stagger=0.03):
    hd = 0.5 - (n - 1) * stagger
    y, u, v = _yuv(color)
    col = f"floor(X/W*{n})"
    cover = _ez(f"({_q}-{col}*{stagger})/{hd:.3f}")
    uncover = _ez(f"({_q}-0.5-{col}*{stagger})/{hd:.3f}")
    return f"if(lt(Y/H,{cover})*gte(Y/H,{uncover}),{_plane(y, u, v)},if(lt({_q},0.5),A,B))"


def _x_ink():
    f = ("((sin(X/W*9.0+1.3)*sin(Y/H*7.0+0.4)+0.6*sin(X/W*17+Y/H*13+2.1)"
         "+0.4*sin((X/W-Y/H)*23+0.7))+2)/4")
    m = f"clip(({_e}*1.3-{f})/0.09,0,1)"
    return f"A*(1-{m})+B*{m}"


def _x_blinds(n=9):
    col = f"floor(X/W*{n})"
    return f"if(lt(X/W*{n}-{col},{_ez(f'{_q}*1.7-{col}*0.08')}),B,A)"


def _x_zoomout():
    A, B = _sampler("a"), _sampler("b")
    black = _plane(16, 128, 128)
    s = f"(1-0.14*{_e})"
    e2 = _ez(f"({_q}-0.3)/0.7")
    s2 = f"(1.08-0.08*{e2})"
    xa, ya = f"((X-W/2)/{s}+W/2)", f"((Y-H/2)/{s}+H/2)"
    out = f"if(between({xa},0,W-1)*between({ya},0,H-1),{A(xa, ya)},{black})"
    inn = B(f"((X-W/2)/{s2}+W/2)", f"((Y-H/2)/{s2}+H/2)")
    return f"({out})*(1-{e2})+({inn})*{e2}"


# ---------------------------------------------------------------------------------------------
# HyperFrames snippets for names hf.scene_transitions does not have
# ---------------------------------------------------------------------------------------------

def _hf_overlay(kind, k, at, d, color=None):
    el = f"tx-{kind}-{k}"
    if kind == "leak":
        bg = ", ".join(f"radial-gradient(circle at {cx * 100:.0f}% {cy * 100:.0f}%, "
                       f"rgba({c[0]},{c[1]},{c[2]},0.95) 0%, rgba({c[0]},{c[1]},{c[2]},0) {r * 100:.0f}%)"
                       for cx, cy, r, c in LEAK_BLOBS)
        css = (f"#{el} {{ position: absolute; inset: 0; z-index: 41; pointer-events: none; opacity: 0; "
               f"mix-blend-mode: screen; background: {bg}; }}\n")
    else:
        css = (f"#{el} {{ position: absolute; inset: 0; z-index: 41; pointer-events: none; opacity: 0; "
               f"background: {color}; }}\n")
    return el, css, f'<div id="{el}"></div>'


def _hf_custom(name, o, i, T, d, k, W, H):
    """GSAP for one bridge-only transition. Same rules as hf.scene_transitions: incoming tweens use
    fromTo with immediateRender:false, outgoing uses to(); overlays start at opacity 0 in CSS."""
    o, i = "#" + o, "#" + i
    IR = "immediateRender: false"
    css = html = ""
    if name == "whip":
        js = (f'tl.to("{o}", {{ x: -{W}, filter: "blur(24px)", duration: {d}, ease: "power4.inOut" }}, {T});\n'
              f'tl.fromTo("{i}", {{ x: {W}, filter: "blur(24px)" }}, {{ x: 0, filter: "blur(0px)", duration: {d}, '
              f'ease: "power4.inOut", {IR} }}, {T});\n')
    elif name in ("flash", "fadeblack"):
        color = "rgb(255,246,232)" if name == "flash" else "#000"
        el, css, html = _hf_overlay(name, k, T, d, color)
        h = d / 2
        js = (f'tl.fromTo("#{el}", {{ opacity: 0 }}, {{ opacity: 1, duration: {h}, ease: "power2.in", {IR} }}, {T});\n'
              f'tl.to("{o}", {{ opacity: 0, duration: 0.01 }}, {T + h});\n'
              f'tl.fromTo("{i}", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.01, {IR} }}, {T + h});\n'
              f'tl.to("#{el}", {{ opacity: 0, duration: {h}, ease: "power2.out" }}, {T + h});\n')
    elif name == "light-leak":
        el, css, html = _hf_overlay("leak", k, T, d)
        h = d / 2
        js = (f'tl.to("{o}", {{ opacity: 0, duration: {d}, ease: "sine.inOut" }}, {T});\n'
              f'tl.fromTo("{i}", {{ opacity: 0 }}, {{ opacity: 1, duration: {d}, ease: "sine.inOut", {IR} }}, {T});\n'
              f'tl.fromTo("#{el}", {{ opacity: 0 }}, {{ opacity: 0.9, duration: {h}, ease: "sine.out", {IR} }}, {T});\n'
              f'tl.to("#{el}", {{ opacity: 0, duration: {h}, ease: "sine.in" }}, {T + h});\n')
    elif name == "slideup":
        js = (f'tl.to("{o}", {{ opacity: 0.5, duration: {d}, ease: "power2.inOut" }}, {T});\n'
              f'tl.fromTo("{i}", {{ y: {H} }}, {{ y: 0, duration: {d}, ease: "power2.inOut", {IR} }}, {T});\n')
    elif name == "wipe":
        js = (f'tl.fromTo("{i}", {{ clipPath: "inset(0% 0% 0% 100%)" }}, {{ clipPath: "inset(0% 0% 0% 0%)", '
              f'duration: {d}, ease: "power2.inOut", {IR} }}, {T});\n')
    elif name == "cut":
        js = f'tl.set("{o}", {{ opacity: 0 }}, {T});\n'
    else:
        raise ValueError(f"no HyperFrames snippet for {name!r}")
    return css, html, js


# ---------------------------------------------------------------------------------------------
# the catalogue
# ---------------------------------------------------------------------------------------------

def _s(what, dur, pil, hf, ffmpeg, aliases=()):
    return dict(what=what, duration=dur, pil=pil, hf=hf, ffmpeg=ffmpeg, aliases=tuple(aliases))


def _hf(type=None, level="exact", gap="", custom=False):
    return dict(type=type, level=level, gap=gap, custom=custom)


def _ff(xfade=None, expr=None, level="exact", gap="", fallback=None):
    return dict(xfade=xfade, expr=expr, level=level, gap=gap, fallback=fallback)


SPECS = {
    # --- the 11 HyperFrames transitions (hf.TRANSITIONS); PIL / ffmpeg follow the GSAP reference ---
    "blur": _s("Cross-dissolve through a soft blur", 0.8, (_p_blur, "exact", ""),
               _hf("blur"), _ff("hblur", level="approx", gap="xfade hblur smears horizontally only; no 2-D defocus")),
    "fade": _s("Plain cross-dissolve", 0.45, (_p_fade, "exact", ""), _hf("fade"), _ff("fade"),
               aliases=("crossfade", "xfade")),
    "push": _s("Outgoing slides left, incoming pushes in from the right (light blur)", 0.7,
               (_p_push, "exact", ""), _hf("push"),
               _ff("slideleft", level="near", gap="no 4 px motion blur"), aliases=("slideleft",)),
    "vpush": _s("Vertical push: outgoing slides up and dims, incoming follows", 0.7, (_p_vpush, "exact", ""),
                _hf("vpush"), _ff("slideup", level="near", gap="outgoing is not dimmed to 40 %")),
    "iris": _s("Circle opens from the centre to reveal the next scene", 1.1, (_p_iris, "exact", ""),
               _hf("iris"), _ff("circleopen", level="near",
                                gap="centre is 50 %/50 % (HF 50 %/45 %); outgoing does not shrink to 0.94"),
               aliases=("circleopen",)),
    "zoom": _s("Outgoing rushes into the lens and blurs; incoming settles from 0.7x", 0.8,
               (_p_zoom, "near", "incoming settles from 1.18x (photo-story) instead of 0.7x"),
               _hf("zoom"), _ff("zoomin", level="approx", gap="only the outgoing zooms; no blur, incoming static"),
               aliases=("zoomin",)),
    "focus": _s("Rack focus: outgoing defocuses, incoming pulls into focus", 0.9, (_p_focus, "exact", ""),
                _hf("focus"), _ff("fade", level="approx",
                                  gap="xfade cannot defocus; pre-blur the tail/head with gblur or render in HF")),
    "blocks": _s("8 dark panels drop in (staggered), cover the cut, then lift away", 1.1,
                 (_p_blocks, "exact", ""), _hf("blocks"),
                 _ff(expr=_x_blocks, level="near", gap="no 1 px panel edge line"), aliases=("panels",)),
    "chroma": _s("Glitchy stepped fade with an RGB split", 0.8, (_p_chroma, "near", "split is a channel roll, not a drop-shadow"),
                 _hf("chroma"), _ff("pixelize", level="approx",
                                    gap="no RGB split; for the real look pre-render with rgbashift")),
    "flip": _s("Card flip: outgoing turns away 90 deg, incoming turns in", 0.9,
               (_p_flip, "near", "horizontal squeeze, no perspective foreshortening"),
               _hf("flip"), _ff("squeezeh", level="approx", gap="squeeze, no perspective or dimming")),
    "zoomout": _s("Outgoing shrinks back and blurs; incoming settles from 1.08x", 1.0,
                  (_p_zoomout, "exact", ""), _hf("zoomout"),
                  _ff(expr=_x_zoomout, level="near", gap="no blur on the outgoing")),
    # --- photo-story / ffmpeg names, bridged into HyperFrames ---
    "whip": _s("Whip pan: fast push with a strong horizontal motion blur at mid-point", 0.32,
               (_p_whip, "exact", ""),
               _hf("push", custom=True, level="near", gap="CSS blur is 2-D, not directional"),
               _ff(expr=_x_whip, level="near", gap="5-tap blur, slight ghosting at 1080p; slow (per-pixel expr)"),
               aliases=("whip-pan", "whippan")),
    "flash": _s("Flash to warm white and out", 0.5, (_p_flash, "exact", ""),
                _hf("fade", custom=True), _ff("fadewhite", level="near", gap="pure white, not warm white"),
                aliases=("fadewhite", "white-flash")),
    "fadeblack": _s("Dip to black", 0.6, (_p_fadeblack, "exact", ""), _hf("fade", custom=True),
                    _ff("fadeblack"), aliases=("dip", "dip-to-black")),
    "light-leak": _s("Cross-dissolve under a warm film light leak", 0.7, (_p_leak, "exact", ""),
                     _hf("fade", custom=True, level="near", gap="CSS radial gradients with screen blend"),
                     _ff(expr=_x_leak, level="near", gap="leak added in YUV (luma + warm chroma shift)"),
                     aliases=("leak", "lightleak")),
    "ink": _s("Organic ink-bleed mask reveals the next shot", 0.6,
              (_p_ink, "exact", ""), _hf("blur", level="approx",
                                         gap="no organic mask; needs an SVG feTurbulence mask"),
              _ff(expr=_x_ink, level="near", gap="sine-field blotches instead of noise")),
    "blinds": _s("9 vertical blinds open left to right in a wave", 0.55, (_p_blinds, "exact", ""),
                 _hf("blocks", level="approx", gap="blocks covers with colour instead of revealing B"),
                 _ff(expr=_x_blinds)),
    "tear": _s("Torn-paper edge sweeps across with a paper band", 0.55, (_p_tear, "exact", ""),
               _hf("push", level="approx", gap="no torn edge"),
               _ff("wipeleft", level="approx", gap="straight edge, no paper band or shadow")),
    "slideup": _s("Incoming slides up over the dimming outgoing", 0.45, (_p_slideup, "exact", ""),
                  _hf("vpush", custom=True), _ff("coverup", level="near", gap="outgoing is not dimmed",
                                                  fallback="slideup"), aliases=("coverup",)),
    "cut": _s("Hard cut (no transition)", 0.0, (_p_cut, "exact", ""), _hf("fade", custom=True),
              _ff("fade", level="near", gap="use xfade=0 in xfade_assemble for a true cut (concat)"),
              aliases=("hard", "none")),
    "wipe": _s("Hard edge wipes right to left", 0.5, (_p_wipe, "exact", ""), _hf("iris", custom=True),
               _ff("wipeleft"), aliases=("wipeleft",)),
    "dissolve": _s("Per-pixel random dissolve", 0.6, (_p_dissolve, "exact", ""),
                   _hf("fade", level="approx", gap="no per-pixel noise"), _ff("dissolve")),
    "pixelize": _s("Pixelate up, swap, pixelate down", 0.6, (_p_pixelize, "exact", ""),
                   _hf("chroma", level="approx", gap="stepped glitch instead of pixel blocks"), _ff("pixelize")),
    "radial": _s("Clock-hand sweep from 12 o'clock", 0.8, (_p_radial, "exact", ""),
                 _hf("iris", level="approx", gap="circle grows; no conic sweep"), _ff("radial"),
                 aliases=("clock", "clock-wipe")),
}

NAMES = tuple(SPECS)
ALIASES = {al: n for n, s in SPECS.items() for al in s["aliases"]}
HF_NATIVE = ("blur", "fade", "push", "vpush", "iris", "zoom", "focus", "blocks", "chroma", "flip", "zoomout")
_HF_CUSTOM = ("whip", "flash", "fadeblack", "light-leak", "slideup", "wipe", "cut")


def names():
    return NAMES


def resolve(name):
    """Canonical transition name for ``name`` or one of its aliases (case-insensitive)."""
    n = str(name).strip().lower().replace("_", "-")
    if n in SPECS:
        return n
    if n in ALIASES:
        return ALIASES[n]
    raise KeyError(f"unknown transition {name!r}; one of {', '.join(NAMES)}")


def spec(name):
    return SPECS[resolve(name)]


def default_duration(name):
    return spec(name)["duration"]


# ---------------------------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------------------------

def blend(name, a, b, p, peak=None, **opts):
    """Per-frame transition between float frames ``a`` (outgoing) and ``b`` (incoming), (H, W, 3).
    p in [0, 1]: 0 -> A, 1 -> B (exact copies). ``peak`` = white level (255 or 1.0; auto by default).
    Extra opts go to the implementation (e.g. ``blur=0.05`` for whip, ``strength`` for light-leak)."""
    fn = spec(name)["pil"][0]
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    if a.shape != b.shape:
        raise ValueError(f"frame shapes differ: {a.shape} vs {b.shape}")
    p = float(p)
    if p <= 0:
        return a.copy()
    if p >= 1:
        return b.copy()
    pk = _peak(a, b, peak)
    return np.asarray(fn(a, b, p, _ease(p), pk, **opts), np.float32)


@functools.lru_cache(maxsize=1)
def ffmpeg_builtins():
    """xfade transition names the installed ffmpeg knows (empty set if ffmpeg is missing)."""
    try:
        from . import media
        exe = media.ffmpeg_bin()
    except Exception:
        exe = "ffmpeg"
    try:
        out = subprocess.run([exe, "-hide_banner", "-h", "filter=xfade"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return frozenset()
    return frozenset(re.findall(r"^\s{5}([a-z]+)\s+-?\d+\s", out, re.M))


def ffmpeg_transition(name, check=True, **opts):
    """Value for ``cut.xfade_assemble(transition=...)``: a built-in xfade name, or
    ``custom:expr='...'`` for transitions ffmpeg has no built-in for. ``check`` swaps in the fallback
    built-in when the installed ffmpeg is too old for the preferred one (e.g. coverup < ffmpeg 7)."""
    ff = spec(name)["ffmpeg"]
    if ff["expr"] is not None:
        return f"custom:expr='{ff['expr'](**opts)}'"
    t = ff["xfade"]
    if check and ff.get("fallback"):
        have = ffmpeg_builtins()
        if have and t not in have:
            t = ff["fallback"]
    return t


def ffmpeg_expr(name, duration, offset, fps=30, **opts):
    """A complete ``xfade=...`` filter for ``[a][b]xfade=...[out]`` graphs. ``cut`` gets one frame."""
    d = float(duration)
    if resolve(name) == "cut":
        d = 1.0 / fps
    return f"xfade=transition={ffmpeg_transition(name, **opts)}:duration={d:.4f}:offset={float(offset):.4f}"


def hf_type(name):
    """Closest ``hf.TRANSITIONS`` type (for code that can only call ``hf.transition``)."""
    return spec(name)["hf"]["type"]


def hf_transitions(items, W=1920, H=1080, wrap=".scene-wrap", **kw):
    """HyperFrames scene transitions for any bridge name. items: (name, out_id, in_id, at, d) tuples
    or ``hf.transition``-style dicts {type, o, i, T, d}. Native names go through ONE
    ``hf.scene_transitions`` call (extra kw: blocks, block_color, ...); bridge-only names (whip, flash,
    fadeblack, light-leak, slideup, wipe, cut) get their own GSAP here. Approximate names (ink, blinds,
    tear, dissolve, pixelize, radial) fall back to their closest native type. Returns {"css","html","js"}."""
    from . import hf
    native, extra = [], {"css": "", "html": "", "js": ""}
    for k, it in enumerate(items):
        if isinstance(it, dict):
            nm, o, i, T, d = it["type"], it["o"], it["i"], it["T"], it["d"]
        else:
            nm, o, i, T, d = it
        n = resolve(nm)
        if n in _HF_CUSTOM:
            c, h, j = _hf_custom(n, o, i, float(T), float(d), k, W, H)
            extra["css"] += c
            extra["html"] += h
            extra["js"] += j
        else:
            native.append(hf.transition(hf_type(n), o, i, T, d))
    out = hf.scene_transitions(native, W=W, H=H, wrap=wrap, **kw) if native else {"css": "", "html": "", "js": ""}
    return {key: out[key] + extra[key] for key in ("css", "html", "js")}


def coverage():
    """{name: {engine: "exact" | "near" | "approx"}} for hyperframes / ffmpeg / pil-frame."""
    out = {}
    for n, s in SPECS.items():
        out[n] = {"hyperframes": s["hf"]["level"], "ffmpeg": s["ffmpeg"]["level"], "pil-frame": s["pil"][1]}
    return out


def gaps():
    """[(name, engine, level, what is missing)] for every non-exact cell."""
    rows = []
    for n, s in SPECS.items():
        for eng, lvl, gap in (("hyperframes", s["hf"]["level"], s["hf"]["gap"]),
                              ("ffmpeg", s["ffmpeg"]["level"], s["ffmpeg"]["gap"]),
                              ("pil-frame", s["pil"][1], s["pil"][2])):
            if lvl != "exact" or gap:
                rows.append((n, eng, lvl, gap))
    return rows


def _ff_cell(s):
    ff = s["ffmpeg"]
    impl = f"`{ff['xfade']}`" if ff["xfade"] else "custom expr"
    return f"{impl} ({ff['level']})"


def _hf_cell(n, s):
    h = s["hf"]
    impl = "bridge GSAP" if n in _HF_CUSTOM else f"`{h['type']}`"
    return f"{impl} ({h['level']})"


def coverage_markdown():
    """Markdown matrix: name | default s | HyperFrames | ffmpeg xfade | PIL | gaps."""
    lines = ["| Transition | Default s | HyperFrames | ffmpeg xfade | PIL `blend` | Gaps |",
             "|---|---|---|---|---|---|"]
    for n, s in SPECS.items():
        gl = "; ".join(f"{e}: {g}" for (m, e, _, g) in gaps() if m == n and g) or "-"
        al = f" ({', '.join(s['aliases'])})" if s["aliases"] else ""
        lines.append(f"| `{n}`{al} | {s['duration']:g} | {_hf_cell(n, s)} | {_ff_cell(s)} | {s['pil'][1]} | {gl} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(coverage_markdown())
