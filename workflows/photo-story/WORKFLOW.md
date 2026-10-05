---
name: photo-story
description: Turn your photos / short clips plus a narration script into a narrated, effect-rich story video (museum visit, travel, art history, product story) with bilingual EN/中文 subtitles, a running header with section progress, chapter cards, a cover and post copy, at any canvas size (3:4, 9:16, 16:9). Pure Python (PIL + OpenCV + ffmpeg), driven by one spec.py.
---

# photo-story

**Use when** someone has a folder of photos (and maybe a few phone clips) and a story to tell over
them: "make a narrated video of my museum visit / trip / this artist / this product", with Ken-Burns
moves, collages, maps, timelines, quotes, highlight circles, film looks, and burned-in bilingual subtitles.
Not for talking-head footage (see talkinghead workflows) or HTML/HyperFrames motion graphics.

**Inputs → Outputs**: `my_photos/*.jpg`, optional `my_clips/*.mov`, optional music bed, a `spec.py`
(titles, sections, script lines with EN+中文 cues, shot list) → `out/story.mp4` (H.264 + AAC, bt709-tagged, two-pass loudnorm),
`out/cover.png`, `out/subtitles.srt`, `out/transcript.md`, `out/voice.mp3`, `out/post.md`.

Scripts live in `$VSTUDIO/workflows/photo-story/scripts/photostory/`; run them from the project
folder. Paths inside the spec are relative to the spec file. Needs `ffmpeg`, numpy, opencv-python,
Pillow, soundfile, `OPENAI_API_KEY` for TTS (no `openai` package needed), and a whisper backend (`mlx_whisper` on Apple Silicon, else
`faster_whisper`, else the OpenAI `whisper-1` API). Fonts come from `vstudio.config.font` (`./install.sh`).

## Pipeline

1. **Gather media.** Put photos in `my_photos/` (names are the shot ids: `photo07.jpg` → `"photo07"`), clips in
   `my_clips/` (`IMG_1234.MOV` can be referenced as `"v1234"`). Still frames from a clip: extract them to
   `my_photos/` with ffmpeg and use them as photos.
2. **Write the spec.** Copy `examples/demo_spec.py` → `work/spec.py`. Fill `TITLE_*`, `SECTIONS(_EN)`, `CANVAS`,
   then `SCRIPT`: one item per narration clip, `(section, [(en, zh), ...], [(src, weight, motion, opts), ...])`.
   Write `**word**` for highlights. Keep each EN cue ≤ ~90 chars and 中文 ≤ ~38 chars. Put content data
   in spec tables, not code: `ROUTE` (cities/legs), `TIMELINE` (range/ticks), `FOCUS`, `VCROP`, `VEQ`, `FILM_SECTIONS`.
3. **Layout check before paying for TTS.** Without `timing.json`, durations are estimated (silent):
   ```bash
   python3 $VSTUDIO/workflows/photo-story/scripts/photostory/render.py work/spec.py --stills 2,10,25,40
   ```
   Stills go to `work/stills/` at 1/3 size (`--full` for full size). Look at each one. Check mid-transition times too.
4. **Voice.** `OPENAI_API_KEY` must be in the environment.
   ```bash
   python3 $VSTUDIO/workflows/photo-story/scripts/photostory/tts.py work/spec.py --sample   # pick a voice
   python3 $VSTUDIO/workflows/photo-story/scripts/photostory/tts.py work/spec.py            # all units -> work/tts/
   python3 $VSTUDIO/workflows/photo-story/scripts/photostory/tts.py work/spec.py 4 9         # redo units 4 and 9
   ```
   Each unit is taken up to 3× and the take whose transcript best matches the script wins (log shows `score`).
   The chosen take is cached in `work/tts/cache/` by text+voice+model+instructions, so editing shots never re-bills; editing a line
   re-synthesises only that line. Synthesis goes through `vstudio.tts` (48 kHz mono wav), transcription through `vstudio.asr`.
5. **Preview, then render.**
   ```bash
   python3 .../render.py work/spec.py --preview 20 --from 60      # -> work/cache/preview.mp4
   python3 .../render.py work/spec.py                              # -> spec OUT
   ```
   Rendering is single-process CPU work. The demo previewed 3 s at 1080x1440 in about 4 s on Apple Silicon.
   1620x2160 and heavy shots (tilt, loupe, ink) are slower, so start long renders in the background.
6. **Cover + side outputs.**
   ```bash
   python3 .../cover.py work/spec.py         # COVER dict -> out/cover.png
   python3 .../export.py work/spec.py        # subtitles.srt, transcript.md, voice.mp3 (-16 LUFS), post.md
   ```

## Spec reference (all optional except SCRIPT)

