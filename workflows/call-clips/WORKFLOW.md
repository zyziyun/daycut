# call-clips: multi-person call / interview / podcast → short clips, optional face masking

**Use when:** someone hands over any multi-person recording (Zoom, Google Meet, Teams, a
recorded interview or video podcast; gallery or speaker view) and wants short clips cut from
it ("截取一段对话发短视频 / 发一段出来"), optionally with one or more participants' faces hidden
behind a face-tracking sticker ("把朋友的脸遮一下 / 打个码 / 放个小猫"), in a vertical,
three-person or landscape layout. Also for tweaking an already-built clip: another sticker,
another segment, re-timed subtitles, a new cover, re-verifying that a face never leaks.

**Inputs → Outputs:** one recording (`recordings/my-call.mp4`) + a `clips.json` you author
(all times in **source** seconds) → per clip `out/<id>.mp4` (hook montage + sped-up body,
node cards between sections, 记笔记 note panels, burned subtitles, sticker over each masked
face with a geometric coverage proof, loudness-normalised, iPhone-safe h264), plus covers,
YouTube thumbnails and `.srt` tracks.

Layouts (`--renderer`):

| renderer | canvas | people | notes |
|---|---|---|---|
| `render_vertical.py` (default) | platform 9:16 (default persona platform, 1080×1920) | 2 tiles stacked | 1 masked guest, or `--no-mask`; safe zone on by default |
| `render_trio.py` | 1080×1920 or `--platform` | 3 tiles | 2 masked guests on top row, host below; quote cards |
| `render_landscape.py` | 1920×1080 or `--platform` | 2 side by side | bilingual subs, `--crop-w`, `--no-mask` |
| `render_landscape_trio.py` | 1920×1080 or `--platform` | 3 side by side | 2 masked guests, all tiles follow a 6s-smoothed face track |

Every renderer blurs the call app's **name labels** (bottom-left of each tile) by default; see
"Name labels" below.

Scripts live in `$VSTUDIO/workflows/call-clips/scripts/` (`$VSTUDIO` = repo root). Run every
command from the **project dir** (your video folder); outputs go to `work/` and `out/` there.
Below, `S=$VSTUDIO/workflows/call-clips/scripts`. Long-form craft notes, measured numbers and
the reasons behind every rule are in `references/craft-notes.md` — read it before a first run.

## Prerequisites

`./install.sh` (fonts, `face_landmarker.task`, Python deps), `ffmpeg`. No `drawtext`/`libass`
needed: every glyph is drawn with PIL. Whisper: `mlx_whisper` on Apple Silicon, else
`faster_whisper` (`transcribe.py` → `vstudio.asr`, cached in `work/audio16k.wav.asr.json`).
Chrome/Chromium/Edge (`$CHROME` first) or Playwright only to re-render sticker art.

## Pipeline

### 0. Check the layout (gallery vs speaker view)
Pull frames from across the whole file. The masking pipeline assumes **each person sits in a
fixed tile region** for the duration of a clip. Gallery view: confirm tiles never swap.
Speaker view / active-speaker switching: either restrict clips to stretches where the layout is
constant (one region per person per clip), or ask for a gallery-view recording. With no
masking (`--no-mask`), any fixed two-region layout works.

### 1. Measure tile geometry
Apps letterbox the recording; find real content rows first:
```python
g = cv2.cvtColor(cv2.imread("frame.jpg"), cv2.COLOR_BGR2GRAY); nz = np.where(g.mean(axis=1) > 12)[0]
```
A 1280×720 two-person gallery is usually two 640×360 tiles at y=180: guest `0,180,640,360`,
host `640,180,640,360`. A three-tile gallery is two on top and one centred below
(`0,0,640,360` / `640,0,640,360` / `320,360,640,360`). Identify who is where from the app's
name badges before deciding which tile gets a sticker.

### 2. Decide the cut: highlights or tiling
Ask. Highlights = 3–5 clips from the best moments. Tiling = clips end to end covering ~all of
the conversation (`clip[k].end == clip[k+1].start`), dropping only hesitation. Check tiling with
`python3 $S/transcript_tools.py coverage clips.json`.

