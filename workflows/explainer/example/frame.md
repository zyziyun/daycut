# frame.md — design truth: "Quantization, explained" (3Blue1Brown-inspired)

Canvas 1920×1080, 30 fps. Dark chalkboard math: a calm navy ground, thin white lines, colour-coded symbols, serif italic math, mono numbers. Motion explains, never decorates.

## Palette (by role)

| token | hex | role |
|---|---|---|
| canvas | `#0B1020` | full-bleed ground (painted by the assembler on index `#root`; scenes do NOT paint their own ground) |
| ink | `#ECEEF2` | primary lines, ticks, plain text |
| dim | `#6B7488` | axes, secondary labels, scene titles |
| faint | `#2A3247` | dividers, table rules |
| card | `#121A30` | card fill (frame 16 only) |
| x / value | `#58C4DD` | real values, weights, dots |
| s / scale | `#F4D35E` | the scale s, step sizes, highlights |
| z / zero-point | `#5CD0B3` | the zero-point z, "good" outcomes |
| q / integer | `#E88CC4` | integers, tick indices |
| error | `#FC6255` | error, outliers, warnings |

One colour = one meaning for the whole film. Never use a math colour decoratively.

## Type

All fonts ship as files; declare `@font-face` inside each scene template with these exact paths (paths are project-root-relative: `assets/fonts/...` — never `../`):

```css
@font-face { font-family: "STIX Two Text"; src: url("assets/fonts/stix-two-text.ttf"); font-style: normal; font-weight: 400 700; }
@font-face { font-family: "STIX Two Text"; src: url("assets/fonts/stix-two-text-italic.ttf"); font-style: italic; font-weight: 400 700; }
```

`JetBrains Mono` is bundled by the HyperFrames renderer (weights 400, 700) — name it directly, no `@font-face` needed.

| role | family | size (px) |
|---|---|---|
| scene title (top-left, x=120, baseline y=110) | STIX Two Text italic, `dim` | 44 |
| display math / formulas | STIX Two Text (variables italic, coloured by role) | 56–92 |
| numbers, labels, tick indices, tables | JetBrains Mono | 24–56 |
| emphasis line | STIX Two Text italic | 34–64 |

No sans-serif in scenes. No emoji. No icons.

## Components

- **Ruler**: horizontal axis line (`dim`, 3px) + vertical ticks (`ink`, 3px, ±22px) + optional pink mono indices 62px below. Reused in frames 06–10, 12–13, 18; when two consecutive frames use it, keep it at the same y (470 in frames 07–08).
- **Dots**: filled circles r=9–13, `x/value` blue.
- **Equations**: built term by term; each symbol keeps its role colour (`x` blue, `s` yellow, `z` teal, `q` pink, error red).
- **Tables**: mono, rows separated by a 2px `faint` rule.
- **Pills/boxes**: 3px stroke in a role colour, no fill, radius 14 (boxes) or full (pills).

## Layout rules

- All scene content within y 80–800. **y > 840 is the subtitle band, owned by the root captions track — never place anything there.**
- The confirmed sketch for each frame is `storyboard/sketches/fNN.svg` (1920×1080 coordinates, identical to the canvas). Its bottom band (y ≥ 850, the dark strip with two text lines) is a stand-in for the captions track — do NOT build it.
- Use absolute positioning in canvas pixels matching the sketch; SVG inside a full-size 1920×1080 `<svg viewBox="0 0 1920 1080">` is the preferred way to draw rulers, lines, dots and charts.

## Motion

- Ease vocabulary: `power2.out` for entrances (0.5–0.9s), `power1.inOut` for moves, `back.out(1.6)` only for small pops (ticks, badges), `sine.inOut` for slow drifts. Line draws via `strokeDashoffset`.
- Reveal on the voiceover cue that names the thing (cue times given per scene, scene-local seconds). Entrances start ≤ 0.15s before the cue word.
- Keep a slow ambient drift (≤ 6px over the scene) on the main group so nothing is ever fully frozen, except the held final line of frame 18.
- No glow, no blur-heavy effects, no particles, no camera shake. No exits on non-final scenes.

## Bans

- No narration sentences on screen (captions own that). Short labels only, as drawn in the sketch.
- No background fill on `#root`; no full-bleed ground layer (the index paints `canvas`).
- No sans-serif, no emoji, no stock icons, no CSS transitions, no `Math.random`, no `repeat: -1`.
