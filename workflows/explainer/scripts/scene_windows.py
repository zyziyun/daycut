#!/usr/bin/env python3
"""One scene per narration line: compute scene windows and scene-local cue times.

Usage:  python3 scene_windows.py [--project .] [--tail 2.5]
Reads   <project>/audio/vo/offsets.json, subtitles/cues.json, audio/vo gap (seams fall mid-gap)
Writes  <project>/audio/scenes.json       {"total": s, "scenes": [{"frame", "start", "end", "duration"}]}
        audio/scene_cues.json   {frame: [{"t", "te", "en"}]}   (scene-local seconds)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--tail", type=float, default=2.5, help="seconds held after the last word")
a = ap.parse_args()
root = pathlib.Path(a.project)

off = json.load(open(root / "audio/vo/offsets.json"))
cues = json.load(open(root / "subtitles/cues.json"))
half_gap = (off[1][1] - (off[0][1] + off[0][2])) / 2 if len(off) > 1 else 0.35
total = round(off[-1][1] + off[-1][2] + a.tail, 2)
W = []
for k, (n, st, d) in enumerate(off):
    s = 0.0 if k == 0 else round(st - half_gap, 2)
    e = round(off[k + 1][1] - half_gap, 2) if k + 1 < len(off) else total
    W.append({"frame": n, "start": s, "end": e, "duration": round(e - s, 2)})
json.dump({"total": total, "scenes": W}, open(root / "audio/scenes.json", "w"), indent=1)
local = {w["frame"]: [{"t": round(c["start"] - w["start"], 2), "te": round(c["end"] - w["start"], 2), "en": c["en"]}
                      for c in cues if c["line"] == w["frame"]] for w in W}
json.dump(local, open(root / "audio/scene_cues.json", "w"), indent=1, ensure_ascii=False)
for w in W:
    print(w)
print("total", total)
