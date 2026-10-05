---
name: video-studio
description: One video-editing skill for every kind of edit, for 小红书 / 抖音 / TikTok / YouTube / Shorts / B站. Talking-head 口播 (去气口, 去 filler/重复/口误, 加速, 字幕, 记笔记面板, 气泡, 进度条, 高光预告/快剪 hooks, 精剪风, 修图/美颜, 封面, 发布文案); long recordings → 切片/分集/剪成课程 (去浏览器头/书签栏, 学员变声, 竖屏切片); calls/interviews → 截取一段 + 遮脸/打码/放个小猫; promo recuts with 左右分栏/split screen, 截图卡片高亮, 定格放大, 精选插片; 文艺片/photo stories with effects; travel vlogs (calm or 卡点快节奏, 调色, 转场, 配乐); 3Blue1Brown-style explainers; covers/thumbnails, slides, scripts, pronunciation drills; one master → many platforms. Use whenever the user hands over footage, photos, screenshots or a topic and wants it edited, cut shorter, captioned, given effects, music, a cover or post copy, or wants to tweak one stage of such a video.
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

### What the creator typically says → workflow
| Phrases (中文 / English) | Workflow |
|---|---|
| 口播, 复盘, 合并剪辑, 二次剪辑, 去气口, 去 filler word, 去重复, 去口误, 精剪, 加速, 加 hooks, 高光预告, 快剪, 加进度条, 加气泡, 加面板, 记笔记, 修图, 美颜, 瘦脸, 换剪辑风格, 发小红书 | `talkinghead` |
| 宣传一下, 讲我做的东西, 左右分栏, 分屏, 截图放进去, 高亮这句, 把 prompt 放大, 定格, 插一段精选, 精选 | `promo-recut` |
| 剪成课程, 上课实录, 教学长视频, 切片, 分几集, 去掉浏览器头/书签栏, 加章节/字幕/zoom/笔记面板, 学员变声, 变声, 去头像, 竖屏切片 | `longform-to-short` |
| 截取一段对话, 发一段出来, 播客剪辑, 把朋友的脸遮一下, 打码, 放个小猫, 三人同框 | `call-clips` |
| 文艺片, 看展, 照片做成视频, 配旁白, 胶片感, 双语字幕故事 | `photo-story` |
| 剪成一个 vlog, 旅游 vlog, 卡点, 快节奏, 去掉不好的部分, 加效果转场, 调色, 配乐, 无人机/DJI 素材 | `vlog` (`style: calm` or `fun`) |
| 讲解视频, 3b1b, 解释一个概念, 原理讲解 | `explainer` (16:9 long or vertical short) |
| Descript/CapCut/剪映 导出后收尾, 第一帧黑, 响度, 加速 1.2× | `polish` |
| 做封面, 缩略图, thumbnail | `cover` |
| 幻灯片, slides | `slides` |
| 写稿, 口播稿, script, 发音练习, 跟读, shadowing | `preproduction` |
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
