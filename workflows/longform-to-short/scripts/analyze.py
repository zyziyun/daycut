#!/usr/bin/env python3
"""Step 1: pull everything the later steps analyse out of the long recording.

    audio16k.wav       mono 16 kHz for whisper
    rec_subs.srt       the platform's embedded caption track (speaker labels only; may be absent)
    silencedetect.txt  -> sounded.json (dead-air estimate; NOT used to drive cuts)
    geo/%04d.png       one frame every geometry.step seconds for screen-geometry detection

Usage: python3 analyze.py work/config.py [--skip audio,subs,silence,geo]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os
import re

import _lfc


def extra(ap):
    ap.add_argument("--skip", default="", help="comma list of steps to skip: audio,subs,silence,geo")


cfg, args = _lfc.load(description=__doc__, extra=extra)
skip = set(filter(None, args.skip.split(",")))
ff = _lfc.ffmpeg_bin()
src = cfg.src
dur = cfg.duration()

if "audio" not in skip:
    _lfc.run([ff, "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "audio16k.wav"])
    print("audio16k.wav")

if "subs" not in skip:
    r = _lfc.run([ff, "-y", "-v", "error", "-i", src, "-map", "0:s:0", "rec_subs.srt"], check=False,
                 capture_output=True)
    print("rec_subs.srt" if r.returncode == 0 else "no embedded caption track (speaker timeline will be empty)")

if "silence" not in skip:
    noise = cfg.get("silence.noise_db", -35)
    mind = cfg.get("silence.min_dur", 1.2)
    r = _lfc.run([ff, "-v", "info", "-i", "audio16k.wav" if os.path.exists("audio16k.wav") else src,
                  "-af", f"silencedetect=noise={noise}dB:d={mind}", "-f", "null", "-"],
                 capture_output=True, text=True)
    text = r.stderr
    open("silencedetect.txt", "w").write(text)
    pad, min_sound = cfg.get("silence.pad", 0.30), cfg.get("silence.min_sound", 0.40)
    starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", text)]
    ends = [float(m) for m in re.findall(r"silence_end: ([\d.]+)", text)]
    if len(ends) < len(starts):
        ends.append(dur)
    sounded, cursor = [], 0.0
    for s, e in zip(starts, ends):
        if s > cursor:
            sounded.append([cursor, s])
        cursor = e
    if cursor < dur:
        sounded.append([cursor, dur])
    merged = []
    for a, b in sounded:
        if b - a < min_sound:
            continue
        a, b = max(0.0, a - pad), min(dur, b + pad)
        if merged and a <= merged[-1][1] + 0.2:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    total = sum(b - a for a, b in merged)
    _lfc.dump_json({"duration": dur, "sounded": merged, "sounded_total": round(total, 1),
                    "silence_total": round(dur - total, 1)}, "sounded.json")
    print(f"sounded.json spans={len(merged)} sounded={total/60:.1f}min silence={(dur-total)/60:.1f}min")

if "geo" not in skip:
    step = cfg.get("geometry.step", 10)
    os.makedirs("geo", exist_ok=True)
    _lfc.run([ff, "-y", "-v", "error", "-i", src, "-vf", f"fps=1/{step}", "geo/%04d.png"])
    print(f"geo/ frames every {step}s")
print(f"duration={dur:.2f}s  next: transcribe.py, geometry.py, speaker_timeline.py")
