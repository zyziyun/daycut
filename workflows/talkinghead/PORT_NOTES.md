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

## Phase 2b rewire

### Swaps (old → new)
- Hook montage + body dissolves, both tracks: `compose.py` PADS/CLIPS/L/MAP/b2f/f2b + `build_base` graph and
  `build_filter.py` xfade/acrossfade chain → new shared `scripts/montage.py` on `cut.xfade_assemble(mute_pad="both")`
  + `cut.TimeMap` (b2f, f2b, is_hook, join_starts, timeline). Hook ranges get their own fast-seek inputs.
- Loudness: compose base single-pass + render single-pass, build_filter inline single-pass → `audio.loudnorm_2pass`
  (V: voice normalised before SFX so the SFX gains keep their old meaning, then the mix again; H: run.sh writes a PCM
  premix then calls loudnorm_2pass). Final encode → `media.delivery_args`.
- SFX: `compose.sfx_bank/mix_audio` → `audio.place_sfx` (same synth, same gains).
- Drawing: compose `F/text_layer/colorize/rounded/shadowed/blit/blitc/vis_len` → `draw.load_font/text_layer/runs/
  rounded_rect/shadow/alpha_paste`, `subs.text_width`; hook badge → `overlays.badge`; stamps → `overlays.stamp`;
  callouts → `overlays.callout` (theme `STYLE['callout_theme']`, default notes-yellow = the old white bubble);
  panel tag → `overlays.tag`. KEYWORDS colouring now also honours 【】 markup.
- Progress bars: `progress_refined/progress_classic` (+ precomputed SEGX/GRAD/LABELS/CLS) → `overlays.progress_bar`.
  The refined chapter pill keeps its fade + slide-in (the strip is split at the label row).
- Subtitle chunk timing: proportional by char width → `asr.align_script` against the strict_pass words (chunk ends
  where its last word ends); proportional via `subs.text_width` remains the fallback when segs.json has no words.
- Cutting: `bodycut.cut_body` (decode-from-0 trim per segment) and cut_pass1's own ffmpeg loop + numpy splice →
  `cut.cut_segments` via `bodycut.cut_sources` (groups consecutive ranges per source); `bodycut.remap` → `cut.TimeMap`
  (snap "fwd"). Envelopes/runs in cut_pass1 + strict_pass → `audio.rms_envelope(smooth=0)` + `audio.voiced_runs`
  (3-frame smoothing kept in dB locally, see lib requests).
- ASR: `scripts/asr.py:transcribe` → thin CLI over `asr.transcribe` (cache, OpenAI fallback, hallucination-safe
  settings, generic + persona term fixes); strict_pass transcribe uses it directly and now also prints
  `cut.suggest_fillers` DEL candidates (review aid, never applied).
- prep_sources.sh: ffmpeg_sdr/avconvert/extract → `media.to_sdr` + `media.extract_wav` (no more `a48_N.wav`; cut_pass1
  reads sound from `sdrN.mp4`).
- Covers: H `make_cover.py` → `cover.notes_cover` + `media.grab_frame` (frame-accurate); V `cover.py` no longer imports
  compose, uses `draw`/`overlays.tag`; `pick_cover_frame.py` → `cover.score_frames` + `cover.contact_sheet`.
- H assets: `make_assets.py` → `overlays.progress_static`, `badge`, `callout`, `notes_panel`.
- Caption: own mmss/xhs_len/tags → `publish.check_title` (with hints), `chapters_from_body`, `chapter_lines`, `hashtags`.
  Both tracks now read `timeline.json` (build_filter writes one).

### Kept local (deliberately)
Per-frame animation engine (zoom, circle inset, card, scene logic, pop/stamp easing), face-track medians per sid
(lib has no tracker), the V 记笔记 panel (needs per-bullet row layers for the reveal), the token pill, the cut-list
logic of cut_pass1 / strict_pass (`cut.tighten` squeezes only whisper gaps > 0.35 s; strict_pass squeezes every RMS
gap > 0.12 s, so it is not equivalent), retouch_video's chunked pipeline, detect_head.

### Behaviour changes
- **mute_pad="both"** (chosen over "head"): the old V code padded only the incoming side (+ the last hook's tail), so
  the outgoing hook's last syllable was faded by every inter-hook acrossfade; the old H track had no pads at all.
  Now every dissolve is silent on both sides. Cost: +XF per inter-hook join on V (synthetic test: 23.63 → 24.23 s,
  body part identical 17.24 s), +2*XF per join on H (0.8 s example: 32.6 → 37.4 s). Body keeps the cloned-frame pre-roll.
  A hook ending at the very end of the source cannot get a tail pad (clamped).
- Durations are frame-quantised per piece; muted-pad frames show the clamped spoken range's subtitle (no flash of the
  neighbouring sentence).
- Loudness lands on target: V −13.9 / H −13.9 LUFS (old single-pass: −14.1 / −15.1).
- **Bug fixed (pre-existing):** the H progress fill/playhead used `drawbox ... w='..t..'`; drawbox evaluates once and
  its `t` is thickness, so the fill never moved. Now colour sources + per-frame `overlay` x.
- Classic progress pill no longer fades in over 0.15 s (lib draws it on/off); badge is auto-width; stamps use brand accent.
- Edge fades on cuts are 12 ms everywhere (bodycut used 10 ms).

### Test evidence (synthetic lavfi media + macOS `say` speech in /tmp)
- cut_pass1 → drop_pass → strict_pass apply (synthetic bw.json): segs.json subs/words/keep/total identical to HEAD;
  body frames pixel-identical (frames 100/250/300/450/568), frame counts equal (638/596/569), audio within ±1-3 samples.
- compose `all` (精剪 preset, all effects + SFX) and notes preset previews vs HEAD: same layout; RMS envelope at every
  join: full level up to the dissolve, only the whoosh inside it, full level right after it (HEAD: outgoing faded).
- Speech run: prep_sources.sh (SDR path, mlx whisper) → cut_pass1 → strict transcribe (suggestions printed) → apply →
  compose all/preview → cover.py → caption.py (title hints) → pick_cover_frame (no-face path). Output 14.33 s, −14.0 LUFS.
- H: make_assets → build_filter → run.sh → make_cover → caption; frame stills + bar crops at 11/16/25/36 s.
- `python3 -m pytest tests -q` 34 passed; py_compile on every .py; `--help` on all 14 CLIs; `bash -n prep_sources.sh`.
- Not run: retouch on a real face, face_track/pick_cover_frame on a real face, the avconvert/zscale HDR paths.

### Lib requests
1. `cut.xfade_assemble`: a pad mode for pieces that start at source 0 / end at source end (clone frame + silence),
   so callers need not prepend `tpad/adelay` and rewrite the graph's input labels (montage.py does that today).
2. `cut.cut_segments`: seek half a frame early (or snap source pts) — concat-joined inputs with ~1 ms pts jitter lose a
   frame and shift by one; its own concat output has that jitter, so chaining cut_segments → cut_segments triggers it
   (worked around by `bodycut.mux`, setts snap).
3. `audio.rms_envelope`: option to smooth in dB (cut_pass1/strict_pass rules were tuned on that; linear smoothing
   widens voiced runs ~10 ms and changed the synthetic cut by 1.1 s).
4. `overlays.progress_static["drawbox"]` has the same drawbox-`t` bug (never animates).
5. `overlays.notes_panel`: return per-bullet row layers/geometry for progressive reveal; `overlays.progress_bar`:
   option to omit the chapter pill (for an animated label) and a fade for the classic pill.
