---
title: Promo recut
description: Recut a talking-head recording into a premium promo with split screen, 3D screenshot cards, highlighter sweeps, a freeze-frame and a highlight reel.
---

You get a polished promo from a recording of you talking about something you made or found: a tight cut, your face sliding into a split screen next to 3D screenshot cards that scroll to what you're describing, highlighter sweeps, a freeze-frame that zooms out into a prompt card, a zoom-through into a framed highlight reel, a chapter bar, an end card, a cover and post copy. 16:9 by default, with vertical versions laid out per platform.

## Before you start

- **The talk**: one talking-head recording about the thing you're showing.
- **Screenshots** (PNG or JPG) of the pages, posts, docs or app screens you mention. Tall ones are fine; they scroll.
- **Optional highlight footage**: a short video to insert as the highlight reel.
- **Links** for the post, and a title if you have one.

## In the Mac app

1. On Home, describe the promo and add the talk, the screenshots and the highlight footage.
2. The **plan** shows the orientation (horizontal or vertical), the platforms and the render quality.
3. **Keep spans.** Decide which sentences make the cut, for the body and for the outro. You can ask the agent to propose them from the transcript.
4. **Confirm filler cuts.** Hesitations and stutters are already gone; possible real words wait for your yes.
5. **Cards, highlights, montage.** Which screenshot appears when, which rows get the highlighter, where the freeze-frame lands, what goes in the highlight reel. This is a creative step, so it's always yours.
6. The **batch** builds the promo, renders it, normalises loudness, and makes the cover and post copy. Review it, then publish.

## With the Claude Code skill

Hand Claude the folder and describe the promo. The skill follows `workflows/promo-recut`, with everything content-specific in one `promo.config.yaml`:

1. It transcribes the talk, snaps your keep spans to word edges and gives you the cleanup review sheet. You answer with something like `确认 3,5,9 / 保留 7`.
2. It cuts, then re-transcribes the cut to make sure no real word was lost.
3. It measures the text rows in each screenshot, so highlighter bands land on real lines instead of guesses.
4. It builds a HyperFrames project and takes snapshots mid-transition for you to check before the full render.
5. It renders, exports at −14 LUFS, and writes the covers and the post with a chapter timeline.

```bash
python3 $VSTUDIO/workflows/promo-recut/scripts/build_promo.py promo.config.yaml --platform douyin
```

That builds the vertical layout for one platform. The 16:9 promo is never just cropped to 9:16, because the split screen and cards would be cut off.

## What's in the edit

| Effect | What it does |
|---|---|
| Split screen | Your face slides to one side (top band on vertical) while a screenshot card fills the other. |
| 3D screenshot cards | Cards scroll to the part you're discussing; highlighter sweeps and red boxes mark rows. |
| Chips and keyword captions | Small labels, and captions with the key term highlighted. |
| Freeze and enlarge | The talk freezes on a frame and a prompt card zooms out of a screenshot. |
| Zoom-through highlight reel | The picture zooms into a framed screen playing your highlight montage. |
| Chapter bar, stamp, end card | A progress bar with chapter labels, an outro stamp, and a closing card. |

## Options worth knowing

| Option | Default | What it does |
|---|---|---|
| Orientation | horizontal | `horizontal` (16:9) or `vertical`, laid out from the platform's safe area. |
| Platforms | YouTube | The first platform decides the layout. Vertical: 小红书 3:4 or 9:16, 抖音, TikTok, Shorts, B站 vertical. |
| Quality | delivery | `draft`, `looks` or `delivery`. |
| Cover retouch | on | The cover photo is retouched; turn it off if you want the frame as is. |

## Example prompts

- "Make a 16:9 promo of this recording about my app. Use the three screenshots and put the demo video in as the highlight reel."
- "Highlight the pricing line on the second screenshot when I mention it, and freeze on the prompt at around 1:20."
- "Now build a vertical version for Douyin and Xiaohongshu."
- "The cover crop cuts off my hand. Pick another frame."

## Related

- [Effects](/docs/reference/effects/)
- [Themes](/docs/concepts/themes/)
- [Covers](/docs/guides/covers/)
- [Talking-head shorts](/docs/guides/talking-head/)
- [promo-recut workflow reference](/docs/reference/workflows/promo-recut/)
- [Examples](/docs/examples/)
