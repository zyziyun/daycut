#!/usr/bin/env python3
"""发布文案 helper: title length check + chapter timeline in FINAL-video time + persona tags.

V track (compose config; needs timeline.json written by compose.py next to the config):
    python3 caption.py work/config.py --title "候选标题一" --title "候选标题二"
H track (make_assets/build_filter config):
    python3 caption.py work/config.py --title "..."
Chapter t (body / original seconds) lands at BODY_START + t / BODY_SPEED. The hook montage is 00:00.
Title length uses vstudio.config.xhs_len (CJK = 1, latin/digit/space = 0.5) against
persona platforms.<default>.title_max. Tags come from persona publish.tags.
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[3] / "lib"),
                                     str(pathlib.Path(__file__).resolve().parent / "vertical")]
import argparse, importlib.util, json, os

from vstudio.config import persona, xhs_len


def mmss(t):
    t = max(0, int(round(t))); return f"{t // 60:02d}:{t % 60:02d}"


def main():
    ap = argparse.ArgumentParser(description="Title length check + final-time chapter list + tags for the post copy.")
    ap.add_argument("config"); ap.add_argument("--title", action="append", default=[])
    ap.add_argument("--hook-label", default="高光预告")
    a = ap.parse_args()
    cfg = os.path.abspath(a.config); os.chdir(os.path.dirname(cfg)); sys.path.insert(0, os.path.dirname(cfg))
    spec = importlib.util.spec_from_file_location("cfg", cfg); C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
    P = persona(); plat = (P.get("platforms") or {}); pname = plat.get("default", "xiaohongshu")
    tmax = (plat.get(pname) or {}).get("title_max", 20)

    for t in a.title:
        n = xhs_len(t); print(f"[{'OK ' if n <= tmax else 'TOO LONG'}] {n:4.1f}/{tmax}  {t}")
    if a.title: print()

    if os.path.exists("timeline.json"):                       # V track
        tl = json.load(open("timeline.json")); start, bs = tl["BODY_START"], tl["BODY_SPEED"]
    else:                                                     # H track: same xfade math as build_filter.py
        sp = P.get("speed") or {}
        hs = getattr(C, "HOOK_SPEED", sp.get("hook", 1.3)); bs = getattr(C, "BODY_SPEED", sp.get("body", 1.1)); x = getattr(C, "XFADE", 0.8)
        d = [(e - s) / hs for s, e in C.HOOKS]; L = d[0]
        for v in d[1:]: L += v - x
        start = L - x
    print(f"00:00 {a.hook_label}")
    for c0, _c1, label in getattr(C, "CHAPTERS", []):
        print(f"{mmss(start + c0 / bs)} {label}")
    pub = P.get("publish") or {}
    if pub.get("chapter_line"): print("\n" + pub["chapter_line"])
    if pub.get("tags"): print("\n" + " ".join(t if t.startswith("#") else "#" + t for t in pub["tags"]))
    rules = (P.get("voice") or {}).get("rules") or []
    if rules: print("\nvoice rules for the body copy:\n- " + "\n- ".join(rules))


if __name__ == "__main__":
    main()
