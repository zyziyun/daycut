#!/usr/bin/env python3
"""Step 7b: overlay note panels + burn subs.ass in ONE encode -> <out>/final_subbed.mp4.

Panel windows (source s) are mapped through timeline.json; a window edge that fell into a
removed gap snaps forward (start) / back (end). Each PNG input needs `-loop 1` + overlay
`shortest=1`, else the single-frame stream EOFs before its enable window and never shows.
Needs an ffmpeg with libass: vstudio.media.ffmpeg_bin(need=["ass"]) picks the system ffmpeg if it has
the `ass` filter, else static_ffmpeg.
Fonts for libass come from vstudio's font dir (fontsdir=).

--clean-master: panels only, no captions -> <out>/master_clean.mp4, the caption-free master for
`python -m vstudio.export` (captions are re-burned per platform from work/cues.json).
With explicit platform targets, the panel is kept inside the first horizontal target's safe box.

Usage: python3 burn_final.py work/config.py [--no-subs | --clean-master]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import _lfc
from vstudio import media
from vstudio.config import FONT_DIR


def extra(ap):
    ap.add_argument("--no-subs", action="store_true", help="panels only")
    ap.add_argument("--clean-master", action="store_true",
                    help="panels only -> <out>/master_clean.mp4 (caption-free master for vstudio.export)")


cfg, args = _lfc.load(description=__doc__, extra=extra)
args.no_subs = args.no_subs or args.clean_master
ff = media.ffmpeg_bin(need=[] if args.no_subs else ["ass"])
tm = _lfc.timemap(_lfc.load_json("timeline.json"))
panels = _lfc.load_json("panels.json") if os.path.exists("panels.json") else []
PROF = _lfc.primary_horizontal(cfg)       # None unless targets were set explicitly
W, H = cfg.get("render.size", list(PROF.size) if PROF else [1920, 1080])
PX, PY = cfg.get("panel_pos", [W - 498, 240])
SAFE = None
if PROF:
    from vstudio import platform as PF
    k = W / PROF.w
    SAFE = [int(v * k) for v in PF.safe_box(PROF)]
src = os.path.join(cfg.out, "final.mp4")
dst = os.path.join(cfg.out, "master_clean.mp4" if args.clean_master else "final_subbed.mp4")

inputs, chains, prev = ["-i", src], [], "0:v"
for i, p in enumerate(panels):
    span = tm.map_span(p["t0"], p["t1"], tag="body")
    if not span:
        print(f"WARN panel {i} window unmapped, skipped")
        continue
    a, b = span
    inputs += ["-loop", "1", "-i", p["png"]]
    idx = inputs.count("-i") - 1
    py = PY if p["h"] + PY < H - 40 else H - 40 - p["h"]
    px = PX
    if SAFE:  # keep the panel inside the target's safe box
        pw = p.get("w", cfg.get("panel_width", 460))
        px = max(SAFE[0], min(px, SAFE[2] - pw))
        py = max(SAFE[1], min(py, SAFE[3] - p["h"]))
    chains.append(f"[{prev}][{idx}:v]overlay={px}:{py}:shortest=1:"
                  f"enable='between(t,{a:.2f},{b:.2f})'[v{i}]")
    prev = f"v{i}"
    print(f"panel {i}: {_lfc.mmss(a)}-{_lfc.mmss(b)}")

if args.no_subs:
    chains.append(f"[{prev}]null[vout]")
else:
    fontsdir = FONT_DIR.replace(":", r"\:")
    chains.append(f"[{prev}]ass=subs.ass:fontsdir='{fontsdir}'[vout]")
media.run([ff, "-y", *inputs, *media.filter_complex_args(";".join(chains)),
           "-map", "[vout]", "-map", "0:a", *_lfc.video_encoder(cfg),
           "-c:a", "copy", "-movflags", "+faststart", dst])
print("done:", dst)
