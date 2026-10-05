#!/usr/bin/env python3
"""Step 3b: focal centre for each planned code-zoom window.

Code blocks in light doc apps render as light-grey rectangles on a white page. For each
config.zoom.windows [t0, t1] (source seconds) grab the midpoint frame, find the centroid of
pixels matching zoom.code_rgb (+- zoom.tol) inside config.share; fall back to the share
centre when fewer than zoom.min_px match... unless the text-density fallback finds text: pages without grey
code blocks (GitHub / Notion / plain white docs, dark editors) get the centre of the zoom.box-sized window
holding the most ink (pixels far from the page's median colour). zoom.detect: auto (code colour, then text
density; default) | code | text. Output zoom_windows.json [{t0,t1,cx,cy,px,method}].
The WINDOWS themselves are always hand-picked (config zoom.windows, source seconds, from the transcript /
geo frames: "here he walks through the code"); override any centre by hand with zoom.centers {"<t0>": [cx, cy]}.

Usage: python3 zoom_targets.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import numpy as np
from PIL import Image

import _lfc
from vstudio import media

cfg, _ = _lfc.load(description=__doc__)
SHARE = cfg.get("share") or sys.exit("config.share [x0,y0,x1,y1] is required for zoom targets")
R, Gc, B = cfg.get("zoom.code_rgb", [247, 246, 243])
TR, TG, TB = cfg.get("zoom.tol", [9, 9, 11])
MIN_PX = cfg.get("zoom.min_px", 4000)
manual = cfg.get("zoom.centers", {})
DETECT = cfg.get("zoom.detect", "auto")
ZW, ZH = cfg.get("zoom.box", [736, 336])


def text_center(rgb, box_w, box_h, ink=40):
    """(cx, cy, ink_px) of the box_w x box_h window with the most text ink in rgb (region coords), or None."""
    g = rgb.astype(np.float32).mean(axis=2)
    m = (np.abs(g - np.median(g)) > ink).astype(np.float64)
    h, w = m.shape
    bw, bh = min(box_w, w), min(box_h, h)
    ii = np.pad(m.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    sums = ii[bh:, bw:] - ii[:-bh, bw:] - ii[bh:, :-bw] + ii[:-bh, :-bw]
    if sums.max() <= 0:
        return None
    y, x = np.unravel_index(int(np.argmax(sums)), sums.shape)
    return x + bw // 2, y + bh // 2, int(sums[y, x])

out = []
for t0, t1 in cfg.get("zoom.windows", []):
    x0, y0, x1, y1 = SHARE
    if str(t0) in manual:
        cx, cy = manual[str(t0)]
        npx = -1
    else:
        media.grab_frame(cfg.src, (t0 + t1) / 2, "zoomchk.png")
        reg = np.asarray(Image.open("zoomchk.png").convert("RGB"), dtype=np.int16)[y0:y1, x0:x1]
        r, g, b = reg[..., 0], reg[..., 1], reg[..., 2]
        mask = ((abs(r - R) < TR) & (abs(g - Gc) < TG) & (abs(b - B) < TB)
                & (abs(r - g) < 6) & (abs(g - b) < 8))
        ys, xs = np.nonzero(mask)
        npx = int(len(xs))
        method = "center"
        tc = text_center(reg, ZW, ZH) if DETECT in ("auto", "text") else None
        if DETECT != "text" and npx > MIN_PX:
            cx, cy, method = x0 + int(xs.mean()), y0 + int(ys.mean()), "code"
        elif tc and tc[2] > MIN_PX // 8:
            cx, cy, npx, method = x0 + int(tc[0]), y0 + int(tc[1]), tc[2], "text"
        else:
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    if npx == -1:
        method = "manual"
    out.append({"t0": t0, "t1": t1, "cx": cx, "cy": cy, "px": npx, "method": method})
    print(f"  {t0}-{t1}  centre=({cx},{cy})  {method} px={npx}")
_lfc.dump_json(out, "zoom_windows.json")
print(f"zoom_windows.json n={len(out)}")
