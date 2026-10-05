# PORT_NOTES: photo-story

## Sources
A project-specific build folder from a museum-exhibition video (read-only):
- `render_fx.py` (v3 core) + `fx_more.py` (v4 extension, injected via `setup(globals())`) → merged into
  `scripts/photostory/` as a package with an explicit `Ctx` object (no globals injection):
  `ctx.py` (spec, canvas presets/layout, fonts, palette, media lookup, shared arrays), `util.py`, `timeline.py`,
  `shots.py`, `overlays.py`, `transitions.py`, `looks.py`, `subtitles.py`, `render.py` (CLI).
- `tts_openai.py` (+ the `spoken/norm/trim/align/best_align` helpers it imported from `tts_clone.py`) → `tts.py`.
- `make_cover_v2.py` → `cover.py` (all text, images, circles and labels from spec `COVER`).
- `gen_learning.py` → `export.py` (SRT, read-along transcript + optional VOCAB, voice-only mp3, and a new `post.md`).
- `spec_en.py` → the spec format (unchanged tuple layout). The real content was replaced by the synthetic `examples/demo_spec.py`.

**Dropped:** `render.py`, `render_en.py`, `tts.py` and the backup specs, as instructed. `tts_clone.py` (local Qwen3 voice
clone) was dropped in phase 1 and **restored in wave B** as the `vstudio.tts` "clone" engine (see below).
All private media (img/, img_hd/, tts_oa/, cache/, ref) were dropped. The hard-coded music path became `BGM`.
`--stills` used to write into `/tmp/rv`; it now writes `<spec dir>/stills` (or `--stills-dir`).

## What changed from hard-coded to spec
- 1620x2160 / header 300 / box 1500 → `CANVAS` presets (3:4, 3:4-hd, 9:16, 16:9, WxH) + `LAYOUT`. Pixel
  constants scale by `ctx.b()` (box scale) or `ctx.t()` (canvas text scale). Landscape overlays subtitles on the picture.
- Route cities/legs/years + projection constants → `ROUTE`. The map now auto-fits an equal-aspect projection and supports `route:A>B>C`.
- Timeline 1483–1520 and tick years → `TIMELINE`.
- `VCROP`, `VEQ` (+ `VEQ_FILTER`), `FOCUS`, `FILM_SECTIONS`, titles, film-strip caption (`FILM_CAPTION`) and
  medal ring default → spec. Gold/red colours → `PALETTE`.
- TTS: key from env only, with no shell-rc sourcing. Voice, model, instructions, tries and whisper model come from `TTS`. Whisper falls back from mlx_whisper to faster_whisper to OpenAI whisper-1.
- New: with no `timing.json`, render uses estimated durations and silent audio, so layout can be checked before TTS.
- Dust overlay seeding used `hash(str)`, which changed between runs. It now uses a deterministic seed.

## Font mapping
| original (macOS system) | vstudio role |
|---|---|
| Songti (CJK serif titles, chapter names, quote 中文, map city names) | `cjk-serif` (**new optional role**, falls back to `cjk-bold`) |
| Hiragino Sans GB (中文 subs, section names, labels) | `cjk` / `cjk-bold` |
| Avenir Next (EN subs, labels, film captions, tags) | `sans` / `sans-bold` (**new optional roles**, fall back to `cjk` / `cjk-bold`; Noto Sans SC has Latin) |
| Georgia Italic (EN title, chapter number/EN name, quote EN, years, ring, map) | `serif-italic` (falls back to `cjk`/`cjk-serif` when the text contains CJK) |

Phase 2 could add real `sans`/`cjk-serif` entries (e.g. Inter, Noto Serif SC) to `vstudio.config.FONTS`.

## Capabilities
photo-fx, transitions, bilingual, captions, tts, asr (alignment only), music, loudness, overlays, progress-bar
(section progress header), cover, publish-copy, grade (VEQ, film look), other (route map, timeline, count-up, chapter cards).

