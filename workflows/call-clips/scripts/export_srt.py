#!/usr/bin/env python3
"""Write .srt tracks from a bilingual subs.json.

YouTube renders uploaded caption tracks itself, so shipping zh and en as
separate files lets a viewer pick one, or turn them off, which burned-in
subtitles never allow.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json


def ts(t):
    # round once, in integer ms, so 59.9996s never prints as ",1000"
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write(path, lines, key):
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for ln in lines:
            txt = (ln.get(key) or "").strip()
            if not txt:
                continue
            n += 1
            f.write(f"{n}\n{ts(ln['start'])} --> {ts(ln['end'])}\n{txt}\n\n")
    print(f"{n:4d} cues -> {path}")


def main():
    ap = argparse.ArgumentParser(description="subs.json (with zh/en keys) -> .zh.srt / .en.srt / .bilingual.srt")
    ap.add_argument("subs")
    ap.add_argument("--prefix", required=True, help="output path prefix, e.g. out/YT")
    args = ap.parse_args()
    lines = json.load(open(args.subs))
    write(f"{args.prefix}.zh.srt", lines, "zh")
    write(f"{args.prefix}.en.srt", lines, "en")
    # a combined track for players that show only one caption stream
    both = [{**l, "both": f"{l.get('zh','')}\n{l.get('en','')}".strip()} for l in lines]
    write(f"{args.prefix}.bilingual.srt", both, "both")


if __name__ == "__main__":
    main()
