#!/usr/bin/env python3
"""Step 3b: focal centre for each planned code-zoom window.

Code blocks in light doc apps render as light-grey rectangles on a white page. For each
config.zoom.windows [t0, t1] (source seconds) grab the midpoint frame, find the centroid of
pixels matching zoom.code_rgb (+- zoom.tol) inside config.share; fall back to the share
centre when fewer than zoom.min_px match. Output zoom_windows.json [{t0,t1,cx,cy,px}].
Override any centre by hand with zoom.centers {"<t0>": [cx, cy]}.

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
        if npx > MIN_PX:
            cx, cy = x0 + int(xs.mean()), y0 + int(ys.mean())
        else:
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    out.append({"t0": t0, "t1": t1, "cx": cx, "cy": cy, "px": npx})
    print(f"  {t0}-{t1}  centre=({cx},{cy})  code_px={npx}")
_lfc.dump_json(out, "zoom_windows.json")
print(f"zoom_windows.json n={len(out)}")
