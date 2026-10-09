#!/usr/bin/env python3
"""Assemble the post copy (title, body, links, chapter timeline, tags) from the project config and the
built timeline with vstudio.publish: title-length check for the platform, chapter lines, hashtags and
persona voice-rule warnings.

  python3 $VSTUDIO/workflows/promo-recut/scripts/post_copy.py promo.config.json [--platform xiaohongshu]

Writes <post.out | post.md> next to the config.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import json
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project  # noqa: E402
from vstudio import formats, publish  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("config")
    ap.add_argument("--platform", default=None, help="default: persona platforms.default (xiaohongshu)")
    a = ap.parse_args()
    prj = Project(a.config)
    post = prj.cfg.get("post") or {}
    chapters = None
    tl_path = os.path.join(prj.p(prj.cfg.get("promo_dir", "promo")), "timeline.json")
    if os.path.exists(tl_path) and post.get("chapters", True):
        chapters = json.load(open(tl_path, encoding="utf-8"))["chapters"]
    warns = []
    use_p, tag_set = formats.post_tags("promo", post)     # persona publish.tag_sets.promo, never the career tags
    text = publish.post_body(None, post.get("body", []), chapters=chapters, links=post.get("links", []),
                             tags=post.get("tags", []), platform=a.platform, title=post.get("title", ""),
                             warn=warns.append, use_persona_tags=use_p, tag_set=tag_set)
    out = prj.p(post.get("out", "post.md"))
    open(out, "w", encoding="utf-8").write(text)
    print(text)
    print("->", out)
    for w in warns:
        print("WARNING:", w)


if __name__ == "__main__":
    main()
