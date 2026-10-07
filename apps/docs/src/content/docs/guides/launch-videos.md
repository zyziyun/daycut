---
title: Launch videos for your product
description: Turn a release of your app or site into a demo video, a README GIF, one clip per feature, Product Hunt stills, post copy in English and Chinese, and a posting schedule.
---

You get everything a launch or an update post needs, made from the real product: a 30–60 second demo in 16:9, 9:16 and 1:1 (kinetic captions, the camera punching in on each click, a logo end card, a soft music bed), a 15-second looping GIF for your README, a 10–20 second clip per feature for X, LinkedIn, Shorts, TikTok and 小红书, Product Hunt gallery stills and an OG image, post copy for every platform in English and 中文, and a schedule proposal. Nothing is posted for you.

## Before you start

- **The product**: its name, a one-liner and the site.
- **What changed**: a CHANGELOG section, a git range (Conventional Commits such as `feat:` and `fix:` become features; chores and CI don't), or release notes pasted as bullets.
- **Something to record**: a URL of your web app or an Electron app, with sample data that is safe to show (no real names, emails, handles or other people's faces). Screenshots or screen recordings you already have work too.
- **The brand**: logo, icon, one accent colour, and optionally your fonts (any OFL font file).

## In the Mac app

1. On Home, pick the idea **Make a launch video for my app**, or describe it ("Make a launch kit for v1.4 from this changelog"), and drop the changelog and your logo.
2. **Product, brand and features.** Pick 3–6 features from the drafted list, write one on-screen line for each, and mark the word to highlight with 【】. You also write the shot list: what to click and type for each feature.
3. The project records the product, renders every video, makes the stills, writes the post copy and proposes a schedule. Each video passes the first-pass check before you see it.
4. **Review and publish.** Read `COPY.md`, watch the videos, and post them yourself.

## With the Claude Code skill

Hand Claude the changelog and say what you're launching. The skill follows `workflows/launch-kit`, with everything in one `launch.config.yaml`:

```bash
LK="python3 $VSTUDIO/workflows/launch-kit/scripts/launch_kit.py"
$LK features launch.config.yaml     # draft the feature list from the release
$LK capture launch.config.yaml      # record the product with Playwright
$LK all launch.config.yaml          # render, stills, copy, schedule, first-pass check
```

The capture runs your product at 2× scale with a smooth cursor and writes, for every shot, where and when each click happened. The camera uses that to punch in on the action and pull back between actions.

## What's in the kit

| Folder | What |
|---|---|
| `demo/` | The demo in 16:9, 9:16 and 1:1 (and a Chinese-captioned 16:9 and 9:16 if you add `zh`), each with a cover |
| `readme/` | A seamless 15 s loop as MP4 and GIF |
| `clips/` | One clip per feature: 1:1 for X and LinkedIn, 9:16 for Shorts, TikTok, Reels and 小红书 |
| `stills/` | Product Hunt gallery (1270×760) with a hero still, and a 1200×630 OG image |
| `copy/` | `COPY.md` with the Product Hunt fields, the launch post and every clip post, per platform, English and 中文 |
| `schedule/` | Launch day: the demo everywhere. Then one feature clip per weekday |

## Options worth knowing

| Option | Default | What it does |
|---|---|---|
| `languages` | `[en]` | Add `zh` for Chinese-captioned versions and Chinese copy. |
| `demo.max_seconds` | 60 | Scenes are squeezed to fit, never under 4 s each. |
| `brand.theme` | editorial | The theme the brand colours sit on: paper, ink and one accent. |
| `music` | auto | A built-in bed from the shared music library (generated, free to use). A mood, `none`, or your own track with its license. |
| `voiceover` | off | A text-to-speech voice-over, labelled "AI voice" on screen. |
| `schedule.accounts` | none | With `schedule --apply`, puts the schedule on the publish calendar as planned posts. |

Platforms are always listed international first, then Chinese.

## Example prompts

- "Make a launch kit for v1.4 of my app from CHANGELOG.md. Record the web app at localhost:3000."
- "Only show three features in the demo, and keep it under 40 seconds."
- "Add Chinese captions and copy for 小红书 and B站."
- "The caption on the sync scene is too long, shorten it and re-render only that clip."

## Related

- [Promo recut](/docs/guides/promo-recut/) for a talking-head promo of your work
- [Multi-platform export](/docs/guides/multi-platform/)
- [Scheduling and publishing](/docs/guides/scheduling-publishing/)
- [Themes](/docs/concepts/themes/)
- [launch-kit workflow reference](/docs/reference/workflows/launch-kit/)
