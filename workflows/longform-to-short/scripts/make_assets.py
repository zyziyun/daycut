#!/usr/bin/env python3
"""Step 6a: chapter cards (cards/card_NN.png) + transparent hook overlay (hook_overlay.png).

Card titles come from keep.chapters in keep order; override the on-card wording with
cards.titles (same count). Cards are vstudio.overlays.chapter_card: "Main：sub" titles render as a
small grey kicker + big title (long titles wrap).
Hook overlay: hook.lines [big line, accent sub line] in a dark rounded box at top centre; per-episode
hooks (episodes.items[i].hook.lines) -> hook_overlay_ep<i+1>.png.
Look: style.accent / style.bg (persona longform.accent / longform.ground), vstudio CJK fonts.

Usage: python3 make_assets.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

from PIL import Image, ImageDraw

import _lfc
from vstudio import overlays

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
T = _lfc.theme(cfg)
for i, title in enumerate(titles, 1):
    card = overlays.chapter_card(i, len(titles), title, size=(W, H), theme=T, ground=P["bg"])
    card.convert("RGB").save(f"cards/card_{i:02d}.png")

def hook_overlay(lines, out):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if lines:
        d = ImageDraw.Draw(ov)
        l1, l2 = (list(lines) + [""])[:2]
        f1, f2 = _lfc.font(int(72 * s), bold=True), _lfc.font(int(44 * s))
        w1, w2 = d.textlength(l1, font=f1), d.textlength(l2, font=f2)
        bw = max(w1, w2) + 120 * s
        bx = (W - bw) / 2
        d.rounded_rectangle([bx, 56 * s, bx + bw, (296 if l2 else 200) * s], radius=int(24 * s),
                            fill=P["bg"] + (216,))
        d.text(((W - w1) / 2, 92 * s), l1, font=f1, fill=P["ink"])
        if l2:
            d.text(((W - w2) / 2, 204 * s), l2, font=f2, fill=P["accent"])
    ov.save(out)
    return out


made = []
lines = cfg.get("hook.lines") or []
if lines or cfg.get("hook.src"):
    made.append(hook_overlay(lines, "hook_overlay.png"))
for i, item in enumerate(cfg.get("episodes.items") or []):      # per-episode hooks (episodes.items[].hook)
    h = item.get("hook") or {}
    if h.get("src"):
        made.append(hook_overlay(h.get("lines") or [], f"hook_overlay_ep{i + 1}.png"))
print(f"{len(titles)} cards" + (" + " + " ".join(made) if made else ""))
