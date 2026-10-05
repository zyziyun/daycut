#!/usr/bin/env python3
"""Loop a music track to the film's full length with crossfades, fade in/out, and level it low.

Usage:  python3 make_bgm_bed.py SOURCE.wav [--project .] [--xfade 6] [--lufs -30]
Reads   <project>/audio/scenes.json (total length); SOURCE is relative to the current dir
Writes  <project>/audio/bgm.wav (48 kHz stereo, two-pass linear loudnorm via vstudio.audio)
Pick a steady track (low loudness range, no drums): `ffmpeg -i x.wav -af ebur128 -f null -` → LRA ≲ 6 LU.
Then carve it under the voice with hyperframes-audio carve.mjs (a volume duck alone is not enough).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, tempfile

from vstudio import audio, media

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("source")
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--xfade", type=float, default=6.0, help="crossfade between loops (s)")
ap.add_argument("--lufs", type=float, default=-30.0, help="bed loudness")
a = ap.parse_args()

root = pathlib.Path(a.project)
total = json.load(open(root / "audio/scenes.json"))["total"]
L = media.duration(a.source)
if L <= a.xfade:
    raise SystemExit(f"source ({L:.1f}s) must be longer than --xfade ({a.xfade}s)")
n = max(1, int(total // (L - a.xfade)) + 2)
# vstudio.audio has no crossfaded loop (mix_bed hard-tiles), so the acrossfade chain stays local
inputs = sum((["-i", a.source] for _ in range(n)), [])
f, prev = [], "[0:a]"
for k in range(1, n):
    f.append(f"{prev}[{k}:a]acrossfade=d={a.xfade}:c1=tri:c2=tri[a{k}]"); prev = f"[a{k}]"
f.append(f"{prev}atrim=0:{total},afade=t=in:d=3,afade=t=out:st={total - 5}:d=5[o]")
with tempfile.TemporaryDirectory() as tmp:
    raw = f"{tmp}/bed_raw.wav"
    media.run(["ffmpeg", "-y", *inputs, *media.filter_complex_args(";".join(f), tmp), "-map", "[o]",
               "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", raw])
    audio.loudnorm_2pass(raw, str(root / "audio/bgm.wav"), lufs=a.lufs, tp=-6, lra=7)
print(f"audio/bgm.wav · {n} loops of {L:.0f}s → {total}s at {a.lufs} LUFS")
