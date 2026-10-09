"""Portrait retouch for covers and talking-head frames (stills and video).

Pipeline per face (all own implementations on OpenCV/NumPy; masks from MediaPipe, Apache-2.0):
  1. reshape   - MLS face slim + eye open, capped (`natural_cap`) and identity-guarded (landmark ratios)
  2. de-shine  - specular highlights pulled toward the skin median
  3. skin mask - multiclass selfie segmenter face-skin (+ body-skin for the neck) intersected with the
                 landmark oval; holes for eyes / brows / lips; glasses frames, hair strands, stubble cut out.
                 Falls back to the landmark mask when the model is missing.
  4. smoothing - three-band frequency separation with a guided filter: high band (pores) kept at `pores`,
                 mid band (blemishes / unevenness) attenuated by `smooth`, base tone-evened toward the
                 median skin chroma (`tone`) and lifted (`light`, base only, so texture never washes out)
  5. blemishes - small dark / red mid-band outliers replaced by the base (`blemish`); under-eye crescent
                 lightened and de-blued (`undereye`)
  6. makeup    - preset ("natural" default, "daily", "glam", "none") scaled by `makeup` (0.5 = as designed):
                 texture-keeping lipstick with gloss from the original luminance, shaped blush, brow fill in
                 the brow-hair colour, eyeliner with a tail, lid eyeshadow gradient, light contour/highlight.
                 Eyeliner / eyeshadow are skipped under thick glasses frames.
Edits are composited back through a feathered face-region mask, so warp ROI borders never show as seams.

    retouch(img, f=None, lm=None, **knobs)        # f: face dict (or list), lm: landmarker; see DEFAULTS
    retouch(frame, f=tracked, state=RetouchState(video=True), **knobs)   # video: temporal state
CLI:  python -m vstudio.retouch in.png out.png [--slim .06] [--eye .04] [--makeup .5] [--preset daily]
See references/RETOUCH.md for every knob.
"""
import argparse
import types

import cv2
import numpy as np

from . import face as F
from .mls import inverse_map, rigid

DEFAULTS = dict(slim=0.05, eye=0.04, eye_extra=0.0, shine=0.8, shine_feather=2.5,
                smooth=0.6, light=0.05, makeup=0.5, body=0.0, region=True)
# v2 knobs (all optional; None for a makeup component = take it from the preset)
EXTRA = dict(preset="natural", pores=0.8, tone=0.35, blemish=0.5, undereye=0.35, neck=0.5, skin_seg=True,
             glasses="auto", faces="main", min_face=0.06, face_strength=None, natural_cap=0.12,
             identity_guard=0.10, grid=640,
             lip=None, blush=None, brow=None, liner=None, shadow=None, contour=None, highlight=None, gloss=None,
             lip_shade=None, blush_shade=None, shadow_shade=None, liner_shade=None, state=None)

# Lab (OpenCV float: L 0-100, a/b ~ -127..127) colour targets
SHADES = {
    "rose": (50, 40, 12), "coral": (58, 42, 30), "red": (42, 58, 22), "berry": (36, 44, 6),
    "nude": (58, 24, 20), "pink": (68, 30, 6), "peach": (72, 24, 24), "brown": (30, 10, 16),
    "black": (14, 1, 2), "taupe": (48, 7, 9), "bronze": (46, 14, 26), "plum": (38, 22, -6),
    "mlbb": (56, 30, 9),     # "my lips but better": muted rosy pink, a touch deeper than bare lips (~#BB7177)
}
COMPONENTS = ("lip", "blush", "brow", "liner", "shadow", "contour", "highlight", "gloss")
SHADE_KEYS = ("lip_shade", "blush_shade", "shadow_shade", "liner_shade")
PRESETS = {
    "none": dict(lip=0, blush=0, brow=0, liner=0, shadow=0, contour=0, highlight=0, gloss=0),
    "natural": dict(lip=.45, blush=.35, brow=.3, liner=0, shadow=0, contour=.15, highlight=.2, gloss=.3,
                    lip_shade="rose", blush_shade="pink", shadow_shade="taupe", liner_shade="brown"),
    "daily": dict(lip=.65, blush=.45, brow=.45, liner=.35, shadow=.3, contour=.25, highlight=.25, gloss=.4,
                  lip_shade="mlbb", blush_shade="peach", shadow_shade="bronze", liner_shade="brown"),
    "glam": dict(lip=.9, blush=.55, brow=.6, liner=.7, shadow=.6, contour=.4, highlight=.4, gloss=.6,
                 lip_shade="red", blush_shade="rose", shadow_shade="plum", liner_shade="black"),
}
for _v in PRESETS.values():
    for _k, _d in zip(SHADE_KEYS, ("rose", "pink", "taupe", "brown")):
        _v.setdefault(_k, _d)


def _opts(**kw):
    d = dict(DEFAULTS); d.update(EXTRA); d.update({k: v for k, v in kw.items() if v is not None})
    return types.SimpleNamespace(**d)


def shade_lab(s):
    """Shade name, '#rrggbb' or an (L, a, b) tuple -> Lab float triple. ValueError otherwise."""
    if isinstance(s, str):
        if s in SHADES:
            return tuple(float(v) for v in SHADES[s])
        h = s.lstrip("#")
        if len(h) == 6:
            try:
                r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
            except ValueError:
                raise ValueError(f"bad shade {s!r}") from None
            lab = cv2.cvtColor(np.array([[[b, g, r]]], np.float32) / 255, cv2.COLOR_BGR2Lab)[0, 0]
            return tuple(float(v) for v in lab)
        raise ValueError(f"unknown shade {s!r}; use one of {sorted(SHADES)} or '#rrggbb'")
    if isinstance(s, (tuple, list)) and len(s) == 3:
        return tuple(float(v) for v in s)
    raise ValueError(f"bad shade {s!r}")


