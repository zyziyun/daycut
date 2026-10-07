---
title: One master, many platforms
description: Export one clean master to every platform you post to, each with its own canvas, captions placed for the app's UI, loudness, cover and post copy.
---

You get one file per platform from a single master: the right canvas and length, captions sized and placed clear of that app's buttons, loudness levelled, its own cover, post copy in the right language and within its limits, and a manifest that lists every check.

## Before you start

- **A clean master**: the finished edit with **no captions burned in**. Text burned into a 16:9 master is cut off on 3:4 and 9:16.
- **The captions as a separate file** (`cues.json` or `.srt`), so each export can place them for its own platform.
- **Covers.** One per aspect you publish, ideally. See [Covers](/docs/guides/covers/).
- Optional: a `post.json` with your title, hook, body, chapters, links and tags, with `en` and `zh` blocks if you post in both languages.

Twenty platforms have profiles, from YouTube, TikTok and Instagram to 小红书, 抖音, 视频号 and B站. The full list with sizes and limits is in the [platform reference](/docs/reference/platforms/).

## In the Mac app

1. Say which platforms you want in the request, or add them to the plan: "for Xiaohongshu, Douyin and Shorts".
2. When the clips are done, **Package for platforms** lets you pick clips and platforms. Each platform gets its own folder with the right video version, cover and copy, checked against that platform's limits.
3. Confirm the list once, then schedule the posts on the Publish board.

## With the Claude Code skill

Ask Claude to export for several platforms; it runs the shared exporter:

```bash
python3 -m vstudio.export work/master.mp4 --platforms xiaohongshu:vertical,douyin,youtube \
    --out exports/ --cues work/cues.json \
    --cover work/cover-3x4.png --cover work/cover-16x9.png --post work/post.json
```

For English-language platforms:

```bash
python3 -m vstudio.export work/master.mp4 --platforms x,instagram,instagram:feed \
    --cues work/cues.json --cover instagram=work/cover-9x16.png --post work/post.json --lang en
```

If you finished the edit elsewhere, `workflows/polish` can polish the master once and then do the same per-platform export.

## What happens for each platform

- **Canvas.** When the aspect changes, the picture is reframed by following the main face inside the safe area. With no face found, it uses a blurred fill. A master of the same aspect is only scaled.
- **Captions** go inside that platform's caption box, sized to fit two lines and kept out of its UI: the top bar, the description at the bottom, the button column on the right. If your master has burned-in panels or stamps, add `keepouts` to `cues.json` and the captions move above or below them while they're on screen.
- **Loudness.** −14 LUFS integrated and −1.5 dBTP true peak by default. Only YouTube publishes a normalisation target; for the others this is a safe convention you can override per platform.
- **Encode.** H.264 High, yuv420p, AAC 48 kHz, with per-platform quality caps. Files over a platform's upload cap get a warning.
- **Cover.** Each target takes the cover closest to its aspect, or the one you name with `--cover douyin=cover_9x16.png`. A cover of another aspect is fitted on a blurred pad with a warning. Where the feed crops covers, you get a `.feed.jpg` preview.
- **Post copy.** Titles, body and tags are checked against each platform's limits (小红书 titles 20, YouTube 100, X 280 weighted characters). English content gets English copy on X, Instagram, TikTok and YouTube; `--bilingual` writes English then Chinese.
- **Manifest.** `manifest.json` records sizes, durations, measured loudness, how well the reframe found the face, and every warning.

Outputs land as `<platform>-<orientation>.mp4` with `.cover.jpg`, `.post.md` and `.crop.json` next to each.

## Options worth knowing

| Option | Default | What it does |
|---|---|---|
| `--platforms` | persona default | Comma list of `name[:orientation]`, for example `xiaohongshu:full,douyin`. |
| `--mode` | face | Reframe: `face`, `center`, `pad-blur` or `letterbox`. |
| `--no-captions` | off | Don't burn the cues, because the master already has its captions. |
| `--lang` / `--bilingual` | detected | Post copy language: `en`, `zh`, or both. |
| `--account` | standard | Account tier for limits, for example `premium` on X. |
| `--encoder` | libx264 | `h264_videotoolbox` uses the Mac's hardware encoder. |

## Example prompts

- "Export this master for Xiaohongshu 3:4, Douyin and YouTube Shorts, each with its own safe zones and loudness."
- "Same video for X and Instagram Reels plus a 4:5 feed cut, English captions and English copy."
- "The master already has captions, so don't add new ones. Just reframe, level the audio and make the covers."
- "Write the post copy for every platform in English and Chinese."

## Related

- [Platforms reference](/docs/reference/platforms/) and [captions reference](/docs/reference/captions/)
- [Covers and thumbnails](/docs/guides/covers/)
- [Scheduling and publishing](/docs/guides/scheduling-publishing/)
- [Publishing](/docs/concepts/publishing/)
- [polish workflow reference](/docs/reference/workflows/polish/)
