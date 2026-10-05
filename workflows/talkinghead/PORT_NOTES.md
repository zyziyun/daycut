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

## Wave B

### Platform wiring
- New `scripts/vertical/layout.py`: `resolve_profile` (config `PLATFORM` / `--platform`, default persona
  `platforms.default` in the track's natural orientation: V 9:16 "full", H horizontal), `Layout` (every V-track overlay
  position from `platform.safe_box` / `caption_box` / `keepouts`), face-aware candidate picking, `h_track_geo` (H track).
  On 小红书 9:16 / 16:9 the derived values equal the old constants (bar y 250, title 330/390, callouts (60, 350), panel
  940 wide ending sub_y-60, circle (540, 1100) R 290, card (243, 600), captions 1525; H bar y 1000 x 80..1840, badge
  (70, 44), callouts (70, 70), panels (66, 86)).
- `compose.py`: canvas from the profile (3:4 1080x1440, 9:16, 16:9 1920x1080). A body of another aspect is reframed once
  with `vstudio.reframe` (face mode; no face: centre crop 9:16→3:4, pad-blur otherwise; 9:16 body on 16:9 = pad-blur)
  into `body_<W>x<H>.mp4` + `.crop.json`; the face track is mapped through the plan. Landscape layout: bar 1.25x, panel /
  callouts on the side away from the face, circle left + tokens right, card left + text right, split left/right.
  Caption band centre and width (shrinks long chunks), loudness LUFS + true peak, length warning from the profile.
  POPS / STAMPS coordinates (authored on 1080x1920) are mapped relative to the face and clamped above the captions and
  left of the button column. `STYLE sub_y` outside the band is ignored with a note (example no longer sets it).
  `--clean-master` writes `<OUT>.clean.mp4` (no captions) + `<OUT>.cues.json` (final-time cues incl. hooks) for
  `python -m vstudio.export`. `timeline.json` gains PLATFORM/W/H.
- `cover.py` (V): per-platform cover size (`--platform` repeatable), face-centred crop for non-legacy sizes, title inside
  `cover_title_safe`, `.feed.jpg` for feed crops, ≤ max_bytes for YouTube. 3:4 from a 9:16 body = old layout.
- H track: `make_assets.py` / `build_filter.py` take `--platform` / `PLATFORM` (positions via `h_track_geo`, loudness +
  true peak from the profile, size from the profile; vertical profiles refused with the export hint);
  `make_cover.py --platform youtube --platform bilibili` re-fits the cover (1280x720 ≤ 2 MB, 1146x717) + feed previews.
- `caption.py`: `--platform` repeatable (default config PLATFORM → timeline PLATFORM → persona), title via
  `platform.check_text` + `publish.check_title`, `--body` description limit, tag count, length sweet spot / max, note when
  the platform has no native chapters.
- `pick_cover_frame.py`: the 3:4 band only for 9:16 frames.

### Horizontal footage
- `prep_sources.sh`: the median-face-x crop is replaced by `vstudio.reframe` face mode (One Euro target, dead zone,
  eased pans, cut resets, safe box of the 9:16 profile; pad-blur fallback). `ORIENT=horizontal` (or old
  `KEEP_LANDSCAPE=1`) keeps 16:9 for `compose --platform youtube|bilibili|xiaohongshu:horizontal`. `PLATFORM`,
  `REFRAME_MODE` env. Writes `prep.json` (mode, hit rate, pan stats, **upscale** incl. a small source enlarged by the fit).
- Punch-in fix (real webcam crop: too tight, title over the eyes): `zoom_level` caps every zoom by
  `STYLE max_upscale` (2.0) / source upscale (`SRC_UPSCALE` or prep.json x reframe scale), by `max_face_frac` (0.62 of
  the canvas width) and by keeping the zoomed face box below the progress bar. `face_track.py` now stores the landmark
  box (8 columns; old 4-column files get an estimated box). The hook title block is checked against the face core
  (brows..chin, after the punch-in) of every hook frame: pushed up to the safe top, shrunk (≥ 0.7), or moved between
  chin and captions (≥ 0.62). Callouts, PiP cards (shrink to 0.58 first), pop words (dropped below the chin) and the
  vertical 记笔记 panel (compacts to 0.78) avoid the face core too. All no-ops on the default synthetic layout.

