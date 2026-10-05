# slides — square slides for vertical short-form video

**Use when:** a locked script (see `workflows/preproduction`) needs 10–15 visual slides to pair with talking-head
footage in a vertical video — dropped into Descript's chapter-title split, a CapCut/剪映 top-half layout, or a
HyperFrames composition. **Inputs:** the script + a slide plan. **Outputs:** `slide_<key>.png` (1080×1080 by default, or a platform full-frame canvas) per slide,
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
   Check each slide before rendering: content centred, nothing overflowing the canvas, accent visible, diagram
   geometry intact (arrows land on their words, bars span correctly).
3. **Render PNGs.**
   `python3 $VSTUDIO/workflows/slides/scripts/render_slides.py work/slides.html work/slides/`
   (all `data-key`s by default; list keys to re-render a few; `--platform` / `--layout full` for full-frame
   slides, see [Platforms](#platforms); `--accent "#hex"` for a one-off accent).
4. **Optional: animated diagrams (max 3 per video).**
   `python3 $VSTUDIO/workflows/slides/scripts/record_slides.py work/slides.html work/slides/ 06_bars:3.4 09_attn:4.0 13_resend:4.2`
   The narration over each animated slide must be at least as long as the recording, or it loops/freezes early.
   Takes the same `--platform / --layout / --size / --accent` flags as `render_slides.py`. Output: H.264 yuv420p,
   `--fps` 25 (Playwright records ~25), CRF from persona `export.crf`. Animate only where motion *is* the
   explanation (bars growing, arrows drawing, a stack building); animating everything makes the video restless.
5. **Place on the timeline** in key order (`slide_NN_*` sorts deterministically): in `workflows/talkinghead` as
   `BROLL` entries with `mode="split"` (slide on top, speaker below) or `mode="cut"` for a full cut-away; in an
   external editor, drop them into the slide region of its split layout.

Not for: slides that need interactive editing (use Keynote / Figma / a slideshow tool), or full-screen landscape
lecture decks (use `--platform youtube --layout full` only for a few cut-aways; a long deck wants its own design).

## Design language
- Black ground, white text, grey dims, **one accent**: `--teal` = `var(--slides-accent, #2dd4bf)`. The scripts
  inject `--slides-accent` from persona `slides.accent` (default teal `#2dd4bf`); `--accent "#hex"` overrides it
  per run. `persona.brand.accent` is **not** used (it is the talking-head/promo accent, often 小红书 red); set
  `slides.accent` if you want slides to match it. Tints use `color-mix()`. Keep `slides.accent` equal to the cover
  accent (`workflows/cover`) so the channel reads as one design. `--no-persona` skips persona brand vars and
  `slides.accent` (accent = `--accent` or teal).
- Fonts via `@font-face` on `assets/fonts/` (copied from the repo font cache at render time; Noto Sans SC covers CJK).
- Square 1080×1080 by default because the slide region of a split layout is roughly square and degrades
  gracefully to 4:5. Full-frame per platform: see Platforms.

## Platforms
Flags (both scripts): `--platform NAME[:orientation]` (`xiaohongshu:vertical`, `douyin`, `tiktok`, `youtube`,
`youtube-shorts`, `bilibili:horizontal`; profiles from `vstudio.platform`), `--layout split|full` (default `split`),
`--size WxH` (always wins).

| flags | canvas | what changes |
|---|---|---|
| none / `--layout split` | 1080×1080 (side = min of the profile canvas, so 1080 for every built-in profile) | nothing: square slide, template padding 60 px |
| `--layout full --platform P` | the profile canvas (小红书 vertical 1080×1440, 抖音/TikTok/Shorts 1080×1920, YouTube/B站 1920×1080) | slide padding and footnote move inside `platform.safe_box`; the lower-right button column (`keepouts`) widens the right padding; the nowrap diagram sentence shrinks if the safe width is < 960 px |
| `--layout full` without `--platform` | persona `platforms.default` profile | as above |

Content keeps its pixel sizes (designed for 1080 wide); a full-frame slide is the square design centred in the
safe area, not scaled. Safe zones come from the profile (override in persona `platforms.<name>`).

Handing slides to a composition:
- **Vertical split** (talking head + slide): render square (default), place it in the top/bottom half of the
  1080×1920 / 1080×1440 composition; the composition owns the platform safe zones.
- **Full-frame vertical cut-aways**: `--platform douyin --layout full` (or `xiaohongshu:vertical`) gives a PNG at the
  exact canvas size: drop it on the timeline full-screen, no scaling.
- **Horizontal** (YouTube/B站): `--platform youtube --layout full` for full-screen slides, or keep the square and
  place it beside the speaker (left/right split).
- Multi-platform delivery happens on the finished video: `python -m vstudio.export master.mp4 --platforms ...`.

## Gotchas (each from a real revision)
- **CSS `var()` does not interpolate inside `@keyframes`.** `to{width:var(--tgt)}` jumps or does nothing. Write
  explicit `from{width:0} to{width:87%}` per element and use fill-mode `both`.
- Add the `animate` class two `requestAnimationFrame`s after load so frame 0 is the start state, not mid-animation.
- Show slides with the `.on` class (`display:flex`), not inline `display` toggles; it composes with animations.
- Sentence-in-a-diagram text: `white-space:nowrap` and size it to fit. A wrapped line breaks arrows/overlays.
- Arrow diagrams are drawn by JS after layout (and after `document.fonts.ready`, else arrows land on pre-font word
  positions in some renders): give their key an `_attn` suffix and keep `--wait ≥ 1500` ms.
- No emojis in headings (inconsistent across renderers); OK inside chat-bubble examples.
- Eyebrow pattern for section labels: `<div class="eyebrow"><span class="dot"></span>NAME</div>`.

## Self-check
- [ ] Every PNG is exactly the target size; nothing overflows
- [ ] Section headers use the giant-number pattern; eyebrows use the standard pattern
- [ ] Keyframes use explicit from/to values, no `var()` inside
- [ ] ≤3 animated slides; each covered by enough narration
- [ ] Files named `slide_NN_name.{png,mp4}`
