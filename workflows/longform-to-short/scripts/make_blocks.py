#!/usr/bin/env python3
"""Step 2: merge whisper segments + speaker timeline into numbered review blocks.

A block breaks on speaker change, a gap > blocks.gap seconds, or length > blocks.max_len.
blocks.txt is what you (or an LLM) read to decide keep/drop; blocks.json feeds the cut.

Usage: python3 make_blocks.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import os

import _lfc

cfg, _ = _lfc.load(description=__doc__)
GAP = cfg.get("blocks.gap", 2.5)
MAX_LEN = cfg.get("blocks.max_len", 45)

w = _lfc.load_json("audio16k.json")
speakers = _lfc.load_json("speakers.json") if os.path.exists("speakers.json") else []


def speaker_at(t):
    best, bestd = "?", 1e9
    for t0, t1, s in speakers:
        if t0 - 2 <= t <= t1 + 2:
            return s
        d = min(abs(t - t0), abs(t - t1))
        if d < bestd:
            best, bestd = s, d
    return best if bestd < 20 else "?"


blocks, cur = [], None
for seg in w["segments"]:
    t0, t1, txt = seg["start"], seg["end"], seg["text"].strip()
    if not txt:
        continue
    spk = speaker_at((t0 + t1) / 2)
    if cur and spk == cur["spk"] and t0 - cur["t1"] <= GAP and cur["t1"] - cur["t0"] < MAX_LEN:
        cur["t1"] = t1
        cur["text"] += txt
    else:
        if cur:
            blocks.append(cur)
        cur = {"t0": round(t0, 2), "t1": round(t1, 2), "spk": spk, "text": txt}
if cur:
    blocks.append(cur)
for i, b in enumerate(blocks):
    b["id"], b["t1"] = i, round(b["t1"], 2)

_lfc.dump_json(blocks, "blocks.json", indent=0)
with open("blocks.txt", "w", encoding="utf-8") as f:
    for b in blocks:
        f.write(f"#{b['id']:03d} [{_lfc.mmss(b['t0'])}-{_lfc.mmss(b['t1'])}] {b['spk']}: {b['text']}\n")
print(f"blocks={len(blocks)} -> blocks.txt; fill keep.ranges + keep.chapters in the config")
