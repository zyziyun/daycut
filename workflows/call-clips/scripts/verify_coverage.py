#!/usr/bin/env python3
"""Geometric proof that the sticker hides the guest's face on every frame.

Re-detecting faces in the masked video is useless: the detector happily locks
onto the cartoon cat's own eyes and mouth. So instead compare, frame by frame,
the tracked human face box against the sticker's opaque alpha footprint and
report the worst-covered frame.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, sys
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--track", required=True)
    ap.add_argument("--sticker", required=True)
    ap.add_argument("--scale", type=float, default=2.40)
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--margin", type=float, default=0.10,
                    help="grow the face box by this fraction before checking")
    ap.add_argument("--min-coverage", type=float, default=1.0)
    args = ap.parse_args()

    tr = json.load(open(args.track))
    cxs, cys, ws, hs = tr["cx"], tr["cy"], tr["w"], tr["h"]
    fps = tr["fps"]

    st = np.array(Image.open(args.sticker).convert("RGBA"))
    opaque = st[:, :, 3] > 200
    s_h0, s_w0 = st.shape[:2]
    # opaque footprint in sticker-relative units (0..1 of sticker width/height)
    ys, xs = np.nonzero(opaque)
    print(f"sticker opaque box: x {xs.min()/s_w0:.3f}-{xs.max()/s_w0:.3f}  "
          f"y {ys.min()/s_h0:.3f}-{ys.max()/s_h0:.3f} of the PNG")

    worst, worst_i = 2.0, 0
    for i in range(len(cxs)):
        tw = max(24, int(round(ws[i] * args.scale)))
        th = int(round(tw * s_h0 / s_w0))
        m = np.array(Image.fromarray(opaque.astype(np.uint8) * 255)
                     .resize((tw, th), Image.NEAREST)) > 127
        sx0 = cxs[i] - tw / 2
        sy0 = cys[i] + args.y_offset * th - th / 2

        fw, fh = ws[i] * (1 + args.margin), hs[i] * (1 + args.margin)
        fx0, fy0 = cxs[i] - fw / 2, cys[i] - fh / 2

        # a face is an oval, not a rectangle: sampling the bbox corners would
        # count background pixels as "uncovered" and never reach 100%
        gx = np.linspace(fx0, fx0 + fw, 61)
        gy = np.linspace(fy0, fy0 + fh, 61)
        GX, GY = np.meshgrid(gx, gy)
        oval = (((GX - cxs[i]) / (fw / 2)) ** 2 + ((GY - cys[i]) / (fh / 2)) ** 2) <= 1.0
        IX = np.round(GX - sx0).astype(int)
        IY = np.round(GY - sy0).astype(int)
        inside = (IX >= 0) & (IX < tw) & (IY >= 0) & (IY < th) & oval
        covered = np.zeros_like(inside)
        covered[inside] = m[IY[inside], IX[inside]]
        frac = covered.sum() / oval.sum()
        if frac < worst:
            worst, worst_i = frac, i

    print(f"frames={len(cxs)}  worst coverage={worst:.3%} at t={worst_i/fps:.2f}s "
          f"(face box grown {args.margin:.0%})")
    if worst < args.min_coverage:
        print("  FAIL: some part of the face box is outside the sticker")
        sys.exit(1)
    print("  PASS")


if __name__ == "__main__":
    main()
