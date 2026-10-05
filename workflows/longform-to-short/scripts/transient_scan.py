#!/usr/bin/env python3
"""Step 3a: find accidental screen flashes (new tab, desktop, another window) in kept ranges.

Decodes the WHOLE source at 1 fps into tiny gray frames (decoding forward, so sparse
keyframes don't matter) and flags seconds where the share region's white ratio drops
below transients.white_thresh. Eyeball each run, then copy the real ones into
config.freezes (the frame before the flash is held while audio keeps rolling).

Segments whose index is in demo.keep_idx are skipped (their video is replaced anyway).
Assumes a light-themed share; set transients.white_thresh / transients.luma for others.

Usage: python3 transient_scan.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import subprocess

import numpy as np

import _lfc

cfg, _ = _lfc.load(description=__doc__)
W, H = 160, 90
SRC_W, SRC_H = cfg.get("source_size", [1280, 720])
x0, y0, x1, y1 = cfg.get("share") or [0, 0, int(SRC_W * 0.75), SRC_H]
SX0, SY0, SX1, SY1 = int(x0 / SRC_W * W), int(y0 / SRC_H * H), int(x1 / SRC_W * W), int(y1 / SRC_H * H)
THRESH = cfg.get("transients.white_thresh", 0.55)
LUMA = cfg.get("transients.luma", 200)
skip = set(cfg.get("demo.keep_idx", []) if cfg.get("demo.enabled") else [])

proc = subprocess.run([_lfc.ffmpeg_bin(), "-v", "error", "-i", cfg.src, "-vf", f"fps=1,scale={W}:{H}",
                       "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True)
buf = np.frombuffer(proc.stdout, dtype=np.uint8)
n = len(buf) // (W * H)
frames = buf[: n * W * H].reshape(n, H, W)

kept = [(s["t0"], s["t1"]) for i, s in enumerate(_lfc.load_json("keep_list.json")) if i not in skip]
flagged = []
for t in range(n):
    if any(a <= t <= b for a, b in kept):
        white = float((frames[t, SY0:SY1, SX0:SX1] > LUMA).mean())
        if white < THRESH:
            flagged.append((t, round(white, 2)))

runs = []
for t, _w in flagged:
    if runs and t - runs[-1][1] <= 2:
        runs[-1][1] = t
    else:
        runs.append([t, t])
_lfc.dump_json(runs, "transients.json", indent=0)
print(f"frames={n} flagged_seconds={len(flagged)}")
for a, b in runs:
    print(f"  transient {a}-{b + 1}s")
print("eyeball each run (e.g. ffmpeg -ss <t> -i SRC -frames:v 1 chk.png); real flashes -> config.freezes")
