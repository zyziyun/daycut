---
title: Covers and thumbnails
description: Make covers and thumbnails at each platform's exact size, pick the best face frame, retouch it, and put the cover on the first frame of your video.
---

You get a cover for every platform you post to, at that platform's exact size, with a preview of how its feed crops it. The same cover can replace the dead first second of your video, so the thumbnail and frame 0 match.

## Before you start

- **The cut video**, and optionally a face photo or a few slide images.
- **A headline.** The cover headline works best as the same sentence as the hook of your script.
- `./install.sh` done: it downloads the fonts and the MediaPipe face and segmentation models the cover tools use.
- **Chrome, Chromium or Edge** for the HTML templates (or `pip install playwright && playwright install chromium`).

## Pick a layout

| Layout | Use it when | What it looks like |
|---|---|---|
| **Collage** | You want to show the range of the content; the face isn't the point | Four stills in a diagonal collage, headline and tags |
| **Face on quadrants** | Personal brand: your face drives the click | Your cut-out face over a 2×2 grid of slides |
| **Split cover** | A horizontal post (小红书 4:3, YouTube 16:9) with a quote or a "tested it myself" angle | Retouched photo on the left, a dark panel with quote, title, thumbnail and chips on the right |
| **Notes cover** | Notes-style talking heads and course clips | A 16:9 notes board, plus a 4:3 centre crop |
| **Framed cover** | Screen-heavy content | Dark plate, big text, a tilted framed screenshot |

A new channel usually gets more from a face. An established one can lean on the collage.

## In the Mac app

1. Covers come with most video projects: talking-head and vlog projects stop at **Pick the cover** in your Inbox with ranked frame candidates and the cover text.
2. For a cover on its own, describe it on Home: which video, which platforms, which layout.
3. Pick a frame and edit the text. Each platform gets its own cover file next to its video, and the feed-crop preview shows what survives in the grid.

## With the Claude Code skill

Ask for a cover and the skill follows `workflows/cover`:

- **Frame picking.** For a talking head, Claude ranks frames by smile, open eyes and a centred face (`cover.score_frames`) and shows you the top picks on a contact sheet. A talking frame (mid-word, eyes on camera) reads better than an idle, posed one.
- **Retouch** before the cover is built: slimming, eye size and a light makeup preset.

  ```bash
  python3 -m vstudio.retouch face.png face_retouched.png --slim .05 --eye .04 --preset natural
  ```

  Presets are `none`, `natural`, `daily` and `glam`. `--faces all` handles group shots.
- **Cut-out face** for the quadrant layout, with a halo check against a checkerboard.
- **Render** at every platform size in one go:

  ```bash
  python3 workflows/cover/scripts/render_cover.py work/cover.html -o work/cover.png \
      --platform xiaohongshu --platform douyin --platform youtube
  ```

### The cover on the first frame

`workflows/polish` puts the cover on the first second of picture. The audio is untouched and the length doesn't change:

```bash
python3 workflows/polish/scripts/polish.py export.mp4 -o final.mp4 --cover cover.png --check
```

`--check` writes the first frame as a PNG so you can confirm frame 0 is the cover. If your first second already carries a hook shot, pick a frame from the hook as the cover instead.

## Sizes per platform

| Platform | Cover | What the feed shows |
|---|---|---|
| 小红书 (3:4 or 9:16 post) | 1080×1440 | the whole cover |
| 小红书 horizontal | 1920×1080 | the centre 4:3 |
| 抖音, TikTok | 1080×1920 | profile grid: the centre 3:4 |
| YouTube Shorts | 1080×1920 | the whole cover |
| YouTube | 1280×720, up to 2 MB | the whole cover; keep text left of the timestamp |
| B站 | 1146×717 (16:10) | also cropped to 4:3 and 16:9 |

Covers for the other platforms are in the [platform reference](/docs/reference/platforms/). Wherever a feed crops the cover, the export writes a `.feed.jpg` preview and warns when the headline is probably cut.

## Options worth knowing

| Option | Default | What it does |
|---|---|---|
| Cover accent | teal `#2dd4bf` | Colour of the collage and quadrant templates (persona `cover.accent`). The split cover follows your brand colours instead. |
| Retouch preset | `natural` | `none`, `natural`, `daily`, `glam`. |
| Matting engine | MediaPipe | `--engine rvm` gives cleaner hair; it is GPL-3.0 and downloaded only if you choose it. |
| Cover length on video | 1.0 s | How much of the opening picture the cover replaces (`--cover-sec`). |

## Example prompts

- "Make a cover for this video for Xiaohongshu and Douyin. Use my face, pick a frame where I'm mid-sentence and looking at the camera."
- "Collage cover with four different moments from the talk. Headline: 'RAG isn't the hard part.'"
- "Split cover for a horizontal Xiaohongshu post: retouched photo on the left, the quote on the right, a 'tested' stamp."
- "Put the cover on the first frame and give me a YouTube thumbnail under 2 MB."

## Related

- [cover workflow reference](/docs/reference/workflows/cover/) and [polish](/docs/reference/workflows/polish/)
- [Retouch reference](/docs/reference/engine/retouch/)
- [One master, many platforms](/docs/guides/multi-platform/)
- [Themes and brand](/docs/concepts/themes/)
- [Platforms reference](/docs/reference/platforms/)
