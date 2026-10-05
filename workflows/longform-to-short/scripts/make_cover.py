#!/usr/bin/env python3
"""Step 8a: covers from config.cover -> <out>/cover_16x9.png (1920x1080, YouTube/B站)
and <out>/cover_3x4.png (1080x1440, 小红书 portrait; shows as 4:3 crop in feeds).

vstudio.cover.framed_cover: dark ground + accent, big readable text (auto-fit to width), a framed +
slightly tilted screenshot of the cut.
The screenshot comes from <out>/final.mp4 at cover.shot_src (SOURCE seconds, mapped through
timeline.json) or cover.shot_final (final seconds). Copy keys (all optional):

  cover.wide: {eyebrow, big1, big2, sub_lines: [..], chips: [..]}
  cover.tall: {eyebrow, hook: [l1, l2], big1, big2, sub, chips: [..]}

Keep cover copy honest to the content (what the video actually teaches).
Usage: python3 make_cover.py work/config.py [--only wide|tall]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image

import _lfc
from vstudio import cover, media


def shot_at(cfg, t_final, png, video=None):
    video = video or os.path.join(cfg.out, "final.mp4")
    media.grab_frame(video, t_final, png, preroll=5.0)
    im = Image.open(png).convert("RGB")
    m = int(round(32 * im.height / 1080))  # strip the render pad margin
    return im.crop((m, m, im.width - m, im.height - m))


def resolve_shot_time(cfg, timeline, src_key="cover.shot_src", final_key="cover.shot_final"):
    if cfg.get(final_key) is not None:
        return float(cfg.get(final_key))
    if cfg.get(src_key) is not None:
        t = _lfc.map_src(timeline, float(cfg.get(src_key)), "fwd")
        if t is not None:
            return t
    return _lfc.total_duration(timeline) * 0.3


def main():
    def extra(ap):
        ap.add_argument("--only", choices=["wide", "tall"])
    cfg, args = _lfc.load(description=__doc__, extra=extra)
    P = _lfc.palette(cfg)
    timeline = _lfc.load_json("timeline.json")
    shot = shot_at(cfg, resolve_shot_time(cfg, timeline), "cover_shot.png")
    for kind, size, name in (("wide", (1920, 1080), "cover_16x9.png"), ("tall", (1080, 1440), "cover_3x4.png")):
        if args.only in (None, kind):
            p = os.path.join(cfg.out, name)
            cover.framed_cover(shot, cfg.get(f"cover.{kind}", {}) or {}, size=size,
                               accent=P["accent"], ground=P["bg"]).save(p)
            print(p)


if __name__ == "__main__":
    main()
