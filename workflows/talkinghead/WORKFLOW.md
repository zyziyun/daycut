# talkinghead — 口播 re-edit into a 小红书 short post

**Use when:** someone hands over recorded Chinese talking-head 口播 / 复盘 footage (a horizontal 剪映 export with
burned subtitles, one or more raw vertical iPhone HDR clips, or a raw horizontal webcam / camera recording) and wants any of: 合并剪辑 / 二次剪辑 / 去气口 /
去 filler word / 加 hooks / 加进度条 / 加气泡 / 加面板 / 修图 / 换剪辑风格 / 加速 / 做封面 / 发小红书. Also for tweaking
one piece of an already-built video: hooks, speed, style switches, panels, stamps, progress bar, cover,
caption, or which sentences are cut.
**Inputs → Outputs:** source clip(s) + a per-video config → an H.264 MP4 on the target platform's canvas (小红书 9:16
1080x1920 by default, 3:4 1080x1440, 抖音 / Shorts 9:16, YouTube / B站 16:9 1920x1080; see Platforms) with a
sped-up hook montage, strict filler/pause removal, portrait retouch (V), subtitles, grade, chosen editing
style, loudnorm to persona `audio.loudness_lufs`; plus a cover image and a 发布文案 (title, chapter timeline, tags).

Config-driven ffmpeg + PIL pipelines: everything for one video lives in one config file. Iterating means
editing the config and re-running one script, so turn changes around one at a time. Writing the spoken
script itself is the preproduction side (persona `voice.*`); this workflow covers **edit and packaging**.

