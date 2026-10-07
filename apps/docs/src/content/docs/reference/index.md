---
title: Reference overview
description: What each Reelfold reference page covers, from the CLI, persona options and platform specs to the 13 workflows and the engine notes.
---

The reference section is the detailed layer under the guides: every command, option, platform value and workflow playbook. These pages are generated from the files in the [Reelfold repository](https://github.com/zyziyun/reelfold) (the engine's own profiles, catalogues, `WORKFLOW.md` playbooks and `references/` notes), so they match the code. They are written in English.

If you are new, start with the [guides](/docs/guides/talking-head/) and [example prompts](/docs/examples/); come here when you need the exact value or flag.

## Core reference

| Page | What it covers |
|---|---|
| [CLI](/docs/reference/cli/) | The engine's commands (`python -m vstudio.*`): intake, project, batch, cleanup, export, reframe, platform, effects, llm, retouch |
| [persona.yaml options](/docs/reference/persona/) | Every option in `persona.local.yaml`: speeds, loudness, brand colours and theme, platform overrides, tags, voice rules, term fixes, fonts, AI routing |
| [Platform specs](/docs/reference/platforms/) | Each platform profile: canvas, cover sizes, length, title limits, loudness |
| [Effects and themes](/docs/reference/effects/) | The effect catalogue, which engines render each effect, and the design themes |
| [Caption rules](/docs/reference/captions/) | Rules for captions, cards and post copy: names, line length, emphasis, contrast |
| [Messages and error codes](/docs/reference/messages/) | Every engine message code with its text and where it appears |

## Workflows

Each workflow is a playbook the skill follows and a recipe the Mac app runs.

| Workflow | Turns… into… |
|---|---|
| [talkinghead](/docs/reference/workflows/talkinghead/) | A talking-head recording into a tight captioned short: cleanup, speed, hooks, notes panels, retouch, cover, post copy |
| [promo-recut](/docs/reference/workflows/promo-recut/) | A talking head plus screenshots, links or another video into a premium promo with split screen and highlight cards |
| [longform-to-short](/docs/reference/workflows/longform-to-short/) | A lecture, webinar or livestream into a cut course video and/or short episodes or vertical slices |
| [call-clips](/docs/reference/workflows/call-clips/) | Calls, interviews and podcasts into clips, with face masking and name-label blur |
| [photo-story](/docs/reference/workflows/photo-story/) | Photos and a narration script (or music only) into an effect-rich story |
| [vlog](/docs/reference/workflows/vlog/) | B-roll into a calm, graded vlog or a fast, beat-cut one |
| [explainer](/docs/reference/workflows/explainer/) | A topic into a 3Blue1Brown-style animated explainer with AI narration and bilingual captions |
| [polish](/docs/reference/workflows/polish/) | Any exported edit made publish-ready: cover frame, loudness, speed, optional cleanup |
| [ai-video](/docs/reference/workflows/ai-video/) | A script or idea into AI-generated video (Kling, Seedance, MiniMax) within a credit budget |
| [cover](/docs/reference/workflows/cover/) | Covers and thumbnails in each platform's sizes |
| [slides](/docs/reference/workflows/slides/) | Square or full-canvas slides for vertical videos |
| [preproduction](/docs/reference/workflows/preproduction/) | Script writing, per-platform script checks and pronunciation drills |
| [batch](/docs/reference/workflows/batch/) | Many shorts at once: plan, pilot, parallel runs, automatic checks, review, publish packages |

## Engine notes

Deeper notes on how the shared engine works. Useful when you script the engine, debug a result or contribute.

| Page | Topic |
|---|---|
| [Intake](/docs/reference/engine/intake/) | How a plain-language request and a pile of files become a plan |
| [Projects](/docs/reference/engine/projects/) | Recipes, items, checkpoints, the inbox, series and the publish calendar |
| [Batch](/docs/reference/engine/batch/) | Batch specs, job lists, the scheduler, QC gates, review and packages |
| [Speech cleanup](/docs/reference/engine/cleanup/) | Pauses, fillers, repeats and retakes: detection, the review reply, verification |
| [Output edit](/docs/reference/engine/output-edit/) | Second-pass editing of finished clips: ops, AI edits, undo and selective revert |
| [AI providers](/docs/reference/engine/providers/) | Routing each AI task to an API, a local model or your Claude Code / Codex login |
| [Publishing](/docs/reference/engine/publishing/) | How a post reaches each platform, and why nothing auto-posts |
| [Style rules](/docs/reference/engine/style-rules/) | The design themes behind title bands, captions, notes and cards |
| [Aesthetics checklist](/docs/reference/engine/aesthetics/) | The checks to run on any cut before delivery |
| [Sound](/docs/reference/engine/sound/) | Beats, sound-effect placement and levels |
| [Retouch](/docs/reference/engine/retouch/) | Skin smoothing, makeup and reshape for covers and video |
| [Short-video SOP](/docs/reference/engine/sop-short-video/) | One talking-head short from topic to published post, end to end |
| [Adding effects](/docs/reference/engine/adding-effects/) | Adding an effect to the catalogue and porting it between renderers |
| [Validation](/docs/reference/engine/validation/) | What was tested on real footage, and the known limits |

## Related

- [What is Reelfold](/docs/start/what-is-reelfold/)
- [Example prompts](/docs/examples/)
- [Contributing](/docs/contributing/)
