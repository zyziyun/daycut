---
title: Privacy
description: Reelfold is local-first. Your media, transcription and rendering stay on your Mac; only short pieces of text go to the AI provider you choose, or nothing.
---

Reelfold runs on your Mac. Your footage is read, transcribed, cut and rendered locally. The only things that leave are the pieces of text a step needs from an AI model (a transcript, captions, titles), and they go only to the provider you picked. With a local model, nothing leaves at all.

## Why it matters

Your recordings hold faces, voices, names, client material and things said off the cuff. Uploading hours of raw footage to a cloud editor is a real cost, especially for client work. Keeping the heavy work local also means no upload wait and no per-minute render fees.

## What stays on your Mac

- **Your media.** Source files are read in place, never copied off the machine. Intake only reads them; nothing is written next to your files.
- **Transcription.** Whisper runs locally by default (on Apple Silicon). A hosted transcription API is used only if you choose it.
- **Rendering.** Cuts, captions, effects, covers and exports are all made on your machine.
- **Keys.** In the Mac app, API keys go into the macOS keychain; the interface only shows whether a key is set. In the skill, configs name an environment variable instead of holding the key, and a client config refuses key or token fields.
- **Your persona.** `persona.local.yaml` (your speeds, colours, tags, term fixes, AI routes) is git-ignored, so it doesn't end up in a commit.

The Mac app's engine listens on no network port: the app reaches it over a Unix domain socket in the app's own folder, with a per-launch token (on Windows: `127.0.0.1`, a random port and the same token).

## What is sent, and to whom

Only to the provider you route each task to:

| Step | Sent | Not sent |
|---|---|---|
| Intake | Your request, a summary of the materials (file names, durations, short excerpts, document headings); a transcript when you ask to pick content from a recording | Audio, video, full documents |
| Segment planning | The transcript with timestamps | Audio, video, file paths |
| Caption proofreading and glossary | Caption text and transcript text, your term list | Audio, video |
| Output edits | Your instruction, the clip's captions or transcript, its edit state | Audio, video |
| Hosted transcription (only if chosen) | The audio track | Video |
| Hosted voice (only if chosen) | The narration text | Anything else |

A local model, local whisper or your cloned voice sends nothing. Transcripts can contain names and private details of the people recorded; for client work, prefer a local model or a provider whose data terms your client accepts.

## Analytics and updates

The Mac app has one optional, opt-in feature that sends anonymous usage counts (such as "a batch of 12 clips finished"). It is off unless you turn it on; every field it sends, and how to delete it, is listed in [Privacy: what Reelfold sends](/docs/concepts/usage-counts/). The engine and the Claude Code skill send no usage data. Installed builds do check the public GitHub releases for updates (every few hours) and download fonts and models on first run. Setting `DESK_DISABLE_UPDATES=1` turns the update check off.

## Guests and other people in the frame

For calls, interviews and podcasts, you choose whose face to hide. A face-tracking sticker covers each chosen guest, with a coverage check that the face never shows, and the call app's name labels are blurred by default. The call-clips recipe also stops at a consent checkpoint, confirming the people shown agreed, which is never answered automatically.

Reelfold never deletes your own recordings. Source cleanup for client batches is off by default, lists exact files first, and needs a confirm code.

## Open source, so you can check

Reelfold is MIT-licensed. Everything on this page can be verified in the code: [the repository](https://github.com/zyziyun/reelfold), especially `lib/vstudio/llm` and [the providers reference](https://github.com/zyziyun/reelfold/blob/main/references/PROVIDERS.md), which lists what each step sends.

## Related

- [Privacy: what Reelfold sends](/docs/concepts/usage-counts/)
- [AI providers](/docs/concepts/ai-providers/)
- [Publishing](/docs/concepts/publishing/)
- [Podcast and call clips](/docs/guides/podcast-clips/)
- [Providers engine reference](/docs/reference/engine/providers/)
