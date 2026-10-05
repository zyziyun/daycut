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
# eyelids, ordered outer corner -> inner corner (image-left eye = LEFT_EYE_RING, image-right = RIGHT_EYE_RING)
UPPER_LID_L = [33, 246, 161, 160, 159, 158, 157, 173, 133]
LOWER_LID_L = [33, 7, 163, 144, 145, 153, 154, 155, 133]
UPPER_LID_R = [263, 466, 388, 387, 386, 385, 384, 398, 362]
LOWER_LID_R = [263, 249, 390, 373, 374, 380, 381, 382, 362]
BROW_LOW_L = [46, 53, 52, 65, 55]          # lower brow edge, outer -> inner
BROW_LOW_R = [276, 283, 282, 295, 285]
NOSE_BRIDGE = [168, 6, 197, 195, 5]
FAST_IDX = sorted(set(LEFT_EYE_RING + RIGHT_EYE_RING + LIPS_OUT + LIPS_IN + BROW_L + BROW_R))


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


_LAST_TS = {}


def _monotonic_ts(lm, ts_ms):
    """MediaPipe VIDEO mode rejects a timestamp <= the previous one on the same landmarker ("Input
    timestamp must be monotonically increasing"). Bump repeats/regressions to last+1 ms so a second
    call on the same frame (e.g. re-acquire after a lost face) cannot crash a long render."""
    ts_ms = int(ts_ms)
    key = id(lm)
    last = getattr(lm, "_vs_last_ts", None)
    if last is None:
        last = _LAST_TS.get(key)
    if last is not None and ts_ms <= last:
        ts_ms = last + 1
    try:
        lm._vs_last_ts = ts_ms
    except Exception:                       # pybind object without __dict__: fall back to a module map
        _LAST_TS[key] = ts_ms
    return ts_ms


def detect(lm, bgr, ts_ms: int = None):
    """List of faces: {"pts": (478,2) pixel coords, "blend": {name: score}}. Pass ts_ms in VIDEO mode
    (it is made strictly increasing per landmarker, see _monotonic_ts)."""
    import cv2
    import mediapipe as mp
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    if ts_ms is not None:
        res = lm.detect_for_video(img, _monotonic_ts(lm, ts_ms))
    else:
        res = lm.detect(img)
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


# ---------------------------------------------------------------- per-frame landmarks for video retouch
class LandmarkSmoother:
    """One Euro smoothing of a (478, 2) mesh for per-frame retouch, in face-width units (resolution
    independent). The head's centroid is filtered on its own, then each landmark's offset from it, with
    eyes / lips / brows (FAST_IDX) on a higher cutoff so blinks and speech are not lagged while the
    cheek / jaw outline (which carries the slim warp) stays rock still. Resets on a cut (jump > reset).
    Chunked renders: feed ~15 warm-up frames before the first written frame and the state converges
    to what a continuous run would have (see retouch_video.py)."""

    def __init__(self, min_cutoff=0.8, beta=1.5, fast_cutoff=2.5, fast_beta=4.0, centre_cutoff=1.5,
                 centre_beta=2.0, d_cutoff=1.0, reset=0.25):
        from .filters import OneEuro
        mc = np.full((478, 1), float(min_cutoff)); bt = np.full((478, 1), float(beta))
        mc[FAST_IDX] = fast_cutoff; bt[FAST_IDX] = fast_beta
        self._mk = lambda: (OneEuro(centre_cutoff, centre_beta, d_cutoff), OneEuro(mc, bt, d_cutoff))
        self.reset_frac = reset
        self.resets = -1
        self.reset()

    def reset(self):
        self.resets += 1
        self.fc, self.fo = self._mk()
        self.scale = None
        self.last = None

    def __call__(self, pts, t):
        pts = np.asarray(pts, np.float64)
        fw = float(np.ptp(pts[FACE_OVAL, 0])) or 1.0
        if self.last is not None and np.abs(pts - self.last).mean() > self.reset_frac * self.scale:
            self.reset()
        if self.scale is None:
            self.scale = fw
        s = self.scale
        c = pts.mean(0)
        cs = self.fc(c / s, t) * s
        off = self.fo((pts - c) / s, t) * s
        self.last = (cs + off).astype(np.float32)
        return self.last


