#!/usr/bin/env python3
"""Build the bilingual caption sub-composition from subtitles/cues.json.

Usage:  python3 make_captions.py [--project .] [--font assets/fonts/subtitle-cjk-w3.woff2] [--font-bold assets/fonts/subtitle-cjk-w6.woff2]
Reads   <project>/subtitles/cues.json, audio/scenes.json
Writes  <project>/compositions/captions.html  (EN line on top, 中文 below, bottom band y > 840)
The CJK font must be a file you are allowed to ship (e.g. Noto Sans SC, OFL); see subset_cjk_font.py.
--font paths are URLs relative to the project root (they are written into the HTML as-is).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--project", "-C", default=".", help="project dir (default: current dir)")
ap.add_argument("--font", default="assets/fonts/subtitle-cjk-w3.woff2")
ap.add_argument("--font-bold", default="assets/fonts/subtitle-cjk-w6.woff2")
a = ap.parse_args()
root = pathlib.Path(a.project)

C = json.load(open(root / "subtitles/cues.json"))
total = json.load(open(root / "audio/scenes.json"))["total"]
data = json.dumps([{"s": c["start"], "e": c["end"], "en": c["en"], "zh": c["zh"]} for c in C], ensure_ascii=False)
open(root / "compositions/captions.html", "w").write(f'''<template>
  <style>
    @font-face {{ font-family: "Subtitle CJK"; src: url("{a.font}") format("woff2"); font-weight: 400; }}
    @font-face {{ font-family: "Subtitle CJK"; src: url("{a.font_bold}") format("woff2"); font-weight: 600; }}
    #root {{ position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }}
    #captions-band {{ position: absolute; left: 0; right: 0; bottom: 0; height: 250px;
      background: linear-gradient(to bottom, rgba(5,8,16,0) 0%, rgba(5,8,16,0.72) 38%, rgba(5,8,16,0.86) 100%); }}
    .captions-cue {{ position: absolute; left: 120px; right: 120px; bottom: 44px; display: flex; flex-direction: column;
      align-items: center; gap: 10px; text-align: center; opacity: 0; font-family: "Subtitle CJK", sans-serif; }}
    .captions-en {{ font-size: 38px; line-height: 1.25; color: #ECEEF2; font-weight: 600; max-width: 1680px; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
    .captions-zh {{ font-size: 34px; line-height: 1.3; color: #C9CED8; font-weight: 400; max-width: 1680px; text-shadow: 0 2px 6px rgba(0,0,0,0.6); }}
  </style>
  <div id="root" data-composition-id="captions" data-width="1920" data-height="1080" data-duration="{total}">
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
