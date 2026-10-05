# PORT_NOTES - vlog

## Source
`drone-nature-vlog` skill (SKILL.md, references/recipes.md, scripts/{contact_sheets.sh, build_vlog.py,
make_cover.py, fetch_music.sh, add_music.sh}). Generalized from drone-only wildlife to any silent or
ambient B-roll (drone, phone travel/walking, nature, city, action cam).

Changed / dropped:
- Real worked example (absolute personal paths, dated DJI filenames, a specific shoot) replaced by
  a synthetic `examples/edit.example.json`; the craft (arc, segment lengths, grade numbers) kept in
  recipes.md.
- `add_music.sh` -> `add_music.py` so loudness reads persona `audio.loudness_lufs` (was hard-coded -14)
  and to add `--ambient-db` / `--track-start`. Same filter chain otherwise.
- `make_cover.py`: hard-coded Chrome path list -> `$CHROME`, PATH names, common macOS/Linux paths,
  each tried in turn (a broken/quarantined `chromium` on PATH returned exit 126 here), then Playwright.
  Photos are now `object-fit:cover` + zoom instead of `background-size:%` (old method left cream gaps
  when slot aspect != frame aspect, worse on vertical); default zooms retuned (130% -> ~110%) to keep
  the original framing. Added `--size` (vertical covers), optional `--title` using vstudio font roles
  copied to `<out>/assets/fonts/`, and `--config` image paths relative to the config file.
  Default stays no text.
- `fetch_music.sh`: now writes/de-dups credit lines in `OUT_DIR/ATTRIBUTION.txt`, `--help`, non-zero
  exit on failure, a "calm / ambient" cheatsheet row (HEAD-checked 200). HyperFrames/HeyGen catalog
  route (`npx hyperframes media-use resolve --type bgm`) documented as alternative (not executed).
- `contact_sheets.sh`: portrait-aware tiles (phone clips), even tile size (400x224; 225 failed pad
  on yuv420p), `--help`.
- Nothing dropped.

## Capabilities
- cut (EDL windows from long takes) - build_vlog.py
- speed (per segment, subject vs empty kinds, slow-mo safe) - build_vlog.py
- grade (eq + warm colorbalance + unsharp, persona house look) - build_vlog.py
- hdr (HLG/PQ auto tone-map; zscale if present else approximate colorspace) - build_vlog.py
- transitions (xfade any transition, no black first frame, fade-out end) - build_vlog.py
- b-roll (whole workflow), other: orientation fit crop/pad/blur, deshake stabilization - build_vlog.py
- music (CC-BY fetch + attribution file, loop/fade mux, ambient bed) - fetch_music.sh, add_music.py
- loudness (loudnorm to persona LUFS) - add_music.py
- cover (torn-paper scrapbook, any size, optional title) - make_cover.py
- other: footage inspection (probe, contact sheets, starter EDL) - probe.py, contact_sheets.sh

## Likely duplicates for phase 2 (`lib/vstudio`)
- Chrome/Playwright HTML->PNG rendering: `scripts/make_cover.py:chrome_candidates` + `render`.
- Font staging for HTML: `scripts/make_cover.py:stage_fonts`.
- Loudnorm / music-bed mux: `scripts/add_music.py:main` (single-pass loudnorm).
- ffprobe helpers: `scripts/probe.py:probe`, `scripts/build_vlog.py:clip_info`, `scripts/add_music.py:probe`.
- HDR->SDR tone-map chain: `scripts/build_vlog.py:hdr_chain` (+ `has_filter`).
- Crossfade concat with offset math: `scripts/build_vlog.py:main` (xfade/acrossfade chain).
- atempo chaining: `scripts/build_vlog.py:atempo`.
- Contact sheets / frame grids: `scripts/contact_sheets.sh`.

## New persona keys (read with defaults; not added to persona.example.yaml)
- `vlog.speed_subject` (1.2), `vlog.speed_empty` (1.3)
- `vlog.grade` ({brightness 0.05, contrast 1.12, saturation 1.18, gamma 1.04})
- `vlog.cover_tape` ("#c9b98f", title label underline)
Existing keys used: `audio.loudness_lufs`, `export.audio_bitrate`.

## Platform-specific / unverified
- Tested on synthetic testsrc clips only (landscape + portrait, crop and blur fit, ambient audio,
  slow-mo, add_music both modes, covers 16:9 + 9:16 with CJK title). No real 4K / HDR render run.
- HDR path: this machine's ffmpeg has no `zscale`, so only the approximate `colorspace` fallback is
  exercised; the zscale/tonemap chain is untested here.
- `npx hyperframes media-use resolve --type bgm` syntax taken from the brief; not run.
- Incompetech availability/licence is third-party; tracks are not vendored.
- `stabilize` (deshake) inherited from the source, unverified on real footage in this port.

