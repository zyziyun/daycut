#!/usr/bin/env python3
"""Side outputs from the same timeline the video uses:
    <out>/subtitles.srt       bilingual SRT (EN line + 中文 line per cue)
    <out>/transcript.md       read-along script by section (+ VOCAB table if the spec has one)
    <out>/voice.mp3           narration only (no music), persona audio.voice_lufs (-16)   (needs timing.json)
    <out>/post.md             post copy (vstudio.publish.post_body): title, intro, outro, chapter timestamps, tags
                              (POST platform= picks the format; default persona platforms.default)

    python3 export.py spec.py [--out out/] [--no-voice]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import os
import tempfile

from vstudio import audio, media, publish
from vstudio.subs import Cue, srt_write, strip_markup

from photostory.ctx import Ctx, load_spec
from photostory.timeline import Timeline, load_timing, place_voice

clean = lambda s: strip_markup(s or "")


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

    srt_write([Cue(s["start"], s["end"], s["en"] or "", s["zh"] or "") for s in T.subs],
              os.path.join(out, "subtitles.srt"), which="both")

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

    post = dict(getattr(spec, "POST", {}) or {})
    pl = publish.platform_name(post.get("platform"))
    cap = publish.XHS_CHAPTER_LABEL_MAX if pl in ("xiaohongshu", "xhs") else None
    chapters = []
    if len(C.SECTIONS) > 1:
        for s, name in enumerate(C.SECTIONS):
            en = C.SECTIONS_EN[s] if s < len(C.SECTIONS_EN) else ""
            lab = f"{name} {en}" if en and en != name else name
            chapters.append((T.sec_bounds[s], lab if not cap or len(lab) <= cap else name))
    body = "\n\n".join(p for p in (post.get("intro"), post.get("outro")) if p)
    text = publish.post_body(None, body, chapters=chapters, tags=post.get("tags"), platform=pl,
                             title=post.get("title", C.TITLE_ZH or C.TITLE_EN))
    open(os.path.join(out, "post.md"), "w", encoding="utf-8").write(text)

    if not a.no_voice and has_audio:
        with tempfile.TemporaryDirectory() as tmp:
            vo = place_voice(C, T, 0.0, T.total, os.path.join(tmp, "voice.wav"))
            vn = os.path.join(tmp, "voice_n.wav")
            audio.normalize_stem(vo, vn)
            media.run(["ffmpeg", "-y", "-i", vn, "-c:a", "libmp3lame", "-b:a", "160k", os.path.join(out, "voice.mp3")])
    elif not a.no_voice:
        print("! no timing.json - skipped voice.mp3 (timestamps above are estimates)")
    print(f"export -> {out}: subtitles.srt transcript.md post.md" + (" voice.mp3" if has_audio and not a.no_voice else ""),
          f"({len(T.subs)} cues)")


if __name__ == "__main__":
    main()
