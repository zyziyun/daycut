#!/usr/bin/env python3
"""Lock the edit list, then build a caption-free master + cues from the FINAL audio.

    python3 assemble.py work/ai/timeline.yaml               # -> work/ai/master.mp4 + work/ai/cues.json
    python3 assemble.py work/ai/timeline.yaml --no-asr      # picture/sound only (captions later)
    python3 -m vstudio.export work/ai/master.mp4 --platforms douyin,tiktok,youtube-shorts \
        --cues work/ai/cues.json --cover douyin=work/cover-9x16.png --out exports/

timeline.yaml (templates/timeline.yaml): canvas, fps, takes_dir, edl: [{take, in, out, mute, gain, speed}
| {still, dur}], grade {saturation, grain}, music {path, duck_db, music_lufs}, captions {language, max_chars},
out. The EDL is the single source of truth: filenames, order and in/out points are taken literally.
Captions are rebuilt from what is actually spoken in the assembled master - never from the draft script.
"""
import argparse
import json
import os
import sys

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio import media  # noqa: E402


def load(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        t = yaml.safe_load(f) or {}
    base = os.path.dirname(os.path.abspath(path))
    t.setdefault("canvas", [1080, 1920])
    t.setdefault("fps", 30)
    t.setdefault("takes_dir", "takes")
    t.setdefault("out", "master.mp4")
    t["_dir"] = base
    return t


def _p(t, rel):
    return rel if os.path.isabs(rel) else os.path.join(t["_dir"], rel)


def validate_edl(t):
    """Literal checks before any render: files exist, in < out, out within the take."""
    errs = []
    for i, e in enumerate(t.get("edl") or []):
        if "still" in e:
            if not os.path.exists(_p(t, e["still"])):
                errs.append(f"#{i}: still {e['still']} missing")
            if float(e.get("dur", 0)) <= 0:
                errs.append(f"#{i}: still needs dur > 0")
            continue
        f = _p(t, os.path.join(t["takes_dir"], e["take"]))
        if not os.path.exists(f):
            errs.append(f"#{i}: take {e['take']} missing")
            continue
        a, b = float(e.get("in", 0)), e.get("out")
        d = media.duration(f)
        b = d if b is None else float(b)
        if b <= a:
            errs.append(f"#{i}: out {b} <= in {a}")
        if b > d + 0.05:
            errs.append(f"#{i}: out {b:.2f} beyond {e['take']} length {d:.2f}")
    if not t.get("edl"):
        errs.append("empty edl")
    return errs


def grade_chain(t):
    g = t.get("grade") or {}
    out = []
    if g.get("saturation", 1.0) != 1.0:
        out.append(f"eq=saturation={float(g['saturation']):.3f}")
    if g.get("grain"):
        out.append(f"noise=alls={int(g['grain'])}:allf=t")
    return out


def segment_cmd(t, e, dst):
    W, H = t["canvas"]
    fps = t["fps"]
    vf = [f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={W}:{H}", "setsar=1",
          f"fps={fps}"] + grade_chain(t)
    if "still" in e:
        dur = float(e["dur"])
        return ["ffmpeg", "-y", "-loop", "1", "-t", f"{dur:.3f}", "-i", _p(t, e["still"]),
                "-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", ",".join(vf), "-map", "0:v", "-map", "1:a", "-shortest",
                "-c:v", "libx264", "-crf", "14", "-preset", "fast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", dst]
    src = _p(t, os.path.join(t["takes_dir"], e["take"]))
    a = float(e.get("in", 0))
    b = e.get("out")
    sp = float(e.get("speed", 1.0))
    info = media.probe(src)
    b = info["duration"] if b is None else float(b)
    dur = (b - a) / sp
    if sp != 1.0:
        vf.insert(0, f"setpts=PTS/{sp}")
    cmd = ["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", src]
    mute = e.get("mute") or not info["has_audio"]
    if mute:
        cmd += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
    af = ["aresample=48000"]
    if sp != 1.0:
        af.append(media.atempo_chain(sp))
    if e.get("gain"):
        af.append(f"volume={float(e['gain'])}dB")
    cmd += ["-vf", ",".join(vf), "-map", "0:v:0", "-map", "1:a:0" if mute else "0:a:0"]
    if not mute:
        cmd += ["-af", ",".join(x for x in af if x)]
    cmd += ["-t", f"{dur:.3f}", "-c:v", "libx264", "-crf", "14", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-ac", "2", dst]
    return cmd


def assemble(t, asr=True, out=print):
    errs = validate_edl(t)
    if errs:
        raise SystemExit("EDL errors:\n  " + "\n  ".join(errs))
    work = _p(t, t.get("work", "assemble_work"))
    os.makedirs(work, exist_ok=True)
    parts = []
    for i, e in enumerate(t["edl"]):
        dst = os.path.join(work, f"seg{i:03d}.mp4")
        media.run(segment_cmd(t, e, dst))
        parts.append(dst)
    lst = os.path.join(work, "concat.txt")
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in parts)
    joined = os.path.join(work, "joined.mp4")
    media.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", joined])
    master = _p(t, t["out"])
    mus = t.get("music") or {}
    if mus.get("path"):
        from vstudio import audio
        mix = os.path.join(work, "mix.wav")
        audio.mix_bed(joined, _p(t, mus["path"]), mix, duck_db=float(mus.get("duck_db", -10.0)),
                      music_lufs=mus.get("music_lufs"), carve=bool(mus.get("carve", True)))
        media.run(["ffmpeg", "-y", "-i", joined, "-i", mix, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "256k", "-ar", "48000", master])
    else:
        media.run(["ffmpeg", "-y", "-i", joined, "-c", "copy", "-movflags", "+faststart", master])
    out(f"master: {master} ({media.duration(master):.2f}s)")
    res = {"master": master}
    if asr:
        res["cues"] = captions(t, master, out=out)
    out("next: python3 -m vstudio.export " + os.path.relpath(master) + " --platforms <list> "
        + (f"--cues {os.path.relpath(res['cues'])} " if res.get("cues") else "") + "--out exports/")
    return res


def captions(t, master, out=print):
    from vstudio import asr as A
    from vstudio import subs as S
    cap = t.get("captions") or {}
    tr = A.transcribe(master, language=cap.get("language"))
    cues = S.cues_from_words(A.words_of(tr), max_chars=cap.get("max_chars"))
    path = _p(t, cap.get("out", "cues.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cues": [c.to_dict() for c in cues], "size": list(t["canvas"])}, f, ensure_ascii=False, indent=1)
    out(f"cues: {path} ({len(cues)} cues from the final audio - proofread names/terms before export)")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("timeline")
    ap.add_argument("--no-asr", action="store_true")
    ap.add_argument("--check", action="store_true", help="validate the EDL only")
    a = ap.parse_args(argv)
    t = load(a.timeline)
    if a.check:
        errs = validate_edl(t)
        print("\n".join(errs) or "EDL ok")
        return 1 if errs else 0
    assemble(t, asr=not a.no_asr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
