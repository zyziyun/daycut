#!/usr/bin/env python3
"""Step 6b: 记笔记-style note panels (panels/panel_NN.png) + panels.json.

config.panels: [{"title": ..., "lines": [...], "src": [t0, t1]}]  (source seconds)
A line starting with spaces continues the previous bullet. Windows stay in SOURCE time;
burn_final.py maps them through timeline.json, so they survive speed changes and recuts.
Drawn by vstudio.overlays.notes_panel (teal theme, long bullets wrap). Panels sit over the doc's
right-side whitespace (panel_pos); the tag text is panel_tag (default 记笔记). Edit panel text -> rerun this + burn_final.py only.

Usage: python3 make_panels.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import _lfc
from vstudio import overlays

cfg, _ = _lfc.load(description=__doc__)
PW = cfg.get("panel_width", 460)
TAG = cfg.get("panel_tag", "记笔记")
T = _lfc.theme(cfg)  # vstudio 'teal' theme (dark card, accent rail + outline) with style.accent

os.makedirs("panels", exist_ok=True)
meta = []
for i, p in enumerate(cfg.get("panels", [])):
    rows = [part for ln in p["lines"] for part in ln.split("\n")]
    im = overlays.notes_panel(p["title"], rows, theme=T, width=PW, tag=TAG)
    png = f"panels/panel_{i:02d}.png"
    im.save(png)
    meta.append({"png": png, "t0": p["src"][0], "t1": p["src"][1], "h": im.height})
_lfc.dump_json(meta, "panels.json")
print(f"{len(meta)} panels written")
