#!/usr/bin/env python3
"""发布文案 helper: title length check + chapter timeline in FINAL-video time + persona tags.

Both tracks read timeline.json next to the config (written by compose.py / build_filter.py):
    python3 caption.py work/config.py --title "候选标题一" --title "候选标题二"
Chapter t (body / original seconds) lands at BODY_START + t / BODY_SPEED. The hook montage is 00:00.
Built on vstudio.publish: check_title (小红书 CJK = 1, latin/digit/space = 0.5, persona
platforms.<default>.title_max), chapters_from_body + chapter_lines (labels capped at 14 chars on 小红书,
floor to the second), hashtags (persona publish.tags), voice rules from persona voice.rules.
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[3] / "lib"),
                                     str(pathlib.Path(__file__).resolve().parent / "vertical")]
import argparse, importlib.util, json, os

from vstudio import publish
from vstudio.config import persona


def main():
    ap = argparse.ArgumentParser(description="Title length check + final-time chapter list + tags for the post copy.")
    ap.add_argument("config"); ap.add_argument("--title", action="append", default=[])
    ap.add_argument("--hook-label", default="高光预告")
    ap.add_argument("--platform", default=None, help="default: persona platforms.default")
    a = ap.parse_args()
    cfg = os.path.abspath(a.config); os.chdir(os.path.dirname(cfg)); sys.path.insert(0, os.path.dirname(cfg))
    spec = importlib.util.spec_from_file_location("cfg", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)

    for t in a.title:
        ok, n, hints = publish.check_title(t, a.platform)
        print(f"[{'OK ' if ok else 'TOO LONG'}] {n:4.1f}/{publish.title_max(a.platform)}  {t}" + ("".join(f"\n      - {h}" for h in hints)))
    if a.title: print()

    if not os.path.exists("timeline.json"):
        sys.exit("no timeline.json next to the config: run compose.py (V) or build_filter.py (H) first")
    tl = json.load(open("timeline.json"))
    ch = publish.chapters_from_body(getattr(C, "CHAPTERS", []), tl["BODY_START"], tl["BODY_SPEED"])
    print("\n".join(publish.chapter_lines(ch, intro_label=a.hook_label, platform=a.platform)))
    pub = persona().get("publish") or {}
    if pub.get("chapter_line"): print("\n" + pub["chapter_line"])
    tags = publish.hashtags(platform=a.platform)
    if tags: print("\n" + tags)
    rules = (persona().get("voice") or {}).get("rules") or []
    if rules: print("\nvoice rules for the body copy:\n- " + "\n- ".join(rules))


if __name__ == "__main__":
    main()