| key | meaning |
|---|---|
| `CANVAS` | `"3:4"` 1080x1440 · `"3:4-hd"` 1620x2160 · `"9:16"` 1080x1920 · `"16:9"` 1920x1080 · `"WxH"` |
| `LAYOUT` | `header`, `sub` (fraction of H or px), `overlay_subs`. Portrait default: header 13.9 %, picture box, sub band 16.7 %. Landscape default: header 15 % and subtitles overlaid on the picture over a gradient |
| `PALETTE` | `accent ground paper ink mark route sub_en sub_zh` (hex or RGB) |
| `TITLE_ZH/EN`, `SECTIONS`, `SECTIONS_EN` | running header + chapter cards (cards for sections ≥ 1, `CHAPTER_CARD` seconds, 0 = off) |
| `FILM_SECTIONS` | sections with the heavy memory-film look (grain, warm desat, flicker, scratches, dust) |
| `MEDIA` | `images`, `videos` folders and extensions |
| `FOCUS` | `{img: ((cx,cy), zoom)}` framing used inside collage/film/grid/split/rows/deck |
| `VCROP` / `VEQ` / `VEQ_FILTER` | per-clip crop `(cx, cy, width_frac)` / clips that get the grade filter |
| `ROUTE` | `title, note, cities={name: dict(lon, lat, zh, year, side)}, legs={key: [(a,b),...]}` |
| `TIMELINE` | `start, end, ticks, labels, format` for the `tl=` bar |
| `FILM_CAPTION` | caption under film-strip frames, `{n}` / `{name}` |
| `TTS` | `dir voice model instructions tries good use_say sample_voices sample_line whisper faster_model language` |
| `SAY` | spoken forms for numbers/names (alignment; also TTS input when `use_say`) |
| `BGM`, `BGM_LUFS`, `BGM_DUCK`, `OUT`, `AUDIO_BITRATE`, `FPS`, `PACING` | music bed (your own licensed file) at `BGM_LUFS` loudness (default persona `audio.music_lufs`, -30), `BGM_DUCK` dB while the voice speaks (default 0 = static bed), output; `PACING` = `gap sec_gap tail lead end_fade`. `BGM_VOLUME` is no longer used |
| `COVER`, `POST`, `VOCAB` | cover.py layout data / post copy (`title intro outro tags platform`; `platform` picks the `vstudio.publish` format, default persona `platforms.default`) / optional study table |

### Shot sources
`"img"` photo · `"v<clip>"` / `"video:<clip>"` (opts `off`, `speed`, `grade`) · `collage:a,b,c` · `film:a,b,c` ·
`split:a|b` (`labels=`) · `grid:a,b,c,d` · `tilt:a` (`yaw=(from,to)`) · `deck:a,b,c` · `quote:a` (`q=(en, zh, who)`) ·
`route:<leg>` or `route:A>B>C` · `medal:a` (`ring="TEXT · "`) · `rows:a,b,c`.
Photo motions: `in out panL panR up down still flip`; options `c=(cx,cy)`, `z=zoom`, `label="..."`, `tr=<transition>`, `trd=seconds`.

### Overlays (any shot)
`fx=("sketch","develop","shimmer","dust","prick")`, `hl=(cx,cy,rx,ry)` red-pen circle (`hl_t`),
`tri=((x,y),(x,y),(x,y))` composition triangle (`tri_label`), `loupe=[(x,y),...]` travelling magnifier (`loupe_mag`),
`tl=year` or `tl=(a,b)` timeline bar, `count=(n,"EN","中")` count-up. Coordinates are 0-1 of the picture box.

### Transitions (`tr=`)
`fade push whip flash zoom iris leak ink blinds tear slideup cut`.

## Gotchas
- **Transitions overlap the previous shot**: each shot keeps rendering for the next shot's transition time. Very
  short shots (< 1 s) with long transitions (leak 0.7 s) look busy.
- **Weights, not seconds**: shots share their script line's slot (voice + gap) by weight. To hold a shot longer, give it more weight or split the line.
- `prick` runs edge detection on the first frame it sees. Use it on a `still` shot.
- `sketch` looks best on detailed photos with `in` or `still`. `flip` mirrors the image half-way, which suits "drawn in mirror image" moments.
- Labels sit bottom-left of the picture. In landscape with overlaid subtitles they move above the subtitle band.
- Chinese text in any serif/italic slot automatically switches to a CJK font, because STIX has no CJK glyphs.
- Highlights (`**x**`) survive line wrapping. Lines are balanced so the last line is never a lone word.
- Route maps are schematic: an equal-aspect projection of the given lon/lat, fitted into the box. Use `side="left"` to keep labels from colliding.
- Editing a line's cue count invalidates that unit's timing. Render falls back to an estimate for that unit and prints a warning. Re-run `tts.py <i>`.
