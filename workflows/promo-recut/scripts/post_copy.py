#!/usr/bin/env python3
"""Assemble the post copy (title, body, links, chapter timeline, tags) from the project config and the
built timeline, check the title length for the platform and flag persona voice-rule breaks.

  python3 $VSTUDIO/workflows/promo-recut/scripts/post_copy.py promo.config.json [--platform xiaohongshu]

Writes <post.out | post.md> next to the config.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project, P  # noqa: E402
from vstudio.config import xhs_len  # noqa: E402


def mmss(t):
    t = int(round(t)); return f"{t // 60}:{t % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config")
    ap.add_argument("--platform", default=None)
    a = ap.parse_args()
    prj = Project(a.config)
    post = prj.cfg.get("post") or {}
    plat = a.platform or P("platforms.default", "xiaohongshu")
    tmax = P(f"platforms.{plat}.title_max", 20)
    title = post.get("title", "")
    n = xhs_len(title) if plat == "xiaohongshu" else len(title)
    warn = []
    if n > tmax:
        warn.append(f"title length {n:g} > {tmax} for {plat}")
    lines = [title, ""] + list(post.get("body", []))
    for lab, url in post.get("links", []):
        lines.append(f"{lab}: {url}")
    tl_path = os.path.join(prj.p(prj.cfg.get("promo_dir", "promo")), "timeline.json")
    if os.path.exists(tl_path) and post.get("chapters", True):
        tl = json.load(open(tl_path, encoding="utf-8"))
        lines += ["", P("publish.chapter_line", "")]
        lines += [f"{mmss(s)} {lab}" for s, _, lab in tl["chapters"]]
    tags = list(post.get("tags", [])) + list(P("publish.tags", []) or [])
    if tags:
        lines += ["", " ".join(t if t.startswith("#") else f"#{t}" for t in dict.fromkeys(tags))]
    text = "\n".join(lines).strip() + "\n"
    rules = " ".join(P("voice.rules", []) or [])
    if "em-dash" in rules and "—" in "".join(post.get("body", [])):
        warn.append("body contains an em-dash (persona voice rule)")
    out = prj.p(post.get("out", "post.md"))
    open(out, "w", encoding="utf-8").write(text)
    print(text)
    print("->", out)
    for w in warn:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
