#!/usr/bin/env python3
"""Generate placeholder media so examples/demo_spec.py renders without any private photos.

    python3 make_demo_assets.py [--out examples/]   -> my_photos/*.jpg  (+ my_clips/clip1.mp4 if ffmpeg exists)

Images are procedural "paintings": gradient sky, hills, sun, a figure-ish triangle, a frame and a
big number, in mixed aspect ratios (portrait / landscape / square). 'sketch*' variants are the
line-art "draft" of the matching 'final*' image for the split (draft|final) shot.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import math
import os
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PALETTES = [
    ((32, 54, 92), (236, 170, 110), (60, 90, 60)),
    ((90, 30, 40), (250, 210, 140), (110, 70, 40)),
    ((20, 70, 80), (200, 230, 220), (40, 110, 90)),
    ((60, 40, 90), (240, 190, 200), (70, 60, 110)),
    ((100, 80, 40), (250, 240, 200), (140, 110, 60)),
    ((30, 30, 30), (220, 220, 210), (90, 90, 90)),
]
SIZES = [(1600, 2000), (2000, 1400), (1600, 1600), (1400, 2100), (2200, 1300), (1700, 2200)]


def _font(size):
    try:
        from vstudio.config import font
        return ImageFont.truetype(font("serif-italic"), size)
    except Exception:
        return ImageFont.load_default()


def painting(i, w, h):
    sky, sun, ground = PALETTES[i % len(PALETTES)]
    y = np.linspace(0, 1, h)[:, None, None]
    top = np.array(sky, np.float32)
    bot = np.array(sun, np.float32) * 0.8 + top * 0.2
    arr = np.broadcast_to(top * (1 - y) + bot * y, (h, w, 3)).copy()
    im = Image.fromarray(arr.astype(np.uint8))
    d = ImageDraw.Draw(im)
    r = min(w, h) * 0.12
    sx, sy = w * (0.25 + 0.5 * ((i * 37) % 10) / 10), h * 0.3
    d.ellipse((sx - r, sy - r, sx + r, sy + r), fill=sun)
    pts = [(0, h)] + [(x, h * (0.62 + 0.06 * math.sin(x / w * 6 + i))) for x in range(0, w + 40, 40)] + [(w, h)]
    d.polygon(pts, fill=ground)
    cx = w * (0.4 + 0.2 * ((i * 13) % 5) / 5)
    d.polygon([(cx, h * 0.38), (cx - w * 0.16, h * 0.86), (cx + w * 0.16, h * 0.86)],
              fill=tuple(int(c * 0.5) for c in sky))
    d.ellipse((cx - w * 0.05, h * 0.3, cx + w * 0.05, h * 0.3 + w * 0.1), fill=(232, 206, 180))
    for k in range(40):                 # texture strokes
        x0, y0 = (k * 97 + i * 31) % w, (k * 53 + i * 71) % h
        d.line((x0, y0, x0 + 60, y0 + 18), fill=tuple(min(255, c + 25) for c in ground), width=3)
    b = int(min(w, h) * 0.025)
    d.rectangle((b, b, w - b, h - b), outline=(30, 24, 18), width=b // 2)
    d.text((w * 0.06, h * 0.05), f"{i + 1:02d}", font=_font(int(min(w, h) * 0.12)), fill=(250, 244, 230))
    return im.filter(ImageFilter.SMOOTH)


def sketch_of(im):
    g = np.asarray(im.convert("L")).astype(np.float32)
    blur = np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(6))).astype(np.float32)
    edge = np.clip(255 - np.abs(g - blur) * 6, 0, 255)
    paper = np.array([238, 228, 206], np.float32)
    return Image.fromarray((edge[..., None] / 255 * paper).astype(np.uint8))


def make_clip(path, seconds=6, fps=30, w=1280, h=720):
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found - skipping the demo clip")
        return
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                          "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", path],
                         stdin=subprocess.PIPE)
    base = painting(4, w, h)
    for f in range(seconds * fps):
        t = f / fps
        im = base.copy()
        d = ImageDraw.Draw(im)
        x = int((t / seconds) * (w + 200)) - 100
        d.ellipse((x - 60, h * 0.45 - 60, x + 60, h * 0.45 + 60), fill=(250, 240, 220))
        d.text((40, h - 90), f"clip  {t:4.1f}s", font=_font(54), fill=(255, 255, 255))
        p.stdin.write(np.asarray(im).tobytes())
    p.stdin.close()
    p.wait()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)), help="folder receiving my_photos/ my_clips/")
    a = ap.parse_args()
    pdir, vdir = os.path.join(a.out, "my_photos"), os.path.join(a.out, "my_clips")
    os.makedirs(pdir, exist_ok=True)
    os.makedirs(vdir, exist_ok=True)
    for i in range(12):
        w, h = SIZES[i % len(SIZES)]
        painting(i, w, h).convert("RGB").save(os.path.join(pdir, f"photo{i + 1:02d}.jpg"), quality=88)
    fin = painting(20, 1600, 1600)
    fin.save(os.path.join(pdir, "final1.jpg"), quality=88)
    sketch_of(fin).save(os.path.join(pdir, "sketch1.jpg"), quality=88)
    make_clip(os.path.join(vdir, "clip1.mp4"))
    print("demo assets ->", pdir, vdir)


if __name__ == "__main__":
    main()
