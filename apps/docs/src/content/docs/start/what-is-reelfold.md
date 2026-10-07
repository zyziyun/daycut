---
title: What is Reelfold
description: Reelfold (千剪) is a free, open-source, local-first video tool that turns one recording into every cut for every platform. Learn how it works.
---

Reelfold (千剪) turns one recording into the set of clips you post this week. You describe what you want in plain language and drop in the footage. Reelfold plans the clips, edits them on your own Mac, checks every file and shows you only what needs a look. Each platform gets its own export, cover, title, caption and tags.

It is free, MIT licensed and open source. The code lives at [github.com/zyziyun/reelfold](https://github.com/zyziyun/reelfold).

## Two ways to use it

Both forms run the same engine, so a recipe that works in one works in the other.

| | Reelfold for Mac | The Claude Code skill |
|---|---|---|
| What it is | A desktop app (`apps/desk`, Electron) | The engine as a skill for [Claude Code](https://claude.com/claude-code) (the repo root) |
| How you talk to it | A request box on Home: "What are we making today?" | Plain language to Claude in your terminal |
| Good for | Batches on a board, a review grid, assisted publishing | Working inside a folder, scripting, one-off edits |
| Platform | macOS on Apple Silicon (Windows x64 in preview) | Anywhere Claude Code, Python 3.10+ and ffmpeg run |
| Install | [Install the Mac app](/docs/start/install-mac/) | [Install the skill](/docs/start/install-skill/) |

In the skill, `SKILL.md` routes each request to a workflow (`workflows/<name>/WORKFLOW.md`) with tested scripts and a shared Python library, `vstudio`.

## How a job flows

1. **Describe.** Say what you are making and add files: a talking-head clip, a 70-minute lecture, a folder of travel footage, a script. For example: "Cut this lecture into 10 vertical clips for TikTok and Shorts, under a minute each."
2. **Plan.** Reelfold reads the material and proposes a plan: which workflow, how many clips, which platforms, how long it will take and what it may cost. You change it in plain words ("only 3 clips", "no 9:16") before anything runs.
3. **Batch.** The edits run on your Mac, several at a time. A pilot clip comes first so you can check the look before the rest is made.
4. **Review.** Every file goes through automatic checks (missing words, frozen frames, loudness, length). You only see what was flagged, plus the decisions that are yours: which filler cuts to accept, which opening to use, which cover.
5. **Publish.** Publishing is assisted. The Mac app opens each platform's own upload page in its built-in browser and fills in the file and the copy. You press publish. Reelfold never posts on its own.

More on each step: [Projects](/docs/concepts/projects/), [Batch and review](/docs/concepts/batch-review/), [Publishing](/docs/concepts/publishing/).

## Who it is for

- **Batch creators** who record once and publish all week, in the shape, length and loudness each platform expects.
- **Podcasters and interviewers** who want many clips from one long conversation, with guests' faces masked when needed.
- **Teachers and course makers** who slice lectures and webinars into vertical clips or episodes.
- **Talking-head creators (口播)** who want pauses, filler words and repeats gone, with captions, notes panels and a cover.
- **Studios** running client batches side by side, each with its own style and glossary.

## What runs on your Mac

Transcription, cutting, effects, rendering and the quality checks all run locally. AI is bring-your-own: your logged-in Claude Code or Codex CLI (no API key needed), an API key (Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini, ElevenLabs), or a local model (Ollama, LM Studio, vLLM, llama.cpp, local whisper).

When an AI model is used, it receives text only (transcript, captions and titles), never your video or audio. In an internal test, one 72-minute lecture became 24 clips for 4 platforms (96 files) for $0.73 in AI API cost, about $0.03 per clip. See [AI providers](/docs/concepts/ai-providers/) and [Privacy](/docs/concepts/privacy/).

## Formerly video-studio and Daycut

Reelfold is the new name of this project. The skill and engine were published as **video-studio**, and the desktop app was called **Daycut** (日剪). Some names stay the same so existing setups keep working:

- the Claude Code skill is still called `video-studio` and installs to `~/.claude/skills/video-studio`
- the Python package is still `vstudio`
- only the repository URL moved, to `github.com/zyziyun/reelfold`

## Related

- [Install the Mac app](/docs/start/install-mac/)
- [Install the Claude Code skill](/docs/start/install-skill/)
- [Your first project](/docs/start/first-project/)
- [Example prompts](/docs/examples/)