Effect list: shots = image in/out/panL/panR/up/down/still/flip, video, collage, film, split, grid, tilt, deck,
quote, route, medal, rows. Overlays = sketch, develop, shimmer, dust, prick, hl, tri, loupe, tl, count, label.
Transitions = fade, push, whip, flash, zoom, iris, leak, ink, blinds, tear, slideup (+ cut). Looks = film grain,
vignette, memory film. Text = chapter cards, running header, bilingual subs with highlight and no-orphan wrapping.

## Duplicates for phase 2 (likely also in other workflows)
- loudnorm + voice/music mix: `render.py:mix_audio`, `export.py:main` (voice-only mp3)
- whisper wrapper with word timestamps: `tts.py:Transcriber`
- script↔ASR word alignment / subtitle timing: `tts.py:align`, `best_align`, `norm`, `trim`
- OpenAI TTS call: `tts.py:main.synth`
- bilingual subtitle rendering + highlight + balanced wrap: `subtitles.py:make_sub`, `wrap`, `bwrap`
- progress bar / section header: `subtitles.py:Header`
- SRT writer: `export.py:ts` + loop
- cover rendering (polaroid, red-pen circle): `cover.py:polaroid`, `circled`
- rawvideo → ffmpeg encode pipe: `render.py:main`
- canvas presets / safe layout: `ctx.py:PRESETS`, `Ctx.__init__`

## Persona keys used
Existing: `export.fps`, `export.crf`, `export.audio_bitrate`, `audio.loudness_lufs`, `publish.tags`,
`publish.chapter_line`, `fonts.*`. **New (optional, safe defaults):** `fonts.cjk-serif`, `fonts.sans`, `fonts.sans-bold`.
Brand colours are not taken from `persona.brand`, because the museum-gold look is the default story palette.
Override it per spec with `PALETTE`.

## Platform / unverified
- Verified: `py_compile` for all files, `--help` for every CLI, the synthetic demo rendered as `--stills`
  (24 stills covering every shot type and most transitions, in 3:4 and 16:9), a 3 s `--preview` (encode + silent audio), `cover.py`, and `export.py`.
- **Not run:** `tts.py` (needs an API key and costs money), the faster_whisper and whisper-1 fallbacks, BGM mixing, and a full render.
- Landscape (16:9): header section names are small, and the medal ring can sit partly under the overlaid subtitles.
  9:16 was not visually checked.
- Cover layout is tuned for portrait canvases. Landscape works but is cramped.
- Music: the original used a third-party track from a local library. It is not copied, so supply your own licensed `BGM`.

## Phase 2b rewire
The per-frame float-array effect engine (shots, overlays, transitions, looks, header, chapter cards,
labels) is untouched. Swaps (old → new):
- `render.py:mix_audio` (amix + single-pass loudnorm) → new shared `timeline.place_voice` (units placed on
  the timeline, 48 kHz stereo wav) + `audio.mix_bed` (when `BGM`) / `audio.loudnorm_2pass`, then muxed.
- `render.py` encoder args → `media.delivery_args(audio=False)` (+ `scale=out_color_matrix=bt709` so the
  RGB→YUV matrix matches the new bt709 tags on older ffmpeg builds; ffmpeg 9 already does this from the tags).
- `tts.py:Transcriber` → `asr.transcribe(cache=False, fix_terms=False)`. Spec `TTS.whisper` / `faster_model`
  still override the model. `tts.py:align` → `asr.align_script`. `best_align`, `norm`, `trim` and `spoken` stay local.
- `tts.py:main.synth` (openai SDK streaming) → `tts.synth(engine="openai")`. The first take may come from the
  vstudio cache, and retries pass `cache=False`. The **per-unit best-take cache** (`<TTS.dir>/cache/<md5>.wav/.json`,
  key = voice|model|instructions|text) is unchanged, so existing caches stay valid.
