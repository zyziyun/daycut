#!/usr/bin/env python3
"""Transcribe audio16k.wav -> audio16k.json (whisper format: segments[] with words[]).

Uses mlx_whisper when importable (Apple Silicon), else faster_whisper. The flags that
matter for long, noisy meeting audio: no conditioning on previous text and a
hallucination-silence threshold, else whisper loops on filler ("嗯嗯嗯") over silence.

Usage: python3 transcribe.py work/config.py [--model ...] [--language zh]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import _lfc
from vstudio.config import persona


def extra(ap):
    ap.add_argument("--model", default=None, help="mlx: mlx-community/whisper-large-v3-turbo; faster: large-v3")
    ap.add_argument("--language", default=None)
    ap.add_argument("--audio", default="audio16k.wav")


cfg, args = _lfc.load(description=__doc__, extra=extra)
lang = args.language or cfg.get("language") or persona().get("creator", {}).get("language", "zh")

try:
    import mlx_whisper  # noqa: F401
    engine = "mlx"
except ImportError:
    engine = "faster"

if engine == "mlx":
    import mlx_whisper
    res = mlx_whisper.transcribe(
        args.audio, path_or_hf_repo=args.model or "mlx-community/whisper-large-v3-turbo",
        language=lang, word_timestamps=True, condition_on_previous_text=False,
        hallucination_silence_threshold=2, verbose=False)
    out = {"text": res.get("text", ""), "language": lang,
           "segments": [{"start": s["start"], "end": s["end"], "text": s["text"],
                         "words": [{"start": w["start"], "end": w["end"], "word": w["word"]}
                                   for w in s.get("words", [])]} for s in res["segments"]]}
else:
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("install mlx-whisper (Apple Silicon) or faster-whisper")
    model = WhisperModel(args.model or "large-v3", compute_type="auto")
    segs, _ = model.transcribe(args.audio, language=lang, word_timestamps=True,
                               condition_on_previous_text=False,
                               hallucination_silence_threshold=2, vad_filter=False)
    out = {"language": lang, "segments": []}
    for s in segs:
        out["segments"].append({"start": s.start, "end": s.end, "text": s.text,
                                "words": [{"start": w.start, "end": w.end, "word": w.word}
                                          for w in (s.words or [])]})
    out["text"] = "".join(s["text"] for s in out["segments"])

_lfc.dump_json(out, "audio16k.json", indent=0)
print(f"audio16k.json segments={len(out['segments'])} engine={engine}")
