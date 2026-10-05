# PORT_NOTES — call-clips

## Source
`~/.claude/skills/zoom-guest-mask` (SKILL.md, 16 scripts, 2 example configs, 6 assets), read-only.
Generalised from "two-person Zoom, hide the friend" to any multi-person call / interview /
podcast recording → short clips with optional masking of chosen participants.

## What changed
- **Model path**: `track_face.py`, `speaker_timeline.py` → `vstudio.config.model("face_landmarker")`
  (original detector options kept so tracking behaviour is unchanged; `track_face --model` still
  overrides); `make_thumb.py` host-face lookup → `vstudio.face.landmarker()` + `detect()`
  (its 0.4 confidence thresholds differ slightly from the old defaults; only affects the thumb crop).
- **Fonts**: all Hiragino paths removed. New `scripts/style.py` is the single font/colour/label
  source for every renderer, cover and thumb (`font("cjk-bold" | "cjk")` via vstudio).
- **Personal content removed**: the real meeting path, conversation text, panels and labels in
  both example configs → synthetic `examples/clips*.example.json` with placeholder dialogue;
  "Wendy" defaults in the trio renderers → `host_label` from config (top-level or per clip),
  else persona `call_clips.labels.host`, else "Host". SKILL.md anecdotes (names, employers,
  the conversation's topics) dropped from the docs; the lessons kept in generic form.
- **TERM_FIX**: creator/recording-specific entries (a product name, an employer's name and its
  Chinese mishearings, several one-off sentence corrections) removed from code. They belong in
  `persona.local.yaml → subtitles.term_fixes` (regex keys) or `clips.json → term_fix`.
  Generic code-switch fixes (figure out, reasoning, Appendix, sign off, review, 思维导图 …) kept.
  Order: clips.json → persona → shared list.
- **Paths**: `build_clips.py` no longer assumes it runs from the skill dir — sibling scripts and
  `assets/…` / `render_trio.py` resolve relative to the workflow; uses `sys.executable`.
- **Hard-coded taste → persona** (with safe defaults): loudnorm target (`audio.loudness_lufs`),
  panel/badge colours (`brand.accent`, `brand.highlight`), speeds and hook gain, frame accent,
  on-frame labels.
- **Added**: `--no-mask` (build_clips, render_vertical, render_landscape) so masking is truly
  optional; `transcribe.py` (mlx_whisper → faster_whisper fallback; the old doc only had an
  mlx CLI line); `transcript_tools.py` (outline / speaker runs / tiling coverage / editor-pass dump /
  privacy grep — all were ad-hoc snippets in SKILL.md); `render_sticker.py` (HTML → transparent
  PNG via Chrome/Chromium or Playwright); `render_landscape.py --crop-w` (was a constant measured
  on one recording); `make_thumb.py --scale/--y-offset`; `find_disfluencies.py --extra/--json`.
- **Fixed**: `export_srt.ts()` could print `,1000` ms; `build_clips` now surfaces a failing
  subprocess's stdout (verify_coverage prints FAIL there); `render_landscape` accepts plain
  `text` subs when no translation exists.
- **find_disfluencies.py**: algorithm untouched; full docstring (rules, thresholds, API, language
  notes, editor-cut format). Note `PAUSE_KEEP` is unused (kept breath = 2×`PAUSE_EDGE`).

## Assets (provenance)
`cat_sticker.html`, `dog_sticker.html`, `cat_avatar.html` are hand-written in-house SVG. The PNGs
match them exactly (512×512 / 960×540; opaque extents 45–466 × 41–432 px = the SVG head ellipse
`256,272 r176×158` + whiskers/ears; same mtimes as their HTML) → generated in-house from the
included HTML, **kept**. Avatar HTML's Hiragino font-family → "Noto Sans SC, sans-serif".

## Dropped
- `__pycache__/`. Nothing functional dropped.
- The full-tile **avatar renderer** was not in the source (only `cat_avatar.*` + `verify_avatar.py`,
  and `build_clips --no-track`); kept as-is, so the avatar layout needs a renderer before use.

## Capabilities
cut, filler-dedup, pause-squeeze (find_disfluencies), asr, captions, bilingual, speed, loudness,
face-track, privacy-mask (sticker + geometric coverage proof, avatar verifier), overlays
(node cards, hook badge, name chips), notes-panels, hook, transitions (xfade/acrossfade),
progress-bar (chapters computed in title json; not drawn by these renderers), cover, long-to-short,
episodes (tiling), other (speaker attribution from lip motion, quote cards, YouTube thumbnails,
srt export, editor-pass tooling).

## Duplicates for phase 2 (→ lib/vstudio)
- `find_disfluencies.py`: `Audio`, `find_cuts`, `split_window` — promote as the shared
  stumble/气口 remover.
- `build_clips.py:cut_piece` / `offsets_of` / `dissolve` — speed + xfade timeline assembly.
- `build_clips.py:load_subs` + `src_to_final` — source→final subtitle/panel time-mapping.
- `build_clips.py` loudnorm block — two-pass loudnorm + bt709 VUI/faststart export.
- `transcribe.py:run_mlx/run_faster` — whisper wrapper.
- `build_subs.py:fix` + `TERM_FIX` — term-fix pass.
- `render_vertical.py:render_panel` and `render_landscape.py:render_panel` — 记笔记 panel
  (duplicate of the talking-head notes panel); `_wrap`/`_toks`, `wrap_sub`/`wrap`, `render_sub`
  — CJK-aware wrapping and subtitle strips; `alpha_paste` (in 3 files + apply_sticker).
- `render_*:render_node_card`, `render_hook_badge`, `render_chip` — overlay furniture.
- `track_face.py` (fill_gaps/ema) and `speaker_timeline.py:mouth_gap` — face tracking / talk
  detection; overlaps `vstudio.face`.
- `make_cover.py`, `make_thumb.py`, `make_thumb_trio.py` — cover/thumbnail rendering.
- `export_srt.py:ts/write` — SRT writer.
- `render_sticker.py:find_chrome` — headless Chrome lookup.

## New persona keys (all optional, defaults in code)
`call_clips.body_speed` (1.2), `call_clips.hook_speed` (1.35), `call_clips.hook_gain_db` (3.0),
`call_clips.sticker` ("assets/cat.png"), `call_clips.frame_accent` ("#2DD4BF"),
`call_clips.labels.{hook_badge, hook_badge_landscape, node_eyebrow, note_tag, guest, host}`.
Existing keys read: `audio.loudness_lufs`, `brand.accent`, `brand.highlight`,
`subtitles.term_fixes`, `creator.language`.

## Platform-specific / unverified
- Smoke-tested on a synthetic test-pattern video only: full `build_clips --no-mask` run,
  previews of all four renderers, cover, both thumbs, apply_sticker, verify_coverage, model
  loading in track_face/speaker_timeline. **Not** re-run on a real call with faces (no media
  in repo), so a tracked + masked end-to-end build is unverified after the port.
- `transcribe.py` faster_whisper branch and `render_sticker.py` Playwright branch untested.
- Noto Sans SC replaces Hiragino: glyph widths differ slightly, so panel/title fits that were
  tuned by eye may wrap differently — check `--preview` frames.
- `render_vertical.py` still has the pre-safe-zone layout (as in the source).
- `FILLERS`/`EMPHASIS` in find_disfluencies and on-frame default labels are Mandarin.
