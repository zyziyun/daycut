---
title: Example prompts
description: Requests that work well in Reelfold, grouped by use case, from cutting pauses in a talking-head clip to slicing a lecture, batching and second-pass edits.
---

You talk to Reelfold the way you would brief an editor. These prompts work in the Mac app's request box and with the Claude Code skill. Point at your files (drop them in the app, or name them to Claude) and adjust the details.

## How to phrase a request

A good request names three things:

1. **The material**: "this talking-head clip", "this 70-minute lecture", "these drone shots and photos".
2. **The deliverable**: how many clips, how long, what goes on them (captions, notes panels, a cover, post copy).
3. **The platform**: TikTok, YouTube Shorts, Instagram, Xiaohongshu, Douyin and so on. The platform sets the canvas, safe areas, loudness and copy limits, so you rarely need to state sizes.

Anything you leave out comes from your defaults (your persona settings) or from the material itself. When something cannot be defaulted and would change the result, such as whose face to hide or narration versus music, the planner asks before it starts.

## Talking head

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| A tight short | "Tighten this talking-head clip: cut the pauses, filler words and repeats, speed it up 1.1×, add captions, notes panels and a progress bar, export for TikTok" | [talkinghead](/docs/reference/workflows/talkinghead/) |
| An opening hook | "Open with three highlight lines from the clip, pop the key words on screen, and make TikTok and Shorts versions" | [talkinghead](/docs/reference/workflows/talkinghead/) |
| A punchier style | "Switch this to the fast-cut style: punch-ins, pop words, stamps and sound effects" | [talkinghead](/docs/reference/workflows/talkinghead/) |
| Retouch | "Smooth my skin and add light, natural makeup; slim the face a little on the cover" | [talkinghead](/docs/reference/workflows/talkinghead/), [cover](/docs/reference/workflows/cover/) |
| B-roll | "When I mention the dashboard, cut away to this screen recording without breaking the audio" | [talkinghead](/docs/reference/workflows/talkinghead/) |

</div>

## Speech cleanup only

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| Clean speech, nothing else | "Cut the pauses, ums and repeats from this recording, and list anything you're unsure about so I can confirm" | [cleanup](/docs/reference/engine/cleanup/) |
| Clean an exported edit | "I exported this from CapCut. Remove the dead air and fillers, fix the black first frame and set the loudness" | [polish](/docs/reference/workflows/polish/) |
| A gentle pass | "Light cleanup only: shorten the long pauses but keep my breaths and the natural rhythm" | [cleanup](/docs/reference/engine/cleanup/) |

</div>

## Long recordings, courses and calls

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| Episodes from a lecture | "Cut this 70-minute class into 3 vertical shorts, one idea each, zoom in on the code, with covers and post copy" | [longform-to-short](/docs/reference/workflows/longform-to-short/) |
| Vertical slices of a webinar | "Slice this webinar into 10 vertical clips under a minute for TikTok and Shorts, title band on top, readable screen crop" | [longform-to-short](/docs/reference/workflows/longform-to-short/) |
| A clean course video | "Turn this screen recording into a course video: hide the browser bar, add chapters and captions, change the students' voices" | [longform-to-short](/docs/reference/workflows/longform-to-short/) |
| A podcast or call clip | "Find the most interesting minute in this Zoom podcast, mask the guest's face, blur the name labels, vertical" | [call-clips](/docs/reference/workflows/call-clips/) |
| Clips from a finished edit | "Pull the part about side projects near the end of this video into its own short" | [talkinghead](/docs/reference/workflows/talkinghead/) |

</div>

## Promo, stories and vlogs

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| A premium promo | "Split screen with me on the left and the screenshots on the right as 3D cards with highlights; freeze for 2 seconds on the prompt and enlarge it; then a highlight reel at 1.1×" | [promo-recut](/docs/reference/workflows/promo-recut/) |
| A photo story | "Make an art-film style story from these exhibition photos: music only, three chapters, before-and-after reveals, a loupe and a film look" | [photo-story](/docs/reference/workflows/photo-story/) |
| A narrated story | "Turn these travel photos and this script into a story with narration in my own voice, 9:16" | [photo-story](/docs/reference/workflows/photo-story/) |
| A fun vlog | "Cut a fast, beat-synced vlog from these Disneyland clips and photos: DAY labels, place pins, sound effects, text pops, 9:16" | [vlog](/docs/reference/workflows/vlog/) (fun) |
| A calm vlog | "Make a calm vlog from these drone shots: color grade, slow motion, soft music" | [vlog](/docs/reference/workflows/vlog/) (calm) |

