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
import json
import re
import shutil
import subprocess
import tempfile
from fractions import Fraction

from vstudio.config import persona

BT709 = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]


def run(cmd, capture=False):
    print("  $ " + " ".join(str(c) for c in cmd[:6]) + (" ..." if len(cmd) > 6 else ""), flush=True)
    r = subprocess.run([str(c) for c in cmd], capture_output=capture, text=True)
    if r.returncode != 0:
        if capture:
            sys.stderr.write(r.stderr[-3000:])
        raise SystemExit(f"ffmpeg failed ({r.returncode})")
    return r


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    if v is None:
        raise SystemExit(f"{path}: no video stream")
    fps = Fraction(v.get("avg_frame_rate") or v.get("r_frame_rate") or "30/1")
    if fps == 0:
        fps = Fraction(v.get("r_frame_rate", "30/1"))
    vbr = int(v.get("bit_rate") or 0)
    if not vbr and d["format"].get("bit_rate"):
        vbr = int(d["format"]["bit_rate"]) - int((a or {}).get("bit_rate") or 192000)
    return dict(w=int(v["width"]), h=int(v["height"]), fps=fps, vbr=max(vbr, 0), vcodec=v["codec_name"],
                has_audio=a is not None, duration=float(d["format"].get("duration") or 0))


def venc_args(info, args):
    if args.crf is not None or not info["vbr"]:
        crf = args.crf if args.crf is not None else persona().get("export", {}).get("crf", 18)
        q = ["-crf", str(crf)]
    else:
        br = info["vbr"] if args.bitrate == "match" else int(float(args.bitrate.rstrip("Mm")) * 1e6)
        q = ["-b:v", str(br), "-maxrate", str(int(br * 1.15)), "-bufsize", str(br * 2)]
    return ["-c:v", "libx264", "-preset", args.preset, *q, "-pix_fmt", "yuv420p", *BT709]


def atempo_chain(s):
    parts = []
    while s > 2.0:
        parts.append(2.0); s /= 2.0
    while s < 0.5:
        parts.append(0.5); s /= 0.5
    parts.append(s)
    return ",".join(f"atempo={p:.6g}" for p in parts)


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
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", t, "-i", cover, "-i", src,
           "-filter_complex", fc, "-map", "[v]"]
    cmd += (["-map", "1:a", "-c:a", "copy"] if info["has_audio"] else [])
    run(cmd + venc_args(info, args) + [out])


def step_speed(src, out, s, info, args):
    fc = f"[0:v]setpts=PTS/{s}[v]" + (f";[0:a]{atempo_chain(s)}[a]" if info["has_audio"] else "")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-filter_complex", fc, "-map", "[v]"]
    # keep audio lossless-ish until loudnorm; PCM in MOV avoids a lossy generation
    cmd += (["-map", "[a]", "-c:a", "pcm_s24le"] if info["has_audio"] else [])
    run(cmd + venc_args(info, args) + [out])


def measure(path, lufs, tp, lra):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af",
                        f"loudnorm=I={lufs}:TP={tp}:LRA={lra}:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    if not m:
        raise SystemExit("loudnorm measurement failed:\n" + r.stderr[-1500:])
    return json.loads(m.group(0))


def step_loudness(src, out, args, lufs):
    m = measure(src, lufs, args.tp, args.lra)
    print(f"  measured: I={m['input_i']} LUFS  TP={m['input_tp']} dBTP  LRA={m['input_lra']}")
    if args.skip_if_close and abs(float(m["input_i"]) - lufs) <= 1.0 and float(m["input_tp"]) <= args.tp + 0.5:
        print("  already within 1 LU of target; copying audio as AAC without gain change")
        af = "anull"
    else:
        af = (f"loudnorm=I={lufs}:TP={args.tp}:LRA={args.lra}:measured_I={m['input_i']}:"
              f"measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
              f"offset={m['target_offset']}:linear=true:print_format=summary")
    ab = persona().get("export", {}).get("audio_bitrate", "192k")
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-map", "0:v", "-map", "0:a", "-c:v", "copy",
         "-af", f"{af},aresample=48000", "-c:a", "aac", "-b:a", ab, out])


def step_finalize(src, out, vcodec):
    bsf = {"h264": "h264_metadata", "hevc": "hevc_metadata"}.get(vcodec)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-map", "0:v", "-map", "0:a?", "-c", "copy"]
    if str(src).endswith(".mov"):  # speed step left PCM audio (loudnorm skipped): encode it for MP4
        cmd += ["-c:a", "aac", "-b:a", persona().get("export", {}).get("audio_bitrate", "192k")]
    if bsf:
        cmd += ["-bsf:v", f"{bsf}=colour_primaries=1:transfer_characteristics=1:matrix_coefficients=1"]
    run(cmd + BT709 + ["-movflags", "+faststart", out])


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

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not found on PATH")
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
    cur, vcodec = pathlib.Path(args.src), info["vcodec"]
    try:
        if args.cover:
            print(">>> 1/4 cover")
            nxt = work / "01_cover.mp4"; step_cover(cur, args.cover, nxt, info, args); cur, vcodec = nxt, "h264"
        if abs(speed - 1.0) > 1e-6:
            print(f">>> 2/4 speed x{speed}")
            nxt = work / "02_speed.mov"; step_speed(cur, nxt, speed, info, args); cur, vcodec = nxt, "h264"
        if info["has_audio"] and not args.no_loudnorm:
            print(f">>> 3/4 loudnorm -> {lufs} LUFS (two-pass)")
            nxt = work / "03_loud.mp4"; step_loudness(cur, nxt, args, lufs); cur = nxt
        print(">>> 4/4 bt709 tags + faststart")
        step_finalize(cur, args.out, vcodec)
    finally:
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)

    fin = probe(args.out)
    print(f"\ndone: {args.out}\n  {fin['w']}x{fin['h']} @ {float(fin['fps']):.3f} fps, {fin['vbr'] / 1e6:.1f} Mbps, "
          f"{fin['duration']:.2f}s (expected ~{info['duration'] / speed:.2f}s)")
    if fin["has_audio"]:
        m = measure(args.out, lufs, args.tp, args.lra)
        print(f"  loudness: I={m['input_i']} LUFS  TP={m['input_tp']} dBTP")
    if args.check:
        png = pathlib.Path(args.out).with_suffix(".first.png")
        run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.3", "-i", args.out, "-frames:v", "1", png])
        print(f"  first frame: {png}")


if __name__ == "__main__":
    main()
