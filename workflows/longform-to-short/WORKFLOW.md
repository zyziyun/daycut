# longform-to-short — long recording → cut course video and/or N short episodes

**Use when:** someone hands over a long recording — a lecture, webinar, livestream replay, podcast
with screen-share, a Zoom / Meet / Teams teaching or coaching session (typically 30–120 min) — and
wants it "剪成课程 / 上课实录 / 教学长视频", "切片发小红书 / 分几集", wants dead air and off-topic chatter
removed, browser chrome / bookmark bar cropped off, chapters + hook + zoom + 记笔记 panels +
subtitles added, a participant's voice anonymised, covers and 发布文案. Also for tweaking any one of
those on an already-cut video (every decision is a config value, so it is a cheap re-run).

**Inputs:** one recording (`raw/my-talk.mp4`), optionally its embedded caption track (speaker
labels), optionally a live web demo to re-record. **Outputs** (in `out/`): `final_subbed.mp4`
(1080p, hook cold-open, chapter cards, body sped up, code zoom cut-ins, note panels, burned subs
with 勘误 notes, ~−14 LUFS), `subs.srt` (soft CC), `cover_16x9.png`, `cover_3x4.png`,
`episodes/ep{N}.mp4` + `ep{N}_cover.png`, `发布包.md`.

Not in scope: writing a script (the recording exists), vertical 9:16 reframing (use a vertical
workflow on the episodes), music beds (tested and rejected for lectures — only a card stinger).

## Setup

```bash
export VSTUDIO=/path/to/video-studio          # repo root; ./install.sh fetched fonts + whisper
cd my-project                                  # your video folder
mkdir -p raw work out && mv ~/somewhere/my-talk.mp4 raw/
cp $VSTUDIO/workflows/longform-to-short/examples/config.example.py work/config.py
```

Edit `work/config.py` as you go (set `src` first). Every script is
`python3 $VSTUDIO/workflows/longform-to-short/scripts/<step>.py work/config.py`; below `$S` means
`$VSTUDIO/workflows/longform-to-short/scripts`. Scripts run inside `work/` (all JSON / PNG / segment
scratch lives there). Taste (speeds, loudness, accent colour, tags, term fixes, title limits) comes
from `persona.local.yaml`; per-video decisions from the config. Needs `ffmpeg` (with libass for
the burn step — else `pip install static-ffmpeg` and it is used automatically), Pillow, numpy,
scipy, and `mlx-whisper` (Apple Silicon) or `faster-whisper`.

## Pipeline

**1. Analyse the source**
```bash
python3 $S/analyze.py work/config.py          # audio16k.wav, rec_subs.srt, sounded.json, geo/*.png
python3 $S/transcribe.py work/config.py       # -> audio16k.json (minutes; run in background; cached)
python3 $S/geometry.py work/config.py         # -> geometry.json + crop_spans.json (chrome removed)
python3 $S/speaker_timeline.py work/config.py # -> speakers.json (labels + times only)
```
Set `speakers.aliases` so real display names become roles ("Host", "Guest") — unknown labels are
anonymised as "Speaker A/B…". Look at one `geo/` frame and set `share` (x0,y0,x1,y1 of the main
shared page) and `source_size`.

**2. Review blocks → keep / drop (human or LLM reads the transcript)**
```bash
python3 $S/make_blocks.py work/config.py      # -> blocks.txt (numbered, speaker-tagged)
```
Read `blocks.txt`; fill `keep.ranges` + `keep.chapters`. For a public video: drop chatter, logistics,
participant-specific advice, anything that names or identifies a participant; keep the teaching.
```bash
python3 $S/build_keep_list.py work/config.py  # -> keep_list.json, prints chapter table
```

**3. Polish targets**
```bash
python3 $S/transient_scan.py work/config.py   # accidental tab / desktop flashes -> transients.json
python3 $S/zoom_targets.py work/config.py     # code-block centroids for zoom.windows
```
Eyeball each transient; real ones → `freezes`. Participant questions to keep → `pitches.windows`
(decide by content). Word-level stumbles / asides → `cuts`. Pick the hook clip → `hook.src` + `hook.lines`.

**4. (optional) Re-record a stale live demo**
```bash
python3 $S/probe_app.py work/config.py        # screenshot + selectors of demo.url
python3 $S/record_demo.py work/config.py      # Playwright video -> set demo.rec, demo.enabled: True
```
Narration audio is kept; only the video of the `demo.keep_idx` segments is swapped.

**5. Master edit decision**
```bash
python3 $S/build_timeline.py work/config.py   # -> timeline.json (cards, clips, freezes, pitch, zoom)
```

**6. Overlays + render**
```bash
python3 $S/make_assets.py work/config.py      # cards/card_NN.png + hook_overlay.png
python3 $S/make_panels.py work/config.py      # panels/*.png + panels.json
python3 $S/make_audio_assets.py work/config.py   # card_sting.wav
python3 $S/render.py work/config.py           # -> out/final.mp4 (loudnorm to persona LUFS)
```

