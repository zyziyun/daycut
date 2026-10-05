#!/usr/bin/env python3
"""Synthesize every narration line in SCRIPT.md with OpenAI TTS (via vstudio.tts, cached).

Usage:  python3 tts.py [--project .] [--voice cedar] [--model gpt-4o-mini-tts] [--speed 1.0] [LINE ...]
Reads   <project>/SCRIPT.md  (sections "## Line N — ...", indented 4-space block = spoken text,
                              optional "**Delivery:** ..." line = per-line direction)
Writes  <project>/audio/vo/lineNN.wav  (48 kHz mono)
Needs   OPENAI_API_KEY in the environment. Takes are cached by text+voice+direction
        ($VSTUDIO_CACHE/tts), so re-running only pays for changed lines; --fresh forces new takes.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, re

from vstudio import media, tts

BASE = ("Calm, curious, unhurried teacher thinking out loud at a whiteboard, like a 3Blue1Brown narrator. "
        "Warm and clear. Read numbers carefully and distinctly. Brief pause before each key insight.")

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("lines", nargs="*", help="only these line numbers")
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--voice", default="cedar")
ap.add_argument("--model", default="gpt-4o-mini-tts")
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--direction", default=BASE, help="global voice direction")
ap.add_argument("--fresh", action="store_true", help="ignore the TTS cache (new take)")
a = ap.parse_args()

root = pathlib.Path(a.project)
(root / "audio/vo").mkdir(parents=True, exist_ok=True)
blocks = re.split(r"\n## Line ", (root / "SCRIPT.md").read_text())[1:]
for b in blocks:
    n = int(b.split(" ", 1)[0])
    if a.lines and str(n) not in a.lines:
        continue
    text = " ".join(l.strip() for l in b.split("\n") if l.startswith("    "))
    m = re.search(r"\*\*Delivery:\*\* (.+)", b)
    instr = a.direction + (" For this part: " + m.group(1) if m else "")
    out = str(root / f"audio/vo/line{n:02d}.wav")
    tts.synth(text, engine="openai", voice=a.voice, speed=a.speed, instructions=instr, model=a.model,
              out=out, cache=not a.fresh)
    print(f"line {n:02d}: {media.duration(out):6.1f}s  {len(text.split())} words", flush=True)
