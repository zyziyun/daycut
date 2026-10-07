---
title: Recipes
description: Every Reelfold workflow is a recipe manifest. See the 13 workflows at a glance and how intake picks the right recipes from a plain request and your files.
---

A recipe is the written-down version of one workflow: what it needs, which settings it takes, the steps it runs, the decisions it asks you for, and what it produces. Every workflow in Reelfold has one, in `workflows/<name>/recipe.yaml`.

## Why it matters

You never have to know the recipe names. You describe the job ("cut the part about side projects and post it to Xiaohongshu") and drop your files. Reelfold reads both, picks the recipe or recipes, and shows you a plan you can edit before anything runs. Because every recipe follows the same format, the Mac app and the skill can run, pause, resume and review any of them the same way.

## The 13 workflows

| Workflow | What it makes |
|---|---|
| [`talkinghead`](/docs/reference/workflows/talkinghead/) | Talking-head clips cleaned of pauses, fillers and repeats, with a cold-open hook, captions, cover and per-platform exports |
| [`promo-recut`](/docs/reference/workflows/promo-recut/) | A promo from a talking-head take plus screenshots: split screen, 3D screenshot cards, freeze and zoom, a highlight reel |
| [`longform-to-short`](/docs/reference/workflows/longform-to-short/) | Vertical slices from a long recording, or a cut 16:9 course with episodes (the course variant) |
| [`call-clips`](/docs/reference/workflows/call-clips/) | Clips from a call, interview or podcast, with guest faces hidden behind stickers and name labels blurred |
| [`photo-story`](/docs/reference/workflows/photo-story/) | A story from photos and short clips, narrated or cut to music |
| [`vlog`](/docs/reference/workflows/vlog/) | A travel vlog, calm or beat-cut, with grading, transitions and music |
| [`explainer`](/docs/reference/workflows/explainer/) | A 3Blue1Brown-style animated explainer with AI voice and bilingual subtitles |
| [`polish`](/docs/reference/workflows/polish/) | Finishing for an edit from any other editor: cover over the first frame, loudness, optional speed-up |
| [`cover`](/docs/reference/workflows/cover/) | Covers and thumbnails at every platform size |
| [`slides`](/docs/reference/workflows/slides/) | Square or full-frame slides for a vertical video |
| [`preproduction`](/docs/reference/workflows/preproduction/) | A spoken script checked for length and pace, plus optional pronunciation drills |
| [`ai-video`](/docs/reference/workflows/ai-video/) | AI-generated video (Kling, Seedance, MiniMax): shot list, prompts, credit budget, take review, assembly |
| [`batch`](/docs/reference/workflows/batch/) | The engine board behind many-at-once runs: pilot, full run, exception review, delivery |

`longform-to-short` has two manifests (`recipe.yaml` and `recipe.course.yaml`), so there are 14 recipe files in total.

## How intake picks the recipe

Intake is the step between your request and a project:

1. **Inventory.** It looks at every file you dropped: durations, orientation, whether there is speech, faces, a screen share, burned-in captions, document headings. Each file gets a role such as `lecture`, `talking-head`, `call`, `photo`, `script` or `finished-edit`. Your files are only read; nothing is written next to them.
2. **Plan.** Your chosen AI model gets the request, a compact summary of the materials and the recipe catalog, and proposes one or more projects. The engine then validates every recipe, input and setting against the manifests. No recipe is ever invented; anything invalid is dropped with a warning.
3. **Rules as a backstop.** With no model set up, or when the model fails, a rule planner builds the plan from a phrase table and the material roles.
4. **Revise and apply.** You can follow up in plain language ("only Xiaohongshu", "each under 60 seconds") or edit the plan directly. Applying it creates the project folders, ready for a pilot run.

What you say literally always wins: platforms, counts, speed, "hide the guest's face".

### Mixed plans and chaining

One request can produce several projects. A course folder might become lecture slices, an explainer and a set of scripts; projects from one plan share a series, so they appear together. Workflows also chain over time, for example `preproduction` → record → `talkinghead` → `cover` → `polish`.

## Related

- [Projects](/docs/concepts/projects/)
- [Batch and review](/docs/concepts/batch-review/)
- [Intake engine reference](/docs/reference/engine/intake/)
- [Workflow reference](/docs/reference/)
