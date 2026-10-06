#!/usr/bin/env python3
"""Synthesize every narration line in SCRIPT.md with OpenAI TTS (via vstudio.tts, cached).

Usage:  python3 tts.py [--project .] [--voice cedar] [--model gpt-4o-mini-tts] [--speed 1.0] [LINE ...]
Reads   <project>/SCRIPT.md  (sections "## Line N — ...", indented 4-space block = spoken text,
                              optional "**Delivery:** ..." line = per-line direction)
Writes  <project>/audio/vo/lineNN.wav  (48 kHz mono)
Needs   OPENAI_API_KEY in the environment (default engine), or --engine openai-compatible (your own TTS server,
        VSTUDIO_TTS_BASE_URL) / elevenlabs / kokoro / edge (see references/PROVIDERS.md). Takes are cached by text+voice+direction
        ($VSTUDIO_CACHE/tts), so re-running only pays for changed lines; --fresh forces new takes.
Check   every take is transcribed (vstudio.asr) and aligned to its script line sentence by sentence with
        numbers normalised on both sides (vo_check.py): a take that dropped a sentence is re-generated
        (--retries, default 2), and the run fails loudly if it still drops one. --no-check skips this
        (also skipped with a warning when no ASR backend is installed).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, os, re

from vstudio import media, tts

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vo_check  # noqa: E402

BASE = ("Calm, curious, unhurried teacher thinking out loud at a whiteboard, like a 3Blue1Brown narrator. "
        "Warm and clear. Read numbers carefully and distinctly. Brief pause before each key insight.")

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("lines", nargs="*", help="only these line numbers")
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--engine", default="openai", choices=["openai", "openai-compatible", "elevenlabs", "kokoro", "edge"],
                help="openai (default, per-line delivery direction) | openai-compatible (your own /v1/audio/speech "
                     "server: VSTUDIO_TTS_BASE_URL) | elevenlabs | kokoro | edge (no direction)")
ap.add_argument("--voice", default="cedar")
ap.add_argument("--model", default="gpt-4o-mini-tts")
ap.add_argument("--speed", type=float, default=1.0)
ap.add_argument("--direction", default=BASE, help="global voice direction")
ap.add_argument("--fresh", action="store_true", help="ignore the TTS cache (new take)")
ap.add_argument("--no-check", dest="check", action="store_false", help="skip the per-take ASR sentence check")
ap.add_argument("--retries", type=int, default=2, help="new takes when the check finds a dropped sentence")
ap.add_argument("--asr-backend", default="auto", choices=["auto", "mlx", "faster", "openai", "openai-compatible"])
a = ap.parse_args()
failed = []

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
    fresh = a.fresh
    for attempt in range(1 + max(0, a.retries)):
        tts.synth(text, engine=a.engine, voice=a.voice if a.engine == "openai" or a.voice != "cedar" else None,
                  speed=a.speed, instructions=instr if a.engine in ("openai", "openai-compatible") else None,
                  model=a.model if a.engine == "openai" or a.model != "gpt-4o-mini-tts" else None,
                  out=out, cache=not fresh)
        print(f"line {n:02d}: {media.duration(out):6.1f}s  {len(text.split())} words", flush=True)
        if not a.check:
            break
        try:
            r = vo_check.check_take(out, text, backend=a.asr_backend)
        except Exception as e:  # noqa: BLE001  (no ASR backend installed / reachable)
            print(f"WARN line {n:02d}: sentence check skipped ({type(e).__name__}: {e}); run vo_check.py later")
            break
        if not r["missing"]:
            break
        print(f"line {n:02d}: take dropped {len(r['missing'])} sentence(s): {r['missing']}"
              + ("; new take" if attempt < a.retries else ""), flush=True)
        fresh = True
    else:
        failed.append((n, r["missing"]))
if failed:
    sys.exit("TTS dropped sentences after retries (re-run with --fresh N, rephrase, or split the line):\n"
             + "\n".join(f"  line {n:02d}: {m}" for n, m in failed))
