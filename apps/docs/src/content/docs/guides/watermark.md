---
title: Watermark
description: Put your handle, your logo or a generated logo on every video you export, placed inside each platform's safe area and clear of the captions.
---

Set your mark up once and every export carries it: your handle as clean type, your own PNG logo, or a logo Reelfold draws from your handle. It sits in the corner you pick, inside each platform's safe area and above the captions, so the app's buttons and your subtitles never cover it.

Nothing is added until you set it up. One video can still go out without it.

## In the Mac app

1. Open **Settings › Watermark**.
2. Type your handle (for example `@yourname`). This sets the mark up and turns on **Add to every video by default**.
3. Pick what to show:
   - **Handle**: your handle as clean type.
   - **Generated logo**: press **Generate a logo**, then choose a style: **Badge** (a dark pill), **Monogram** (your initial in a circle beside the handle) or **Plain**. It is drawn on your Mac; no online service is used.
   - **My logo**: drop a PNG on the box or press **Choose a file**. A transparent background looks best.
4. Pick a **Corner**, the **Size** and the **Opacity**. The two previews (vertical 9:16 and horizontal 16:9) are drawn by the engine exactly as an export places the mark.
5. Under **Platforms**, tap a platform to leave its videos without the mark.

To skip it for one video, open the clip, press **Export** and untick **Watermark** before you export. The switch starts at your default.

## With the Claude Code skill or a terminal

The settings live in `~/.config/vstudio/watermark.json` (or `$VSTUDIO_HOME/watermark.json`), shared by the app and the skill. You can also set defaults under `watermark:` in `persona.local.yaml`; the settings file wins.

```bash
export PYTHONPATH="$PWD/lib:$PYTHONPATH"
python3 -m vstudio.watermark set --text @yourname --default on
python3 -m vstudio.watermark set --kind generate --style monogram --position top-left
python3 -m vstudio.watermark set --image ~/logo.png          # your own logo (copied in)
python3 -m vstudio.watermark set --platform douyin=off       # never on Douyin
python3 -m vstudio.watermark preview --aspect 9:16 --out preview.jpg
python3 -m vstudio.watermark show
```

Every export path applies it: `vstudio.export` (all batch recipes, long video to clips, polish, vlog) and the app's final renders. Per export:

- `python3 -m vstudio.export master.mp4 --platforms tiktok --watermark off`
- a batch job or spec: `watermark: false`
- `python3 -m vstudio.project output render --quality final --watermark off`

## How it is placed

| Setting | Default | What it does |
|---|---|---|
| Corner | bottom right | Inside the platform's safe area (no like / comment column, no app caption bar). A bottom corner moves up above the caption band. |
| Size | 24 % | The mark fits a square of this share of the frame's short side, so it looks the same on 9:16 and 16:9. |
| Opacity | 80 % | |
| Margin | 2 % | Extra space inside the safe area. |

A video that already carries your mark (an export the engine made) is never marked a second time when you edit and render it again. Previews in the clip editor stay clean; the mark goes on the final export.

## Related

- [One master, many platforms](/docs/guides/multi-platform/)
- [Covers and thumbnails](/docs/guides/covers/)
- [Persona reference](/docs/reference/persona/)
- [CLI reference](/docs/reference/cli/#vstudiowatermark)
