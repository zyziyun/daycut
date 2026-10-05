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
import shutil
import subprocess

from vstudio import audio, media  # noqa: E402


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

    if a.skip_render:
        raw = a.src
    else:
        if not shutil.which("npx"):
            sys.exit("npx (Node) not found")
        os.makedirs(os.path.join(a.src, "renders"), exist_ok=True)
        raw = os.path.join(a.src, "renders", "_raw.mp4")
        subprocess.run(["npx", "hyperframes", "render", "--quality", a.quality, "--output", "renders/_raw.mp4"],
                       cwd=a.src, check=True)

    tmp = a.out[:-4] + ".loud.mp4"
    m = audio.loudnorm_2pass(raw, tmp, lufs=a.lufs, tp=tp)
    print(f"loudnorm: measured {m['input_i']:.1f} LUFS, TP {m['input_tp']:.1f}")
    media.retag_bt709(tmp, a.out)
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
