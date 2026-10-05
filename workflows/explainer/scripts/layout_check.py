#!/usr/bin/env python3
"""Vertical-short layout QA: does each scene's graphic FILL the math area, or sit small in its top half?

For every snapshot (PNG of the canvas, e.g. `npx hyperframes snapshot --at <85 % of each scene>`) the drawn content
inside the math area (canvas.py: between the scene-title strip and the caption band; the title eyebrow and the
captions are ignored) is found as pixels that stand out from the background (per-row median, so the dark vignette
does not count). Reported per frame:

  height   share of the math-area height spanned by content (first to last content row)
  bottom   empty share at the bottom of the math area (between the last content and the caption band)
  width    share of the math-area width spanned by content

WARN when height < --min-height (0.6) or bottom > --max-bottom (0.3): the visual is too small / top-heavy for a
phone. Mid-transition or hook frames (big number alone) can legitimately warn; judge those by eye.
Exit 1 when any frame warns and --strict is given.

Usage:  python3 layout_check.py [--project .] [--platform ...] [snapshots/*.png ...] [--strict] [--json]
        (no files: every <project>/snapshots/*.png)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canvas import add_platform_arg, resolve  # noqa: E402

MIN_HEIGHT = 0.6
MAX_BOTTOM = 0.3


def content_box(rgb, math, thresh=36, min_px=3, trim=0.002):
    """(x0, y0, x1, y1) of the content inside ``math`` (canvas px) of an HxWx3 uint8 frame, or None.
    Background = per-row median of the side margins outside the math area (always empty canvas there; follows a
    vertical gradient / vignette), so a graphic wider than half the row is still content. Extents ignore the
    outer ``trim`` share of content pixels on each side (stray anti-aliasing / grain)."""
    mx0, my0, mx1, my1 = (int(v) for v in math)
    W = rgb.shape[1]
    rows_px = rgb[my0:my1].astype(np.int16)
    side = np.concatenate([rows_px[:, :max(1, mx0)], rows_px[:, min(W - 1, mx1):]], axis=1)
    bg = np.median(side, axis=1, keepdims=True)
    ink = np.abs(rows_px[:, mx0:mx1] - bg).max(axis=2) > thresh
    ink &= (ink.sum(axis=1) >= min_px)[:, None]                # rows with a few lone pixels are noise
    ys, xs = np.nonzero(ink)
    if len(ys) < 20:
        return None
    qy = np.quantile(ys, [trim, 1 - trim])
    qx = np.quantile(xs, [trim, 1 - trim])
    return (mx0 + int(qx[0]), my0 + int(qy[0]), mx0 + int(qx[1]) + 1, my0 + int(qy[1]) + 1)


def measure(rgb, cv, min_height=MIN_HEIGHT, max_bottom=MAX_BOTTOM):
    """Fill metrics of one frame on canvas ``cv`` (canvas.resolve)."""
    H, W = rgb.shape[:2]
    if (W, H) != (cv["W"], cv["H"]):
        from PIL import Image
        rgb = np.asarray(Image.fromarray(rgb).resize((cv["W"], cv["H"]), Image.LANCZOS))
    mx0, my0, mx1, my1 = cv["math"]
    mh, mw = my1 - my0, mx1 - mx0
    box = content_box(rgb, cv["math"])
    if box is None:
        return dict(box=None, height=0.0, bottom=1.0, width=0.0, warn=["empty math area"])
    x0, y0, x1, y1 = box
    r = dict(box=list(box), height=round((y1 - y0) / mh, 3), bottom=round((my1 - y1) / mh, 3),
             width=round((x1 - x0) / mw, 3))
    warn = []
    if r["height"] < min_height:
        warn.append(f"content spans {r['height']:.0%} of the math-area height (< {min_height:.0%}): scale it up")
    if r["bottom"] > max_bottom:
        warn.append(f"bottom {r['bottom']:.0%} of the math area is empty (> {max_bottom:.0%}): the graphic sits in "
                    f"the top; move the result / conclusion down to just above the caption band (y ≈ {my1})")
    r["warn"] = warn
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="snapshot PNGs (default: <project>/snapshots/*.png)")
    ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
    add_platform_arg(ap)
    ap.add_argument("--min-height", type=float, default=MIN_HEIGHT)
    ap.add_argument("--max-bottom", type=float, default=MAX_BOTTOM)
    ap.add_argument("--strict", action="store_true", help="exit 1 when any frame warns")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = pathlib.Path(a.project)
    cv = resolve(root, a.platform)
    if cv["legacy"]:
        sys.exit("layout_check.py is for vertical shorts (set \"platform\" in scenes.config.json or pass --platform)")
    files = a.files or sorted(str(p) for p in (root / "snapshots").glob("*.png"))
    if not files:
        sys.exit("no snapshots: npx hyperframes snapshot --at <85 % of each scene>, or pass PNG paths")
    from PIL import Image
    out, bad = {}, 0
    for f in files:
        r = measure(np.asarray(Image.open(f).convert("RGB")), cv, a.min_height, a.max_bottom)
        out[f] = r
        bad += bool(r["warn"])
        if not a.json:
            print(f"{os.path.basename(f)}: height {r['height']:.0%}  bottom gap {r['bottom']:.0%}  width {r['width']:.0%}"
                  + "".join(f"\n    WARN {w}" for w in r["warn"]))
    if a.json:
        print(json.dumps(out, indent=1))
    print(f"{bad}/{len(files)} frame(s) warn (math area {tuple(cv['math'])}, {cv['key']})", file=sys.stderr)
    if bad and a.strict:
        sys.exit(1)


if __name__ == "__main__":
    main()
