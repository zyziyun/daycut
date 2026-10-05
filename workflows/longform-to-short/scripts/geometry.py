#!/usr/bin/env python3
"""Step 1b: screen-share geometry per sampled frame, then stable crop spans.

Per frame in geo/ (written by analyze.py):
  share_active  a large bright (page-like) region exists in the left share area
  bbox          tight box of the bright share content [x0,y0,x1,y1]
  header        'doc' (thin white app header, e.g. a docs app) | 'browser' (grey tab strip
                + bookmark bar) | 'none'
  content_top   first content row below that header -> browser chrome is cropped away

Then collapses samples into crop spans (crop_spans.json: [{t0,t1,header,crop:[w,h,x,y]}]).
Spans without a share (gallery/avatar view) get crop=None and should be dropped by the
keep list; a bottom trim shaves the "<host>'s screen" label meeting apps paint at the edge.

Tuned for light-themed shared pages on a dark meeting canvas. Thresholds live in
config.geometry.* ; dark-mode shares need a lower `bright` / inverted test.

Usage: python3 geometry.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import numpy as np
from PIL import Image

import _lfc

cfg, _ = _lfc.load(description=__doc__)
G = lambda k, d: cfg.get(f"geometry.{k}", d)  # noqa: E731
STEP = G("step", 10)
BRIGHT = G("bright", 160)
SHARE_X = G("share_frac_x", 0.80)       # share lives in the left 80% (participant strip on the right)
FRAC = G("min_frac", 0.12)
REF_W = G("ref_width", 1500)            # header heights measured on a ~1500px wide share
DOC_H = G("doc_header_px", 45)
CHROME_H = G("browser_header_px", 115)  # tab strip + address bar + bookmark bar
BOTTOM_TRIM = G("bottom_trim", 14)
MIN_SPAN = G("min_span", 30)

results = {}
for f in sorted(x for x in os.listdir("geo") if x.endswith(".png")):
    t = (int(f.split(".")[0]) - 1) * STEP
    im = np.asarray(Image.open(os.path.join("geo", f)).convert("L"), dtype=np.uint8)
    H, W = im.shape
    left = (im > BRIGHT)[:, : int(W * SHARE_X)]
    cols = np.where(left.mean(axis=0) > FRAC)[0]
    rows = np.where(left.mean(axis=1) > FRAC)[0]
    if len(cols) < W * 0.156 or len(rows) < H * 0.208:
        results[t] = {"share_active": False}
        continue
    x0, x1, y0, y1 = int(cols[0]), int(cols[-1]), int(rows[0]), int(rows[-1])
    band_mean = float(im[y0:y0 + 8, x0:x1].mean())
    share_w = x1 - x0
    if band_mean > 235:
        header, top = "doc", y0 + max(18, int(share_w * DOC_H / REF_W))
    elif band_mean > 180:
        header, top = "browser", y0 + max(40, int(share_w * CHROME_H / REF_W))
    else:
        header, top = "none", y0
    results[t] = {"share_active": True, "bbox": [x0, y0, x1, y1], "header": header,
                  "band_mean": round(band_mean, 1), "content_top": int(top)}

_lfc.dump_json(results, "geometry.json", indent=0)
hdrs = {}
for v in results.values():
    if v["share_active"]:
        hdrs[v["header"]] = hdrs.get(v["header"], 0) + 1
print(f"geometry.json samples={len(results)} headers={hdrs}")

# ---- spans
def sig(v):
    if not v["share_active"]:
        return None
    q = lambda a: round(a / 24)  # noqa: E731  quantize so flicker doesn't split spans
    x0, y0, x1, y1 = v["bbox"]
    return (q(x0), q(y0), q(x1), q(y1), v["header"])


spans, cur = [], None
for t, v in sorted((int(k), v) for k, v in results.items()):
    s = sig(v)
    if cur is None or s != cur["sig"]:
        if cur:
            spans.append(cur)
        cur = {"sig": s, "t0": t, "t1": t + STEP, "samples": [v]}
    else:
        cur["t1"] = t + STEP
        cur["samples"].append(v)
if cur:
    spans.append(cur)

out = []
for sp in spans:
    if sp["sig"] is None:
        out.append({"t0": sp["t0"], "t1": sp["t1"], "crop": None})
        continue
    m = len(sp["samples"]) // 2
    med = lambda key: sorted(key(v) for v in sp["samples"])[m]  # noqa: E731
    x0, x1 = med(lambda v: v["bbox"][0]), med(lambda v: v["bbox"][2])
    y1, top = med(lambda v: v["bbox"][3]) - BOTTOM_TRIM, med(lambda v: v["content_top"])
    w, h = x1 - x0, y1 - top
    out.append({"t0": sp["t0"], "t1": sp["t1"], "header": sp["sig"][4],
                "crop": [w - w % 2, h - h % 2, x0, top]})

merged = []
for sp in out:
    tiny = merged and merged[-1]["crop"] and sp["crop"] and sp["t1"] - sp["t0"] < MIN_SPAN
    if tiny or (merged and merged[-1]["crop"] == sp["crop"]):
        merged[-1]["t1"] = sp["t1"]
        continue
    merged.append(sp)
_lfc.dump_json(merged, "crop_spans.json")
for sp in merged:
    print(f"  {sp['t0']:>6} -> {sp['t1']:<6} {sp.get('header', '-'):8} {sp['crop']}")
