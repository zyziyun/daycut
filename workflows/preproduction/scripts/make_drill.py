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
  openai  OpenAI TTS (any OS, needs OPENAI_API_KEY; pip install openai)

  python3 make_drill.py work/drill_words.json -o work/pronunciation_drill [--script SCRIPT.md] [--engine edge]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import asyncio
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile

from vstudio.config import persona

SR = 24000
DEFAULT_VOICE = {"kokoro": "af_heart", "edge": "en-US-AriaNeural", "openai": "alloy"}


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


def pick_engine(name):
    if name != "auto":
        return name
    if platform.system() == "Darwin" and platform.machine() == "arm64" and importlib.util.find_spec("mlx_audio"):
        return "kokoro"
    if importlib.util.find_spec("edge_tts") or shutil.which("edge-tts"):
        return "edge"
    if os.environ.get("OPENAI_API_KEY") and importlib.util.find_spec("openai"):
        return "openai"
    raise SystemExit("no TTS engine: pip install mlx-audio (Apple Silicon) | edge-tts | openai (+OPENAI_API_KEY)")


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1", "-ar", str(SR),
                    "-c:a", "pcm_s16le", str(dst)], check=True)


def tts(engine, text, speed, out_wav, voice, tmp, model):
    raw = tmp / (out_wav.stem + "_raw")
    if engine == "kokoro":
        subprocess.run([sys.executable, "-m", "mlx_audio.tts.generate", "--model", model or "mlx-community/Kokoro-82M-bf16",
                        "--text", text, "--voice", voice, "--speed", str(speed), "--join_audio", "--audio_format", "wav",
                        "--output_path", str(tmp), "--file_prefix", raw.name], check=True, capture_output=True)
        src = tmp / f"{raw.name}.wav"
    elif engine == "edge":
        src = raw.with_suffix(".mp3")
        rate = f"{int(round((speed - 1) * 100)):+d}%"
        if importlib.util.find_spec("edge_tts"):
            import edge_tts
            asyncio.run(edge_tts.Communicate(text, voice, rate=rate).save(str(src)))
        else:
            subprocess.run(["edge-tts", "--voice", voice, f"--rate={rate}", "--text", text, "--write-media", str(src)],
                           check=True, capture_output=True)
    elif engine == "openai":
        from openai import OpenAI
        src = raw.with_suffix(".wav")
        r = OpenAI().audio.speech.create(model=model or "tts-1", voice=voice, input=text, speed=speed,
                                         response_format="wav")
        src.write_bytes(r.content)
    else:
        raise SystemExit(f"unknown engine {engine}")
    to_wav(src, out_wav)
    return out_wav


def silence(sec, path):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    f"anullsrc=channel_layout=mono:sample_rate={SR}", "-t", str(sec), "-c:a", "pcm_s16le", str(path)],
                   check=True)


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
    ap.add_argument("--model", help="kokoro HF repo or openai TTS model")
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

    engine = pick_engine(a.engine)
    tts_cfg = persona().get("tts", {}) or {}
    voice = a.voice or tts_cfg.get(f"{engine}_voice") or DEFAULT_VOICE[engine]
    print(f"engine={engine} voice={voice}")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="drill_"))
    try:
        intro = a.intro or f"Pronunciation drill. {len(items)} words. Repeat after each one."
        seq = [tts(engine, intro, a.normal, tmp / "intro.wav", voice, tmp, a.model), tmp / "sil_long.wav"]
        silence(a.gap_short, tmp / "sil_short.wav"); silence(a.gap_long, tmp / "sil_long.wav")
        for i, it in enumerate(items):
            print(f"  [{i + 1}/{len(items)}] {it['word']}", flush=True)
            w = tts(engine, f"{it['word']}.", a.slow, tmp / f"w{i:02d}_slow.wav", voice, tmp, a.model)
            s = tts(engine, it["sentence"], a.normal, tmp / f"w{i:02d}_sent.wav", voice, tmp, a.model)
            seq += [w, tmp / "sil_short.wav", w, tmp / "sil_short.wav", s, tmp / "sil_long.wav"]
        lst = tmp / "concat.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in seq), encoding="utf-8")
        wav = out.with_suffix(".wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(wav)], check=True)
        lufs = persona().get("audio", {}).get("loudness_lufs", -14)
        base = f"loudnorm=I={lufs}:LRA=11:TP=-1.5"
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(wav), "-af", base + ":print_format=json",
                            "-f", "null", "-"], capture_output=True, text=True)
        m = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S).group(0))  # two-pass, linear
        af = (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
              f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", af, "-ar", "44100",
                        "-c:a", "aac", "-b:a", "96k", str(out.with_suffix(".m4a"))], check=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for ext in (".wav", ".m4a", ".md"):
        f = out.with_suffix(ext)
        print(f"  {f}  ({f.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
