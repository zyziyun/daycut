#!/usr/bin/env python3
"""Whisper wrapper with word timestamps: mlx_whisper (Apple Silicon) if importable, else faster_whisper.

Returns the mlx_whisper-shaped dict {"text", "segments": [{start, end, text, words: [{word, start, end}]}]}
so every caller works the same on either backend. persona.subtitles.term_fixes is applied to the
text of segments and words (indices are untouched, so strict_pass DEL indices stay valid).

CLI:  python3 asr.py audio.wav out.json [--prompt "术语 列表"] [--language zh]
      prints "start-end text" per segment.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

from vstudio.config import persona

MLX_REPO = os.environ.get("VSTUDIO_WHISPER_MLX", "mlx-community/whisper-large-v3-turbo")
FW_MODEL = os.environ.get("VSTUDIO_WHISPER_FW", "large-v3-turbo")


def _fix(text: str) -> str:
    for a, b in ((persona().get("subtitles") or {}).get("term_fixes") or {}).items():
        text = text.replace(a, b)
    return text


def transcribe(wav: str, prompt: str = None, language: str = None, word_timestamps: bool = True) -> dict:
    language = language or (persona().get("creator") or {}).get("language") or "zh"
    try:
        import mlx_whisper
        r = mlx_whisper.transcribe(wav, path_or_hf_repo=MLX_REPO, language=language,
                                   word_timestamps=word_timestamps, initial_prompt=prompt or None)
    except ImportError:
        from faster_whisper import WhisperModel
        m = WhisperModel(FW_MODEL, device="auto", compute_type="auto")
        segs, _ = m.transcribe(wav, language=language, word_timestamps=word_timestamps,
                               initial_prompt=prompt or None)
        out = []
        for s in segs:
            words = [dict(word=w.word, start=w.start, end=w.end) for w in (s.words or [])]
            out.append(dict(start=s.start, end=s.end, text=s.text, words=words))
        r = dict(text="".join(s["text"] for s in out), segments=out)
    for s in r["segments"]:
        s["text"] = _fix(s["text"])
        for w in s.get("words") or []:
            w["word"] = _fix(w["word"])
    r["text"] = _fix(r.get("text", ""))
    return r


def main():
    ap = argparse.ArgumentParser(description="Whisper transcription with word timestamps (mlx_whisper or faster_whisper).")
    ap.add_argument("wav"); ap.add_argument("out")
    ap.add_argument("--prompt", default=os.environ.get("PROMPT"), help="initial_prompt with domain terms (env PROMPT)")
    ap.add_argument("--language", default=None, help="default: persona creator.language, else zh")
    a = ap.parse_args()
    r = transcribe(a.wav, a.prompt, a.language)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False)
    for s in r["segments"]:
        print(f"{s['start']:7.2f}-{s['end']:7.2f} {s['text']}")


if __name__ == "__main__":
    main()
