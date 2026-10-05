---
name: video-studio
description: One video-editing skill for every kind of edit, for 小红书 / 抖音 / TikTok / YouTube / Shorts / B站. Talking-head 口播 (去气口, 去 filler/重复/口误, 加速, 字幕, 记笔记面板, 气泡, 进度条, 高光预告/快剪 hooks, 精剪风, 修图/美颜, 封面, 发布文案); long recordings → 切片/分集/剪成课程 (去浏览器头/书签栏, 学员变声, 竖屏切片); calls/interviews → 截取一段 + 遮脸/打码/放个小猫; promo recuts with 左右分栏/split screen, 截图卡片高亮, 定格放大, 精选插片; 文艺片/photo stories with effects; travel vlogs (calm or 卡点快节奏, 调色, 转场, 配乐); 3Blue1Brown-style explainers; covers/thumbnails, slides, scripts, pronunciation drills; one master → many platforms. Use whenever the user hands over footage, photos, screenshots or a topic and wants it edited, cut shorter, captioned, given effects, music, a cover or post copy, or wants to tweak one stage of such a video.
---

# video-studio

One entry point, many workflows, one shared library (`lib/vstudio`) and one creator persona.
`$VSTUDIO` below = this folder. Run scripts from the **project folder** of the video being edited.

## 0. Setup (once per machine)
```bash
$VSTUDIO/install.sh                      # Python deps + open-licensed fonts (Noto Sans/Serif SC, STIX, JetBrains Mono) + MediaPipe models (landmarker, selfie + multiclass segmenter)
cp $VSTUDIO/persona.example.yaml $VSTUDIO/persona.local.yaml   # your speeds, brand colours, tags, voice rules, term fixes
export PYTHONPATH="$VSTUDIO/lib:$PYTHONPATH"
```
HyperFrames-based workflows (explainer, promo-recut) also need Node 18+ and `npx hyperframes`.

## 1. Route the request

Identify the **main material** and the **deliverable**, then open that workflow's `WORKFLOW.md` and follow it.

| Material → deliverable | Workflow |
|---|---|
| Talking-head / 口播 recording(s) → tight short with captions, effects, B-roll, cover. Raw vertical phone clips; raw horizontal webcam/camera footage (face-tracked reframe to 9:16, or kept 16:9 with the landscape layout); legacy 剪映 horizontal exports | `workflows/talkinghead` |
| Talking head **plus** screenshots, links, another video to showcase → premium promo (split screen, 3D screenshot cards, highlight zoom/freeze, inserted highlight reel) | `workflows/promo-recut` |
| Long recording (lecture, webinar, livestream, screen-share, podcast) → cut course video and/or N short episodes (16:9 or vertical slices) | `workflows/longform-to-short` |
| Multi-person call / interview (Zoom, Meet, Teams) → clips, hide chosen participants' faces, vertical/landscape/trio layouts | `workflows/call-clips` |
| Photos / short clips + a narration script (TTS or your cloned voice), or just music → effect-rich story (museum, travel, history, product) | `workflows/photo-story` |
| B-roll (drone, travel, nature, phone clips) → vlog: `calm` (grade, per-segment speed, crossfades, music) or `fun` (卡点, speed ramps, whips, pops, SFX) | `workflows/vlog` |
| A topic / concept → 3Blue1Brown-style animated explainer with AI voice + bilingual subtitles (16:9 long or vertical short) | `workflows/explainer` |
| An already-exported edit → cover on first frame, loudness, speed-up, delivery tags | `workflows/polish` |
| Just a cover / thumbnail | `workflows/cover` |
| Square slides for a vertical video | `workflows/slides` |
| Writing the script before recording, pronunciation drills | `workflows/preproduction` |
| Script / idea → AI-generated video (可灵 Kling, Seedance/即梦, MiniMax/海螺): shot list, prompts, credit plan, take review, assembly; AI series → 投稿 packages + per-post confirmed upload | `workflows/ai-video` |
| A topic → published short, end to end (script → drill → slides → record → clean up → edit → cover → export → post) | `references/SOP_SHORT_VIDEO.md` |

