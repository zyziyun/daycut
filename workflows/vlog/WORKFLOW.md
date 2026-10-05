---
name: vlog
description: Edit a pile of silent or ambient B-roll clips (drone/DJI aerials, phone travel or walking clips, nature, city, action cam) into one short polished vlog - inspect the footage, cut the good windows out of long takes, colour grade (HDR phone clips tone-mapped), speed-adjust per shot, crossfade with a clean non-black opening and a fade-out ending, build a scrapbook torn-paper cover, and add CC-BY or catalog music. Use when someone hands over several clips and wants them "剪成一个vlog / 合并 / 去掉不好的部分 / 加转场 / 调色 / 配乐 / 做封面", even if they mention only one piece, or to tweak one stage of an already-built vlog (re-cut, re-grade, speed, music swap, cover, smaller upload file).
---

# vlog: B-roll clips -> short vlog

**Use when** the footage carries the story without narration: drone flights, walks, trips, nature,
city wandering, a day of phone clips. The raw material is long takes, slow moves, dim or HDR light,
dead tails, and no (or only ambient) sound. The craft is choosing good windows, tightening pace,
lifting the light, and giving it a soundtrack and a cover. Narrated / talking-head videos belong in
other workflows.

**Inputs ->** a folder of clips (MP4/MOV, any size, landscape or portrait, SDR or HLG/PQ).
**Outputs ->** `work/edit.json` (reusable edit list), `work/vlog_master.mp4` (graded, crossfaded),
`work/vlog_music.mp4`, `work/cover.png` (+ `cover_1920.jpg`), `music/*.mp3` + `music/ATTRIBUTION.txt`.

