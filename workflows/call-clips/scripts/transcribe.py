#!/usr/bin/env python3
"""Transcribe the whole recording once, with word timestamps.

Writes <out>.wav (16 kHz mono, what find_disfluencies.py reads) and <out>.json
(whisper format: {"segments": [{start, end, text, words: [{word, start, end}]}]}).
Uses mlx_whisper on Apple Silicon if importable, else faster_whisper.

Usage:
  transcribe.py recordings/my-call.mp4 --out work/audio16k [--language zh]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess


def run_mlx(wav, model, language):
    import mlx_whisper
    return mlx_whisper.transcribe(
        wav, path_or_hf_repo=model, language=language, word_timestamps=True,
        condition_on_previous_text=False)


def run_faster(wav, model, language):
    from faster_whisper import WhisperModel
    m = WhisperModel(model, compute_type="auto")
    segs, _ = m.transcribe(wav, language=language, word_timestamps=True,
                           condition_on_previous_text=False)
    out = []
    for s in segs:
        out.append({"start": s.start, "end": s.end, "text": s.text,
                    "words": [{"word": w.word, "start": w.start, "end": w.end,
                               "probability": w.probability} for w in (s.words or [])]})
    return {"segments": out}


def main():
    ap = argparse.ArgumentParser(description="Recording -> 16k wav + word-timestamped whisper JSON.")
    ap.add_argument("video")
    ap.add_argument("--out", default="work/audio16k", help="path prefix for .wav and .json")
    ap.add_argument("--language", default=None, help="default: persona creator.language or zh")
    ap.add_argument("--mlx-model", default="mlx-community/whisper-large-v3-turbo")
    ap.add_argument("--faster-model", default="large-v3")
    args = ap.parse_args()

    if args.language is None:
        from vstudio.config import persona
        args.language = (persona().get("creator") or {}).get("language") or "zh"
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    wav = args.out + ".wav"
    if not os.path.exists(wav):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", args.video, "-ac", "1", "-ar", "16000",
                        "-c:a", "pcm_s16le", wav], check=True)
    try:
        import mlx_whisper  # noqa: F401
        res = run_mlx(wav, args.mlx_model, args.language)
        engine = "mlx_whisper"
    except ImportError:
        res = run_faster(wav, args.faster_model, args.language)
        engine = "faster_whisper"
    json.dump({"segments": res["segments"]}, open(args.out + ".json", "w", encoding="utf-8"),
              ensure_ascii=False)
    print(f"{engine}: {len(res['segments'])} segments -> {args.out}.json, audio -> {wav}")


if __name__ == "__main__":
    main()
