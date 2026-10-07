---
title: Install the Claude Code skill
description: Install the video-studio skill for Claude Code in three commands, see what install.sh downloads, set up Whisper offline, update and verify it.
---

The Claude Code skill is the Reelfold engine packaged for [Claude Code](https://claude.com/claude-code). Once it is installed, you talk to Claude about your footage ("cut the pauses and speed it up 1.1×") and the skill tells Claude which workflow to run, with tested scripts and a shared library behind it. The skill is still called `video-studio`.

## Requirements

**Required**

- Claude Code
- Python 3.10+
- `ffmpeg` (`brew install ffmpeg` or `apt install ffmpeg`)

**Optional, per workflow**

| You want | Install |
|---|---|
| Explainers and promo recuts (HyperFrames) | Node 18+ with `npx hyperframes` |
| HTML covers and slides | Chrome / Chromium, or Playwright |
| AI narration (OpenAI TTS) | `OPENAI_API_KEY` |
| Music catalog | The HeyGen CLI |
| Better beat tracking | `librosa` |
| HEIC photos | `pillow-heif` (macOS falls back to `sips`) |
| Your own cloned voice | `mlx-audio` and a Qwen3-TTS model |

## Install

Run these three lines:

```bash
git clone https://github.com/zyziyun/reelfold ~/.claude/skills/video-studio
~/.claude/skills/video-studio/install.sh
cp ~/.claude/skills/video-studio/persona.example.yaml ~/.claude/skills/video-studio/persona.local.yaml
```

1. The clone puts the skill where Claude Code looks for skills.
2. `install.sh` installs the Python dependencies and downloads fonts and models (see below). It is safe to run again; files that already exist are skipped.
3. `persona.local.yaml` holds your taste: default speeds, loudness, brand colours, title rules, hashtags, term fixes, fonts and which AI does each task. It is git-ignored, so your settings never end up in the repo. All options: [persona.yaml options](/docs/reference/persona/).

Start a new Claude Code session afterwards so it picks up the skill.

## What install.sh downloads

Everything goes into one cache folder, `~/.cache/video-studio` (set `VSTUDIO_CACHE` to move it):

| What | Where | Licence |
|---|---|---|
| Noto Sans SC, Noto Serif SC, STIX Two Text, JetBrains Mono | `fonts/` | SIL OFL 1.1 |
| MediaPipe face landmarker, selfie segmenter, selfie multiclass segmenter (used by retouch) | `models/` | Apache-2.0 |
| Python packages from `requirements.txt`, plus `mlx-whisper` on Apple Silicon or `faster-whisper` elsewhere | your Python environment | various |

At the end it warns you if `ffmpeg` or `npx` is missing. Set `SKIP_PIP=1` to skip the Python packages and only fetch fonts and models.

The same cache also holds transcripts, TTS takes and other reusable results. The Mac app uses this folder too, so nothing is downloaded twice.

## Whisper models and offline use

The first transcription downloads a Whisper model into the Hugging Face cache (`~/.cache/huggingface/hub`, or `$HF_HOME/hub`):

- `mlx-community/whisper-large-v3-turbo` for mlx-whisper (Apple Silicon)
- `large-v3-turbo` (`Systran/faster-whisper-large-v3-turbo`) for faster-whisper

To use a model you already have, or to work on an offline machine, point the engine at it:

```bash
export VSTUDIO_WHISPER_MLX=/path/to/whisper-large-v3-turbo-mlx    # MLX folder (config.json + weights) or an HF repo id
export VSTUDIO_WHISPER_FW=/path/to/faster-whisper-large-v3-turbo  # CTranslate2 folder, or a size name such as small
export HF_HUB_OFFLINE=1                                           # never touch the network
```

The transcription backend is chosen automatically: mlx-whisper, else faster-whisper, else OpenAI `whisper-1` when `OPENAI_API_KEY` is set.

## Choose your AI

Every AI step (planning segments, proofreading captions, the glossary, post copy) can run on your own logged-in Claude Code or Codex CLI with no API key, on an API key, or on a local model. Set it in `persona.local.yaml`:

```yaml
llm:
  default: {provider: claude-code}
```

Routing per task, fallbacks and costs: [AI providers](/docs/concepts/ai-providers/).

## Verify the install

See which AI providers, transcription and TTS engines this machine has (nothing is sent):

```bash
cd ~/.claude/skills/video-studio/lib && python3 -m vstudio.llm providers
```

Optionally run the test suite on synthetic media (needs `pytest`; no network):

```bash
cd ~/.claude/skills/video-studio && python3 -m pytest tests -q
```

## Moving from the old repository URL

If you cloned the skill when it was published as video-studio, point it at the new repository. The folder name, the skill name and the `vstudio` package stay the same:

```bash
git -C ~/.claude/skills/video-studio remote set-url origin https://github.com/zyziyun/reelfold
```

Older builds wrote part of the cache to `~/.cache/vstudio`. It is still read but no longer written; delete it once you no longer need it.

## Update

```bash
git -C ~/.claude/skills/video-studio pull
~/.claude/skills/video-studio/install.sh
```

Re-running `install.sh` picks up new Python dependencies and any new fonts or models. Your `persona.local.yaml` is not touched.

## Related

- [Your first project](/docs/start/first-project/)
- [Example prompts](/docs/examples/)
- [CLI reference](/docs/reference/cli/)
- [Install the Mac app](/docs/start/install-mac/)
