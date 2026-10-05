#!/usr/bin/env python3
"""1080x1920 cover for one clip: black + accent, oversized headline, and a
still from the clip itself so the thumbnail is not a dead black frame.

Usage:
  make_cover.py out/<id>.mp4 --title-json work/<id>.title.json --at 12 --out out/<id>.cover.jpg
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import TEAL, DIM, WHITE, font

W, H = 1080, 1920


def tw(d, s, f):
    return d.textbbox((0, 0), s, font=f)[2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--at", type=float, default=6.0)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    meta = json.load(open(args.title_json))

    cap = cv2.VideoCapture(args.clip)
    cap.set(cv2.CAP_PROP_POS_MSEC, args.at * 1000)
    ok, fr = cap.read()
    cap.release()
    if not ok:
        raise SystemExit("could not read a still from the clip")

    img = Image.new("RGB", (W, H), (0, 0, 0))

    # the two speaker tiles, lifted straight out of the finished vertical clip
    y0, y1 = meta.get("cover_band", [330, 1575])
    strip = Image.fromarray(cv2.cvtColor(fr[y0:y1, 0:W], cv2.COLOR_BGR2RGB))
    strip = strip.resize((W, int(strip.height * 0.78)), Image.LANCZOS)
    strip_y = meta.get("cover_strip_y", 664)
    img.paste(strip, (0, strip_y))

    # fade the top of the still into the black headline block
    px = np.array(img).astype(np.float32)
    for k in range(180):
        y = strip_y + k
        px[y] *= k / 180.0
    img = Image.fromarray(px.astype(np.uint8))

    d = ImageDraw.Draw(img)

    lines = meta["title"]
    size = 96 if max(sum(len(r[0]) for r in ln) for ln in lines) <= 9 else 82
    # shrink until the widest line fits inside the side margins
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    while size > 56 and max(sum(tw(probe, r[0], font(size)) for r in ln) for ln in lines) > W - 144:
        size -= 2
    f_t = font(size)
    y = meta.get("cover_title_y", 176)
    for ln in lines:
        x = 72
        for txt, acc in ln:
            d.text((x, y), txt, font=f_t, fill=TEAL if acc else WHITE)
            x += tw(d, txt, f_t)
        y += int(f_t.size * 1.28)

    if meta.get("accent"):
        d.rectangle([72, y + 34, 72 + 110, y + 40], fill=TEAL)
        d.text((72, y + 76), meta["accent"], font=font(38), fill=DIM)

    if meta.get("cover_footer"):
        d.text((72, H - 130), meta["cover_footer"], font=font(34), fill=DIM)

    img.save(args.out, quality=95)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