def makeup_params(preset="natural", makeup=0.5, **over):
    """Validated makeup recipe: preset components x (makeup / 0.5), explicit component / shade overrides
    win. Returns {component: strength 0..1, *_shade: Lab}. ValueError on unknown preset / bad values."""
    if preset not in PRESETS:
        raise ValueError(f"unknown makeup preset {preset!r}; one of {sorted(PRESETS)}")
    makeup = float(makeup)
    if not 0 <= makeup <= 2:
        raise ValueError(f"makeup must be in [0, 2], got {makeup}")
    rec = dict(PRESETS[preset])
    out = {}
    for c in COMPONENTS:
        v = over.get(c)
        v = rec[c] * makeup * 2 if v is None else float(v) * makeup * 2
        if v < 0:
            raise ValueError(f"{c} strength must be >= 0")
        out[c] = float(min(v, 1.0))
    for k in SHADE_KEYS:
        out[k] = shade_lab(over.get(k) or rec[k])
    bad = set(over) - set(COMPONENTS) - set(SHADE_KEYS)
    if bad:
        raise ValueError(f"unknown makeup keys {sorted(bad)}")
    return out


class RetouchState:
    """Temporal state for video: segmentation confidences EMA'd in a landmark-anchored canonical face
    frame (so masks neither flicker nor swim), and the MLS warp field reused while the controls barely
    move. One per tracked face; reset() on a cut."""

    def __init__(self, video=True, seg_alpha=0.5, warp_tol=0.35):
        self.video, self.seg_alpha, self.warp_tol = video, seg_alpha, warp_tol
        self.reset()

    def reset(self):
        self.seg = None
        self.warp = None


# ---------------------------------------------------------------- small helpers
def _poly(shape, pts, blur=0.0):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [np.round(pts).astype(np.int32)], 255)
    m = m.astype(np.float32) / 255
    return cv2.GaussianBlur(m, (0, 0), blur) if blur > 0 else m


def _hull(shape, pts, dilate=0, blur=0.0):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillConvexPoly(m, cv2.convexHull(np.round(pts).astype(np.int32)), 255)
    if dilate > 0:
        k = int(dilate) * 2 + 1
        m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    m = m.astype(np.float32) / 255
    return cv2.GaussianBlur(m, (0, 0), blur) if blur > 0 else m


def _fw(pts):
    return float(np.ptp(pts[F.FACE_OVAL, 0])) or 1.0


def _resample(pts, n):
    """n points evenly spaced by arc length along a polyline."""
    pts = np.asarray(pts, np.float64)
    d = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))]
    if d[-1] <= 0:
        return np.repeat(pts[:1], n, 0)
    t = np.linspace(0, d[-1], n)
    return np.stack([np.interp(t, d, pts[:, 0]), np.interp(t, d, pts[:, 1])], 1)


def _up(pts):
    """Unit vector from the chin toward the forehead (face 'up', handles head roll)."""
    v = pts[10] - pts[152]
    return v / (np.linalg.norm(v) + 1e-6)


def _box(x, r):
    return cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1), normalize=True, borderType=cv2.BORDER_REFLECT)


def guided_filter(I, p, r, eps):
    """Edge-preserving guided filter (He, Sun, Tang 2010), own box-filter implementation; uses
    cv2.ximgproc when opencv-contrib is installed. I, p float32 same shape (single channel)."""
    r = max(1, int(round(r)))
    I = np.asarray(I, np.float32); p = np.asarray(p, np.float32)
    if hasattr(cv2, "ximgproc"):
        return cv2.ximgproc.guidedFilter(I, p, r, eps)
    mI, mp_ = _box(I, r), _box(p, r)
    cov = _box(I * p, r) - mI * mp_
    var = _box(I * I, r) - mI * mI
    a = cov / (var + eps)
    b = mp_ - a * mI
    return _box(a, r) * I + _box(b, r)


# ---------------------------------------------------------------- reshape
def _controls(pts, blend, roi, p):
    rx0, ry0, rh, rw = roi
    P, Q = [], []
    for idx in F.ANCHORS_FACE + F.BROW_ANCHORS:
        x, y = pts[idx]; P.append([x - rx0, y - ry0]); Q.append([x - rx0, y - ry0])
    for x in np.linspace(0, rw - 1, 5):
        for y in (0, rh - 1):
            P.append([x, y]); Q.append([x, y])
    for y in np.linspace(0, rh - 1, 5):
        for x in (0, rw - 1):
            P.append([x, y]); Q.append([x, y])
    axis_x = (pts[152][0] + pts[9][0]) / 2
    for idx in F.JAW_SLIM:
        x, y = pts[idx]; k = 1.5 if idx in F.CHEEK_WIDE else 1.0
        P.append([x - rx0, y - ry0]); Q.append([x + (axis_x - x) * p.slim * k - rx0, y - ry0])
    for ring, ear_i, bk in ((F.LEFT_EYE_RING, F.LEFT_EAR, "eyeBlinkLeft"), (F.RIGHT_EYE_RING, F.RIGHT_EAR, "eyeBlinkRight")):
        ep = pts[ring]; cx, cy = ep.mean(0)
        e = F.ear(pts, ear_i); bl = float((blend or {}).get(bk, 0.0))
        squint = np.clip((0.30 - e) / 0.18, 0, 1) * 0.6 + np.clip((bl - 0.20) / 0.55, 0, 1) * 0.4
        grow = p.eye + p.eye_extra * float(squint)
        for idx in ring:
            x, y = pts[idx]
            P.append([x - rx0, y - ry0])
            Q.append([cx + (x - cx) * (1 + grow) - rx0, cy + (y - cy) * (1 + grow * 1.15) - ry0])
    return np.array(P, np.float64), np.array(Q, np.float64)


def _ratios(pts):
    d = lambda a, b: float(np.linalg.norm(pts[a] - pts[b])) + 1e-6  # noqa: E731
    fh = d(10, 152)
    return np.array([d(172, 397) / fh, d(234, 454) / fh, d(33, 133) / d(133, 362), d(263, 362) / d(133, 362),
                     d(61, 291) / d(234, 454), d(159, 145) / d(33, 133), d(386, 374) / d(263, 362),
                     d(1, 152) / fh])


def identity_drift(before, after):
    """Largest relative change of identity-carrying landmark ratios (jaw / cheek width vs face height,
    eye size vs interocular, mouth vs cheek width, nose-chin vs face height)."""
    a, b = _ratios(before), _ratios(after)
    return float(np.max(np.abs(b / a - 1)))


