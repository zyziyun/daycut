#!/usr/bin/env python3
"""Loop a music track to the film's full length with crossfades, fade in/out, and level it low.

Usage:  python3 make_bgm_bed.py SOURCE.wav [--xfade 6] [--lufs -30]
Reads   audio/scenes.json (total length)
Writes  audio/bgm.wav
Pick a steady track (low loudness range, no drums): `ffmpeg -i x.wav -af ebur128 -f null -` → LRA ≲ 6 LU.
Then carve it under the voice with hyperframes-audio carve.mjs (a volume duck alone is not enough).
"""
import argparse, json, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("source")
ap.add_argument("--xfade", type=float, default=6.0)
ap.add_argument("--lufs", type=float, default=-30.0)
a = ap.parse_args()

total = json.load(open("audio/scenes.json"))["total"]
L = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.source],
                         capture_output=True, text=True).stdout)
n = max(1, int(total // (L - a.xfade)) + 2)
inputs = sum((["-i", a.source] for _ in range(n)), [])
f, prev = [], "[0:a]"
for k in range(1, n):
    f.append(f"{prev}[{k}:a]acrossfade=d={a.xfade}:c1=tri:c2=tri[a{k}]"); prev = f"[a{k}]"
f.append(f"{prev}atrim=0:{total},afade=t=in:d=3,afade=t=out:st={total - 5}:d=5,"
         f"loudnorm=I={a.lufs}:LRA=7:TP=-6[o]")
subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(f), "-map", "[o]",
                "-ar", "48000", "-ac", "2", "audio/bgm.wav"], check=True)
print(f"audio/bgm.wav · {n} loops of {L:.0f}s → {total}s at {a.lufs} LUFS")
