#!/usr/bin/env python3
"""Write one build packet per scene for frame workers (sub-agents or yourself).

Usage:  python3 make_packets.py
Reads   scenes.config.json, audio/scenes.json, audio/scene_cues.json
Writes  .hyperframes/frame-packets/<id>.md

scenes.config.json:
{
  "scenes": [
    {"id": "f01-hook", "transition": null,           "shots": "Scene title fades in at 0.2s.\n- 2.7s (...): ..."},
    {"id": "f02-rounding", "transition": ["blur", 0.8], "shots": "..."}
  ]
}
Line N of SCRIPT.md maps to scenes[N-1]. Shot times are scene-local seconds taken from
audio/scene_cues.json — write the shots AFTER the voice exists so reveals land on real words.
"""
import json, os

cfg = json.load(open("scenes.config.json"))["scenes"]
S = json.load(open("audio/scenes.json"))["scenes"]
CUES = json.load(open("audio/scene_cues.json"))
os.makedirs(".hyperframes/frame-packets", exist_ok=True)
for k, (w, sc) in enumerate(zip(S, cfg)):
    n, fid, last = w["frame"], sc["id"], k == len(S) - 1
    cues = "\n".join(f"| {c['t']:6.2f} | {c['te']:6.2f} | {c['en']} |" for c in CUES[str(n)])
    open(f".hyperframes/frame-packets/{fid}.md", "w").write(f"""# Frame packet — {fid}

- frame_id: `{fid}` → write `compositions/{fid}.html` (+ `compositions/{fid}.motion.json`)
- composition id / timeline key: `{fid}`
- duration: **{w['duration']}s** (scene-local time 0 = this scene's start; fixed — never change)
- canvas: 1920×1080 · Captions: enabled (root track owns y > 840; keep all content y ≤ 800)
- confirmed sketch: `storyboard/sketches/f{n:02d}.svg` — keep its placement, hierarchy and copy (ignore its bottom subtitle band)
- design truth: `frame.md`
- final frame: {"yes — a closing fade is allowed" if last else "no — no exit animation"}

## Time-coded shot sequence (scene-local seconds)

{sc.get("shots", "(write the shot sequence in scenes.config.json)")}

## Voiceover cues (timing reference only — never render this text)

| start | end | spoken (display form) |
|---|---|---|
{cues}
""")
print("wrote", len(S), "packets")