def _roi_box(pts, shape, pad=0.5):
    h, w = shape[:2]
    x0, y0 = pts.min(0); x1, y1 = pts.max(0)
    pad = int(pad * max(x1 - x0, y1 - y0))
    return max(0, int(x0 - pad)), max(0, int(y0 - pad)), min(w, int(x1 + pad)), min(h, int(y1 + pad))


def _warp(img, f, p, state=None):
    """MLS reshape -> (image, landmarks moved by the same deformation). Applies the natural cap on
    slim + eye and the identity guard; reuses the cached field in video when controls barely move."""
    pts = np.asarray(f["pts"], np.float64)
    q = types.SimpleNamespace(**vars(p))
    tot = max(q.slim, 0) + max(q.eye, 0) + max(q.eye_extra, 0) * 0.5
    if q.natural_cap and tot > q.natural_cap:
        k = q.natural_cap / tot; q.slim *= k; q.eye *= k; q.eye_extra *= k
    if q.slim <= 0 and q.eye <= 0 and q.eye_extra <= 0:
        return img, pts.astype(np.float32)
    rx0, ry0, rx1, ry1 = _roi_box(pts, img.shape)
    if state is not None and state.video:                       # quantise so a still head keeps one ROI
        rx0, ry0 = rx0 // 16 * 16, ry0 // 16 * 16
        rx1 = min(img.shape[1], -(-rx1 // 16) * 16); ry1 = min(img.shape[0], -(-ry1 // 16) * 16)
    roi = img[ry0:ry1, rx0:rx1]
    rh, rw = roi.shape[:2]
    P, Q = _controls(pts, f.get("blend"), (rx0, ry0, rh, rw), q)
    off = np.array([rx0, ry0])
    moved = rigid(pts - off, P, Q) + off
    if q.identity_guard:
        drift = identity_drift(pts, moved)
        if drift > q.identity_guard:
            k = q.identity_guard / drift
            q.slim *= k; q.eye *= k; q.eye_extra *= k
            P, Q = _controls(pts, f.get("blend"), (rx0, ry0, rh, rw), q)
            moved = rigid(pts - off, P, Q) + off
    key = (rx0, ry0, rx1, ry1)
    c = state.warp if state is not None else None
    if c is not None and c[0] == key and c[1].shape == P.shape and \
            max(np.abs(c[1] - P).max(), np.abs(c[2] - Q).max()) < state.warp_tol:
        mx, my = c[3], c[4]
    else:
        mx, my = inverse_map(rh, rw, P, Q, grid=int(q.grid))
        if state is not None:
            state.warp = (key, P, Q, mx, my)
    out = img.copy()
    out[ry0:ry1, rx0:rx1] = cv2.remap(roi, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    return out, moved.astype(np.float32)


def warp_face(img, f, p):
    """MLS face slim + eye open (backward-compatible wrapper; see _warp)."""
    if not isinstance(p, types.SimpleNamespace) or not hasattr(p, "natural_cap"):
        p = _opts(**vars(p))
    return _warp(img, f, p)[0]


# ---------------------------------------------------------------- de-shine (unchanged algorithm)
def deshine(img, f, p):
    if p.shine <= 0:
        return img
    pts = f["pts"]; h, w = img.shape[:2]
    skin = (_poly(img.shape, pts[F.FACE_OVAL]) * 255).astype(np.uint8)
    for ring in (F.LEFT_EYE_RING, F.RIGHT_EYE_RING, F.BROW_L, F.BROW_R):
        cv2.fillConvexPoly(skin, cv2.convexHull(pts[ring].astype(np.int32)), 0)
    skin = cv2.erode(skin, np.ones((5, 5), np.uint8)); sk = skin > 0
    if sk.sum() < 50:
        return img
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    S, V = hsv[..., 1], hsv[..., 2]
    v_hi, v_med, s_lo = np.percentile(V[sk], 76), np.percentile(V[sk], 55), np.percentile(S[sk], 45)
    hl = sk & (V > v_hi) & (S < s_lo + 25)
    if not hl.any():
        return img
    soft = np.zeros((h, w), np.float32)
    soft[hl] = np.clip((V - v_hi) / (255 - v_hi + 1e-6), 0, 1)[hl]
    soft = cv2.GaussianBlur(soft, (0, 0), p.shine_feather) * p.shine
    hsv[..., 2] = V * (1 - soft) + np.minimum(V, v_med + (V - v_med) * 0.35) * soft
    hsv[..., 1] = np.clip(S + soft * (np.percentile(S[sk], 60) - S) * 0.5, 0, 255)
    return cv2.cvtColor(np.clip(hsv, 0, 255).astype(np.uint8), cv2.COLOR_HSV2BGR)


# ---------------------------------------------------------------- masks
_SEG = {}
THICK_FRAME = 0.028          # frame thickness (face-width units) above which eyeliner / eyeshadow are skipped
SEG_CLASSES = ("background", "hair", "body_skin", "face_skin", "clothes", "others")


def _segmenter():
    """Multiclass selfie segmenter (cached per process) or None when the model / mediapipe is missing."""
    if "m" not in _SEG:
        try:
            from mediapipe.tasks.python import BaseOptions, vision
            from .config import model
            _SEG["m"] = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
                base_options=BaseOptions(model_asset_path=model("selfie_multiclass")),
                output_confidence_masks=True, output_category_mask=False))
        except Exception as e:  # noqa: BLE001 - model optional: landmark mask fallback
            print("retouch: multiclass segmenter unavailable, landmark skin mask only:", e)
            _SEG["m"] = None
    return _SEG["m"]


def _canon(pts, size=256):
    """Similarity transform image -> canonical face frame (eyes level, face ~0.42 of the width)."""
    le, re = pts[F.LEFT_EYE_RING].mean(0), pts[F.RIGHT_EYE_RING].mean(0)
    ang = np.degrees(np.arctan2(re[1] - le[1], re[0] - le[0]))
    fw = float(np.linalg.norm(pts[234] - pts[454])) or _fw(pts)
    c = pts[F.FACE_OVAL].mean(0) - _up(pts) * 0.12 * float(np.linalg.norm(pts[10] - pts[152]))
    M = cv2.getRotationMatrix2D((float(c[0]), float(c[1])), float(ang), size / (2.4 * fw))
    M[:, 2] += np.array([size / 2, size / 2]) - c
    return M


def segment_face(img, pts, state=None, size=256):
    """{class: confidence map (img-sized float32)} for hair / body_skin / face_skin / others, computed in
    the canonical face frame (EMA'd there for video), or None without the model."""
    seg = _segmenter()
    if seg is None:
        return None
    import mediapipe as mp
    M = _canon(pts, size)
    crop = cv2.warpAffine(img, M, (size, size), flags=cv2.INTER_AREA, borderMode=cv2.BORDER_REPLICATE)
    res = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(crop[..., ::-1])))
    conf = np.stack([np.asarray(m.numpy_view(), np.float32).reshape(size, size) for m in res.confidence_masks], -1)
    if state is not None and state.video:
        if state.seg is not None and state.seg.shape == conf.shape:
            conf = state.seg_alpha * conf + (1 - state.seg_alpha) * state.seg
        state.seg = conf
    h, w = img.shape[:2]
    out = {}
    for i, name in enumerate(SEG_CLASSES):
        if name in ("background", "clothes"):
            continue
        out[name] = cv2.warpAffine(np.ascontiguousarray(conf[..., i]), M, (w, h),
                                   flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderValue=0)
    return out


