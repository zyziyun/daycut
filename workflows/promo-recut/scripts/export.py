#!/usr/bin/env python3
"""Render a promo-recut HyperFrames project and make it upload-ready:
HyperFrames render -> two-pass loudnorm to persona audio.loudness_lufs (default -14 LUFS, TP -1.5,
vstudio.audio.loudnorm_2pass, video stream-copied) -> BT.709 colour tags written into the H.264/HEVC
stream + container with no re-encode, +faststart (vstudio.media.retag_bt709).

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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 1)[1])
    ap.add_argument("src", help="HyperFrames project dir, or the rendered mp4 with --skip-render")
    ap.add_argument("out", help="delivery mp4")
    ap.add_argument("quality", nargs="?", default="delivery", choices=["draft", "looks", "delivery"],
                    help="hyperframes render --quality (default delivery)")
    ap.add_argument("--skip-render", action="store_true", help="src is an already rendered mp4: only deliver")
    ap.add_argument("--lufs", type=float, default=None, help="default persona audio.loudness_lufs (-14)")
    ap.add_argument("--platform", default=None,
                    help="take LUFS / true peak from a vstudio.platform profile (e.g. douyin, youtube) and check length")
    a = ap.parse_args()
    tp = -1.5
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
    try:
        m = audio.loudnorm_2pass(raw, tmp, lufs=a.lufs, tp=tp)
        print(f"loudnorm: measured {m['input_i']:.1f} LUFS, TP {m['input_tp']:.1f}")
        media.retag_bt709(tmp, a.out)
    except media.FFmpegError as e:
        fail(f"delivery (loudness / colour tags) failed: {proctail.clean_error(e)}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("->", a.out)
    info = media.probe(a.out)
    print({k: info[k] for k in ("vcodec", "w", "h", "fps", "duration", "primaries", "transfer", "acodec", "sample_rate")})
    after = audio.measure_loudness(a.out)
    print(f"delivered: {after['input_i']:.1f} LUFS integrated, true peak {after['input_tp']:.1f} dBTP")
    if a.platform:
        for w in PF.check_length(prof, info["duration"]):
            print("warning:", w)


if __name__ == "__main__":
    main()