- `export.py:ts` + SRT loop → `subs.srt_write(which="both")`. `post.md` → `publish.post_body`, and chapter
  labels go through `publish.chapter_lines`. The voice.mp3 loudnorm → `place_voice` + `audio.normalize_stem` (-16) + mp3 encode.
- `subtitles.py:wrap/bwrap/runs` → `subs.balanced_wrap(measure=PIL textlength)` + `subs.parse_highlight` /
  `strip_markup`. This handles both `**` and 【】. `draw.wrap` was NOT used because it only parses the persona markup (【】), so
  `**` highlights would be measured as text and broken across lines.
- `cover.py:polaroid` → `cover.polaroid` (identical geometry). The thin wrapper passes the caption font file as
  `cap_role`, so latin captions keep the `sans` role fallback.

Behaviour changes (deliberate):
- Music bed is loudness-based: `BGM_LUFS` (default persona `audio.music_lufs`, -30) replaces linear
  `BGM_VOLUME`. A set `BGM_VOLUME` prints a note and is ignored. New optional `BGM_DUCK` (dB, default 0 = the old static bed).
  Fade-out stays 3.5 s. Final loudness is now two-pass linear rather than single-pass dynamic.
- Audio is 48 kHz **stereo** (it was mono). TTS takes are 48 kHz (they were 24 kHz).
- SRT times are rounded to ms (they were truncated, a ±1 ms shift) with no overlap. post.md is unchanged for the demo. On 小红书, a
  bilingual chapter label longer than 14 chars falls back to the 中文 name. New optional `POST.platform`.
- Long subtitle lines: a line never starts with `，`, "Claude Code"-style latin runs stay whole, and there are no empty `****`
  fragments. Breaks are DP-balanced.

Test evidence (synthetic demo in /tmp, before = `git HEAD` copy of scripts):
- py_compile all files, `--help` for render/tts/cover/export/make_demo_assets, `ruff --select F` clean, `pytest tests` green at the time (current count: run it; see tests/).
- `--stills` at 24 times, 3:4 and 16:9: **all 48 stills are bit-identical** before/after. `cover.png` is bit-identical. transcript.md
  and post.md are identical. The SRT differs only by 1 ms rounding.
- Wrap check, old vs new `bwrap` at real subtitle sizes: all 22 demo cues are identical on both canvases. 3 of 6 long synthetic
  lines changed, each for the better (see above).
- `asr.align_script` vs old `align`: 300/300 identical on randomised word streams with dropouts and substitutions.
- `tts.py` was run with mocked `tts.synth`/`asr.transcribe`. It made 3 tries per unit, wrote timing.json, and a second run hit the per-unit cache with 0 synth calls.
- Audio with fake narration + a lavfi music bed: 12 s preview -13.8 → -13.9 LUFS (persona -14), voice.mp3 -16.4 → -16.4 LUFS.
  Durations were the same (12.0 s / 24.12 s). A 3 s silent `--preview` still encodes with a (silent) stereo track.

Lib requests:
- `subs.balanced_wrap`: closing punctuation glued to a highlighted token inherits the highlight
  (`**里**，` becomes `**里，**`, so the comma is drawn gold). Keep punctuation outside the highlight.
- `draw.wrap`/`draw.runs`: accept `**` as well as the persona markup (as `subs.parse_highlight` does).
- `asr`: a public `backend()` resolver, so callers can pick a per-backend model override without re-probing imports.
- `cover`: a red-pen ellipse helper (`cover.py:circled`, the tagline circle) is still local.
- `audio`: a "place clips on a timeline → stem" helper (`timeline.place_voice`). Other TTS-driven workflows likely need it too.

## Wave B
Platform wiring, music-only mode, video clip audio, voice clone.

