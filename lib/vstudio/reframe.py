"""Reframe a video to another canvas: face-tracked virtual camera, centre crop, blurred-fill or letterbox.

    from vstudio import reframe as R
    plan = R.plan("talk-16x9.mp4", 1080, 1440, mode="face", safe=(48, 60, 1032, 1290))
    R.render("talk-16x9.mp4", "talk-3x4.mp4", plan)            # rawvideo pipe: decode -> warp -> encode
    R.reframe("talk-16x9.mp4", "talk-9x16.mp4", 1080, 1920)     # plan + render + <dst>.crop.json

    python -m vstudio.reframe talk.mp4 out.mp4 --size 1080x1920 --mode face [--platform douyin]

Modes
  face       the main face is kept inside the target ``safe`` box (target px; e.g. platform.safe_box) with
             the eye line ~1/3 down it (headroom rule). Faces are detected every ``every`` frames
             (MediaPipe via vstudio.face, or any ``detector(bgr) -> [(x0, y0, x1, y1[, talk])]``), the target
             is One-Euro filtered (vstudio.filters), then followed by a virtual camera with a dead zone (small
             moves never drift the crop), an acceleration-limited eased pan and a max pan speed. Shot cuts
             (frame-difference spikes) reset the camera: a hard cut never becomes a pan. Several faces: the
             largest / most-talking (mouth-movement energy, as face.talk_activity) is followed; switching
             needs a sustained lead (``switch_hold`` s) and is done as an eased pan.
             No face found (hit rate < ``min_hit``) -> ``fallback`` mode ("pad-blur" by default).
  center     fixed centre crop.  pad-blur  fit inside, blurred+dimmed fill behind.  letterbox  fit on black.

The plan is plain JSON: per-frame crop rects [x, y, w, h] in source pixels (float, sub-pixel; render uses
cv2.warpAffine so slow pans don't step).
"""
import argparse
import json
import math
import os
import subprocess
import sys

import numpy as np

from . import media

MODES = ("face", "center", "pad-blur", "letterbox")

DEFAULTS = dict(
    every=None,            # detect every N frames (default ~6 Hz)
    analysis_w=960,        # detection frame width
    max_faces=3,
    zoom=1.0,              # >1 = tighter crop than the largest box of the target aspect
    headroom=1 / 3,        # eye line at this fraction down the safe box
    dead_zone=0.06,        # fraction of the crop size the target may move before the camera follows
    settle=0.015,          # once moving, stop when within this fraction (hysteresis)
    gain=3.0,              # 1/s: camera speed per unit of error beyond the dead zone
    max_speed=0.45,        # crop widths (or heights) per second
    max_accel=1.2,         # crop widths per second^2 (eases pans in and out)
    min_cutoff=0.6, beta=0.6,   # One Euro on the normalised target
    cut_thresh=28.0,       # mean abs diff (0-255) of 64x36 grey thumbnails that counts as a shot cut
    switch_margin=0.20,    # challenger score lead needed to switch subject
    switch_hold=1.5,       # ... held for this many seconds
    lost_hold=1.0,         # keep framing the last face position this long after it disappears
    talk_weight=0.5,       # weight of mouth-movement energy vs face size in the subject score
    min_hit=0.15,          # below this face hit rate -> fallback
    fallback="pad-blur",
    blur_dim=0.72,
)


# ----------------------------------------------------------------------------------- geometry
def crop_size(sw, sh, tw, th, zoom=1.0):
    """Largest (w, h) of the target aspect inside a sw x sh source, divided by zoom."""
    ta = tw / th
    if sw / sh > ta:
        ch, cw = sh, sh * ta
    else:
        cw, ch = sw, sw / ta
    return cw / zoom, ch / zoom


def _fit(sw, sh, tw, th):
    s = min(tw / sw, th / sh)
    w, h = max(2, int(round(sw * s / 2)) * 2), max(2, int(round(sh * s / 2)) * 2)
    return w, h, (tw - w) // 2, (th - h) // 2


