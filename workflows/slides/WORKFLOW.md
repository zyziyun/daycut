# slides — square slides for vertical short-form video

**Use when:** a locked script (see `workflows/preproduction`) needs 10–15 visual slides to pair with talking-head
footage in a vertical video — dropped into Descript's chapter-title split, a CapCut/剪映 top-half layout, or a
HyperFrames composition. **Inputs:** the script + a slide plan. **Outputs:** `slide_<key>.png` (1080×1080) per slide,
plus ≤3 `slide_<key>.mp4` animated diagram clips.

Run from the project folder; `$VSTUDIO` = repo root.

## Prerequisites
- `./install.sh` (fonts). Chrome/Chromium/Edge for PNGs (found via `$CHROME`, PATH or standard install paths).
- Animated clips only: `pip install playwright && playwright install chromium`.

## Pipeline

1. **Slide plan.** One slide every 6–12 s of narration → 10–14 slides for a 90 s short. Typical order:

   | # | Preset class | Purpose |
   |---|---|---|
   | 01 | `s-title` | hook headline (same sentence as the spoken hook and the cover) |
   | 02 | `s-contrast` | the misconception / "you" framing |
   | 03 | `s-three` | optional preview of the 3 parts |
   | 04, 08, 11 | `s-sec` | section headers: giant accent number + word |
   | 05, 10 | `s-punch` | one big sentence per idea (optional eyebrow) |
   | 06, 09, 13 | `s-bars`, `s-attn`, `s-ctx` | diagrams: the visual proof (bars, arrows, stack) |
   | 12 | `s-nomem` | one giant word |
   | 14 | `s-recap` | key → value rows |
   | last | `s-outro` | the closing lens (no generic CTA) |

2. **Write the deck.** `cp $VSTUDIO/workflows/slides/templates/slides_vertical.template.html work/slides.html`.
   One `<section class="slide <preset>" data-key="NN_name">` per slide; reuse the presets (they cover ~90 % of needs)
   and only add a class when a slide is structurally new. Open it in a browser: keys `1–9, 0, q–t` flip slides.
3. **Render PNGs.**
   `python3 $VSTUDIO/workflows/slides/scripts/render_slides.py work/slides.html work/slides/`
   (all `data-key`s by default; list keys to re-render a few; `--size 1080x1920` for full-frame slides).
4. **Optional: animated diagrams (max 3 per video).**
   `python3 $VSTUDIO/workflows/slides/scripts/record_slides.py work/slides.html work/slides/ 06_bars:3.4 09_attn:4.0 13_resend:4.2`
   The narration over each animated slide must be at least as long as the recording, or it loops/freezes early.
5. **Place on the timeline** in key order (`slide_NN_*` sorts deterministically).

## Design language
- Black ground, white text, grey dims, **one accent**: `var(--accent)` injected from `persona.brand.accent` by
  `vstudio.render` (`--no-persona` keeps the template's original teal `#2dd4bf`). Tints use `color-mix()`.
  Use the same accent as the cover (`workflows/cover`) so the channel reads as one design.
- Fonts via `@font-face` on `assets/fonts/` (copied from the repo font cache at render time; Noto Sans SC covers CJK).
- Square 1080×1080 because the slide region of a split layout is roughly square and degrades gracefully to 4:5.

## Gotchas (each from a real revision)
- **CSS `var()` does not interpolate inside `@keyframes`.** `to{width:var(--tgt)}` jumps or does nothing. Write
  explicit `from{width:0} to{width:87%}` per element and use fill-mode `both`.
- Add the `animate` class two `requestAnimationFrame`s after load so frame 0 is the start state, not mid-animation.
- Show slides with the `.on` class (`display:flex`), not inline `display` toggles; it composes with animations.
- Sentence-in-a-diagram text: `white-space:nowrap` and size it to fit. A wrapped line breaks arrows/overlays.
- Arrow diagrams are drawn by JS after layout: give their key an `_attn` suffix and keep `--wait ≥ 1500` ms.
- No emojis in headings (inconsistent across renderers); OK inside chat-bubble examples.
- Eyebrow pattern for section labels: `<div class="eyebrow"><span class="dot"></span>NAME</div>`.

## Self-check
- [ ] Every PNG is exactly the target size; nothing overflows
- [ ] Section headers use the giant-number pattern; eyebrows use the standard pattern
- [ ] Keyframes use explicit from/to values, no `var()` inside
- [ ] ≤3 animated slides; each covered by enough narration
- [ ] Files named `slide_NN_name.{png,mp4}`
