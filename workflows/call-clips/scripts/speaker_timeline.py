#!/usr/bin/env python3
"""Who is talking, per moment, from mouth movement alone.

A call recording is usually a single mixed audio track, so there is no diarisation to read.
But it is gallery view: each participant has a fixed tile. Track the inner-lip
gap in both tiles and whoever's mouth is moving more over a short window is the
one speaking. Attributing a quote to the wrong person is the one mistake a clip
about "she said / I said" cannot survive, so this is measured, not guessed.

Usage:
  speaker_timeline.py VIDEO --tiles guest=0,180,640,360 host=640,180,640,360 \
      --out speakers.json [--every 3]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json
import cv2
import numpy as np
# inner lip centre pair, and the face-oval extremes used to normalise
UPPER_LIP, LOWER_LIP, CHIN, FOREHEAD = 13, 14, 152, 10


def mouth_gap(lm):
    up, lo = lm[UPPER_LIP], lm[LOWER_LIP]
    face_h = abs(lm[CHIN].y - lm[FOREHEAD].y) or 1e-6
    return abs(lo.y - up.y) / face_h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--tiles", nargs="+", required=True, help="name=x,y,w,h")
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=int, default=3)
    ap.add_argument("--win", type=float, default=0.8, help="variance window, seconds")
    args = ap.parse_args()

    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    from vstudio.config import model
    MODEL = model("face_landmarker")

    tiles = {}
    for t in args.tiles:
        name, rect = t.split("=")
        tiles[name] = [int(v) for v in rect.split(",")]

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    dets = {}
    for name in tiles:
        dets[name] = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL),
                running_mode=vision.RunningMode.VIDEO, num_faces=1))

    times, series = [], {n: [] for n in tiles}
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % args.every == 0:
            ts = i / fps
            times.append(ts)
            for name, (x, y, w, h) in tiles.items():
                rgb = cv2.cvtColor(fr[y:y + h, x:x + w], cv2.COLOR_BGR2RGB)
                res = dets[name].detect_for_video(
                    mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                    int(round(ts * 1000)))
                series[name].append(mouth_gap(res.face_landmarks[0])
                                    if res.face_landmarks else np.nan)
        i += 1
    cap.release()
    for d in dets.values():
        d.close()

    step = args.every / fps
    k = max(3, int(round(args.win / step)))
    energy = {}
    for name, vals in series.items():
        a = np.array(vals, dtype=float)
        # hold the last reading through a dropped detection rather than
        # letting a NaN read as silence
        idx = np.where(~np.isnan(a))[0]
        if len(idx):
            a = np.interp(np.arange(len(a)), idx, a[idx])
        else:
            a = np.zeros(len(a))
        pad = np.pad(a, (k // 2, k // 2), mode="edge")
        energy[name] = np.array([pad[j:j + k].std() for j in range(len(a))])

    names = list(tiles)
    E = np.vstack([energy[n] for n in names])
    win = E.argmax(axis=0)
    # margin between the loudest mouth and the runner-up, so this works for
    # any number of tiles, not just two
    top2 = np.sort(E, axis=0)[-2:] if len(names) > 1 else np.vstack([E, 0 * E])
    margin = (top2[1] - top2[0]) / (E.max(axis=0) + 1e-9)
    labels = [names[w] if m > 0.18 else "both" for w, m in zip(win, margin)]

    json.dump({"fps": fps, "step": step, "times": times, "labels": labels,
               "energy": {n: energy[n].tolist() for n in names}},
              open(args.out, "w"))
    from collections import Counter
    c = Counter(labels)
    print(f"{len(times)} samples @ {step:.3f}s  " +
          "  ".join(f"{k2}={v*step:.0f}s" for k2, v in c.most_common()))


if __name__ == "__main__":
    main()