def landmark_skin_mask(shape, pts):
    """Feathered face-oval skin mask (forehead extended a little) with holes for eyes, brows and lips."""
    fw = _fw(pts)
    oval = pts[F.FACE_OVAL].astype(np.float64)
    c = oval.mean(0); up = _up(pts)
    rel = oval - c
    lift = np.clip(rel @ up / (np.abs(rel @ up).max() + 1e-6), 0, 1)       # 1 at the top of the oval
    oval = c + rel * 1.02 + up[None] * (lift[:, None] * 0.06 * fw)
    skin = _poly(shape, oval, fw * .015)
    return skin * feature_holes(shape, pts)


def feature_holes(shape, pts):
    """1 on skin, 0 on eyes / brows / lips (+ margin), feathered."""
    fw = _fw(pts)
    hole = np.zeros(shape[:2], np.float32)
    for ring, dil in ((F.LEFT_EYE_RING, .035), (F.RIGHT_EYE_RING, .035), (F.BROW_L, .012), (F.BROW_R, .012),
                      (F.LIPS_OUT, .012)):
        hole = np.maximum(hole, _hull(shape, pts[ring], fw * dil))
    return 1 - cv2.GaussianBlur(hole, (0, 0), max(1.0, fw * .008))


def _line_structures(L, fw, region):
    """Thin dark/bright elongated structures (glasses frames, hair strands) inside `region` (bool)."""
    k = int(max(5, fw * .035)) | 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    bh = cv2.morphologyEx(L, cv2.MORPH_BLACKHAT, se)
    th = cv2.morphologyEx(L, cv2.MORPH_TOPHAT, se)
    cand = (((bh > 7) | (th > 9)) & region).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, 8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if max(w, h) > fw * .07 and a < max(w, h) * fw * .03:        # long and thin
            keep[i] = True
    return keep[lab]


def glasses_mask(img_or_L, pts, others=None):
    """(frame mask float32, thickness in face-width units or 0 if no glasses). `others` is the
    segmenter's accessory confidence (optional). Frames are excluded from smoothing / makeup."""
    L = img_or_L if img_or_L.ndim == 2 else cv2.cvtColor(img_or_L, cv2.COLOR_BGR2Lab)[..., 0]
    L = L.astype(np.float32) * (100 / 255 if L.dtype == np.uint8 or L.max() > 101 else 1)
    fw = _fw(pts); shape = L.shape
    up = _up(pts)
    band_pts = np.concatenate([pts[F.BROW_L + F.BROW_R], pts[[234, 454, 127, 356, 6, 168]],
                               pts[F.LOWER_LID_L + F.LOWER_LID_R] - up * fw * .14])
    band = _hull(shape, band_pts, fw * .03) > .5
    eyes = (_hull(shape, pts[F.LEFT_EYE_RING], fw * .01) + _hull(shape, pts[F.RIGHT_EYE_RING], fw * .01)
            + _hull(shape, pts[F.BROW_L], fw * .004) + _hull(shape, pts[F.BROW_R], fw * .004)) > .5
    lines = _line_structures(L, fw, band & ~eyes).astype(np.uint8)
    m = lines.copy()
    if others is not None:
        m |= ((others > .5) & band).astype(np.uint8)
    area = int(m.sum())
    if area < (fw * .05) ** 2:
        return np.zeros(shape, np.float32), 0.0
    src = lines if lines.sum() > (fw * .03) ** 2 else m       # thickness from the crisp line detection
    dt = cv2.distanceTransform(src, cv2.DIST_L2, 3)
    thick = 2 * float(np.percentile(dt[src > 0], 90)) / fw
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.0), thick


def _stubble(L, pts, fw):
    """Lower-face beard/stubble: dark, high-local-variance texture covering a real share of the jaw."""
    shape = L.shape
    low = _poly(shape, pts[F.JAW_SLIM + [61, 0, 291]], 0) > .5
    low &= _hull(shape, pts[F.LIPS_OUT], fw * .02) < .5
    if low.sum() < 50:
        return np.zeros(shape, np.float32)
    mu = cv2.GaussianBlur(L, (0, 0), fw * .01)
    sd = np.sqrt(np.maximum(cv2.GaussianBlur(L * L, (0, 0), fw * .01) - mu * mu, 0))
    med = np.median(L[low]); sdm = np.median(sd[low])
    cand = low & (L < med - 4) & (sd > max(2.5, sdm * 1.6))
    if cand.sum() < 0.15 * low.sum():
        return np.zeros(shape, np.float32)
    m = cv2.morphologyEx(cand.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), fw * .01)