def _desired(face_box, cw, ch, sw, sh, tw, safe, headroom):
    """Crop top-left (x, y) that puts a face box inside the safe box with the eye line at headroom."""
    fx0, fy0, fx1, fy1 = face_box
    s = tw / cw
    sx0, sy0, sx1, sy1 = (v / s for v in safe)
    fcx = (fx0 + fx1) / 2
    eye = fy0 + 0.42 * (fy1 - fy0)                         # landmark box: forehead..chin, eyes ~0.42
    x = fcx - (sx0 + sx1) / 2
    y = eye - (sy0 + (sy1 - sy0) * headroom)
    lo, hi = fx1 - sx1, fx0 - sx0                          # keep the whole face inside the safe box
    if lo <= hi:
        x = min(max(x, lo), hi)
    lo, hi = fy1 - sy1, fy0 - sy0
    if lo <= hi:
        y = min(max(y, lo), hi)
    return min(max(x, 0.0), sw - cw), min(max(y, 0.0), sh - ch)


# ----------------------------------------------------------------------------------- detection
def _face_detector(max_faces, analysis_w):
    from . import face
    lm = face.landmarker(max_faces, video=True)

    def det(bgr, ts_ms):
        import cv2
        h, w = bgr.shape[:2]
        k = min(1.0, analysis_w / w)
        small = cv2.resize(bgr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else bgr
        out = []
        for f in face.detect(lm, np.ascontiguousarray(small), ts_ms):
            p = f["pts"] / k
            out.append((float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()),
                        face.mouth_gap(f["pts"])))
        return out
    det.close = lm.close
    return det


def _scan(src, start, dur, every, detector, cut_thresh=None):
    """One decode pass: per-frame thumbnail differences + detections at sample frames (and right after a
    cut). Returns fps, n, sw, sh, diffs[n], samples {i: [(x0, y0, x1, y1, talk|None)]}."""
    import cv2
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if start:
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    n_max = int(round(dur * fps)) if dur else None
    diffs, samples, prev, i, sw, sh, force = [], {}, None, 0, 0, 0, False
    try:
        while n_max is None or i < n_max:
            ok, fr = cap.read()
            if not ok:
                break
            sh, sw = fr.shape[:2]
            th = cv2.resize(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY), (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)
            d = float(np.abs(th - prev).mean()) if prev is not None else 0.0
            diffs.append(d)
            prev = th
            if d > 0 and i > 0 and _is_cut(diffs, i, cut_thresh):
                force = True
            if i % every == 0 or force:
                res = detector(fr, int(round(i / fps * 1000))) if _takes_ts(detector) else detector(fr)
                samples[i] = [tuple(b) + (None,) * (5 - len(b)) for b in (res or [])]
                force = False
            i += 1
    finally:
        cap.release()
    return fps, i, sw, sh, diffs, samples


def _takes_ts(fn):
    try:
        import inspect
        return len(inspect.signature(fn).parameters) >= 2
    except (TypeError, ValueError):
        return False


def _is_cut(diffs, i, thresh=None):
    t = thresh if thresh is not None else DEFAULTS["cut_thresh"]
    d = diffs[i]
    if d < t:
        return False
    recent = diffs[max(1, i - 15):i]
    base = float(np.median(recent)) if recent else 0.0
    return d > 3.0 * base + 4.0


def shot_cuts(diffs, thresh=None):
    """Frame indices that start a new shot (frame-difference spikes)."""
    return [i for i in range(1, len(diffs)) if _is_cut(diffs, i, thresh)]


