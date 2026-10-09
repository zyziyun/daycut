#!/usr/bin/env python3
"""Render a promo-recut HyperFrames project and make it upload-ready:
HyperFrames render -> two-pass loudnorm to persona audio.loudness_lufs (default -14 LUFS, TP -1.5,
vstudio.audio.loudnorm_2pass, video stream-copied) -> BT.709 colour tags written into the H.264/HEVC
stream + container with no re-encode, +faststart (vstudio.media.retag_bt709). The delivered size is reported.

Bitrate: without libx264 (the bundled LGPL ffmpeg) HyperFrames encodes with h264_videotoolbox at ~15 Mbps
(900 MB for 8 min 1080p). A render more than 25 % over the delivery target (vstudio.platform.delivery_bitrate:
the --platform profile, else 8 Mbps at 1080p30, scaled by resolution / fps) has its video re-encoded to the
target first (vstudio.media.delivery_args hw_bitrate; libx264 keeps CRF capped at the target). --keep-bitrate skips it.

  python3 $VSTUDIO/workflows/promo-recut/scripts/export.py promo my-promo.mp4 [--quality delivery]
  python3 $VSTUDIO/workflows/promo-recut/scripts/export.py --skip-render promo/renders/raw.mp4 my-promo.mp4
(export.sh in this folder is a shell entry point with the same arguments.)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import os
import subprocess

from vstudio import audio, media, node, proctail  # noqa: E402


def fail(msg):
    """Exit 1 with a short, readable reason on stderr (no traceback: the stage error keeps the real cause)."""
    print(f"error: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def render(proj, quality):
    """``npx hyperframes render`` on a Node that works (vstudio.node), with the same ffmpeg as the delivery steps.
    Interactive: progress goes to the terminal. Otherwise (the desk / batch runner) the full output goes to
    renders/hyperframes.log and only meaningful lines are echoed, so a failure keeps its real reason."""
    os.makedirs(os.path.join(proj, "renders"), exist_ok=True)
    raw = os.path.join(proj, "renders", "_raw.mp4")
    if os.path.exists(raw):
        os.remove(raw)                    # a stale render must not pass for this one
    try:
        env = node.child_env(extra_dirs=[d for d in [media.ffmpeg_dir()] if d])
        cmd = node.npx(os.environ.get("VSTUDIO_HYPERFRAMES") or "hyperframes", "render", "--quality", quality,
                       "--output", "renders/_raw.mp4", env=env)
    except node.NodeError as e:
        fail(str(e))
    if sys.stdout.isatty():
        rc, out = subprocess.run(cmd, cwd=proj, env=env).returncode, ""
    else:
        log_path = os.path.join(proj, "renders", "hyperframes.log")
        buf = []
        with open(log_path, "w", encoding="utf-8") as log:
            p = subprocess.Popen(cmd, cwd=proj, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 stdin=subprocess.DEVNULL, text=True, errors="replace")
            for ln in p.stdout:
                log.write(ln)
                buf.append(ln)
                del buf[:-400]
                for clean in proctail.lines(ln):
                    if not proctail.is_noise(clean):
                        print(clean, file=sys.stderr, flush=True)
            rc = p.wait()
        out = "".join(buf)
    if rc != 0:
        fail(f"hyperframes render failed (exit {rc}):\n{proctail.tail(out) or '(no output)'}")
    if not os.path.exists(raw):
        fail(f"hyperframes render finished but wrote no {raw}:\n{proctail.tail(out)}")
    return raw


def video_bitrate(info, path):
    """Average video bitrate (bps) of a probed file: the stream's bit_rate, else the file size over its duration."""
    if info.get("vbitrate"):
        return int(info["vbitrate"])
    dur = info.get("duration") or 0
    return int(os.path.getsize(path) * 8 / dur) if dur else 0


