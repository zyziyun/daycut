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
Tags = publish.tags + persona publish.tags (vstudio.publish.hashtags, de-duplicated). Chapter lines come from
vstudio.publish.chapter_lines; 小红书 labels are capped at publish.label_max (14) chars and titles are checked
with vstudio.publish.check_title against persona platforms.xiaohongshu.title_max.

Platform checks: every episode against the episode targets (episodes.targets, else the short-form targets of
config targets / platform: 小红书, 抖音, TikTok, Shorts) and the full cut against the long-form ones (YouTube,
B站): vstudio.platform.check_length (sweet spot / max) + check_text (title) -> WARN lines and
<out>/platform_checks.json. With explicit targets each episode also gets ep{N}_cover_<aspect>.png for every
other cover aspect those targets need. Vertical slices of the episodes: make_vertical.py.

Usage: python3 make_episodes.py work/config.py [--no-video] [--targets xiaohongshu:vertical,youtube]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import _lfc
import make_cover as MC
from vstudio import media, publish
from vstudio import platform as PF
from vstudio.config import persona


def extra(ap):
    ap.add_argument("--no-video", action="store_true", help="covers + 发布包 only, skip slicing")
    ap.add_argument("--targets", "--platform", dest="targets", default=None,
                    help="comma list of platform targets (overrides config targets/platform), e.g. xiaohongshu:vertical,youtube")


cfg, args = _lfc.load(description=__doc__, extra=extra)
timeline = _lfc.load_json("timeline.json")
total = _lfc.total_duration(timeline)
cards = _lfc.chapters_from_timeline(timeline)  # [(final_t, title)]
src = os.path.join(cfg.out, "final_subbed.mp4")
if not os.path.exists(src):
    src = os.path.join(cfg.out, "final.mp4")
xdir = os.path.join(cfg.out, "episodes")
pers = persona()
LABEL_MAX = cfg.get("publish.label_max", 14)
short = cfg.get("publish.short_labels", {}) or {}

# ---- episode ranges (final seconds)
eps = _lfc.episode_ranges(cfg, timeline)
profs, explicit = _lfc.targets(cfg, args.targets)
ep_profs = _lfc.episode_targets(cfg, profs)
checks = {"targets": [p.key for p in profs], "explicit": explicit, "full": {}, "episodes": []}


def ep_cover(ep, shot, N, size=(1080, 1440)):
    return MC.episode_cover(cfg, ep, shot, N, size)


def chapter_lines(a, b, cap=None):
    """'MM:SS label' lines for final-time window [a, b) (episode-relative), 00:00 always first."""
    return publish.chapter_lines([(t, short.get(title, title)) for t, title in cards], offset=a, end=b, cap=cap,
                                 platform="youtube" if cap is None else "xiaohongshu",
                                 warn=lambda m: print("WARN", m))


if eps:
    os.makedirs(xdir, exist_ok=True)
for ep in eps:
    n = ep["n"]
    dur = (ep["b"] or total) - ep["a"]
    if dur > cfg.get("episodes.max_minutes", 15) * 60:
        print(f"WARN ep{n} is {dur/60:.1f} min (> episodes.max_minutes)")
    ew = {}
    for p in ep_profs:
        w = PF.check_length(p, dur) + (PF.check_text(p, title=ep["title"]) if ep.get("title") else [])
        for m in w:
            print(f"WARN ep{n} {p.key}: {m}")
        ew[p.key] = w
    checks["episodes"].append({"n": n, "a": round(ep["a"], 3), "b": round(ep["b"] or total, 3),
                               "duration": round(dur, 3), "warnings": ew})
    if not args.no_video:
        cmd = ["ffmpeg", "-y", "-ss", f"{ep['a']:.3f}"] + (["-to", f"{ep['b']:.3f}"] if ep["b"] else [])
        media.run(cmd + ["-i", src, *_lfc.video_encoder(cfg), "-c:a", "aac", "-b:a", "160k",
                        "-movflags", "+faststart", os.path.join(xdir, f"ep{n}.mp4")])
    t_shot = _lfc.map_src(timeline, ep["shot_src"], "fwd") if ep.get("shot_src") is not None else \
        ep["a"] + min(60.0, dur / 2)
    shot = MC.shot_at(cfg, t_shot, "ep_shot.png")
    ep_cover(ep, shot, len(eps)).save(os.path.join(xdir, f"ep{n}_cover.png"))
    if explicit:  # extra cover aspects the episode targets need (3:4 above is always written)
        for name, size in MC.extra_cover_sizes(ep_profs, base=("3x4",)).items():
            img = ep_cover(ep, shot, len(eps), size) if size[1] > size[0] else MC.wide_episode_cover(cfg, ep, shot, len(eps), size)
            img.save(os.path.join(xdir, f"ep{n}_cover_{name}.png"))
    print(f"ep{n}: {_lfc.mmss(ep['a'])}-{_lfc.mmss(ep['b'] or total)}  {ep.get('title', '')}")

# ---- 发布包.md
tagline = publish.hashtags(cfg.get("publish.tags", []), platform="xiaohongshu")
errata = cfg.get("publish.errata_line", "")
chapter_intro = pers.get("publish", {}).get("chapter_line", "")
L = ["# 发布包", "", "## 完整版 (YouTube / B站)", "", f"**标题**: {cfg.get('publish.title', '')}", "",
     cfg.get("publish.body", ""), "", chapter_intro, *chapter_lines(0, None), ""]
if errata:
    L += [errata, ""]
L += [tagline, "", f"文件: final_subbed.mp4 · 字幕: subs.srt · 封面: cover_16x9.png / cover_3x4.png", ""]
for ep in eps:
    title = ep.get("title", "")
    ok, n_len, hints = publish.check_title(title, "xiaohongshu") if title else (True, 0, [])
    if not ok:
        print(f"WARN ep{ep['n']} title length {n_len:g} > {publish.title_max('xiaohongshu')}: {title} ({'; '.join(hints)})")
    L += [f"## 第 {ep['n']}/{len(eps)} 集 (小红书)", "", f"**标题**: {title}", "",
          ep.get("body", ""), "", chapter_intro, *chapter_lines(ep["a"], ep["b"], LABEL_MAX), ""]
    if errata and (ep.get("errata", False)):
        L += [errata, ""]
    L += [tagline, "", f"文件: episodes/ep{ep['n']}.mp4 · 封面: episodes/ep{ep['n']}_cover.png", ""]
for p in _lfc.full_targets(profs):
    w = PF.check_length(p, total) + (PF.check_text(p, title=cfg.get("publish.title")) if cfg.get("publish.title") else [])
    for m in w:
        print(f"WARN full {p.key}: {m}")
    checks["full"][p.key] = w
_lfc.dump_json(checks, os.path.join(cfg.out, "platform_checks.json"))
p = os.path.join(cfg.out, "发布包.md")
open(p, "w", encoding="utf-8").write("\n".join(L))
print(p)