### 3. Transcribe once, whole recording
```bash
python3 $S/transcribe.py recordings/my-call.mp4 --out work/audio16k [--prompt "Term, Term"]   # -> .wav + raw .json (word timestamps)
python3 $S/transcript_tools.py outline work/audio16k.json               # 45s chunks, pick segments
```
Snap every clip boundary to a whisper segment start so nothing opens or closes mid-word.

### 4. Work out who is actually speaking
```bash
python3 $S/speaker_timeline.py recordings/my-call.mp4 \
  --tiles guest=0,180,640,360 host=640,180,640,360 --out work/speakers.json
python3 $S/transcript_tools.py runs work/audio16k.json --speakers work/speakers.json
```
A mixed single audio track has no diarisation; this calls the speaker from whose inner-lip gap
moves more over 0.8s (any number of tiles). **Never attribute a quote from content alone** —
publishing someone else's story in the first person is not a cosmetic error. Sanity check:
total speaking time per tile should be roughly balanced over a conversation.

### 5. Privacy sweep before choosing windows
```bash
python3 $S/transcript_tools.py grep work/audio16k.json 剪掉 剪走 会剪 公司 <guest names> <whisper spellings>
```
Guests ask for cuts mid-recording, and a spoken name undoes a sticker. Whisper often renders a
spoken name as a placeholder-looking word (某某 / 默默 …), so grep variants too.

### 6. Author `clips.json`
Copy `examples/clips.example.json` (2-person), `clips_trio.example.json` (3-person) or
`clips_yt.example.json` (landscape long-form). Keys per clip:
- `windows` — keep-intervals `[[a,b],...]`; `nodes` — one entry per seam: a string = node card
  naming the next section (0.5s dissolve), `null` = silent trim (0.16s, no card; for redacting a
  few seconds mid-topic), `"~"` = full dissolve with no card (quote compilations).
- `hooks` — two 4–6s payoff pulls (≈7s total after speed-up), played first at hook speed with
  a "高光预告" badge.
- `panels` — `[anchor_src_s, dur_s, title, [3–4 bullets]]` 记笔记 cards, drawn over a **masked**
  tile (that face is a sticker already). Anchor where the point is actually *said* (check
  `work/<id>.subs.json`). `build_clips.py` exits if an anchor lands inside a cut.
- `title` (lines of `[text, is_accent]` runs), `accent`, `guest_label`/`host_label` (or set them
  once at the top level), `chapters`, `quote_cards`, `yt_title`, `thumb`, `cover_*`.
- Top level: `source`, `whisper`, `guest_region`+`host_region` or `guests: [{name, region,
  sticker, label, search?, upscale?}]`, `term_fix: [[regex, repl]]`, `auto_trim`, `audio`,
  `extra_cuts`, `track_host`, `translations`.

### 7. Read the auto-trim before building (optional, recommended)
```bash
python3 $S/find_disfluencies.py work/audio16k.wav work/audio16k.json --windows 12-96.5,104.9-180.2 [--profile word]
```
With `"auto_trim": true` every window is split at pauses, restarts, back-to-back repeats and
filler-only segments (~3% of body time). Two **cut profiles** (`scripts/cut_profiles.py`;
clips.json `"cut_profile"`, `--cut-profile`, persona `call_clips.cut_profile`):

| profile | pauses | with an editor pass | cut edges |
|---|---|---|---|
| `classic` (**default**, the original editor defaults) | > 0.75 s → keep 0.30 s | > 0.50 s → keep 0.25 s | snap **backward** to the quietest 20 ms frame (≤ 0.15 s before the edge) |
| `word` (phase-2 `vstudio.cut.find_cuts`) | > 0.60 s → keep 0.36 s | same | quietest frame between the neighbouring words' midpoints |

For a higher bar, run the **editor pass** (`references/craft-notes.md` → Editor pass):
`transcript_tools.py editor` dumps word-onset chunks, reviewers mark `[from, to, why]`, merge
into `work/editor_cuts.json`, point `"extra_cuts"` at it (~10% total). Review the longest
editor cuts before applying.