## Phase 2b rewire
Swaps (old -> new):
- `probe.py:probe` -> `media.probe` (+ local rotation swap for display w/h and HLG/PQ label).
- `build_vlog.py:clip_info` -> `media.probe` (kept as an `lru_cache` wrapper; segments probe the same source repeatedly).
- `build_vlog.py:hdr_chain`/`has_filter` -> `media.hdr_to_sdr_args(src, transfer, force=hdr is true)`; adds the
  libplacebo backend between zscale and the approximate colorspace fallback. Local `has_filter` deleted.
- `build_vlog.py:atempo` -> `media.atempo_chain`.
- `add_music.py` ffprobe + single-pass loudnorm filter graph -> `media.probe` + `audio.mix_bed(..., lufs=)`
  (loop, fades, two-pass linear `audio.loudnorm_2pass` inside), then a video-copy mux.
- `make_cover.py:chrome_candidates`/`render`/`stage_fonts` -> `render.find_chrome` / `render.html_to_png`
  (`use_persona=False, fonts=False`) / `render.stage_fonts` + `render.font_face_css`.
- `contact_sheets.sh` -> thin bash wrapper (same CLI) over `media.contact_sheet` (cols 5, max 30, start 0).
NOT swapped: the crossfade join in `build_vlog.py:main` stays local (see Lib requests).

Behaviour changes:
- add_music: loudness now two-pass linear (synthetic test: -13.7 / -13.8 LUFS vs old -14.8 / -15.5 for a -14 target).
  `--ambient-db` now means "ambience at music_lufs + N LUFS" (measured), not N dB on the raw track; fades shape
  the music only (the master already fades its ambience out). `--track-start` loops the trimmed track
  (old looped from 0 after the first pass). New optional persona key read: `audio.music_lufs` (-30, existing lib key).
- contact sheets: time label under each tile (no drawtext needed), grid only as tall as the clip needs
  (old always padded to 5x6), PIL compositing instead of the ffmpeg tile filter.
- HDR: libplacebo used when zscale is missing; warning text now comes from vstudio.media (stderr).
- Masters and covers: unchanged.

Tests (synthetic lavfi media in /tmp, old run from HEAD before editing, then new):
- build_vlog 16:9 crop (landscape + portrait + HLG-tagged clip at 0.5x slow-mo, kind:"empty") and 9:16 blur
  (ambient audio, 0.5x + 2.5x atempo chain): identical durations (10.833 / 10.800 s), PSNR inf at t=1/5/9 s,
  ambient loudness identical (-23.1 LUFS).
- add_music music-only and `--ambient-db -12 --track-start 1`: durations identical; ambience/music band levels
  within ~1.5 dB of old; integrated loudness closer to target (above).
- make_cover 16:9 auto layout and 9:16 with CJK+Latin title: PSNR inf vs old.
- probe.py table + `--init --max-res 960`, contact_sheets.sh landscape + portrait: OK.
- `pytest tests -q` 34 passed; py_compile all; `--help` for all 4 Python CLIs and both shell scripts.

Lib requests:
- `cut.xfade_assemble`: (1) per-piece `vf` (dict key) so grade/bright/HDR/stabilize can vary per clip, and
  fit modes beyond crop (pad, blur - needs a split/overlay subgraph, so a per-piece graph hook); (2) a
  `transition=` parameter (vlog exposes any xfade transition); (3) `audio=False` video-only mode (silent drone
  masters have no audio streams, the graph always maps `[i:a]`); (4) `render_assembly(post_video=...)` for the
  closing `fade=t=out`. With those, build_vlog could drop its local offset maths and gain frame-quantised timing.
- `media.probe`: optional `display_w/display_h` (rotation applied) - vlog, cover and contact sheets all re-derive it.

## Wave B: platform wiring + fun travel style + speech clips
Changes:
- `"style": "calm" | "fun"` in edit.json. calm = `build_vlog.py` unchanged when `res` is set (regression test
  below); `build_vlog.py` hands `"style": "fun"` to the new `build_fun.py` (one command for both).
- New `scripts/build_fun.py` + `scripts/funvlog/` (score, plan, frames, gfx, mix): music-first beat-grid
  edit (`beats.analyze`, `energy_arc("travel-fun")`, `cut_plan(..., "accelerate")` for hook/finale, drops),
  auto best windows (per-second sharpness/motion/exposure/face score, cached), speed ramps inside a shot
  (rate keys, smoothstep, true slow-mo from 60/120 fps, frame blend on 24/30 fps + warning), photo inserts
  (Ken Burns card/full, HEIC via pillow-heif or `sips`), freeze-to-photo-card, transitions (whip >= 300 px/f,
  zoom punch, flash, light leak, glitch-lite; one per cut, borrowed frames, A4 hit budget), graphics (title
  pop, location tag, DAY stamp, date stamp, word pops, route map card, end card), SFX via
  `audio.cue_sheet_for`, music via `loop_bed` + `mix_bed` ducking, look-ahead limiter + two-pass loudnorm to
  the profile, `.nomusic.mp4` (A13), `--clean-master` + cues.json/SRT, report.json (verify, hits, boxes,
  cue sheet, measured duck).
