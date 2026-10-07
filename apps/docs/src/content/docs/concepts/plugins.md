---
title: Plugins
description: Reelfold runs the batch; tools and agents plug in. Import HyperFrames boards and shot lists, render shots with any tool, hand shots to Claude Code, Codex or any command in parallel lanes.
---

Reelfold is the batch orchestrator for video work. It plans the series, keeps the storyboard, prices every shot, runs the work in parallel lanes, checks what comes back and puts it in front of you for review. The tools that make the pictures, and the agents that drive those tools, plug in.

## Three kinds of plugin

| Kind | What it does | Built in |
|---|---|---|
| Importer | Brings a board or project in as shots | HyperFrames projects, shot lists (JSON, CSV, Markdown), EDL, OpenTimelineIO, Premiere and Final Cut XML |
| Shot provider | Makes a shot | Kling, MiniMax Hailuo, Veo, Seedance, 即梦 (you press Generate), HyperFrames render |
| Agent runner | Hands one shot's job folder to an agent or a command | Claude Code, Codex, any command |

You see them all in **Settings › Video generation › Plugins**: on or off, version, what each one may do and what it costs.

## Import a board

On the Create page, click **Import board…** (or drop a file or folder on the box). Reelfold reads it and opens the new episode on its storyboard. On an episode's storyboard, **Import board…** replaces the shots (it asks first; takes you already made stay on disk).

A HyperFrames project brings in one shot per storyboard frame, with its length, scene, voiceover and notes. Frames whose composition exists are set to render with HyperFrames on your Mac.

## Make shots with plugins and agents

Set a shot to a plugin or an agent from its source menu (or a `source` column in your shot list), then press **Make**. Each shot gets its own job folder with a brief, the storyboard frame and the series rules. Several shots run at once, in lanes. A shot only counts when the job folder holds a playable video or an image; it then becomes a take. Failures and shots waiting for you show up in Making and the Inbox.

## Money

Nothing paid runs without the spend check (estimate, confirm, budget, monthly limit). Agents that use your own Claude Code or Codex plan, and tools that run on your Mac, cost nothing from Reelfold. A paid plugin can only run through the spend check.

## Add your own

Put a folder with a `plugin.yaml` in `~/.config/vstudio/plugins/`. New plugins start turned off. The full contract (manifest, board format, job-folder protocol, permissions, cost) is in the repository's `docs/PLUGINS.md`.
