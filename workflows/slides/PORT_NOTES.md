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