- Speech clips (`speech: auto|true`): transcript file / `<clip>.words.json` -> `asr.transcribe` -> RMS
  fallback; windows grow to whole sentences; shot ends on the next beat; optional `cut.tighten`; captions in
  `platform.caption_box` via `export.caption_overlay`.
- Platform wiring: `platform` / `--platform` on build_vlog (canvas + fps when `res` absent, length check),
  build_fun (canvas, fps, safe box, caption box/style, loudness, encode, length, reframe), add_music
  (loudness target + length), make_cover (`platform.cover_size` + title-safe box); probe `--init --style fun`.
- No change to `lib/vstudio/cut.py` was needed (the fun engine composites per frame; hard cuts stay exact).

Tests (`workflows/vlog/tests/test_vlog.py`, synthetic; 22 passed, ~6 min): fun renders for
xiaohongshu:full 1080x1920 and youtube 1920x1080 - canvas/duration/frame count; every cut within +-1 frame
of the TRUE beats of a 120 BPM drum track and `beats.verify` ok (max 0.01 frames); frame-difference spike on
each planned cut frame; flash = white frame, leak = brighter frame, whip = horizontal gradient energy < 25 %;
all six transition kinds used; <= 3 hits >= 16 beats apart; drop -> zoom; loudness -14 +-1 LU, TP <= -0.9;
captions (master minus clean master) inside the caption box; overlay boxes inside the safe box; SFX peaks
>= 15 dB over the local floor at cue times in the no-music file; speech window covers whole sentences; music
measurably ducked (-11.9 dB for duck_db -12); 120 fps slow-mo shot has no repeated frames; HEIC photo;
dry run + douyin. Calm: HEAD `build_vlog.py` vs new on two configs (16:9 crop + slow-mo, 9:16 blur + ambient
atempo) -> identical frames and durations; calm with `platform: youtube-shorts` -> 1080x1920, add_music
`--platform` uses the profile target. `pytest tests -q`: 318 passed.

Unverified / limits:
- Synthetic media only: no real faces (face-mode reframe exercised only through its pad-blur fallback; face
  score term always 0), no real speech (captions from a transcript sidecar; the whisper path is the lib's
  `asr.transcribe`, not run here), no HDR source in the fun path (same `media.hdr_to_sdr_args` as calm).
- Speed: per-frame Python compositing ~10 output fps at 1080x1920 on an M-series Mac (38 s video ~2 min);
  4K 120 fps sources decode at full size per shot.
- The synthetic drum track has a ~20 dB crest factor: the limiter works hard; real mastered music needs less.
- `add_music.py` on that track lands ~2 dB under target (lib loudnorm true-peak guard; unchanged behaviour).

Duplicates for later unification:
- `funvlog/frames.py:load_photo` (HEIC via pillow-heif/sips) = photo-story `ctx.py` HEIC cache.
- `funvlog/frames.py:photo_frames` / `_cover` (Ken Burns) ~ photo-story shots; `card_renderer` ~ hf.freeze_hold.
- `funvlog/gfx.py` easing (`out_back`, `out_cubic`) ~ hf/HyperFrames easing; `pin_icon`, `MapCard` new.
- `funvlog/score.py:clip_scores` ~ `cover.score_frames` (frame scoring) - a per-second clip scorer fits `media`.
- `funvlog/mix.py:limit` (look-ahead peak limiter) - none in lib yet.
- `funvlog/frames.py:grade_chain` = build_vlog `grade_chain` (separate defaults).

New persona keys (read with defaults): `vlog.fun_grade`, `vlog.fun_music_lufs` (-19). Existing used:
`brand.*`, `platforms.default`, `audio.voice_lufs`, `export.audio_bitrate`.

Lib requests:
- `subs.cues_from_words`: Latin text loses the space after punctuation ("everyone,welcome"); build_fun
  re-inserts it (`build_fun.captions`). Join rule should add a space when the next token starts with a
  letter/digit and the text is not CJK.
- `audio.loudnorm_2pass` falls back to dynamic mode on peaky mixes and overshoots true peak after AAC; an
  `audio.limit(x, ceiling_db)` (see `funvlog/mix.py:limit`) or a pre-limit option would fix it for everyone.
- `audio.mix_bed`: return/write the ducked music stem (or the gain curve) so callers can report the dip
  (`funvlog/mix.py:measured_duck` recomputes it from the voice gain).
- `beats.Beats.shift(seconds)`: music time -> video time copy (`funvlog/plan.py:shift_beats`).
- `reframe.plan`: accept already-decoded frames / a frame iterator (the fun engine decodes each window twice:
  once for face detection, once to render).