Tools: `ffmpeg`/`ffprobe`, Python 3, Chrome/Chromium or Playwright (cover), `curl` (music).
Everything runs from the PROJECT dir (the user's video folder); `$VSTUDIO` = repo root.
Read `references/recipes.md` before writing edit.json or hand-rolling any filter chain.

## Entry points
- "merge / 剪个vlog / 去掉不好的部分" -> full pipeline.
- "make a cover / 封面 / 剪贴报" -> step 6.
- "add music / 配乐 / 换首曲子" -> step 7.
- "higher quality / 高清一点" -> set `res` to source 4K, re-run step 5 (see Export variants).
- "too dark / 太暗" -> raise `grade.brightness` or per-segment `bright`, never add a vignette; re-run step 5.
- "too shaky" -> `"stabilize": true` on those segments; re-run step 5.

## Pipeline

1. **Probe and confirm scope.**
   ```bash
   python3 $VSTUDIO/workflows/vlog/scripts/probe.py footage/*.MP4 footage/*.MOV
   ```
   Note size, fps, duration, audio and HDR per clip. If the user named a subset, edit only those.
   Confirm the subset and target (16:9 4K master? vertical 1080x1920?) before any long render.

2. **SEE the footage (never edit blind).**
   ```bash
   bash $VSTUDIO/workflows/vlog/scripts/contact_sheets.sh work/sheets 4 footage/*
   ```
   Read every `work/sheets/*_sheet.jpg`: one tile per 4 s, 5 across, left->right top->bottom,
   each labelled with its source time (tile n = (n-1)*4 s). Mark windows where the subject is clearly framed and the move is smooth;
   skip approach/retreat tails, pocket shots, shaky stretches.

3. **Write the edit list.**
   ```bash
   python3 $VSTUDIO/workflows/vlog/scripts/probe.py footage/* --init work/edit.json
   ```
   then replace the placeholder `segments` with `{clip,start,dur}` windows (optional `speed`,
   `kind:"empty"`, `bright`, `stabilize`). Order them into a small arc: wide establishing ->
   reveal -> intimate subject moments -> calm closing shot. Keep most segments 8-22 s of source.
   Schema + example: `references/recipes.md`, `examples/edit.example.json`.

4. **(optional) Draft first.** Copy edit.json with `res` at 1080p (or `--max-res 1920` on `--init`)
   and `"out": "draft.mp4"`; render, watch, adjust windows.

5. **Render the master.**
   ```bash
   python3 $VSTUDIO/workflows/vlog/scripts/build_vlog.py work/edit.json          # --dry-run to inspect
   ```
   Renders segments in parallel (HDR tone-map -> fit -> grade -> speed -> fps), then crossfades into
   one master with NO black first frame and a fade-out at the end. A true-4K pass is slow: run it in
   the background and report when done. `"ambient_audio": true` keeps each clip's own sound
   (tempo-matched, crossfaded) instead of a silent master.

6. **Build the cover** (scrapbook torn-paper collage, full-bleed, no text by default).
   Extract 5-6 frames where the subject reads clearly plus one wide frame for the darkened backing:
   ```bash
   mkdir -p work/frames
   ffmpeg -ss 3 -i footage/CLIP.MP4 -frames:v 1 -vf "scale=1400:-1,eq=saturation=1.18" work/frames/a.jpg
   python3 $VSTUDIO/workflows/vlog/scripts/make_cover.py --out work/cover.png \
     --hero work/frames/hero.jpg --frames work/frames/{a,b,c,d}.jpg --base work/frames/wide.jpg
   ffmpeg -i work/cover.png -vf scale=1920:1080 -q:v 2 work/cover_1920.jpg
   ```
   Vertical: `--size 1080x1920`. Optional label: `--title "..."` (vstudio font roles, staged into
   `work/assets/fonts/`). Read `cover.png`; if a piece crops the subject, copy
   `examples/cover.example.json`, adjust `bgpos`/`bgsize`/`left/top`, and re-run with `--config`.
   For HDR phone clips pull frames from the master, not the source.

7. **Add music.** Ask for the vibe in the user's words, map it to the cheatsheet inside
   `fetch_music.sh`, fetch, mux:
   ```bash
   bash $VSTUDIO/workflows/vlog/scripts/fetch_music.sh music "Atlantean Twilight"
   python3 $VSTUDIO/workflows/vlog/scripts/add_music.py work/vlog_master.mp4 \
     music/Atlantean_Twilight_KevinMacLeod.mp3 work/vlog_music.mp4 --fade 2
   ```
   `add_music.py` loops the track to fill, fades it in/out, two-pass normalizes to persona
   `audio.loudness_lufs` (-14), and copies the video stream (fast). With an ambient master add
   `--ambient-db -12` to keep the place's sound 12 dB under the music bed (`vstudio.audio.mix_bed`).
   **Attribution:** these tracks are CC BY 4.0. `music/ATTRIBUTION.txt` holds the credit line(s);
   give them to the user to paste into the post description.
   **Catalog alternative:** `npx hyperframes media-use resolve --type bgm` (HyperFrames / HeyGen
   catalog via the `media-use` skill) returns a frozen local track; use it with `add_music.py` the
   same way, and record whatever credit its licence requires in `music/ATTRIBUTION.txt`.
   Music taste is subjective: deliver one, offer named swaps from a different cheatsheet row
   ("too cheerful" / "too epic" -> change family, not track).

8. **Deliver.** A native-4K master is large (~1.8 GB per ~3 min). Offer a smaller visually-lossless
   4K or high-bitrate 1080p (commands in recipes.md). State duration, resolution, file size, and list
   the files produced. `work/clips/seg_*.mp4` are safe to delete.

## Scripts
- `scripts/probe.py` - per-clip size/fps/duration/audio/HDR; `--init` writes a starter edit.json.
- `scripts/contact_sheets.sh` - time-labelled thumbnail grids per clip (wraps `vstudio.media.contact_sheet`).
- `scripts/build_vlog.py` - config-driven HDR tone-map + fit + grade + speed + stabilize + crossfade master.
- `scripts/make_cover.py` - torn-paper scrapbook cover, any size, optional title; Chrome/Chromium/Playwright.
- `scripts/fetch_music.sh` - CC-BY Incompetech tracks by title + `ATTRIBUTION.txt`.
- `scripts/add_music.py` - loop/fade/two-pass-loudnorm music mux (optional ambient bed), video copied.

## Persona keys (all optional)
`vlog.speed_subject` (1.2), `vlog.speed_empty` (1.3), `vlog.grade` ({brightness, contrast,
saturation, gamma}), `vlog.cover_tape` (title label underline colour); plus existing
`audio.loudness_lufs`, `audio.music_lufs` (bed level before the final loudnorm), `export.audio_bitrate`.
