#!/usr/bin/env python3
"""One scene per narration line: compute scene windows and scene-local cue times.

Usage:  python3 scene_windows.py [--project .] [--tail 2.5]
Reads   <project>/audio/vo/offsets.json, subtitles/cues.json, audio/vo gap (seams fall mid-gap)
Writes  <project>/audio/scenes.json       {"total": s, "scenes": [{"frame", "start", "end", "duration"}]}
        audio/scene_cues.json   {frame: [{"t", "te", "en"}]}   (scene-local seconds)
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canvas import add_platform_arg, resolve

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--tail", type=float, default=None,
                help="seconds held after the last word (default 2.5; 1.2 for a vertical canvas / \"mode\": \"short\")")
add_platform_arg(ap)
a = ap.parse_args()
root = pathlib.Path(a.project)
cv = resolve(root, a.platform)
mode = None
if (root / "scenes.config.json").exists():
    mode = json.load(open(root / "scenes.config.json")).get("mode")
short = mode == "short" or not cv["legacy"]
if a.tail is None:
    a.tail = 1.2 if short else 2.5

off = json.load(open(root / "audio/vo/offsets.json"))
cues = json.load(open(root / "subtitles/cues.json"))
half_gap = (off[1][1] - (off[0][1] + off[0][2])) / 2 if len(off) > 1 else 0.35
total = round(off[-1][1] + off[-1][2] + a.tail, 2)
W = []
for k, (n, st, d) in enumerate(off):
    s = 0.0 if k == 0 else round(st - half_gap, 2)
    e = round(off[k + 1][1] - half_gap, 2) if k + 1 < len(off) else total
    W.append({"frame": n, "start": s, "end": e, "duration": round(e - s, 2)})
out = {"total": total, "scenes": W}
if not cv["legacy"]:
    out["canvas"] = {"key": cv["key"], "W": cv["W"], "H": cv["H"], "safe": list(cv["safe"]),
                     "caption": list(cv["caption"]), "math": list(cv["math"])}
json.dump(out, open(root / "audio/scenes.json", "w"), indent=1)
local = {w["frame"]: [{"t": round(c["start"] - w["start"], 2), "te": round(c["end"] - w["start"], 2), "en": c["en"]}
                      for c in cues if c["line"] == w["frame"]] for w in W}
json.dump(local, open(root / "audio/scene_cues.json", "w"), indent=1, ensure_ascii=False)
for w in W:
    print(w)
print("total", total)
if cv.get("profile") is not None:
    from vstudio import platform as PF
    for w in PF.check_length(cv["profile"], total):
        print("warning:", w)
if short:
    long = [w for w in W if w["duration"] > 14]
    if long:
        print("short mode: scenes over 14 s (split the line or cut words):", [w["frame"] for w in long])
    if total > 120:
        print(f"short mode: total {total}s is over the 60-120 s target")
