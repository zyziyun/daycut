#!/usr/bin/env python3
"""Step 6a: chapter cards (cards/card_NN.png) + transparent hook overlay (hook_overlay.png).

Card titles come from keep.chapters in keep order; override the on-card wording with
cards.titles (same count). "Main：sub" titles render as a small grey kicker + big title.
Hook overlay: hook.lines [big line, accent sub line] in a dark rounded box at top centre.
Look: style.accent / style.bg (persona longform.accent / longform.ground), vstudio CJK fonts.

Usage: python3 make_assets.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image, ImageDraw

import _lfc

cfg, _ = _lfc.load(description=__doc__)
P = _lfc.palette(cfg)
W, H = cfg.get("render.size", [1920, 1080])
s = H / 1080.0

titles = [seg["chapter"] for seg in _lfc.load_json("keep_list.json") if seg.get("chapter")]
override = cfg.get("cards.titles")
if override:
    if len(override) != len(titles):
        sys.exit(f"cards.titles has {len(override)} entries, keep list has {len(titles)} chapters")
    titles = override

os.makedirs("cards", exist_ok=True)
f_idx, f_title = _lfc.font(int(40 * s)), _lfc.font(int(76 * s), bold=True)
for i, title in enumerate(titles, 1):
    im = Image.new("RGB", (W, H), P["bg"])
    d = ImageDraw.Draw(im)
    d.text((120 * s, 96 * s), f"{i:02d} / {len(titles)}", font=f_idx, fill=P["accent"])
    sep = "：" if "：" in title else (": " if ": " in title else None)
    main, sub = (title.split(sep, 1) if sep else (title, ""))
    if sub:
        d.text((120 * s, H // 2 - 110 * s), main, font=f_idx, fill=P["muted"])
        d.text((118 * s, H // 2 - 50 * s), sub, font=f_title, fill=P["ink"])
    else:
        d.text((118 * s, H // 2 - 50 * s), main, font=f_title, fill=P["ink"])
    d.rectangle([120 * s, H // 2 + 78 * s, 300 * s, H // 2 + 86 * s], fill=P["accent"])
    im.save(f"cards/card_{i:02d}.png")

lines = cfg.get("hook.lines") or []
if lines:
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    l1, l2 = (lines + [""])[:2]
    f1, f2 = _lfc.font(int(72 * s), bold=True), _lfc.font(int(44 * s))
    w1, w2 = d.textlength(l1, font=f1), d.textlength(l2, font=f2)
    bw = max(w1, w2) + 120 * s
    bx = (W - bw) / 2
    d.rounded_rectangle([bx, 56 * s, bx + bw, (296 if l2 else 200) * s], radius=int(24 * s),
                        fill=P["bg"] + (216,))
    d.text(((W - w1) / 2, 92 * s), l1, font=f1, fill=P["ink"])
    if l2:
        d.text(((W - w2) / 2, 204 * s), l2, font=f2, fill=P["accent"])
    ov.save("hook_overlay.png")
elif cfg.get("hook.src"):
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save("hook_overlay.png")
print(f"{len(titles)} cards" + (" + hook_overlay.png" if cfg.get("hook.src") else ""))