def skin_mask(img, pts, p=None, seg=None, frames=None):
    """(face skin, neck skin) float32 masks in [0, 1]. seg: segment_face() output or None (landmark
    fallback). frames: glasses_mask()[0] or None."""
    p = p or _opts()
    shape = img.shape[:2]; fw = _fw(pts)
    L = cv2.cvtColor(img, cv2.COLOR_BGR2Lab)[..., 0].astype(np.float32) * (100 / 255)
    skin = landmark_skin_mask(shape, pts)
    neck = np.zeros(shape, np.float32)
    if seg is not None:
        fs = np.clip((seg["face_skin"] - .3) / .4, 0, 1)
        skin *= cv2.GaussianBlur(fs, (0, 0), max(1.0, fw * .004))
        skin *= 1 - np.clip((seg["hair"] - .3) / .4, 0, 1)
        if p.neck > 0:
            up = _up(pts); chin = pts[152]
            yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
            below = -((xx - chin[0]) * up[0] + (yy - chin[1]) * up[1]) / fw      # >0 under the chin
            side = np.abs((xx - chin[0]) * up[1] - (yy - chin[1]) * -up[0]) / fw
            reach = np.clip(1 - below / .9, 0, 1) * (below > -.15) * np.clip((.38 - side) / .1, 0, 1)
            neck = np.clip((seg["body_skin"] - .3) / .4, 0, 1) * reach * float(p.neck)
            neck *= 1 - skin
    # hair strands over the forehead / temples (thin elongated structures above the eyes)
    up = _up(pts); fh = float(np.linalg.norm(pts[10] - pts[152]))
    upper = _hull(shape, np.concatenate([pts[F.FACE_OVAL], pts[F.BROW_L + F.BROW_R] + up * fh * .3]), 0) > .5
    upper &= _hull(shape, np.concatenate([pts[F.BROW_L + F.BROW_R], pts[[10, 109, 338, 67, 297]] + up * fh * .2]), 0) > .5
    strands = cv2.dilate(_line_structures(L, fw, upper).astype(np.uint8), np.ones((3, 3), np.uint8))
    skin *= 1 - cv2.GaussianBlur(strands.astype(np.float32), (0, 0), 1.0)
    if frames is not None:
        skin *= 1 - frames; neck *= 1 - frames
    skin *= 1 - _stubble(L, pts, fw)
    return skin.astype(np.float32), neck.astype(np.float32)


# ---------------------------------------------------------------- skin
def smooth_skin(lab, pts, skin, neck, p, blemish=True):
    """Three-band frequency separation in Lab (float, L 0-100). Returns the new Lab image."""
    fw = _fw(pts)
    m = np.clip(skin + neck, 0, 1)
    if m.max() <= 0 or (p.smooth <= 0 and p.pores >= 1 and p.tone <= 0 and p.light <= 0
                        and p.blemish <= 0 and p.undereye <= 0):
        return lab
    I = lab[..., 0] / 100
    r1, r2 = max(1.0, fw * .006), max(3.0, fw * .035)
    fine = [guided_filter(I, lab[..., c] / 100, r1, .03 ** 2) * 100 for c in range(3)]
    base = [guided_filter(I, fine[c] / 100, r2, .06 ** 2) * 100 for c in range(3)]
    high = [lab[..., c] - fine[c] for c in range(3)]
    mid = [fine[c] - base[c] for c in range(3)]
    sk = skin > .5
    if sk.sum() < 100:
        return lab
    # blemishes: small dark / red mid-band outliers -> drop their mid band, damp their high band
    bl = np.zeros_like(I)
    if blemish and p.blemish > 0:
        mL, ma = mid[0], mid[1]
        sL = 1.4826 * np.median(np.abs(mL[sk] - np.median(mL[sk]))) + 1e-3
        sa = 1.4826 * np.median(np.abs(ma[sk] - np.median(ma[sk]))) + 1e-3
        cand = (((-mL > max(2.0, 3.2 * sL)) | (ma > max(2.0, 3.2 * sa))) & (cv2.erode(skin, np.ones((5, 5))) > .8))
        n, labs, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
        amax = np.pi * (fw * .022) ** 2
        ok = np.zeros(n, bool)
        for i in range(1, n):
            w_, h_, a = st[i, 2], st[i, 3], st[i, 4]
            ok[i] = 2 <= a <= amax and max(w_, h_) <= 3.5 * min(w_, h_) + 2
        bl = ok[labs].astype(np.float32)
        if bl.any():
            bl = cv2.dilate(bl, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(r1 * 2) | 1,) * 2))
            bl = np.clip(cv2.GaussianBlur(bl, (0, 0), r1) * 1.5, 0, 1) * float(min(p.blemish * 1.6, 1))
    # tone evening of the base: chroma toward the median skin chroma, L toward a broad masked mean
    medL, meda, medb = (float(np.median(base[c][sk])) for c in range(3))
    t = float(p.tone)
    if t > 0:
        for c, med in ((1, meda), (2, medb)):
            base[c] = base[c] + (med - base[c]) * t * .6 * m
        s3 = fw * .12
        broad = cv2.GaussianBlur(base[0] * m, (0, 0), s3) / (cv2.GaussianBlur(m, (0, 0), s3) + 1e-4)
        base[0] = base[0] + (broad - base[0]) * t * .3 * m
    # under-eye crescents: lift L toward the cheek and neutralise blue / purple, base only
    if p.undereye > 0:
        ue = undereye_mask(skin.shape, pts) * skin
        cheek = _hull(skin.shape, pts[F.CHEEK_APPLE_L]) + _hull(skin.shape, pts[F.CHEEK_APPLE_R])
        ck = (cheek > .5) & sk
        tgt = float(np.median(base[0][ck])) if ck.sum() > 20 else medL
        k = ue * float(p.undereye)
        base[0] = base[0] + np.maximum(tgt - base[0], 0) * .7 * k + 1.0 * k
        base[1] = base[1] + (meda - base[1]) * .6 * k
        base[2] = base[2] + (medb - base[2]) * .7 * k
    if p.light > 0:
        base[0] = base[0] + float(p.light) * (100 - base[0]) * m
    keep_mid = 1 - np.clip(float(p.smooth) * .85, 0, 1) * m
    keep_high = 1 - (1 - float(p.pores)) * m
    out = np.empty_like(lab)
    for c in range(3):
        out[..., c] = base[c] + mid[c] * keep_mid * (1 - bl) + high[c] * keep_high * (1 - .6 * bl)
    return out


