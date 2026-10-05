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
| `talkinghead` | 口播 recordings → tight short: 气口/filler/repeat removal, speed, captions, punch-ins, pop words, stamps, 记笔记 panels, progress bar, hooks, retouch, cover, post copy |
| `promo-recut` | talking head + screenshots/links/another video → premium promo: split screen, 3D screenshot cards with highlighter, freeze-and-enlarge, inserted highlight reel |
| `longform-to-short` | lectures, webinars, livestreams, screen-shares → cut course video and/or N short episodes with chapters, code zooms, covers, 发布包 |
| `call-clips` | Zoom / Meet / Teams / interviews → clips in vertical, trio or landscape layouts, optional face masking |
| `photo-story` | photos + narration script → effect-rich story (17 shot types, 11 overlays, 12 transitions, film looks) |
| `vlog` | silent B-roll (drone, travel, phone) → graded, speed-ramped, crossfaded vlog with music |
| `explainer` | a topic → 3Blue1Brown-style animated explainer with AI narration and bilingual subtitles |
| `polish` | any exported edit → cover on first frame, −14 LUFS, speed-up, delivery tags |
| `cover`, `slides`, `preproduction` | covers/thumbnails, square slides, script writing + pronunciation drills |

About 155 reusable effects are catalogued in [`references/EFFECTS.md`](references/EFFECTS.md).

## Install

```bash
git clone https://github.com/zyziyun/video-studio ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

`install.sh` installs the Python dependencies and downloads open-licensed fonts (Noto Sans SC, STIX Two Text,
JetBrains Mono — OFL) and MediaPipe face/segmentation models (Apache-2.0) into `~/.cache/video-studio`.

Requirements: Python 3.10+, `ffmpeg`. Optional: Node 18+ with `npx hyperframes` (explainer, promo-recut),
Chrome/Chromium or Playwright (HTML covers/slides), an `OPENAI_API_KEY` (AI narration), the HeyGen CLI (music catalog).
Transcription uses `mlx-whisper` on Apple Silicon and `faster-whisper` elsewhere.

## Make it yours: `persona.local.yaml`

Everything that is taste rather than technique lives in one file: default speeds, loudness targets, brand colours and
panel theme, platform title rules, default hashtags, script/caption voice rules, ASR term fixes, your own fonts.
`persona.local.yaml` is git-ignored, so your settings never end up in the repo.

## Layout

```
SKILL.md                  router: which workflow for which request + capability index
workflows/<name>/         WORKFLOW.md playbook, scripts/, references/, examples/ (synthetic)
lib/vstudio/              shared library (media, audio, asr, cut, subs, tts, face, retouch, draw,
                          overlays, cover, render, hf, publish)
references/EFFECTS.md     effect catalogue + recipes
tests/                    pytest on synthetic media (python3 -m pytest tests -q)
```

## Credits and licences

- Code: MIT (see `LICENSE`).
- Fonts and models are downloaded at install time from their upstream projects under their own licences
  (SIL OFL 1.1; Apache-2.0) and are not redistributed here.
- The optional RVM matting engine in `workflows/cover` is GPL-3.0 and is fetched at runtime only if you choose it.
- Built with [HyperFrames](https://hyperframes.heygen.com) for the HTML-to-video workflows.