**A. Platforms** (`ctx.py`, `subtitles.py`, `render.py`, `cover.py`, `export.py`). New spec `PLATFORM` / `--platform`
on render, cover and export. With a profile, the canvas comes from `profile.size`. The header content starts at the safe
top (`HDR_Y0`), and its x margins are `max(t(70), safe)`. Subtitles go in `caption_box`: the 中文 size is clamped to the
profile's caption range, and both languages shrink until they fit the band width and height (`_make_sub_fit`). The box
spans header to caption box (portrait), or reaches the bottom under overlaid subtitles (landscape). Labels use
`LAB_BOT` / the safe left edge. Chapter names fit the safe width. The mix is loudnormed to the profile `lufs`/`tp`.
The cover uses `cover_size`, `post.md` takes the platform format, and render/export print `check_length` warnings.
Without `PLATFORM` the old layout is kept (`SAFE` = full canvas), and length checks use persona `platforms.default` in
the canvas orientation. `--clean-master` skips burned text and writes `<out>.cues.json`. `export.py` writes `cues.json`.
Docs recommend re-rendering per platform, plus `vstudio.export` for same-aspect / encode passes.
Deliberate 16:9 fixes, which also apply without `PLATFORM`:
- landscape header redesigned (title left, section bars + names right, names 0.17 x header height ≈ 27 px instead of 15 px);
- medal ring shrunk and centred in the area above the overlaid subtitles.
Platform portrait headers use bigger section names (1.7 % of H), and the title is pushed down to match.

**B. Music-only mode** (`music.py`, new). `MODE="music"`: `beats.analyze(BGM)` (cached pickle + `beats.json`). Shots get
integer grid units by weight (largest remainder, min 1). Spec sections are allotted first, and their boundaries snap
to `beats.sections` changes within a quarter section. Shots start on the grid points (transition begins on the downbeat,
default fade = half a unit). Spec lines become title-style text (`make_title_text`, 0.6 s fades). `MusicTimeline` has
the same surface as `Timeline`. Render prints `beats.verify` and writes `cache/music_cuts.json`. "auto" backend guard:
if the chosen grid catches few kicks (< 0.35) and the numpy tracker catches > 0.15 more, use numpy. Narration (+ BGM) mode
is unchanged.

**C. Clip audio** (`audiomix.py`, new). `audio="keep"|"duck"|"mute"` + `gain`. Clip sound is cut with `off`/`speed` (atempo)
and faded with the transitions. It is levelled to `CLIP_LUFS` (-16) / `AMBIENT_LUFS` (-26). Music ducks under kept clips
(`CLIP_DUCK` -10), ambient clips duck under narration (`AMBIENT_DUCK` -12), and the music still ducks under the voice
(`BGM_DUCK`). The new mixer is used only in music mode or when a clip keeps sound. Otherwise the old `audio.mix_bed` path
runs (identical output). Also new: HDR (HLG/PQ) clips are converted to SDR before crop (avconvert, or the ffmpeg
tone-map from `media.hdr_to_sdr_args`).

**D. Voice clone** (`lib/vstudio/tts.py`, clone engine only + `tts.py`). `tts.synth(engine="clone", ref_wav, ref_text,
language, seed, model)`:
- Qwen3-TTS through `mlx_audio.tts.utils.load_model`, imported optionally; the model is loaded once per process.
- The reference comes from the arguments, else persona `tts.clone.{ref_wav, ref_text, model, language}`.
- The cache key includes a sha1 of the reference audio + transcript, plus language and seed. Output is 48 kHz mono.
- Other engines and their cache keys are unchanged.
In the workflow, `VOICE` (merged over `TTS`) with `engine="clone"` / `--engine clone`:
- 4 seeded takes per unit, levelled to -20 dBFS RMS, Whisper-scored, with the original speech-rate penalty;
- the per-unit cache key is `clone|ref_hash|model|language|text`, so OpenAI keys are unchanged.
The user's reference voice is not in the repo. WORKFLOW.md shows the `persona.local.yaml` block (git-ignored).

New persona keys (optional): `tts.clone.ref_wav`, `tts.clone.ref_text`, `tts.clone.model`, `tts.clone.language`.
New spec keys: `PLATFORM`, `MODE`, `MUSIC`, `VOICE`, `CLIP_DUCK`, `AMBIENT_DUCK`, `CLIP_LUFS`, `AMBIENT_LUFS`; shot opts `audio`, `gain`.