def undereye_mask(shape, pts):
    """Feathered crescents under both eyes, from the lower-lid landmarks."""
    fw = _fw(pts); up = _up(pts)
    m = np.zeros(shape[:2], np.float32)
    for lid in (F.LOWER_LID_L, F.LOWER_LID_R):
        lp = _resample(pts[lid], 15)
        ew = float(np.linalg.norm(lp[0] - lp[-1]))
        s = np.sin(np.linspace(0, np.pi, 15))[:, None]
        top = lp - up * ew * .07
        bot = lp - up * ew * (.07 + .34 * s ** .8)
        m = np.maximum(m, _poly(shape, np.concatenate([top, bot[::-1]]), 0))
    return cv2.GaussianBlur(m, (0, 0), fw * .02)


# ---------------------------------------------------------------- makeup
def _blend_lab(lab, m, target, wa=1.0, wb=1.0, dl=0.0):
    lab[..., 1] += (target[1] - lab[..., 1]) * m * wa
    lab[..., 2] += (target[2] - lab[..., 2]) * m * wb
    if dl:
        lab[..., 0] += dl * m


def apply_makeup(lab, pts, skin, frames, mk, thick_frames=False, L0=None):
    """Makeup v2 on a Lab float image (L 0-100) in place. mk: makeup_params() output."""
    shape = lab.shape[:2]; fw = _fw(pts); up = _up(pts)
    L0 = lab[..., 0].copy() if L0 is None else L0
    nf = 1 - (frames if frames is not None else 0)
    if mk["lip"] > 0:
        w = mk["lip"]; t = mk["lip_shade"]
        outer = _poly(shape, pts[F.LIPS_OUT], max(1.2, fw * .006))
        inner = _poly(shape, pts[F.LIPS_IN], 0)
        inner = cv2.GaussianBlur(cv2.dilate(inner, np.ones((3, 3))), (0, 0), max(1.0, fw * .003))
        m = np.clip(outer - inner, 0, 1)
        lk = m > .5
        if lk.sum() > 10:
            medL = float(np.median(lab[..., 0][lk]))
            lab[..., 0] += (t[0] - medL) * .45 * w * m                  # shift, texture kept
            # chroma: move toward the shade but keep a share of the lip's own variation (no flat paint)
            for c in (1, 2):
                med = float(np.median(lab[..., c][lk]))
                lab[..., c] += ((t[c] - med) * (.8 if c == 1 else .65)) * w * m
            if mk["gloss"] > 0:
                p80, p98 = np.percentile(L0[lk], 80), np.percentile(L0[lk], 98.5)
                g = np.clip((L0 - p80) / (p98 - p80 + 1e-3), 0, 1) * m
                g = cv2.GaussianBlur(g, (0, 0), max(.8, fw * .002))
                lab[..., 0] += g * mk["gloss"] * w * 9
                lab[..., 1] *= 1 - g * mk["gloss"] * .25
    if mk["blush"] > 0:
        w = mk["blush"]; t = mk["blush_shade"]
        m = np.zeros(shape, np.float32)
        for apple, temple in ((F.CHEEK_APPLE_L, 127), (F.CHEEK_APPLE_R, 356)):
            a = pts[apple].mean(0); v = pts[temple] - a
            c = a + v * .18 + up * fw * .015
            ang = np.degrees(np.arctan2(v[1], v[0]))
            e = np.zeros(shape, np.float32)
            cv2.ellipse(e, (int(c[0]), int(c[1])), (int(fw * .13), int(fw * .075)), ang, 0, 360, 1, -1)
            m = np.maximum(m, cv2.GaussianBlur(e, (0, 0), fw * .055))
        m *= skin * w
        _blend_lab(lab, m, t, .55, .45, -1.5)
    if mk["contour"] > 0 or mk["highlight"] > 0:
        con = np.zeros(shape, np.float32); hi = np.zeros(shape, np.float32)
        for side, corner, apple, outer in ((234, 61, F.CHEEK_APPLE_L, 33), (454, 291, F.CHEEK_APPLE_R, 263)):
            a, b = pts[side], pts[corner]
            cv2.line(con, tuple(int(v) for v in a + (b - a) * .05), tuple(int(v) for v in a + (b - a) * .5),
                     1, max(1, int(fw * .06)), cv2.LINE_AA)
            ap = pts[apple].mean(0); hc = ap + (pts[outer] - ap) * .45
            cv2.circle(hi, (int(hc[0]), int(hc[1])), max(1, int(fw * .045)), 1, -1)
        for a, b in zip(F.JAW_SLIM[:4], F.JAW_SLIM[1:4]):
            cv2.line(con, tuple(int(v) for v in pts[a]), tuple(int(v) for v in pts[b]), .6, max(1, int(fw * .04)))
        for a, b in zip(F.JAW_SLIM[-4:-1], F.JAW_SLIM[-3:]):
            cv2.line(con, tuple(int(v) for v in pts[a]), tuple(int(v) for v in pts[b]), .6, max(1, int(fw * .04)))
        nb = pts[F.NOSE_BRIDGE]
        cv2.polylines(hi, [np.round(nb).astype(np.int32)], False, 1, max(1, int(fw * .03)), cv2.LINE_AA)
        fc = pts[151]; cv2.circle(hi, (int(fc[0]), int(fc[1])), max(1, int(fw * .07)), .8, -1)
        cc = pts[152] + up * fw * .09; cv2.circle(hi, (int(cc[0]), int(cc[1])), max(1, int(fw * .04)), .7, -1)
        con = cv2.GaussianBlur(con, (0, 0), fw * .035) * skin * mk["contour"]
        hi = cv2.GaussianBlur(hi, (0, 0), fw * .025) * skin * mk["highlight"]
        lab[..., 0] += -5.0 * con + 5.0 * hi
        lab[..., 2] += 1.5 * con
    if mk["brow"] > 0:
        w = mk["brow"]
        for brow in (F.BROW_L, F.BROW_R):
            bp = pts[brow]
            bm = _poly(shape, bp, 0) > .5
            if bm.sum() < 10:
                continue
            Lb = lab[..., 0][bm]; dark = Lb <= np.percentile(Lb, 35)
            tL = float(np.median(Lb[dark])) - 2
            ta = float(np.median(lab[..., 1][bm][dark])); tb = float(np.median(lab[..., 2][bm][dark]))
            inner, outer = bp[[4, 5]].mean(0), bp[[0, 9]].mean(0)
            ax = outer - inner; ln = float(np.dot(ax, ax)) + 1e-6
            yy, xx = np.mgrid[0:shape[0], 0:shape[1]].astype(np.float32)
            s = np.clip(((xx - inner[0]) * ax[0] + (yy - inner[1]) * ax[1]) / ln, 0, 1)
            taper = np.interp(s, [0, .25, .7, 1], [.45, .9, 1, .7]).astype(np.float32)
            m = _poly(shape, bp, max(1.0, fw * .005)) * taper * w * nf
            lab[..., 0] += np.minimum(tL - lab[..., 0], 0) * .75 * m
            _blend_lab(lab, m, (0, ta, tb), .4, .4)
    if not thick_frames and (mk["liner"] > 0 or mk["shadow"] > 0):
        for lid, ring, brow in ((F.UPPER_LID_L, F.LEFT_EYE_RING, F.BROW_LOW_L),
                                (F.UPPER_LID_R, F.RIGHT_EYE_RING, F.BROW_LOW_R)):
            lp = _resample(pts[lid], 16)                    # outer -> inner
            ew = float(np.linalg.norm(lp[0] - lp[-1]))
            eye = _hull(shape, pts[ring], 0)
            if mk["shadow"] > 0:
                bp = _resample(pts[brow], 16)
                mid1 = lp + (bp - lp) * .55
                mid2 = lp + (bp - lp) * .3
                m = (.5 * _poly(shape, np.concatenate([lp, mid1[::-1]]), fw * .02)
                     + .6 * _poly(shape, np.concatenate([lp, mid2[::-1]]), fw * .012))
                m = np.clip(m, 0, 1) * (1 - eye) * nf * mk["shadow"]
                _blend_lab(lab, m, mk["shadow_shade"], .5, .5, (mk["shadow_shade"][0] - 60) * .12)
            if mk["liner"] > 0:
                sc = 4
                lm_ = np.zeros((shape[0], shape[1]), np.uint8)
                d = lp[0] - lp[-1]; d = d / (np.linalg.norm(d) + 1e-6)
                tail_dir = d * .94 + up * .34
                path = np.concatenate([lp[::-1], [lp[0] + tail_dir * ew * .2]])
                for i in range(len(path) - 1):
                    s = i / (len(path) - 2)
                    th = fw * (.0025 + .007 * min(s, 1)) if i < len(path) - 2 else fw * .004
                    a, b = path[i] + up * th * .4, path[i + 1] + up * th * .4
                    cv2.line(lm_, tuple(np.round(a * sc).astype(int)), tuple(np.round(b * sc).astype(int)), 255,
                             max(1, int(th)), cv2.LINE_AA, shift=2)
                m = cv2.GaussianBlur(lm_.astype(np.float32) / 255, (0, 0), .7) * nf * mk["liner"]
                t = mk["liner_shade"]
                lab[..., 0] += (t[0] - lab[..., 0]) * m * .85
                _blend_lab(lab, m, t, .6, .6)