# ----------------------------------------------------------------------------------- subject choice
def _choose_subjects(samples, n, fps, cuts, sw, sh, o):
    """Per-sample chosen face box (or None), tracking identities by proximity; switches need a sustained
    lead. Returns {i: box}, number of switches."""
    order = sorted(samples)
    cutset = sorted(cuts)
    tracks, cur, chosen, switches = [], None, {}, 0
    lead_since = {}
    hist_n = max(3, int(round(0.8 * fps / max(1, o["every"]))))
    seg_of = lambda i: sum(1 for c in cutset if c <= i)
    last_seg = None
    for i in order:
        seg = seg_of(i)
        if seg != last_seg:                           # new shot: forget everything
            tracks, cur, lead_since, last_seg = [], None, {}, seg
        faces = samples[i]
        # associate
        used = set()
        for tr in tracks:
            bx = tr["box"]; cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2; sz = max(bx[2] - bx[0], 1)
            best, bd = None, 0.6 * sz
            for k, f in enumerate(faces):
                if k in used:
                    continue
                d = math.hypot((f[0] + f[2]) / 2 - cx, (f[1] + f[3]) / 2 - cy)
                if d < bd:
                    best, bd = k, d
            if best is not None:
                used.add(best); f = faces[best]
                tr.update(box=f[:4], seen=i)
                if f[4] is not None:
                    tr["talk"].append(f[4]); tr["talk"] = tr["talk"][-hist_n:]
        for k, f in enumerate(faces):
            if k not in used:
                tracks.append(dict(id=len(tracks) + 1000 * seg, box=f[:4], seen=i,
                                   talk=[f[4]] if f[4] is not None else []))
        lost_frames = o["lost_hold"] * fps
        tracks = [t for t in tracks if i - t["seen"] <= lost_frames]
        live = [t for t in tracks if t["seen"] == i]
        if not live:
            chosen[i] = next((t["box"] for t in tracks if cur is not None and t["id"] == cur), None)
            continue
        areas = {t["id"]: (t["box"][2] - t["box"][0]) * (t["box"][3] - t["box"][1]) for t in live}
        energy = {t["id"]: float(np.std(t["talk"])) if len(t["talk"]) >= 3 else 0.0 for t in live}
        amax, emax = max(areas.values()) or 1.0, max(energy.values())
        tw = o["talk_weight"] if emax > 0.004 else 0.0
        score = {k: (1 - tw) * areas[k] / amax + tw * (energy[k] / emax if emax else 0) for k in areas}
        best = max(score, key=score.get)
        if cur is not None and cur not in score:
            held = next((t for t in tracks if t["id"] == cur), None)
            if held is not None:                       # briefly lost (within lost_hold): hold its position
                chosen[i] = held["box"]
                continue
            cur = None
        if cur is None:
            cur, lead_since = best, {}
        elif best != cur and score[best] > score[cur] + o["switch_margin"]:
            t0 = lead_since.setdefault(best, i)
            if (i - t0) / fps >= o["switch_hold"]:
                cur, lead_since, switches = best, {}, switches + 1
        else:
            lead_since = {}
        chosen[i] = next(t["box"] for t in live if t["id"] == cur)
    return chosen, switches


# ----------------------------------------------------------------------------------- camera
def follow(targets, fps, size, o, start=None):
    """Virtual camera over one shot: dead zone + One Euro + accel/speed limits. targets in source px
    (1-D, crop top-left along one axis); size = crop extent along that axis (normaliser)."""
    from .filters import OneEuro
    f = OneEuro(o["min_cutoff"], o["beta"])
    dt = 1.0 / fps
    p = targets[0] if start is None else start
    v, moving, out = 0.0, False, []
    for k, t in enumerate(targets):
        tn = float(f(t / size, k * dt)) * size
        e = tn - p
        a = o["max_accel"] * size * dt
        if moving:
            if abs(e) <= o["settle"] * size and abs(v) <= a * 2:
                moving = False
        elif abs(e) > o["dead_zone"] * size:
            moving = True
        if moving:
            mag = min(abs(e) * o["gain"], o["max_speed"] * size,
                      math.sqrt(2 * o["max_accel"] * size * abs(e)))      # brake in time: eased stop
            want = math.copysign(mag, e)
        else:
            want = 0.0
        v += min(max(want - v, -a), a)
        p += v * dt
        out.append(p)
    return out


def _interp_targets(points, n):
    """{i: value} -> per-frame list (linear between samples, held at the ends)."""
    if not points:
        return None
    xs = sorted(points)
    return list(np.interp(np.arange(n), xs, [points[i] for i in xs]))


