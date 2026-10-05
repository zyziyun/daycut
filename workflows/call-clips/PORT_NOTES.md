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

## Phase 2b rewire (onto lib/vstudio)

### Swaps (old → new)
- `find_disfluencies.py` `Audio/find_cuts/split_window/all_words/words_in/load_energy` + constants
  → `vstudio.cut` (promoted intact). The script is now a thin CLI, same args/output; its
  `--json` output is byte-identical to the old one on the synthetic run. build_clips imports
  from `vstudio.cut` directly.
- `build_clips.cut_piece/offsets_of/dissolve/_dissolve` → `cut.xfade_assemble` (plan) + local
  `_render/render_timeline` (one input-seeked read per piece, chunks of 30, same encode args).
  `src_to_final` and every meta[...] offset → the plan's `cut.TimeMap` (`to_final(tag="body")`,
  clip items' `dst0/dur/xfade`). `load_subs` keeps its per-piece/word logic but reads the TimeMap.
- loudnorm block → `audio.loudnorm_2pass` + `media.retag_bt709` (bt709 VUI, faststart, copy).
- `build_subs.fix/TERM_FIX/_load_persona_fixes` → `asr.apply_term_fixes`; regex entries not in
  the lib's generic list kept as `build_subs.CALL_TERM_FIXES` (call-site). `build_subs --config`
  (new, optional) applies a clips.json `term_fix`.
- `transcribe.run_mlx/run_faster` → `asr.transcribe(fix_terms=False)` (+ `media.extract_wav`);
  new optional `--prompt`; `--mlx-model/--faster-model` default to the lib's models.
- `export_srt.ts/write` → `subs.Cue.from_dict` + `subs.srt_write(which=text|alt|both)`.
- Renderers: `render_chip` → `overlays.chip(style="tag")`, `render_hook_badge` → `overlays.badge`,
  `render_node_card` → `overlays.node_card(theme={"accent": teal})`, `render_panel` + `_toks/_wrap`
  → `overlays.notes_panel` (sized to the old 940/880 px, 40/36 px bullets), `wrap_sub/wrap/
  render_sub` → `draw.text_layer(max_w=…)` (balanced CJK wrap), `alpha_paste` (4 copies incl.
  apply_sticker) → `draw.alpha_paste` via `style.alpha_paste`; `render_quote` wrap → `draw.wrap(
  balance=True)`; `style.font` → `draw.load_font`, `_hex` → `draw.rgb`.
- Covers/thumbs: cv2 seeks → `style.frame_at` (`media.grab_frame`, frame-accurate); make_thumb's
  hand-rolled sticker blend → `draw.alpha_paste`; `fit()` / size loops → `draw.fit_font`;
  `tw()` → `draw.text_width`. Layouts stay local (no lib equivalent of these designs).
- `render_sticker.find_chrome` + Chrome/Playwright code → `render.html_to_png(transparent=True,
  use_persona=False, fonts=False)` (nothing is staged into assets/).

### Behaviour changes (deliberate)
- `xfade_assemble(mute_pad=False)`: plain acrossfade as before. Muted pads would extend pieces
  into cut stumbles and silent redactions.
- Piece durations are whole frames: title.json `total`/offsets now match the encoded file (old
  drifted ~20 ms over 9 pieces); auto_trim seams land ≤1 frame differently. Timeline audio is now
  48 kHz stereo (was the source layout).
- load_subs: a line's late edge now stops at the midpoint of the OUTGOING dissolve (old used the
  piece's own incoming xfade, wrong when consecutive fades differ).
- Overlapping body windows: a source time maps to the LAST containing piece (was the first).
- Term fixes: persona `subtitles.term_fixes` are LITERAL now (regex → move to clips.json
  `term_fix`); order is term_fix → CALL_TERM_FIXES → persona → lib generic (old: persona before
  the shared list). `apply_term_fixes` also drops 嗯嗯 runs and 5+ repeated-char runs.
- loudnorm raises its LRA target to the measured LRA (stays linear); measured after 48 kHz stereo.
- Panels follow persona `brand.panel_theme` (default notes-red = old look; title now bold, long
  titles shrink instead of a WARN). Subtitle strips use balanced wrap; landscape chip/node card
  sizes within ~4 px of the old ones.
- export_srt writes a .zh.srt from `text` even when subs.json has no `zh` key (old wrote 0 cues).
- transcribe: lib settings (hallucination_silence_threshold, zero-length repeated words dropped),
  ASR cache `<out>.wav.asr.json`, default faster-whisper model large-v3-turbo (was large-v3).

### Test evidence (synthetic: 1280x720 testsrc2 + 16 kHz tone "speech" with pauses/restart/repeat/
filler, hand-made whisper JSON, clips.json with auto_trim, 1 hook, 3 windows, node card, null seam,
2 panels, 3 chapters, term_fix, translations; old code run from `git archive HEAD`)
- find_disfluencies `--json`: identical. build_clips `--no-mask` (vertical) end to end: same 5 auto
  cuts, 11 subtitle lines with identical text (term_fix + generic `readning→reasoning` applied);
  timings within 1 frame; total 39.867 s vs 39.888 s planned / 39.95 s actual old; -13.9 LUFS both;
  bt709 tags present. `--renderer render_landscape.py --reuse` end to end: OK, -13.9 LUFS.
- Chunked path (CHUNK=3, 7 pieces, mixed fades): file 471 frames = plan exactly, chunks removed.
- Four renderers' previews (masked + --no-mask, hook badge, node card, panels, bilingual subs),
  make_cover, make_thumb, make_thumb_trio, apply_sticker, verify_coverage (PASS), export_srt
  run on the OLD run's work files: mean abs pixel diff 0.2–3.4 vs old; side-by-side checked by eye
  (same layout; differences are bold panel titles and ±few px in chips/cards). render_sticker:
  alpha identical to assets/cat.png. transcribe.py: mlx smoke test on a 4 s clip.
- `pytest tests` 34 passed; py_compile all; `--help` OK for every CLI.
- Still unverified: a real recording with faces (tracked + masked build), faster_whisper branch.

### Lib requests (kept local)
- `cut.render_assembly`: per-input options (`-ss/-t` input seeking for N spans of one source)
  and built-in chunking for 30+ pieces — call-clips' `_render/render_timeline` does this.
- `subs.retime` is cue-level; call-clips needs per-piece word-level mapping (a segment straddling
  a cut keeps only its in-piece words; lines clamped to dissolve midpoints, never across a join):
  `build_clips.load_subs` kept.
- `cut.TimeMap.to_final(..., with_item=True)` (item index), to drop the local piece search.
- `face`: track gap-fill/EMA (`track_face.fill_gaps/ema`) and lip-motion talk detection
  (`speaker_timeline.mouth_gap`) have no lib counterpart; kept.
- `overlays.chip(style="tag")`: radius/min-width params; a bilingual stacked `text_layer` helper
  (render_landscape.render_sub stacks two locally).
