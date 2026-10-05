#!/usr/bin/env python3
"""Report the 气口 / stumbles the automatic disfluency pass would cut from keep-windows.

Two profiles (scripts/cut_profiles.py; ``--profile``, clips.json ``cut_profile``, persona
``call_clips.cut_profile``):
  classic  (default) pauses > 0.75 s keep 0.30 s; with editor cuts pauses > 0.50 s keep 0.25 s;
           edges snap BACKWARD to the quietest frame (<= 0.15 s before each edge)
  word     vstudio.cut.find_cuts: pauses > 0.60 s keep 0.36 s; edges at the quietest frame between
           the neighbouring words' midpoints

Silence comes from 20 ms RMS frames relative to the recording's own floor/speech level
(``vstudio.cut.Audio``); the transcript only says WHAT to cut:

  pause    silence > threshold with no word midpoint inside -> cut, keep the profile's breath
  restart  segment A then B starting with A's text within 1.5 s -> drop A
  repeat   the same 1..6-word unit (2..10 chars) said twice back to back -> keep the last copy
           (one-word repeats across a segment break are kept; EMPHASIS doublings whitelisted)
  filler   a whole segment that is only a FILLERS word (嗯 / 啊 / 然后呢 ...)
  edit     optional editor cuts (--extra): [[from_onset, next_kept_onset, why], ...]

The Mandarin FILLERS/EMPHASIS lists are in ``vstudio.cut`` (persona pause_* keys are NOT read).
build_clips.py runs the same pass when clips.json has "auto_trim": true.

Usage (standalone report, read before building):
  find_disfluencies.py work/audio16k.wav work/audio16k.json --windows 124.58-410.3,527-560.9
  find_disfluencies.py ... --extra editor_cuts.json --json work/cuts.json
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cut_profiles import PROFILES, default_profile, find_cuts
from vstudio.cut import Audio


def main():
    ap = argparse.ArgumentParser(description="Report the stumbles/pauses find_cuts() would remove.")
    ap.add_argument("wav", help="16 kHz mono wav of the recording")
    ap.add_argument("whisper", help="whisper JSON with word timestamps")
    ap.add_argument("--windows", required=True, help="a-b,a-b in source seconds")
    ap.add_argument("--extra", default=None, help="editor cuts JSON: [[from, to, why], ...]")
    ap.add_argument("--json", default=None, help="also write {window: cuts} here")
    ap.add_argument("--profile", default=None, choices=list(PROFILES),
                    help="cut profile (default persona call_clips.cut_profile, else classic)")
    args = ap.parse_args()
    audio = Audio(args.wav)
    segs = json.load(open(args.whisper, encoding="utf-8"))["segments"]
    extra = json.load(open(args.extra, encoding="utf-8")) if args.extra else None
    total = saved = 0
    report = {}
    for w in args.windows.split(","):
        lo, hi = (float(v) for v in w.split("-"))
        cuts = find_cuts(audio, segs, lo, hi, extra, args.profile)
        report[w] = cuts
        total += hi - lo
        for a, b, why in cuts:
            saved += b - a
            print(f"{a:8.2f}-{b:8.2f} {b - a:5.2f}s  {why}")
    print(f"window {total:.0f}s, cut {saved:.1f}s ({saved / total:.0%}), thr {audio.thr:.1f}dB, "
          f"profile {args.profile or default_profile()}")
    if args.json:
        json.dump(report, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
