---
title: AI providers
description: Bring your own AI to Reelfold, from your Claude Code or Codex login, an API key, or a local model. Route each task, set fallbacks and see what each step costs.
---

Reelfold doesn't come with its own AI. It uses one you already have: your logged-in Claude Code or Codex CLI, an API key from a provider you choose, or a model running on your own machine. You can pick a different one for each task.

## Why it matters

You stay in control of cost, quality and where your text goes. A subscription you already pay for can do the planning at no extra cost. A local model keeps everything on your Mac. And when one provider is down or your login expires, a fallback can take over and you are told which one answered.

## Which steps use AI

| Step | What the AI does |
|---|---|
| Intake | Turns your request and files into a plan |
| Segment planning | Picks the segments of a long recording, with titles and hooks |
| Caption proofreading and glossary | Fixes names and terms the speech recognizer got wrong |
| Post copy and scripts | Writes titles, post text and scripts |
| Output edits | Turns a plain-language edit into edit steps |

Speech recognition and voice are separate: transcription runs locally by default (whisper on Apple Silicon), and narration can use a local voice, your cloned voice, or a hosted one. Every text step also works with no model at all, through a rule-based path.

## Three ways to connect

| Way | Providers | Notes |
|---|---|---|
| CLI login, no API key | Claude Code, Codex | Uses the plan you are logged into. Runs with no tools, in an empty temporary folder; nothing is written to your project |
| API key | Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini; ElevenLabs for voice | Keys are referenced by environment variable name, never written into config files |
| Local | Ollama, LM Studio, vLLM, llama.cpp; local whisper; your own whisper or TTS server | Nothing leaves your machine |

:::note[Subscription CLIs are for your own use]
Claude Code and Codex logins come with their own usage limits and terms. Before using one to produce paid client work at volume, check the provider's current terms, and use an API key or a local model where they call for it.
:::

## Routing and fallbacks

Each task (intake, segment planning, proofreading, glossary, copy, script, output edits) can have its own provider, with a default for the rest. Each route can list fallbacks in order: if the first fails, the next is tried. A provider you name explicitly for one run never falls back.

When a fallback runs you see a message rather than a silent switch:

- `llm-fallback`: "Claude Code failed (login expired); Codex answered instead." The job continued.
- `llm-all-failed`: every provider in the chain failed. The step stops and lists them. Where a rule-based path exists (segment planning, intake), it fills in and says so.

Failure reasons include an expired login, not logged in, not installed, a missing key, rate limiting and timeouts.

## Cost

API calls are costed per token and reported with each step. Subscription CLIs and local models count as zero. In an internal test, a 72-minute lecture became 24 clips for 4 platforms (96 files) for $0.73 in API cost, about $0.03 per clip.

## In the Mac app

Settings → AI accounts & models shows each provider's status (an expired Claude Code login shows as expired), lets you log in to a CLI in a built-in terminal, stores API keys in the macOS keychain, and sets the default, per-task choices and fallbacks.

## With the Claude Code skill

Put an `llm:` section in your `persona.local.yaml`, then check it from the `lib/` folder:

```bash
python3 -m vstudio.llm providers   # what works on this machine; nothing is sent
python3 -m vstudio.llm route       # which provider each task uses, and why
python3 -m vstudio.llm test --provider ollama --model llama3.2:1b   # one tiny round-trip
```

## Related

- [Privacy](/docs/concepts/privacy/)
- [Persona reference](/docs/reference/persona/)
- [Providers engine reference](/docs/reference/engine/providers/)
- [Engine messages](/docs/reference/messages/)
