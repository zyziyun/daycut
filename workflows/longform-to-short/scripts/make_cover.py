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

Platform targets (config targets / platform, or --targets): when set explicitly, every extra cover aspect a
target needs is written too (vstudio.platform.cover_size), e.g. cover_9x16.png (1080x1920) for 抖音 / TikTok /
Shorts. cover_16x9 + cover_3x4 are always written; `python -m vstudio.export --cover ...` re-fits the closest
aspect to each platform's exact size (YouTube 1280x720, B站 1146x717, ...).
Usage: python3 make_cover.py work/config.py [--only wide|tall] [--targets xiaohongshu:full,douyin]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image, ImageDraw

import _lfc
from vstudio import cover, media
from vstudio import platform as PF

ASPECTS = {"16x9": (1920, 1080), "3x4": (1080, 1440), "9x16": (1080, 1920)}


def extra_cover_sizes(profiles, base=("16x9", "3x4")):
    """{name: (w, h)} of cover aspects the profiles need beyond ``base`` (nearest of 16:9 / 3:4 / 9:16;
    16:10 B站 covers are re-fitted from 16:9 by vstudio.export)."""
    import math
    out = {}
    for p in profiles:
        w, h = PF.cover_size(p)
        name = min(ASPECTS, key=lambda k: abs(math.log((w / h) / (ASPECTS[k][0] / ASPECTS[k][1]))))
        if name not in base:
            out[name] = ASPECTS[name]
    return out


def _fit(text, size, maxw):
    """Bold CJK font at ``size``, shrunk only when ``text`` would run past ``maxw`` px."""
    f = _lfc.font(size, True)
    if f.getlength(text) <= maxw:
        return f
    from vstudio import draw
    return draw.fit_font(text, "cjk-bold", size, maxw, min_size=max(12, size // 3))


def episode_cover(cfg, ep, shot, N, size=(1080, 1440)):
    """Portrait episode cover: '<series> · n/N' eyebrow (ep["eyebrow"] overrides), big1 / big2 / sub (shrunk to
    fit the width when too long), framed screenshot bottom-right.
    1080x1440 is the original layout; taller canvases (9:16) keep the text block and push the shot down."""
    P = _lfc.palette(cfg)
    W, H = size
    k = W / 1080.0
    im = Image.new("RGB", (W, H), P["bg"])
    d = ImageDraw.Draw(im)
    y0 = int((H - 1440 * k) * 0.45)          # 0 at 3:4; centres the 3:4 block on taller covers
    series = cfg.get("episodes.series", "")
    eyebrow = ep.get("eyebrow") or (f"{series} · {ep['n']}/{N}" if series else f"{ep['n']}/{N}")
    d.text((int(84 * k), y0 + int(130 * k)), eyebrow, font=_fit(eyebrow, int(40 * k), W - int(168 * k)),
           fill=P["accent"])
    if ep.get("big1"):
        d.text((int(80 * k), y0 + int(300 * k)), ep["big1"], font=_fit(ep["big1"], int(108 * k), W - int(160 * k)),
               fill=P["ink"])
    if ep.get("big2"):
        d.text((int(80 * k), y0 + int(440 * k)), ep["big2"], font=_fit(ep["big2"], int(132 * k), W - int(160 * k)),
               fill=P["accent"])
    if ep.get("sub"):
        d.text((int(84 * k), y0 + int(660 * k)), ep["sub"], font=_fit(ep["sub"], int(46 * k), W - int(168 * k)),
               fill=(225, 225, 228))
    fr = cover.framed(shot, int(900 * k), -3, P["accent"])
    im.paste(fr, (W - fr.width + int(120 * k), H - fr.height + int(60 * k)), fr)
    return im


def wide_episode_cover(cfg, ep, shot, N, size=(1920, 1080)):
    """16:9 episode cover (vstudio.cover.framed_cover wide layout) from the episode copy."""
    P = _lfc.palette(cfg)
    series = cfg.get("episodes.series", "")
    copy = {"eyebrow": f"{series} · {ep['n']}/{N}" if series else f"{ep['n']}/{N}",
            "big1": ep.get("big1", ""), "big2": ep.get("big2", ""), "sub_lines": [ep["sub"]] if ep.get("sub") else []}
    return cover.framed_cover(shot, copy, size=size, accent=P["accent"], ground=P["bg"])


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
        ap.add_argument("--targets", "--platform", dest="targets", default=None,
                        help="comma list of platform targets (overrides config targets/platform)")
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
    profs, explicit = _lfc.targets(cfg, args.targets)
    if explicit and args.only in (None, "tall"):
        for name, size in extra_cover_sizes(profs).items():
            p = os.path.join(cfg.out, f"cover_{name}.png")
            cover.framed_cover(shot, cfg.get("cover.tall", {}) or {}, size=size,
                               accent=P["accent"], ground=P["bg"]).save(p)
            print(p)


if __name__ == "__main__":
    main()
