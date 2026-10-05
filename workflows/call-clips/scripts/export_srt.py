#!/usr/bin/env python3
"""Write .srt tracks from a (bilingual) subs.json (vstudio.subs.srt_write).

YouTube renders uploaded caption tracks itself, so shipping zh and en as
separate files lets a viewer pick one, or turn them off, which burned-in
subtitles never allow.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

from vstudio.subs import Cue, srt_write


def main():
    ap = argparse.ArgumentParser(description="subs.json (with zh/en keys) -> .zh.srt / .en.srt / .bilingual.srt")
    ap.add_argument("subs")
    ap.add_argument("--prefix", required=True, help="output path prefix, e.g. out/YT")
    args = ap.parse_args()
    cues = [Cue.from_dict(d) for d in json.load(open(args.subs, encoding="utf-8"))]
    # text = zh (or the plain line), alt = en; "both" is a combined track for
    # players that show only one caption stream
    for suffix, which in (("zh", "text"), ("en", "alt"), ("bilingual", "both")):
        path = f"{args.prefix}.{suffix}.srt"
        print(f"{srt_write(cues, path, which=which):4d} cues -> {path}")


if __name__ == "__main__":
    main()
