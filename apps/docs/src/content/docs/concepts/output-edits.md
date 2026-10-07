---
title: Output edits
description: Edit any finished Reelfold clip again with trims, word-snapped cuts, captions, title band, theme, effects, cover, speed, re-layout and plain-language AI edits.
---

The output edit layer lets you change a finished clip after it is rendered, without starting the project over. It works on any video Reelfold shows you: a recipe project's export, or a final video in a folder the skill made.

## Why it matters

Most fixes come after you watch the result: cut one sentence, fix a name in a caption, add a vertical version, make it a little faster. These edits are small and should be cheap. The edit layer keeps a history of steps you can undo, never overwrites the original file, and re-renders only what an edit touched.

## How it works

### Two modes

| Mode | When | What you can do with captions |
|---|---|---|
| Pipeline | Reelfold kept the clip's clean master (no burned captions) and its caption cues | Captions are fully editable: text, style, position, keyword colour, on or off. Other aspect ratios are a fresh face-tracked reframe of the master |
| Flattened | Only the finished file exists | Edits go on top of the file. Captions can only be added (over a mask that hides the burned ones, or in a band layout); burned text is never restyled |

The editor tells you which mode a clip is in and why a given option is off.

### What you can change

| Edit | Notes |
|---|---|
| Trim, cut | Edges snap to whole words once the clip is transcribed (cached after the first time) |
| Speed | 0.5× to 2.5×, pitch kept |
| Loudness | Defaults to the target platform's level |
| Captions | Edit text, style, add or remove cues. Edits to original cues must stay faithful to the audio |
| Title band | Add, change or remove |
| Theme | Restyle the whole look in one step (see [Themes](/docs/concepts/themes/)) |
| Effects | 20 effects: pop words, stamps, punch-in, quote and chapter cards, callouts, notes panel, stickers, badge, highlight box, progress bar, marker sweep, chapter rule, number counter, lower third, SFX, music bed, transitions, end fade, colour grade |
| Cover | Pick a frame and text |
| Re-layout | Add 3:4, 9:16 or 16:9 (or a platform) as a designed re-layout, never a plain letterbox |
| Reset | Back to the original, as an undoable step |

### Plain-language edits

Type what you want ("cut this part", "make the captions bigger", "add a progress bar"). Your chosen AI model proposes edit steps; each one is checked by the same validator as a manual edit, so invented effects or out-of-range values are dropped. Nothing changes until you confirm. You can point at a selection on the timeline, a caption or an effect, and "this" or "here" means that. With no model set up, a small set of literal phrases still works (speed, trimming the head or tail, platform exports, loudness, progress bar, fade).

A project-level request ("remove the series label from all clips") goes to every output at once. Text burned into a flattened file can't be removed by the editor; those clips are marked as needing a re-render, with the files to change.

### Undo, selective revert and chat

Every edit is one undo step. Selective revert cancels one earlier step and keeps everything after it; if a later step builds on it, you are told to undo back instead. Each clip keeps its own chat history (requests, proposals, provider, cost), so you can reopen it later and see what was done.

### Previews

Previews render fast at low bitrate; finals use the platform's delivery encode. Results are cached per stage, so a caption change only re-runs the last pass. You can also render a before and after comparison of edits you have not applied yet.

## In the Mac app

Open any finished clip from a project and edit it there, by hand or by typing in its chat.

## With the Claude Code skill

Ask Claude to change the finished video ("cut the second sentence and add a 16:9 version"). Underneath: `python -m vstudio.project output show / edit / render / undo / revert / ai / chat / effects`.

## Related

- [Themes](/docs/concepts/themes/)
- [Effects reference](/docs/reference/effects/)
- [Output edit engine reference](/docs/reference/engine/output-edit/)
- [AI providers](/docs/concepts/ai-providers/)
