#!/usr/bin/env python3
"""Step 9: verify before handing off.

  decode   ffmpeg -v error full decode of <out>/final_subbed.mp4 (no moov / EOF errors)
  loud     integrated loudness (should be ~ persona audio.loudness_lufs)
  mosaic   contact sheets (one frame every --every s, 6x5 per sheet) -> qa/mosaic_NN.jpg
           LOOK at every sheet: zero participant avatars, name tags, bookmark bars, emails
  pitch    median f0 of each pitches window in source vs final (anonymised voice should drop
           by ~|semitones|; the host's voice elsewhere unchanged)

Usage: python3 qa.py work/config.py [--video PATH] [--every 15] [--skip decode,loud,mosaic,pitch]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import math
import os
import re
import subprocess

import numpy as np

import _lfc


def extra(ap):
    ap.add_argument("--video")
    ap.add_argument("--every", type=float, default=15)
    ap.add_argument("--skip", default="")


cfg, args = _lfc.load(description=__doc__, extra=extra)
skip = set(filter(None, args.skip.split(",")))
ff = _lfc.ffmpeg_bin()
video = args.video or os.path.join(cfg.out, "final_subbed.mp4")
if not os.path.exists(video):
    video = os.path.join(cfg.out, "final.mp4")
print("checking", video)

if "decode" not in skip:
    r = subprocess.run([ff, "-v", "error", "-i", video, "-f", "null", "-"], capture_output=True, text=True)
    print("decode:", "clean" if not r.stderr.strip() else "ERRORS\n" + r.stderr[:2000])

if "loud" not in skip:
    r = subprocess.run([ff, "-hide_banner", "-i", video, "-af", "loudnorm=print_format=summary",
                        "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"Input Integrated:\s*(-?[\d.]+)", r.stderr)
    print("loudness integrated:", m.group(1) if m else "?", "LUFS")

if "mosaic" not in skip:
    os.makedirs("qa", exist_ok=True)
    _lfc.run([ff, "-y", "-v", "error", "-i", video, "-vf",
              f"fps=1/{args.every},scale=320:-2,tile=6x5", "qa/mosaic_%02d.jpg"])
    print("mosaics:", sorted(os.listdir("qa")), "-> inspect every sheet")


def f0_median(path, t0, dur):
    r = subprocess.run([ff, "-v", "error", "-ss", f"{t0:.2f}", "-t", f"{dur:.2f}", "-i", path, "-vn",
                        "-ac", "1", "-ar", "16000", "-f", "s16le", "-"], capture_output=True)
    x = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32)
    f0s, n = [], 640  # 40 ms frames
    for i in range(0, len(x) - n, n):
        fr = x[i:i + n] - x[i:i + n].mean()
        if np.sqrt((fr ** 2).mean()) < 300:
            continue
        ac = np.correlate(fr, fr, "full")[n - 1:] / (n - np.arange(n))  # unbiased
        lo, hi = 16000 // 400, 16000 // 70
        seg = ac[lo:hi]
        peaks = [i for i in range(1, len(seg) - 1)
                 if seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1] and seg[i] > 0.8 * seg.max()]
        k = lo + (peaks[0] if peaks else int(np.argmax(seg)))  # first strong peak, not a subharmonic
        if ac[k] > 0.3 * ac[0] and 0 < k < n - 1:
            a, b, c = ac[k - 1], ac[k], ac[k + 1]
            den = a - 2 * b + c
            f0s.append(16000 / (k + (0.5 * (a - c) / den if den else 0.0)))  # parabolic refine
    return float(np.median(f0s)) if f0s else float("nan")


if "pitch" not in skip and cfg.get("pitches.windows"):
    timeline = _lfc.load_json("timeline.json")
    final = os.path.join(cfg.out, "final.mp4")
    for a, b in [w[:2] for w in cfg.get("pitches.windows")]:
        fa = _lfc.map_src(timeline, a, "fwd")
        sp = _lfc.speed(cfg, "lecture", 1.2)
        if fa is None:
            print(f"pitch {a}-{b}: not in cut")
            continue
        s0, s1 = f0_median(cfg.src, a, b - a), f0_median(final, fa, (b - a) / sp)
        st = 12 * math.log2(s1 / s0) if s0 and s1 and s0 == s0 and s1 == s1 else float("nan")
        print(f"pitch {a}-{b}: src f0 {s0:.0f} Hz -> final {s1:.0f} Hz ({st:+.1f} st)")
