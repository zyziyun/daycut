---
name: video-studio
description: One video-editing skill for every kind of edit, for 小红书 / 抖音 / 视频号 / TikTok / YouTube / Shorts / B站 / X / Instagram. Talking-head 口播 (去气口, 去 filler/重复/口误, 加速, 字幕, 记笔记面板, 气泡, 进度条, 高光预告/快剪 hooks, 精剪风, 修图/美颜, 封面, 发布文案); long recordings → 切片/分集/剪成课程 (去浏览器头/书签栏, 学员变声, 竖屏切片); calls/interviews/podcasts → clips + 遮脸/打码/放个小猫; promo recuts with 左右分栏/split screen, 截图卡片高亮, 定格放大, 精选插片; 文艺片/photo stories with effects; travel vlogs (calm or 卡点快节奏, 调色, 转场, 配乐); 3Blue1Brown-style explainers; AI-generated skits; covers/thumbnails, slides, scripts, pronunciation drills; one master → many platforms. Use whenever the user hands over footage, photos, screenshots or a topic and wants it edited, cut shorter, captioned, given effects, music, a cover or post copy, or wants to tweak one stage of such a video.
---

# video-studio

Part of [Reelfold](https://github.com/zyziyun/reelfold) (千剪): the open-source engine behind the Reelfold desktop app
(`apps/desk`); works on its own in Claude Code. One entry point, many workflows, one library (`lib/vstudio`), one
creator persona. `$VSTUDIO` = this folder. Run scripts from the **project folder** of the video being edited.

Setup once: `$VSTUDIO/install.sh` (deps, open fonts, MediaPipe models), `cp persona.example.yaml persona.local.yaml`
(her speeds, theme, tags, term fixes, format overrides), `export PYTHONPATH="$VSTUDIO/lib:$PYTHONPATH"`.
HyperFrames workflows (explainer, promo-recut) also need Node 18+ and `npx hyperframes`.

## 1. Every job, in this order
1. **Format first.** `python -m vstudio.formats detect "<her request>"` (or pick from `formats list`). Say its summary
   line to her before any render, e.g. "按「口播」默认：正文 1.25x，hook 给 12 条候选你挑，严格去 filler，封面与正片同尺寸、修图，
   不加系列角标". Her words for this job override it; persona `formats.<id>` holds her lasting overrides. Ask at most one
   question, and only when the material or the platform is unclear.
2. **Register** so the desktop app shows it: `python -m vstudio.project new` when a recipe fits, else
   `python -m vstudio.project touch <folder> --status running --stage plan`; `--stage <s> --progress 0.4` at long steps,
   `--status waiting --needs-you` at a question, `--status done` at the end (details: references/PROJECTS.md).
3. **Open the workflow's `WORKFLOW.md`** (table below) and follow it.
4. **First-pass check before she sees anything:** `python -m vstudio.firstpass final.mp4 --format <id> --source <raw>
   --cues <cues.json> --cover <cover> --post <post.md>`. Fix every 必须修 item, then look at 3-4 frames (busiest moment,
   a transition, the cover). Never hand over with a red item.
5. **Hand over**: the file paths (finals in one place, intermediates under `work/`), the summary line of what was applied
   (speed, cleanup, hooks, cover), the firstpass result, and any choice left to her as a numbered menu.

## 2. Route: material → deliverable

| Material → deliverable | Workflow |
|---|---|
| 口播 / talking-head clip(s) → captioned short (phone vertical, webcam / camera landscape, 剪映 export) | `workflows/talkinghead` |
| 口播 **plus** screenshots, links, a demo or a finished video of her work → premium promo (split screen, 3D screenshot cards, freeze-zoom, 精选 inserts) | `workflows/promo-recut` |
| Lecture, webinar, livestream, screen-share → course video or N slices | `workflows/longform-to-short` |
| Call / interview / **podcast** (Zoom, Meet) → clips, guest faces hidden — even when she says 切片 | `workflows/call-clips` |
| A **lesson** (teacher / tutor / coach; screen share and / or camera) → one clip per teaching point (今日短语 / 知识点), recap, study notes, 中英字幕 | `workflows/lesson-clips` |
| Interview / podcast / coaching → **Q&A clips** (一问一答: opens on the question, answer cut tight, role labels) | `workflows/interview-qa` |
| Her own voice-over + clips / photos → vlog (`calm` or `fun` 卡点) | `workflows/vlog` |
| Photos / clips + narration or music → 文艺片 / photo story | `workflows/photo-story` |
| A topic → 3b1b-style explainer (AI voice, bilingual captions) | `workflows/explainer` |
| Script / idea → AI-generated video (可灵, Seedance / 即梦, 海螺), AI series | `workflows/ai-video` |
| An exported edit (Descript / CapCut / 剪映) → cover on frame 1, loudness, speed, cleanup | `workflows/polish` |
| Cover / thumbnail only · square slides · script or pronunciation drill | `workflows/cover` · `workflows/slides` · `workflows/preproduction` |
| 10s-100s of videos at once (one long recording → N slices, a folder of 口播) | `workflows/batch` (references/BATCH.md) |
| A **finished** clip to tweak (trim, captions, theme, effects, cover, speed, re-layout, plain-language edits, undo) | `python -m vstudio.project output ...` (references/OUTPUT_EDIT.md) |
| A sentence + a mixed pile of files → a plan of recipes | `python -m vstudio.intake` (references/INTAKE.md) |
| 气口 / filler / 重复 / 口误 in any recording with her speech | `python -m vstudio.cleanup` (references/CLEANUP.md), inside every workflow |

Mixed jobs chain workflows (preproduction → record → talkinghead → cover → polish). Phrase table, capability index and
library modules: [references/CAPABILITIES.md](references/CAPABILITIES.md). Full topic → post SOP: references/SOP_SHORT_VIDEO.md.

## 3. Rules learned from her corrections (all workflows)
- **Speed is always applied and always said.** Use the format's speeds; hooks above 1.6x and Chinese speech above ~1.4x
  sound fake. firstpass fails a render that is not shorter than its sources / speed.
- **Hooks: never auto-picked.** Formats with `hooks: menu` show ~12 numbered candidates (text, type, length at hook
  speed) and she picks the set and order; promo / explainer / vlog get no hook montage unless she asks.
- **She decides taste-critical choices** (hooks, which sentences go, style preset, voice): a short menu with a
  recommendation, never a silent choice. Lines naming colleagues, a boss, a company or her self-introduction are listed
  for her before they are cut or kept.
- **Framing**: keep the source framing; no big-face crop (a 1.7x upscale was 太丑). A finished master with burned
  captions goes into a band layout (picture band + new captions), not a face crop. Keep people fully in frame.
- **Look = one design theme** (`vstudio.theme`, references/STYLE_RULES.md), `editorial` by default; never hard-code
  colours; no saturated red text; notes = light paper card; quotes = typography; subtle stamps / pops.
- **No series labels** (01/04, PART n, 第n集, 系列名 + 编号) unless she says it is a series.
- **Bilingual captions** (中英): `vstudio.bilingual` (source line + smaller translated line in the theme's secondary
  ink, or translation only); persona `subtitles.glossary` is enforced; a failed translation stops the job (never a
  silent mono). Per-language SRT / VTT go with every export.
- **Captions**: after ASR always run proofread with entity verification (宏都拉斯 → 洪都拉斯) before burning captions or
  writing cards / copy, and put every new mis-hearing into persona `subtitles.term_fixes` (references/CAPTION_RULES.md).
- **Cleanup**: strict on fillers, stutters and restarts (persona `cleanup.profile`); deliberate doubling (起起落落,
  泛泛) and rhetorical repeats stay; every cut is re-transcribed (`cleanup verify`).
- **Cover**: same canvas as the video, bright, her full face (retouched: slimmer, light makeup), designed type, no
  clutter labels, burned into frame 1 when the platform shows frame 1. Look at it before handing over.
- **Voice**: her own recording over TTS; her cloned voice next; a stock TTS voice only when she says so.
- **Persona first**: speeds, loudness, theme, tags (`publish.tag_sets` per format: no career tags on an art post),
  voice rules come from `persona()`; never hard-code her taste in a script.
- **Delivery**: H.264 High, bt709, AAC 192k / 48k, `+faststart`, two-pass loudnorm to −14 LUFS (platform profile),
  resolution never below the source or the platform canvas.
- **Public-safe**: fonts / models only via `vstudio.config.font()/model()`; no personal paths or media in the repo.

Tests: `python3 -m pytest tests -q`. Repo check: `python3 scripts/check_skill.py`.
