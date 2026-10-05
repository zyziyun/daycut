# video-studio

One **Claude Code skill** for every kind of video edit: talking-head shorts, long recordings cut into episodes,
call/interview clips with privacy masking, premium promo recuts, photo stories with effects, B-roll vlogs and
3Blue1Brown-style explainers, plus covers, music, loudness, captions and publish copy for 小红书 / YouTube / B站.

You talk to Claude ("cut the 气口 and speed it up 1.3×", "add a split screen with this screenshot and highlight the
prompt", "make it 10 minutes, bilingual subtitles, 3b1b style"); the skill tells Claude which workflow to run and
gives it tested scripts and a shared library to do it.

![explainer storyboard](workflows/explainer/example/storyboard/f07.svg)

## What it covers

| Workflow | Turns… into… |
|---|---|
| `talkinghead` | 口播 recordings → tight short: 气口/filler/repeat removal (conservative, creator-confirmed, ASR-verified), speed, captions, punch-ins, pop words, stamps, 记笔记 panels, progress bar, hooks, B-roll (cut-away / PiP / split screen / scrolling screenshot cards), retouch, cover, post copy. Raw vertical phone clips, or raw horizontal webcam / camera footage reframed to 9:16 (face-tracked) or kept 16:9 with a landscape layout; legacy 剪映 horizontal exports with burned subtitles |
| `promo-recut` | talking head + screenshots/links/another video → premium promo: split screen, 3D screenshot cards with highlighter, freeze-and-enlarge, inserted highlight reel; 16:9 or platform-laid-out vertical |
| `longform-to-short` | lectures, webinars, livestreams, screen-shares → cut course video and/or N short episodes with chapters, code zooms, covers, 发布包; **vertical slices** (3:4 / 9:16, speaker band or title band, readable code crops) |
| `call-clips` | Zoom / Meet / Teams / interviews → clips in vertical, trio or landscape layouts, face masking (stickers) and name-label blur |
| `photo-story` | photos + narration script → effect-rich story (17 shot types, 11 overlays, 12 transitions, film looks), 3:4 / 9:16 / 16:9; **music-only mode** cut on bars; narration by OpenAI TTS or **your own cloned voice** (Qwen3-TTS, local) |
| `vlog` | B-roll (drone, travel, phone) → `calm` (graded, crossfaded, per-segment speed, music) or **`fun`** (cut to the beat, speed ramps inside shots, true slow-mo, whips/flash/leaks, text pops, map card, SFX cue sheet, ducked music, speech clips with captions) |
| `explainer` | a topic → 3Blue1Brown-style animated explainer with AI narration and bilingual subtitles; 16:9 long form or **vertical short** (9:16 / 3:4) |
| `polish` | any exported edit → cover on first frame, −14 LUFS (or the platform's target), speed-up, delivery tags; one or many platforms |
| `cover`, `slides`, `preproduction` | covers/thumbnails per platform size, square or full-canvas slides, script writing + lint per platform + pronunciation drills |

Shared across workflows:

- **Platform profiles + multi-platform export**: one clean master → per-platform files with captions placed for each
  app's UI, loudness, covers and a manifest (`python -m vstudio.export`; see Platforms below).
- **Reframe**: face-tracked virtual camera (One Euro smoothing, dead zone, eased pans) between any aspect ratios.
- **Beats / 卡点 and SFX**: beat grid + downbeats + sections (`vstudio.beats`), SFX cue sheets snapped to cuts and
  beats (`audio.cue_sheet_for`), synthesized SFX bank; see [`references/SOUND.md`](references/SOUND.md).
- **Effects registry**: 87 effects (190 counting named variants) in one declarative catalogue
  (`lib/vstudio/effects.py` → generated [`references/EFFECTS.md`](references/EFFECTS.md)); 24 transitions that work in
  HyperFrames, ffmpeg and per-frame PIL (`vstudio.xfade`). Add your own: [`references/ADDING_EFFECTS.md`](references/ADDING_EFFECTS.md).
- **Retouch v2**: MLS reshape, three-band skin smoothing, glasses-aware masks, makeup presets (`natural`, `daily`
  rosy-pink lip, `glam`); temporally stable on video with subtle makeup on by default and a `fast` preset for long
  videos ([`references/RETOUCH.md`](references/RETOUCH.md)).

What was tested on real footage, and the known limits: [`references/VALIDATION.md`](references/VALIDATION.md).

## Install

```bash
git clone https://github.com/zyziyun/video-studio ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

`install.sh` installs the Python dependencies and downloads open-licensed fonts (Noto Sans SC, STIX Two Text,
JetBrains Mono — OFL) and the MediaPipe models (Apache-2.0: face landmarker, selfie segmenter and the selfie
**multiclass** segmenter used by retouch for face-skin / hair / accessory masks) into `~/.cache/video-studio`.

Requirements: Python 3.10+, `ffmpeg`. Optional: Node 18+ with `npx hyperframes` (explainer, promo-recut),
Chrome/Chromium or Playwright (HTML covers/slides), an `OPENAI_API_KEY` (AI narration), the HeyGen CLI (music catalog).
Transcription uses `mlx-whisper` on Apple Silicon and `faster-whisper` elsewhere. Optional: `librosa` (better beat
tracking), `pillow-heif` (HEIC photos; macOS falls back to `sips`), `mlx-audio` + a Qwen3-TTS model (voice clone).

## Platforms

Profiles for **小红书** (`xiaohongshu:vertical` 3:4, `:full` 9:16, `:horizontal` 16:9), **抖音** (`douyin`),
**TikTok** (`tiktok`), **YouTube** (`youtube` 16:9), **YouTube Shorts** (`youtube-shorts`) and **B站** (`bilibili`,
`bilibili:vertical`): canvas, UI safe zones and button keep-outs, caption box and size, loudness (LUFS / true peak),
encode caps, length sweet spots, cover sizes and feed crops, title / description / tag limits. Every workflow takes
`--platform` (or `PLATFORM` in its config); `python -m vstudio.platform` prints them and
[`references/PLATFORMS.md`](references/PLATFORMS.md) says which values are sourced and which are conventions.
Override anything per creator in `persona.local.yaml`.

## Make it yours: `persona.local.yaml`

Everything that is taste rather than technique lives in one file: default speeds, loudness targets, brand colours and
panel theme, platform title rules, default hashtags, script/caption voice rules, ASR term fixes, your own fonts.
`persona.local.yaml` is git-ignored, so your settings never end up in the repo.

## Layout

```
SKILL.md                  router: which workflow for which request + capability index
workflows/<name>/         WORKFLOW.md playbook, scripts/, references/, examples/ (synthetic)
lib/vstudio/              shared library (media, audio, asr, cut, subs, tts, face, filters, mls, retouch,
                          draw, overlays, cover, render, hf, xfade, effects, beats, platform, reframe,
                          export, publish)
references/               EFFECTS.md (generated catalogue), ADDING_EFFECTS, PLATFORMS, RETOUCH, SOUND,
                          AESTHETICS, VALIDATION (real-media test record)
tests/                    pytest on synthetic media (python3 -m pytest tests -q)
```

## Credits and licences

- Code: MIT (see `LICENSE`).
- Fonts and models are downloaded at install time from their upstream projects under their own licences
  (SIL OFL 1.1; Apache-2.0) and are not redistributed here.
- The optional RVM matting engine in `workflows/cover` is GPL-3.0 and is fetched at runtime only if you choose it.
- Built with [HyperFrames](https://hyperframes.heygen.com) for the HTML-to-video workflows.
