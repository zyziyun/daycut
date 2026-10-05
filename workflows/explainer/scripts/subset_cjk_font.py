#!/usr/bin/env python3
"""Subset a CJK font down to the characters your subtitles use → small woff2 you can ship with the project.

Usage:  python3 subset_cjk_font.py FONT.ttf|.otf|.ttc [--project .] [--face-name "Noto Sans SC Regular"] \
            --out assets/fonts/subtitle-cjk-w3.woff2
Reads   <project>/subtitles/cues.json
Writes  --out, relative to the project dir (absolute paths kept). FONT is relative to the current dir.
Needs   pip install fonttools brotli   (without brotli vstudio.render.subset_font writes .otf/.ttf instead
        and prints the path; point make_captions.py --font at that file).

Use a font whose licence allows embedding/redistribution (Noto Sans SC / Source Han Sans are OFL).
Do NOT subset system fonts like PingFang or Hiragino for anything you publish.
The renderer is a clean headless Chrome: a CJK family that only exists on your machine silently falls back.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

from vstudio.render import subset_font

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("font")
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--face-name", help="face to pick from a .ttc collection")
ap.add_argument("--out", required=True)
a = ap.parse_args()

root = pathlib.Path(a.project)
cues = json.load(open(root / "subtitles/cues.json"))
chars = "".join(c["zh"] + c["en"] for c in cues)          # + ASCII and CJK punctuation (render.BASE_CHARS)
out = subset_font(a.font, chars, root / a.out, face_name=a.face_name)
print(f"{out} · {len(set(chars))} subtitle glyphs requested")
