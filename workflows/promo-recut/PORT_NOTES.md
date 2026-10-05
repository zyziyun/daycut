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

## Phase 2b rewire (onto `lib/vstudio`)

**Swaps (old → new)**
- `common.py:run/need/duration/extract_wav/read_wav` → `media.run/duration/extract_wav`, `audio.read_wav`;
  `common.transcribe/words_of` → `asr.transcribe(cache=False, fix_terms=False)` (work/audio.json stays the cache);
  `common.raw2cut` + `tight_cut.rawmap` → `cut.TimeMap` (layout.json `maps` are now TimeMap item lists;
  build_promo's `BT/OT` use `to_final(t, "fwd")`, falling back to `"back"` past the end = old raw2cut semantics).
  common.py now only holds `Project`, `P`, `link_or_copy`.
- `tight_cut.tighten` → `cut.tighten`; `suggest/hidden_onset/rms_envelope` → `cut.suggest_fillers` (uses
  `cut.hidden_onset` + `audio.rms_envelope`); `cut_file` (trim/concat + single-pass loudnorm) →
  `cut.cut_segments` (frame-exact) + `audio.loudnorm_2pass`; `montage` → `cut.xfade_assemble` +
  `cut.render_assembly` + `audio.loudnorm_2pass`; `HDR_TONEMAP` → `media.hdr_to_sdr_args`;
  draft-subs term fixes → `asr.apply_term_fixes`.
- `build_promo.subset_fonts` → `render.subset_project_fonts`; progress bar CSS/HTML/JS → `overlays.hf_progress`;
  cue CSS → `overlays.hf_cue_css`; 【】→`<em>` (now HTML-escaped, in Python) → `overlays.cue_html`.
- `make_cover.build/get_photo` (own PIL layout + retouch) → `cover.split_cover` (config mapped onto it);
  frame grabs → `media.grab_frame`.
- `post_copy.py` → `publish.post_body` (title check, chapter_lines, hashtags, voice warnings).
- `export.sh` (inline 2-pass loudnorm + h264_metadata) → new `scripts/export.py` (`audio.loudnorm_2pass` +
  `media.retag_bt709`); export.sh is kept as a thin `exec python3 export.py "$@"` entry point (same args,
  plus `--lufs`).

**Behaviour changes (deliberate)**
- Cuts snap to the frame grid (segments move ≤ 1 frame; body 42.80 → 42.83 s, final timeline shifts ≤ 0.03 s);
  audio is 48 kHz stereo with 12 ms edge fades. Stems use two-pass loudnorm (measured: body -16.0, outro -15.9,
  montage -17.0 LUFS; old single-pass -15.9/-16.0/-17.0).
- Montage uses `mute_pad=False` (plain acrossfade, same clip timing the step labels are computed from);
  `montage.scale` is now scale-to-cover + crop instead of a bare scale (identical for 16:9 sources).
- `cut.tighten` without audio is equivalent to the old function; new opt-in `cut.rms_snap: true` (config key)
  snaps pause edges to voiced energy. Persona `audio.pause_squeeze` is read but below pad_in/pad_out it has no effect.
- `hdr_tonemap` accepts `"auto"` (tone-map only HLG/PQ sources); falls back to libplacebo / approximate if no zimg.
- Default filler list (when `cut.fillers` is unset) is the library's broader zh + en list; `--suggest` now also
  prints a PATCH list.
- Post copy: timestamps `00:08` (floored, MM:SS) instead of `0:09` (rounded); links use `：` on 小红书; a blank
  line separates body and links; 小红书 chapter labels capped at 14 chars.
- Cover: split_cover's layout (scaled by min(W,H)/1080, chips/tags via `overlays`) — visually matches the old
  cover; retouch runs once per size (slower, same result).
- Vertical chapter labels are 24 px (hf_progress vertical geometry) instead of 22 px.

**Test evidence** (synthetic project /tmp/promo-recut-after vs the phase-1 outputs, old code from `git show HEAD`)
- `tight_cut --suggest`: same candidates and DROP list as the old script (text format of the note differs).
- `tight_cut` default: 6 body + 1 outro segments, same boundaries within 1 frame; durations 42.83 / 6.47 / 40.0 s.
- `build_promo` horizontal + vertical: `hyperframes lint` 0 errors, the same 6 advisory warnings; snapshots at
  7.5/23.8/34.9/45/74.5/78 s match the old ones (cards, chips, cues with highlight, montage label/badge/tag,
  progress bar + active chapter, end card).
- `make_cover`: 4:3 / 16:9 / 3:4 visually match the old covers (synthetic footage has no face → centred crop).
- `post_copy`: OK (format changes above). `export.sh --skip-render`: -14.0 LUFS, bt709 primaries/transfer/space.
- `python3 -m pytest tests -q`: 34 passed; py_compile + `--help` for every script; `export.sh --help`.
- Not run: `--verify`/real whisper, a full HyperFrames render.

**Lib requests**
- `cover.split_cover`: accept a pre-retouched photo + face_x so multi-size runs retouch once, and a pixel `crop`
  for thumbnails (we crop locally today).
- `media.grab_frame`: return `out`, and an optional JPEG quality (build_promo still uses `media.run` with `-q:v 2`
  for the freeze frame).
- A small `link_or_copy` (hard link, else copy) in `media` or `render` would remove the last local file helper.

## Phase 3: effects moved to `vstudio.hf`

`render_html` now composes `vstudio.hf` generators (split_screen, punch_in, punch_at, enter_zoom,
screenshot_cards, chips, subtitles, freeze_clips, freeze_hold, framed_screen, zoom_through, step_labels, tag,
badge, title_card, stamp, end_card) instead of inline CSS/HTML/GSAP. Output is **byte-identical**:
`index.html` diffed against the pre-refactor script on /tmp/promo-recut-after (horizontal + vertical) and a
minimal variant (no hold / montage / outro / end card / chips, explicit `split`). `hyperframes lint`: 0 errors,
the same advisory warnings as before. Unused local `HL` dropped from render_html.


## Wave B: platform profiles

**Changes**
- `build_promo.py --platform <profile>` (or config `platform:`), `--out DIR`, `--clean-master`. Horizontal default =
  the legacy GEO (byte-identical). A vertical profile (xiaohongshu:full / :vertical 3:4, douyin, tiktok,
  youtube-shorts, bilibili:vertical) builds its layout with `vertical_geo(profile)` from `platform.safe_box`,
  `caption_box` and `keepouts`: chapter bar + labels (22 px) at the safe top on a top scrim; talking-head band below
  (≈42 % of the free height, ≈2.4 face heights when a face is found), clip window centred on the face
  (`estimate_face`: `vstudio.face` landmarker on 6 frames; else centred; `layout.vertical.face: [fx, fy]`) and
  `object-position` from the face x; chips + card under it down to 24 px above the caption band, side margin widened
  to clear the button column; captions bottom-anchored in the caption box, `text-wrap: balance`, size = box width /
  max_chars_zh within the profile's size range; montage screen at the safe width, centred in the free area but above
  the button column, labels under it; stamp / end card inside the safe area. `--orientation vertical` without a
  platform = persona `platforms.default` at 9:16 (`promo-vertical/`, deliberately changed from the old first-pass
  GEO). Explicit `--platform` → `<promo_dir_vertical>-<name>-<orientation>/`.
- Every build writes `<promo_dir>/cues.json` (final-timeline cues, 【】 kept) for `vstudio.export --cues`;
  `timeline.json` gains `platform`, `canvas`, `boxes` (non-default builds only). Warnings: length vs profile, cues
  that can't fit 2 lines, chapter labels colliding on the narrower bar.
- `export.py --platform`: LUFS / true peak from the profile + length warning.
- WORKFLOW.md "Geometry / vertical" rewritten + new "Platforms" section (multi-platform delivery via
  `vstudio.export`, clean-master route, why not to reframe the 16:9 promo); example config documents `platform:` and
  `layout.vertical.face`.

**Tests** (synthetic project /tmp/promo-recut-after copied to /tmp/wb_promo)
- Horizontal: `index.html` and `timeline.json` **cmp-identical** to the pre-change build.
- `--platform xiaohongshu:full`, `--platform douyin`, `--platform xiaohongshu:vertical` (3:4): `hyperframes lint`
  0 errors (the same 6 advisory warnings as horizontal). Snapshots at 7.5 (split + card + chips + caption), 19.0
  (prompt hold), 35.3 (mid zoom-through), 45 (montage + labels) and 75.5 s (outro stamp + 2-line caption), read with
  the safe box / caption box / button column drawn on: no overlaps, captions inside the caption box, nothing in the
  button column or outside the safe box (the synthetic talk has no face → centred fallback; face path not exercised
  on real footage). The synthetic chapters 起因 / 讲解视频 are only ~5 s apart and their labels touch on the
  1080 bar → the new warning fires (content issue: merge/shorten).
- `export.py --skip-render --platform douyin`: -14.0 LUFS, bt709, length warning. `vstudio.export.load_cues` reads
  `cues.json`. `--clean-master` build: empty cue list. py_compile + `--help`; `python3 -m pytest tests -q`: 108 passed.

**Lib requests**
- `overlays.hf_progress`: a `position="top"` option (top scrim gradient, labels under the bar) — we override
  `#bar-scrim` CSS for vertical today; and label collision handling (stagger or hide) for short chapters.
- `hf.split_screen`: optional `scale` so the face band can show more of the frame (we can only clip + translate).
- `references/EFFECTS.md` row "Vertical face band + card" still quotes the old GEO values; point it at
  `build_promo.py:vertical_geo`.
