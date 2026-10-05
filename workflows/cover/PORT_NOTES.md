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

## Phase 2b rewire
Swaps (old → new):
- `scripts/render_html.py` (whole file) → **deleted**; `python3 -m vstudio.render page.html -o out.png` (same flags:
  `--size --query --wait --no-persona`, plus `--scale --transparent`). No shim: WORKFLOW.md/templates now call the module.
- `split_cover.py:build/draw_title/face_center_x/rgb/F/tw` → `vstudio.cover.split_cover`; the script is now a JSON
  shim (config format unchanged: photo, retouch, retouch_force, photo_lift, face_x, quote, title, thumbnail, chips,
  stamp, corner_tag, colors, glow, photo_shift, outputs[{path, size, photo_w, photo_shift, quality}]). Outputs may also
  use `"aspect": "4:3"|"16:9"|"3:4"` (3:4 = new portrait stacked layout). Retouch caching (`*.retouched.png`) kept locally.
- `extract_frames.py:grab` → `media.grab_frame` (frame-accurate preroll seek instead of fast `-ss`);
  `cmd_sheet`/`duration` → `media.contact_sheet`; new `pick` subcommand → `cover.score_frames` + `cover.contact_sheet`.
- `matte.py` unchanged (MediaPipe / RVM engines stay local, out of lib scope).
Behaviour changes:
- split cover: per-output `fade`/`overlap` keys are no longer honoured (lib uses fixed 220/40 px × scale); plain-string
  chips after the first are drawn `dim` (dict chips unchanged); quote→title spacing follows the quote height instead
  of a fixed y; photo crop scales to fill (identical for photos taller than the cover). Visual diff on the synthetic
  config: same layout, thumbnail a few px taller.
- `sheet` no longer writes full-size `cand_<t>.png` unless `--save-frames` (the sheet is a single decode pass now).
- Font staging copies installed font roles (`config.FONTS`) instead of every file in FONT_DIR; persona CSS injects all
  hex `brand.*` keys (superset of accent/highlight/ink/ground).
Tests: collage + face-quadrant templates rendered via `vstudio.render` (collage pixel-identical to the old render_html,
mean abs diff 0.0); split_cover 4:3 + 16:9 (synthetic photo/thumbnail) and a 3:4 aspect output; extract_frames
sheet (+`--save-frames`), collage, face on a lavfi clip; `pick` exits cleanly with no face; py_compile + `--help`
for all 3 CLIs (+ matte.py); `pytest tests` 34 passed.
Lib requests: `cover.split_cover` could accept `fade`/`overlap` (photo fade width, panel overlap) to keep per-output
tuning.
