#!/usr/bin/env python3
"""Step 8a: covers from config.cover -> <out>/cover_16x9.png (1920x1080, YouTube/B站)
and <out>/cover_3x4.png (1080x1440, 小红书 portrait; shows as 4:3 crop in feeds).

Dark ground + accent, big readable text, a framed + slightly tilted screenshot of the cut.
The screenshot comes from <out>/final.mp4 at cover.shot_src (SOURCE seconds, mapped through
timeline.json) or cover.shot_final (final seconds). Copy keys (all optional):

  cover.wide: {eyebrow, big1, big2, sub_lines: [..], chips: [..]}
  cover.tall: {eyebrow, hook: [l1, l2], big1, big2, sub, chips: [..]}

Keep cover copy honest to the content (what the video actually teaches).
Usage: python3 make_cover.py work/config.py [--only wide|tall]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image, ImageDraw

import _lfc


def shot_at(cfg, t_final, png, video=None):
    video = video or os.path.join(cfg.out, "final.mp4")
    _lfc.run([_lfc.ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{t_final:.2f}", "-i", video,
              "-frames:v", "1", png])
    im = Image.open(png).convert("RGB")
    m = int(round(32 * im.height / 1080))  # strip the render pad margin
    return im.crop((m, m, im.width - m, im.height - m))


def framed(shot, box_w, P, tilt):
    sh = shot.resize((box_w, int(box_w * shot.height / shot.width)), Image.LANCZOS)
    fr = Image.new("RGBA", (sh.width + 24, sh.height + 24), (0, 0, 0, 0))
    ImageDraw.Draw(fr).rounded_rectangle([0, 0, fr.width - 1, fr.height - 1], radius=20,
                                         fill=(255, 255, 255, 255), outline=P["accent"] + (255,), width=6)
    fr.paste(sh, (12, 12))
    return fr.rotate(tilt, expand=True, resample=Image.BICUBIC)


def chips_row(d, chips, y, fnt, W=None, x=None, pad=44):
    widths = [d.textlength(c, font=fnt) + pad for c in chips]
    if x is None:
        x = (W - sum(widths) - 18 * (len(chips) - 1)) / 2
    h = fnt.size + 26
    for c, cw in zip(chips, widths):
        d.rounded_rectangle([x, y, x + cw, y + h], radius=h // 2, outline=(92, 92, 98), width=2)
        d.text((x + pad / 2, y + 11), c, font=fnt, fill=(192, 192, 197))
        x += cw + 18


def resolve_shot_time(cfg, timeline, src_key="cover.shot_src", final_key="cover.shot_final"):
    if cfg.get(final_key) is not None:
        return float(cfg.get(final_key))
    if cfg.get(src_key) is not None:
        t = _lfc.map_src(timeline, float(cfg.get(src_key)), "fwd")
        if t is not None:
            return t
    return _lfc.total_duration(timeline) * 0.3


def wide(cfg, shot, P):
    c = cfg.get("cover.wide", {}) or {}
    W, H = 1920, 1080
    im = Image.new("RGB", (W, H), P["bg"])
    fr = framed(shot, 1016, P, -3)
    im.paste(fr, (W - fr.width + 130, H - fr.height + 80), fr)
    d = ImageDraw.Draw(im)
    if c.get("eyebrow"):
        d.text((110, 130), c["eyebrow"], font=_lfc.font(44, True), fill=P["accent"])
    if c.get("big1"):
        d.text((104, 220), c["big1"], font=_lfc.font(150, True), fill=P["ink"])
    if c.get("big2"):
        d.text((104, 410), c["big2"], font=_lfc.font(190, True), fill=P["accent"])
    for i, line in enumerate(c.get("sub_lines", [])[:2]):
        d.text((110, 700 + 100 * i), line, font=_lfc.font(60, True), fill=(235, 235, 235))
    if c.get("chips"):
        chips_row(d, c["chips"], 930, _lfc.font(30), x=110)
    return im


def tall(cfg, shot, P, c=None, W=1080, H=1440):
    c = c if c is not None else (cfg.get("cover.tall", {}) or {})
    im = Image.new("RGB", (W, H), P["bg"])
    d = ImageDraw.Draw(im)

    def center(text, y, fnt, fill):
        d.text(((W - d.textlength(text, font=fnt)) / 2, y), text, font=fnt, fill=fill)

    if c.get("eyebrow"):
        center(c["eyebrow"], 110, _lfc.font(46, True), P["accent"])
    for i, line in enumerate(c.get("hook", [])[:2]):
        center(line, 250 + 72 * i, _lfc.font(58), (220, 220, 224))
    if c.get("big1"):
        center(c["big1"], 470, _lfc.font(96, True), P["ink"])
    if c.get("big2"):
        center(c["big2"], 600, _lfc.font(150, True), P["accent"])
    if c.get("sub"):
        center(c["sub"], 800, _lfc.font(50, True), (235, 235, 235))
    fr = framed(shot, 860, P, -2.5)
    im.paste(fr, ((W - fr.width) // 2, 905), fr)
    if c.get("chips"):
        chips_row(d, c["chips"], 1372, _lfc.font(34), W=W, pad=50)
    return im


def main():
    def extra(ap):
        ap.add_argument("--only", choices=["wide", "tall"])
    cfg, args = _lfc.load(description=__doc__, extra=extra)
    P = _lfc.palette(cfg)
    timeline = _lfc.load_json("timeline.json")
    shot = shot_at(cfg, resolve_shot_time(cfg, timeline), "cover_shot.png")
    if args.only in (None, "wide"):
        p = os.path.join(cfg.out, "cover_16x9.png")
        wide(cfg, shot, P).save(p)
        print(p)
    if args.only in (None, "tall"):
        p = os.path.join(cfg.out, "cover_3x4.png")
        tall(cfg, shot, P).save(p)
        print(p)


if __name__ == "__main__":
    main()
