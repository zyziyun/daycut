---
title: Troubleshooting
description: "Fixes for common Reelfold problems: ffmpeg not found, whisper downloads, missing fonts, AI login errors, slow batches, full disks and wrong caption names."
---

Each entry names the symptom, the likely cause and the fix. If you see a message code such as `llm-all-failed` or `qc.loudness`, look it up in [Messages and error codes](/docs/reference/messages/).

## Setup and engine

### ffmpeg not found

The engine looks for `ffmpeg` and `ffprobe` on your `PATH`, then falls back to the `static-ffmpeg` package.

- Install it: `brew install ffmpeg`.
- Or point at specific binaries: `VSTUDIO_FFMPEG=/path/to/ffmpeg` and `VSTUDIO_FFPROBE=/path/to/ffprobe`.

### The hardware H.264 encoder doesn't work

`VSTUDIO_H264_ENCODER` (or persona `export.h264_encoder`) chooses the encoder: `libx264` (default), `h264_videotoolbox` on macOS, `h264_mf` on Windows. The engine test-encodes the chosen one once. If it doesn't work on this machine, everything falls back to `libx264` on its own, and a failed hardware encode is re-run with libx264. Nothing to fix unless you want the hardware encoder; then check your ffmpeg build supports it.

### Whisper model download is slow, or you're offline

The first transcription downloads the model into the Hugging Face cache (`~/.cache/huggingface/hub`, or `$HF_HOME/hub`): `whisper-large-v3-turbo` for mlx-whisper on Apple Silicon, `large-v3-turbo` for faster-whisper elsewhere.

- Let the first download finish once on a good connection; later runs reuse it.
- To use a model you already have: `VSTUDIO_WHISPER_MLX=/path/to/whisper-large-v3-turbo-mlx` or `VSTUDIO_WHISPER_FW=/path/to/faster-whisper-large-v3-turbo` (a size name such as `small` also works).
- Add `HF_HUB_OFFLINE=1` so it never touches the network.

### "font '…' not found" warning

A font role (`cjk`, `cjk-bold`, `serif`, `mono` …) is missing from `~/.cache/video-studio/fonts`. Anything drawn with it uses a fallback face, which is why the warning is loud.

- Run `./install.sh` again; it downloads the open-licensed fonts.
- Or point the role at your own file in `persona.local.yaml` under `fonts:`. One face of a collection works as `path/to/Fonts.ttc#N`.

### "model '…' not found" (MediaPipe)

Face tracking, retouch, cover frame picking and matting use the MediaPipe face landmarker and segmenters. `./install.sh` downloads them into `~/.cache/video-studio/models`. Run it again if one is missing. Without a model, cover layouts fall back to a centred crop.

### The Mac app can't find the engine

If the app shows **Demo mode** instead of **Ready on this computer**, it couldn't import the engine and is running a stand-in.

1. Open Settings → **Engine**. It shows the engine folder, Python and data folder **In use**.
2. Set **Engine folder (Reelfold repo)** to the folder that contains `lib/vstudio`, and **Python** to an interpreter that has `requirements.txt` installed.
3. The same can come from the environment: `VSTUDIO_ENGINE_PATH` for the engine and `DESK_PYTHON` for Python. The app looks at Settings first, then those variables, then the repo it lives in.

### An old cache folder

Everything is cached under `$VSTUDIO_CACHE`, by default `~/.cache/video-studio`. Older builds wrote some of it to `~/.cache/vstudio`. That folder is still read but no longer written; delete it once you no longer need it.

## AI providers

### "Every AI provider failed" (`llm-all-failed`)

The routed provider and all its fallbacks failed. The message lists which ones were tried.

- Check what this Mac has: `python3 -m vstudio.llm auth status`, run from the repo's `lib` folder, or Settings → **AI accounts & models** in the app.
- Fix the first failing one (login, key, local server), or add a fallback: in the app, per task; in the persona, `fallback: [codex, ollama]` on the route.

A notice like `llm-fallback` ("Claude Code failed; Codex answered instead") is not an error. The work was done by the next provider in the chain.

### Claude Code login expired

The app checks Claude Code with a one-line round trip, because its own status can still say "logged in" after the token expired.

- In the app: Settings → AI accounts & models → **Log in again**. The login runs in a terminal inside the app.
- In a terminal: run `claude`, then `/login` (or `claude auth login`).

The engine never sees your password or token. Nothing is lost when a run stops on an expired login: sign in, run it again, and finished stages are not redone.

## Batches

### A batch is slow

- Run `estimate` before a large batch. After one pilot on an otherwise idle Mac, estimates use your machine's measured speed (`bench` prints the table).
- Transcription runs one at a time (whisper owns the GPU); rendering runs a few in parallel. Lower `--concurrency cpu-render=2` if your Mac is also busy with other work; raise it only if it isn't.
- `VSTUDIO_H264_ENCODER=h264_videotoolbox` uses the Mac's hardware encoder for every encode.
- Retouching long videos: the `fast` preset is about three times faster than `quality`.

### The disk is full

```bash
python3 -m vstudio.batch du --batch <batch>      # what uses the space
python3 -m vstudio.batch clean --batch <batch>   # delete regenerable intermediates
```

`clean` keeps JSON, covers, sheets and previews. For delivered client batches, `cleanup-sources` lists source files past their cleanup date (a dry run) and only deletes with the code it printed. Your own recordings outside the batch folder are never deleted.

## Captions and cuts

### Names or terms are spelled wrong in captions

Speech recognition writes names by sound.

- Proofreading with entity checks runs before captions are burned: place names are matched to their standard spelling, and your glossary terms are applied the same way everywhere. Run it, don't skip it.
- Add your own fixes to `persona.local.yaml`: `subtitles: {term_fixes: [["[Tt]runking", "chunking"]]}` (a regex and its replacement). Client batches use the client's glossary.
- Pass key terms to transcription up front (`asr: {prompt: "LangChain, RAG"}`).
- Fix a single caption in review. A change that adds or drops a spoken word is refused unless a re-hearing of that audio confirms it.

### Cleanup cut too much

1. `python -m vstudio.cleanup verify OUTPUT` re-transcribes the cut. A lost content word fails with its source and output time.
2. Keep the edit that covers it: reply `保留 7` (or `--keep 7`) and apply again.
3. If it keeps happening, use a gentler profile (`gentle` keeps more pause and breath), or add words to `cleanup.never_cut` in the persona.

In the app, filler cuts that might be real words wait for your yes in the Inbox; answer "keep" for the ones you want.

## Related

- [Messages and error codes](/docs/reference/messages/)
- [FAQ](/docs/help/faq/)
- [AI providers](/docs/concepts/ai-providers/) and [providers reference](/docs/reference/engine/providers/)
- [Cleanup reference](/docs/reference/engine/cleanup/)
- [Install the Mac app](/docs/start/install-mac/) and [install the skill](/docs/start/install-skill/)
