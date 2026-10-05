#!/usr/bin/env python3
"""Step 6b: 记笔记-style note panels (panels/panel_NN.png) + panels.json.

config.panels: [{"title": ..., "lines": [...], "src": [t0, t1]}]  (source seconds)
A line starting with spaces continues the previous bullet. Windows stay in SOURCE time;
burn_final.py maps them through timeline.json, so they survive speed changes and recuts.
Panels sit over the doc's right-side whitespace (panel_pos); the tag text is
panel_tag (default 记笔记). Edit panel text -> rerun this + burn_final.py only.

Usage: python3 make_panels.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image, ImageDraw

import _lfc

cfg, _ = _lfc.load(description=__doc__)
P = _lfc.palette(cfg)
PW = cfg.get("panel_width", 460)
TAG = cfg.get("panel_tag", "记笔记")

os.makedirs("panels", exist_ok=True)
f_tag, f_title, f_line = _lfc.font(24), _lfc.font(34, bold=True), _lfc.font(27)
meta = []
for i, p in enumerate(cfg.get("panels", [])):
    rows = [part for ln in p["lines"] for part in ln.split("\n")]
    ph = 132 + len(rows) * 46 + 24
    im = Image.new("RGBA", (PW, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, PW - 1, ph - 1], radius=18, fill=(13, 13, 16, 235),
                        outline=P["accent"] + (255,), width=2)
    d.rectangle([0, 18, 6, ph - 18], fill=P["accent"])
    d.text((28, 22), TAG, font=f_tag, fill=P["accent"])
    d.text((28, 58), p["title"], font=f_title, fill=P["ink"])
    y = 118
    for part in rows:
        pre = "  " if part.startswith(" ") else "· "
        d.text((28, y), pre + part.strip(), font=f_line, fill=(220, 220, 224))
        y += 46
    png = f"panels/panel_{i:02d}.png"
    im.save(png)
    meta.append({"png": png, "t0": p["src"][0], "t1": p["src"][1], "h": ph})
_lfc.dump_json(meta, "panels.json")
print(f"{len(meta)} panels written")
