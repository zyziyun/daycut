#!/usr/bin/env python3
"""Step 8b: split the cut into N episodes at chapter-card boundaries, one portrait cover per
episode, and write <out>/发布包.md (full-video + per-episode post copy).

Episodes (config.episodes):
  items: [{"chapters": [first, last], "title": .., "big1": .., "big2": .., "sub": .., "shot_src": s}]
         chapter numbers are 1-based card indexes; episode 1 always starts at 0 (keeps the hook)
  count: N        auto-split into N parts of similar length at card boundaries (if no items)
  max_minutes: 15 warn when an episode exceeds the platform cap (小红书 regular video ~15 min)
  series: "..."   eyebrow on each cover: "<series> · n/N"
No items and no count -> only 发布包.md for the full video.

Publish copy (config.publish): title, body, tags, errata_line, short_labels {chapter title: label}.
Tags = persona publish.tags + publish.tags. 小红书 chapter labels are capped at 14 chars and
titles are checked with vstudio.config.xhs_len against persona platforms.xiaohongshu.title_max.

Usage: python3 make_episodes.py work/config.py [--no-video]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image, ImageDraw

import _lfc
import make_cover as MC
from vstudio.config import persona, xhs_len


def extra(ap):
    ap.add_argument("--no-video", action="store_true", help="covers + 发布包 only, skip slicing")


cfg, args = _lfc.load(description=__doc__, extra=extra)
P = _lfc.palette(cfg)
ff = _lfc.ffmpeg_bin()
timeline = _lfc.load_json("timeline.json")
total = _lfc.total_duration(timeline)
cards = _lfc.chapters_from_timeline(timeline)  # [(final_t, title)]
src = os.path.join(cfg.out, "final_subbed.mp4")
if not os.path.exists(src):
    src = os.path.join(cfg.out, "final.mp4")
xdir = os.path.join(cfg.out, "episodes")
pers = persona()
XHS_MAX = pers.get("platforms", {}).get("xiaohongshu", {}).get("title_max", 20)
LABEL_MAX = cfg.get("publish.label_max", 14)
short = cfg.get("publish.short_labels", {}) or {}

# ---- episode ranges (final seconds)
items = cfg.get("episodes.items") or []
count = cfg.get("episodes.count")
if not items and count and len(cards) >= count:
    target = total / count
    starts = [1]
    for k in range(1, count):
        goal = target * k
        best = min(range(2, len(cards) + 1), key=lambda c: abs(cards[c - 1][0] - goal))
        starts.append(max(best, starts[-1] + 1))
    items = [{"chapters": [s, (starts[i + 1] - 1) if i + 1 < len(starts) else len(cards)]}
             for i, s in enumerate(starts)]
if count and not items:
    print(f"episodes.count={count} but only {len(cards)} chapter cards; no episodes split")
eps = []
for i, it in enumerate(items):
    first, last = it["chapters"]
    a = 0.0 if i == 0 else cards[first - 1][0]
    b = cards[last][0] if last < len(cards) else None
    eps.append({**it, "n": i + 1, "a": a, "b": b})


def ep_cover(ep, shot, N):
    W, H = 1080, 1440
    im = Image.new("RGB", (W, H), P["bg"])
    d = ImageDraw.Draw(im)
    series = cfg.get("episodes.series", "")
    d.text((84, 130), f"{series} · {ep['n']}/{N}" if series else f"{ep['n']}/{N}",
           font=_lfc.font(40, True), fill=P["accent"])
    if ep.get("big1"):
        d.text((80, 300), ep["big1"], font=_lfc.font(108, True), fill=P["ink"])
    if ep.get("big2"):
        d.text((80, 440), ep["big2"], font=_lfc.font(132, True), fill=P["accent"])
    if ep.get("sub"):
        d.text((84, 660), ep["sub"], font=_lfc.font(46, True), fill=(225, 225, 228))
    fr = MC.framed(shot, 900, P, -3)
    im.paste(fr, (W - fr.width + 120, H - fr.height + 60), fr)
    return im


def chapter_lines(a, b, cap=None):
    out = [] if a > 0 else ["00:00 开场"]
    for t, title in cards:
        if t >= a and (b is None or t < b):
            label = short.get(title, title)
            if cap and len(label) > cap:
                print(f"WARN chapter label > {cap} chars, set publish.short_labels: {label}")
                label = label[:cap]
            out.append(f"{_lfc.mmss(t - a)} {label}")
    if out and not out[0].startswith("00:00"):
        out.insert(0, "00:00 开场")
    return out


if eps:
    os.makedirs(xdir, exist_ok=True)
for ep in eps:
    n = ep["n"]
    dur = (ep["b"] or total) - ep["a"]
    if dur > cfg.get("episodes.max_minutes", 15) * 60:
        print(f"WARN ep{n} is {dur/60:.1f} min (> episodes.max_minutes)")
    if not args.no_video:
        cmd = [ff, "-y", "-v", "error", "-ss", f"{ep['a']:.3f}"] + (["-to", f"{ep['b']:.3f}"] if ep["b"] else [])
        _lfc.run(cmd + ["-i", src, *_lfc.video_encoder(cfg), "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", os.path.join(xdir, f"ep{n}.mp4")])
    t_shot = _lfc.map_src(timeline, ep["shot_src"], "fwd") if ep.get("shot_src") is not None else \
        ep["a"] + min(60.0, dur / 2)
    shot = MC.shot_at(cfg, t_shot, "ep_shot.png")
    ep_cover(ep, shot, len(eps)).save(os.path.join(xdir, f"ep{n}_cover.png"))
    print(f"ep{n}: {_lfc.mmss(ep['a'])}-{_lfc.mmss(ep['b'] or total)}  {ep.get('title', '')}")

# ---- 发布包.md
tags = list(pers.get("publish", {}).get("tags", [])) + list(cfg.get("publish.tags", []))
tagline = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)
errata = cfg.get("publish.errata_line", "")
chapter_intro = pers.get("publish", {}).get("chapter_line", "")
L = ["# 发布包", "", "## 完整版 (YouTube / B站)", "", f"**标题**: {cfg.get('publish.title', '')}", "",
     cfg.get("publish.body", ""), "", chapter_intro, *chapter_lines(0, None), ""]
if errata:
    L += [errata, ""]
L += [tagline, "", f"文件: final_subbed.mp4 · 字幕: subs.srt · 封面: cover_16x9.png / cover_3x4.png", ""]
for ep in eps:
    title = ep.get("title", "")
    if title and xhs_len(title) > XHS_MAX:
        print(f"WARN ep{ep['n']} title length {xhs_len(title)} > {XHS_MAX}: {title}")
    L += [f"## 第 {ep['n']}/{len(eps)} 集 (小红书)", "", f"**标题**: {title}", "",
          ep.get("body", ""), "", chapter_intro, *chapter_lines(ep["a"], ep["b"], LABEL_MAX), ""]
    if errata and (ep.get("errata", False)):
        L += [errata, ""]
    L += [tagline, "", f"文件: episodes/ep{ep['n']}.mp4 · 封面: episodes/ep{ep['n']}_cover.png", ""]
p = os.path.join(cfg.out, "发布包.md")
open(p, "w", encoding="utf-8").write("\n".join(L))
print(p)
