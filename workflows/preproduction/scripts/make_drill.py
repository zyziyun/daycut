#!/usr/bin/env python3
"""Pronunciation / shadowing drill from a word list: audio (WAV + M4A) and a markdown reference card.

Per word:  [word, slow] 1.2s [word, slow] 1.2s [script sentence, near-normal] 2.2s
Preceded by a spoken intro. Loudness-normalized to persona audio.loudness_lufs.

Input (JSON or TXT):
  JSON: [{"word": "...", "sentence": "...", "ipa": "/.../", "pitfall": "...", "bad": "...", "good": "..."}, ...]
  TXT : one entry per line, `word | sentence | ipa | pitfall` (ipa/pitfall optional, '#' = comment)

TTS engines (--engine auto picks the first available):
  kokoro  Kokoro-82M via mlx-audio (Apple Silicon; pip install mlx-audio)
  edge    Microsoft Edge neural voices via edge-tts (any OS, needs network; pip install edge-tts)
  openai  OpenAI gpt-4o-mini-tts (any OS, needs OPENAI_API_KEY; plain HTTPS, no package needed)
Clips go through vstudio.tts.synth (48 kHz mono, cached in $VSTUDIO_CACHE/tts, so re-runs are free).

  python3 make_drill.py work/drill_words.json -o work/pronunciation_drill [--script SCRIPT.md] [--engine edge]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import json
import re
import tempfile

import numpy as np

from vstudio import audio, tts

SR = audio.SR                    # vstudio.tts writes 48 kHz mono; the drill is assembled at that rate


def load_words(path):
    p = pathlib.Path(path)
    txt = p.read_text(encoding="utf-8")
    if p.suffix.lower() == ".json":
        items = json.loads(txt)
        items = items.get("words", items) if isinstance(items, dict) else items
    else:
        items = []
        for ln in txt.splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            parts = [x.strip() for x in ln.split("|")]
            items.append(dict(zip(["word", "sentence", "ipa", "pitfall"], parts)))
    for it in items:
        it.setdefault("sentence", it["word"] + ".")
    return items


def say(engine, text, speed, voice, model):
    """One TTS clip as mono float32 at SR (vstudio.tts.synth, cached by text+voice+speed)."""
    x, sr = audio.read_wav(tts.synth(text, engine=engine, voice=voice, speed=speed, model=model), mono=True)
    if sr != SR:
        raise SystemExit(f"unexpected TTS sample rate {sr}")
    return x


def gap(sec):
    return np.zeros(int(round(sec * SR)), np.float32)


def write_card(items, path, script_ok):
    lines = ["# Pronunciation drill", ""]
    for i, it in enumerate(items, 1):
        lines.append(f"## {i}. {it['word']}  {it.get('ipa', '')}".rstrip())
        lines.append("")
        if it.get("pitfall"):
            lines += [f"**Pitfall**: {it['pitfall']}", ""]
        if it.get("bad") or it.get("good"):
            lines += ["```", f"BAD:  {it.get('bad', '')}", f"GOOD: {it.get('good', '')}", "```", ""]
        flag = "" if script_ok.get(it["word"], True) else "  ⚠ not found in the script"
        lines += [f"**Sentence**: *{it['sentence']}*{flag}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", help="JSON or TXT word list")
    ap.add_argument("-o", "--out", default="pronunciation_drill", help="output stem (writes .wav .m4a .md)")
    ap.add_argument("--script", help="locked script; warns about words/sentences not in it")
    ap.add_argument("--engine", choices=["auto", "kokoro", "edge", "openai"], default="auto")
    ap.add_argument("--voice", help="voice id (default: persona tts.<engine>_voice or engine default)")
    ap.add_argument("--model", help="kokoro HF repo or openai TTS model (default: vstudio.tts.DEFAULT_MODEL)")
    ap.add_argument("--slow", type=float, default=0.65, help="word speed (0.65 = every phoneme audible)")
    ap.add_argument("--normal", type=float, default=0.85, help="sentence speed (near-normal with breathing room)")
    ap.add_argument("--gap-short", type=float, default=1.2)
    ap.add_argument("--gap-long", type=float, default=2.2)
    ap.add_argument("--intro", help="spoken intro (default: 'Pronunciation drill. N words. Repeat after each one.')")
    ap.add_argument("--max-words", type=int, default=12, help="refuse longer lists (split into two drills)")
    ap.add_argument("--dry-run", action="store_true", help="write the .md card and print the plan, no TTS")
    a = ap.parse_args()

    items = load_words(a.words)
    if not 1 <= len(items) <= a.max_words:
        raise SystemExit(f"{len(items)} words; keep it to 5-10 (max {a.max_words}) per drill")
    out = pathlib.Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)

    script_ok = {}
    if a.script:
        st = re.sub(r"\s+", " ", pathlib.Path(a.script).read_text(encoding="utf-8")).lower()
        for it in items:
            script_ok[it["word"]] = it["word"].lower() in st
            if not script_ok[it["word"]]:
                print(f"  warning: '{it['word']}' is not in the script (drill only what you'll record)")
    write_card(items, out.with_suffix(".md"), script_ok)
    print("card:", out.with_suffix(".md"))
    if a.dry_run:
        est = 6 + len(items) * 9.6
        print(f"plan: {len(items)} words, ~{est:.0f}s of audio")
        return

    try:
        engine = tts.pick_engine(a.engine)
    except RuntimeError as e:
        raise SystemExit(str(e))
    voice = a.voice                              # None -> persona tts.<engine>_voice, else vstudio.tts default
    print(f"engine={engine} voice={voice or 'persona/engine default'}")
    intro = a.intro or f"Pronunciation drill. {len(items)} words. Repeat after each one."
    seq = [say(engine, intro, a.normal, voice, a.model), gap(a.gap_long)]
    for i, it in enumerate(items):
        print(f"  [{i + 1}/{len(items)}] {it['word']}", flush=True)
        w = say(engine, f"{it['word']}.", a.slow, voice, a.model)
        s = say(engine, it["sentence"], a.normal, voice, a.model)
        seq += [w, gap(a.gap_short), w, gap(a.gap_short), s, gap(a.gap_long)]
    with tempfile.TemporaryDirectory(prefix="drill_") as tmp:
        raw = str(pathlib.Path(tmp) / "raw.wav")
        audio.write_wav(raw, np.concatenate(seq), SR)
        # two-pass linear loudnorm to persona audio.loudness_lufs; both outputs 48 kHz stereo
        m = audio.loudnorm_2pass(raw, str(out.with_suffix(".wav")))
        audio.loudnorm_2pass(raw, str(out.with_suffix(".m4a")), audio_bitrate="96k")
    print(f"  loudness in: I={m['input_i']} LUFS  TP={m['input_tp']} dBTP")
    for ext in (".wav", ".m4a", ".md"):
        f = out.with_suffix(ext)
        print(f"  {f}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
