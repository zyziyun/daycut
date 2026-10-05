#!/usr/bin/env python3
"""Upscale cheap draft takes (e.g. Seedance 480p 样片) to the delivery size locally instead of paying for an upgrade.

    python3 upscale.py takes/u02_v1.mp4 takes/u02_v1_1080.mp4                         # ffmpeg lanczos + grain
    python3 upscale.py takes/u02_v1.mp4 out.mp4 --weights ~/models/realesr-general-x4v3.pth   # Real-ESRGAN mix

Sessions: upgrading drafts in the web UI cost ~7x the draft price (~64 vs ~9 credits/s), so the drafts were
upscaled locally. Pure ESRGAN gives plastic skin; the kept recipe blends 60 % ESRGAN with 40 % bicubic and adds
light temporal grain (keeps pores/freckles). Weights: Real-ESRGAN realesr-general-x4v3 (BSD-3-Clause, download
yourself; not shipped). Needs torch for --weights; without it the ffmpeg path runs anywhere.
"""
import argparse
import os
import subprocess
import sys

import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio import media  # noqa: E402


def ffmpeg_upscale(src, dst, w=1080, h=1920, fps=30, grain=4):
    vf = (f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},"
          f"unsharp=5:5:0.4:5:5:0.0,noise=alls={grain}:allf=t,setsar=1")
    media.run(["ffmpeg", "-y", "-i", src, "-vf", vf, "-map", "0:v", "-map", "0:a?", "-c:v", "libx264", "-crf", "14",
               "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", dst])
    return dst


def esrgan_upscale(src, dst, weights, w=1080, h=1920, fps=30, mix=0.6, grain=4):
    import numpy as np
    import torch
    import torch.nn.functional as F
    from torch import nn

    class SRVGGNetCompact(nn.Module):          # Real-ESRGAN compact architecture (weights keys body.N)
        def __init__(self, num_feat=64, num_conv=32, upscale=4):
            super().__init__()
            self.upscale = upscale
            body = [nn.Conv2d(3, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
            for _ in range(num_conv):
                body += [nn.Conv2d(num_feat, num_feat, 3, 1, 1), nn.PReLU(num_parameters=num_feat)]
            body += [nn.Conv2d(num_feat, 3 * upscale * upscale, 3, 1, 1)]
            self.body = nn.ModuleList(body)
            self.upsampler = nn.PixelShuffle(upscale)

        def forward(self, x):
            out = x
            for layer in self.body:
                out = layer(out)
            return self.upsampler(out) + F.interpolate(x, scale_factor=self.upscale, mode="nearest")

    dev = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
    half = dev != "cpu"
    m = SRVGGNetCompact()
    sd = torch.load(os.path.expanduser(weights), map_location="cpu")
    m.load_state_dict(sd.get("params", sd))
    m = m.eval().to(dev)
    m = m.half() if half else m
    info = media.probe(src)
    wi, hi = info["w"], info["h"]
    tmp = dst + ".video.mp4"
    dec = subprocess.Popen([media.ffmpeg_bin(), "-v", "error", "-i", src, "-vf", f"fps={fps}", "-f", "rawvideo",
                            "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    enc = subprocess.Popen([media.ffmpeg_bin(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                            "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-vf", f"noise=alls={grain}:allf=t",
                            "-c:v", "libx264", "-crf", "14", "-preset", "medium", "-pix_fmt", "yuv420p", tmp],
                           stdin=subprocess.PIPE)
    fb = wi * hi * 3
    with torch.no_grad():
        while True:
            buf = dec.stdout.read(fb)
            if len(buf) < fb:
                break
            x = torch.from_numpy(np.frombuffer(buf, np.uint8).reshape(hi, wi, 3).copy()).to(dev)
            x = x.permute(2, 0, 1)[None].float() / 255.0
            y = m(x.half() if half else x).float()
            y = F.interpolate(y, size=(h, w), mode="bicubic", antialias=True)   # aspect: caller passes matching w/h
            base = F.interpolate(x, size=(h, w), mode="bicubic")
            y = (mix * y + (1 - mix) * base).clamp_(0, 1)
            enc.stdin.write((y[0].permute(1, 2, 0) * 255).round().byte().cpu().numpy().tobytes())
    enc.stdin.close()
    enc.wait()
    dec.wait()
    media.run(["ffmpeg", "-y", "-i", tmp, "-i", src, "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy",
               "-shortest", dst])
    os.remove(tmp)
    return dst


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--size", default="1080x1920")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--weights", help="realesr-general-x4v3.pth (optional; needs torch)")
    ap.add_argument("--mix", type=float, default=0.6, help="ESRGAN share (rest bicubic) - lower = less plastic")
    ap.add_argument("--grain", type=int, default=4)
    a = ap.parse_args(argv)
    w, h = map(int, a.size.lower().split("x"))
    if a.weights:
        esrgan_upscale(a.src, a.dst, a.weights, w, h, a.fps, a.mix, a.grain)
    else:
        ffmpeg_upscale(a.src, a.dst, w, h, a.fps, a.grain)
    print(a.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