Tests:
- **Default 3:4 and 9:16 demo:** 24 `--stills` each are bit-identical to `git HEAD` scripts. `cover.png`, `subtitles.srt`,
  `transcript.md` and `post.md` are identical. 16:9 changed only by the two deliberate fixes (Read: header readable,
  ring clear of subtitles).
- **Platform stills** for xiaohongshu:vertical, xiaohongshu:full (9:16), youtube and xiaohongshu:horizontal were Read
  with the safe / caption / keep-out boxes drawn on them. Header, subtitles and labels sit inside. Portrait header names
  were enlarged after the first look; a name/title touch was then fixed.
- **Music-only demo** (synthetic 90 BPM click track, accented downbeats, louder second half):
  - all 19 cuts on the true downbeats (`beats.verify` against the ground truth: max 0.0 frames, mean 0.9 ms);
  - 14 s `--preview`: -14.8 LUFS, -1.3 dBTP;
  - the clip with `audio="keep"`: clip tone +55 dB in its window, music downbeats 9 dB lower under it.
- **Duck check:** narration mode, fake voice + `audio="duck"` ambient clip. The ambient is 13 dB lower while the voice
  speaks; the mix measures -14.0 LUFS.
- **Clean master:** `--clean-master --platform douyin` → `master.cues.json`, then `python -m vstudio.export` to douyin and
  tiktok worked (-14.0 LUFS).
- **Clone engine, for real:** Qwen3-TTS 1.7B was already cached locally. The reference was a synthetic macOS `say` voice,
  not the user's. 2 units:
  - "He was born in Northport in 1890." scored 1.0 on the first take;
  - "…twelve photos" scored 0.875 on all 4 takes, because Whisper writes "12"; it fell back to the best take.
  - `tests/test_tts_clone.py` (mocked model): cache keys, persona fallback, errors.
- **REAL check** (outputs only in /tmp): 10 iPhone HEIC + 2 HLG MOVs, music only on Kevin MacLeod "Wholesome" (CC-BY),
  `PLATFORM xiaohongshu:vertical` 1080x1440, `grid="bar"`, `length=48`.
  - Timing: 128 BPM, 11 cuts on bars, 2 section boundaries moved onto music sections. `beats.verify` against the raw
    tracked beats gave max 0.49 frames.
  - 6 full-size stills Read: HEIC rotation correct, HDR clip tone-mapped, title text in the caption box, chapter card on
    the section change.
  - 10 s preview with a kept clip: -14.3 LUFS, -1.45 dBTP.
  - "Lightless Dawn" (ambient) has no steady grid (p90 270 ms), so cuts follow the raw beats; this is documented.
- `python3 -m pytest tests -q` green at the time (current count: run it; see tests/). `ruff --select F` is clean. `--help` works for all CLIs.

Lib requests:
- `beats.analyze` (librosa backend), synthetic 90 BPM kick track with off-beat hats added after 32 s:
  - it tracked only from 32.8 s, on the off-beat hats;
  - `tempo_check` (kick_on_grid 0.20) did not shift the grid by half a beat;
  - the numpy tracker also drifted to the off-beats once the hats entered.
  The workflow guard helps only partly. Please add a half-beat phase check on the final grid and track the whole file.
- `audio`: expose the ducking curve (`mix_bed`'s one-pole envelope) with an absolute threshold for stems that are
  digital silence between events. Today it is duplicated in `audiomix.duck_curve`. Also, a clip-sound extractor with
  speed/fades (`audiomix._clip_wav`).
- `asr`/`tts`: digit-aware scoring ("twelve" vs "12") for TTS take scoring; it is shared with other TTS workflows.

Unverified: a full-length render (only previews were rendered), and `xiaohongshu:horizontal` covers (the cover layout is
still portrait-tuned).
