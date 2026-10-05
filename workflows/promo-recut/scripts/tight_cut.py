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
from common import Project, P, run, need, duration, extract_wav, read_wav, transcribe, words_of  # noqa: E402

DEFAULT_FILLERS = ["然后", "就是", "那个", "嗯", "呃", "额", "啊", "um", "uh", "erm"]
PUNCT = re.compile(r"[\s，。,.!?！？、：:；;“”\"'…-]+")
HDR_TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
               "zscale=t=bt709:m=bt709:r=tv")


def norm(s):
    return PUNCT.sub("", s).lower()


# ---------------------------------------------------------------- transcript
def load_words(prj, force=False):
    js = prj.w("audio.json")
    if force or not os.path.exists(js):
        wav = prj.w("audio.wav")
        extract_wav(prj.p(prj.cfg["talk"]), wav)
        tr = transcribe(wav, prj.get("language"), prj.get("whisper_model"))
        json.dump(tr, open(js, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("transcript ->", js)
    words = words_of(json.load(open(js, encoding="utf-8")))
    # PATCH: hand-measured word-start corrections (whisper merged a filler into the next word)
    for a, b in prj.get("cut.patch", []) or []:
        for w in words:
            if abs(w["start"] - a) < 0.015:
                w["start"] = b
    return words


# ---------------------------------------------------------------- suggest
def rms_envelope(x, sr, hop=0.01, win=0.03):
    import numpy as np
    h, n = int(sr * hop), int(sr * win)
    frames = max(1, (len(x) - n) // h)
    env = np.array([np.sqrt(np.mean(x[i * h:i * h + n] ** 2) + 1e-12) for i in range(frames)])
    k = np.ones(3) / 3
    return np.convolve(env, k, mode="same"), hop


def hidden_onset(env, hop, t0, t1, valley=0.35, min_gap=0.05):
    """If a word contains an energy valley (< valley*peak for >= min_gap s) followed by a rise,
    return (dip_start, dip_end, new_start). That is usually a filler merged into the word."""
    import numpy as np
    i0, i1 = int(t0 / hop), int(t1 / hop)
    seg = env[i0:i1]
    if len(seg) < 8:
        return None
    peak = seg.max()
    low = seg < valley * peak
    best = None
    i = 0
    while i < len(seg):
        if low[i]:
            j = i
            while j < len(seg) and low[j]:
                j += 1
            if (j - i) * hop >= min_gap and i > 2 and j < len(seg) - 3:
                rise = j + int(np.argmax(seg[j:] > 0.5 * peak)) if (seg[j:] > 0.5 * peak).any() else j
                best = (i0 + i) * hop, (i0 + j) * hop, (i0 + rise) * hop - 0.03
            i = j
        else:
            i += 1
    return best


def suggest(prj, words):
    import numpy as np  # noqa: F401
    fillers = [norm(f) for f in prj.get("cut.fillers", DEFAULT_FILLERS)]
    drops = prj.get("cut.drop", []) or []
    in_drop = lambda t: any(a - 0.01 <= t < b - 0.01 for a, b in drops)
    toks = [norm(w["word"]) for w in words]
    out = []

    # 1) fillers (may be split across whisper tokens, or glued to the next word)
    for i in range(len(words)):
        for k in (1, 2, 3):
            if i + k > len(words):
                break
            joined = "".join(toks[i:i + k])
            if joined in fillers:
                out.append(("filler", words[i]["start"], words[i + k - 1]["end"], joined))
                break
        else:
            for f in fillers:
                if len(f) >= 2 and toks[i].startswith(f) and toks[i] != f:
                    out.append(("filler-glued", words[i]["start"], words[i]["end"],
                                f"'{words[i]['word'].strip()}' starts with {f}: drop + PATCH the start"))

    # 2) immediate repeats: A A, or A B A B (drop the first copy)
    for i in range(len(words) - 1):
        if toks[i] and toks[i] == toks[i + 1] and toks[i] not in fillers:
            out.append(("repeat", words[i]["start"], words[i + 1]["start"], toks[i] * 2))
        if i + 3 < len(words) and toks[i] and toks[i] + toks[i + 1] == toks[i + 2] + toks[i + 3]:
            out.append(("repeat2", words[i]["start"], words[i + 2]["start"], toks[i] + toks[i + 1]))

    # 3) long words: energy dip inside -> likely a merged filler or a restart
    wav = prj.w("audio.wav")
    if not os.path.exists(wav):
        extract_wav(prj.p(prj.cfg["talk"]), wav)
    x, sr = read_wav(wav)
    env, hop = rms_envelope(x, sr)
    per_char = prj.get("cut.long_word_per_char", 0.22)
    for w in words:
        d, n = w["end"] - w["start"], max(1, len(norm(w["word"])))
        if d > max(0.45, per_char * n + 0.15):
            hit = hidden_onset(env, hop, w["start"], w["end"])
            if hit:
                out.append(("long-word", w["start"], w["end"],
                            f"'{w['word'].strip()}' {d:.2f}s, dip {hit[0]:.2f}-{hit[1]:.2f} -> "
                            f"PATCH [{w['start']:.2f}, {hit[2]:.2f}] and maybe DROP [{w['start']:.2f}, {hit[2]:.2f}]"))
            else:
                out.append(("long-word", w["start"], w["end"], f"'{w['word'].strip()}' {d:.2f}s, no clear dip - listen"))

    out.sort(key=lambda r: r[1])
    print(f"{'kind':<13}{'start':>8}{'end':>8}  note")
    for kind, a, b, note in out:
        flag = "  (already dropped)" if in_drop(a) else ""
        print(f"{kind:<13}{a:8.2f}{b:8.2f}  {note}{flag}")
    new = [[round(a, 2), round(b, 2)] for kind, a, b, _ in out
           if kind in ("filler", "repeat", "repeat2") and not in_drop(a)]
    print("\nDROP candidates (review by ear before pasting into cut.drop):")
    print(json.dumps(new))
    print("\nTip: inspect a region with  ffplay -ss <start-0.5> -t 2 work/audio.wav ;"
          " a PATCH moves a word start to where the RMS rises after the dip.")


# ---------------------------------------------------------------- draft subtitles
def draft_subs(prj, words):
    fixes = P("subtitles.term_fixes", {}) or {}
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
        t = "".join(w["word"] for w in ln).strip()
        for a, b in fixes.items():
            t = re.sub(re.escape(a), b, t, flags=re.I)
        out.append([round(ln[0]["start"], 2), round(ln[-1]["end"], 2), t])
    print("[\n" + ",\n".join("  " + json.dumps(o, ensure_ascii=False) for o in out) + "\n]")
    print("\nEdit the text (punctuation, 【term】 highlights), split body vs outro, paste into subtitles.body / subtitles.outro.")


# ---------------------------------------------------------------- cut
def tighten(spans, words, drops, thr, pad_in, pad_out):
    dropped = lambda w: any(a - 0.01 <= w["start"] < b - 0.01 for a, b in drops)
    out = []
    for a, b in spans:
        ws = [w for w in words if a - 0.05 <= w["start"] < b and not dropped(w)]
        if not ws:
            print(f"  warning: no words in span {a}-{b}")
            continue
        brk = lambda prev, w: w["start"] - prev["end"] > thr or any(prev["end"] - 0.02 <= x[0] < w["start"] + 0.02 for x in drops)
        cur = [max(a, ws[0]["start"] - pad_in), None]
        last, pw = ws[0]["end"], ws[0]
        for w in ws[1:]:
            if brk(pw, w):
                long_gap = w["start"] - last > thr
                cur[1] = last + (pad_out if long_gap else 0.01)
                out.append(tuple(cur))
                cur = [w["start"] - (pad_in if long_gap else 0.0), None]
            last, pw = w["end"], w
        cur[1] = min(b + 0.05, last + 0.1)
        out.append(tuple(cur))
    return [(round(s, 3), round(e, 3)) for s, e in out]


def cut_file(src, segs, out, lufs):
    fl, cat = [], ""
    for i, (s, e) in enumerate(segs):
        fl.append(f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS[v{i}];[0:a]atrim={s}:{e},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.015,afade=t=out:st={max(0, e - s - 0.02):.3f}:d=0.02[a{i}]")
        cat += f"[v{i}][a{i}]"
    fl.append(f"{cat}concat=n={len(segs)}:v=1:a=1[v][a0];[a0]loudnorm=I={lufs}:TP=-1.5:LRA=11[a]")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", ";".join(fl), "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])


def montage(src, clips, out, xf, scale, fps, lufs):
    fl, n = [], len(clips)
    for i, (s, e) in enumerate(clips):
        fl.append(f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS,fps={fps},scale={scale},format=yuv420p[v{i}]")
        fl.append(f"[0:a]atrim={s}:{e},asetpts=PTS-STARTPTS[a{i}]")
    d = [e - s for s, e in clips]
    off, pv, pa = 0.0, "v0", "a0"
    for i in range(1, n):
        off += d[i - 1] - xf
        fl.append(f"[{pv}][v{i}]xfade=transition=fade:duration={xf}:offset={off:.3f}[xv{i}]"); pv = f"xv{i}"
        fl.append(f"[{pa}][a{i}]acrossfade=d={xf}[xa{i}]"); pa = f"xa{i}"
    fl.append(f"[{pa}]loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    run(["ffmpeg", "-y", "-v", "error", "-i", src, "-filter_complex", ";".join(fl), "-map", f"[{pv}]", "-map", "[aout]",
         "-c:v", "libx264", "-crf", "16", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", out])


def remap(segs, words):
    out, acc = [], 0.0
    for s0, e0 in segs:
        for w in words:
            if s0 <= w["start"] < e0:
                out.append({"w": w["word"].strip(), "t": round(acc + w["start"] - s0, 3),
                            "te": round(acc + min(w["end"], e0) - s0, 3), "raw": w["start"]})
        acc += e0 - s0
    return out


def rawmap(segs):
    m, acc = [], 0.0
    for s0, e0 in segs:
        m.append([s0, e0, round(acc, 3)]); acc += e0 - s0
    return m


def do_cut(prj, words, args):
    need("ffmpeg")
    fps = P("export.fps", 30)
    voice = P("audio.voice_lufs", -16)
    thr = prj.get("cut.pause_threshold", P("audio.pause_threshold", 0.35))
    pad_in, pad_out = prj.get("cut.pad_in", 0.06), prj.get("cut.pad_out", 0.08)
    drops = prj.get("cut.drop", []) or []

    graded = prj.w("raw_graded.mp4")
    if args.regrade or not os.path.exists(graded):
        vf = [f"fps={fps}"]
        if prj.get("hdr_tonemap"):
            vf.append(HDR_TONEMAP)
        if prj.get("grade"):
            vf.append(prj.get("grade"))
        vf.append("format=yuv420p")
        run(["ffmpeg", "-y", "-v", "error", "-i", prj.p(prj.cfg["talk"]), "-vf", ",".join(vf), "-c:v", "libx264",
             "-crf", "14", "-preset", "fast", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", graded])

    parts = {"body": prj.get("cut.body", []), "outro": prj.get("cut.outro", []) or []}
    parts.update(prj.get("cut.extra", {}) or {})
    layout = {"D": {}, "maps": {}, "words": {}}
    for name, spans in parts.items():
        if not spans:
            continue
        segs = tighten(spans, words, drops, thr, pad_in, pad_out)
        out = prj.w(f"{name}.mp4")
        cut_file(graded, segs, out, voice)
        layout["D"][name] = duration(out)
        layout["maps"][name] = rawmap(segs)
        layout["words"][name] = remap(segs, words)
        print(f"  {name}: {len(segs)} segments -> {layout['D'][name]:.2f}s")

    m = prj.get("montage") or {}
    if m.get("clips"):
        clips = [(c[0], c[1]) for c in m["clips"]]
        out = prj.w("montage.mp4")
        if args.remontage or not os.path.exists(out):
            montage(prj.p(prj.cfg["highlights"]), clips, out, m.get("crossfade", 0.3),
                    m.get("scale", "1920:1080"), fps, voice - 1)
        layout["D"]["montage"] = duration(out)
        layout["clips"] = [[c[0], c[1]] for c in clips]
    json.dump(layout, open(prj.w("layout.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("layout ->", prj.w("layout.json"), {k: round(v, 2) for k, v in layout["D"].items()})
    print("Next: python3 tight_cut.py <config> --verify   (ASR the cut, listen to every join)")


def verify(prj):
    fillers = [norm(f) for f in prj.get("cut.fillers", DEFAULT_FILLERS)]
    for name in ["body", "outro"] + list((prj.get("cut.extra") or {}).keys()):
        f = prj.w(f"{name}.mp4")
        if not os.path.exists(f):
            continue
        wav = prj.w(f"{name}.asr.wav")
        extract_wav(f, wav)
        tr = transcribe(wav, prj.get("language"), prj.get("whisper_model"))
        json.dump(tr, open(prj.w(f"{name}.asr.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        ws = words_of(tr); toks = [norm(w["word"]) for w in ws]
        print(f"\n=== {name} ({duration(f):.2f}s) ===")
        for s in tr["segments"]:
            print(f"  {s['start']:6.2f}  {s['text'].strip()}")
        for i, w in enumerate(ws):
            if toks[i] in fillers:
                print(f"  ! filler '{w['word'].strip()}' at cut {w['start']:.2f}s")
            if i + 1 < len(ws) and toks[i] and toks[i] == toks[i + 1]:
                print(f"  ! repeat '{w['word'].strip()}' at cut {w['start']:.2f}s")
        os.remove(wav)
    print("\nCut-file seconds -> raw: see work/layout.json maps. Fix with cut.drop / cut.patch and re-run.")


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
