#!/usr/bin/env python3
"""Write one build packet per scene for frame workers (sub-agents or yourself).

Usage:  python3 make_packets.py [--project .]
Reads   <project>/scenes.config.json, audio/scenes.json, audio/scene_cues.json
Writes  <project>/.hyperframes/frame-packets/<id>.md

scenes.config.json:
{
  "scenes": [
    {"id": "f01-hook", "transition": null,           "shots": "Scene title fades in at 0.2s.\n- 2.7s (...): ..."},
    {"id": "f02-rounding", "transition": ["blur", 0.8], "shots": "..."}
  ]
}
Optional top level: "platform": "xiaohongshu:full" (vertical canvas, see canvas.py) and "mode": "short".
Line N of SCRIPT.md maps to scenes[N-1]. Shot times are scene-local seconds taken from
audio/scene_cues.json — write the shots AFTER the voice exists so reveals land on real words.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canvas import add_platform_arg, describe, resolve

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
add_platform_arg(ap)
a = ap.parse_args()
root = pathlib.Path(a.project)
cv = resolve(root, a.platform)
if cv["legacy"]:
    SKETCH = "keep its placement, hierarchy and copy (ignore its bottom subtitle band)"
    EXTRA = ""
else:
    SKETCH = (f"same {cv['W']}×{cv['H']} coordinates — keep its placement, hierarchy and copy (ignore its caption-band "
              f"stand-in y ≥ {cv['caption'][1]})")
    EXTRA = ("- canvas json: `" + json.dumps({k: cv[k] for k in ("W", "H", "key", "safe", "caption", "keepouts", "math",
                                                                   "math_narrow_from_y", "math_narrow_x1", "title_xy")})
             + "`\n- reference scene: `$VSTUDIO/workflows/explainer/assets/reference-scene-portrait.html`; design truth: "
               "`frame.md` = `references/design-truth-portrait.md` (bigger type: titles 56, math 72–120, mono 34–64)\n")

cfg = json.load(open(root / "scenes.config.json"))["scenes"]
S = json.load(open(root / "audio/scenes.json"))["scenes"]
CUES = json.load(open(root / "audio/scene_cues.json"))
os.makedirs(root / ".hyperframes/frame-packets", exist_ok=True)
for k, (w, sc) in enumerate(zip(S, cfg)):
    n, fid, last = w["frame"], sc["id"], k == len(S) - 1
    cues = "\n".join(f"| {c['t']:6.2f} | {c['te']:6.2f} | {c['en']} |" for c in CUES[str(n)])
    open(root / f".hyperframes/frame-packets/{fid}.md", "w").write(f"""# Frame packet — {fid}

- frame_id: `{fid}` → write `compositions/{fid}.html` (+ `compositions/{fid}.motion.json`)
- composition id / timeline key: `{fid}`
- duration: **{w['duration']}s** (scene-local time 0 = this scene's start; fixed — never change)
- {describe(cv)}
{EXTRA}- confirmed sketch: `storyboard/sketches/f{n:02d}.svg` — {SKETCH}
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
