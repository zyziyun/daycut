# PORT_NOTES — slides

## Source
- `content-skills/skills/vertical-slide-design` (SKILL.md, `templates/slides_vertical.template.html`,
  `scripts/render_slides.sh`, `scripts/record_slides_anim.py`).

## What changed / dropped
- `record_slides_anim.py` hard-coded the deck URL and output dir under the creator's Desktop and a fixed shot list
  → `scripts/record_slides.py html out KEY:SECONDS...` (`--size`, `--fps`); CRF from `persona.export.crf`;
  bt709 tags; temp dir instead of `/tmp/slide_records`.
- `render_slides.sh` (hard-coded `/Applications/Google Chrome.app`) → `scripts/render_slides.py` using
  `scripts/render_html.py` (portable Chrome lookup, Playwright fallback, font staging, persona colour injection).
- Template: system/SF font stack → `@font-face` Noto Sans SC; teal hard-codes → `var(--accent, #2dd4bf)` +
  `color-mix()` tints; SVG arrow colour read from the CSS var. Real video copy (ChatGPT / LLM / Transformer /
  Context, "follow for more AI breakdowns" outro with emoji) → neutral placeholders; the outro now follows the
  no-generic-CTA rule. The generic textbook diagram examples (next-token bars, "the cat sat on the mat" arrows,
  chat re-send stack) are kept as demos of the presets. Arrow drawing triggers on any key ending `_attn`
  (was the literal `09_attn`); keys renamed `06_bars`, `04_a_sec`, etc.
- Dropped: the "Descript Chapter Title Split" assumption as a requirement (kept as one target among several).
- Smoke-tested: PNG render of 3 slides incl. the JS arrow diagram (persona accent applied).
  `record_slides.py` only `--help`-tested: Playwright's Chromium isn't installed on this machine (not downloaded).

## Capabilities
screenshot-cards, overlays, transitions (CSS animated diagram clips), other (HTML→PNG slides).

## Duplicates for phase 2 (`lib/vstudio`)
- `scripts/render_html.py` — identical copy of `workflows/cover/scripts/render_html.py` (Chrome lookup, font staging,
  persona CSS injection). Unify into `vstudio.render`.
- `scripts/record_slides.py:record_one` — Playwright record + webm→mp4 (HyperFrames workflows have their own renderer).

## Persona keys used
- existing: `brand.accent` (and highlight/ink/ground injected as CSS vars), `export.crf`.
- new: none.

## Platform-specific / unverified
- Animated recording path unverified here (needs `playwright install chromium`).
- `color-mix()` needs Chrome ≥ 111.

## Phase 2b rewire
Swaps (old → new):
- `scripts/render_html.py` → **deleted**; `render_slides.py` calls `vstudio.render.html_to_png(..., query="export=<key>")`;
  standalone renders use `python3 -m vstudio.render`.
- `record_slides.py`: `stage_fonts/inject_persona` → `render.stage_fonts` + `render.inject_css(persona_css())`;
  webm→mp4 encode → `media.run` + `media.delivery_args(audio=False, preset="slow", fps=...)` (CRF from persona
  export.crf).
Behaviour changes: recorded MP4s now also get H.264 High profile, `color_range tv` and bt709 in the H.264 VUI
(h264_metadata bsf) — previously container tags only. Font staging/persona CSS as in cover's notes.
Tests: `render_slides.py` on the template (01_title, 06_bars, 09_attn) — pixel-identical to the phase-1 render
(mean abs diff 0.0 on 09_attn incl. the JS arrows); py_compile + `--help` for both CLIs; record path still
unverified (Playwright Chromium not installed); `pytest tests` green at the time (current count: run it; see tests/).
Lib requests: none.

## Wave B
Changes:
- **Accent regression fix.** Phase 2b injected persona `brand.accent` (red for many creators) as `--accent`, which the
  template used, so slides turned red. Template `--teal` is now `var(--slides-accent, #2dd4bf)`; both scripts inject
  `--slides-accent` from persona `slides.accent` (default `#2dd4bf`) or `--accent "#hex"`. brand.accent is no longer
  read by slides. Injection = a sibling temp copy `<stem>.slides.html` (same dir, so fonts resolve), removed after.
- **Platforms** (`scripts/slide_frame.py`, shared): `--platform`, `--layout split|full` (default split), `--size`
  override. Split → square, side = min(profile canvas) (1080x1080 without a platform). Full → profile canvas, and
  `--safe-top/right/bottom/left` (max(60, safe margin); right also clears `keepouts`) + `--footnote-bottom`
  (max(54, safe bottom + 24)) injected; full without `--platform` uses persona `platforms.default`.
- Template: `body` 1080x1080 → `100vw/100vh`; `.slide` padding / `.s-sec` padding-top / `.footnote` read the safe vars
  with the old values as fallbacks; `.sentence` font-size `min(42px, safe width / 21)` (42 px in the square layout;
  shrinks on 抖音 where the button column narrows the safe width to 840 px).
- Fixes: `_attn` arrows now wait for `document.fonts.ready` (HEAD placed arrows before/after the font swap at random:
  two HEAD renders of 09_attn differed by up to 212/255); `render_slides.py` key discovery skips HTML comments
  (the template's comment produced a blank `slide_NN_name.png`).
Tests (outputs in /tmp/slides-waveb/, not committed):
- Default render of all 15 template slides vs HEAD scripts+template run with `--no-persona` (teal fallback, i.e. HEAD
  with the accent forced to teal): max abs diff 0 on every slide (09_attn equals the post-font-load HEAD state; 3
  repeat renders identical). HEAD default renders are red (255,36,66) since persona brand.accent = #FF2442.
- Accent pixels: new default 01_title/04_a_sec dominant accent = (45,212,191); `--accent "#ff8800"` → (255,136,0).
- `--platform xiaohongshu:vertical --layout full` → 15 PNGs 1080x1440, union content bbox (60,367)-(960,1265) inside
  safe box (48,60,1032,1290), no pixels in the keep-out. `--platform douyin --layout full` → 1080x1920, union bbox
  (60,512)-(900,1455) inside (60,160,930,1480) and clear of the (900,900)+ button column. `--platform youtube
  --layout full` (2 slides) 1920x1080 inside the safe box. `--platform youtube` (split) → 1080x1080.
- py_compile, `--help` both CLIs; `record_slides.py` run reached Playwright and failed only on the missing Chromium
  download (temp page cleaned up) — recording itself still unverified.
New persona keys: `slides.accent` (default `#2dd4bf`).
Lib requests:
- `vstudio.render.html_to_png(..., extra_css=None)` (or `persona_css(extra=...)` passthrough) so workflows can inject
  their own :root vars without writing a second temp copy.
