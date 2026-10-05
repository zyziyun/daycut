#!/usr/bin/env python3
"""Side outputs from the same timeline the video uses:
    <out>/subtitles.srt       bilingual SRT (EN line + 中文 line per cue)
    <out>/transcript.md       read-along script by section (+ VOCAB table if the spec has one)
    <out>/voice.mp3           narration only (no music), -16 LUFS            (needs timing.json)
    <out>/post.md             post copy draft: title, intro, chapter timestamps, tags

    python3 export.py spec.py [--out out/] [--no-voice]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import os
import subprocess

from vstudio.config import persona

from photostory.ctx import Ctx, load_spec
from photostory.timeline import Timeline, load_timing

clean = lambda s: (s or "").replace("**", "")


def ts(x):
    return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(x * 1000 % 1000):03d}"


def mmss(x):
    return f"{int(x // 60):02d}:{int(x % 60):02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", help="output folder (default: folder of spec OUT)")
    ap.add_argument("--no-voice", action="store_true")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    C = Ctx(spec)
    timing, has_audio = load_timing(C)
    T = Timeline(C, timing)
    out = a.out or os.path.dirname(C.path(getattr(spec, "OUT", "out/story.mp4")))
    os.makedirs(out, exist_ok=True)

    srt = []
    for k, s in enumerate(T.subs, 1):
        srt += [str(k), f"{ts(s['start'])} --> {ts(s['end'])}", *[x for x in (clean(s["en"]), clean(s["zh"])) if x], ""]
    open(os.path.join(out, "subtitles.srt"), "w", encoding="utf-8").write("\n".join(srt))

    title = C.TITLE_EN or C.TITLE_ZH
    md = [f"# {title}", ""]
    for s, name in enumerate(C.SECTIONS):
        en = C.SECTIONS_EN[s] if s < len(C.SECTIONS_EN) else ""
        md += [f"## {s:02d} {name}" + (f" · {en}" if en else ""), ""]
        for sec, chunks, _ in spec.SCRIPT:
            if sec == s:
                for e, z in chunks:
                    md += [f"- {clean(e)}  ", f"  {clean(z)}"]
        md.append("")
    vocab = getattr(spec, "VOCAB", None)
    if vocab:
        md += ["## Vocabulary · 重点词汇", "", "| word | meaning | line |", "|---|---|---|"]
        md += [f"| **{w}** | {m} | {ex} |" for w, m, ex in vocab]
    open(os.path.join(out, "transcript.md"), "w", encoding="utf-8").write("\n".join(md) + "\n")

    P = persona()
    post = dict(getattr(spec, "POST", {}) or {})
    tags = list(post.get("tags", [])) + [t for t in ((P.get("publish") or {}).get("tags") or []) if t not in post.get("tags", [])]
    lines = [post.get("title", C.TITLE_ZH or C.TITLE_EN), ""]
    if post.get("intro"):
        lines += [post["intro"], ""]
    if len(C.SECTIONS) > 1:
        lines.append((P.get("publish") or {}).get("chapter_line", "Chapters:"))
        for s, name in enumerate(C.SECTIONS):
            en = C.SECTIONS_EN[s] if s < len(C.SECTIONS_EN) else ""
            lines.append(f"{mmss(T.sec_bounds[s])} {name}" + (f" {en}" if en and en != name else ""))
        lines.append("")
    if post.get("outro"):
        lines += [post["outro"], ""]
    if tags:
        lines.append(" ".join(tags))
    open(os.path.join(out, "post.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")

    if not a.no_voice and has_audio:
        ins, flt = [], []
        for n, u in enumerate(T.units):
            ins += ["-i", C.path(u["path"])]
            ms = int(u["start"] * 1000)
            flt.append(f"[{n}:a]aresample=48000,adelay={ms}|{ms},apad[a{n}]")
        flt.append("".join(f"[a{k}]" for k in range(len(T.units))) +
                   f"amix=inputs={len(T.units)}:normalize=0,atrim=0:{T.total:.2f},loudnorm=I=-16:TP=-1.5[o]")
        subprocess.run(["ffmpeg", "-v", "error", "-y", *ins, "-filter_complex", ";".join(flt), "-map", "[o]",
                        "-c:a", "libmp3lame", "-b:a", "160k", os.path.join(out, "voice.mp3")], check=True)
    elif not a.no_voice:
        print("! no timing.json - skipped voice.mp3 (timestamps above are estimates)")
    print(f"export -> {out}: subtitles.srt transcript.md post.md" + (" voice.mp3" if has_audio and not a.no_voice else ""),
          f"({len(T.subs)} cues)")


if __name__ == "__main__":
    main()
