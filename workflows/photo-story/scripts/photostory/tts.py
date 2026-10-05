#!/usr/bin/env python3
"""OpenAI TTS narration -> <TTS.dir>/uNN.wav + timing.json (per-cue start/end from word timestamps).

    python3 tts.py spec.py --sample            # one line in a few voices -> <dir>/samples/
    python3 tts.py spec.py                      # all units (cached by text+voice+instructions)
    python3 tts.py spec.py 3 7                  # only units 3 and 7

Reads OPENAI_API_KEY from the environment only. Voice / model / instructions from spec TTS.
Each unit is synthesised up to 3x and transcribed; the take whose words best match the script wins
(>= 0.93 stops early). Synthesis: ``vstudio.tts.synth`` (OpenAI engine, 48 kHz mono wav); transcription:
``vstudio.asr.transcribe`` (mlx_whisper -> faster_whisper -> OpenAI whisper-1); cue timing:
``vstudio.asr.align_script``. The chosen take per unit is cached in <dir>/cache/ by text+voice+model+instructions.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re

import numpy as np
import soundfile as sf

from vstudio import asr, tts as vtts

from photostory.ctx import Ctx, load_spec
from photostory.timeline import tts_dir

DEFAULTS = dict(voice="marin", model="gpt-4o-mini-tts", tries=3, good=0.93, use_say=False,
                instructions="Voice: a warm, articulate narrator telling a friend a story. Tone: curious, gently "
                             "enthusiastic, never salesy. Pacing: calm and clear, slightly slower than conversation.",
                sample_voices=["marin", "coral", "nova"], language="en")

norm = lambda s: re.findall(r"[a-z0-9]+", s.lower().replace("’", "").replace("'", ""))


def spoken(en, say):
    s = en.replace("**", "")
    for k in sorted(say, key=len, reverse=True):
        s = re.sub(rf"(?<![\w]){re.escape(k)}(?![\w])", say[k], s)
    return s


def trim(a, sr, thr=0.012, pad=0.06):
    idx = np.where(np.abs(a) > thr)[0]
    if not len(idx):
        return a
    s, e = max(0, idx[0] - int(pad * sr)), min(len(a), idx[-1] + int(pad * sr))
    return a[s:e]


def best_align(variants, words, dur):
    """Align the variant (spoken forms vs display text) whose tokens best match the transcript."""
    got = [t for wd, _, _ in words for t in norm(wd)]
    v = max(variants, key=lambda tx: difflib.SequenceMatcher(None, norm(" ".join(tx)), got).ratio())
    return asr.align_script(v, words, dur)


def asr_words(path, cfg):
    """Word timestamps [(word, start, end)] of one take via vstudio.asr (no sidecar cache, no term fixes:
    alignment wants the raw words). Spec TTS ``whisper`` / ``faster_model`` override the backend model."""
    has = lambda m: importlib.util.find_spec(m) is not None
    model = cfg.get("whisper") if has("mlx_whisper") else cfg.get("faster_model") if has("faster_whisper") else None
    tr = asr.transcribe(path, language=cfg["language"], model=model, cache=False, fix_terms=False)
    return [(w["w"], w["t"], w["te"]) for w in tr["words"]]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("units", nargs="*", type=int, help="only these unit indices")
    ap.add_argument("--voice", help="override TTS voice")
    ap.add_argument("--sample", action="store_true", help="synthesise one line in several voices")
    a = ap.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set in the environment")

    spec = load_spec(a.spec)
    C = Ctx(spec)
    cfg = dict(DEFAULTS)
    cfg.update(getattr(spec, "TTS", {}) or {})
    voice = a.voice or cfg["voice"]
    say = getattr(spec, "SAY", {}) or {}
    out = tts_dir(C)
    os.makedirs(os.path.join(out, "cache"), exist_ok=True)
    tmp = os.path.join(out, "cache", "_take.wav")

    def synth(text, v, path, fresh=False):
        # fresh=True forces a new take (retries); the first take may come from the vstudio TTS cache
        vtts.synth(text, engine="openai", voice=v, instructions=cfg["instructions"], model=cfg["model"],
                   out=path, cache=not fresh)
        x, sr = sf.read(path, dtype="float32")
        return (x.mean(1) if x.ndim > 1 else x), sr

    if a.sample:
        os.makedirs(os.path.join(out, "samples"), exist_ok=True)
        line = cfg.get("sample_line") or " ".join(en.replace("**", "") for en, _ in spec.SCRIPT[0][1])
        for v in cfg["sample_voices"]:
            synth(line, v, os.path.join(out, "samples", f"{v}.wav"))
            print("sample", v)
        return

    tpath = os.path.join(out, "timing.json")
    timing = {d["i"]: d for d in json.load(open(tpath))} if os.path.exists(tpath) else {}
    want = set(a.units) or None
    for i, (sec, chunks, _) in enumerate(spec.SCRIPT):
        if want is not None and i not in want:
            continue
        texts = [spoken(en, say) for en, zh in chunks]
        disp = [en.replace("**", "") for en, zh in chunks]
        say_text = " ".join(texts if cfg["use_say"] else disp)
        exps = [norm(" ".join(texts)), norm(" ".join(disp))]
        key = hashlib.md5(f"{voice}|{cfg['model']}|{cfg['instructions']}|{say_text}".encode()).hexdigest()[:16]
        cw, cj = os.path.join(out, "cache", f"{key}.wav"), os.path.join(out, "cache", f"{key}.json")
        if os.path.exists(cw) and os.path.exists(cj):
            c = json.load(open(cj))
            x, sr = sf.read(cw, dtype="float32")
            print(f"[{i:02d}] cache score={c['score']}", flush=True)
            save(out, timing, i, x, sr, c["score"], [tuple(w) for w in c["words"]], texts, disp, tpath)
            continue
        best = None
        for k in range(int(cfg["tries"])):
            x, sr = synth(say_text, voice, tmp, fresh=k > 0)
            x = trim(x, sr)
            sf.write(tmp, x, sr)
            words = asr_words(tmp, cfg)
            got = [t for wd, _, _ in words for t in norm(wd)]
            score = max(difflib.SequenceMatcher(None, e, got).ratio() for e in exps)
            print(f"[{i:02d}] try{k} score={score:.3f} dur={len(x) / sr:.1f}s", flush=True)
            if best is None or score > best[0]:
                best = (score, x, sr, words)
            if score >= cfg["good"]:
                break
        score, x, sr, words = best
        sf.write(cw, x, sr)
        json.dump(dict(score=round(score, 3), words=words, text=say_text), open(cj, "w"))
        save(out, timing, i, x, sr, score, words, texts, disp, tpath)


def save(out, timing, i, x, sr, score, words, texts, disp, tpath):
    p = os.path.join(out, f"u{i:02d}.wav")
    sf.write(p, x, sr)
    timing[i] = dict(i=i, path=p, dur=len(x) / sr, score=round(score, 3),
                     chunks=best_align([texts, disp], words, len(x) / sr))
    json.dump([timing[k] for k in sorted(timing)], open(tpath, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
