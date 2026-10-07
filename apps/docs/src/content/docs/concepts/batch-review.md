---
title: Batch and review
description: How Reelfold runs dozens of videos in parallel, checks every file automatically, and asks you to review only the clips that were flagged.
---

Batch is how Reelfold makes many videos at once; review is how you check them without watching every one. Every file gets automatic quality checks, and you look at the exceptions: the clips that failed a check, a small random sample of the ones that passed, and the cuts that need your yes.

![The Inbox in the Mac app: only the clips and decisions that need you, each with a short reason](../../../assets/shots/home-I1-inbox.png)

## Why it matters

Watching 96 files end to end is a day of work. Most of them are fine. Reelfold spends that attention where it matters, so the time you spend reviewing grows with the number of problems, not the number of files.

## How it works

```
plan → estimate → pilot → full run → review (exceptions) → package
```

1. **Plan.** One job per short: a segment of a long recording, or one clip from a folder. For a long recording the AI drafts the segment list (title, hook, range on word boundaries); you go through it before anything is cut.
2. **Estimate.** Machine time, storage and API cost, before running. A run over budget is refused.
3. **Pilot.** A few jobs run end to end and stop. You check layout, captions, hook and loudness on real output, fix the settings, then confirm.
4. **Full run.** Jobs run in parallel on your Mac, sharing expensive work (one transcript per source). The run is resumable: after a crash or quit, start it again and finished steps are not redone. A circuit breaker pauses the run when too many jobs fail or go red, or when spend passes the budget.
5. **Review.** Only the exceptions.
6. **Package.** Approved clips go into per-platform folders with cover, post copy and a schedule. The package gets a confirmation code from its manifest hash; any change produces a new code. Nothing is uploaded.

### The automatic checks

| Check | What it catches |
|---|---|
| Loudness and true peak | Off the platform target by more than 1 LU, or peaking too hot |
| Lost words | Every cut is transcribed again; a word that disappeared by accident is red |
| Caption hallucination | Caption lines the speech recognizer made up |
| Length | Outside the platform's limits (red) or its sweet spot (warning, with a suggestion: speed, trims, drop the cold open) |
| Title length | Too long for the platform, or missing where one is required |
| Safe zone | Captions outside the platform's safe box |
| A/V sync | Sound and picture drifting apart |
| Black or frozen frames | Unintended black or stuck picture |
| Privacy | For screen-share lectures: a crop that touched an area you excluded, such as the participant tiles |
| Screen checks | For screen-share lectures: popups or menus left on screen, text too small to read (warnings) |

### What "flagged" means

A job is **green** when no red check fails, and **red** when one does. Warnings show on the card but do not turn it red. By default 10% of green jobs are also flagged at random for a human look, because a green light is necessary but not sufficient. Pilot jobs are flagged too.

### Approving and fixing

On the review page you approve, or reject with a reason. You can approve all unsampled greens in one step. Rejected jobs go back for re-planning. Small fixes don't need a re-cut: edit a caption, pick another hook, trim, cut a passage, change the cover or the post copy, and only the affected steps re-run. A caption edit that adds or drops a spoken word is refused unless the audio actually says the new text.

Pending filler cuts across all jobs are gathered in one sheet. Only the automatic cuts are made until you approve more.

## In the Mac app

Describe the batch on Home ("cut this lecture into 20 vertical clips for Douyin and Xiaohongshu"). The project runs a pilot first and lands in the Inbox when it needs you. Flagged clips are what you see in review.

## With the Claude Code skill

Ask for it the same way. Underneath, the skill uses `python -m vstudio.batch` (`plan-segments`, `plan`, `estimate`, `run --pilot`, `review`, `run --confirm-pilot`, `package` or `deliver`).

## Related

- [Make 100 clips in one go](/docs/guides/batch-100/)
- [Projects](/docs/concepts/projects/)
- [Batch engine reference](/docs/reference/engine/batch/)
- [Batch workflow](/docs/reference/workflows/batch/)
