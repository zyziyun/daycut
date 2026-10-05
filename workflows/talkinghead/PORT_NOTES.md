# PORT_NOTES — talkinghead

## Source
`~/.claude/skills/talkinghead-video-edit` (SKILL.md, references/, scripts/, scripts/vertical/, scripts/examples/).
SKILL.md → `WORKFLOW.md`; the four references kept (sanitized); all V-track scripts kept; H-track scripts kept.

**Dropped / replaced**
- `scripts/make_cover.py.bak`: stale backup.
- `scripts/config_example.py`, `scripts/examples/*_config.py` (2 real H configs), `scripts/vertical/examples/*L5L6_config.py`,
  `edit_list_example.py` (real transcript): replaced by ONE synthetic config per track
  (`examples/h_config_example.py`, `examples/v_config_example.py`) + synthetic `v_edit_list_example.py`, `v_strict_example.py`.
  Every knob is still shown.
- `scripts/vertical/examples/cover_example.py` (sed-patched template with real copy) → `scripts/vertical/cover.py`,
  a real CLI that reads `COVER = dict(...)` from the compose config (also removes the "sed overwrote the real cover" gotcha).
- Real content scrubbed from docs: video topics, term lists, hook lines, quotes, real paths, a third-party editor's name.

**Changed behaviour (intentional)**
- `retouch_video.py` now calls `vstudio.retouch.retouch(img, f=smoothed_face, lm=None, ...)`. Kept: per-frame EMA landmark
  smoothing (a=0.55, reset on >25 px jump), half-res detection, chunked multiprocessing, frame-exact re-encode, `--test`.
  The old local 12% ROI feather + own skin smoother are replaced by vstudio's feathered face-region mask and
  `skin_and_makeup` (makeup=0). Order is now warp → deshine → skin (was warp → skin → deshine).
- `prep_sources.sh`: avconvert if present, else ffmpeg `zscale`+`tonemap=hable` (HLG/PQ only), else `libplacebo`, else warn.
  `TONEMAP=ffmpeg|avconvert` forces a backend. Whisper via `scripts/asr.py`.
- Filter graphs are passed inline with `-filter_complex "<text>"` (works on all ffmpeg versions) instead of
  `-/filter_complex file` (7.1+ only). The file is still written for debugging.
- Brand red/yellow come from persona `brand.accent/highlight` (compose's old shades were slightly different).
  KEYWORDS are now `re.escape`d; empty KEYWORDS no longer needed a dummy `['AI']`.
- Bug fix: `cut_pass1.py` clamps a padded range start at 0 (a range at t≈0 produced `trim=start_frame=-2` and a wrapped audio slice).
- New `scripts/caption.py`: title length check (`xhs_len` vs `title_max`), final-time chapter list, persona chapter line/tags/voice rules.
- `detect_head.py`: tries `vstudio.face` landmarks first, falls back to the old dark-hair scan.

## Capabilities
cut (keep list, frame-exact) · pause-squeeze · filler-dedup (strict word pass, sid-preserving re-cuts) · asr ·
captions (per-chunk burned subtitles, keyword colouring) · speed · loudness · sfx (synthesized pop/whoosh/thud) ·
zoom (per-sentence punch-in on tracked face) · overlays (pop words, stamps, callouts, circle-inset list scenes, shrink-to-card) ·
notes-panels · progress-bar (classic + refined segmented) · hook (sped montage with muted pads, title, badge) ·
retouch · face-track · hdr · grade · cover (V 3:4 + H notes-board 16:9 with 4:3 check, smile/eyes-open frame picker) ·
publish-copy · other (sid time anchors that survive re-cuts).

## Duplicates for phase 2 (likely also in other workflows)
- whisper wrapper: `scripts/asr.py:transcribe` (mlx_whisper → faster_whisper, term_fixes).
- loudnorm: `scripts/vertical/compose.py:build_base`, `compose.py:render`, `scripts/build_filter.py` (inline `loudnorm=I=...`).
- HDR→SDR: `scripts/vertical/prep_sources.sh:ffmpeg_sdr`.
- frame-exact cut + numpy audio splice + time remap: `scripts/vertical/bodycut.py:cut_body/remap`, `cut_pass1.py` (inline).
- voiced-RMS envelope + run snapping: `cut_pass1.py` and `strict_pass.py` (same code twice, inline).
- subtitle time-mapping / sid anchors: `scripts/vertical/anchors.py:S/E/SPAN/W`, `compose.py:b2f/f2b`.
- hook montage xfade math with muted pads: `compose.py` (module top + `build_base`), older `build_filter.py`.
- notes panels / callouts: `compose.py` (PANI/CALI build), `scripts/make_assets.py`.
- progress bar: `compose.py:progress_refined/progress_classic`, `make_assets.py` + `build_filter.py` drawbox.
- text rendering helpers: `compose.py:text_layer/colorize/rounded/shadowed/blit`.
- SFX synthesis: `compose.py:sfx_bank/mix_audio`.
- face tracking: `scripts/vertical/face_track.py`; cover frame scoring: `pick_cover_frame.py`.
- cover rendering: `scripts/vertical/cover.py`, `scripts/make_cover.py`.
- 小红书 title length: uses `vstudio.config.xhs_len` already (`scripts/caption.py`).

## Persona keys
Existing, now read: `speed.hook/body` (default speeds when the config omits them), `brand.accent/highlight`,
`audio.loudness_lufs`, `audio.pause_squeeze` (strict_pass KEEPGAP default), `subtitles.term_fixes` (asr),
`creator.language` (asr), `platforms.<default>.title_max`, `publish.tags`, `publish.chapter_line`, `voice.rules`.
**New (safe defaults, not in persona.example.yaml):** `retouch.video.{slim,eye,eye_extra,shine,shine_feather,smooth,light,makeup,body}`
(defaults 0.042/0.04/0/0.7/2.5/0.55/0.04/0/0 in `retouch_video.py`).
Per-video config keys (not persona): `HOOK_BADGE_TEXT`, `NOTES_TAG`, `COVER`.

## Platform-specific / unverified
- `avconvert` is macOS-only; the ffmpeg zscale path is untested on real HLG footage here (needs ffmpeg with libzimg;
  Homebrew's default lacks it). Compare a frame from both backends once.
- Smoke-tested on synthetic media: compose base+preview, cover.py, caption.py (both tracks), make_assets + build_filter
  (run.sh not executed), cut_pass1 → drop_pass → anchors, retouch_video `--test` no-face path. NOT run: a full
  compose `comp` render, retouch on real face footage (vstudio.retouch path with a detected face), strict_pass
  (needs whisper), prep_sources.sh, faster_whisper backend.
- Voice Memos TCC note is macOS-specific (kept in gotchas).
- No third-party assets copied: SFX are synthesized in code; fonts via vstudio.