def fit_bitrate(raw, out, prof=None, slack=1.25):
    """Re-encode the video of ``raw`` to the delivery bitrate when it is more than ``slack`` over it (audio
    copied). Returns (path to use, target bps, the raw's bps); ``raw`` itself when it is already small enough."""
    from vstudio import platform as PF
    info = media.probe(raw)
    target = PF.delivery_bitrate(prof, info["w"], info["h"], info.get("fps") or 30)
    have = video_bitrate(info, raw)
    if not have or have <= target * slack:
        return raw, target, have
    enc = (prof.encode if prof is not None else {}) or {}
    print(f"bitrate: render is {have / 1e6:.1f} Mbps, delivery target {target / 1e6:.1f} Mbps: re-encoding the video",
          flush=True)
    args = media.delivery_args(crf=enc.get("crf"), audio=None, faststart=False, hw_bitrate=target,
                               maxrate=int(target * 1.5), bufsize=int(target * 3))     # libx264: CRF under that cap
    media.run(["ffmpeg", "-y", "-i", raw, "-map", "0:v:0", "-map", "0:a?", "-c:a", "copy", *args, out])
    return out, target, have


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 1)[1])
    ap.add_argument("src", help="HyperFrames project dir, or the rendered mp4 with --skip-render")
    ap.add_argument("out", help="delivery mp4")
    ap.add_argument("quality", nargs="?", default="delivery", choices=["draft", "looks", "delivery"],
                    help="hyperframes render --quality (default delivery)")
    ap.add_argument("--skip-render", action="store_true", help="src is an already rendered mp4: only deliver")
    ap.add_argument("--lufs", type=float, default=None, help="default persona audio.loudness_lufs (-14)")
    ap.add_argument("--keep-bitrate", action="store_true", help="never re-encode the render to the delivery bitrate")
    ap.add_argument("--platform", default=None,
                    help="take LUFS / true peak from a vstudio.platform profile (e.g. douyin, youtube) and check length")
    a = ap.parse_args()
    tp, prof = -1.5, None
    if a.platform:
        from vstudio import platform as PF
        prof = PF.profile(a.platform)
        a.lufs = a.lufs if a.lufs is not None else prof.loudness["lufs"]
        tp = prof.loudness.get("tp", tp)

    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)   # out/ does not exist on a fresh project: ffmpeg cannot create it
    raw = a.src if a.skip_render else render(a.src, a.quality)
    if not os.path.exists(raw):
        fail(f"no rendered video at {raw}")

    tmp = os.path.splitext(a.out)[0] + ".loud.mp4"
    fit = os.path.splitext(a.out)[0] + ".rate.mp4"
    try:
        src, target = raw, None
        if not a.keep_bitrate:
            src, target, _ = fit_bitrate(raw, fit, prof)
        m = audio.loudnorm_2pass(src, tmp, lufs=a.lufs, tp=tp)
        print(f"loudnorm: measured {m['input_i']:.1f} LUFS, TP {m['input_tp']:.1f}")
        media.retag_bt709(tmp, a.out)
    except media.FFmpegError as e:
        fail(f"delivery (loudness / colour tags) failed: {proctail.clean_error(e)}")
    finally:
        for f in (tmp, fit):
            if os.path.exists(f):
                os.remove(f)
    print("->", a.out)
    info = media.probe(a.out)
    print({k: info[k] for k in ("vcodec", "w", "h", "fps", "duration", "primaries", "transfer", "acodec", "sample_rate")})
    size = os.path.getsize(a.out)
    print(f"size: {size / 1e6:.1f} MB, video {video_bitrate(info, a.out) / 1e6:.1f} Mbps"
          + (f" (target {target / 1e6:.1f} Mbps)" if target else ""))
    lim = ((prof.extra.get("limits") or {}).get("max_bytes") if prof is not None else None)
    if lim and size > lim:
        print(f"warning: {size / 1e6:.0f} MB is over the {prof.name} upload cap ({lim / 1e6:.0f} MB)")
    after = audio.measure_loudness(a.out)
    print(f"delivered: {after['input_i']:.1f} LUFS integrated, true peak {after['input_tp']:.1f} dBTP")
    if a.platform:
        for w in PF.check_length(prof, info["duration"]):
            print("warning:", w)


if __name__ == "__main__":
    main()
