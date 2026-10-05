# Recipes, schema, and gotchas

- [Probe the source](#probe-the-source)
- [edit.json schema](#editjson-schema)
- [Worked example](#worked-example)
- [Footage types](#footage-types)
- [Colour grade values](#colour-grade-values)
- [Speed / pacing](#speed--pacing)
- [Cover layout tuning](#cover-layout-tuning)
- [Music](#music)
- [Export / compression variants](#export--compression-variants)
- [Gotchas](#gotchas)

## Probe the source
`scripts/probe.py footage/*` prints size (display orientation, rotation applied), fps, duration,
audio yes/no and HDR (HLG/PQ). Raw equivalent:
```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate,color_transfer \
  -show_entries format=duration,size -of default=noprint_wrappers=1 CLIP.MP4
```
DJI drones: commonly 3840x2160 @ 60fps (some 30), silent, SDR unless shot in HLG.
iPhones: 4K 30/60, HEVC, HDR (HLG, `arib-std-b67`) by default, often portrait, with ambient audio.

## edit.json schema
Relative paths (`src_dir`, `out`) resolve against the edit.json folder.

| key | meaning | typical |
|---|---|---|
| `src_dir` | folder holding the source clips | `"../footage"` |
| `clips` | map of short id -> filename (relative to `src_dir`) | `{"0079":"DJI_0079.MP4"}` |
| `res` | master `[W,H]` | `[3840,2160]` 4K, `[1920,1080]`, `[1080,1920]` vertical |
| `fps` | output fps | `30` |
| `xfade` | crossfade seconds between segments | `0.8` |
| `transition` | ffmpeg xfade transition name | `"fade"` (also `dissolve`, `smoothleft`, `fadeblack`...) |
| `fade_out` | fade-to-black seconds at the end | `1.5` |
| `fit` | how off-aspect clips fill the frame: `crop` / `pad` / `blur` / `stretch` | `"crop"` |
| `hdr` | `auto` tone-maps HLG/PQ clips to BT.709; `true` forces; `false` skips | `"auto"` |
| `ambient_audio` | keep each clip's own sound, tempo-matched and crossfaded | `false` |
| `grade` | base `eq` values (overrides persona `vlog.grade`) | see below |
| `warm` / `sharpen` | gentle colorbalance warm push / light unsharp | `true` / `true` |
| `stabilize` | built-in `deshake` + small zoom-crop (also per segment) | `false` |
| `stab_rx`, `stab_ry`, `stab_zoom` | deshake search range (x16, max 64) and keep fraction | `32`, `32`, `0.93` |
| `default_speed` / `empty_speed` | speed for subject / `kind:"empty"` segments | persona `vlog.speed_subject` 1.2 / `vlog.speed_empty` 1.3 |
| `seg_crf` / `final_crf` | x264 quality (lower = better) | `12` / `18` |
| `workers` | parallel segment encodes | `3` |
| `out` | master path | `"vlog_master.mp4"` |
| `segments` | ordered cuts | see below |

Each segment: `clip`, `start` (sec), `dur` (SOURCE seconds), optional `speed` (beats `kind`),
`kind` (`"subject"` default or `"empty"` for 空镜 / establishing), `bright` (added to
`grade.brightness`), `stabilize`. Legacy key `deer_speed` is still read as `default_speed`.

The opener has **no fade-in** by design, so the first frame is a usable poster. The end fades to black.

## Worked example
`examples/edit.example.json`. The arc that has worked on a dusk wildlife flight (9 silent DJI clips,
~3 min, 14 segments): wide establishing (sped up, brightened) -> reveal of the subject group ->
intimate single-subject moments in the middle -> calm walk-off / pull-back to close.
Most segments 8-22 s of source; weak shots trimmed short rather than sped up hard.

## Footage types
| footage | typical issues | settings |
|---|---|---|
| drone (DJI etc.) | long approach/retreat tails, dim dusk, silent | `kind:"empty"` on reveals, `bright` per dim shot |
| phone walking / travel | handheld shake, HDR, portrait, wind noise | `hdr:"auto"`, `stabilize` on shaky segments, `fit:"blur"` if mixing orientations |
| city / timelapse-ish | already fast; harsh highlights | speed 1.0-1.1, lower `saturation` to ~1.08 |
| nature close-ups | subject moves in and out of frame | short windows (4-8 s), speed 1.0-1.15 |
| ambient-audio vlog (waves, birds, street) | music would hide the place | `ambient_audio:true`, then `add_music.py --ambient-db -12` or skip music |

Vertical delivery (Reels/Shorts/小红书): `res:[1080,1920]`, `fit:"crop"` for landscape drone shots only
when the subject is central; otherwise `fit:"blur"`.

## Colour grade values
Dim / flat evening footage; lifts it without looking fake:
- `brightness 0.05`, `contrast 1.12`, `saturation 1.18`, `gamma 1.04`
- plus a gentle warm push (`colorbalance`) and light `unsharp`, on by default (`warm`, `sharpen`).
- **No vignette** on already-dim footage: it crushes the corners and reads as "too dark".
- Lift one dull shot with per-segment `bright` (e.g. +0.08), not the global grade.
- Midday / phone footage is usually already punchy: try `contrast 1.05`, `saturation 1.08`, `brightness 0`.
- Set your house look once in persona `vlog.grade`; edit.json `grade` overrides it per video.

## Speed / pacing
Aerial and walking footage is slow by nature; a mild global speed-up keeps it watchable:
- subject moments: ~1.2x (still breathe)
- empty / establishing 空镜: ~1.3x
- trim weak shots shorter rather than relying on speed alone.
- slow-mo: `speed < 1` on 60 fps sources (0.5x = 30 unique fps at 30 fps output, buttery; 0.6x fine).
- With `ambient_audio`, audio is time-stretched with `atempo` (pitch kept); above ~1.4x ambient sound
  starts to sound processed.

## Cover layout tuning
`make_cover.py` fills the frame with overlapping torn-paper fragments over a darkened backing photo, so
gaps between torn edges show scenery, never a black seam. Each photo is cover-fit into its piece and
zoomed by `bgsize`% around `bgpos` (CSS position). If a piece crops the subject out, override it in
`--config` (move `bgpos`, lower `bgsize`, or shift `left/top`). The **last piece is the hero** (biggest,
on top): your clearest / most expressive frame. Torn-edge roughness = `roughness` (feDisplacementMap
scale, default 13). Built-in hand-tuned layouts exist for 5 and 6 pieces at 16:9 (rescaled to other
landscape sizes); vertical or other counts use a generic overlapping grid with a centred hero.
No text by default; `--title` adds one torn-paper label (CJK titles use font role `cjk-bold`, latin
`serif-italic`; font files are copied next to the HTML in `assets/fonts/`).

Frames: extract clean stills at the timestamps you liked, slightly saturated:
```bash
ffmpeg -ss 3 -i CLIP.MP4 -frames:v 1 -vf "scale=1400:-1,eq=saturation=1.18" work/frames/a.jpg
```
For HDR phone clips, extract from the graded master (or `work/clips/seg_*.mp4`) instead of the source,
otherwise stills look washed out.

## Music
- `fetch_music.sh OUT_DIR "Title"...` pulls CC-BY 4.0 Kevin MacLeod tracks (static MP3s) and appends
  the credit line to `OUT_DIR/ATTRIBUTION.txt`. That credit MUST go into the post description.
- Catalog alternative: `npx hyperframes media-use resolve --type bgm` (HyperFrames / HeyGen catalog,
  see the `media-use` skill); it returns a frozen local file plus a ledger record. Check the licence
  it reports; copy any required credit into `ATTRIBUTION.txt` yourself.
- `add_music.py` loops/trims, fades, normalizes to persona `audio.loudness_lufs` (-14 default).
- If the user rejects a vibe ("太欢快了" / "too epic"), jump to a different row of the cheatsheet
  rather than re-fetching the same family.

## Export / compression variants
Native 4K masters are large (~1.8 GB for ~3 min at crf 18). Platforms re-compress on upload:
```bash
# visually-lossless 4K, much smaller
ffmpeg -i master.mp4 -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p \
  -c:a copy -movflags +faststart out_4k_small.mp4
# 1080p high-bitrate delivery
ffmpeg -i master.mp4 -vf scale=1920:1080:flags=lanczos -c:v libx264 -preset slow \
  -crf 19 -pix_fmt yuv420p -c:a copy -movflags +faststart out_1080.mp4
```
Quick draft: `probe.py --init work/edit.json --max-res 1920`, or set `res` to 1080p, then raise to
source res for the final.

## Gotchas
- **drawtext missing**: many Homebrew ffmpeg builds lack `drawtext`. Don't burn timestamps; read
  contact-sheet tile order instead (tile n ~= (n-1) * EVERY_SEC).
- **Contact sheets cover only 30 tiles**: 5x6 tiles at EVERY_SEC -> first 30*EVERY_SEC seconds. Raise
  EVERY_SEC for long takes.
- **Odd tile sizes**: pad/scale to even dimensions (yuv420p) or ffmpeg errors "Padded dimensions
  cannot be smaller than input dimensions".
- **Pixabay can't be curl'd**: its audio URLs are JS-injected. Incompetech serves direct MP3s.
- **slow-mo (speed < 1)**: `build_vlog.py` reads `dur` seconds of SOURCE (`-t` before `-i`) so a slowed
  segment expands to `dur/speed`. `-t` after `-i` caps the OUTPUT, silently truncates slow-mo, shifts
  every later xfade offset and can drop the last segment and the fade-out.
- **fps filter order**: `setpts` (speed) BEFORE the final `fps=` so output is clean CFR.
- **no black first frame**: never add `fade=t=in`.
- **xfade offset math**: timeline length is `sum(durations) - D*(n-1)`; each segment must be longer on
  screen than `xfade` (the script checks).
- **HDR without zscale**: Homebrew's default ffmpeg has no `zscale` (libzimg). `build_vlog.py` then
  falls back to a gamut-only `colorspace` conversion (highlights a bit flat). For proper HLG/PQ
  tone-mapping use an ffmpeg built with libzimg, or export SDR copies first (macOS Photos /
  QuickTime export, `avconvert` — unverified which presets drop HDR) and feed them in with `hdr:false`.
- **Rotation metadata**: phone clips store portrait as landscape + rotation; ffmpeg auto-rotates on
  decode, and `probe.py` reports the displayed orientation.
- **Chrome exit 126**: a quarantined or broken `chromium` on PATH; `make_cover.py` tries the next
  candidate, then Playwright. Force one with `CHROME=/path/to/chrome`.
