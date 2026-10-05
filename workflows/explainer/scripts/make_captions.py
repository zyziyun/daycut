#!/usr/bin/env python3
"""Build the bilingual caption sub-composition from subtitles/cues.json.

Usage:  python3 make_captions.py [--project .] [--font assets/fonts/subtitle-cjk-w3.woff2] [--font-bold assets/fonts/subtitle-cjk-w6.woff2]
Reads   <project>/subtitles/cues.json, audio/scenes.json
Writes  <project>/compositions/captions.html  (EN line on top, 中文 below, bottom band y > 840)
        For a vertical canvas (--platform / scenes.config.json "platform", see canvas.py) the cue block sits
        bottom-anchored inside the profile's caption box, sizes from the band height, balanced wraps, and cues
        longer than 2 lines per language are reported.
The CJK font must be a file you are allowed to ship (e.g. Noto Sans SC, OFL); see subset_cjk_font.py.
--font paths are URLs relative to the project root (they are written into the HTML as-is).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from canvas import add_platform_arg, resolve

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--font", default="assets/fonts/subtitle-cjk-w3.woff2")
ap.add_argument("--font-bold", default="assets/fonts/subtitle-cjk-w6.woff2")
add_platform_arg(ap)
a = ap.parse_args()
root = pathlib.Path(a.project)
cv = resolve(root, a.platform)

C = json.load(open(root / "subtitles/cues.json"))
total = json.load(open(root / "audio/scenes.json"))["total"]
data = json.dumps([{"s": c["start"], "e": c["end"], "en": c["en"], "zh": c["zh"]} for c in C], ensure_ascii=False)
W, H = cv["W"], cv["H"]
if cv["legacy"]:
    style = f'''    #captions-band {{ position: absolute; left: 0; right: 0; bottom: 0; height: 250px;
      background: linear-gradient(to bottom, rgba(5,8,16,0) 0%, rgba(5,8,16,0.72) 38%, rgba(5,8,16,0.86) 100%); }}
    .captions-cue {{ position: absolute; left: 120px; right: 120px; bottom: 44px; display: flex; flex-direction: column;
      align-items: center; gap: 10px; text-align: center; opacity: 0; font-family: "Subtitle CJK", sans-serif; }}
    .captions-en {{ font-size: 38px; line-height: 1.25; color: #ECEEF2; font-weight: 600; max-width: 1680px; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
    .captions-zh {{ font-size: 34px; line-height: 1.3; color: #C9CED8; font-weight: 400; max-width: 1680px; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}'''
else:
    x0, y0, x1, y1 = cv["caption"]
    band_top = max(0, y0 - 60)
    # soft scrim from just above the caption box down to the canvas bottom; the cue block grows upwards from y1
    style = f'''    #captions-band {{ position: absolute; left: 0; right: 0; top: {band_top}px; bottom: 0;
      background: linear-gradient(to bottom, rgba(5,8,16,0) 0px, rgba(5,8,16,0.70) 60px, rgba(5,8,16,0.82) 100%); }}
    .captions-cue {{ position: absolute; left: {x0}px; width: {x1 - x0}px; bottom: {H - y1 + 10}px; display: flex; flex-direction: column;
      align-items: center; gap: 8px; text-align: center; opacity: 0; font-family: "Subtitle CJK", sans-serif; }}
    .captions-en {{ font-size: {cv["en_fs"]}px; line-height: 1.2; color: #ECEEF2; font-weight: 600; max-width: {x1 - x0}px; text-wrap: balance; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
    .captions-zh {{ font-size: {cv["zh_fs"]}px; line-height: 1.25; color: #DDE1EA; font-weight: 600; max-width: {x1 - x0}px; text-wrap: balance; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}'''
    long = [c for c in C if len(c["en"]) > cv["max_en"] or len(c["zh"]) > cv["max_zh"]]
    for c in long:
        print(f"warning: line {c['line']} cue at {c['start']:.2f}s exceeds 2 lines in the {cv['key']} caption box "
              f"(EN {len(c['en'])}/{cv['max_en']}, ZH {len(c['zh'])}/{cv['max_zh']}): split it in cues.txt")
open(root / "compositions/captions.html", "w").write(f'''<template>
  <style>
    @font-face {{ font-family: "Subtitle CJK"; src: url("{a.font}") format("woff2"); font-weight: 400; }}
    @font-face {{ font-family: "Subtitle CJK"; src: url("{a.font_bold}") format("woff2"); font-weight: 600; }}
    #root {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
{style}
  </style>
  <div id="root" data-composition-id="captions" data-width="{W}" data-height="{H}" data-duration="{total}">
    <div id="captions-band" class="clip" data-start="0" data-duration="{total}" data-track-index="1"></div>
    <div id="captions-layer" class="clip" data-start="0" data-duration="{total}" data-track-index="2"></div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <script>
    (function () {{
      const CUES = {data};
      const layer = document.getElementById("captions-layer");
      const tl = gsap.timeline({{ paused: true }});
      CUES.forEach((c, i) => {{
        const d = document.createElement("div"); d.className = "captions-cue"; d.id = "captions-cue-" + i;
        const en = document.createElement("div"); en.className = "captions-en"; en.textContent = c.en;
        const zh = document.createElement("div"); zh.className = "captions-zh"; zh.textContent = c.zh;
        d.appendChild(en); d.appendChild(zh); layer.appendChild(d);
        tl.fromTo(d, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.12, ease: "none" }}, c.s);
        tl.to(d, {{ opacity: 0, duration: 0.12, ease: "none" }}, Math.max(c.s + 0.2, c.e - 0.12));
      }});
      window.__timelines["captions"] = tl;
    }})();
  </script>
</template>
''')
print("captions:", len(C), "cues")
