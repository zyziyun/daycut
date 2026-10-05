"""Portrait retouch for covers and talking-head frames: face slim + eye open (MLS), de-shine,
skin smoothing with texture kept, light makeup (lips, blush, brows), optional body slim.

Edits are composited back through a feathered face-region mask, so warp ROI borders never show
as seams on hands, shirts or the wall (a real failure we hit on a cover).

CLI:  python -m vstudio.retouch in.png out.png [--slim .06] [--eye .04] [--makeup .5] [--body 0]
"""
import argparse
import types

import cv2
import numpy as np

from . import face as F
from .mls import inverse_map

DEFAULTS = dict(slim=0.05, eye=0.04, eye_extra=0.0, shine=0.8, shine_feather=2.5,
                smooth=0.6, light=0.05, makeup=0.5, body=0.0, region=True)


def _opts(**kw):
    d = dict(DEFAULTS); d.update({k: v for k, v in kw.items() if v is not None})
    return types.SimpleNamespace(**d)


def _poly(shape, pts, blur=0.0):
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [pts.astype(np.int32)], 255)
    m = m.astype(np.float32) / 255
    return cv2.GaussianBlur(m, (0, 0), blur) if blur > 0 else m


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
        e = F.ear(pts, ear_i); bl = float(blend.get(bk, 0.0))
        squint = np.clip((0.30 - e) / 0.18, 0, 1) * 0.6 + np.clip((bl - 0.20) / 0.55, 0, 1) * 0.4
        grow = p.eye + p.eye_extra * float(squint)
        for idx in ring:
            x, y = pts[idx]
            P.append([x - rx0, y - ry0])
            Q.append([cx + (x - cx) * (1 + grow) - rx0, cy + (y - cy) * (1 + grow * 1.15) - ry0])
    return np.array(P, np.float64), np.array(Q, np.float64)


def warp_face(img, f, p):
    if p.slim <= 0 and p.eye <= 0:
        return img
    pts = f["pts"]; h, w = img.shape[:2]
    x0, y0 = pts.min(0); x1, y1 = pts.max(0)
    pad = int(0.5 * max(x1 - x0, y1 - y0))
    rx0, ry0 = max(0, int(x0 - pad)), max(0, int(y0 - pad))
    rx1, ry1 = min(w, int(x1 + pad)), min(h, int(y1 + pad))
    roi = img[ry0:ry1, rx0:rx1]
    P, Q = _controls(pts, f["blend"], (rx0, ry0, roi.shape[0], roi.shape[1]), p)
    mx, my = inverse_map(roi.shape[0], roi.shape[1], P, Q)
    out = img.copy()
    out[ry0:ry1, rx0:rx1] = cv2.remap(roi, mx, my, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    return out


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


def skin_and_makeup(img, f, p):
    pts = f["pts"]; h, w = img.shape[:2]; fw = np.ptp(pts[:, 0])
    out = img.astype(np.float32)
    if p.smooth > 0:
        skin = _poly(img.shape, pts[F.FACE_OVAL], fw * .02)
        for ring in (F.BROW_L, F.BROW_R, F.LIPS_OUT, F.LEFT_EYE_RING, F.RIGHT_EYE_RING):
            hole = np.zeros((h, w), np.uint8)
            cv2.fillConvexPoly(hole, cv2.convexHull(pts[ring].astype(np.int32)), 255)
            hole = cv2.dilate(hole, np.ones((int(fw * .03) | 1,) * 2, np.uint8))
            skin *= 1 - cv2.GaussianBlur(hole.astype(np.float32) / 255, (0, 0), fw * .01)
        sm = cv2.bilateralFilter(img, 0, 24, 9).astype(np.float32) + (out - cv2.GaussianBlur(out, (0, 0), 1.0)) * .45
        a = (skin * p.smooth)[..., None]
        out = out * (1 - a) + sm * a
        out = out + (skin * p.light)[..., None] * (255 - out)
    if p.makeup > 0:
        k = p.makeup
        for c in (pts[F.CHEEK_APPLE_L].mean(0), pts[F.CHEEK_APPLE_R].mean(0)):        # blush
            m = np.zeros((h, w), np.float32); cv2.circle(m, (int(c[0]), int(c[1])), int(fw * .11), 1, -1)
            m = (cv2.GaussianBlur(m, (0, 0), fw * .07) * .55 * k)[..., None]
            out = out * (1 - m) + np.array([150, 120, 235], np.float32) * m
        lip = _poly(img.shape, pts[F.LIPS_OUT], 2.0) * (1 - _poly(img.shape, pts[F.LIPS_IN], 1.5))   # lips
        lum = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)[..., None] / 255
        a = (lip * 1.05 * k)[..., None]
        out = out * (1 - a) + np.array([95, 85, 205], np.float32) * (0.55 + lum * .6) * a
        for b in (F.BROW_L, F.BROW_R):                                                       # brows
            m = (_poly(img.shape, pts[b], 2.5) * .45 * k)[..., None]
            out = out * (1 - m) + np.array([45, 40, 42], np.float32) * m
    return np.clip(out, 0, 255).astype(np.uint8)


def body_slim(img, f, k):
    """Squeeze the main person horizontally toward each row's centre (selfie segmenter)."""
    if k <= 0:
        return img
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    from scipy.ndimage import gaussian_filter1d
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


def retouch(img, f=None, lm=None, **kw):
    """Full pipeline on one BGR image. Pass a detected face `f` (or a landmarker `lm`)."""
    p = _opts(**kw)
    if f is None:
        lm = lm or F.landmarker(1)
        f = F.main_face(F.detect(lm, img))
        if f is None:
            return img
    orig = img
    out = warp_face(img, f, p)
    if p.body > 0:
        out = body_slim(out, f, p.body)
    if lm is not None:
        f2 = F.main_face(F.detect(lm, out)) or f
    else:
        f2 = f
    out = deshine(out, f2, p)
    out = skin_and_makeup(out, f2, p)
    if p.region and p.body <= 0:              # keep edits on the face only: no warp seams elsewhere
        pts = f2["pts"]; fw = np.ptp(pts[:, 0]); c = pts.mean(0)
        keep = np.zeros(img.shape[:2], np.float32)
        cv2.ellipse(keep, (int(c[0]), int(c[1])), (int(fw * .8), int(np.ptp(pts[:, 1]) * .72)), 0, 0, 360, 1, -1)
        keep = cv2.GaussianBlur(keep, (0, 0), fw * .08)[..., None]
        out = (out.astype(np.float32) * keep + orig.astype(np.float32) * (1 - keep)).astype(np.uint8)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("inp"); ap.add_argument("out")
    for k, v in DEFAULTS.items():
        if k != "region":
            ap.add_argument(f"--{k.replace('_', '-')}", dest=k, type=float, default=v)
    ap.add_argument("--no-region", dest="region", action="store_false")
    a = vars(ap.parse_args())
    img = cv2.imread(a.pop("inp")); out = a.pop("out")
    cv2.imwrite(out, retouch(img, lm=F.landmarker(1), **a))
    print("retouched ->", out)


if __name__ == "__main__":
    main()
