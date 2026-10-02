#!/usr/bin/env python3
"""Assemble index.html: shared ground, scene sub-compositions with transitions, captions, voice, music.

Usage:  python3 make_index.py [--patch-scenes]
Reads   scenes.config.json (ids + "transition": [type, seconds] for each scene after the first),
        audio/scenes.json, compositions/<id>.html, compositions/captions.html,
        audio/narration.wav, optional audio/bgm.wav
Writes  index.html

Transition types: blur, fade, push, vpush, iris, zoom, focus, blocks, chroma, flip, zoomout.
A transition overlaps two scenes, so the OUTGOING scene must live `d` seconds longer than its
window. --patch-scenes rewrites each scene file's own data-duration (root + stage clip) to match;
without it the outgoing scene goes blank the moment the transition starts.
After regenerating, re-run the music carve:
  node <hyperframes-audio>/scripts/carve.mjs --comp index.html --bed bgm --voice narration --strength 0.8
"""
import json, os, re, sys
S = json.load(open("audio/scenes.json")); total = S["total"]
CFG = json.load(open("scenes.config.json"))["scenes"]
IDS = [c["id"] for c in CFG]
TR = {k + 1: tuple(c["transition"]) for k, c in enumerate(CFG) if k > 0 and c.get("transition")}
if "--patch-scenes" in sys.argv:
    for k, (w, fid) in enumerate(zip(S["scenes"], IDS)):
        ext = TR[k + 2][1] if k + 2 in TR else 0
        p = f"compositions/{fid}.html"; s = open(p).read()
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
trans = [{"n": n, "o": "w-" + IDS[n - 2], "i": "w-" + IDS[n - 1], "type": t, "d": d, "T": S["scenes"][n - 1]["start"]} for n, (t, d) in TR.items()]
bgm = ""
if os.path.exists("audio/bgm.wav"):
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
      .scene-wrap {{ position: absolute; inset: 0; width: 1920px; height: 1080px; transform-origin: 50% 45%; }}
      #tx-blocks {{ position: absolute; inset: 0; z-index: 40; pointer-events: none; display: flex; }}
      .tx-block {{ flex: 1; height: 100%; background: #111A33; border-right: 1px solid #1B2645; transform-origin: 50% 0%; }}
      #ground {{ position: absolute; inset: 0;
        background: radial-gradient(ellipse 80% 70% at 50% 40%, #111830 0%, #0B1020 60%, #080C18 100%); }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-width="1920" data-height="1080" data-duration="{total}">
      <div id="ground" class="clip" data-start="0" data-duration="{total}" data-track-index="1"></div>
{chr(10).join(hosts)}
      <div id="tx-blocks">{"".join('<div class="tx-block"></div>' for _ in range(8))}</div>
      <div id="captions" style="position:absolute;inset:0;z-index:50" data-composition-id="captions" data-composition-src="compositions/captions.html" data-track-kind="captions"
        data-start="0" data-duration="{total}" data-track-index="5" data-width="1920" data-height="1080"></div>
      <audio id="narration" src="audio/narration.wav" data-start="0" data-duration="{total}" data-track-index="8" data-volume="1"></audio>
{bgm}    </div>
    <script>
      const tl = gsap.timeline({{ paused: true }});
      const TR = {json.dumps(trans)};
      const ID = {{ x: 0, y: 0, scale: 1, rotationY: 0, opacity: 1, filter: "blur(0px)", clipPath: "circle(150% at 50% 45%)" }};
      document.querySelectorAll(".scene-wrap").forEach((w) => tl.set(w, ID, 0));
      tl.set(".tx-block", {{ scaleY: 0 }}, 0);
      const IR = {{ immediateRender: false }};
      TR.forEach((t) => {{
        const o = "#" + t.o, i = "#" + t.i, T = t.T, d = t.d;
        switch (t.type) {{
          case "blur":
          case "fade": {{
            const b = t.type === "blur" ? 10 : 0;
            tl.to(o, {{ opacity: 0, filter: `blur(${{b}}px)`, duration: d, ease: "sine.inOut" }}, T);
            tl.fromTo(i, {{ opacity: 0, filter: `blur(${{b}}px)` }}, {{ opacity: 1, filter: "blur(0px)", duration: d, ease: "sine.inOut", ...IR }}, T);
            break; }}
          case "push":
            tl.to(o, {{ x: -1920, filter: "blur(4px)", duration: d, ease: "power3.inOut" }}, T);
            tl.fromTo(i, {{ x: 1920, filter: "blur(4px)" }}, {{ x: 0, filter: "blur(0px)", duration: d, ease: "power3.inOut", ...IR }}, T);
            break;
          case "vpush":
            tl.to(o, {{ y: -1080, opacity: 0.4, duration: d, ease: "power3.inOut" }}, T);
            tl.fromTo(i, {{ y: 1080 }}, {{ y: 0, duration: d, ease: "power3.inOut", ...IR }}, T);
            break;
          case "iris":
            tl.to(o, {{ scale: 0.94, opacity: 0, duration: d, ease: "power2.inOut" }}, T);
            tl.fromTo(i, {{ clipPath: "circle(0% at 50% 45%)" }}, {{ clipPath: "circle(150% at 50% 45%)", duration: d, ease: "power2.in", ...IR }}, T);
            break;
          case "zoom":
            tl.to(o, {{ scale: 1.8, opacity: 0, filter: "blur(10px)", duration: d, ease: "power3.in" }}, T);
            tl.fromTo(i, {{ scale: 0.7, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: d, ease: "power3.out", ...IR }}, T + d * 0.25);
            break;
          case "focus":
            tl.to(o, {{ filter: "blur(16px)", opacity: 0, scale: 1.04, duration: d, ease: "power2.inOut" }}, T);
            tl.fromTo(i, {{ filter: "blur(16px)", opacity: 0, scale: 0.97 }}, {{ filter: "blur(0px)", opacity: 1, scale: 1, duration: d, ease: "power2.inOut", ...IR }}, T + d * 0.3);
            break;
          case "blocks": {{
            const h = d / 2;
            tl.fromTo(".tx-block", {{ scaleY: 0, transformOrigin: "50% 0%" }}, {{ scaleY: 1, duration: h, ease: "power3.in", stagger: 0.035, ...IR }}, T);
            tl.to(o, {{ opacity: 0, duration: 0.01 }}, T + h + 0.25);
            tl.fromTo(i, {{ opacity: 0 }}, {{ opacity: 1, duration: 0.01, ...IR }}, T + h + 0.25);
            tl.to(".tx-block", {{ scaleY: 0, transformOrigin: "50% 100%", duration: h, ease: "power3.out", stagger: 0.035 }}, T + h + 0.3);
            break; }}
          case "chroma": {{
            const k = [8, -12, 6, -4, 0];
            const sh = (a) => `drop-shadow(${{a}}px 0 0 rgba(252,98,85,0.75)) drop-shadow(${{-a}}px 0 0 rgba(88,196,221,0.75))`;
            tl.to(o, {{ opacity: 0, duration: d * 0.6, ease: "steps(4)" }}, T);
            tl.fromTo(i, {{ opacity: 0, x: 18 }}, {{ opacity: 1, x: 0, duration: d * 0.6, ease: "steps(5)", ...IR }}, T + d * 0.15);
            k.forEach((a, j) => tl.set([o, i], {{ filter: a ? sh(a) : "none" }}, T + j * d / 5));
            break; }}
          case "flip":
            tl.to(o, {{ rotationY: -90, transformPerspective: 1600, opacity: 0.2, duration: d / 2, ease: "power2.in" }}, T);
            tl.fromTo(i, {{ rotationY: 90, transformPerspective: 1600, opacity: 0.2 }}, {{ rotationY: 0, opacity: 1, duration: d / 2, ease: "power2.out", ...IR }}, T + d / 2);
            tl.set(i, {{ opacity: 0 }}, T);
            break;
          case "zoomout":
            tl.to(o, {{ scale: 0.86, opacity: 0, filter: "blur(6px)", duration: d, ease: "power2.inOut" }}, T);
            tl.fromTo(i, {{ scale: 1.08, opacity: 0 }}, {{ scale: 1, opacity: 1, duration: d, ease: "power2.out", ...IR }}, T + d * 0.3);
            break;
        }}
      }});
      window.__timelines["main"] = tl;
    </script>
  </body>
</html>
'''
open("index.html", "w").write(html)
print("index:", len(hosts), "scenes, total", total)
