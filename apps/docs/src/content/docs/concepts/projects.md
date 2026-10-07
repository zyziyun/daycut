---
title: Projects
description: How Reelfold organizes work into projects of one or many items, what lives in a project folder, and how checkpoints, the Inbox and series fit together.
---

A project is one piece of work in Reelfold: one recipe applied to a set of items. A single talking-head video is a project with one item. Fifty slices of a lecture are a project with fifty items. Same structure, same tools, whatever the size.

## Why it matters

Because one video and a hundred videos are the same kind of thing, you never switch tools when the job grows. Every item in a project runs in parallel, shares the expensive work (one transcript per source, one glossary), resumes after a crash, and stops at the same decision points. You learn the flow once.

## How it works

The chain from top to bottom:

```
workspace (your persona or a client) → series → project (one recipe) → items → outputs (per platform)
```

- **Items** come from whatever you hand over: a folder of clips (one item per file), a list of topics, CSV rows, N episodes, or the segments planned from one long recording.
- **Params** stack from general to specific: recipe defaults, then series, then project, then item, then your answers at checkpoints.
- **Checkpoints** are the decisions that are yours: which filler cuts to accept, which hook, which segments, which cover, whether a clip is ready to publish. When a run reaches one, that item parks in a "needs you" state. It is not a failure; nothing else stops.
- **Outputs** land in `exports/<item>/<platform>-<orientation>`, with a cover and post copy next to each file and a manifest with a checksum per file.

### The project folder

| Path | What it holds |
|---|---|
| `project.yaml` | The editable truth: recipe, params, inputs, items, your answers |
| `items/<item>/` | Each item's workspace: authored files and the workflow's own `work/` and `out/` |
| `state/` | The run state (a batch database, caches, checkpoint payloads). Never edit it by hand |
| `exports/` | Finished files, covers, post copy, `manifest.json` |
| `AGENTS.md`, `CLAUDE.md` | A short brief so a Claude Code or Codex session opened in the folder knows the playbook and commands |

### Work folders and `.vstudio/`

Not every job starts as a recipe project. When the skill edits a plain folder (a `final/` video, a `REPORT.md`, a `post.md`), it still registers it. The only thing written is a `.vstudio/` subfolder: `status.json` holds the live status (running, waiting, done, failed, the current stage, progress, a heartbeat), and `work.json` records the folder as an adopted work folder. A running record whose heartbeat goes silent is shown as interrupted.

### Inbox and series

- The **Inbox** gathers every pending checkpoint across all projects. Similar questions are grouped, so you can accept the same kind of filler cut across twenty items at once. Budget and consent questions are never answered by default.
- A **series** is a preset for recurring work: a recipe, params, a posting cadence and an auto-answer policy. New projects in the series inherit all of it.

## In the Mac app

Home turns your request into one or more projects. All projects lists them with their live state, the Inbox shows what needs you, and each project opens to its items and outputs.

## With the Claude Code skill

The skill registers every job so the Mac app can show it without an import. At the start it runs `python -m vstudio.project new` when a recipe fits, otherwise `python -m vstudio.project touch <folder> --status running --stage plan`. It updates the stage and progress on long steps, marks `--status waiting --needs-you` when it has a question for you, and `--status done` at the end. An old folder made before this can be registered with `python -m vstudio.project adopt <folder>`.

## Related

- [Recipes](/docs/concepts/recipes/)
- [Batch and review](/docs/concepts/batch-review/)
- [Your first project](/docs/start/first-project/)
- [Projects engine reference](/docs/reference/engine/projects/)