</div>

## Explainers and AI video

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| An explainer | "Make a 3Blue1Brown-style explainer on how CUDA runs on a GPU, vertical short, bilingual subtitles" | [explainer](/docs/reference/workflows/explainer/) |
| Explainers from a document | "Make five short explainer videos from the sections of this PDF" | [explainer](/docs/reference/workflows/explainer/) |
| An AI-generated episode | "Make episode 3 of my AI short drama from this script with Kling, keep the same characters, budget 200 credits" | [ai-video](/docs/reference/workflows/ai-video/) |

</div>

## Covers, packaging and platforms

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| A publish package | "Make a cover, title, description and tags for this video, for YouTube and Instagram" | [cover](/docs/reference/workflows/cover/), [polish](/docs/reference/workflows/polish/) |
| Just a thumbnail | "Make a YouTube thumbnail from this clip with a big two-line title" | [cover](/docs/reference/workflows/cover/) |
| Many platforms | "Export this one video for Instagram, TikTok and YouTube Shorts, each with its own safe area and loudness" | [export](/docs/reference/cli/#vstudioexport) |
| A script first | "Write a 90-second script on this topic for Shorts, then give me a pronunciation drill for the hard words" | [preproduction](/docs/reference/workflows/preproduction/) |

</div>

## Batches and scheduling

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| A whole batch | "Turn this folder of 30 talking-head clips into cleaned shorts for TikTok and Shorts, and show me only the ones that fail a check" | [batch](/docs/reference/workflows/batch/) |
| A week from one recording | "Slice this livestream into 14 clips under 60 seconds and package them for TikTok and Instagram" | [batch](/docs/reference/workflows/batch/) |
| A posting schedule | "Schedule these clips two a day starting Monday, at 12:00 and 19:00" | [batch](/docs/reference/workflows/batch/) |

</div>

Nothing is posted for you. A schedule gives you a posting calendar and packaged files; when you post, the Mac app fills in the upload page and you press publish. See [Scheduling and publishing](/docs/guides/scheduling-publishing/).

## Second-pass edits on a finished clip

Every finished clip can be edited again in plain words. In the Mac app you can select a span on the timeline or a caption first, so "this" means your selection.

<div class="rf-prompts">

| You want | Say something like | Workflow |
|---|---|---|
| Trim and speed | "Trim the first two seconds and speed the whole thing up to 1.2×" | [output edit](/docs/reference/engine/output-edit/) |
| Cut a span | "Cut this part" (with a span selected) | [output edit](/docs/reference/engine/output-edit/) |
| Captions | "Make the captions bigger and highlight the key words in yellow" | [output edit](/docs/reference/engine/output-edit/) |
| A different look | "Switch to the editorial theme" | [output edit](/docs/reference/engine/output-edit/) |
| Effects | "Add a pop word on 'three steps' at 0:12 and a chapter card at 0:40" | [output edit](/docs/reference/engine/output-edit/) |
| Another size | "Add a 16:9 version for YouTube" | [output edit](/docs/reference/engine/output-edit/) |
| Undo one change | "Take back the music change, keep everything after it" | [output edit](/docs/reference/engine/output-edit/) |
| Every clip at once | "Remove the series label from all clips" | [output edit](/docs/reference/engine/output-edit/) |

</div>

## Tips for follow-up edits

- **Change the plan before it runs.** Short follow-ups work well: "only TikTok", "under 60 seconds each", "5 clips", "speed 1.2×", "original speed", "in English", "cleaner" or "lighter cleanup", "mask faces" or "don't mask faces", "add a hook" or "no hook", "landscape" or "vertical", "beat-cut" or "calm". The plan keeps everything you did not mention.
- **One change at a time** after the clip is made. Each request becomes one undo step, so it is easy to compare and roll back.
- **Point at the moment.** Give a time ("at 0:12"), quote the words ("where I say 'three steps'"), or select the span in the app.
- **Text burned into the original video** (a watermark or captions in your source file) cannot be restyled or removed by an edit. Reelfold tells you when a clip has to be re-rendered from its source instead.
- **Say what you liked.** "Keep the captions as they are, just change the cover" stops a request from touching more than you meant.

## Related

- [Your first project](/docs/start/first-project/)
- [Recipes](/docs/concepts/recipes/)
- [Output edits](/docs/concepts/output-edits/)
- [Workflows reference](/docs/reference/)
