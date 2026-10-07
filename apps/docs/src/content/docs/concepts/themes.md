---
title: Themes
description: Reelfold styles every caption band, card and effect from one design theme. Learn the five themes, the rules they follow and how to pick or switch one.
---

A theme is the whole look of a video's graphics in one name: paper and ink colours, one accent, how keywords are emphasised, fonts, corner radius, shadow, and how things move. Title bands, captions on a paper band, notes cards, quote cards, stamps, pop words, progress bars and the other themed effects all read from the same theme.

## Why it matters

Consistency is most of what makes a video look considered. With one theme, a notes card, a title and a progress bar always agree with each other, across one clip or a hundred. Changing the look is one decision, not twenty colour pickers.

## The themes

| Theme | Look | Good for |
|---|---|---|
| `editorial` (default) | Warm paper, deep ink, one terracotta accent; serif titles and quotes; keywords get a soft marker band | Most talking-head and how-to content. The safe premium choice |
| `mono` | Neutral paper, near-black ink, a pale yellow marker, no colour accent | Opinion and tech content where colour would distract |
| `soft` | Stone white, sage green accent, rounder corners, lighter shadow | Lifestyle, gentle sharing |
| `night` | Charcoal paper, warm ivory ink, amber accent; keywords in amber | Night talks, mood pieces, dark footage |
| `xhs-pop` | The Xiaohongshu red, on one keyword only; white cards, hairlines | When you want the platform-native red |

There is also `classic`, the look from before themes existed. It is kept only so older setups don't change under you, and is never offered for new work.

## The rules every theme follows

- **One accent per frame.** The accent marks one thing: a short rule, a dot, the progress fill, one keyword. Never a whole title or a box border.
- **At most one emphasised keyword per line.** Extra `【keyword】` marks in the same line render plain.
- **No saturated red on light paper.** Only `xhs-pop` uses red, a deeper one, on one keyword.
- **Notes are paper, not dashboards.** A light card, a small label, a hairline rule, then rows.
- **Quotes are typography.** Weight and size, not a coloured clip-art quote mark.
- **Stamps and pop words are quiet.** Fade and rise in 200 to 350 ms with ease-out; no slam or tilt outside `xhs-pop`.
- **Captions have contrast of at least 4.5:1.** The tests check this for every theme.
- **Progress is a hairline.** A thin track with the accent fill. No knob, no glow.

Fonts are open-licensed only (Noto Sans SC and Noto Serif SC).

## How a theme is chosen

The first one that is set wins:

1. A `theme` edit on a finished clip
2. The `VSTUDIO_THEME` environment variable
3. The project's or recipe's `theme` setting
4. The client's `theme` (for client work)
5. Your persona's `style.theme`
6. `editorial`

Any layer can tint a theme instead of replacing it, for example `editorial` with your own accent colour. A colour you set by hand on a single element (an effect's colour, a caption highlight) always wins over the theme, until you apply a theme edit, which hands those back to the theme.

## Effects are themed too

Every themed effect reads its colours, fonts, shapes and motion from the current theme. New effects are written the same way: a theme token instead of a colour literal, with an optional colour parameter for one-off overrides.

## In the Mac app and with the skill

Set your default once with `style.theme` in your persona. To restyle a finished clip, say it plainly: "use a more premium palette", "switch to black and white", "night mode". That becomes a `theme` edit, applied in one undoable step.

## Related

- [Output edits](/docs/concepts/output-edits/)
- [Effects reference](/docs/reference/effects/)
- [Persona reference](/docs/reference/persona/)
- [Style rules](/docs/reference/engine/style-rules/) and [aesthetics checklist](/docs/reference/engine/aesthetics/)
