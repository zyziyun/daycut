#!/usr/bin/env python3
"""Polish any exported edit (Descript, CapCut/剪映, Premiere, Resolve, Final Cut...) for publishing.

Steps (each its own ffmpeg call, intermediates kept with --keep so you can inspect any stage):
  1. cover    replace the first N seconds of picture with a still cover (audio untouched, length kept)
  2. speed    optional pitch-preserved speed-up (setpts + atempo chain)
  3. loudness two-pass loudnorm to persona.audio.loudness_lufs (measure, then linear apply)
  4. finalize bt709 colour tags + faststart (stream copy; tags via h264/hevc_metadata bsf)

Resolution and frame rate always follow the source. Re-encodes target the source bitrate
(platforms re-encode anyway; you only lose quality by going lower).

Usage:
  python3 polish.py export.mp4 -o final.mp4 [--cover cover.png] [--speed 1.2|body|hook]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import shutil
import tempfile

from vstudio import audio, media
from vstudio.config import persona


def run(cmd):
    print("  $ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""), flush=True)
    try:
        media.run(cmd)
    except media.FFmpegError as e:
        raise SystemExit(str(e))


def probe(path):
    """vstudio.media.probe + the two names this script uses (fps as a Fraction, vbr = video bps)."""
    info = media.probe(str(path))
    if not info["has_video"]:
        raise SystemExit(f"{path}: no video stream")
    info["fps"] = info["fps_q"] or 30
    info["vbr"] = info["vbitrate"]
    return info


def venc_args(info, args):
    if args.crf is not None or not info["vbr"]:
        crf = args.crf if args.crf is not None else persona().get("export", {}).get("crf", 18)
        q = ["-crf", str(crf)]
    else:
        br = info["vbr"] if args.bitrate == "match" else int(float(args.bitrate.rstrip("Mm")) * 1e6)
        q = ["-b:v", str(br), "-maxrate", str(int(br * 1.15)), "-bufsize", str(br * 2)]
    return ["-c:v", "libx264", "-preset", args.preset, *q, "-pix_fmt", "yuv420p", *media.BT709]


def resolve_speed(val):
    if val is None:
        return 1.0
    try:
        return float(val)
    except ValueError:
        sp = persona().get("speed", {})
        if val not in sp:
            raise SystemExit(f"--speed {val!r}: not a number and not a persona speed key ({', '.join(sp)})")
        return float(sp[val])


def step_cover(src, cover, out, info, args):
    w, h, fps, t = info["w"], info["h"], info["fps"], args.cover_sec
    fit = (f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}" if args.cover_fit == "fill"
           else f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black")
    fc = (f"[0:v]{fit},setsar=1,fps={fps},format=yuv420p[c];"
          f"[1:v]trim=start={t},setpts=PTS-STARTPTS,scale={w}:{h},setsar=1,fps={fps},format=yuv420p[r];"
          f"[c][r]concat=n=2:v=1:a=0[v]")
    cmd = ["ffmpeg", "-y", "-loop", "1", "-t", t, "-i", cover, "-i", src,
           "-filter_complex", fc, "-map", "[v]"]
    cmd += (["-map", "1:a", "-c:a", "copy"] if info["has_audio"] else [])
    run(cmd + venc_args(info, args) + [out])


def step_speed(src, out, s, info, args):
    fc = f"[0:v]setpts=PTS/{s}[v]" + (f";[0:a]{media.atempo_chain(s)}[a]" if info["has_audio"] else "")
    cmd = ["ffmpeg", "-y", "-i", src, "-filter_complex", fc, "-map", "[v]"]
    # keep audio lossless-ish until loudnorm; PCM in MOV avoids a lossy generation
    cmd += (["-map", "[a]", "-c:a", "pcm_s24le"] if info["has_audio"] else [])
    run(cmd + venc_args(info, args) + [out])


def step_loudness(src, out, args, lufs):
    """Two-pass linear loudnorm (vstudio.audio.loudnorm_2pass): 48 kHz stereo AAC, video stream-copied."""
    if args.skip_if_close:
        m = audio.measure_loudness(str(src), lufs, args.tp, args.lra)
        if abs(m["input_i"] - lufs) <= 1.0 and m["input_tp"] <= args.tp + 0.5:
            print(f"  measured: I={m['input_i']} LUFS  TP={m['input_tp']} dBTP - within 1 LU of target; "
                  "encoding audio as AAC without gain change")
            ab = persona().get("export", {}).get("audio_bitrate", "192k")
            run(["ffmpeg", "-y", "-i", src, "-map", "0:v", "-map", "0:a", "-c:v", "copy",
                 "-af", "aresample=48000", "-c:a", "aac", "-b:a", ab, out])
            return
    m = audio.loudnorm_2pass(str(src), str(out), lufs=lufs, tp=args.tp, lra=args.lra)
    print(f"  measured: I={m['input_i']} LUFS  TP={m['input_tp']} dBTP  LRA={m['input_lra']}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", help="exported edit (mp4/mov)")
    p.add_argument("-o", "--out", required=True, help="final mp4")
    p.add_argument("--cover", help="cover image (any size; fitted to the source frame)")
    p.add_argument("--cover-sec", default="1.0", help="seconds of picture the cover replaces (default 1.0)")
    p.add_argument("--cover-fit", choices=["fill", "fit"], default="fill", help="crop-to-fill or letterbox")
    p.add_argument("--speed", help="number (1.2) or a persona speed key (body, hook, fast_body...). Default 1.0")
    p.add_argument("--lufs", type=float, help="target integrated loudness (default persona audio.loudness_lufs)")
    p.add_argument("--tp", type=float, default=-1.5, help="true-peak ceiling dBTP (default -1.5)")
    p.add_argument("--lra", type=float, default=11, help="loudness range target (default 11, spoken word)")
    p.add_argument("--no-loudnorm", action="store_true")
    p.add_argument("--skip-if-close", action="store_true", help="leave gain alone if already within 1 LU")
    p.add_argument("--bitrate", default="match", help="'match' source video bitrate, or e.g. 28M")
    p.add_argument("--crf", type=int, help="use CRF instead of bitrate targeting")
    p.add_argument("--preset", default="slow")
    p.add_argument("--keep", metavar="DIR", help="keep intermediates (01_cover.mp4, 02_speed.mov, 03_loud.mp4) here")
    p.add_argument("--check", action="store_true", help="after writing, dump first frame next to the output")
    args = p.parse_args()

    try:
        media.ffmpeg_bin(); media.ffprobe_bin()
    except media.FFmpegError as e:
        raise SystemExit(str(e))
    lufs = args.lufs if args.lufs is not None else float(persona().get("audio", {}).get("loudness_lufs", -14))
    speed = resolve_speed(args.speed)
    cap = float(persona().get("speed", {}).get("cjk_max_intelligible", 1.4))
    if speed > cap:
        print(f"  warning: speed {speed} > persona speed.cjk_max_intelligible {cap}; speech may become hard to follow")

    info = probe(args.src)
    print(f"source: {info['w']}x{info['h']} @ {float(info['fps']):.3f} fps, {info['vbr'] / 1e6:.1f} Mbps, "
          f"{info['duration']:.2f}s, audio={'yes' if info['has_audio'] else 'no'}")

    work = pathlib.Path(args.keep) if args.keep else pathlib.Path(tempfile.mkdtemp(prefix="polish_"))
    work.mkdir(parents=True, exist_ok=True)
    cur = pathlib.Path(args.src)
    try:
        if args.cover:
            print(">>> 1/4 cover")
            nxt = work / "01_cover.mp4"; step_cover(cur, args.cover, nxt, info, args); cur = nxt
        if abs(speed - 1.0) > 1e-6:
            print(f">>> 2/4 speed x{speed}")
            nxt = work / "02_speed.mov"; step_speed(cur, nxt, speed, info, args); cur = nxt
        if info["has_audio"] and not args.no_loudnorm:
            print(f">>> 3/4 loudnorm -> {lufs} LUFS (two-pass)")
            nxt = work / "03_loud.mp4"; step_loudness(cur, nxt, args, lufs); cur = nxt
        print(">>> 4/4 bt709 tags + faststart")
        media.retag_bt709(str(cur), str(args.out))
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)

    fin = probe(args.out)
    print(f"\ndone: {args.out}\n  {fin['w']}x{fin['h']} @ {float(fin['fps']):.3f} fps, {fin['vbr'] / 1e6:.1f} Mbps, "
          f"{fin['duration']:.2f}s (expected ~{info['duration'] / speed:.2f}s)")
    if fin["has_audio"]:
        m = audio.measure_loudness(str(args.out), lufs, args.tp, args.lra)
        print(f"  loudness: I={m['input_i']} LUFS  TP={m['input_tp']} dBTP")
    if args.check:
        png = pathlib.Path(args.out).with_suffix(".first.png")
        media.grab_frame(str(args.out), 0.3, str(png))
        print(f"  first frame: {png}")


if __name__ == "__main__":
    main()
