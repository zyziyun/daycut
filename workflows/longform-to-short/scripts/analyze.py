#!/usr/bin/env python3
"""Step 1: pull everything the later steps analyse out of the long recording.

    audio16k.wav       mono 16 kHz for whisper
    rec_subs.srt       the platform's embedded caption track (speaker labels only; may be absent)
    sounded.json       silencedetect -> sounded spans (dead-air estimate; NOT used to drive cuts)
    geo/%04d.png       one frame every geometry.step seconds for screen-geometry detection

Usage: python3 analyze.py work/config.py [--skip audio,subs,silence,geo]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import _lfc
from vstudio import audio, media


def extra(ap):
    ap.add_argument("--skip", default="", help="comma list of steps to skip: audio,subs,silence,geo")


cfg, args = _lfc.load(description=__doc__, extra=extra)
skip = set(filter(None, args.skip.split(",")))
src = cfg.src
dur = cfg.duration()

if "audio" not in skip:
    media.extract_wav(src, "audio16k.wav", sr=16000, channels=1)
    print("audio16k.wav")

if "subs" not in skip:
    r = media.run(["ffmpeg", "-y", "-i", src, "-map", "0:s:0", "rec_subs.srt"], check=False)
    print("rec_subs.srt" if r.returncode == 0 else "no embedded caption track (speaker timeline will be empty)")

if "silence" not in skip:
    sil = audio.silence_spans("audio16k.wav" if os.path.exists("audio16k.wav") else src,
                              noise_db=cfg.get("silence.noise_db", -35), min_dur=cfg.get("silence.min_dur", 1.2))
    merged = audio.sounded_spans(sil, dur, pad=cfg.get("silence.pad", 0.30),
                                 min_sound=cfg.get("silence.min_sound", 0.40))
    total = sum(b - a for a, b in merged)
    _lfc.dump_json({"duration": dur, "sounded": merged, "sounded_total": round(total, 1),
                    "silence_total": round(dur - total, 1)}, "sounded.json")
    print(f"sounded.json spans={len(merged)} sounded={total/60:.1f}min silence={(dur-total)/60:.1f}min")

if "geo" not in skip:
    step = cfg.get("geometry.step", 10)
    os.makedirs("geo", exist_ok=True)
    media.run(["ffmpeg", "-y", "-i", src, "-vf", f"fps=1/{step}", "geo/%04d.png"])
    print(f"geo/ frames every {step}s")
print(f"duration={dur:.2f}s  next: transcribe.py, geometry.py, speaker_timeline.py")