# ---------------------------------------------------------------- per-face pass
def skin_and_makeup(img, f, p, state=None, seg=None):
    """De-shined image -> smoothed, tone-evened, blemish-cleaned, made-up image (whole frame, but
    processed on a face ROI). Backward-compatible signature."""
    if not hasattr(p, "pores"):
        p = _opts(**vars(p))
    pts = np.asarray(f["pts"], np.float32)
    h, w = img.shape[:2]; fw = _fw(pts)
    x0, y0, x1, y1 = _roi_box(pts, img.shape, .35)
    y1 = min(h, int(pts[152][1] + .8 * fw))                     # room for the neck
    roi = np.ascontiguousarray(img[y0:y1, x0:x1])
    rp = pts - np.array([x0, y0], np.float32)
    if seg is None and p.skin_seg:
        seg = segment_face(roi, rp, state)
    gl = str(p.glasses)
    frames, thick = glasses_mask(roi, rp, seg.get("others") if seg else None)
    if gl == "none":
        frames, thick = None, 0.0
    thick_frames = gl == "thick" or (gl == "auto" and thick > THICK_FRAME)
    skin, neck = skin_mask(roi, rp, p, seg, frames)
    lab = cv2.cvtColor(roi.astype(np.float32) / 255, cv2.COLOR_BGR2Lab)
    L0 = lab[..., 0].copy()
    lab = smooth_skin(lab, rp, skin, neck, p)
    if p.makeup > 0:
        mk = makeup_params(p.preset, p.makeup, **{k: getattr(p, k) for k in COMPONENTS + SHADE_KEYS
                                                  if getattr(p, k, None) is not None})
        apply_makeup(lab, rp, skin, frames, mk, thick_frames, L0)
    res = cv2.cvtColor(lab, cv2.COLOR_Lab2BGR)
    res = np.clip(np.rint(res * 255), 0, 255).astype(np.uint8)
    out = img.copy()
    out[y0:y1, x0:x1] = res
    return out


def gaussian_filter1d(x, sigma, truncate=4.0):
    """scipy.ndimage.gaussian_filter1d(x, sigma) of a 1-D array without scipy: normalised Gaussian
    of radius int(truncate * sigma + 0.5), mode='reflect' (half-sample symmetric, = np.pad
    'symmetric', which also repeats the reflection when the signal is shorter than the radius)."""
    x = np.asarray(x, np.float64)
    r = int(truncate * float(sigma) + 0.5)
    w = np.exp(-0.5 * (np.arange(-r, r + 1) / float(sigma)) ** 2)
    return np.convolve(np.pad(x, r, mode="symmetric"), w / w.sum(), mode="valid")


