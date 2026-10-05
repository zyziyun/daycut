#!/usr/bin/env python3
"""发布文案 helper: title length check + chapter timeline in FINAL-video time + persona tags.

Both tracks read timeline.json next to the config (written by compose.py / build_filter.py):
    python3 caption.py work/config.py --title "候选标题一" --title "候选标题二"
Chapter t (body / original seconds) lands at BODY_START + t / BODY_SPEED. The hook montage is 00:00.
Built on vstudio.publish: check_title (小红书 CJK = 1, latin/digit/space = 0.5, persona
platforms.<default>.title_max), chapters_from_body + chapter_lines (labels capped at 14 chars on 小红书,
floor to the second), hashtags (persona publish.tags), voice rules from persona voice.rules.
Platform (--platform, else config PLATFORM, else the canvas compose.py rendered (timeline.json), else persona
platforms.default): title limit + counting rule, description limit (--body FILE), tag count, length
sweet spot / max (vstudio.platform.check_text / check_length), chapters only where the platform has them.
Several targets: --platform xiaohongshu:vertical --platform youtube (one block each).
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[3] / "lib"),
                                     str(pathlib.Path(__file__).resolve().parent / "vertical")]
import argparse, importlib.util, json, os

from vstudio import publish
from vstudio import platform as P
from vstudio.config import persona


def _pub_name(prof):
    return "youtube" if prof.name == "youtube-shorts" else prof.name


def block(prof, a, C, tl):
    pn = _pub_name(prof)
    print(f"== {prof.label} ({prof.key}) ==")
    for t in a.title:
        ok, n, hints = publish.check_title(t, pn)
        ok = ok and not P.check_text(prof, title=t)
        print(f"[{'OK ' if ok else 'TOO LONG'}] {P.title_len(prof, t):4.1f}/{prof.title_max:g}  {t}" + ("".join(f"\n      - {h}" for h in hints)))
    if a.body:
        body = open(a.body, encoding="utf-8").read()
        for w in P.check_text(prof, body=body): print("WARN", w)
    if tl.get("TOTAL"):
        for w in P.check_length(prof, tl["TOTAL"]): print("WARN", w)
    ch = publish.chapters_from_body(getattr(C, "CHAPTERS", []), tl["BODY_START"], tl["BODY_SPEED"])
    lines = publish.chapter_lines(ch, intro_label=a.hook_label, platform=pn)
    if lines:
        if not prof.chapters.get("supported", False):
            print(f"(no native chapters on {prof.label}: paste as a 时间线 text list)")
        print("\n".join(lines))
    pub = persona().get("publish") or {}
    if pub.get("chapter_line"): print("\n" + pub["chapter_line"])
    tags = publish.hashtags(platform=pn)
    if tags:
        print("\n" + tags)
        for w in P.check_text(prof, tags=tags.split()): print("WARN", w)
    print()


def main():
    ap = argparse.ArgumentParser(description="Title length check + final-time chapter list + tags for the post copy.")
    ap.add_argument("config"); ap.add_argument("--title", action="append", default=[])
    ap.add_argument("--hook-label", default="高光预告")
    ap.add_argument("--platform", action="append", default=[],
                    help="e.g. xiaohongshu:vertical, douyin, youtube (repeatable; default: config PLATFORM / timeline / persona)")
    ap.add_argument("--body", help="post body text file: checked against each platform's description limit")
    a = ap.parse_args()
    cfg = os.path.abspath(a.config); os.chdir(os.path.dirname(cfg)); sys.path.insert(0, os.path.dirname(cfg))
    spec = importlib.util.spec_from_file_location("cfg", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
    if not os.path.exists("timeline.json"):
        sys.exit("no timeline.json next to the config: run compose.py (V) or build_filter.py (H) first")
    tl = json.load(open("timeline.json"))
    specs = a.platform or [getattr(C, "PLATFORM", None) or tl.get("PLATFORM") or None]
    from layout import resolve_profile
    for sp in specs:
        block(resolve_profile(sp), a, C, tl)
    rules = (persona().get("voice") or {}).get("rules") or []
    if rules: print("voice rules for the body copy:\n- " + "\n- ".join(rules))


if __name__ == "__main__":
    main()
