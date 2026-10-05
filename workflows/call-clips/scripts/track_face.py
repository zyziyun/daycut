#!/usr/bin/env python3
"""Track one person's face inside a fixed region of a video.

Pass 1 of the mask pipeline. Writes a per-frame track (JSON) of the face
bounding box, with detection gaps filled and the path smoothed, so that pass 2
can paste a sticker that never blinks off.

Usage:
  track_face.py VIDEO --region x,y,w,h --out track.json [--start S] [--dur D]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json
import cv2
import numpy as np


def ema(vals, alpha):
    out = []
    acc = None
    for v in vals:
        acc = v if acc is None else alpha * v + (1 - alpha) * acc
        out.append(acc)
    return out


def fill_gaps(series):
    """Linear-interpolate None holes; hold the nearest known value at the ends."""
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--region", required=True, help="x,y,w,h of the tile to search")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=None,
                    help="face_landmarker.task (default: vstudio.config.model('face_landmarker'))")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--dur", type=float, default=None)
    ap.add_argument("--smooth", type=float, default=0.25, help="EMA alpha; lower = steadier")
    ap.add_argument("--search", default=None,
                    help="x,y,w,h inside the region to detect in (e.g. a portrait phone "
                         "video pillarboxed in a wide tile); upscaled by --upscale first")
    ap.add_argument("--upscale", type=float, default=1.0)
    args = ap.parse_args()

    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    from vstudio.config import model
    model_path = args.model or model("face_landmarker")

    rx, ry, rw, rh = (int(v) for v in args.region.split(","))
    # the landmarker loses a ~55px face in a 640x360 tile; detecting in a tight,
    # upscaled crop and mapping back keeps it locked on every frame
    sx, sy, sw, sh = ((int(v) for v in args.search.split(","))
                      if args.search else (rx, ry, rw, rh))
    up = args.upscale

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    if args.start:
        cap.set(cv2.CAP_PROP_POS_MSEC, args.start * 1000.0)
    n_target = int(round(args.dur * fps)) if args.dur else None

    opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
    )

    cx_s, cy_s, w_s, h_s = [], [], [], []
    n_hit = 0
    with vision.FaceLandmarker.create_from_options(opts) as det:
        i = 0
        while True:
            if n_target is not None and i >= n_target:
                break
            ok, frame = cap.read()
            if not ok:
                break
            tile = frame[sy:sy + sh, sx:sx + sw]
            if up != 1.0:
                tile = cv2.resize(tile, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC)
            rgb = np.ascontiguousarray(cv2.cvtColor(tile, cv2.COLOR_BGR2RGB))
            img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            res = det.detect_for_video(img, int(round(i / fps * 1000)))
            if res.face_landmarks:
                lm = res.face_landmarks[0]
                xs = np.array([p.x for p in lm]) * sw
                ys = np.array([p.y for p in lm]) * sh
                x0, x1 = xs.min(), xs.max()
                y0, y1 = ys.min(), ys.max()
                cx_s.append((x0 + x1) / 2 + sx)
                cy_s.append((y0 + y1) / 2 + sy)
                w_s.append(x1 - x0)
                h_s.append(y1 - y0)
                n_hit += 1
            else:
                for s in (cx_s, cy_s, w_s, h_s):
                    s.append(None)
            i += 1
    cap.release()

    n = len(cx_s)
    if n == 0:
        sys.exit("no frames read")
    if n_hit == 0:
        sys.exit("no face detected anywhere in the region -- check --region")

    cx_s, cy_s, w_s, h_s = (fill_gaps(s) for s in (cx_s, cy_s, w_s, h_s))
    a = args.smooth
    cx_s, cy_s = ema(cx_s, a), ema(cy_s, a)
    # size drifts less than position and a shrinking sticker is the risky
    # direction, so smooth it harder and floor it at the run's median.
    w_s, h_s = ema(w_s, a * 0.5), ema(h_s, a * 0.5)
    w_med, h_med = float(np.median(w_s)), float(np.median(h_s))
    w_s = [max(v, w_med * 0.9) for v in w_s]
    h_s = [max(v, h_med * 0.9) for v in h_s]

    json.dump({
        "fps": fps,
        "n_frames": n,
        "hit_rate": round(n_hit / n, 4),
        "region": [rx, ry, rw, rh],
        "cx": cx_s, "cy": cy_s, "w": w_s, "h": h_s,
    }, open(args.out, "w"))
    print(f"frames={n} detected={n_hit} hit_rate={n_hit/n:.1%} "
          f"face_w_median={w_med:.0f}px -> {args.out}")


if __name__ == "__main__":
    main()
