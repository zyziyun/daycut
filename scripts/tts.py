#!/usr/bin/env python3
"""Synthesize every narration line in SCRIPT.md with OpenAI TTS.

Usage:  python3 tts.py [--voice cedar] [--model gpt-4o-mini-tts] [--speed 1.0] [LINE ...]
Reads   SCRIPT.md  (sections "## Line N — ...", indented 4-space block = spoken text,
                    optional "**Delivery:** ..." line = per-line direction)
Writes  audio/vo/lineNN.wav
Needs   OPENAI_API_KEY in the environment.
"""
import argparse, json, os, re, subprocess, urllib.request

BASE = ("Calm, curious, unhurried teacher thinking out loud at a whiteboard, like a 3Blue1Brown narrator. "
        "Warm and clear. Read numbers carefully and distinctly. Brief pause before each key insight.")

ap = argparse.ArgumentParser()
ap.add_argument("lines", nargs="*", help="only these line numbers")
ap.add_argument("--voice", default="cedar")
ap.add_argument("--model", default="gpt-4o-mini-tts")
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--direction", default=BASE, help="global voice direction")
a = ap.parse_args()

key = os.environ.get("OPENAI_API_KEY")
if not key:
    raise SystemExit("OPENAI_API_KEY is not set")
os.makedirs("audio/vo", exist_ok=True)
blocks = re.split(r"\n## Line ", open("SCRIPT.md").read())[1:]
for b in blocks:
    n = int(b.split(" ", 1)[0])
    if a.lines and str(n) not in a.lines:
        continue
    text = " ".join(l.strip() for l in b.split("\n") if l.startswith("    "))
    m = re.search(r"\*\*Delivery:\*\* (.+)", b)
    instr = a.direction + (" For this part: " + m.group(1) if m else "")
    out = f"audio/vo/line{n:02d}.wav"
    req = urllib.request.Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps({"model": a.model, "voice": a.voice, "speed": a.speed, "response_format": "wav",
                         "input": text, "instructions": instr}).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r, open(out, "wb") as f:
        f.write(r.read())
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out],
                       capture_output=True, text=True).stdout.strip()
    print(f"line {n:02d}: {float(d):6.1f}s  {len(text.split())} words", flush=True)
