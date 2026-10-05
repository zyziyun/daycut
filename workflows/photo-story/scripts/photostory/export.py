#!/usr/bin/env python3
"""Side outputs from the same timeline the video uses:
    <out>/subtitles.srt       bilingual SRT (EN line + 中文 line per cue)
    <out>/cues.json           the same cues as subs.Cue dicts (text = 中文, alt = EN) for python -m vstudio.export
    <out>/transcript.md       read-along script by section (+ VOCAB table if the spec has one)
    <out>/voice.mp3           narration only (no music), persona audio.voice_lufs (-16)   (needs timing.json)
    <out>/post.md             post copy (vstudio.publish.post_body): title, intro, outro, chapter timestamps, tags
                              (POST platform= picks the format; default persona platforms.default; POST tags=
                              [...] own tags, use_persona_tags=False drops the persona's, tag_set="art" picks
                              persona publish.tag_sets.art)

    python3 export.py spec.py [--out out/] [--no-voice]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import inspect
import json
import os
import tempfile

from vstudio import audio, media, publish
from vstudio.subs import Cue, srt_write, strip_markup

from vstudio import platform as vplat

from photostory.ctx import Ctx, check_profile, load_spec
from photostory.timeline import Timeline, load_timing, place_voice

clean = lambda s: strip_markup(s or "")


def tag_args(post):
    """POST keys for the hashtag line -> publish.post_body kwargs. ``tags`` = the post's own; persona tags are
    appended unless ``use_persona_tags: False``; ``tag_set`` picks persona ``publish.tag_sets[<name>]`` (e.g.
    "art") instead of the default ``publish.tags``. An older library without these arguments gets neither
    (a warning names what was ignored)."""
    want = dict(use_persona_tags=bool(post.get("use_persona_tags", True)), tag_set=post.get("tag_set"))
    params = inspect.signature(publish.post_body).parameters
    if "use_persona_tags" in params and "tag_set" in params:
        return want
    for k, default in (("use_persona_tags", True), ("tag_set", None)):
        if want[k] != default:
            print(f"! this vstudio.publish.post_body has no {k}; POST {k}={want[k]!r} ignored (update lib/)")
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", help="output folder (default: folder of spec OUT)")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--platform", help="override spec PLATFORM (post format, length check)")
    ap.add_argument("--mode", choices=["narration", "music"], help="override spec MODE")
    a = ap.parse_args()
    spec = load_spec(a.spec)
    if a.platform:
        spec.PLATFORM = a.platform
    if a.mode:
        spec.MODE = a.mode
    C = Ctx(spec)
    if C.MODE == "music":
        from photostory.music import MusicTimeline
        T, has_audio = MusicTimeline(C), False
    else:
        timing, has_audio = load_timing(C)
        T = Timeline(C, timing)
    out = a.out or os.path.dirname(C.path(getattr(spec, "OUT", "out/story.mp4")))
    os.makedirs(out, exist_ok=True)

    srt_write([Cue(s["start"], s["end"], s["en"] or "", s["zh"] or "") for s in T.subs],
              os.path.join(out, "subtitles.srt"), which="both")
    json.dump([Cue(s["start"], s["end"], clean(s["zh"]), clean(s["en"])).to_dict() for s in T.subs],
              open(os.path.join(out, "cues.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

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
    pl = publish.platform_name(post.get("platform") or (C.prof.name if C.prof is not None else None))
    cap = publish.XHS_CHAPTER_LABEL_MAX if pl in ("xiaohongshu", "xhs") else None
    chapters = []
    if len(C.SECTIONS) > 1:
        for s, name in enumerate(C.SECTIONS):
            en = C.SECTIONS_EN[s] if s < len(C.SECTIONS_EN) else ""
            lab = f"{name} {en}" if en and en != name else name
            chapters.append((T.sec_bounds[s], lab if not cap or len(lab) <= cap else name))
    body = "\n\n".join(p for p in (post.get("intro"), post.get("outro")) if p)
    text = publish.post_body(None, body, chapters=chapters, tags=post.get("tags"), platform=pl,
                             title=post.get("title", C.TITLE_ZH or C.TITLE_EN), **tag_args(post))
    open(os.path.join(out, "post.md"), "w", encoding="utf-8").write(text)

    if not a.no_voice and has_audio:
        with tempfile.TemporaryDirectory() as tmp:
            vo = place_voice(C, T, 0.0, T.total, os.path.join(tmp, "voice.wav"))
            vn = os.path.join(tmp, "voice_n.wav")
            audio.normalize_stem(vo, vn)
            media.run(["ffmpeg", "-y", "-i", vn, "-c:a", "libmp3lame", "-b:a", "160k", os.path.join(out, "voice.mp3")])
    elif not a.no_voice:
        print("! no timing.json - skipped voice.mp3 (timestamps above are estimates)")
    cp = check_profile(C)
    for w in (vplat.check_length(cp, T.total) if cp is not None else []):
        print("!", w)
    print(f"export -> {out}: subtitles.srt cues.json transcript.md post.md" + (" voice.mp3" if has_audio and not a.no_voice else ""),
          f"({len(T.subs)} cues)")


if __name__ == "__main__":
    main()
