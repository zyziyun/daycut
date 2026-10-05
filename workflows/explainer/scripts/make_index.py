#!/usr/bin/env python3
"""Assemble index.html: shared ground, scene sub-compositions with transitions, captions, voice, music.

Usage:  python3 make_index.py [--project .] [--patch-scenes]
Reads   <project>/scenes.config.json (ids + "transition": [type, seconds] for each scene after the first),
        audio/scenes.json, compositions/<id>.html, compositions/captions.html,
        audio/narration.wav, optional audio/bgm.wav
Writes  <project>/index.html

Transition types: blur, fade, push, vpush, iris, zoom, focus, blocks, chroma, flip, zoomout.
A transition overlaps two scenes, so the OUTGOING scene must live `d` seconds longer than its
window. --patch-scenes rewrites each scene file's own data-duration (root + stage clip) to match;
without it the outgoing scene goes blank the moment the transition starts.
After regenerating, re-run the music carve:
  node <hyperframes-audio>/scripts/carve.mjs --comp index.html --bed bgm --voice narration --strength 0.8
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re
from vstudio import hf

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--patch-scenes", action="store_true",
                help="stretch each outgoing scene file's data-duration by its transition length")
a = ap.parse_args()
root = pathlib.Path(a.project)

S = json.load(open(root / "audio/scenes.json")); total = S["total"]
CFG = json.load(open(root / "scenes.config.json"))["scenes"]
IDS = [c["id"] for c in CFG]
TR = {k + 1: tuple(c["transition"]) for k, c in enumerate(CFG) if k > 0 and c.get("transition")}
if a.patch_scenes:
    for k, (w, fid) in enumerate(zip(S["scenes"], IDS)):
        ext = TR[k + 2][1] if k + 2 in TR else 0
        p = root / f"compositions/{fid}.html"; s = open(p).read()
        new = round(w["duration"] + ext, 2)
        # only full-length clips (root + stage) are stretched; shorter inner clips keep their timing
        s = re.sub(r'data-duration="([0-9.]+)"',
                   lambda m: f'data-duration="{new}"' if float(m.group(1)) >= w["duration"] - 0.01 else m.group(0), s)
        open(p, "w").write(s)
hosts = []
for k, (w, fid) in enumerate(zip(S["scenes"], IDS)):
    n = k + 1
    ext = TR[n + 1][1] if n + 1 in TR else 0
    hosts.append(f'''      <div id="w-{fid}" class="scene-wrap" style="z-index:{n}">
        <div id="{fid}" data-composition-id="{fid}" data-composition-src="compositions/{fid}.html"
          data-start="{w['start']}" data-duration="{round(w['duration'] + ext, 2)}" data-track-index="2" data-width="1920" data-height="1080"></div>
      </div>''')
trans = [{"n": n, **hf.transition(t, "w-" + IDS[n - 2], "w-" + IDS[n - 1], S["scenes"][n - 1]["start"], d)} for n, (t, d) in TR.items()]
tx = hf.scene_transitions(trans)  # css/html/js for the 11 transition types (vstudio.hf)
bgm = ""
if os.path.exists(root / "audio/bgm.wav"):
    bgm = f'''      <audio id="bgm" src="audio/bgm.wav" data-start="0" data-duration="{total}" data-track-index="9" data-volume="1"></audio>\n'''
html = f'''<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: 1920px; height: 1080px; overflow: hidden; background: #0B1020; }}
      #root {{ position: relative; width: 100%; height: 100%; overflow: hidden; background: #0B1020; }}
{hf.indent(tx['css'], 6)}      #ground {{ position: absolute; inset: 0;
        background: radial-gradient(ellipse 80% 70% at 50% 40%, #111830 0%, #0B1020 60%, #080C18 100%); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="{total}">
      <div id="ground" class="clip" data-start="0" data-duration="{total}" data-track-index="1"></div>
{chr(10).join(hosts)}
      {tx["html"]}
      <div id="captions" style="position:absolute;inset:0;z-index:50" data-composition-id="captions" data-composition-src="compositions/captions.html" data-track-kind="captions"
        data-start="0" data-duration="{total}" data-track-index="5" data-width="1920" data-height="1080"></div>
      <audio id="narration" src="audio/narration.wav" data-start="0" data-duration="{total}" data-track-index="8" data-volume="1"></audio>
{bgm}    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
{hf.indent(tx['js'], 6)}      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
'''
open(root / "index.html", "w").write(html)
print("index:", len(hosts), "scenes, total", total)
