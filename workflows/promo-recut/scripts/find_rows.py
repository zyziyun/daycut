#!/usr/bin/env python3
"""Measure text-row bands in a screenshot with numpy, so card highlights / boxes / scroll targets and
cover thumbnail crops use real pixel rows instead of guesses.

  python3 $VSTUDIO/workflows/promo-recut/scripts/find_rows.py input/shot1.png [--preview work/shot1_rows.png]

Prints one line per band: index, y0, y1 (image px, the units cards[].highlights / box / scroll use),
and the ink width fraction (a good starting value for the highlight's width fraction).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse

import numpy as np
from PIL import Image, ImageDraw


def bands(img, thr=18, min_ink=0.004, min_gap=6, min_h=6):
    g = np.asarray(img.convert("L"), np.float32)
    bg = np.median(g[:, :max(4, g.shape[1] // 50)])            # background from the left margin
    ink = np.abs(g - bg) > thr
    frac = ink.mean(1)
    on = frac > min_ink
    out, y = [], 0
    while y < len(on):
        if on[y]:
            y0 = y
            gap = 0
            while y < len(on) and gap < min_gap:
                gap = 0 if on[y] else gap + 1
                y += 1
            y1 = y - gap
            if y1 - y0 >= min_h:
                cols = np.flatnonzero(ink[y0:y1].any(0))
                out.append((y0, y1, (cols[-1] + 1) / g.shape[1] if cols.size else 0.0, cols[0] if cols.size else 0))
        else:
            y += 1
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("image")
    ap.add_argument("--thr", type=float, default=18, help="grey difference from background that counts as ink")
    ap.add_argument("--min-gap", type=int, default=6, help="blank rows that end a band")
    ap.add_argument("--preview", help="write a copy with numbered bands drawn on it")
    a = ap.parse_args()
    img = Image.open(a.image).convert("RGB")
    bs = bands(img, a.thr, min_gap=a.min_gap)
    print(f"{a.image}: {img.width}x{img.height}, {len(bs)} bands")
    print(f"{'#':>3} {'y0':>6} {'y1':>6} {'h':>4} {'x0':>5} {'width_frac':>10}")
    for i, (y0, y1, wf, x0) in enumerate(bs):
        print(f"{i:>3} {y0:>6} {y1:>6} {y1 - y0:>4} {x0:>5} {wf:>10.2f}")
    if bs:
        print(f"content rows: {bs[0][0]}-{bs[-1][1]}  (use as cover.thumb.crop y-range or card scroll targets)")
    if a.preview:
        d = ImageDraw.Draw(img)
        for i, (y0, y1, wf, x0) in enumerate(bs):
            d.rectangle([x0, y0, int(wf * img.width), y1], outline=(255, 36, 66), width=2)
            d.text((4, y0), str(i), fill=(255, 36, 66))
        img.save(a.preview)
        print("preview ->", a.preview)


if __name__ == "__main__":
    main()
