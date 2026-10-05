"""MediaPipe FaceLandmarker helpers (478-point mesh + blendshapes) and landmark index sets."""
import os
import warnings

import numpy as np

warnings.filterwarnings("ignore")
os.environ.setdefault("GLOG_minloglevel", "3")

LEFT_EYE_RING = [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7]
RIGHT_EYE_RING = [263, 466, 388, 387, 386, 385, 384, 398, 362, 382, 381, 380, 374, 373, 390, 249]
LEFT_EAR = [33, 160, 158, 133, 153, 144]
RIGHT_EAR = [362, 385, 387, 263, 373, 380]
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400,
             377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
BROW_L = [70, 63, 105, 66, 107, 55, 65, 52, 53, 46]
BROW_R = [300, 293, 334, 296, 336, 285, 295, 282, 283, 276]
LIPS_OUT = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]
LIPS_IN = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95]
JAW_SLIM = [132, 58, 172, 136, 150, 149, 176, 148, 377, 400, 378, 379, 365, 397, 288, 361]
CHEEK_WIDE = [234, 454, 93, 323, 132, 361]
ANCHORS_FACE = [10, 9, 151, 8, 168, 6, 1, 2, 0, 17, 152, 200, 199, 61, 291, 78, 308]
BROW_ANCHORS = [70, 63, 105, 66, 107, 300, 293, 334, 296, 336]
CHEEK_APPLE_L = [50, 101, 118, 117, 123]
CHEEK_APPLE_R = [280, 330, 347, 346, 352]


def landmarker(num_faces: int = 1, video: bool = False):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    from .config import model
    opts = vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=model("face_landmarker")),
        output_face_blendshapes=True, num_faces=num_faces,
        min_face_detection_confidence=0.4, min_face_presence_confidence=0.4,
        running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE)
    return vision.FaceLandmarker.create_from_options(opts)


def detect(lm, bgr, ts_ms: int = None):
    """List of faces: {"pts": (478,2) pixel coords, "blend": {name: score}}. Pass ts_ms in VIDEO mode."""
    import cv2
    import mediapipe as mp
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    res = lm.detect_for_video(img, ts_ms) if ts_ms is not None else lm.detect(img)
    h, w = bgr.shape[:2]
    out = []
    for i, f in enumerate(res.face_landmarks):
        pts = np.array([[p.x * w, p.y * h] for p in f], np.float32)
        blend = {c.category_name: c.score for c in res.face_blendshapes[i]} if res.face_blendshapes else {}
        out.append({"pts": pts, "blend": blend})
    return out


def ear(pts, idx):
    p1, p2, p3, p4, p5, p6 = pts[idx]
    return float((np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)) / (2 * np.linalg.norm(p1 - p4) + 1e-6))


def main_face(faces, min_area_frac: float = 0.0, shape=None):
    """Largest face (optionally ignoring tiny background faces)."""
    best, area = None, 0
    for f in faces:
        p = f["pts"]; a = np.ptp(p[:, 0]) * np.ptp(p[:, 1])
        if shape is not None and a / (shape[0] * shape[1]) < min_area_frac:
            continue
        if a > area:
            best, area = f, a
    return best


# ---------------------------------------------------------------- tracking over a video
UPPER_LIP, LOWER_LIP, CHIN, FOREHEAD = 13, 14, 152, 10


def fill_gaps(series):
    """Linear-interpolate None holes; hold the nearest known value at the ends (None if all None).
    From call-clips ``track_face.fill_gaps``."""
    idx = [i for i, v in enumerate(series) if v is not None]
    if not idx:
        return None
    out = list(series)
    for i in range(idx[0]):
        out[i] = series[idx[0]]
    for i in range(idx[-1] + 1, len(series)):
        out[i] = series[idx[-1]]
    for a, b in zip(idx, idx[1:]):
        if b - a > 1:
            va, vb = series[a], series[b]
            for k in range(1, b - a):
                out[a + k] = va + (vb - va) * k / (b - a)
    return out


def ema(vals, alpha):
    """Exponential moving average (alpha = weight of the new sample; lower = steadier)."""
    out, acc = [], None
    for v in vals:
        acc = v if acc is None else alpha * v + (1 - alpha) * acc
        out.append(acc)
    return out


def smooth_track(cx, cy, w, h, alpha=0.25, size_floor=0.9):
    """Gap-fill + EMA a per-frame box track (lists with None for missed frames). Size is smoothed
    twice as hard as position and floored at ``size_floor`` x its median (a shrinking mask is the
    risky direction). Returns dict(cx, cy, w, h) or None if nothing was detected.
    From call-clips ``track_face.main``."""
    if fill_gaps(cx) is None:
        return None
    cx, cy, w, h = (fill_gaps(s) for s in (cx, cy, w, h))
    cx, cy = ema(cx, alpha), ema(cy, alpha)
    w, h = ema(w, alpha * 0.5), ema(h, alpha * 0.5)
    wm, hm = float(np.median(w)), float(np.median(h))
    return dict(cx=cx, cy=cy, w=[max(v, wm * size_floor) for v in w], h=[max(v, hm * size_floor) for v in h])


def _frames(video, start=0.0, dur=None, every=1):
    import cv2
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if start:
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
    n_target = int(round(dur * fps)) if dur else None
    i = 0
    try:
        while n_target is None or i < n_target:
            ok, fr = cap.read()
            if not ok:
                break
            if i % every == 0:
                yield fps, i, fr
            i += 1
    finally:
        cap.release()