### What the creator typically says → workflow
| Phrases (中文 / English) | Workflow |
|---|---|
| 口播, 复盘, 合并剪辑, 二次剪辑, 精剪, 加速, 加 hooks, 高光预告, 快剪, 加进度条, 加气泡, 加面板, 记笔记, 修图, 美颜, 瘦脸, 换剪辑风格, 发小红书 | `talkinghead` |
| 去气口, 去 filler word, 去嗯啊, 去重复, 去口误, 剪掉停顿, 说一半重来 (any recording with original speech, in any workflow) | `cleanup`: `python -m vstudio.cleanup` → `references/CLEANUP.md` |
| 宣传一下, 讲我做的东西, 左右分栏, 分屏, 截图放进去, 高亮这句, 把 prompt 放大, 定格, 插一段精选, 精选 | `promo-recut` |
| 剪成课程, 上课实录, 教学长视频, 切片, 分几集, 去掉浏览器头/书签栏, 加章节/字幕/zoom/笔记面板, 学员变声, 变声, 去头像, 竖屏切片 | `longform-to-short` |
| 截取一段对话, 发一段出来, 播客剪辑, 把朋友的脸遮一下, 打码, 放个小猫, 三人同框 | `call-clips` |
| 文艺片, 看展, 照片做成视频, 配旁白, 胶片感, 双语字幕故事 | `photo-story` |
| 剪成一个 vlog, 旅游 vlog, 卡点, 快节奏, 去掉不好的部分, 加效果转场, 调色, 配乐, 无人机/DJI 素材 | `vlog` (`style: calm` or `fun`) |
| 讲解视频, 3b1b, 解释一个概念, 原理讲解 | `explainer` (16:9 long or vertical short) |
| Descript/CapCut/剪映 导出后收尾, 第一帧黑, 响度, 加速 1.2×, 导出后再去气口 | `polish` (`--cleanup pauses\|gentle\|standard\|tight`, default off) |
| 做封面, 缩略图, thumbnail | `cover` |
| 幻灯片, slides | `slides` |
| 写稿, 口播稿, script, 发音练习, 跟读, shadowing | `preproduction` |
| AI生成视频, 可灵, 即梦, Seedance, 海螺, 分镜prompt, 定妆照, 积分, 投稿, 多平台发布, 连载, 系列 | `ai-video` |
| 从选题到发布, 完整流程, SOP, end to end | `references/SOP_SHORT_VIDEO.md` |
| 一个视频发多个平台, 抖音/Shorts/B站版本 | any workflow → `python -m vstudio.export` |

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
| Cut 气口 / fillers / repeats / misspeaks | ONE shared tool for every workflow with original speech (talkinghead, promo-recut, longform-to-short, call-clips, vlog speech clips, photo-story clips with speech, polish `--cleanup`): `python -m vstudio.cleanup analyze clip.mp4 [--ranges 12.5-80] [--profile gentle\|standard\|tight]` → `cleanup_review.md` → creator replies "确认 3,5,9 / 保留 7" → `apply cleanup.json --reply "确认 3,5,9 / 保留 7"` → `verify <out>` (re-ASR, lost words exit 1). In memory: `cleanup.detect/clean/keep_segments`, captions via `timemap` + `remap_words`. `references/CLEANUP.md`. **Only auto edits are cut until the creator approves more.** |
| Long → short, multi-episode split, vertical slices | `workflows/longform-to-short` (`--platform xiaohongshu:vertical` or `douyin`; speaker or title band) |
| Speed up (pitch-preserved), per-segment speed, speed ramps | persona `speed.*`; `media.atempo_chain`; vlog calm = per-segment `speed`, vlog fun = ramps inside a shot + true slow-mo; HyperFrames `data-playback-rate` |
| Beats / 卡点, cut to music | `vstudio.beats` (`analyze`, `snap`, downbeats, sections, `verify`); vlog `style: fun`; photo-story `MODE = "music"` |
| Volume / loudness / music bed / ducking | `audio.loudnorm_2pass`, `audio.mix_bed`, `audio.loop_bed`; HyperFrames `carve.mjs` |
| SFX cue sheets (whoosh / pop / hit on cuts and reveals) | `audio.cue_sheet_for`, `audio.sfx_bank`, `audio.place_sfx`; `references/SOUND.md` |
| Captions (bilingual, keyword highlight, SRT/ASS) | `asr.transcribe` → `subs` (wrap, retime, srt/ass); explainer `display_en` for spoken numbers → digits |
| Notes panels 记笔记, callouts, chips, badges, stamps, progress bar | `overlays.*` (PIL) or `overlays.hf_progress` / `hf.*` (HyperFrames) |
| Highlight frame / freeze + enlarge / zoom-in / punch-in | `hf.freeze_hold`, `hf.punch_in`, talkinghead compose zoom, photo-story loupe + red-pen circle |
| Split screen, screenshot cards with highlighter | `hf.split_screen`, `hf.screenshot_cards` (promo-recut) |
| B-roll in 口播 (cut-away, PiP, split screen, scrolling screenshot cards) | talkinghead `BROLL` in the config (`scripts/vertical/broll.py`; captions avoid the face in splits) |
| Transitions | `vstudio.xfade` (24 names in HyperFrames, ffmpeg and per-frame PIL), `hf.scene_transitions`, `cut.xfade_assemble(transition=…)` |
| Effects registry, add an effect | `python -m vstudio.effects --list / --show <id>`, `effects.find(...)`; `references/ADDING_EFFECTS.md` |
| Reframe 16:9 ↔ 9:16 ↔ 3:4 (face-tracked) | `python -m vstudio.reframe in.mp4 out.mp4 --size 1080x1920`, `reframe.plan/render` |
| Platform export (one master → 小红书 / 抖音 / TikTok / YouTube / Shorts / B站) | `python -m vstudio.export master.clean.mp4 --platforms xiaohongshu:vertical,douyin,youtube --cues cues.json --out exports/`; profiles: `vstudio.platform`, `references/PLATFORMS.md` |
| Retouch (slim, skin, makeup; video `--preset fast` for long bodies), cover frame picking | `python -m vstudio.retouch`, talkinghead `retouch_video.py`, `references/RETOUCH.md`, `cover.score_frames`, `cover.prepare_photo` |
| Voice clone (your own voice for narration) | `tts.synth(engine="clone", ref_wav=…, ref_text=…)` (Qwen3-TTS via mlx-audio, local); photo-story `VOICE = dict(engine="clone")`; persona `tts.clone.*` |
| Vertical explainer (3b1b short) | `workflows/explainer` "Vertical short" (`--platform xiaohongshu:full`, portrait design truth) |
| Music-only photo story | `workflows/photo-story` `MODE = "music"` (cuts on bars, chapter cards on music sections) |
| Cover / thumbnail | `workflows/cover`, `cover.split_cover`, `cover.notes_cover`, `cover.framed_cover` (sizes per platform) |
| Post copy, title length, chapter timeline | `publish.check_title`, `publish.chapter_lines`, `publish.post_body`, `platform.check_text` |
| Hide a face / name label (privacy) | `workflows/call-clips` (`face.track_faces` + sticker, `name_mask`) |
| What was validated on real footage | `references/VALIDATION.md` |