def face_box(pts, scale=2.2, shape=None):
    """Square (x, y, side) around a face, `scale` x its larger extent, shifted (not shrunk) into the frame."""
    x0, y0 = pts.min(0); x1, y1 = pts.max(0)
    side = int(round(max(x1 - x0, y1 - y0) * scale))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x, y = int(round(cx - side / 2)), int(round(cy - side / 2))
    if shape is not None:
        h, w = shape[:2]; side = min(side, h, w)
        x = min(max(0, x), w - side); y = min(max(0, y), h - side)
    return x, y, side


def detect_in_box(lm, bgr, box, ts_ms=None, max_side=640):
    """Landmarks of the face inside square `box` (x, y, side), the crop resized to <= max_side (a face
    filling ~half of the crop is what the short-range detector and the mesh model like). Returns faces
    in FRAME pixel coordinates (same dicts as detect())."""
    import cv2
    x, y, side = box
    crop = bgr[y:y + side, x:x + side]
    s = min(1.0, max_side / max(1, side))
    if s < 1.0:
        crop = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    faces = detect(lm, np.ascontiguousarray(crop), ts_ms)
    for f in faces:
        f["pts"] = f["pts"] / s + np.array([x, y], np.float32)
    return faces


class VideoFaceTracker:
    """Main face per frame for video retouch: VIDEO-mode landmarker on a face crop at adequate
    resolution (crop re-centred with hysteresis so it does not chase jitter), IMAGE-mode full-frame
    detection to (re)acquire, and LandmarkSmoother on top. Call with strictly increasing frame indices.
    Returns {"pts": smoothed, "raw": raw, "blend": ...} or None (smoother reset)."""

    def __init__(self, fps, max_side=640, box_scale=2.2, smoother=None, acquire_scale=0.5):
        self.fps = float(fps); self.max_side = max_side; self.box_scale = box_scale
        self.acquire_scale = acquire_scale
        self.lm = landmarker(1, video=True); self._lm_img = None
        self.sm = smoother or LandmarkSmoother()
        self.box = None

    def close(self):
        self.lm.close()
        if self._lm_img is not None:
            self._lm_img.close()

    def _acquire(self, bgr):
        import cv2
        if self._lm_img is None:
            self._lm_img = landmarker(1)
        a = self.acquire_scale
        small = cv2.resize(bgr, None, fx=a, fy=a, interpolation=cv2.INTER_AREA) if a != 1 else bgr
        f = main_face(detect(self._lm_img, small))
        if f is not None:
            f["pts"] = f["pts"] / a
        return f

    def __call__(self, bgr, idx):
        try:
            return self._track(bgr, idx)
        except Exception as e:              # fail loudly with the frame, never a bare MediaPipe error
            raise RuntimeError(f"VideoFaceTracker failed at frame {idx} "
                               f"(t={idx / self.fps:.3f}s): {e}") from e

    def _track(self, bgr, idx):
        ts = int(round(idx * 1000.0 / self.fps))
        f = None
        if self.box is not None:
            f = main_face(detect_in_box(self.lm, bgr, self.box, ts, self.max_side))
        if f is None:
            f = self._acquire(bgr)
            if f is None:
                self.box = None; self.sm.reset()
                return None
            self.box = face_box(f["pts"], self.box_scale, bgr.shape)
            g = main_face(detect_in_box(self.lm, bgr, self.box, ts, self.max_side))
            f = g or f
        raw = f["pts"]
        x, y, side = self.box
        nx, ny, nside = face_box(raw, self.box_scale, bgr.shape)
        cx, cy = nx + nside / 2, ny + nside / 2
        if abs(cx - (x + side / 2)) > 0.12 * side or abs(cy - (y + side / 2)) > 0.12 * side \
                or abs(nside - side) > 0.15 * side:
            self.box = (nx, ny, nside)
        pts = self.sm(raw, idx / self.fps)
        return {"pts": pts, "raw": raw, "blend": f["blend"]}
