# PORT_NOTES — promo-recut

## Sources
A one-off promo project (not a skill), all read-only:
- `work/prep.py` → `scripts/tight_cut.py` (+ shared helpers in `scripts/common.py`)
- `promo/build.py` (+ the generated `promo/index.html` used as reference) → `scripts/build_promo.py`
- `work/make_cover.py` + `work/retouch_cover.py` → `scripts/make_cover.py` (the retouch now goes through `vstudio.retouch`)
- New: `--suggest` / `--draft-subs` / `--verify` modes in tight_cut, `scripts/find_rows.py` (numpy row bands),
  `scripts/export.sh` (render + loudnorm + bt709 + faststart), `scripts/post_copy.py`, an optional vertical layout,
  and a portrait (stacked) cover.

All content (sentences, DROP/PATCH times, cards, rows, chips, labels, hold, montage clips, chapters, stamp,
end card, cover text, post) moved into one config, documented by `examples/promo.config.example.yaml`
(synthetic text). No absolute paths. Hiragino and `~/Desktop/photo_retouch` were replaced with
`vstudio.config.font()` / `vstudio.retouch`.

**Dropped**
- Hook teasers (`hook5`/`hook3`/`hookV` and the Ken Burns/flash code): the final edit had already removed
  them (empty `h_start`/`h_dur`). You can still cut extra named clips with `cut.extra`, but nothing places them.
- Per-project hard-coded quote/name on the cover: these are now config strings.
- The `/tmp` Hiragino TTC extraction: replaced by subsetting Noto Sans SC / STIX Two Text from FONT_DIR.
- The no-op `atempo=1.0` in the montage, and the unused `PRE` pre-speed constant.

## Capabilities
cut, pause-squeeze, filler-dedup (suggest + verify), asr, captions (【】 highlight), speed (playback rates),
loudness (voice stem, montage stem, -14 LUFS delivery), zoom (punch-ins, zoom-through), split-screen,
screenshot-cards (3D, scroll, highlighter, red box), overlays (chips, badge, step labels, stamp, end card),
progress-bar (chapters + scrim), freeze-frame (prompt card hold), transitions, b-roll (highlights montage with
crossfades), grade, hdr (optional zscale tonemap), retouch, cover, publish-copy, other (row-band measurement,
bt709 tagging).

## Duplicates to unify in phase 2 (`lib/vstudio`)
- whisper wrapper: `scripts/common.py:transcribe`, `words_of`
- loudnorm: `scripts/tight_cut.py:cut_file` / `montage` (single-pass, stems), `scripts/export.sh` (two-pass delivery)
- subtitle/time mapping: `scripts/common.py:raw2cut`, `tight_cut.py:rawmap` / `remap`, `build_promo.py` `BT` / `OT`
- tight cut / pause squeeze / filler detection: `tight_cut.py:tighten`, `suggest`, `hidden_onset`, `rms_envelope`
- progress bar + chapters: the JS/CSS block in `build_promo.py:render_html`
- font subsetting: `build_promo.py:subset_fonts` (same idea as `workflows/explainer/scripts/subset_cjk_font.py`)
- cover rendering + face-centred crop: `make_cover.py:build`, `get_photo`
- ffmpeg helpers: `common.py:run`, `duration`, `extract_wav`, `link_or_copy`
- post copy / title length: `post_copy.py:main` (uses `vstudio.config.xhs_len`)

## New persona keys (read with safe defaults)
- `brand.highlight_alt` (default `#F4D35E`): gold for chips, step numbers, quote and title highlight on the cover
- `brand.accent_soft` (default `#FF5A72`): active chapter label
- `brand.dim` (default `#969EB2`): secondary cover text
Existing keys used: `speed.body`, `speed.b_roll`, `audio.voice_lufs`, `audio.loudness_lufs`,
`audio.pause_threshold`, `export.fps`, `brand.*`, `subtitles.term_fixes`, `subtitles.max_cjk_chars`,
`platforms.*.title_max`, `publish.chapter_line`, `publish.tags`, `voice.rules`, `creator.language`.

## Verified / unverified
- Verified on synthetic media in /tmp:
  - tight_cut `--suggest`, `--draft-subs` and the cut run
  - build_promo for both orientations; `hyperframes lint` gives 0 errors (6 advisory structure warnings, the
    same kinds as the original), and snapshots look right at the split, the montage and the end card
  - make_cover with a real retouch pass and face-centred crop
  - post_copy
  - `export.sh --skip-render`: -13.9 LUFS and bt709 tags
  - every `.py` passes py_compile and `--help`
- Not run:
  - a full HyperFrames render
  - `--verify` and real whisper transcription (the mlx_whisper import works; faster_whisper fallback untested)
- The vertical layout (`GEO["vertical"]`) is a first pass: subtitles over the face band, the card under it,
  the montage frame centred. It renders, but no real 9:16 post has been made with it yet, so tune it against
  the 小红书 safe zone.
- `hdr_tonemap` needs ffmpeg built with zimg.
- `export.sh` tags BT.709 with the `h264_metadata` bitstream filter (H.264 only). If HyperFrames outputs HEVC,
  switch to `hevc_metadata`.
- The GSAP CDN script (same as the original) needs network access at render time.
- No third-party assets were copied: no stickers, SFX or music. Fonts are fetched by install.sh (OFL).