The effect catalogue (87 effects, 190 counting named variants, generated from `lib/vstudio/effects.py`; 9 recipes): `references/EFFECTS.md`. Add an effect: `references/ADDING_EFFECTS.md`. Transitions shared across engines: `vstudio.xfade` (24 names in HyperFrames, ffmpeg and per-frame PIL).

## 4. Shared library (`lib/vstudio`)
| Module | What |
|---|---|
| `config` | `font(role)` (incl. `cjk-serif`, persona `path.ttc#N` faces; loud warning when missing), `model(name)`, `persona()`, `xhs_len(title)` |
| `media` | ffmpeg/ffprobe discovery, probe, frame grab, contact sheet, HDR→SDR, delivery encode + bt709 retag |
| `audio` | two-pass loudnorm (post-encode true-peak check, wav headroom, `ensure_loudness`), stems, RMS envelopes, silence spans, music beds (mix/loop/duck), pitch shift, SFX bank + cue sheets |
| `asr` | whisper (mlx → faster-whisper → OpenAI) with word timestamps, cache, term fixes, script alignment; `drop_hallucinations` (on by default) + `has_speech(tr)` for music-only clips |
| `cut` | `TimeMap`, word-level tightening, automatic disfluency finder, frame-exact cuts, crossfade assembly |
| `cleanup` | the shared 气口 / filler / repeat / restart / retake tool: `analyze` → EDL + review sheet, `apply` (word-safe, frame-exact, versioned, never re-cuts a cut file), `verify` (re-ASR); profiles gentle / standard / tight, persona `cleanup:`; `python -m vstudio.cleanup` |
| `subs` | cues, CJK-aware balanced wrap, highlight markup, SRT/ASS, retime, bilingual pairing |
| `tts` | OpenAI / Kokoro / Edge TTS and local voice clone (Qwen3-TTS) with a content cache |
| `face`, `filters`, `mls`, `retouch` | landmarks, `VideoFaceTracker`, talk activity; One Euro smoothing; own MLS warp; portrait retouch v2 + makeup |
| `draw`, `overlays`, `cover` | PIL text/shape primitives, themed overlays and progress bars, cover compositors |
| `render`, `hf` | headless-Chrome HTML→PNG, font staging/subsetting; HyperFrames effect generators |
| `xfade` | one transition name → HyperFrames GSAP, ffmpeg `xfade` or per-frame blend (24 names) |
| `effects` | effect registry (87 entries, 190 with variants) → generated `references/EFFECTS.md`; `--list`, `--show`, `find()` |
| `beats` | beat grid, tempo check, downbeats, energy, sections, `snap`, `cut_plan`, `verify` |
| `platform` | profiles: canvas, safe box, caption box, keep-outs, loudness, encode, length, cover, text limits |
| `reframe` | face-tracked / centre / pad-blur / letterbox reframe between aspects (`python -m vstudio.reframe`) |
| `export` | one clean master → per-platform files, captions (cues.json `keepouts`, 【kw】/`hl` colour, `--no-captions`), covers (`--cover platform=path`), manifest (`python -m vstudio.export`) |
| `publish` | title checks, chapter lines, post bodies for 小红书 / YouTube / B站; `use_persona_tags=False` / `tag_set=` (persona `publish.tag_sets`) |

Tests: `python3 -m pytest tests -q` (synthetic media, no network).
Pre-publish repo check: `python3 scripts/check_skill.py` (frontmatter, decorative emoji, personal paths).
