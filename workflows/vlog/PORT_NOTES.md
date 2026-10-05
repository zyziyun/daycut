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
