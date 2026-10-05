---
name: video-studio
description: One video-editing skill for every kind of edit. Talking-head 口播 recuts (气口/filler/repeat removal, speed, captions, punch-ins, notes panels, progress bar, hooks, retouch); long recordings cut into courses or short episodes; call/interview clips with privacy masking; premium promo recuts with split screen, screenshot cards, highlight freeze-frames and inserted highlight reels; photo stories with effects; B-roll vlogs; 3Blue1Brown-style explainers; plus covers, music beds, loudness/export polish, pre-production scripts, and publish copy for 小红书/YouTube/B站. Use whenever the user hands over footage, screenshots or a topic and wants it edited, cut shorter, sped up, captioned, de-filler'd, given effects, music, a cover or post copy — or wants to tweak one stage of a video made this way.
---

# video-studio

One entry point, many workflows, one shared library (`lib/vstudio`) and one creator persona.
`$VSTUDIO` below = this folder. Run scripts from the **project folder** of the video being edited.

## 0. Setup (once per machine)
```bash
$VSTUDIO/install.sh                      # Python deps + open-licensed fonts (Noto Sans SC, STIX, JetBrains Mono) + MediaPipe models
cp $VSTUDIO/persona.example.yaml $VSTUDIO/persona.local.yaml   # your speeds, brand colours, tags, voice rules, term fixes
export PYTHONPATH="$VSTUDIO/lib:$PYTHONPATH"
```
HyperFrames-based workflows (explainer, promo-recut) also need Node 18+ and `npx hyperframes`.

## 1. Route the request

Identify the **main material** and the **deliverable**, then open that workflow's `WORKFLOW.md` and follow it.

| Material → deliverable | Workflow |
|---|---|
| Talking-head / 口播 recording(s) → tight short with captions, effects, cover (vertical or horizontal) | `workflows/talkinghead` |
| Talking head **plus** screenshots, links, another video to showcase → premium promo (split screen, 3D screenshot cards, highlight zoom/freeze, inserted highlight reel) | `workflows/promo-recut` |
| Long recording (lecture, webinar, livestream, screen-share, podcast) → cut course video and/or N short episodes | `workflows/longform-to-short` |
| Multi-person call / interview (Zoom, Meet, Teams) → clips, hide chosen participants' faces, vertical/landscape/trio layouts | `workflows/call-clips` |
| Photos / short clips + a narration script → effect-rich narrated story (museum, travel, history, product) | `workflows/photo-story` |
| Silent B-roll (drone, travel, nature, phone clips) → vlog with grade, speed, transitions, music | `workflows/vlog` |
| A topic / concept → 3Blue1Brown-style animated explainer with AI voice + bilingual subtitles | `workflows/explainer` |
| An already-exported edit → cover on first frame, loudness, speed-up, delivery tags | `workflows/polish` |
| Just a cover / thumbnail | `workflows/cover` |
| Square slides for a vertical video | `workflows/slides` |
| Writing the script before recording, pronunciation drills | `workflows/preproduction` |

Mixed jobs chain workflows (e.g. `preproduction` → record → `talkinghead` → `cover` → `polish`).
When the request is ambiguous, ask one question: what is the material, and where will it be posted.

## 2. Shared rules (all workflows)
- **The creator decides taste-critical choices**: hook lines, which sentences to cut, style preset, voice. Offer a short menu with a recommendation; don't silently choose.
- **Persona first**: speeds, loudness, brand colours, title rules, tags and voice rules come from `persona()` (`lib/vstudio/config.py`). Never hard-code a creator's taste.
- **Verify by looking and listening**: snapshot frames at the busiest moment of each section and mid-transition; ASR the cut to confirm no clipped syllables; check loudness of the final file.
- **Delivery defaults**: H.264 High, bt709 tags, AAC 192k/48k, `+faststart`, two-pass loudnorm to `persona.audio.loudness_lufs` (−14).
- **Public-safe**: fonts and models only through `vstudio.config.font()/model()`; no absolute personal paths in configs you commit.

## 3. Find a capability fast

| You want… | Go to |
|---|---|
| Cut 气口 / fillers / repeats / misspeaks | `cut.find_cuts` (auto), `cut.tighten` + `cut.suggest_fillers` (word-level), talkinghead `strict_pass.py`, promo-recut `tight_cut.py --suggest/--verify` |
| Long → short, multi-episode split | `workflows/longform-to-short` |
| Speed up (pitch-preserved), speed ramps per shot | persona `speed.*`; `media.atempo_chain`; vlog per-segment speed; HyperFrames `data-playback-rate` |
| Volume / loudness / music bed / ducking / SFX | `audio.loudnorm_2pass`, `audio.mix_bed`, `audio.loop_bed`, `audio.sfx_bank`; HyperFrames `carve.mjs` |
| Captions (bilingual, keyword highlight, SRT/ASS) | `asr.transcribe` → `subs` (wrap, retime, srt/ass); explainer `display_en` for spoken numbers → digits |
| Notes panels 记笔记, callouts, chips, badges, stamps, progress bar | `overlays.*` (PIL) or `overlays.hf_progress` / `hf.*` (HyperFrames) |
| Highlight frame / freeze + enlarge / zoom-in / punch-in | `hf.freeze_hold`, `hf.punch_in`, talkinghead compose zoom, photo-story loupe + red-pen circle |
| Split screen, screenshot cards with highlighter | `hf.split_screen`, `hf.screenshot_cards` (promo-recut) |
| Transitions | `hf.scene_transitions` (11 HyperFrames types), photo-story (12 per-frame types), `cut.xfade_assemble(transition=…)` |
| Retouch (slim, makeup), cover frame picking | `python -m vstudio.retouch`, `cover.score_frames`, `cover.prepare_photo` |
| Cover / thumbnail | `workflows/cover`, `cover.split_cover`, `cover.notes_cover`, `cover.framed_cover` |
| Post copy, title length, chapter timeline | `publish.check_title`, `publish.chapter_lines`, `publish.post_body` |
| Hide a face (privacy) | `workflows/call-clips` (`face.track_faces` + sticker) |

The full effect catalogue (≈155 effects, 9 recipes): `references/EFFECTS.md`.

## 4. Shared library (`lib/vstudio`)
| Module | What |
|---|---|
| `config` | `font(role)`, `model(name)`, `persona()`, `xhs_len(title)` |
| `media` | ffmpeg/ffprobe discovery, probe, frame grab, contact sheet, HDR→SDR, delivery encode + bt709 retag |
| `audio` | two-pass loudnorm, stems, RMS envelopes, silence spans, music beds (mix/loop/duck), pitch shift, SFX |
| `asr` | whisper (mlx → faster-whisper → OpenAI) with word timestamps, cache, term fixes, script alignment |
| `cut` | `TimeMap`, word-level tightening, automatic disfluency finder, frame-exact cuts, crossfade assembly |
| `subs` | cues, CJK-aware balanced wrap, highlight markup, SRT/ASS, retime, bilingual pairing |
| `tts` | OpenAI / Kokoro / Edge TTS with a content cache |
| `face`, `mls`, `retouch` | landmarks, face tracking, talk activity; own MLS warp; seam-free portrait retouch + makeup |
| `draw`, `overlays`, `cover` | PIL text/shape primitives, themed overlays and progress bars, cover compositors |
| `render`, `hf` | headless-Chrome HTML→PNG, font staging/subsetting; HyperFrames effect generators |
| `publish` | title checks, chapter lines, post bodies for 小红书 / YouTube / B站 |

Tests: `python3 -m pytest tests -q` (synthetic media, no network).
