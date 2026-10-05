#!/usr/bin/env python3
"""Cover for one clip: black + accent, oversized headline, and a still from the
clip itself so the thumbnail is not a dead black frame.

Default: the original 1080x1920 design. ``--platform`` sizes it for that profile's cover
(小红书 3:4 1080x1440, 抖音 / Shorts 1080x1920 ...): headline inside the cover's title-safe rect
(and the feed crop), the clip's tile band (auto-detected) under it at its own aspect.
``--size canvas`` (or an explicit ``:full`` orientation, e.g. ``xiaohongshu:full``) makes a cover the
size of the platform's VIDEO canvas instead (9:16 1080x1920, headline in the safe box), for a
first-frame / 9:16 cover; ``--size profile`` (default for a bare name) keeps the profile cover size.

Usage:
  make_cover.py out/<id>.mp4 --title-json work/<id>.title.json --at 12 --out out/<id>.cover.jpg [--platform xiaohongshu]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import TEAL, DIM, WHITE, font, frame_at
import layout
from vstudio import platform as P
from vstudio.draw import text_width

W, H = 1080, 1920


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--at", type=float, default=6.0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--platform", default=None, help="cover profile, e.g. xiaohongshu, douyin, youtube-shorts")
    ap.add_argument("--size", default=None, choices=["profile", "canvas"],
                    help="profile = the platform's cover size (小红书 3:4); canvas = the video canvas "
                         "(9:16 1080x1920). Default: canvas for an explicit ':full', else profile")
    args = ap.parse_args()

    meta = json.load(open(args.title_json))

    fr = frame_at(args.clip, args.at)
    prof = layout.cover_profile(args.platform, "vertical")
    if prof is not None:
        size = args.size or ("canvas" if args.platform.strip().lower().endswith(":full") else "profile")
        return platform_cover(fr, meta, prof, args.out, canvas=size == "canvas")

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
    while size > 56 and max(sum(text_width(r[0], font(size)) for r in ln) for ln in lines) > W - 144:
        size -= 2
    f_t = font(size)
    y = meta.get("cover_title_y", 176)
    for ln in lines:
        x = 72
        for txt, acc in ln:
            d.text((x, y), txt, font=f_t, fill=TEAL if acc else WHITE)
            x += text_width(txt, f_t)
        y += int(f_t.size * 1.28)

    if meta.get("accent"):
        d.rectangle([72, y + 34, 72 + 110, y + 40], fill=TEAL)
        d.text((72, y + 76), meta["accent"], font=font(38), fill=DIM)

    if meta.get("cover_footer"):
        d.text((72, H - 130), meta["cover_footer"], font=font(34), fill=DIM)

    img.save(args.out, quality=95)
    print(f"-> {args.out}")


def tile_band(fr, max_gap=24):
    """Rows of the clip frame that carry the tiles: the longest run where most of the row is
    picture (headline and caption rows are mostly black); thin gaps between tile rows are bridged."""
    lit = np.flatnonzero((fr.max(axis=2) > 24).mean(axis=1) > 0.3)
    if not len(lit):
        return 0, fr.shape[0]
    runs, start = [], lit[0]
    for p, q in zip(lit, lit[1:]):
        if q - p > max_gap:
            runs.append((start, p + 1)); start = q
    runs.append((start, lit[-1] + 1))
    return max(runs, key=lambda r: r[1] - r[0])


def cover_geometry(prof, canvas=False):
    """(W, H, title-safe rect) of the cover: the profile's cover, or (canvas=True) the video canvas
    with its UI-free safe box (a 9:16 cover for 小红书 / any vertical platform)."""
    if canvas:
        return prof.w, prof.h, tuple(P.safe_box(prof))
    W, H = P.cover_size(prof)
    return W, H, tuple(P.cover_title_safe(prof))


def platform_cover(fr, meta, prof, out, canvas=False):
    W, H, (x0, y0, x1, y1) = cover_geometry(prof, canvas)
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    lines = meta["title"]
    xl = max(72, x0 + 12)
    size = 96 if max(sum(len(r[0]) for r in ln) for ln in lines) <= 9 else 82
    while size > 48 and max(sum(text_width(r[0], font(size)) for r in ln) for ln in lines) > x1 - 12 - xl:
        size -= 2
    f_t = font(size)
    y = meta.get("cover_title_y") or y0 + 40
    for ln in lines:
        x = xl
        for txt, acc in ln:
            d.text((x, y), txt, font=f_t, fill=TEAL if acc else WHITE)
            x += text_width(txt, f_t)
        y += int(f_t.size * 1.28)
    if meta.get("accent"):
        d.rectangle([xl, y + 34, xl + 110, y + 40], fill=TEAL)
        d.text((xl, y + 70), meta["accent"], font=font(38), fill=DIM)
        y += 130
    b0, b1 = meta.get("cover_band") or tile_band(fr)
    strip = Image.fromarray(cv2.cvtColor(fr[b0:b1], cv2.COLOR_BGR2RGB))
    strip = strip.resize((W, max(1, int(strip.height * W / strip.width))), Image.LANCZOS)
    sy = int(meta.get("cover_strip_y") or y + 40)
    room = H - sy
    if strip.height > room:                      # keep the top of the band (the masked guests' row)
        strip = strip.crop((0, 0, W, room))
    img.paste(strip, (0, sy))
    px = np.array(img).astype(np.float32)
    for k in range(min(160, strip.height)):
        px[sy + k] *= k / 160.0
    img = Image.fromarray(px.astype(np.uint8))
    if meta.get("cover_footer"):
        ImageDraw.Draw(img).text((xl, min(H - 130, y1 - 50)), meta["cover_footer"], font=font(34), fill=DIM)
    img.save(out, quality=95)
    print(f"-> {out} ({prof.key} {'canvas' if canvas else 'cover'} {W}x{H})")


if __name__ == "__main__":
    main()
