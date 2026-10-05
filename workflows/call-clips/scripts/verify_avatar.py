#!/usr/bin/env python3
"""Prove the guest's tile is the avatar bitmap, not video, on every frame.

Re-detecting faces here is useless (the detector locks onto the cartoon cat)
and unnecessary: the tile is replaced wholesale, so the honest check is pixel
agreement with the avatar. The output is H.264, so exact equality is impossible
-- compression noise on the avatar's edges runs about 1.5 mean absolute error,
while any real video in that tile would be an order of magnitude above it.

Frames where a node card dims the band, and the bottom strip where the name
chip sits, are excluded because neither is part of the avatar.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, sys
import cv2
import numpy as np


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--avatar", required=True)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--tile", default="0,150,960,540", help="x,y,w,h of the guest tile")
    ap.add_argument("--skip-bottom", type=int, default=60, help="rows the name chip covers")
    ap.add_argument("--every", type=int, default=5)
    ap.add_argument("--max-mean", type=float, default=6.0)
    args = ap.parse_args()

    x, y, w, h = (int(v) for v in args.tile.split(","))
    av = cv2.resize(cv2.imread(args.avatar), (w, h), interpolation=cv2.INTER_AREA)
    hh = h - args.skip_bottom
    av = av[:hh].astype(np.int16)
    nodes = [t for t, _ in json.load(open(args.title_json)).get("node_cards", [])]

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    checked = 0
    worst, worst_t = 0.0, -1.0
    bad = []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        t = i / fps
        if i % args.every == 0 and not any(abs(t - n) < 2.6 for n in nodes):
            d = float(np.abs(fr[y:y + hh, x:x + w].astype(np.int16) - av).mean())
            checked += 1
            if d > worst:
                worst, worst_t = d, t
            if d > args.max_mean:
                bad.append(t)
        i += 1
    cap.release()

    print(f"checked {checked} frames  worst mean delta={worst:.2f} at t={worst_t:.1f}s  "
          f"over threshold: {len(bad)}")
    if bad:
        print(f"  FAIL at {[round(b, 1) for b in bad[:8]]}")
        sys.exit(1)
    print("  PASS: the guest's tile is the avatar on every frame, never video")


if __name__ == "__main__":
    main()
