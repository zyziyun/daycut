---
title: FAQ
description: Answers about Reelfold's price and licence, Windows support, what leaves your Mac, which AI you need, languages, brand fonts, publishing and commercial use.
---

## Is Reelfold free?

Yes. Reelfold is open source under the MIT licence: the engine, the Claude Code skill, the Mac app and the website. You only pay your AI provider, if you use a paid API. With a local model or your own logged-in Claude Code or Codex CLI, there is no API bill. In an internal test, 96 files from one 72-minute lecture cost $0.73 in API calls.

## Is there a download for Mac? What about Windows?

The first macOS release (Apple Silicon) is coming soon on [GitHub Releases](https://github.com/zyziyun/reelfold/releases/latest). Until then, build it from source: see [Install the Mac app](/docs/start/install-mac/). Windows 10 / 11 (x64) is in preview: build it from source, see [Install on Windows](/docs/start/install-windows/). The engine uses faster-whisper and the `h264_mf` encoder there; most testing still happens on Macs, and there is no Windows release yet.

## Does it post for me?

No. Publishing is assisted: the app opens the platform's own upload page in its built-in browser, sets the video and types the title, text and tags. You check it and press publish yourself. The app never clicks publish and never posts on a schedule. See [Publishing](/docs/concepts/publishing/).

## What leaves my Mac?

Your video and audio stay on your Mac: transcription and rendering run locally. Only what an AI step needs goes to the AI provider you chose: text such as the transcript, captions and titles. With a local model, nothing leaves at all. Two exceptions you opt into: the OpenAI transcription backend sends audio, and OpenAI narration sends the script text. The app can also share anonymous usage counts, only if you turn it on ([what is sent](/docs/concepts/usage-counts/)). See [Privacy](/docs/concepts/privacy/).

## Which AI do I need?

Any of these, per task:

- Your own logged-in **Claude Code** or **Codex** CLI (no API key).
- An **API key**: Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini, ElevenLabs.
- A **local model**: Ollama, LM Studio, vLLM, llama.cpp, local whisper.

Without any AI, segment planning falls back to a rule-based planner. See [AI providers](/docs/concepts/ai-providers/).

## Do I need Claude Code?

Not for the Mac app; any provider above works. The skill form of Reelfold runs inside Claude Code, so that one does. The explainer recipe also needs an AI agent (Claude Code or Codex) to write its animated scenes.

## How is it different from Opus Clip, Descript or CapCut?

They are good tools with a different focus. Opus Clip is a hosted service for finding clips in long videos, Descript is a transcript-based editor, and CapCut is a timeline editor with templates. Reelfold is built for people who cut in batches:

- **Local-first.** Your footage is processed on your own Mac.
- **Batch, then review exceptions.** Many clips run in parallel, every file is checked automatically, and you look at what was flagged.
- **One recording, every platform.** Per-platform canvas, captions, loudness, cover and copy for 20 platforms.
- **Bring your own AI**, including none.
- **Open source** (MIT), so you can read, change and extend it.
- **Assisted publishing** that leaves the final click to you.

## Which languages does it support?

The app is in English, 简体中文 and Français. For content, Chinese and English are the most developed: filler detection, caption rules, bilingual subtitles and post copy in both. Whisper transcribes many other languages, but those paths are less tested.

## Can I use my own fonts and brand colours?

Yes. In `persona.local.yaml`, point any font role (`cjk`, `cjk-bold`, `serif`, `mono` …) at your own file, and set your brand colours, panel theme, default hashtags and title rules. Studios can keep a separate brand per client. See [Themes](/docs/concepts/themes/) and the [persona reference](/docs/reference/persona/).

## Can I use it for commercial work?

The MIT licence allows commercial use, including client work. Two things to check yourself: your AI provider's terms (subscription CLIs such as Claude Code and Codex are meant for your own use; use an API key or a local model where the terms call for it), and the licences of the fonts, music and footage you put in. The optional RVM matting engine for covers is GPL-3.0 and is downloaded only if you choose it.

## Do I have to label AI content?

Follow each platform's rules. Chinese platforms require a declaration for AI-generated content (rules in force since 1 September 2025), and YouTube, TikTok and Meta have their own AI labels. Reelfold never ticks these for you; the publishing checklist and client delivery notes remind you. The AI video workflow plans a label per platform. See the [publishing reference](/docs/reference/engine/publishing/).

## What happened to video-studio and Daycut?

Reelfold is the new name. The open-source skill and engine were published as **video-studio**, and the desktop app was called **Daycut** (日剪). The skill is still named `video-studio`, the Python package is still `vstudio`, and existing installs in `~/.claude/skills/video-studio` keep working. Only the repository moved, to [github.com/zyziyun/reelfold](https://github.com/zyziyun/reelfold).

## Related

- [What is Reelfold](/docs/start/what-is-reelfold/)
- [Troubleshooting](/docs/help/troubleshooting/)
- [Contributing](/docs/contributing/)
