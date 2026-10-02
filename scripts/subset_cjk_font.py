#!/usr/bin/env python3
"""Subset a CJK font down to the characters your subtitles use → small woff2 you can ship with the project.

Usage:  python3 subset_cjk_font.py FONT.ttf|.otf|.ttc [--face-name "Noto Sans SC Regular"] --out assets/fonts/subtitle-cjk-w3.woff2
Reads   subtitles/cues.json
Needs   pip install fonttools brotli

Use a font whose licence allows embedding/redistribution (Noto Sans SC / Source Han Sans are OFL).
Do NOT subset system fonts like PingFang or Hiragino for anything you publish.
The renderer is a clean headless Chrome: a CJK family that only exists on your machine silently falls back.
"""
import argparse, json
from fontTools import subset
from fontTools.ttLib import TTCollection, TTFont

ap = argparse.ArgumentParser()
ap.add_argument("font")
ap.add_argument("--face-name", help="face to pick from a .ttc collection")
ap.add_argument("--out", required=True)
a = ap.parse_args()

cues = json.load(open("subtitles/cues.json"))
chars = set("".join(c["zh"] + c["en"] for c in cues)) | {chr(i) for i in range(32, 127)} | set("−×÷≈≤→·…—“”‘’（）：；，。、？！%")
src = a.font
if a.font.lower().endswith(".ttc"):
    col = TTCollection(a.font)
    face = next((f for f in col.fonts if not a.face_name or f["name"].getDebugName(4) == a.face_name), col.fonts[0])
    src = "/tmp/_face.ttf"; face.save(src)
opts = subset.Options(); opts.flavor = "woff2"; opts.layout_features = ["*"]
ft = subset.load_font(src, opts); s = subset.Subsetter(opts); s.populate(text="".join(chars)); s.subset(ft)
subset.save_font(ft, a.out, opts)
print(f"{a.out} · {len(chars)} glyphs requested")