**7. Subtitles + final burn**
```bash
python3 $S/build_subs.py work/config.py       # subs.srt + subs.ass (term fixes, 勘误 notes)
python3 $S/burn_final.py work/config.py       # panels + subs in one encode -> out/final_subbed.mp4
```

**8. Covers, episodes, publish package**
```bash
python3 $S/make_cover.py work/config.py       # out/cover_16x9.png + out/cover_3x4.png
python3 $S/make_episodes.py work/config.py    # out/episodes/* + out/发布包.md
```
`episodes.count: N` auto-splits at chapter-card boundaries; `episodes.items` gives explicit chapter
ranges + per-episode cover copy. With neither, only the full-video 发布包 is written. For a
"short episodes only" job, still build the full cut and just publish the episodes.

**9. Verify before handing off**
```bash
python3 $S/qa.py work/config.py               # decode, loudness, mosaics, pitch check
```
- decode is clean; integrated loudness ≈ persona `audio.loudness_lufs` (−14).
- Open every `work/qa/mosaic_NN.jpg`: **zero participant avatars, name tags, bookmark bars, emails**.
- Pitch windows dropped ~3 semitones; the host's voice unchanged.
- Spot-check each cut join (re-transcribe ~6 s of final audio around it or just listen).

## Hard-won defaults
- **Platform auto-captions are unusable** for non-English speech (Meet/Zoom map Chinese onto random
  English words). Keep only speaker labels + timestamps; re-transcribe with whisper.
- **Whisper flags:** `condition_on_previous_text=False`, `hallucination_silence_threshold=2`, else it
  loops on 嗯嗯嗯 over silence (`transcribe.py` → `vstudio.asr.transcribe` sets both). Put domain terms in
  `asr_prompt` (or `--prompt`); `--backend mlx|faster|openai` forces an engine. Results are cached in
  `work/audio16k.wav.asr.json`, so re-runs are instant.
- **Speaker labels are often misattributed.** Decide who said what by content before cutting or
  pitch-shifting anyone.
- **Cut from the transcript, not from silence.** Meeting audio is too noisy for silencedetect-driven
  cutting; `sounded.json` only estimates dead air.
- **Sparse keyframes:** fast input-seek + `-frames:v 1` can land seconds off in meeting recordings.
  Stills seek ~25 s early and decode forward (`vstudio.media.grab_frame`); the transient scan decodes the
  whole file at 1 fps.
- **Overlaying a PNG** needs `-loop 1` + `overlay=…:shortest=1`, or the 1-frame stream ends before its
  `enable` window and silently never renders.
- **libass:** some ffmpeg builds (e.g. recent Homebrew) ship without the `ass` filter; `burn_final.py`
  asks `vstudio.media.ffmpeg_bin(need=["ass"])`, which falls back to `static_ffmpeg`.
- **VideoToolbox:** use `-q:v` quality mode, never a fixed `-b:v` (balloons the file). For code /
  slide text libx264 crf ~20 is crisper (`burn.encoder: x264`).
- **Seamless zoom cut-ins:** zoom/pitch/freeze splits are marked audio-continuous, so no afade at
  those joins; fades only at real cuts (30 ms in / 40 ms out).
- **No BGM.** A synthesized hook bed was tried and rejected as odd under a lecture; only a 1.6 s card
  stinger. Don't propose music beds for this genre.
- Geometry thresholds assume a light page on a dark meeting canvas; dark-mode shares need
  `geometry.bright` / `transients.luma` retuned.

## Publishing notes
- **YouTube:** full upload; timestamps in the description auto-create chapters (first must be 00:00);
  upload `subs.srt` as CC; 16:9 cover.
- **小红书:** regular-video cap is ~15 min (verify in the live uploader) → split into episodes at card
  boundaries. Chapter labels ≤ 14 chars (`publish.short_labels`); titles checked with `xhs_len`
  against persona `platforms.xiaohongshu.title_max`. Portrait 3:4 cover (feeds show a 4:3 crop).
- **B站:** optional archive.
- If the lecture contains a now-outdated claim, keep the burned 勘误 note (`subtitles.errata`) and pin
  `publish.errata_line` as a comment.

## Iterating
Change one knob, re-run from that step down:
- cuts / freezes / pitches / speeds / hook → `build_timeline` → `render` (`--from N` reuses earlier
  segments) → `build_subs` → `burn_final`.
- panel text only → `make_panels` → `burn_final` (no body re-render).
- term fixes / errata → `build_subs` → `burn_final`.
- cover copy → `make_cover`; episode copy → `make_episodes --no-video`.

Coaching-call variant (diarization, visual privacy leaks, word-level filler tightening):
`references/coaching-variant.md`.