Scripts: `$VSTUDIO/workflows/talkinghead/scripts/` (H track + shared `asr.py`, `caption.py`) and
`scripts/vertical/` (V track). Run from the project dir (the user's video folder) unless a step says WORK.
Prereqs: `ffmpeg`, Python with `numpy opencv-python pillow soundfile mediapipe`, a whisper backend
(`mlx_whisper` on Apple Silicon, else `faster_whisper`, else OpenAI `whisper-1` via `OPENAI_API_KEY`), and
`./install.sh` for fonts + face model. Both tracks are built on `lib/vstudio` (cutting, dissolves, loudness,
ASR, overlays, covers, publish copy); only the V-track per-frame animation engine and the cut-list logic are local.

## Step 0: pick the track and the style

**Track**
- **V track (main engine)**: raw clips without subtitles: vertical phone clips (usually 1080x1920 HLG HDR,
  possibly several) or a horizontal webcam / camera recording (see Horizontal footage). `scripts/vertical/`.
  Supports every style, renders vertical (9:16, 3:4) or horizontal (16:9). See below and `references/vertical_pipeline.md`.
- **H track, horizontal (legacy)**: a 1920x1080 剪映 export that already has burned subtitles. `scripts/*.py`.
  Notes-board style only. **`scripts/vertical/compose.py` supersedes `build_filter.py`** (sid anchors, all
  styles, per-frame overlays); the H scripts are kept working for horizontal 剪映 exports. Both tracks share
  `scripts/montage.py` (muted-pad hook dissolves).

**Style.** Read `references/styles.md` (the strategy menu: what each looks like, when it fits, its knobs).
Ask the creator which preset they want:
- **记笔记风**: classic progress bar, callouts, 记笔记 panels, hook badge. Calm, 干货-dense, screenshot-friendly.
- **精剪风**: zoom rhythm, pop words, red stamps, circle list scenes, card, SFX, refined progress bar. Fast and punchy.
- **混合**: 精剪 rhythm plus 记笔记 panels for the 2-3 most note-worthy points.

On the V track the style is just the `STYLE` dict in the config, so switching later costs one re-render.

## Shared rules (both tracks)

- **Hooks are the highest-leverage choice, so the creator picks them.**
  - Scan the transcript and present a numbered menu of about 12 candidates: text, a type tag
    (核心观点 / 反差 / 吐槽 / 共鸣 / 金句 / 悬念) and length at the hook speed. Suggest 2-3 combos.
  - The creator picks the set and the order. Half-sentences are allowed.
  - Re-check the cut with ASR at normal speed (`atempo=1/HOOK_SPEED`).
- **Disfluency.** Fillers, repeated words, restarts and breaths go; 气口 squeezed to persona
  `audio.pause_squeeze` (0.06s). One heuristic pass is not enough: do the strict word-level pass every time.
- **Cutting padding sentences (废话).** When asked, propose the exact sentence list first: background asides,
  sentences repeating the previous one, hedges (「也可能这是我的感觉」), a second example of the same point.
  Then drop the agreed sentences by sid.
- **Speed.** Defaults persona `speed.hook` 1.3x / `speed.body` 1.1x. On 加速: hooks 1.5-1.65x, body 1.25-1.35x
  (`fast_hook` / `fast_body`). Chinese speech stays intelligible up to about 1.4x (`cjk_max_intelligible`).
- **Safe zone.** Comes from the platform profile (`vstudio.platform.safe_box` / `caption_box` / `keepouts`). 小红书 9:16:
  meaningful content in y 240..1660, nothing on the right edge in the lower half (buttons), subtitles around y 1525.
  Other canvases: see Platforms.
- **Subtitles.** Read every line against the audio before handover. Whisper mangles English terms in Chinese
  speech: pass a term prompt, put recurring fixes in persona `subtitles.term_fixes`, fix the rest by hand.
  Mark line breaks with `|` so a word is never split.
- **Hook dissolves never cost a syllable.** Every join plays over muted pads on BOTH sides (`cut.xfade_assemble`
  `mute_pad="both"`): the outgoing clip runs on and the incoming one starts early by XF*speed, both muted, and the
  body opens on a cloned first frame + silence. So each join adds about 2*XF of silent dissolve; keep XF short
  (0.3s on V; the H example's 0.8s gives 1.6s per join, lower it if the montage drags).
- **Export.** 1080p30 H.264 high, bt709 tags via the `h264_metadata` bsf, AAC 192k 48k, `+faststart`,
  two-pass linear loudnorm to persona `audio.loudness_lufs` (`vstudio.audio.loudnorm_2pass`).
- **Caption.** `references/publish_caption.md`; `scripts/caption.py` does the counting and the timeline.

## V track: vertical phone clips, all styles

Run in a WORK dir (e.g. `mkdir -p work && cd work`), `V=$VSTUDIO/workflows/talkinghead/scripts/vertical`.
Full notes in `references/vertical_pipeline.md`.

1. **HDR→SDR, audio, word-level whisper.** `PROMPT="术语 列表" bash $V/prep_sources.sh . ../clip1.MOV ../clip2.MOV`
   → `sdrN.mp4`, `aN.wav`, `aN.json`, `prep.json` (`vstudio.media.to_sdr`: `avconvert` for HDR on macOS, ffmpeg zscale
   tonemap elsewhere; whisper is cached next to the wav). Landscape clips are reframed to 9:16 (Horizontal footage).
2. **Keep list**, one entry per sentence (sid = list index): write `edit_list.py` from `examples/v_edit_list_example.py`.
3. **Snap to voice, squeeze pauses, frame-exact cut.** `python3 $V/cut_pass1.py edit_list.py` → `body_v.mp4 body_a.wav segs.json`.
4. **Per-frame retouch** (slim, eyes, de-shine, three-band skin smoothing, subtle "natural" makeup;
   One Euro-smoothed landmarks from a VIDEO-mode face-crop tracker, landmark-anchored masks, 15-frame
   chunk warm-up so seams don't jump; ~0.8 s/frame/worker).
   `python3 $V/retouch_video.py body_v.mp4 x --test 300,2500` to check, then
   `python3 $V/retouch_video.py body_v.mp4 body_rt.mp4 --workers 5`.
   Knobs: `--makeup 0` (off) / `--preset daily`, `--smooth`, `--pores`, `--glasses thick`; persona
   `retouch.video.<knob>` sets your defaults. All knobs, presets and checks: `references/RETOUCH.md`.
5. **Strict filler pass on the retouched body.** `python3 $V/strict_pass.py transcribe body_a.wav "$PROMPT"`
   (prints the indexed words plus `DEL candidates` from `vstudio.cut.suggest_fillers`: fillers, repeats, merged
   restarts; check each by ear), write `strict.py` (`examples/v_strict_example.py`), then
   `python3 $V/strict_pass.py apply strict.py body_rt.mp4 body_a.wav body2_rt.mp4 body2_a.wav`.
6. **Optional: drop 废话 sentences by sid.** `python3 $V/drop_pass.py "1,7,11" body2_rt.mp4 body2_a.wav body3_rt.mp4 body3_a.wav`.
7. **Face track on the final body.** `python3 $V/face_track.py body3_rt.mp4 face3.npy` (centre + face box per sample;
   compose uses the boxes to cap the punch-in and keep titles, callouts, PiP cards and pop words off the face).
8. **Config** with STYLE switches and sid-anchored times: copy `examples/v_config_example.py` to `config.py`.
9. **Preview, then render.** `python3 $V/compose.py config.py base`, `python3 $V/compose.py config.py preview 3,40,90`
   (look at `preview.jpg`), then `python3 $V/compose.py config.py comp` (or `all` for base+comp).
   Add `--platform xiaohongshu:vertical` (3:4) / `douyin` / `youtube` for another canvas (`preview_<platform>.jpg`).
10. **Cover** (3:4, 1080x1440 by default). `python3 $V/pick_cover_frame.py body3_rt.mp4` ranks frames by
    `mouthSmile - 1.5*eyeBlink - |cx-0.5|` and writes a contact sheet; set `COVER` in the config, then
    `python3 $V/cover.py config.py` (`--platform douyin --platform youtube` adds 9:16 / 1280x720 covers). Bottom gradient + 2-line title (line 2 with yellow keywords), a 记笔记 sticky
    top-left, a rotated red tag top-right. Always look at the rendered cover.
11. **Caption.** `python3 $VSTUDIO/workflows/talkinghead/scripts/caption.py config.py --title "..." [--platform douyin]`
    (title / description / tag / length limits per platform).

Effect times are anchors, not seconds: `S(sid, frac)`, `E(sid)`, `SPAN(a, b)`, `W(sid, "word")` from
`anchors.py`. Sentence ids survive steps 5 and 6, so later cuts never break effect timing. Use raw body
seconds only for half-sentence hooks. **Never re-run step 4 to apply a later cut**: steps 5 and 6 cut the
already-retouched body.

## H track: horizontal 剪映 export, notes-board (legacy)

`H=$VSTUDIO/workflows/talkinghead/scripts`, run from the project dir.

1. **Work dir and transcript.** `ffprobe` (expect 1920x1080/30), `ffmpeg -i my-talk.mp4 -ac 1 -ar 16000 work/audio.wav`,
   `python3 $H/asr.py work/audio.wav work/audio.json --prompt "术语"`. Whisper hallucinates over a silent tail,
   so set `MAIN_DUR` to where the real content ends. (macOS: Voice Memos files are TCC-protected; ask the user
   to drag them into the project folder.)
2. **Hooks menu**, as in the shared rules.
3. **Fill `work/config.py`** from `examples/h_config_example.py`: CHAPTERS (6-8, 2-4 character labels),
   CALLOUTS (full-sentence bubbles of ~5s), PANELS (记笔记 cards, 5-7, anchored where the point is said),
   REMOVE (callouts now covered by a panel), HOOKS.
4. `python3 $H/make_assets.py work/config.py` renders the bar, active-chapter highlights, hook badge, callouts, panels, `assets.json`.
5. `python3 $H/build_filter.py work/config.py && bash work/run.sh`: hook montage with muted-pad dissolves, body
   speed-up, eq grade, always-on bar (fill + playhead now actually move), overlays, two-pass loudnorm.
   Also writes `work/timeline.json` (read by `caption.py`).
6. **QC.** Duration ≈ `BODY_START + MAIN_DUR/BODY_SPEED` (`work/timeline.json`), loudness, 3-4 frames: a hook, the handoff, a panel, a callout.
7. **Cover.** `python3 $H/detect_head.py frame.jpg` → `COVER_HEAD_X`, then `python3 $H/make_cover.py work/config.py`:
   notes-board cover with the face centred, 2-3 mini panels and a yellow sticky. Keep cards inside the 4:3 crop
   x[240,1680] and judge `work/cover43.png`, not the full frame.
8. **Caption.** `python3 $H/caption.py work/config.py --title "..."`.
9. **Other platforms.** `PLATFORM = "youtube"` (or `--platform` on make_assets / build_filter / make_cover) moves the
   bar / badge / callouts / panels into that profile's safe box and sets loudness; `make_cover.py --platform youtube
   --platform bilibili` re-fits the cover to 1280x720 / 1146x717. Vertical versions: `python -m vstudio.export` on the
   output (face-tracked reframe; the 剪映 burned subtitles are part of the picture, so check they survive the crop).

## Platforms
One config, any canvas. `PLATFORM = "..."` in the config or `--platform` on `compose.py`, `cover.py`, `caption.py`,
`build_filter.py`, `make_assets.py`, `make_cover.py`. Default: persona `platforms.default` in the track's natural
orientation (V: 9:16, H: 16:9), i.e. the old 小红书 layout, pixel-identical.

| target | canvas | what changes |
|---|---|---|
| `xiaohongshu` (9:16 "full", default) | 1080x1920 | measured layout: bar y 250, title y 330, panels above captions at y 1525 |
| `xiaohongshu:vertical` | 1080x1440 (3:4) | 9:16 body face-cropped to 3:4 once (`body_1080x1440.mp4`); bar y 70, captions band 1080..1270 (y 1170), circle scene radius fits the shorter frame |
| `douyin`, `tiktok`, `youtube-shorts`, `bilibili:vertical` | 1080x1920 | their safe boxes: captions higher (抖音 y 1345, above the description), stamps/pops kept left of the button column |
| `youtube`, `bilibili`, `xiaohongshu:horizontal` | 1920x1080 | landscape layout (below) |

Derived from the profile: canvas, progress bar / hook title / callout / panel / circle / card positions (layout.py),
caption band, size fit and width, keep-outs, loudness (LUFS + true peak), length warnings, cover size + feed-crop preview,
title / description / tag limits. Config pixel coordinates (POPS, STAMPS) are authored on 1080x1920; on other canvases
they move with the face and are clamped above the captions and off the face. A `STYLE sub_y` outside the caption band is ignored with a note.

**Landscape layout (16:9).** Same effects: progress bar 1.25x, 记笔记 panel and callouts on the side away from the face,
circle scene = face circle left + title/tokens right, card scene = card left + text column right, split screen left/right.
A 9:16 body on a 16:9 canvas goes on a blurred fill; a 16:9 body (Horizontal footage) fills it.

**Many platforms from one render.** `python3 $V/compose.py config.py comp --clean-master` also writes
`<OUT>.clean.mp4` (no burned captions; overlays kept) and `<OUT>.cues.json` (final-time captions). Then:
```bash
python3 -m vstudio.export ../my-talk_xhs.clean.mp4 --platforms xiaohongshu:vertical,douyin,youtube-shorts \
    --cues ../my-talk_xhs.cues.json --cover ../my-talk_cover.jpg --out exports/
```
Each export gets captions placed for that UI, loudness per profile, a cover and `manifest.json`. Overlays burned into a
9:16 master survive a 3:4 face crop only if they sit inside it; for 16:9 or a different layout, re-render with `--platform`.

## Horizontal footage (webcam / camera, 精剪 / 记笔记 styles)
- **Vertical output:** `bash $V/prep_sources.sh . ../webcam.mp4` reframes a landscape clip to 1080x1920 with
  `vstudio.reframe` face mode: per-frame face detection, One Euro smoothed target, virtual camera with a dead zone,
  eased pans and shot-cut resets, the face kept in the platform safe box (eye line ~1/3 down). No face → pad-blur.
  `prep.json` records the mode, face hit rate and the **upscale** (a 1080p webcam cropped to 9:16 is enlarged 1.78x).
- **Horizontal output:** `ORIENT=horizontal bash $V/prep_sources.sh . ../webcam.mp4` keeps 16:9; then run the same
  steps and `compose.py config.py all --platform youtube` (or `bilibili`, `xiaohongshu:horizontal`).
- **Punch-in on an upscaled crop.** compose caps every zoom: `upscale x zoom <= STYLE max_upscale` (2.0), zoomed face
  width `<= STYLE max_face_frac` (0.62) of the canvas, and the zoomed face must stay below the progress bar. A webcam
  head that already fills the frame gets no punch-in. The hook title moves under the face (just above the captions)
  when its top spot would cover the eyes of any hook frame; callouts, PiP cards and pop words avoid the face box too.
- Retouch, strict pass, face track, covers: unchanged (they work on any body size).

## B-roll (plain 口播)
`BROLL = [dict(t0=S(3), t1=E(3), src="broll/demo.mp4", mode="cut"), ...]` in the config (see the example). The voice
continues; the inserted clip's own audio is not used. Modes:
- **cut**: full cut-away (video fills the canvas; a screenshot becomes a card on its own blurred fill).
- **pip**: rounded card with a white rim, placed on the corner / side that covers least of the face box; pops in.
- **split**: top/bottom on vertical canvases (`side="top"|"bottom"`), left/right on 16:9; the speaker half is cropped
  around the face.
Tall images (pages, chats, docs) become **screenshot cards**: they scroll top → bottom over the window, or follow the
`highlight=[(t, y0, y1)]` rows, each marker wiping in left → right at its time. `label="演示"` adds a small badge. With
`sfx` on, whooshes mark cut-away / split in and out. Zoom, stamps and pop words pause during cut / split; subtitles
and the progress bar stay on. Circle / card scenes win over B-roll in the same window.

## Iterating
Typical asks, each one re-run: swap hooks or their order; 加速; cut 废话 sentences; switch strategies in STYLE;
move a stamp off the face or the subtitle; change a panel's text or the cover copy. A V-track re-render takes
about 3 min; re-QC with `preview` stills before a full render.

## Gotchas
Read `references/gotchas.md` before debugging: runaway duration and xfade math, TCC, whisper tail
hallucination, **xfades swallowing the first syllable of every hook** (fixed with muted pads), HDR→SDR,
ffmpeg flag changes, frame-exact cutting, MLS warp streaks, landmark jitter, stamps on the chin or the subtitle.
