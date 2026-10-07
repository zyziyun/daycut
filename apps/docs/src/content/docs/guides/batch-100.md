---
title: A batch of 100+ videos
description: Plan, estimate and run a batch of a hundred or more shorts on your Mac, pilot a few first, and review only the clips that automatic QC flags.
---

You get a hundred or more finished shorts from one long recording or a folder of clips, each exported per platform with captions, cover and post copy. You look at the pilot, the clips that failed a check and a small random sample; the rest go straight to the publish packages.

## Before you start

- **The source**: one long recording (a lecture, a webinar, a podcast) or a folder of clips.
- **Time, disk space and an AI route.** Transcription and rendering run locally. Only planning, proofreading and post copy call your AI provider, and only with text. In an internal test, a 72-minute lecture became 24 clips × 4 platforms = 96 files for $0.73 of AI API cost, about $0.03 a clip.
- **A rough idea of the clips**: how many, how long, which platforms. You can let Reelfold propose the list.

## How a big batch runs

1. **Spec.** One file says the recipe, the source, the defaults every clip inherits (platforms, layout, cleanup strength, speed) and the budget. One row per clip says its range, title, hook and tags.
2. **Plan the clips.** `plan-segments` drafts the list from the transcript: ranges on word boundaries, titles checked against each platform's limit, hook candidates, notes. Go through it and drop, move or retitle rows. Don't ship the draft unseen.
3. **Estimate.** Machine time, wall time, storage and API cost, measured from your own machine once a pilot has run. `run` refuses to start when the estimate is over the budget you set.
4. **Pilot first.** A few clips run end to end and the batch stops. Check layout, captions, hook and loudness, fix the spec, then confirm.
5. **Full run.** Clips run in parallel on resource queues (transcription, rendering, AI calls). It is resumable: after a crash or Ctrl-C, run it again and finished stages are not redone. A circuit breaker pauses the batch when too many clips fail, too many go red, or the spend passes the budget.
6. **QC gates.** Every clip is checked automatically: loudness and true peak, lost words in the cut, invented captions, length per platform, title length, caption box inside the safe area, audio and video in sync, black or frozen frames.
7. **Exception-only review.** You see red clips, a random 10 % of green ones and the cleanup cuts that need your yes. The rest can be approved in one go.
8. **Package and clean up.** Approved clips go into per-platform folders with a posting schedule and a confirmation code. Then delete the regenerable intermediates.

## In the Mac app

1. On Home, describe the batch and drop the recording: "Cut this course into 40 vertical clips for Xiaohongshu and Douyin."
2. Check the proposed clip list in the plan and edit it in plain words.
3. The project makes the first clip as a pilot. Look at it in the project; if it's right, let the rest run.
4. The Inbox collects only what needs you: clips that failed a check, sampled clips and filler cuts to confirm, grouped so you can answer a whole kind at once.
5. When clips are approved, package them and drag them onto the Publish board.

## With the Claude Code skill

Ask for the batch and Claude follows `workflows/batch`. The engine commands, run from the project folder:

```bash
python3 -m vstudio.batch plan-segments --source raw/lecture.mp4 --count 40 --min 45 --max 150
python3 -m vstudio.batch plan batch.yaml
python3 -m vstudio.batch estimate --batch batch-course
python3 -m vstudio.batch run --batch batch-course --pilot 3
python3 -m vstudio.batch review --batch batch-course        # opens review/index.html
python3 -m vstudio.batch run --batch batch-course --confirm-pilot
python3 -m vstudio.batch review --batch batch-course --approve-green
python3 -m vstudio.batch package --batch batch-course --per-day 2 --start 2026-10-10
```

`status` shows progress, QC lights and why a batch paused. Fix the cause, then `run --resume`.

### Disk space

A hundred clips × several platforms adds up. Check and reclaim it:

```bash
python3 -m vstudio.batch du --batch batch-course       # disk use by part and by stage
python3 -m vstudio.batch clean --batch batch-course    # delete regenerable intermediates
```

`clean` keeps JSON, covers, sheets and previews; a later change rebuilds only what it needs. Your source recordings are never deleted by it.

## Options worth knowing

| Option | Where | What it does |
|---|---|---|
| `budget` | spec | `max_usd`, `max_hours`, `max_storage_gb`; `run` refuses over budget. |
| `--pilot N` | run | Run N clips end to end, then wait for your review. |
| `qc.sample_pct` | spec | Share of green clips flagged for a human look (default 10). |
| `concurrency` | spec or `--concurrency` | Override the parallel limits, for example `cpu-render=2`. |
| `variants` | spec | Fan out per hook, platform or language. |
| `max_len` | spec or row | A shorter version for one platform, for example `douyin: 60`. |
| `breaker` | spec | Failure rate that pauses the batch (default 0.3 after 4 clips). |

## Example prompts

- "Cut this 3-hour course into about 60 vertical clips, 45 seconds to 2 and a half minutes each, for Xiaohongshu and Douyin. Show me the list first."
- "Run three as a pilot. If they look right, do the rest overnight."
- "Make three hook versions of every clip and export each for Shorts and TikTok."
- "How much disk is this batch using? Clean up what can be rebuilt."

## Related

- [Batch and review](/docs/concepts/batch-review/)
- [Batch engine reference](/docs/reference/engine/batch/) and [batch workflow](/docs/reference/workflows/batch/)
- [Long video to clips](/docs/guides/long-video-to-clips/)
- [Studios and client batches](/docs/guides/studios/)
- [Scheduling and publishing](/docs/guides/scheduling-publishing/)
