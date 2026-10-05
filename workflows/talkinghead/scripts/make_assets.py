#!/usr/bin/env python3
"""Render overlay PNGs from config: dim chapter bar, active-chapter highlights, hook badge,
callout bubbles, 记笔记 panels. Writes assets.json (manifest read by build_filter.py).
All furniture comes from vstudio.overlays (progress_static, badge, callout, notes_panel; theme =
persona brand.panel_theme, default notes-red).
Usage: python3 make_assets.py work/config.py   (template: examples/h_config_example.py)"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"): print(__doc__); sys.exit(0)
import os, json, importlib.util
from vstudio import overlays as O

cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.py"
spec = importlib.util.spec_from_file_location("config", cfg_path)
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
OUT, MAIN_DUR = C.WORK, C.MAIN_DUR
os.makedirs(OUT, exist_ok=True)
BAR_Y = 1000                      # build_filter overlays the bar strip here (fill drawbox at BAR_Y + 22)

# dim chapter bar + active-chapter highlight labels (chapter times = source seconds of the main part)
pb = O.progress_static(C.CHAPTERS, MAIN_DUR, width=1920, y=BAR_Y, x0=80, bar_w=1760)
pb["bar"].save(f"{OUT}/bar_overlay.png")
active = []
for k, (im, x, y, s, e) in enumerate(pb["active"]):
    im.save(f"{OUT}/active_{k}.png")
    active.append({"k": k, "x": x, "y": y, "s": s, "e": e})

# hook badge
O.badge(getattr(C, "HOOK_BADGE_TEXT", "高光预告 · 完整版在下面"), size=30).save(f"{OUT}/hook_badge.png")

# callouts (skip REMOVE)
co = []
for i, (anchor, dur, text) in enumerate(C.CALLOUTS):
    if anchor in getattr(C, "REMOVE", set()): continue
    im = O.callout(text, max_w=560); im.save(f"{OUT}/callout_{i}.png")
    co.append({"i": i, "anchor": anchor, "dur": dur, "w": im.width, "h": im.height})

# 记笔记 panels
pa = []
for p, (anchor, dur, title, bullets) in enumerate(C.PANELS):
    im = O.notes_panel(title, bullets, width=620, tag=getattr(C, "NOTES_TAG", None)); im.save(f"{OUT}/panel_{p}.png")
    pa.append({"p": p, "anchor": anchor, "dur": dur, "w": im.width, "h": im.height})

json.dump({"callouts": co, "panels": pa, "active": active}, open(f"{OUT}/assets.json", "w"), ensure_ascii=False, indent=1)
print(f"callouts {len(co)} | panels {len(pa)} | active {len(active)} -> {OUT}")
