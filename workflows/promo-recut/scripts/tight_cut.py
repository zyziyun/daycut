#!/usr/bin/env python3
"""Tight-cut a talking-head recording from a project config.

  transcribe (whisper, word timestamps)  -> work/audio.json
  --suggest     propose DROP / PATCH candidates (fillers, immediate repeats, long words that hide a
                merged filler, found with the RMS energy envelope) and print them for review
  --draft-subs  print subtitle lines (raw seconds) from the kept words, ready to paste into the config
  (default)     grade the raw, cut body/outro/extra spans (DROP + PATCH + pause squeeze), build the
                highlights montage with internal crossfades, write work/layout.json (raw->cut maps)
  --verify      ASR the cut files again and flag leftover fillers / repeats

Run from anywhere:  python3 $VSTUDIO/workflows/promo-recut/scripts/tight_cut.py promo.config.json [--suggest]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os
import re

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project, P  # noqa: E402
from vstudio import asr, audio, cut, media  # noqa: E402

PUNCT = re.compile(r"[\s，。,.!?！？、：:；;“”\"'…-]+")


def norm(s):
    return PUNCT.sub("", s).lower()


def fillers_of(prj):
    """Config cut.fillers, else the library's zh + en filler lists."""
    return prj.get("cut.fillers") or (cut.FILLERS_ZH + cut.FILLERS_EN)


def words_of(transcript):
    """Whisper-shaped words [{word, start, end}] (leading spaces kept, so English re-joins cleanly)."""
    return [dict(w) for s in transcript["segments"] for w in s.get("words", [])]


# ---------------------------------------------------------------- transcript
def transcribe(prj, src):
    return asr.transcribe(src, language=prj.get("language"), model=prj.get("whisper_model"),
                          cache=False, fix_terms=False)


