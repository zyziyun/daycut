---
title: Long video to clips
description: Turn one long recording, such as a livestream, webinar or talk, into many captioned vertical clips with titles, hooks, covers and per-platform exports.
---

You get a set of vertical clips cut from one long recording, each with its own title, cold-open hook, captions, cover and post copy, exported once per platform.

![Contact sheet of vertical slices from a screen-share lecture: a title band with the series and chapter, the shared screen below, chapter cards and a notes panel](../../../assets/shots/longform-slices.jpg)

## Before you start

- **One long recording**: a livestream replay, webinar, conference talk, podcast or screen-share session. Typical length is 30 to 120 minutes.
- **A rough idea of how many clips** you want and how long each should be.
- **A list of domain terms**, so captions spell them right.
- **If it's a meeting recording**, look at one frame first. Participant tiles or name tags need a privacy region so they never show up in a clip.

## In the Mac app

1. On Home, describe the job and add the recording, for example "12 clips for Xiaohongshu and Douyin from this livestream."
2. The **plan** shows the recipe, the number of clips, the length range and the platforms. Reelfold transcribes the recording once and drafts a segment list: each row has a title, a chapter, a hook, a few notes and a short reason why it's worth a clip.
3. **Approve the segments.** This is the one review you should never skip: drop rows, move edges, retitle. Edges always sit on word boundaries. For a meeting recording you also mark the privacy regions on a frame.
4. The **batch** runs on your Mac, every clip in parallel: cleanup, captions, layout, cover, post, one export per platform. Each file is checked automatically.
5. **Review** only what was flagged: filler cuts that need a yes, red QC lights, a sample of the green ones. Small fixes (a caption, a trim, another hook, cover text, the title) don't need a re-cut.
6. Publish from the week board, one platform page at a time. You press publish.

## With the Claude Code skill

Tell Claude what the recording is and how many clips you want. For a single course or a few episodes it uses `workflows/longform-to-short`; for many clips at once it uses `workflows/batch`. The segment draft comes from:

```bash
python3 -m vstudio.batch plan-segments --source raw/livestream.mp4 --count 12 --min 45 --max 150 --provider auto
```

This writes `segments.draft.yaml`. Go through it with Claude before anything is rendered. Then Claude plans the batch, tells you the estimated machine time, storage and API cost, runs a pilot of a few clips for you to look at, and only then runs the rest.

`--provider` picks who drafts the list: your configured model, any supported provider, or `none` for an offline rule-based planner. Only transcript text goes to the provider. The rule-based draft is rougher, so review every row.

## Two layouts

| Layout | For | What it looks like |
|---|---|---|
| Split | Screen-share lectures, webinars, coding sessions | A title band (series and chapter) or the host's camera on top, the shared screen below, cropped to follow the content and zoomed until text is readable. Chapter card and notes panel per clip. |
| Reframe | A talking head or podcast filmed as one picture | The whole frame reframed to vertical: follow the face, centre crop, or fit it over a blurred fill. |

A face reframe of a screen share is unreadable, so pick split for anything with slides or code. See [Course slicing](/docs/guides/course-slicing/) for the split layout in detail.

## Options worth knowing

| Option | Default (app) | What it does |
|---|---|---|
| Number of clips | 12 | How many rows the draft plan proposes. |
| Shortest / longest | 45 s / 160 s | Length range for each clip. |
| Planner | auto | Which model drafts the segment list, or rule-based. |
| Speed | 1.2× | Body speed, pitch kept. |
| Cleanup strength | standard | `gentle`, `standard`, `tight` or off. |
| Series name | empty | Shown in the title band and on covers. |
| Privacy regions | none | Rectangles painted out of every frame (participant tiles, name tags). |
| Platforms | 小红书 3:4, 抖音 | Any vertical targets; each gets captions placed for its own UI. |

## Example prompts

- "Cut this two-hour livestream into 15 clips, 45 to 90 seconds each, for Douyin and Shorts. Show me the list first."
- "This is a Zoom webinar. The participant tiles are on the right, keep them out. 10 vertical clips with chapter cards."
- "Make three hook versions for the five best clips so I can test them."
- "Clip 4 starts too early. Trim the first sentence and change its title."

## Related

- [Projects and recipes](/docs/concepts/recipes/)
- [Batch and review](/docs/concepts/batch-review/)
- [AI providers](/docs/concepts/ai-providers/)
- [Making 100 clips in one go](/docs/guides/batch-100/)
- [Course slicing](/docs/guides/course-slicing/) and [podcast clips](/docs/guides/podcast-clips/)
- [longform-to-short workflow](/docs/reference/workflows/longform-to-short/) and [batch workflow](/docs/reference/workflows/batch/)
- [Batch engine reference](/docs/reference/engine/batch/)
- [Examples](/docs/examples/)
