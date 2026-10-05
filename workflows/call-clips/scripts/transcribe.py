#!/usr/bin/env python3
"""Transcribe the whole recording once, with word timestamps (vstudio.asr.transcribe).

Writes <out>.wav (16 kHz mono, what find_disfluencies.py / auto_trim read) and <out>.json
(whisper format: {"segments": [{start, end, text, words: [{word, start, end}]}]}), RAW: term
fixes are applied later, per subtitle line, by build_clips.py. Backend: mlx_whisper on Apple
Silicon if importable, else faster_whisper (else OpenAI whisper-1 if OPENAI_API_KEY is set).
The ASR result is cached in <out>.wav.asr.json, so a re-run never re-transcribes.

Usage:
  transcribe.py recordings/my-call.mp4 --out work/audio16k [--language zh]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, importlib.util, json, os

from vstudio import asr, media


def main():
    ap = argparse.ArgumentParser(description="Recording -> 16k wav + word-timestamped whisper JSON.")
    ap.add_argument("video")
    ap.add_argument("--out", default="work/audio16k", help="path prefix for .wav and .json")
    ap.add_argument("--language", default=None, help="default: persona creator.language or zh")
    ap.add_argument("--mlx-model", default=None, help=f"default {asr.MLX_REPO}")
    ap.add_argument("--faster-model", default=None, help=f"default {asr.FW_MODEL}")
    ap.add_argument("--prompt", default=None, help="initial prompt with domain terms (helps code-switched English)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    wav = args.out + ".wav"
    if not os.path.exists(wav):
        media.extract_wav(args.video, wav, sr=16000, channels=1)
    mlx = importlib.util.find_spec("mlx_whisper") is not None
    res = asr.transcribe(wav, language=args.language, prompt=args.prompt,
                         model=args.mlx_model if mlx else args.faster_model, fix_terms=False)
    json.dump({"segments": res["segments"]}, open(args.out + ".json", "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"{res['backend']}: {len(res['segments'])} segments -> {args.out}.json, audio -> {wav}")


if __name__ == "__main__":
    main()
