# photo-story

**Use when:** Turn your photos / short clips plus a narration script (or just a music track: `MODE = "music"`, cuts on bars) into an effect-rich story video (museum visit, travel, art history, product story) with bilingual EN/中文 subtitles, a running header with section progress, chapter cards, a cover and post copy, at any canvas size (3:4, 9:16, 16:9) or laid out for a platform (`PLATFORM`). Narration by OpenAI TTS or your own cloned voice. Pure Python (PIL + OpenCV + ffmpeg), driven by one spec.py.

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
4. **Voice** (skip in `MODE = "music"`). OpenAI: `OPENAI_API_KEY` must be in the environment. Your own voice:
   `VOICE = dict(engine="clone")` (see "Voice clone" below).
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

## Modes
- **narration** (default): the TTS `timing.json` drives the timeline; optional `BGM` bed under the voice.
- **music** (`MODE = "music"` or `render.py --mode music`, no TTS): `beats.analyze(BGM)` drives it. Every shot gets a
  whole number of grid units by weight (min 1), so every cut lands on a bar (or beat). Spec sections start on the
  music's own section changes when one is within a quarter section (chapter cards + header follow). The `(en, zh)`
  lines become quiet title text (中文 serif + English italic, 0.6 s fades) spread over each item's shots; `captions=False`
  hides them, `"subs"` uses the speech-subtitle style. Lines may be empty: `(0, [], shots)`.
  ```python
  MODE = "music"; BGM = "music/bed.mp3"
  MUSIC = dict(grid="bar", per=1.0, length=None, start=0.0, tr="fade", trd=None, sections=True,
               captions="title", lufs=-16, backend="auto")
  ```
  `grid`: `bar` (calm, 文艺片) · `beat` · `2` (every 2 beats) · any number of beats. `per` = units per weight; `length` =
  target seconds instead. Default transition = a fade of half a grid unit (0.25-1.4 s) starting on the downbeat; per-shot
  `tr=`/`trd=` still win. Render prints `beats.verify` and writes `cache/music_cuts.json` + `cache/beats.json`
  (audit trail). The music is normalised as the main track (`lufs`, then the final loudnorm), fades out over the last bar.
  Ambient / rubato tracks have no steady grid (`grid raw` in the log): cuts then follow the tracked beats.

## Video clip audio
Video shots are silent by default. `("vIMG_1234", 1, "still", dict(audio="keep", gain=-3))` keeps the clip's own sound
in the foreground (the music dips by `CLIP_DUCK`, default -10 dB); `audio="duck"` keeps it as ambience (set to
`AMBIENT_LUFS` -26, dipping by `AMBIENT_DUCK` -12 dB while the narration speaks); `audio="mute"` = default. `gain` is dB
on top. Kept clips are levelled to `CLIP_LUFS` (persona `audio.voice_lufs`, -16). Clip sound follows `off=`/`speed=` and
fades with the picture transitions. iPhone HLG/PQ clips are converted to SDR first (avconvert on macOS, else ffmpeg tone-map).

## Voice clone (your own voice)
Offline Qwen3-TTS (Base) via `mlx-audio` on Apple Silicon, cloned from a 5-15 s recording of your voice:
```yaml
# persona.local.yaml (git-ignored) - never commit the recording or put it inside the repo
tts:
  clone:
    ref_wav: ~/voice/ref.wav                     # clean speech, no music, one speaker
    ref_text: "the exact words spoken in ref.wav"
    model: mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16   # optional (default); ~4 GB, downloaded on first use
```
Spec: `VOICE = dict(engine="clone")` (optional `ref_wav=`, `ref_text=`, `model=`, `tries=` 4, `good=` 0.93;
`VOICE` is merged over `TTS`), or `tts.py spec.py --engine clone`. Each unit is generated with seeds 1000*unit+try,
levelled to -20 dBFS RMS, transcribed by whisper and scored against the script; a speech rate < 1.6 or > 4.2 words/s
costs 0.2 (stuck / garbled takes). The best take wins; it is cached per unit by reference-audio hash + transcript +
model + text, and each seeded take is cached by `vstudio.tts`. Library use: `tts.synth(text, engine="clone", seed=1)`.

## Platforms
`PLATFORM = "xiaohongshu:vertical"` in the spec, or `--platform <name[:orientation]>` on `render.py`, `cover.py`,
`export.py` (`douyin`, `tiktok`, `youtube`, `youtube-shorts`, `bilibili:horizontal`, `xiaohongshu:full|horizontal` ...).
From `vstudio.platform`: the canvas (overrides `CANVAS`), the header content starts at the safe-zone top and stays inside
the safe left/right margins, subtitles are fitted (size from the profile's caption range, shrunk until both languages fit)
into `caption_box` (clear of the lower-right button column), the picture box sits between them (portrait) or under the
overlaid subtitles (landscape), labels stay above the subtitles and inside the safe margins, the final mix is loudnormed
to the profile's LUFS / true peak, `cover.py` uses `cover_size` (e.g. YouTube 1280x720), `post.md` uses the platform's
format, and render/export print `check_length` warnings. Without `PLATFORM` the old CANVAS layout is used unchanged
(length checks use persona `platforms.default` in the canvas orientation). The area below the caption box (the platform's
description UI) stays ground-coloured.

Because the header, picture box and labels are laid out per canvas, the best multi-platform route is **re-rendering per
platform** (`render.py spec.py --platform douyin --out out/douyin.mp4`; cached shots make it cheap). For an extra
encode/cover/post pass, or a same-aspect variant, write a caption-free master and let `vstudio.export` burn captions:
```bash
python3 .../render.py work/spec.py --clean-master --out out/master.mp4    # + out/master.cues.json
python3 -m vstudio.export out/master.mp4 --platforms douyin,tiktok --cues out/master.cues.json --cover out/cover.png
```
`export.py` also writes `cues.json` (text = 中文, alt = EN) next to the SRT.

## Spec reference (all optional except SCRIPT)

| key | meaning |
|---|---|
| `PLATFORM` | `vstudio.platform` profile, e.g. `"xiaohongshu:vertical"` (sets canvas + safe layout, LUFS, cover size) |
| `MODE`, `MUSIC` | `"narration"` (default) or `"music"` + its options (see Modes) |
| `VOICE` | TTS engine options merged over `TTS`; `engine="clone"` = your own voice |
| `CLIP_DUCK`, `AMBIENT_DUCK`, `CLIP_LUFS`, `AMBIENT_LUFS` | clip-audio levels / ducking (see Video clip audio) |
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
`"img"` photo · `"v<clip>"` / `"video:<clip>"` (opts `off`, `speed`, `grade`, `audio=keep|duck|mute`, `gain`) · `collage:a,b,c` · `film:a,b,c` ·
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
- Music mode with a click-free ambient track: `beats.analyze` may find no steady grid. Check the log (`grid raw`, p90
  residual) and `cache/music_cuts.json`; pick a track with a pulse, or `MUSIC.backend="numpy"|"librosa"` to compare.
- Landscape: the medal ring is shrunk and centred above the overlaid subtitles; the header puts the title left and the
  section progress right.
- Editing a line's cue count invalidates that unit's timing. Render falls back to an estimate for that unit and prints a warning. Re-run `tts.py <i>`.
