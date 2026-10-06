#!/usr/bin/env python3
"""Word-timestamp transcript of the narration via vstudio.asr (alternative to `npx hyperframes transcribe`).

Usage:  python3 transcribe.py [--project .] [--audio audio/narration.wav] [--model small.en] [--backend auto]
Reads   <project>/audio/narration.wav (from concat_vo.py)
Writes  <project>/audio/transcript.json in the HyperFrames shape [{"text", "start", "end", "id"}, ...],
        which align_cues.py reads. Backends: mlx_whisper -> faster_whisper -> OpenAI whisper-1
        (see vstudio.asr); the result is cached next to the audio as narration.wav.asr.json.
Term fixes are OFF by default: SCRIPT.md is the ground truth and align_cues.py only uses word timing.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

from vstudio import asr

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--audio", default="audio/narration.wav", help="relative to the project dir")
ap.add_argument("--language", default="en")
ap.add_argument("--model", default=None, help="backend model id (default: vstudio.asr's)")
ap.add_argument("--backend", default="auto", choices=["auto", "mlx", "faster", "openai", "openai-compatible"])
ap.add_argument("--prompt", default=None, help="initial prompt with domain terms")
ap.add_argument("--term-fixes", action="store_true", help="apply persona/generic ASR term fixes to words")
a = ap.parse_args()

root = pathlib.Path(a.project)
tr = asr.transcribe(str(root / a.audio), language=a.language, prompt=a.prompt, model=a.model,
                    backend=a.backend, fix_terms=a.term_fixes)
out = [{"text": w["w"], "start": w["t"], "end": w["te"], "id": f"w{k}"} for k, w in enumerate(tr["words"])]
json.dump(out, open(root / "audio/transcript.json", "w"), indent=2, ensure_ascii=False)
print(f"audio/transcript.json · {len(out)} words · backend {tr['backend']}")