def load_words(prj, force=False, patch=True):
    js = prj.w("audio.json")
    if force or not os.path.exists(js):
        tr = transcribe(prj, prj.p(prj.cfg["talk"]))
        json.dump({k: tr[k] for k in ("language", "text", "segments")}, open(js, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("transcript ->", js)
    words = words_of(json.load(open(js, encoding="utf-8")))
    if patch:  # PATCH: hand-measured word-start corrections (whisper merged a filler into the next word)
        for a, b in prj.get("cut.patch", []) or []:
            for w in words:
                if abs(w["start"] - a) < 0.015:
                    w["start"] = b
    return words


def audio_wav(prj):
    wav = prj.w("audio.wav")
    if not os.path.exists(wav):
        media.extract_wav(prj.p(prj.cfg["talk"]), wav)
    return wav


# ---------------------------------------------------------------- suggest
def suggest(prj, words):
    drops = prj.get("cut.drop", []) or []
    wav = audio_wav(prj)
    x, sr = audio.read_wav(wav, mono=True)
    out = cut.suggest_fillers(words, audio=(x, sr), fillers=fillers_of(prj), drops=drops,
                              per_char=prj.get("cut.long_word_per_char", 0.22))
    print(f"{'kind':<13}{'start':>8}{'end':>8}  note")
    for r in out:
        note = r["note"] or r["text"]
        if r["kind"] == "filler-glued":
            note = f"'{r['text']}' {r['note']}"
        elif r["kind"] == "long-word":
            note = f"'{r['text']}' {r['note']}"
        print(f"{r['kind']:<13}{r['start']:8.2f}{r['end']:8.2f}  {note}{'  (already dropped)' if r['dropped'] else ''}")
    new = [[round(r["start"], 2), round(r["end"], 2)] for r in out
           if r["kind"] in ("filler", "repeat", "repeat2") and not r["dropped"]]
    patches = [[round(r["patch"][0], 2), round(r["patch"][1], 2)] for r in out if r["patch"] and not r["dropped"]]
    print("\nDROP candidates (review by ear before pasting into cut.drop):")
    print(json.dumps(new))
    if patches:
        print("PATCH candidates (cut.patch, [whisper_start, real_start]):")
        print(json.dumps(patches))
    print("\nTip: inspect a region with  ffplay -ss <start-0.5> -t 2 work/audio.wav ;"
          " a PATCH moves a word start to where the RMS rises after the dip.")


# ---------------------------------------------------------------- draft subtitles
def draft_subs(prj, words):
    maxc = P("subtitles.max_cjk_chars", 18)
    drops = prj.get("cut.drop", []) or []
    spans = (prj.get("cut.body", []) or []) + (prj.get("cut.outro", []) or [])
    keep = [w for w in words if any(a - 0.05 <= w["start"] < b for a, b in spans)
            and not any(a - 0.01 <= w["start"] < b - 0.01 for a, b in drops)]
    lines, cur = [], []
    for w in keep:
        if cur and (w["start"] - cur[-1]["end"] > 0.25 or len("".join(c["word"] for c in cur)) >= maxc):
            lines.append(cur); cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:
        t = asr.apply_term_fixes("".join(w["word"] for w in ln).strip())   # persona + generic fixes
        out.append([round(ln[0]["start"], 2), round(ln[-1]["end"], 2), t])
    print("[\n" + ",\n".join("  " + json.dumps(o, ensure_ascii=False) for o in out) + "\n]")
    print("\nEdit the text (punctuation, 【term】 highlights), split body vs outro, paste into subtitles.body / subtitles.outro.")


# ---------------------------------------------------------------- cut
def cut_part(src, segs, out, lufs, fps):
    """Frame-exact cut (vstudio.cut.cut_segments) -> two-pass loudnorm voice stem. Returns the TimeMap."""
    tmp = out[:-4] + ".raw.mp4"
    tm = cut.cut_segments(src, segs, tmp, fps=fps, crf=16)
    audio.loudnorm_2pass(tmp, out, lufs=lufs)
    os.remove(tmp)
    return tm


def montage(src, clips, out, xf, scale, fps, lufs):
    """Highlights montage with internal dissolves (vstudio.cut.xfade_assemble, plain acrossfade:
    mute_pad=False keeps the old clip timing the step labels rely on) -> two-pass loudnorm."""
    asm = cut.xfade_assemble(clips, xfade=xf, mute_pad=False, fps=fps, size=scale,
                             src_durations=[media.duration(src)])
    tmp = out[:-4] + ".raw.mp4"
    cut.render_assembly(asm, [src], tmp, args=["-c:v", "libx264", "-crf", "16", "-preset", "fast",
                                               "-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
    audio.loudnorm_2pass(tmp, out, lufs=lufs)
    os.remove(tmp)


def remap(tm, words):
    """Words that start inside a kept segment -> cut-file seconds."""
    out = []
    for it in tm.segments:
        for w in words:
            if it["src0"] <= w["start"] < it["src1"]:
                out.append({"w": w["word"].strip(), "t": round(it["dst0"] + w["start"] - it["src0"], 3),
                            "te": round(it["dst0"] + min(w["end"], it["src1"]) - it["src0"], 3), "raw": w["start"]})
    return out


def do_cut(prj, words, args):
    fps = P("export.fps", 30)
    voice = P("audio.voice_lufs", -16)
    thr = prj.get("cut.pause_threshold", P("audio.pause_threshold", 0.35))
    pad_in, pad_out = prj.get("cut.pad_in", 0.06), prj.get("cut.pad_out", 0.08)
    drops = prj.get("cut.drop", []) or []

    talk = prj.p(prj.cfg["talk"])
    graded = prj.w("raw_graded.mp4")
    if args.regrade or not os.path.exists(graded):
        vf = [f"fps={fps}"]
        hdr = prj.get("hdr_tonemap")
        if hdr:   # true = force, "auto" = only when the source is HLG/PQ
            tone = media.hdr_to_sdr_args(talk, force=hdr is True)
            if tone:
                vf.append(tone)
        if prj.get("grade"):
            vf.append(prj.get("grade"))
        vf.append("format=yuv420p")
        media.run(["ffmpeg", "-y", "-i", talk, "-vf", ",".join(vf), "-c:v", "libx264",
                   "-crf", "14", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", graded])

    parts = {"body": prj.get("cut.body", []), "outro": prj.get("cut.outro", []) or []}
    parts.update(prj.get("cut.extra", {}) or {})
    layout = {"D": {}, "maps": {}, "words": {}}
    for name, spans in parts.items():
        if not spans:
            continue
        segs = cut.tighten(words, spans, drop=drops, pause_threshold=thr, pad_in=pad_in, pad_out=pad_out,
                           audio=audio_wav(prj) if prj.get("cut.rms_snap") else None)
        if not segs:
            print(f"  warning: no words in {name} spans")
            continue
        out = prj.w(f"{name}.mp4")
        tm = cut_part(graded, segs, out, voice, fps)
        layout["D"][name] = media.duration(out)
        layout["maps"][name] = tm.to_list()        # vstudio.cut.TimeMap items (raw -> cut file)
        layout["words"][name] = remap(tm, words)
        print(f"  {name}: {len(segs)} segments -> {layout['D'][name]:.2f}s")

    m = prj.get("montage") or {}
    if m.get("clips"):
        clips = [(c[0], c[1]) for c in m["clips"]]
        out = prj.w("montage.mp4")
        if args.remontage or not os.path.exists(out):
            montage(prj.p(prj.cfg["highlights"]), clips, out, m.get("crossfade", 0.3),
                    m.get("scale", "1920:1080"), fps, voice - 1)
        layout["D"]["montage"] = media.duration(out)
        layout["clips"] = [[c[0], c[1]] for c in clips]
    json.dump(layout, open(prj.w("layout.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("layout ->", prj.w("layout.json"), {k: round(v, 2) for k, v in layout["D"].items()})
    print("Next: python3 tight_cut.py <config> --verify   (ASR the cut, listen to every join)")


def verify(prj):
    fillers = [norm(f) for f in fillers_of(prj)]
    for name in ["body", "outro"] + list((prj.get("cut.extra") or {}).keys()):
        f = prj.w(f"{name}.mp4")
        if not os.path.exists(f):
            continue
        tr = transcribe(prj, f)
        json.dump({k: tr[k] for k in ("language", "text", "segments")}, open(prj.w(f"{name}.asr.json"), "w",
                  encoding="utf-8"), ensure_ascii=False, indent=1)
        ws = words_of(tr); toks = [norm(w["word"]) for w in ws]
        print(f"\n=== {name} ({media.duration(f):.2f}s) ===")
        for s in tr["segments"]:
            print(f"  {s['start']:6.2f}  {s['text'].strip()}")
        for i, w in enumerate(ws):
            if toks[i] in fillers:
                print(f"  ! filler '{w['word'].strip()}' at cut {w['start']:.2f}s")
            if i + 1 < len(ws) and toks[i] and toks[i] == toks[i + 1]:
                print(f"  ! repeat '{w['word'].strip()}' at cut {w['start']:.2f}s")
    print("\nCut-file seconds -> raw: see work/layout.json maps (vstudio.cut.TimeMap items)."
          " Fix with cut.drop / cut.patch and re-run.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("config", help="project config (JSON or YAML); paths inside are relative to its folder")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--suggest", action="store_true", help="print DROP / PATCH candidates and exit")
    g.add_argument("--draft-subs", action="store_true", help="print subtitle lines from kept words and exit")
    g.add_argument("--verify", action="store_true", help="ASR the cut files and flag leftovers")
    ap.add_argument("--retranscribe", action="store_true", help="re-run whisper on the raw recording")
    ap.add_argument("--regrade", action="store_true", help="re-render work/raw_graded.mp4")
    ap.add_argument("--remontage", action="store_true", help="re-render work/montage.mp4")
    a = ap.parse_args()
    prj = Project(a.config)
    if a.verify:
        return verify(prj)
    words = load_words(prj, a.retranscribe)
    if a.suggest:
        return suggest(prj, words)
    if a.draft_subs:
        return draft_subs(prj, words)
    do_cut(prj, words, a)


if __name__ == "__main__":
    main()
