# frame.md — design truth, PORTRAIT variant (vertical explainer short, 3Blue1Brown-inspired)

Copy this to the project's `frame.md` for a vertical short (`"platform": "xiaohongshu:full"` / `"douyin"` /
`"youtube-shorts"` / `"xiaohongshu:vertical"` in `scenes.config.json`). Palette, colour code, fonts, components,
motion vocabulary and bans are **the same as `design-truth.md`** (read it); only the canvas, layout and type
scale change. The exact boxes for the chosen platform are printed in every frame packet (`canvas json` line,
from `vstudio.platform`). The numbers below are for `xiaohongshu:full` 1080×1920 and are safe on every 9:16 profile.

Canvas 1080×1920 (9:16; 3:4 = 1080×1440, see the end), 30 fps. One idea per scene, read on a phone at arm's length.

## Layout (1080×1920)

| zone | y | what |
|---|---|---|
| platform top bar | 0–240 | nothing important (status bar, search, follow button cover it) |
| scene title | baseline ≈ 310, x = 90 | short eyebrow: "Step 1 · the scale s" |
| **math area** | 350–1370 | everything that explains: number lines, equations, tables, charts |
| button column | x > 900 for y > 960 | like / comment / share icons cover it — keep content left of x 900 there |
| caption band | 1420–1640 (box x 160–920) | bilingual captions, owned by the root captions track — never place anything here |
| platform description | > 1660 | nothing |

Portable 9:16 area (works for 小红书 full, 抖音, Shorts, TikTok without re-layout): x 150–930 above y 900,
x 150–880 below it, y 280–1190. Use it when one build has to ship to several vertical platforms.

- **Stack, don't spread.** A 16:9 scene that sits side by side becomes top-to-bottom: picture on top
  (number line, dots, chart), the equation or result under it, one emphasis line last.
- **Fill the math area, top to bottom.** At its most complete moment a scene's content spans ≥ 70 % of the math
  area's height (title strip → caption band) and its last element (the result / conclusion line) sits in the
  bottom fifth, just above the caption band. A 16:9 composition shrunk into the top half (big empty band above
  the captions, 20–30 px labels) is the classic failure: on a phone it reads as a thumbnail. Lay the stack out
  over the whole height first (picture ≈ upper 55 %, equation / result ≈ lower 45 %), then size things up until
  they fill it. The visual centre of mass sits near the middle of the math area (y ≈ 800–900 at 1080×1920).
- **Make the picture big.** The main graphic (grid, ruler, chart, diagram) is ≥ 80 % of the math-area width and
  ≥ 35 % of its height; grids of cells / dots get fewer, bigger cells rather than more, smaller ones.
- One ruler / chart per scene, ≤ 840 px wide (≤ 760 in the portable area). Never two equations side by side; break long ones over two lines
  at the `=`.
- **Check it:** `python3 scripts/layout_check.py` on the snapshots (taken at ~85 % of each scene) reports the
  content height / bottom gap per frame and warns below 60 % height or above 30 % empty bottom.
- A build for ONE platform uses that profile's math box from the packet's `canvas json` (小红书 full: y 350–1370),
  not the portable area: fill down to its bottom.
- Full-size `<svg viewBox="0 0 1080 1920">` (canvas coordinates = sketch coordinates), like the 16:9 scenes.

## Type (bigger than 16:9: the frame is viewed small)

| role | family | size (px) |
|---|---|---|
| scene title (x = 90, baseline 310) | STIX Two Text italic, `dim` | 56 |
| display math / formulas | STIX Two Text (variables italic, coloured by role) | 72–120 |
| numbers, labels, tick indices, tables | JetBrains Mono | 34–64 (never < 30) |
| emphasis line | STIX Two Text italic | 48–72 |
| captions (root track) | Subtitle CJK, EN 38 / 中文 48 bold, 2 lines max each | (make_captions.py) |

Cap height of the smallest readable text ≥ 1.6 % of 1920 (≈ 30 px). Check by scaling a snapshot to 480 px wide.

## Motion for shorts

- Hook in the first 2 s: the first visual lands by 0.3 s (no slow title fade-in on scene 1), the hook number
  or question is readable by 1.5 s.
- Faster entrances (0.35–0.6 s), a reveal every 2–4 s; no scene longer than ~14 s.
- No ambient drift requirement on scenes under 6 s; keep ≤ 4 px drift otherwise.
- Same bans as 16:9 (no glow, particles, shake, exits on non-final scenes).

## 3:4 (xiaohongshu:vertical, 1080×1440)

Title baseline ≈ 130, math area y 170–1030, caption band 1080–1270 (box x 120–960), button column x > 960
below y 900. Same type scale minus ~10 %. Same fill rule: the content runs from y ≈ 190 down to ≈ 1000; the picture takes the
upper ~55 %, the equation / result the rest (there is no room for a second picture).
