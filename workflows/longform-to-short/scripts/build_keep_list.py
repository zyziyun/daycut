#!/usr/bin/env python3
"""Step 2b: keep_list.json from reviewed block-ID ranges.

config.keep.ranges   [[a, z], ...] inclusive block ids to KEEP
config.keep.chapters {block_id: "chapter title"}  a chapter card goes before that block
Adjacent kept blocks with a gap <= keep.merge_gap merge into one segment (natural pacing);
larger gaps are cut. A chapter start always begins a new segment.

Usage: python3 build_keep_list.py work/config.py
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import _lfc

cfg, _ = _lfc.load(description=__doc__)
MERGE_GAP = cfg.get("keep.merge_gap", 1.5)
PAD_IN, PAD_OUT = cfg.get("keep.pad_in", 0.15), cfg.get("keep.pad_out", 0.25)
RANGES = cfg.get("keep.ranges") or sys.exit("config keep.ranges is empty; review blocks.txt first")
CHAPTERS = {int(k): v for k, v in (cfg.get("keep.chapters") or {}).items()}

blocks = {b["id"]: b for b in _lfc.load_json("blocks.json")}
kept = [blocks[i] for a, z in RANGES for i in range(a, z + 1) if i in blocks]

segments = []
for b in kept:
    ch = CHAPTERS.get(b["id"])
    if segments and b["t0"] - segments[-1]["t1"] <= MERGE_GAP and not ch:
        segments[-1]["t1"] = b["t1"]
        segments[-1]["ids"].append(b["id"])
    else:
        segments.append({"t0": b["t0"], "t1": b["t1"], "ids": [b["id"]], "chapter": ch})
for s in segments:
    s["t0"] = round(max(0, s["t0"] - PAD_IN), 2)
    s["t1"] = round(s["t1"] + PAD_OUT, 2)
_lfc.dump_json(segments, "keep_list.json")

total, cur = sum(s["t1"] - s["t0"] for s in segments), 0.0
print(f"segments={len(segments)} total={total/60:.1f}min (before speed-up)")
for i, s in enumerate(segments):
    if s["chapter"]:
        print(f"  seg {i:>3}  {_lfc.mmss(cur)}  {s['chapter']}")
    cur += s["t1"] - s["t0"]