# ----------------------------------------------------------------------------------- plan
def plan(src, target_w, target_h, mode="face", safe=None, start=0.0, dur=None, detector=None, **opts):
    """Per-frame crop rects for ``src`` -> target_w x target_h. safe: (x0, y0, x1, y1) in TARGET px
    (default: whole canvas inset 6 %). Returns a JSON-able dict (see module doc); ``mode_used`` says
    what actually ran (face may fall back)."""
    o = dict(DEFAULTS, **{k: v for k, v in opts.items() if v is not None})
    if mode not in MODES:
        raise ValueError(f"mode={mode!r} (one of {MODES})")
    tw, th = int(target_w), int(target_h)
    safe = tuple(safe) if safe else (tw * 0.06, th * 0.06, tw * 0.94, th * 0.94)
    info = media.probe(src)
    fps = info["fps"] or 30.0
    sw, sh = info["display_w"], info["display_h"]
    total = info["duration"] - (start or 0)
    dur = min(dur, total) if dur else total
    n_est = int(round(dur * fps))
    out = dict(src=os.fspath(src), src_w=sw, src_h=sh, fps=fps, start=float(start or 0), dur=dur,
               target=[tw, th], safe=[round(v, 1) for v in safe], mode=mode, mode_used=mode, hit_rate=None,
               cuts=[], switches=0)
    cw, ch = crop_size(sw, sh, tw, th, o["zoom"])
    if mode in ("pad-blur", "letterbox"):
        out.update(crop_w=sw, crop_h=sh, n_frames=n_est, rects=None)
        return out
    cx0, cy0 = (sw - cw) / 2, (sh - ch) / 2
    if mode == "center":
        out.update(crop_w=cw, crop_h=ch, n_frames=n_est, rects=None, fixed=[cx0, cy0, cw, ch])
        return out

    o["every"] = int(o["every"] or max(1, round(fps / 6)))
    own = detector is None
    try:
        det = _face_detector(o["max_faces"], o["analysis_w"]) if own else detector
    except Exception as e:                            # no mediapipe / model: same as "no face found"
        det = lambda fr: []
        det.close = lambda: None
        out["detector_error"] = f"{type(e).__name__}: {e}"
    try:
        fps, n, sw2, sh2, diffs, samples = _scan(src, start, dur, o["every"], det, o["cut_thresh"])
    finally:
        if own:
            det.close()
    if n == 0:
        raise RuntimeError(f"no frames decoded from {src}")
    cuts = shot_cuts(diffs, o["cut_thresh"])
    hits = sum(1 for v in samples.values() if v)
    hit_rate = hits / max(1, len(samples))
    out.update(n_frames=n, cuts=cuts, hit_rate=round(hit_rate, 4), samples=len(samples))
    if hit_rate < o["min_hit"]:
        fb = o["fallback"]
        out["mode_used"] = fb
        out["fallback_reason"] = f"face hit rate {hit_rate:.2f} < {o['min_hit']}"
        if fb == "center":
            out.update(crop_w=cw, crop_h=ch, rects=None, fixed=[cx0, cy0, cw, ch])
        else:
            out.update(crop_w=sw, crop_h=sh, rects=None)
        return out

    chosen, switches = _choose_subjects(samples, n, fps, cuts, sw, sh, o)
    bounds = [0] + cuts + [n]
    xs, ys = [], []
    for a, b in zip(bounds, bounds[1:]):
        px, py = {}, {}
        for i, box in chosen.items():
            if a <= i < b and box is not None:
                x, y = _desired(box, cw, ch, sw, sh, tw, safe, o["headroom"])
                px[i - a], py[i - a] = x, y
        m = b - a
        tx = _interp_targets(px, m) or [cx0] * m
        ty = _interp_targets(py, m) or [cy0] * m
        xs += follow(tx, fps, cw, o)
        ys += follow(ty, fps, ch, o)
    rects = [[round(min(max(x, 0.0), sw - cw), 2), round(min(max(y, 0.0), sh - ch), 2), round(cw, 2), round(ch, 2)]
             for x, y in zip(xs, ys)]
    out.update(crop_w=cw, crop_h=ch, rects=rects, switches=switches, stats=path_stats(rects, fps, cuts))
    return out


