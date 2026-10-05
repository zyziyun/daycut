# PORT_NOTES — cover

## Sources
- `content-skills/skills/cover-design` (SKILL.md, `templates/cover_face_quadrants.template.html`,
  `scripts/extract_collage_frames.sh`, `scripts/matte_one.py`).
- Pattern C generalized from a project-local `make_cover.py` (xhs-explainer-promo) into `scripts/split_cover.py`
  + JSON config. Its real quote, attribution, title copy and photo were replaced by synthetic placeholders.

## What changed / dropped
- `matte_one.py` (RVM only) → `scripts/matte.py`: **default engine is MediaPipe selfie segmenter**
  (`vstudio.config.model("selfie_segmenter")`) + guided-filter refinement. RVM kept as `--engine rvm`,
  **GPL-3.0, not vendored**, loaded by `torch.hub` at runtime (clearly labelled in code and docs).
  Added `--crop-bottom`, `--trim`, `--preview`, CUDA support.
- `extract_collage_frames.sh` (hard-coded 1080×1920 pixel crops) → `scripts/extract_frames.py` with
  `sheet` (contact sheet to pick frames), `collage` (fraction-based crops on the decoded frame), `face`.
- Hard-coded `/Applications/Google Chrome.app` → `scripts/render_html.py`: `$CHROME`, PATH names, per-OS install
  paths, skips broken binaries (seen: a homebrew chromium exiting 126), Playwright fallback.
  It also copies repo fonts into `assets/fonts/` and injects persona brand colours as CSS vars.
- Templates: system-ui/SF fonts → `@font-face` Noto Sans SC; teal hard-codes → `var(--accent, #2dd4bf)` +
  `color-mix` tints; real video copy (ChatGPT/LLM/Transformer) → neutral placeholders.
- `cover_collage.template.html` was referenced by the source SKILL.md but missing; written new from the
  described structure (2×2 stills, two accent slashes, centre diamond + play glyph, badges, headline, pills).
- `qlmanage` previews dropped (macOS-only); `matte.py --preview` writes a checkerboard composite instead.
- `make_cover.py` pieces kept as config: quote, title with highlights, thumbnail, chips, stamp (亲测), corner tag
  (记笔记 ↓), multi-size outputs, photo lift. Added: face-centred crop (`vstudio.face`), auto-shrinking title/quote,
  optional in-place retouch via `vstudio.retouch`.
- Smoke-tested: matte (mediapipe), extract_frames sheet/collage, collage template render, split_cover both sizes
  (on synthetic test-pattern images; no real face verified for matte quality).

## Capabilities
cover, retouch, other (matting / segmentation, HTML→PNG render, contact sheet).

## Duplicates for phase 2 (`lib/vstudio`)
- `scripts/render_html.py:find_chromes/render/stage_fonts/inject_persona` — headless Chrome render; also copied as
  `workflows/slides/scripts/render_html.py` (identical). Strong candidate for `vstudio.render`.
- `scripts/matte.py:matte_mediapipe/guided` — person segmentation (talking-head / privacy-mask workflows likely
  have their own selfie-segmenter wrapper). `matte_rvm` likewise.
- `scripts/extract_frames.py:grab/cmd_sheet` — frame grab + contact sheet (cover pickers in other workflows).
- `scripts/split_cover.py:build` — PIL cover compositor (other workflows render covers too).

## Persona keys used
- existing: `brand.accent`, `brand.highlight`, `brand.ink`, `brand.ground`, `platforms.*.title_max` (doc only).
- new: none.

## Platform-specific / unverified
- `--engine rvm` not run here (needs torch + network); code path identical to the source except device selection.
- `color-mix()` needs Chrome ≥ 111.
- Pattern C layout is landscape only (photo left / panel right); a portrait variant would need a new layout.
