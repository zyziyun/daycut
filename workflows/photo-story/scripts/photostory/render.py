#!/usr/bin/env python3
"""Render a photo-story spec to MP4: picture box (shots + overlays + transitions + film look),
running header with section progress, chapter cards, bilingual subtitles, voice + music mix.

    python3 render.py spec.py --stills 3,12.5,40        # JPEG stills (1/3 size; --full = full size)
    python3 render.py spec.py --preview 20 --from 60    # 20 s preview from 60 s -> cache/preview.mp4
    python3 render.py spec.py                           # full render -> spec OUT
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import argparse
import os
import subprocess

import numpy as np
from PIL import Image

from vstudio.config import persona

from photostory import overlays as ov
from photostory.ctx import Ctx, load_spec
from photostory.looks import film_look
from photostory.shots import build, parse_src
from photostory.subtitles import Header, make_chapter, make_label, make_sub, sub_backdrop
from photostory.timeline import Timeline, load_timing
from photostory.transitions import transition
from photostory.util import paste_rgba


def prepare(spec_path):
    spec = load_spec(spec_path)
    C = Ctx(spec)
    timing, has_audio = load_timing(C)
    T = Timeline(C, timing)
    return C, T, has_audio


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="story spec .py (paths inside are relative to its folder)")
    ap.add_argument("--preview", type=float, help="render only this many seconds")
    ap.add_argument("--from", dest="t_from", type=float, default=0.0, help="start time (s)")
    ap.add_argument("--stills", help="comma-separated times (s): write JPEG stills instead of a video")
    ap.add_argument("--full", action="store_true", help="stills at full canvas size (default 1/3)")
    ap.add_argument("--stills-dir", default=None, help="where stills go (default <spec dir>/stills)")
    ap.add_argument("--out", default=None, help="output mp4 (default spec OUT, or cache/preview.mp4 for --preview)")
    a = ap.parse_args()

    C, T, has_audio = prepare(a.spec)
    print(f"canvas {C.W}x{C.H}, header {C.HDR}, box {C.BOX_W}x{C.BOX_H}, subs {C.SUB_H}"
          f"{' (overlaid)' if C.overlay_subs else ''} | {T.summary()}")
    total = T.total
    t_from = a.t_from
    end_t = min(total, t_from + a.preview) if a.preview else total

    header = Header(C)
    chapters = {s: make_chapter(C, s) for s in range(1, len(C.SECTIONS))}
    for s in T.subs:
        s["_lay"] = make_sub(C, s["en"], s["zh"])
    for sh in T.shots:
        if "label" in sh and not sh["src"].startswith("split:"):
            sh["_lab"] = make_label(C, sh["label"])
        sh["_video"] = parse_src(C, sh["src"])[0] == "video"
    backdrop = sub_backdrop(C) if C.overlay_subs else None
    chap_len = float(getattr(C.spec, "CHAPTER_CARD", 2.2) or 0)
    end_fade = T.pace["end_fade"]

    stills = [float(x) for x in a.stills.split(",")] if a.stills else None
    enc = None
    vid_tmp = os.path.join(C.cache_dir, "video_fx.mp4")
    if stills:
        sdir = a.stills_dir or C.path("stills")
        os.makedirs(sdir, exist_ok=True)
        frames = [int(t * C.FPS) for t in stills]
    else:
        crf = str((persona().get("export") or {}).get("crf", 18))
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{C.W}x{C.H}",
                                "-r", str(C.FPS), "-i", "-", "-c:v", "libx264", "-crf", crf, "-preset", "medium",
                                "-profile:v", "high", "-pix_fmt", "yuv420p", vid_tmp], stdin=subprocess.PIPE)
        frames = range(int(t_from * C.FPS), int(end_t * C.FPS))

    live, shots = {}, T.shots
    for fi in frames:
        gt = fi / C.FPS
        need = [k for k, sh in enumerate(shots) if sh["start"] <= gt < sh["end"] + sh["tail"]] or [len(shots) - 1]
        for k in list(live):
            if k not in need:
                del live[k]
        for k in need:
            if k not in live:
                live[k] = build(C, shots[k], k)
        k = max(need)                                  # current shot = the latest one that started
        sh = shots[k]
        N = live[k].frame(gt - sh["start"])
        N = ov.overlays(C, sh, N.copy() if sh["_video"] else N, gt - sh["start"])
        if k - 1 in live and gt - sh["start"] < sh["trd"]:
            pv = shots[k - 1]
            P = live[k - 1].frame(gt - pv["start"])
            P = ov.overlays(C, pv, P.copy() if pv["_video"] else P, gt - pv["start"])
            box = transition(C, P, N, (gt - sh["start"]) / sh["trd"], sh["tr"])
        else:
            box = N.copy()
        sec = T.section_at(gt)
        box = film_look(C, box, gt, sec in C.FILM_SECTIONS or sh["src"].startswith("film:"))
        if "_lab" in sh:                               # picture label, bottom-left
            la = min(1, (gt - sh["start"] - 0.45) / 0.3, (sh["end"] - gt) / 0.3)
            if la > 0:
                m = C.b(44)
                lab_y = C.BOX_H - m - sh["_lab"].shape[0] - (C.SUB_H if C.overlay_subs else 0)
                paste_rgba(box, sh["_lab"], m, lab_y, la)
        if chap_len and sec >= 1 and gt - T.sec_bounds[sec] < chap_len:     # chapter card
            lt = gt - T.sec_bounds[sec]
            paste_rgba(box, chapters[sec], 0, 0, min(1, lt / 0.3, (chap_len - lt) / 0.45))
        frame = C.BG.copy()
        frame[C.HDR:C.HDR + C.BOX_H] = box
        header.draw(frame, sec, gt, T.sec_bounds)
        cue = [s for s in T.subs if s["start"] <= gt < s["end"]]
        if cue and backdrop is not None:
            paste_rgba(frame, backdrop, 0, C.SUB_Y0)
        for s in cue:
            paste_rgba(frame, s["_lay"], 0, C.SUB_Y0, min(1, (gt - s["start"]) / 0.1))
        if gt > total - end_fade:
            frame *= max(0, (total - gt) / end_fade)
        img = np.clip(frame, 0, 255).astype(np.uint8)
        if stills:
            im = Image.fromarray(img)
            if not a.full:
                im = im.resize((C.W // 3, C.H // 3), Image.LANCZOS)
            p = os.path.join(sdir, f"st_{gt:06.1f}.jpg")
            im.save(p, quality=90)
            print("still", p)
            continue
        enc.stdin.write(img.tobytes())
        if fi % (C.FPS * 30) == 0:
            print(f"  {gt:6.1f}s / {end_t:.1f}s", flush=True)
    if stills:
        return
    enc.stdin.close()
    enc.wait()
    out = a.out or (os.path.join(C.cache_dir, "preview.mp4") if a.preview else C.path(getattr(C.spec, "OUT", "out/story.mp4")))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    mix_audio(C, T, t_from, end_t, vid_tmp, out)


def mix_audio(C, T, t0, t1, vid, out):
    """Voice units placed on the timeline + looping music bed at BGM_VOLUME, then loudnorm."""
    P = persona()
    lufs = (P.get("audio") or {}).get("loudness_lufs", -14)
    abr = getattr(C.spec, "AUDIO_BITRATE", None) or (P.get("export") or {}).get("audio_bitrate", "192k")
    dur = t1 - t0
    ins, flt, n = [], [], 0
    for u in T.units:
        if not u["path"] or u["start"] >= t1 or u["start"] + u["dur"] <= t0:
            continue
        ins += ["-i", C.path(u["path"])]
        ms = int((u["start"] - t0) * 1000)
        trim = f"atrim=start={-ms / 1000:.3f}," if ms < 0 else ""
        flt.append(f"[{n + 1}:a]aresample=48000,{trim}asetpts=PTS-STARTPTS,adelay={max(ms, 0)}|{max(ms, 0)},apad[a{n}]")
        n += 1
    bgm = C.path(getattr(C.spec, "BGM", None))
    if bgm and not os.path.exists(bgm):
        print(f"! BGM not found: {bgm} - rendering without music")
        bgm = None
    vol = getattr(C.spec, "BGM_VOLUME", 0.12)
    labels = []
    if n:
        flt.append("".join(f"[a{k}]" for k in range(n)) + f"amix=inputs={n}:normalize=0,atrim=0:{dur:.2f}[vo]")
        labels.append("[vo]")
    if bgm:
        ins += ["-i", bgm]
        flt.append(f"[{n + 1}:a]aresample=48000,aloop=loop=-1:size=2e9,atrim={t0:.2f}:{t1:.2f},asetpts=PTS-STARTPTS,"
                   f"volume={vol},afade=t=in:d=2,afade=t=out:st={max(0, dur - 3.5):.2f}:d=3.5[bg]")
        labels.append("[bg]")
    if not labels:
        ins += ["-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]
        flt.append("[1:a]anull[aout]")
    else:
        mix = f"amix=inputs={len(labels)}:normalize=0," if len(labels) > 1 else ""
        flt.append("".join(labels) + f"{mix}loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", vid, *ins, "-filter_complex", ";".join(flt),
                    "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", str(abr), "-ar", "48000",
                    "-movflags", "+faststart", "-shortest", out], check=True)
    print("output:", out)


if __name__ == "__main__":
    main()