### 8. Build
```bash
python3 $S/build_clips.py --config clips.json [--only <id>]                    # 2-person vertical
python3 $S/build_clips.py --config clips.json --renderer render_trio.py        # 3-person vertical
python3 $S/build_clips.py --config clips.json --no-mask                        # nobody hidden
```
Per clip: cut each piece at its own speed (hooks 1.35× +3dB, body 1.2×; persona
`call_clips.*` overrides) → dissolve (`vstudio.cut.xfade_assemble`: whole-frame durations,
plain `xfade`/`acrossfade`, chunks of 30 pieces; its `TimeMap` maps source→final) → `track_face.py` per masked person
on the **assembled** file → `verify_coverage.py` on every track (**exits on FAIL**) → subtitles,
node cards, panels mapped source→final → render → two-pass loudnorm to
`audio.loudness_lufs` (`vstudio.audio.loudnorm_2pass`) + bt709 VUI retag (`media.retag_bt709`). `--reuse` skips cut/dissolve/track when work files exist (restyling in
~30s instead of minutes); any timeline change invalidates every track. Single frames:
`render_*.py ... --preview <sec> --out x.jpg`.

### 9. Verify
- `verify_coverage.py --track work/<id>.track.json --sticker assets/cat.png` must print `PASS`
  at 100% (build_clips already enforces this). Never "verify" by re-detecting faces in the
  masked video: the detector locks onto the cartoon's eyes and reports a face on every frame.
- **Subtitle review:** read every line of `work/<id>.subs.json`; re-listen to doubtful lines
  with large-v3 on a ~12s window; put fixes in `term_fix` (recording, `[[regex, repl]]`) or
  persona `subtitles.term_fixes` (creator, `{"heard": "meant"}`: **literal**, case-insensitive; a
  regex there no longer matches, move it to `term_fix`). Order: `term_fix` →
  `build_subs.CALL_TERM_FIXES` → persona → `vstudio.asr` generic list. If audio cannot settle a word, drop the phrase.
- **Redactions:** re-transcribe the finished mp4 and grep it — a clean config proves nothing
  about the render.

### 10. Covers, thumbnails, captions
```bash
python3 $S/make_cover.py out/<id>.mp4 --title-json work/<id>.title.json --at <first_panel+4> --out out/<id>.cover.jpg [--platform xiaohongshu]
python3 $S/make_thumb.py recordings/my-call.mp4 --title-json work/<id>.title.json --track work/<id>.track.json --sticker $S/../assets/cat.png --at 300 --out out/thumb.jpg [--platform bilibili]
python3 $S/make_thumb_trio.py out/YT.mp4 --title-json work/YT.title.json --at 900 --out out/thumb.jpg [--platform youtube]
python3 $S/export_srt.py work/YT.subs.json --prefix out/YT        # .zh / .en / .bilingual .srt
```
Each clip is published on its own: no "01 / 04" index, no caption referring to another clip.
Write the 发布文案 from the clip transcript.

### Long-form landscape (YouTube), two passes
```bash
python3 $S/build_clips.py --config clips_yt.json --renderer render_landscape_trio.py \
  --body-speed 1.0 --hook-speed 1.25 --sub-max-chars 24 --subs-only
# translate unique `text` lines of work/YT_full.subs.json into work/yt_en.json ({zh: en}), then:
python3 $S/build_clips.py --config clips_yt.json --renderer render_landscape_trio.py \
  --body-speed 1.0 --hook-speed 1.25 --sub-max-chars 24 --reuse
```
English is keyed by the final Chinese text, so re-cuts never misalign it.

## Platforms

`--platform` on `build_clips.py` (or `"platform"` in clips.json) and on every renderer:
`xiaohongshu`, `douyin`, `tiktok`, `youtube-shorts`, `bilibili:vertical` for the vertical renderers
(a bare name picks the platform's 9:16 canvas; `xiaohongshu:vertical` = the 3:4 1080×1440 feed
canvas), `youtube`, `bilibili`, `xiaohongshu:horizontal`, `douyin:horizontal` for the landscape ones.
Profiles live in `lib/vstudio/platform.py` (`references/PLATFORMS.md`; override in the persona).

