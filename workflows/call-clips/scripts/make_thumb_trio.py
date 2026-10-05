#!/usr/bin/env python3
"""1280x720 YouTube thumbnail for a three-person cut, lifted from the RENDERED
landscape video, so both guests are already masked and every tile is already
framed. Same conventions as make_thumb.py: headline owns the top ~45%, white
setup line + accent punch line with a heavy stroke, all speakers large along
the bottom, nothing under ~60px.

The still is chosen automatically: a moment with no node card and no 记笔记
panel on screen, near --at.

Usage:
  make_thumb_trio.py out/YT.mp4 --title-json work/YT.title.json --at 900 --out thumb.jpg
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import TEAL, YEL, WHITE, font

W, H = 1280, 720
ACCENTS = {"teal": TEAL, "yellow": YEL, "white": WHITE}
TILE_Y, TILE_H = 96, 720          # render_landscape_trio.py geometry


def clean_time(meta, at):
    """Nearest second to `at` with no card or panel overlapping the tiles."""
    busy = [(a - 1.4, a + 1.4) for a, _ in meta.get("node_cards", [])]
    busy += [(p[0] - 0.4, p[0] + p[1] + 0.4) for p in meta.get("panels", [])]
    for d in range(0, 600):
        for t in (at + d, at - d):
            if t > meta.get("hook_end", 0) + 2 and not any(a <= t <= b for a, b in busy):
                return t
    return at


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--at", type=float, default=900)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    meta = json.load(open(args.title_json))
    tb = meta["thumb"]
    accent = ACCENTS[tb.get("accent_color", "yellow")]

    t = clean_time(meta, args.at)
    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("could not read a still")

    # the three tiles, minus their bottom strip where the name chips sit
    band = fr[TILE_Y:TILE_Y + TILE_H - 60]
    band_h = int(H * 0.60)
    band = cv2.resize(band, (W, int(band.shape[0] * W / band.shape[1])), interpolation=cv2.INTER_AREA)
    top = max(0, int(band.shape[0] * 0.10))
    band = band[top:top + band_h]
    img = Image.new("RGB", (W, H), (8, 9, 12))
    img.paste(Image.fromarray(cv2.cvtColor(band, cv2.COLOR_BGR2RGB)), (0, H - band.shape[0]))

    px = np.array(img).astype(np.float32)
    y0 = H - band.shape[0]
    for k in range(170):
        px[y0 + k] *= 0.10 + 0.90 * k / 170
    yy, xx = np.mgrid[0:H, 0:W]
    v = 1 - 0.34 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    px *= np.clip(v, 0.55, 1)[:, :, None]
    img = Image.fromarray(np.clip(px, 0, 255).astype(np.uint8))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(glow).ellipse([-200, -260, 900, 380], fill=tuple(int(c * 0.28) for c in accent))
    img = Image.fromarray(np.clip(np.array(img).astype(np.int16) +
                                  np.array(glow.filter(ImageFilter.GaussianBlur(150))).astype(np.int16),
                                  0, 255).astype(np.uint8))

    d = ImageDraw.Draw(img)
    y = tb.get("y", 36)
    for line, is_acc in tb["lines"]:
        size = tb.get("size", 100)
        while size > 48 and d.textbbox((0, 0), line, font=font(size))[2] > W - 110:
            size -= 2
        f = font(size)
        d.text((56, y), line, font=f, fill=accent if is_acc else WHITE,
               stroke_width=9, stroke_fill=(0, 0, 0))
        y += int(size * 1.14)
    # role labels under each face, so "who is talking" reads at feed size
    labels = tb.get("labels") or []
    fl = font(30)
    for k, lab in enumerate(labels):
        cx = W * (2 * k + 1) / (2 * len(labels))
        wl = d.textbbox((0, 0), lab, font=fl)[2] + 40
        d.rounded_rectangle([cx - wl / 2, H - 62, cx + wl / 2, H - 14], radius=24,
                            fill=(0, 0, 0), outline=accent, width=3)
        d.text((cx - (wl - 40) / 2, H - 56), lab, font=fl, fill=WHITE)
    img.save(args.out, quality=95)
    print(f"-> {args.out}  (still at {t:.0f}s)")


if __name__ == "__main__":
    main()