def track_faces(video, region=None, search=None, upscale=1.0, start=0.0, dur=None, smooth=0.25,
                size_floor=0.9, lm=None):
    """Per-frame face box of one person inside ``region`` (x, y, w, h; default the whole frame) of a
    video, detection gaps interpolated and the path EMA-smoothed, so a sticker/blur pasted on it never
    blinks off. search: tighter (x, y, w, h) to detect in, upscaled by ``upscale`` first (a ~55 px
    face in a gallery tile is lost otherwise). Returns dict(fps, n_frames, hit_rate, region, cx, cy,
    w, h) in frame pixels (lists, one per frame). Raises RuntimeError if no frame/face.
    From call-clips ``track_face.py``."""
    import cv2
    own = lm is None
    lm = lm or landmarker(1, video=True)
    region = list(region) if region else None
    cx, cy, ws, hs = [], [], [], []
    fps, hits = 25.0, 0
    try:
        for fps, i, fr in _frames(video, start, dur):
            if region is None:
                region = [0, 0, fr.shape[1], fr.shape[0]]
            sx, sy, sw, sh = (int(v) for v in (search or region))
            tile = fr[sy:sy + sh, sx:sx + sw]
            if upscale != 1.0:
                tile = cv2.resize(tile, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
            faces = detect(lm, np.ascontiguousarray(tile), int(round(i / fps * 1000)))
            if faces:
                p = faces[0]["pts"] / upscale
                x0, x1, y0, y1 = p[:, 0].min(), p[:, 0].max(), p[:, 1].min(), p[:, 1].max()
                cx.append(float((x0 + x1) / 2 + sx)); cy.append(float((y0 + y1) / 2 + sy))
                ws.append(float(x1 - x0)); hs.append(float(y1 - y0)); hits += 1
            else:
                for s in (cx, cy, ws, hs):
                    s.append(None)
    finally:
        if own:
            lm.close()
    n = len(cx)
    if not n:
        raise RuntimeError(f"no frames read from {video}")
    tr = smooth_track(cx, cy, ws, hs, smooth, size_floor)
    if tr is None:
        raise RuntimeError("no face detected anywhere in the region")
    return dict(fps=fps, n_frames=n, hit_rate=round(hits / n, 4), region=region, **tr)


def mouth_gap(pts):
    """Inner-lip opening normalised by face height, from (478, 2) landmark pixels (or MediaPipe
    landmark objects). From call-clips ``speaker_timeline.mouth_gap``."""
    if hasattr(pts[0], "y"):
        up, lo, ch, fh = pts[UPPER_LIP].y, pts[LOWER_LIP].y, pts[CHIN].y, pts[FOREHEAD].y
    else:
        up, lo, ch, fh = pts[UPPER_LIP][1], pts[LOWER_LIP][1], pts[CHIN][1], pts[FOREHEAD][1]
    return float(abs(lo - up) / (abs(ch - fh) or 1e-6))


def talk_labels(series, step, win=0.8, margin=0.18):
    """Who talks when, from per-person mouth-gap series {name: [gap or nan/None]} sampled every
    ``step`` s: mouth-movement energy = rolling std over ``win`` s (dropped detections hold the last
    reading); the most-moving mouth wins a sample when it beats the runner-up by ``margin`` (relative),
    else "both". Returns dict(labels, energy={name: [...]}). From call-clips ``speaker_timeline``."""
    k = max(3, int(round(win / step)))
    energy = {}
    for name, vals in series.items():
        a = np.array([np.nan if v is None else v for v in vals], dtype=float)
        idx = np.where(~np.isnan(a))[0]
        a = np.interp(np.arange(len(a)), idx, a[idx]) if len(idx) else np.zeros(len(a))
        pad = np.pad(a, (k // 2, k // 2), mode="edge")
        energy[name] = np.array([pad[j:j + k].std() for j in range(len(a))])
    names = list(series)
    if not names or not len(energy[names[0]]):
        return dict(labels=[], energy={n: [] for n in names})
    E = np.vstack([energy[n] for n in names])
    win_i = E.argmax(axis=0)
    top2 = np.sort(E, axis=0)[-2:] if len(names) > 1 else np.vstack([0 * E, E])
    rel = (top2[1] - top2[0]) / (E.max(axis=0) + 1e-9)
    labels = [names[w] if m > margin else "both" for w, m in zip(win_i, rel)]
    return dict(labels=labels, energy={n: energy[n].tolist() for n in names})


def talk_activity(video, tiles, every=3, win=0.8, margin=0.18):
    """Speaker timeline of a gallery-view call from mouth movement alone (one mixed audio track has
    no diarisation): tiles = {name: (x, y, w, h)}; samples every ``every`` frames. Returns dict(fps,
    step, times, labels, energy) - labels per sample: a tile name or "both".
    From call-clips ``speaker_timeline.py``."""
    dets = {n: landmarker(1, video=True) for n in tiles}
    times, series, fps = [], {n: [] for n in tiles}, 25.0
    try:
        for fps, i, fr in _frames(video, every=every):
            ts = i / fps
            times.append(ts)
            for name, (x, y, w, h) in tiles.items():
                f = detect(dets[name], np.ascontiguousarray(fr[y:y + h, x:x + w]), int(round(ts * 1000)))
                series[name].append(mouth_gap(f[0]["pts"]) if f else np.nan)
    finally:
        for d in dets.values():
            d.close()
    step = every / fps
    res = talk_labels(series, step, win, margin)
    return dict(fps=fps, step=step, times=times, **res)