| what | from the profile |
|---|---|
| canvas | `profile.w × h` |
| headline, hook badge, label chips, 记笔记 panels, node cards | inside `platform.safe_box` (top bar, bottom description, side buttons); panels/cards narrowed to the safe width |
| tiles | between the headline and the caption box; rows cut in height around the face when space is short |
| captions | `platform.caption_box`, size fitted with `fit_text_size` (shrunk to the box height), lines merged up to `caption.max_chars_zh` (14) unless `--sub-max-chars` |
| loudness | `profile.loudness` (LUFS / true peak) in the final two-pass loudnorm |
| length | `platform.check_length` warning on each clip's total |
| cover / thumbnail | `make_cover.py --platform` → `cover_size` (小红书 3:4 1080×1440, headline in `cover_title_safe`); `make_thumb*.py --platform` → cover-cropped to e.g. B站 1146×717 |

Defaults: `render_vertical.py` uses persona `platforms.default` (the old full-bleed layout ignored
the phone UI: title at 150, subtitles at 1654, both under the app chrome; `--platform legacy`
restores it). `render_trio.py` and the landscape renderers keep their fixed layouts unless given a
platform (`render_trio`'s was already hand-fitted to 小红书 9:16). Preview any layout with
`--preview <sec> --show-safe` (green = safe box, yellow = caption box, red = button column).

Several platforms: either re-render per platform (`build_clips.py ... --reuse --platform douyin`,
~30 s each, no re-tracking), or render a caption-free master and let `vstudio.export` re-burn the
captions per target:
```bash
python3 $S/build_clips.py --config clips.json --clean-master          # out/<id>.clean.mp4 + work/<id>.cues.json
python3 -m vstudio.export out/<id>.clean.mp4 --platforms xiaohongshu,douyin,youtube-shorts \
    --cues work/<id>.cues.json --cover out/<id>.cover.jpg --out exports/<id>
```
The clean master still carries the composed layout of its own canvas, so prefer per-platform
re-renders when the targets' caption bands differ a lot.

## Name labels

Call apps stamp each participant's real name at a tile's bottom-left; it survives the crop and
the label chip does not always cover it (real-media QA). `name_mask` in clips.json (or
`--name-mask/--name-box/--name-tiles/--name-extra` on any renderer and `make_thumb.py`):
`"blur"` (default: 1/16 downscale + blur, no glyph survives), `"cover"` (flat median colour),
`"off"`, or `{"mode": "blur", "box": [0, 0.90, 0.40, 0.10], "tiles": "all" | "guests",
"extra": [[x, y, w, h]]}`: `box` is the label rect as fractions of each tile, `extra` adds
source-pixel rects (a label in another corner, a speaker-view name). It runs on source pixels
before any crop. Check one preview frame zoomed on each tile's corner.

## Stickers
`assets/cat.png` and `assets/dog.png` are rendered from `assets/*_sticker.html` (in-house SVG,
same head ellipse, so `--scale 2.40 --y-offset -0.031` fit both). `cat_avatar.html/png` is a
full-tile "camera off" avatar, checked by `verify_avatar.py`. New art: edit/write an HTML,
`python3 $S/render_sticker.py assets/my_sticker.html --out assets/my.png`, then re-derive
scale/offset with a `verify_coverage.py` sweep (craft notes → Sticker sizing).

## Persona keys read
`platforms.default` / `platforms.<name>.*` (canvas, safe/caption boxes, loudness, length, cover),
`audio.loudness_lufs`, `brand.accent` / `brand.highlight` (note-panel header, badge, 记笔记 tag),
`brand.panel_theme` (记笔记 panel theme, default notes-red), `subtitles.term_fixes` (literal
heard → meant), `creator.language` (transcribe), `export.audio_bitrate`, and new
`call_clips.*`: `body_speed`, `hook_speed`, `hook_gain_db`, `sticker`, `cut_profile` (classic),
`name_mask` (blur), `frame_accent`
(default `#2DD4BF`), `labels.{hook_badge, hook_badge_landscape, node_eyebrow, note_tag, guest, host}`.

## Consent
A sticker hides a face, not a voice, a spoken name, an employer or an opinion about a former
team. Naming a masked guest's employer/role on screen can re-identify them. Whenever a masked
person is not the user, say so in the handover and recommend clearing the clip with them.