def path_stats(rects, fps, cuts=()):
    """Smoothness numbers for a crop path: max / p95 pan speed (crop widths per s) and mean |accel|,
    excluding the frames at shot cuts."""
    if not rects or len(rects) < 3:
        return dict(max_speed=0.0, p95_speed=0.0, mean_abs_accel=0.0)
    a = np.array(rects, dtype=float)
    cw = a[0, 2]
    pos = a[:, :2] / cw
    v = np.linalg.norm(np.diff(pos, axis=0), axis=1) * fps
    keep = np.ones(len(v), bool)
    for c in cuts:
        if 0 < c <= len(v):
            keep[c - 1] = False
    acc = np.abs(np.diff(v)) * fps
    keep_a = keep[1:] & keep[:-1]
    return dict(max_speed=round(float(v[keep].max() if keep.any() else 0), 4),
                p95_speed=round(float(np.percentile(v[keep], 95)) if keep.any() else 0, 4),
                mean_abs_accel=round(float(acc[keep_a].mean()) if keep_a.any() else 0, 4))


# ----------------------------------------------------------------------------------- render
def frame_fn(pl, blur_dim=None):
    """Callable(i, bgr) -> target-size bgr frame for a plan."""
    import cv2
    tw, th = pl["target"]
    sw, sh = pl["src_w"], pl["src_h"]
    mode = pl["mode_used"]
    if mode in ("pad-blur", "letterbox"):
        fw, fh, ox, oy = _fit(sw, sh, tw, th)
        dim = DEFAULTS["blur_dim"] if blur_dim is None else blur_dim
        bw, bh = max(8, tw // 12), max(8, th // 12)
        canvas = np.zeros((th, tw, 3), np.uint8)

        def fn(i, fr):
            interp = cv2.INTER_AREA if fw < sw else cv2.INTER_CUBIC
            fg = cv2.resize(fr, (fw, fh), interpolation=interp)
            if mode == "letterbox":
                img = canvas.copy()
            else:
                s = max(bw / sw, bh / sh)
                small = cv2.resize(fr, (max(1, int(sw * s)), max(1, int(sh * s))), interpolation=cv2.INTER_AREA)
                yy, xx = (small.shape[0] - bh) // 2, (small.shape[1] - bw) // 2
                small = cv2.GaussianBlur(small[yy:yy + bh, xx:xx + bw], (0, 0), 2.2)
                img = cv2.resize(small, (tw, th), interpolation=cv2.INTER_LINEAR)
                img = (img.astype(np.float32) * dim).astype(np.uint8)
            img[oy:oy + fh, ox:ox + fw] = fg
            return img
        return fn
    rects = pl.get("rects")
    fixed = pl.get("fixed")

    def fn(i, fr):
        x, y, cw, ch = fixed if rects is None else rects[min(i, len(rects) - 1)]
        s = tw / cw
        if abs(s - 1.0) < 1e-6 and float(x).is_integer() and float(y).is_integer():
            return np.ascontiguousarray(fr[int(y):int(y) + th, int(x):int(x) + tw])
        M = np.float32([[s, 0, -x * s], [0, s, -y * s]])
        return cv2.warpAffine(fr, M, (tw, th), flags=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA,
                              borderMode=cv2.BORDER_REPLICATE)
    return fn


def render(src, dst, pl, overlay=None, encode_args=None, audio=True, fps=None):
    """Decode ``src`` (from plan start/dur) as raw BGR, apply the plan (+ ``overlay(i, t, img)`` that
    may draw on the target frame in place), encode to ``dst``. encode_args default
    ``media.delivery_args()`` (H.264 + AAC). audio: map the source audio (same window) if present.
    Returns dst."""
    info = media.probe(src)
    sw, sh = pl["src_w"], pl["src_h"]
    tw, th = pl["target"]
    start, dur = pl.get("start") or 0.0, pl.get("dur")
    rate = str(info["fps_q"]) if info["fps_q"] else f"{pl['fps']:.6g}"
    ff = media.ffmpeg_bin()
    win = (["-ss", f"{start:.3f}"] if start else []) + (["-t", f"{dur:.3f}"] if dur else [])
    dec = [ff, "-v", "error", *win, "-i", os.fspath(src), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    has_a = audio and info["has_audio"]
    enc = [ff, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{tw}x{th}", "-r", rate, "-i", "-"]
    if has_a:
        enc += [*win, "-i", os.fspath(src), "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    else:
        enc += ["-map", "0:v:0"]
    args = list(encode_args) if encode_args is not None else media.delivery_args(audio=bool(has_a))
    if not has_a:
        args = _strip_audio(args)
    if fps:
        args += ["-r", str(fps)]
    enc += args + [os.fspath(dst)]
    fn = frame_fn(pl)
    fsize = sw * sh * 3
    p_dec = subprocess.Popen(dec, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    p_enc = subprocess.Popen(enc, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    i = 0
    try:
        while True:
            buf = p_dec.stdout.read(fsize)
            if len(buf) < fsize:
                break
            fr = np.frombuffer(buf, np.uint8).reshape(sh, sw, 3)
            img = fn(i, fr)
            if overlay is not None:
                img = np.ascontiguousarray(img)
                r = overlay(i, i / pl["fps"], img)
                img = img if r is None else r
            p_enc.stdin.write(np.ascontiguousarray(img).tobytes())
            i += 1
    except BrokenPipeError:
        pass
    finally:
        try:
            p_enc.stdin.close()
        except BrokenPipeError:
            pass
        p_dec.stdout.close()
        p_dec.wait()
        err = p_enc.stderr.read().decode("utf-8", "replace")
        rc = p_enc.wait()
    if rc != 0 or i == 0:
        raise media.FFmpegError(f"reframe render failed (frames={i}, rc={rc}):\n{err[-1500:]}")
    return dst


def _strip_audio(args):
    out, skip = [], 0
    for k, a in enumerate(args):
        if skip:
            skip -= 1
            continue
        if a in ("-c:a", "-b:a", "-ar", "-ac"):
            skip = 1
            continue
        out.append(a)
    return out


def reframe(src, dst, target_w, target_h, mode="face", safe=None, start=0.0, dur=None, plan_json=True,
            overlay=None, encode_args=None, detector=None, **opts):
    """plan() + render(). Writes ``<dst stem>.crop.json`` (plan_json=True) or to the given path.
    Returns the plan dict."""
    pl = plan(src, target_w, target_h, mode=mode, safe=safe, start=start, dur=dur, detector=detector, **opts)
    render(src, dst, pl, overlay=overlay, encode_args=encode_args)
    if plan_json:
        path = plan_json if isinstance(plan_json, (str, os.PathLike)) else os.path.splitext(os.fspath(dst))[0] + ".crop.json"
        with open(path, "w") as f:
            json.dump(pl, f)
        pl["plan_json"] = os.fspath(path)
    return pl


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.reframe", description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--size", help="WxH (default from --platform)")
    ap.add_argument("--platform", help="e.g. douyin or xiaohongshu:vertical (size + safe box)")
    ap.add_argument("--mode", default="face", choices=MODES)
    ap.add_argument("--fallback", default=None, choices=MODES[1:])
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--zoom", type=float, default=None)
    ap.add_argument("--every", type=int, default=None, help="detect every N frames")
    a = ap.parse_args(argv)
    safe = None
    if a.platform:
        from . import platform as P
        prof = P.profile(a.platform)
        tw, th = prof.w, prof.h
        safe = P.safe_box(prof)
    if a.size:
        tw, th = (int(v) for v in a.size.lower().split("x"))
    elif not a.platform:
        ap.error("--size or --platform is required")
    pl = reframe(a.src, a.dst, tw, th, mode=a.mode, safe=safe, start=a.start, dur=a.dur,
                 fallback=a.fallback, zoom=a.zoom, every=a.every)
    print(json.dumps({k: pl.get(k) for k in ("mode_used", "hit_rate", "cuts", "switches", "stats", "plan_json")}))


if __name__ == "__main__":
    sys.exit(main())
