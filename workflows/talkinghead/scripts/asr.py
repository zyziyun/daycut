#!/usr/bin/env python3
"""Whisper CLI with word timestamps (thin wrapper over vstudio.asr.transcribe: mlx_whisper -> faster_whisper
-> OpenAI whisper-1 if OPENAI_API_KEY is set; cached in <wav>.asr.json; persona + generic term fixes).

Writes the whisper-shaped dict {"text", "segments": [{start, end, text, words: [{word, start, end}]}], "words"}.
CLI:  python3 asr.py audio.wav out.json [--prompt "术语 列表"] [--language zh]
      prints "start-end text" per segment.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

from vstudio import asr


def main():
    ap = argparse.ArgumentParser(description="Whisper transcription with word timestamps (vstudio.asr).")
    ap.add_argument("wav"); ap.add_argument("out")
    ap.add_argument("--prompt", default=os.environ.get("PROMPT"), help="initial_prompt with domain terms (env PROMPT)")
    ap.add_argument("--language", default=None, help="default: persona creator.language, else zh")
    a = ap.parse_args()
    r = asr.transcribe(a.wav, language=a.language, prompt=a.prompt)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    for s in r["segments"]:
        print(f"{s['start']:7.2f}-{s['end']:7.2f} {s['text']}")


if __name__ == "__main__":
    main()
