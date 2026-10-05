"""Frame sources and frame effects for the fun travel vlog (everything on BGR uint8 canvases).

Shot frames
  * video: one ffmpeg decode of the needed source span (HDR->SDR + grade in the ffmpeg chain), each
    output frame picks its SOURCE time from the shot's time map (speed ramps, slow-mo, tightened speech),
    then the frame is fitted to the canvas: same aspect -> resize; otherwise vstudio.reframe (face mode,
    pad-blur or centre-crop fallback for faceless scenery). Slow-mo on a 120/60 fps source uses real
    frames; on 24/30 fps it blends the two neighbouring frames (and the plan warns).
  * photo: Ken Burns on a cover-fitted still ("full") or a white-bordered photo card dropping onto a
    blurred copy of itself ("card"). HEIC via pillow-heif, else macOS ``sips`` (cached JPEG).
  * freeze: the last ``freeze`` seconds of a video shot hold its frame as a photo card (shutter).

Transitions (applied around a hard cut that stays ON the beat frame; frames are borrowed half from each
neighbour, A5): whip (directional translate + box motion blur, peak >= 300 px/frame), zoom (punch:
A pushes in, B lands from 1.16x), flash (white hidden cut), leak (warm light leak, screen blend), glitch
(RGB split + band displacement), cut (nothing).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
import hashlib
import math
import os
import shutil
import subprocess

import numpy as np

from vstudio import media

WHIP_MIN_PEAK = 300.0         # px per frame at the cut (whip-pan rule: below this the swap shows)


# ----------------------------------------------------------------------------- time maps
def smooth_rate(keys, u):
    """Rate at normalised time u from [[u, rate], ...] keys, smoothstep-eased between keys (no kinks)."""
    keys = sorted((float(a), float(b)) for a, b in keys)
    if u <= keys[0][0]:
        return keys[0][1]
    for (u0, r0), (u1, r1) in zip(keys, keys[1:]):
        if u <= u1:
            v = (u - u0) / max(1e-9, u1 - u0)
            v = v * v * (3 - 2 * v)
            return r0 + (r1 - r0) * v
    return keys[-1][1]


RAMPS = {
    "slow-fast": [[0, 0.3], [0.5, 0.3], [0.72, 2.2], [1, 2.2]],
    "fast-slow": [[0, 2.2], [0.3, 2.2], [0.52, 0.3], [1, 0.3]],
    "fast-slow-fast": [[0, 2.2], [0.22, 2.2], [0.38, 0.3], [0.62, 0.3], [0.78, 2.2], [1, 2.2]],
}


def ramp_keys(spec, src_fps, speed=1.0):
    """edit.json ``ramp`` -> keys. "slowmo" = constant true slow-mo (30/src_fps, >= 0.2)."""
    if spec in (None, False):
        return [[0, speed], [1, speed]]
    if spec == "slowmo" or spec is True:
        r = max(0.2, min(1.0, 30.0 / max(1.0, src_fps or 30.0)))
        return [[0, r], [1, r]]
    if isinstance(spec, str):
        if spec not in RAMPS:
            raise ValueError(f"ramp {spec!r}: one of slowmo, {', '.join(RAMPS)} or [[u, rate], ...]")
        return RAMPS[spec]
    return [[float(a), float(b)] for a, b in spec]


def src_span_of(keys, D, fine=2000):
    u = (np.arange(fine) + 0.5) / fine
    return float(D * np.mean([smooth_rate(keys, v) for v in u]))


def ramp_times(keys, D, n, src_start):
    """Source time for each of n output frames of a D-second shot (rate integral)."""
    fine = max(400, n * 8)
    u = np.linspace(0, 1, fine + 1)
    r = np.array([smooth_rate(keys, v) for v in u])
    cum = np.concatenate([[0.0], np.cumsum((r[1:] + r[:-1]) / 2 * np.diff(u))]) * D
    uk = np.arange(n) / max(1, n) if n else np.zeros(0)
    return src_start + np.interp(uk, u, cum)


def piece_times(pieces, n, fps):
    """Concatenated source pieces [(a, b)] at rate 1 -> source time per output frame (holds the last
    source time when the output is longer)."""
    lens = np.array([b - a for a, b in pieces])
    cum = np.concatenate([[0.0], np.cumsum(lens)])
    out = np.empty(n)
    for k in range(n):
        tau = k / fps
        i = int(np.searchsorted(cum, tau, side="right") - 1)
        if i >= len(pieces):
            out[k] = pieces[-1][1] + (tau - cum[-1])
        else:
            out[k] = pieces[i][0] + (tau - cum[i])
    return out


# ----------------------------------------------------------------------------- grade
DEFAULT_FUN_GRADE = {"brightness": 0.02, "contrast": 1.08, "saturation": 1.2, "gamma": 1.0}
COLORBALANCE = "colorbalance=rs=0.02:rm=0.02:bm=-0.02:bs=-0.03:rh=0.01:bh=-0.02"


def grade_chain(grade, warm=True, sharpen=True, extra_bright=0.0):
    g = grade
    parts = [f"eq=brightness={g['brightness'] + extra_bright:.3f}:contrast={g['contrast']}"
             f":saturation={g['saturation']}:gamma={g['gamma']}"]
    if warm:
        parts.append(COLORBALANCE)
    if sharpen:
        parts.append("unsharp=5:5:0.4:5:5:0.0")
    return ",".join(parts)


# ----------------------------------------------------------------------------- canvas fitting
def _fit_resize(fr, W, H):
    import cv2
    h, w = fr.shape[:2]
    s = max(W / w, H / h)
    nw, nh = max(W, int(round(w * s))), max(H, int(round(h * s)))
    r = cv2.resize(fr, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    y, x = (nh - H) // 2, (nw - W) // 2
    return np.ascontiguousarray(r[y:y + H, x:x + W])


def make_fitter(src, info, W, H, mode, fallback, safe, start, dur, cache):
    """(fn(i, frame) -> canvas, plan_summary). Same aspect (within 1 %) -> cover resize."""
    from vstudio import reframe as R
    sw, sh = info["display_w"], info["display_h"]
    if abs(math.log((sw / sh) / (W / H))) < 0.01 or mode == "crop":
        if mode == "crop" and abs(math.log((sw / sh) / (W / H))) >= 0.01:
            return (lambda i, fr: _fit_resize(fr, W, H)), dict(mode="crop", mode_used="crop")
        return (lambda i, fr: _fit_resize(fr, W, H)), dict(mode="scale", mode_used="scale")
    key = hashlib.sha1(f"{os.path.abspath(src)}|{start:.3f}|{dur:.3f}|{W}x{H}|{mode}|{fallback}|{safe}".encode()).hexdigest()[:16]
    pl = cache.get(key)
    if pl is None:
        pl = R.plan(src, W, H, mode=mode, safe=safe, start=start, dur=dur, fallback=fallback)
        cache[key] = pl
    return R.frame_fn(pl), dict(mode=mode, mode_used=pl["mode_used"], hit_rate=pl.get("hit_rate"),
                                reason=pl.get("fallback_reason"))


# ----------------------------------------------------------------------------- video decode
def decode_frames(src, start, dur, vf=""):
    """Generator of (index, BGR frame) for [start, start+dur) at the source rate (display orientation)."""
    info = media.probe(src)
    w, h = info["display_w"], info["display_h"]
    cmd = [media.ffmpeg_bin(), "-v", "error", "-ss", f"{max(0.0, start):.4f}", "-t", f"{dur:.4f}",
           "-i", os.fspath(src), "-map", "0:v:0"]
    if vf:
        cmd += ["-vf", vf]
    cmd += ["-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * 3
    i = 0
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield i, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            i += 1
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def video_shot_frames(src, src_times, W, H, fitter_args, vf="", blend=True, freeze_from=None, card=None,
                      report=None):
    """Yield one canvas frame per entry of ``src_times`` (monotonic source seconds).

    fitter_args: kwargs for ``make_fitter`` except start/dur. freeze_from: output index from which the last
    live frame is held as a photo card (``card(still, k_since_freeze)``). report: dict that receives the
    fitter summary (reframe mode used, face hit rate)."""
    info = media.probe(src)
    fps_src = info["fps"] or 30.0
    lim = max(0.0, (info["duration"] or 1e9) - 1.0 / fps_src)
    st = np.clip(np.asarray(src_times, float), 0.0, lim)
    live = st if freeze_from is None else st[:max(1, freeze_from)]
    a = float(live.min())
    b = float(live.max()) + 3.0 / fps_src
    fit, summary = make_fitter(src, info, W, H, start=a, dur=b - a, **fitter_args)
    if report is not None:
        report.update(summary)
    it = decode_frames(src, a, b - a, vf)
    buf, state = {}, dict(max_i=-1, done=False)

    def need(i):
        while not state["done"] and state["max_i"] < i:
            try:
                j, fr = next(it)
            except StopIteration:
                state["done"] = True
                break
            buf[j] = fr
            state["max_i"] = j

    last, still = None, None
    try:
        for k, s in enumerate(st):
            if freeze_from is not None and k >= freeze_from:
                if still is None:
                    still = last if last is not None else np.zeros((H, W, 3), np.uint8)
                yield card(still, k - freeze_from)
                continue
            x = (s - a) * fps_src
            i0 = int(math.floor(x + 1e-6))
            w = x - i0
            need(i0 + 1)
            for j in [j for j in buf if j < i0]:
                del buf[j]
            if not buf:
                img = last if last is not None else np.zeros((H, W, 3), np.uint8)
            else:
                f0 = buf.get(i0, buf[max(buf)] if i0 > max(buf) else buf[min(buf)])
                f1 = buf.get(i0 + 1, f0)
                if blend and fps_src < 50 and 0.2 < w < 0.8 and f1 is not f0:
                    fr = ((f0.astype(np.uint16) + f1.astype(np.uint16)) // 2).astype(np.uint8)
                    idx = i0
                elif w >= 0.5:
                    fr, idx = f1, i0 + 1
                else:
                    fr, idx = f0, i0
                img = fit(idx, fr)
            last = img
            yield img
    finally:
        it.close()


# ----------------------------------------------------------------------------- photos
def load_photo(path, cache_dir):
    """RGB uint8 array; HEIC/HEIF via pillow-heif when installed, else macOS ``sips`` to a cached JPEG."""
    from PIL import Image, ImageOps
    p = os.fspath(path)
    if os.path.splitext(p)[1].lower() in (".heic", ".heif"):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            out = os.path.join(cache_dir, "heic", hashlib.sha1(os.path.abspath(p).encode()).hexdigest()[:12] + ".jpg")
            if not os.path.exists(out):
                if not shutil.which("sips"):
                    raise RuntimeError(f"{p}: HEIC needs `pip install pillow-heif` (or macOS sips)")
                os.makedirs(os.path.dirname(out), exist_ok=True)
                subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", p, "--out", out],
                               check=True, capture_output=True)
            p = out
    im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    return np.asarray(im)


def _cover(img, W, H, zoom=1.0, cx=0.5, cy=0.5):
    import cv2
    h, w = img.shape[:2]
    s = max(W / w, H / h) * zoom
    M = np.float32([[s, 0, W / 2 - cx * w * s], [0, s, H / 2 - cy * h * s]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)


def photo_card_layer(img_bgr, W, H, unit, angle=-3.0):
    """White-bordered photo card (thicker bottom) with a soft shadow, as RGBA (BGR order kept in RGB slots)."""
    from PIL import Image
    from vstudio import draw as D
    h, w = img_bgr.shape[:2]
    maxw, maxh = W * 0.74, H * 0.6
    s = min(maxw / w, maxh / h)
    pw, ph = int(w * s), int(h * s)
    import cv2
    ph_img = cv2.resize(img_bgr, (pw, ph), interpolation=cv2.INTER_AREA)
    b = int(18 * unit)
    card = np.full((ph + b + int(b * 3.2), pw + 2 * b, 4), 255, np.uint8)
    card[b:b + ph, b:b + pw, :3] = ph_img[..., ::-1]           # to RGB for PIL
    im = Image.fromarray(card, "RGBA").rotate(angle, expand=True, resample=Image.BICUBIC)
    im, pad = D.shadow(im, blur=int(14 * unit), offset=(0, int(10 * unit)), alpha=130)
    return np.asarray(im)


def card_renderer(W, H, unit, angle=-3.0, flash=True):
    """card(still_bgr, k) for freeze frames: blurred dimmed still behind, the still as a dropping card."""
    import cv2
    from vstudio import draw as D
    state = {}

    def card(still, k):
        if "bg" not in state:
            sm = cv2.resize(still, (max(8, W // 10), max(8, H // 10)), interpolation=cv2.INTER_AREA)
            sm = cv2.GaussianBlur(sm, (0, 0), 2.5)
            state["bg"] = (cv2.resize(sm, (W, H)).astype(np.float32) * 0.6).astype(np.uint8)
            state["card"] = photo_card_layer(still, W, H, unit, angle)
        img = state["bg"].copy()
        u = min(1.0, k / 8.0)
        s = 1.12 - 0.12 * (1 - (1 - u) ** 3)
        c = state["card"]
        if abs(s - 1) > 1e-3:
            c = cv2.resize(c, (int(c.shape[1] * s), int(c.shape[0] * s)), interpolation=cv2.INTER_LINEAR)
        D.alpha_paste(img, c[..., [2, 1, 0, 3]], (W / 2, H * 0.46), center=True, bgr=True)
        if flash and k < 3:
            a = (0.75, 0.4, 0.15)[k]
            img = (img.astype(np.float32) * (1 - a) + 255 * a).astype(np.uint8)
        return img
    return card


def photo_frames(photo_rgb, n, W, H, unit, style="card", k_index=0, fps=30):
    """Ken Burns frames for a still: zoom 1.0 -> 1.1 (alternating direction), card drop for style card."""
    import cv2
    from vstudio import draw as D
    bgr = photo_rgb[..., ::-1].copy()
    z0, z1 = (1.0, 1.1) if k_index % 2 == 0 else (1.1, 1.0)
    dx = 0.03 if k_index % 2 == 0 else -0.03
    if style == "full":
        for k in range(n):
            u = k / max(1, n - 1)
            e = u * u * (3 - 2 * u)
            yield _cover(bgr, W, H, z0 + (z1 - z0) * e, 0.5 + dx * e, 0.5)
        return
    sm = cv2.resize(bgr, (max(8, W // 10), max(8, int(bgr.shape[0] * (W // 10) / bgr.shape[1]))),
                    interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), 2.5)
    card = photo_card_layer(bgr, W, H, unit, angle=-3.0 if k_index % 2 == 0 else 3.0)[..., [2, 1, 0, 3]]
    for k in range(n):
        u = k / max(1, n - 1)
        e = u * u * (3 - 2 * u)
        bg = _cover(sm, W, H, z0 + (z1 - z0) * e, 0.5 + dx * e, 0.5)
        bg = (bg.astype(np.float32) * 0.62).astype(np.uint8)
        d = min(1.0, k / 7.0)
        s = (1.14 - 0.14 * (1 - (1 - d) ** 3)) * (1.0 + 0.04 * e)
        c = cv2.resize(card, (int(card.shape[1] * s), int(card.shape[0] * s)), interpolation=cv2.INTER_LINEAR)
        D.alpha_paste(bg, c, (W / 2, H * 0.46), center=True, bgr=True)
        yield bg


def soft_bg(img, factor=12, dim=0.7):
    """Heavily blurred, dimmed copy of a frame (background under a full card)."""
    import cv2
    H, W = img.shape[:2]
    sm = cv2.resize(img, (max(8, W // factor), max(8, H // factor)), interpolation=cv2.INTER_AREA)
    sm = cv2.GaussianBlur(sm, (0, 0), 1.6)
    return (cv2.resize(sm, (W, H), interpolation=cv2.INTER_LINEAR).astype(np.float32) * dim).astype(np.uint8)


# ----------------------------------------------------------------------------- transitions
def trans_frames(kind, fps):
    """(frames before the cut, frames from the cut on) a transition borrows from its neighbours."""
    k = max(2, int(round(4 * fps / 30)))
    return {"whip": (k, k), "zoom": (max(2, k - 1), k + 2), "flash": (2, k + 3), "leak": (k + 1, k + 2),
            "glitch": (3, 3), "cut": (0, 0)}.get(kind, (0, 0))


def whip_params(W, fps):
    k = trans_frames("whip", fps)[0]
    dist = max(0.6 * W, WHIP_MIN_PEAK * k / 2 * 1.1)
    return k, dist, 2 * dist / k               # frames per side, travel, peak px/frame


def apply_transition(img, kind, off, fps, direction=1, seed=0):
    """Effect for the frame ``off`` frames from the cut (negative = before, 0 = first frame of B)."""
    import cv2
    H, W = img.shape[:2]
    pre, post = trans_frames(kind, fps)
    if kind == "cut" or off < -pre or off >= post:
        return img
    if kind == "whip":
        k, dist, _ = whip_params(W, fps)
        if off < 0:
            p = (k + off + 1) / k                   # 1/k .. 1 approaching the cut
            x, v = -direction * dist * p * p, 2 * dist * p / k
        else:
            q = 1 - off / k                         # 1 .. 1/k after the cut
            x, v = direction * dist * q * q, 2 * dist * q / k
        M = np.float32([[1, 0, x], [0, 1, 0]])
        out = cv2.warpAffine(img, M, (W, H), borderMode=cv2.BORDER_REFLECT_101)
        L = int(min(W * 0.6, v * 0.9))
        if L >= 3:
            out = cv2.blur(out, (L, 1))
        return out
    if kind == "zoom":
        if off < 0:
            p = (pre + off + 1) / pre
            s = 1.0 + 0.10 * p * p
            out = _zoom(img, s)
            out = cv2.addWeighted(out, 0.6, _zoom(img, s * 1.04), 0.4, 0)
        else:
            u = off / max(1, post - 1)
            s = 1.0 + 0.16 * (1 - u) ** 2.2
            out = _zoom(img, s)
            if off == 0:
                out = cv2.add(out, np.full_like(out, 28))
        return out
    if kind == "flash":
        if off < 0:
            a = (0.3, 0.65)[min(1, pre + off)] if pre >= 2 else 0.6
        else:
            a = 0.97 * math.exp(-off / 1.6)
        return (img.astype(np.float32) * (1 - a) + 255 * a).astype(np.uint8)
    if kind == "leak":
        a = 0.88 * math.exp(-(off / 3.0) ** 2)
        pos = (off + pre) / (pre + post)
        yy, xx = np.mgrid[0:H:8, 0:W:8].astype(np.float32)
        cx, cy = W * (-0.1 + 1.2 * pos), H * 0.35
        r = np.sqrt((xx - cx) ** 2 + ((yy - cy) * 0.8) ** 2) / max(W, H)
        f = np.clip(1.15 - r * 1.6, 0, 1)
        leak = np.stack([f * 60 + 40, f * 140 + 60, np.full_like(f, 255)], -1) * f[..., None]
        leak = cv2.resize(leak, (W, H), interpolation=cv2.INTER_LINEAR) * a
        base = img.astype(np.float32)
        out = 255 - (255 - base) * (255 - leak) / 255
        if abs(off) <= 1:
            out = out * 0.5 + 255 * 0.5 * a
        return np.clip(out, 0, 255).astype(np.uint8)
    if kind == "glitch":
        g = 1 - abs(off + 0.5) / 4
        rng = np.random.default_rng(seed * 101 + off + 50)
        dx = int(18 * g * W / 1080) + 2
        out = img.copy()
        out[..., 2] = np.roll(img[..., 2], dx, axis=1)
        out[..., 0] = np.roll(img[..., 0], -dx, axis=1)
        for _ in range(8):
            h = int(H * rng.uniform(0.02, 0.08))
            y = int(rng.uniform(0, H - h))
            out[y:y + h] = np.roll(out[y:y + h], int(rng.uniform(-1, 1) * 60 * g * W / 1080), axis=1)
        return out
    return img


def _zoom(img, s):
    import cv2
    H, W = img.shape[:2]
    M = np.float32([[s, 0, W / 2 * (1 - s)], [0, s, H / 2 * (1 - s)]])
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)
