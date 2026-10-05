# V track: raw vertical phone clips → 小红书 post

Scripts are in `$VSTUDIO/workflows/talkinghead/scripts/vertical/`; `$V` below means that folder.
Run everything from the WORK dir (e.g. `my-video/work`). Face steps need `./install.sh` to have fetched
the MediaPipe face landmarker (`vstudio.config.model("face_landmarker")`).

## 1. Prep
```bash
PROMPT="以下是普通话口播，提到 TermA、TermB、Product-X" \
  bash $V/prep_sources.sh . ../clip1.MOV ../clip2.MOV ../clip3.MOV
```
- iPhone clips are HLG 10-bit HEVC with rotation -90, and some are 120fps.
  - macOS: `avconvert -p Preset1920x1080` tone-maps them to SDR 1080x1920 H.264.
  - elsewhere: ffmpeg `zscale`+`tonemap=hable` (or `libplacebo`). Force with `TONEMAP=ffmpeg`.
  - Later steps resample to 30fps.
- Clips are numbered 1..N in the order given.
- Whisper (`vstudio.asr`: mlx_whisper, else faster_whisper, else OpenAI; cached in `<wav>.asr.json`; CLI
  `scripts/asr.py`) still mishears English terms in Chinese
  speech. Re-transcribe doubtful spans with a term prompt (`python3 ../asr.py clip.wav out.json --prompt ...`)
  and add recurring fixes to persona `subtitles.term_fixes`.

## 2. Keep list → `edit_list.py`
One entry per spoken sentence. The list index becomes its **sid** for the rest of the pipeline:
```python
E = [
  (1, [(10.20, 13.18)], "第一句"),
  (1, [(14.28, 15.66), (15.96, 17.02)], "第二句"),        # 2 ranges = the words between them are cut out
  (2, [(16.16, 17.52), (20.30, 23.62)], "第三句|换行在这里"),
]
```
- Drop the intro small talk ("今天拿手机录个视频"), restarts, tangents, and 就是 / 然后 / 反正 at sentence edges.
- The subtitle text must match the audio word for word. `|` marks line breaks, at about 14 characters max.
- Whisper word *starts* swallow the preceding pause. Word *ends* are reliable.
- Full example: `examples/v_edit_list_example.py`.

## 3. First cut
```bash
python3 $V/cut_pass1.py edit_list.py      # TH -45 dB, MAXGAP 0.20, KEEPGAP 0.10, overridable in edit_list.py
```
- Snaps each range to voiced audio and squeezes internal pauses.
- Cuts with `vstudio.cut.cut_segments` (via `bodycut.cut_sources`): frame-grid snap, a 2 s accurate pre-seek
  then `trim=start_frame/end_frame`, audio sliced sample-exact on the same grid with 12ms fades.

Per-segment `ffmpeg -ss -t` drifted 0.57s over 163 cuts, so don't go back to it.

## 4. Retouch, the slow step: about 40 min for 6.4k frames with 5 workers
```bash
python3 $V/retouch_video.py body_v.mp4 x --test 300,2500,4800    # side-by-side stills, check first
python3 $V/retouch_video.py body_v.mp4 body_rt.mp4 --workers 5
```
- `vstudio.retouch.retouch()` per frame on EMA-smoothed landmarks, so the face doesn't jitter between frames.
- Video defaults: `slim 0.042`, `eye 0.04` (minimal: glasses lenses warp), `shine 0.7`, `smooth 0.55`
  (bilateral, 45% fine texture added back), `light 0.04`, `makeup 0` (flickers on video).
- Override per creator in persona `retouch.video.<knob>`, or per run with `--slim 0.05` etc.
- The warp is blended back through a feathered face-region mask; without it the ROI edge streaks.

**Never redo this for later cuts.** Steps 5 and 6 cut `body_rt.mp4` directly.

## 5. Strict filler pass
```bash
python3 $V/strict_pass.py transcribe body_a.wav "$PROMPT"     # prints idx:word[t] for the whole body
# write strict.py: DEL = {13, 18, 25, ...}; TEXT = {sid: "fixed|subtitle"} for every changed sentence
python3 $V/strict_pass.py apply strict.py body_rt.mp4 body_a.wav body2_rt.mp4 body2_a.wav
```
- **What goes in DEL**:
  - fillers: 就是, 这个, 然后, 像, 其实, 反正, 嘛, 的话
  - stray leftover syllables from pass 1
  - first halves of self-repeats: in 「你要作为X你要干Y」 drop the first 你要; in 「大家都众所周知」 drop 大家都
- **Pauses**: squeezed to persona `audio.pause_squeeze` (0.06s) with MAXGAP 0.12.
- **Effect**: about 10% shorter (212s → 191s in the reference video).
- The apply step prints `kept words || subtitle` per sid. Read every line and fix the TEXT entries.
- The kept words (with new times) go into `segs.json`; compose.py ends each `|` / CJK-space subtitle chunk where
  its last word ends (`vstudio.asr.align_script`), so a chunk change lands on the speech, not on a character-count
  guess (that guess is still the fallback when a body has no words, i.e. before strict_pass).
- Example: `examples/v_strict_example.py`.

## 6. Cut padding sentences (废话), optional
Propose the list first, then run:
```bash
python3 $V/drop_pass.py "1,7,11,17" body2_rt.mp4 body2_a.wav body3_rt.mp4 body3_a.wav
```
The reference video went from 191s to 157s.

## 7. Face track on the final body
```bash
python3 $V/face_track.py body3_rt.mp4 face3.npy
```

## 8. Config + render
Copy `examples/v_config_example.py` to `config.py` and set BODY/AUDIO/FACE/OUT, KEYWORDS, STYLE,
HOOK_TITLE, HOOKS, CHAPTERS, EMPH and the effect lists, using sid anchors.
```bash
python3 $V/compose.py config.py base                    # hook montage + body + grade -> base.mov
python3 $V/compose.py config.py preview 2,30,60,90,115  # stills -> preview.jpg, check layout first
python3 $V/compose.py config.py comp                    # SFX mix + overlays + final encode (about 3 min)
```
`timeline.json` gets `BODY_START` and `BODY_SPEED`. A chapter that starts at body time `b` is at
`BODY_START + b / BODY_SPEED` in the final video; `scripts/caption.py config.py` prints that list.

## 9. Cover
```bash
python3 $V/pick_cover_frame.py body3_rt.mp4      # ranked times + cover_candidates.jpg
# set COVER = dict(SRC=..., T=..., OUT=..., TITLE=[...], STICKY=..., TAG=...) in config.py
python3 $V/cover.py config.py
```

## 10. QC
- Duration, and loudness (persona `audio.loudness_lufs`, -14 LUFS).
- `preview` stills of: a hook, the handoff, each scene type, the stamp stack, and the progress bar
  cropped at full resolution.
- Hook audio: check with ASR at normal speed, `atempo=1/HOOK_SPEED`. ASR on a 1-2s sped-up clip
  hallucinates, so don't trust it there. Use an RMS envelope instead to confirm a syllable starts at full level.