### B-roll (new `scripts/vertical/broll.py`, config `BROLL`)
cut (full cut-away; screenshots as a card on their own blurred fill), pip (rounded rimmed card, face-aware corner, pop
in), split (top/bottom vertical, left/right 16:9; speaker half cropped on the face). Images taller than their box = the
screenshot-card idea in PIL: scroll top→bottom or follow `highlight` rows, marker wipe per row, optional label badge.
Voice continues (b-roll audio unused); whooshes with `sfx`; zoom / stamps / pops pause under cut / split; circle / card
scenes win. Drawing uses `draw.rounded_rect/alpha_paste/text_width` + local card/shadow (numpy, per frame).

### Other fixes
- `retouch_video.py`: ffprobe `csv=p=0` prints `30/1,` on ffmpeg 8+/9 → crashed on real media (`'1,'`); stripped.
- `lib/vstudio/retouch.py` (allowed edit): new shade `mlbb` Lab (56, 30, 9) ≈ #BB7177 (muted rosy MLBB pink);
  preset `daily` lip_shade coral → mlbb. Other presets unchanged.

### Tests
- Synthetic (lavfi 1080x1920 + `say` speech, 10 sentences, 精剪 config + notes preset) vs `git archive HEAD` copy:
  cut_pass1 segs.json identical; `compose all` out.mp4 16 sampled frames max diff 0 and mix.wav byte-identical;
  notes-preset preview max diff 0; V cover.py 3:4 max diff 0. H track (lavfi 1920x1080): make_assets → build_filter →
  run.sh: 13 sampled frames max diff 0, audio identical; make_cover identical.
- Other targets: compose base+preview on `xiaohongshu:vertical` (1080x1440), `douyin` (captions y 1345), `youtube`
  (1920x1080, pad-blur from 9:16); both presets; B-roll cut/pip/split + screenshot scroll/highlight on 9:16, 3:4, 16:9;
  `--clean-master` (out.mp4 unchanged, clean master caption-free, 22 cues) → `vstudio.export` xiaohongshu:vertical +
  douyin at −14.0 LUFS; H track on bilibili (bar y 980, −14.0 LUFS / −1.5 dBTP); covers 3:4 / 9:16 / 1280x720 / 1146x717.
- Real (outputs in /tmp only): creator's vertical HLG 口播, first 65 s: prep (avconvert HDR→SDR) → auto keep list
  (18 whisper segments) → cut_pass1 (51.5 s) → retouch_video `--preset daily` (6 workers) → strict_pass suggest + apply
  (51.5 → 40.9 s; auto-DEL took every candidate, test only) → face_track (100 %) → compose previews on 3:4 and 抖音 9:16
  with hook, callout, 记笔记 panel, refined progress bar, pop word. Horizontal webcam (60 s): prep → reframe face mode
  (hit 1.0, p95 pan 0.05 crop-widths/s, x1.78 upscale) → cut → face_track → 抖音 9:16 previews (punch-in capped to
  none: face already 0.75 of the width; title shrunk above the glasses; PiP shrunk off the eyes; split; circle scene);
  and ORIENT=horizontal → 16:9 YouTube previews (landscape layout).
- `python3 -m pytest tests -q`: 318 passed. py_compile + `--help` on all CLIs, `bash -n prep_sources.sh`.

### Persona / config keys
Config: `PLATFORM`, `SRC_UPSCALE`, `REFRAME_MODE`, `BROLL`, `STYLE max_upscale / max_face_frac`. Persona: none new
(reads `platforms.*` through vstudio.platform).

### Lib requests
1. `references/RETOUCH.md` preset table still says "coral lip" for `daily` (now `mlbb`); add `mlbb` to the shade list.
2. `media.py:211` (and photo-story `shots.py`) parse ffprobe `csv=p=0`; ffmpeg 8+/9 appends a trailing comma on stream
   entries (format=duration seems fine) — worth a shared `ffprobe_value()` helper.
3. `reframe.plan`: return the source→target scale / upscale factor (callers recompute it from crop_w).
4. `platform`: a per-profile "ui_top" (bottom of the progress-bar / top-bar zone) and a face-safe helper
   (`avoid_face(rect_candidates, face_boxes)`) — layout.py has local versions.
5. `export.caption_overlay`: optional keyword colouring (cues.json from compose carry the raw chunk text).
