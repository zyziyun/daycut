#!/usr/bin/env python3
"""Transcribe audio16k.wav -> audio16k.json (whisper format: segments[] with words[]).

Thin wrapper over vstudio.asr.transcribe: mlx_whisper (Apple Silicon) -> faster_whisper ->
OpenAI whisper-1 (only with OPENAI_API_KEY in the environment). It sets the flags that matter for
long, noisy meeting audio (no conditioning on previous text, hallucination-silence threshold, else
whisper loops on filler like "嗯嗯嗯" over silence) and caches the result next to the audio
(audio16k.wav.asr.json), so a re-run is instant. Text is written RAW here; term fixes are applied
by build_subs.py, so editing subtitles.term_fixes never needs a re-transcribe.

Usage: python3 transcribe.py work/config.py [--model ...] [--language zh] [--backend auto|mlx|faster|openai]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import _lfc
from vstudio import asr


def extra(ap):
    ap.add_argument("--model", default=None, help="mlx: mlx-community/whisper-large-v3-turbo; faster: large-v3-turbo")
    ap.add_argument("--language", default=None)
    ap.add_argument("--audio", default="audio16k.wav")
    ap.add_argument("--backend", default="auto", choices=["auto", "mlx", "faster", "openai"])
    ap.add_argument("--prompt", default=None, help="initial prompt with domain terms (default config asr_prompt)")


cfg, args = _lfc.load(description=__doc__, extra=extra)
lang = args.language or cfg.get("language")  # None -> persona creator.language (asr default)
tr = asr.transcribe(args.audio, language=lang, prompt=args.prompt or cfg.get("asr_prompt"), model=args.model,
                    backend=args.backend, fix_terms=False)
out = {"text": tr["text"], "language": tr["language"],
       "segments": [{"start": s["start"], "end": s["end"], "text": s["text"],
                     "words": [{"start": w["start"], "end": w["end"], "word": w["word"]} for w in s["words"]]}
                    for s in tr["segments"]]}
_lfc.dump_json(out, "audio16k.json", indent=0)
print(f"audio16k.json segments={len(out['segments'])} engine={tr['backend']}")
