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
- Landscape clips (webcam, camera) are reframed to 1080x1920 with `vstudio.reframe` face mode (tracked, smoothed
  virtual camera; pad-blur when no face); `ORIENT=horizontal` keeps them 16:9 for a horizontal render
  (`compose.py --platform youtube`). `prep.json` records the reframe mode, face hit rate and upscale factor.
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

## 3. First cut + speech cleanup analysis (`vstudio.cleanup`, references/CLEANUP.md)
```bash
python3 $V/cut_pass1.py edit_list.py      # PROFILE / CLEANUP / REPLY overridable in edit_list.py
python3 $V/cut_pass1.py edit_list.py --analyze-only    # only cleanup.cN.json + cleanup_review.md, no cut
```
- Range edges: `cleanup.snap_range` (start before the first word's onset, end over the last word's real tail,
  neither into a neighbour word of `aN.json`).
- `cleanup.analyze` on each RAW clip over those ranges → `cleanup.cN.json` (EDL, ids unique across clips) and
  `cleanup_review.md` for the creator. Only the 气口 edits (pause / breath / lead / tail; squeezed per profile,
  never deleted) are applied in pass 1; word edits wait for the creator (step 5).
- Cuts with `vstudio.cut.cut_segments` (via `bodycut.cut_sources`): frame-grid snap, a 2 s accurate pre-seek
  then `trim=start_frame/end_frame`, audio sliced sample-exact on the same grid with 12ms fades.
- `segs.pass1.json` records every body segment's raw span (clip, t0, t1) and body span (b0, b1) plus the raw words
  on the body timeline (`body_words`): later passes map the cleanup keep spans through it.

Per-segment `ffmpeg -ss -t` drifted 0.57s over 163 cuts, so don't go back to it.

## 4. Retouch, the slow step: about 40 min for 6.4k frames with 5 workers (`--preset fast`: ~3x less)
```bash
python3 $V/retouch_video.py body_v.mp4 x --test 300,2500,4800    # side-by-side stills, check first
python3 $V/retouch_video.py body_v.mp4 body_rt.mp4 --workers 5
```
- `vstudio.retouch.retouch()` per frame on EMA-smoothed landmarks, so the face doesn't jitter between frames.
- Video defaults: `slim 0.042`, `eye 0.04` (minimal: glasses lenses warp), `shine 0.7`, `smooth 0.55`
  (bilateral, 45% fine texture added back), `light 0.04`, `makeup 0.3` `natural` (on by default; landmark-anchored
  masks keep it flicker-free; `--makeup 0` turns it off).
- **Long videos:** `--preset fast` (half-res skin/makeup delta, full-res warp, ~0.21 vs ~0.64 s/frame/worker); see
  `references/RETOUCH.md` → Video speed presets.
- Override per creator in persona `retouch.video.<knob>`, or per run with `--slim 0.05` etc.
- The warp is blended back through a feathered face-region mask; without it the ROI edge streaks.

**Never redo this for later cuts.** Steps 5 and 6 cut `body_rt.mp4` directly.

## 5. 去 filler / 重复 / 口误: the creator's reply, applied to the retouched body
```bash
python3 $V/strict_pass.py review          # = old `transcribe`: prints cleanup_review.md, writes strict_draft.py (REPLY = "")
# creator answers: cp strict_draft.py strict.py; REPLY = "确认 3,5,9 / 保留 7"; TEXT = {sid: "fixed|subtitle"}
python3 $V/strict_pass.py apply strict.py body_rt.mp4 body_a.wav body2_rt.mp4 body2_a.wav
python3 $V/strict_pass.py verify strict.py body2_a.wav "$PROMPT"  # cleanup.verify: lost content words (exit 1)
```
- **What is cut**: every 自动删 AUTO row (hesitations 嗯 呃 um uh, stutters, clear repeats) unless 保留 N, plus the
  待确认 CONFIRM rows the creator names with 确认 N (semantic fillers 就是 这个 然后 when isolated, restarts — the
  abandoned half of 「你要作为X你要干Y」 —, re-takes, merged fillers, ASR noise). 保留 KEEP rows look like real words.
  `REPLY = ""` = AUTO only. Extra editor cuts: `CUT = [(clip, raw t0, raw t1)]`. A legacy `DEL` set of `bw.json`
  indices is still cut.
- **Never confirm every row unheard.** A real test that applied every suggestion deleted real words and the
  subtitles drifted from the audio.
- The body ranges = the cleanup keep spans (raw clip seconds) intersected with the pass-1 segments, mapped to body
  seconds; word edits have word-safe edges (the silence between the neighbours, never inside a kept word).
- **Verify**: `verify` = `cleanup.verify` on `body2_a.wav` via its sidecar `body2_a.cleanup.json` (also
  `python -m vstudio.cleanup verify body2_a.wav`): a fresh ASR vs the words that should remain, fillers ignored,
  single-character ASR noise ignored; missing spans come with the applied edit ids near them (保留 N, re-apply).
- **Pauses**: squeezed in pass 1 per profile (`standard`: pauses ≥ 0.45 s → 0.18-0.40 s, 0.30 s after a sentence).
  Keeping one of those (保留 N) is refused here: put `REPLY = "保留 N"` in `edit_list.py` and re-run pass 1.
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

**Pass files (re-runs are safe).** `cut_pass1` writes `segs.pass1.json` (immutable root); `strict_pass apply`
always derives `segs.strict.json` from it; `drop_pass` derives `segs.drop.json` from `segs.strict.json` (or pass 1
when no strict pass ran). `segs.json` is a copy of the newest stage. Each pass checks that the body wav it is given
has its parent's length and refuses otherwise, so: change REPLY and re-apply strict on `body_rt.mp4 body_a.wav`
(the drop is then marked stale: re-run it); change the drop list and re-run drop on the strict body with the FULL
list. Never feed `body3_*` back into a pass.

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
python3 $V/cover.py config.py                       # OUT, for the config's platform
python3 $V/cover.py config.py --platform douyin     # -> <OUT stem>.douyin-vertical.jpg (OUT untouched)
```

## 10. QC
- Duration, and loudness (persona `audio.loudness_lufs`, -14 LUFS).
- `preview` stills of: a hook, the handoff, each scene type, the stamp stack, and the progress bar
  cropped at full resolution.
- Hook audio: check with ASR at normal speed, `atempo=1/HOOK_SPEED`. ASR on a 1-2s sped-up clip
  hallucinates, so don't trust it there. Use an RMS envelope instead to confirm a syllable starts at full level.