def body_slim(img, f, k):
    """Squeeze the main person horizontally toward each row's centre (selfie segmenter)."""
    if k <= 0:
        return img
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    from .config import model
    seg = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
        base_options=BaseOptions(model_asset_path=model("selfie_segmenter")), output_confidence_masks=True))
    conf = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB))).confidence_masks[-1].numpy_view()
    m = (conf > .5).astype(np.uint8) * 255
    m = cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)), cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats((m > 0).astype(np.uint8), 8)
    sx, sy = np.clip(f["pts"][1].astype(int), 0, [img.shape[1] - 1, img.shape[0] - 1])
    lbl = lab[sy, sx] or (1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])) if n > 1 else 0)
    mm = lab == lbl
    h, w = mm.shape; cx = np.full(h, np.nan); hw = np.zeros(h); pres = np.zeros(h)
    for y in range(h):
        xs = np.flatnonzero(mm[y])
        if xs.size > w * .03:
            cx[y] = (xs[0] + xs[-1]) / 2; hw[y] = (xs[-1] - xs[0]) / 2; pres[y] = 1
    ok = ~np.isnan(cx)
    if ok.sum() < 8:
        return img
    ys = np.arange(h); sig = max(3.0, h * .02)
    cx = gaussian_filter1d(np.interp(ys, ys[ok], cx[ok]), sig)
    hw = gaussian_filter1d(np.maximum(np.interp(ys, ys[ok], hw[ok]), 1), sig)
    pres = gaussian_filter1d(pres, sig)
    gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = gx - cx[:, None]; r = np.abs(d) / hw[:, None]
    fall = np.where(r <= 1, 1, np.clip((1.35 - r) / .35, 0, 1)) * pres[:, None]
    return cv2.remap(img, (cx[:, None] + d * (1 + k * fall)).astype(np.float32), gy, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def _select_faces(img, f, lm, p):
    """-> list of face dicts (largest first) to retouch."""
    if f is None:
        try:
            lm = lm or F.landmarker(1 if p.faces == "main" else 6)
            faces = F.detect(lm, img)
        except FileNotFoundError as e:                  # MissingAsset: no model -> no-op
            print("retouch: skipped,", e)
            return []
    else:
        faces = list(f) if isinstance(f, (list, tuple)) else [f]
    faces = [x for x in faces if x is not None]
    faces.sort(key=lambda x: -np.ptp(x["pts"][:, 0]) * np.ptp(x["pts"][:, 1]))
    if not faces:
        return []
    if p.faces == "main":
        return faces[:1]
    W = img.shape[1]
    return [x for i, x in enumerate(faces) if i == 0 or np.ptp(x["pts"][:, 0]) / W >= float(p.min_face)]


_SCALED = ("slim", "eye", "eye_extra", "shine", "smooth", "light", "makeup", "tone", "blemish", "undereye")


def retouch(img, f=None, lm=None, **kw):
    """Full pipeline on one BGR image. Pass a detected face `f` (dict or list of dicts) or a landmarker
    `lm` (else one is created). Knobs: DEFAULTS + EXTRA (see references/RETOUCH.md). Video: pass
    state=RetouchState(video=True) (one per tracked face) and grid~160."""
    p = _opts(**kw)
    if p.preset not in PRESETS:
        raise ValueError(f"unknown makeup preset {p.preset!r}; one of {sorted(PRESETS)}")
    faces = _select_faces(img, f, lm, p)
    if not faces:
        return img
    strengths = p.face_strength
    if strengths is None:
        strengths = [1.0] * len(faces)
    elif np.isscalar(strengths):
        strengths = [float(strengths)] * len(faces)
    else:
        strengths = list(strengths) + [1.0] * (len(faces) - len(strengths))
    orig = img
    out = img
    plans = []
    for i, fc in enumerate(faces):
        q = types.SimpleNamespace(**vars(p))
        for k in _SCALED:
            setattr(q, k, getattr(q, k) * float(strengths[i]))
        st = p.state if i == 0 else None
        out, moved = _warp(out, fc, q, st)
        plans.append((q, {"pts": moved, "blend": fc.get("blend", {})}, st))
    if p.body > 0:
        out = body_slim(out, plans[0][1], p.body)
    keep = np.zeros(img.shape[:2], np.float32)
    for q, fc, st in plans:
        x0, y0, x1, y1 = _roi_box(fc["pts"], out.shape, .35)
        sub = deshine(np.ascontiguousarray(out[y0:y1, x0:x1]), {"pts": fc["pts"] - [x0, y0]}, q)
        out = out.copy(); out[y0:y1, x0:x1] = sub
        out = skin_and_makeup(out, fc, q, st)
        pts = fc["pts"]; fw = np.ptp(pts[:, 0]); c = pts.mean(0)
        e = np.zeros(img.shape[:2], np.float32)
        cv2.ellipse(e, (int(c[0]), int(c[1] + .1 * fw)), (int(fw * .8), int(np.ptp(pts[:, 1]) * .8)), 0, 0, 360, 1, -1)
        keep = np.maximum(keep, cv2.GaussianBlur(e, (0, 0), fw * .08))
    if p.region and p.body <= 0:              # keep edits on the face only: no warp seams elsewhere
        k = keep[..., None]
        out = np.clip(out.astype(np.float32) * k + orig.astype(np.float32) * (1 - k) + .5, 0, 255).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp"); ap.add_argument("out")
    for k, v in DEFAULTS.items():
        if k != "region":
            ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float, default=v)
    for k in ("pores", "tone", "blemish", "undereye", "neck", "min_face", "natural_cap", "identity_guard",
              "lip", "blush", "brow", "liner", "shadow", "contour", "highlight", "gloss"):
        ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float, default=None)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="natural")
    for k in SHADE_KEYS:
        ap.add_argument(f"--{k.replace('_', '-')}", dest=k, default=None, help="shade name or #rrggbb")
    ap.add_argument("--glasses", choices=("auto", "none", "thin", "thick"), default="auto")
    ap.add_argument("--faces", choices=("main", "all"), default="main")
    ap.add_argument("--face-strength", dest="face_strength", default=None,
                    help="comma list of per-face strengths, largest face first (e.g. 1,0.6)")
    ap.add_argument("--no-seg", dest="skin_seg", action="store_false", help="landmark-only skin mask")
    ap.add_argument("--no-region", dest="region", action="store_false")
    a = vars(ap.parse_args())
    if a.get("face_strength"):
        a["face_strength"] = [float(v) for v in a["face_strength"].split(",")]
    img = cv2.imread(a.pop("inp")); out = a.pop("out")
    if img is None:
        raise SystemExit("cannot read input image")
    try:
        lm = F.landmarker(1 if a["faces"] == "main" else 6)
    except FileNotFoundError as e:
        raise SystemExit(str(e))
    cv2.imwrite(out, retouch(img, lm=lm, **a))
    print("retouched ->", out)


if __name__ == "__main__":
    main()
