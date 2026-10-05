# Editing strategy menu

Each strategy is one switch in the V-track config `STYLE` dict, read by `scripts/vertical/compose.py`.
The H track only has the notes-board strategies. Show the creator the three presets, let them pick,
and mention that any single strategy can be toggled later for one re-render.

## Presets

| Preset | STYLE |
|---|---|
| 记笔记风 | `zoom=False, pops=False, stamps=False, circles=False, cards=False, sfx=False, progress='classic', callouts=True, panels=True, hook_badge=True` |
| 精剪风 | `zoom=True, pops=True, stamps=True, circles=True, cards=True, sfx=True, progress='refined', callouts=False, panels=False` |
| 混合 | `zoom=True, pops=True, stamps=False, circles=False, cards=False, sfx=True, progress='refined', callouts=True, panels=True` |

In 混合 mode, pop words and stamps automatically step aside while a 记笔记 panel is on screen.

## Shared by every preset
- **Hook montage.** It runs 3-6 clips at HOOK_SPEED, joined with 0.3s dissolves and audio crossfades.
  - Every dissolve runs over muted pads on both sides (XF*speed of extra source, muted), so it never swallows
    the first syllable of the incoming hook or the last syllable of the outgoing one.
  - The body gets a 0.3s cloned-frame pre-roll (there is nothing before body second 0 to pad with).
  - The hook title is 2 lines at the top, line 2 with yellow keywords, and pops in.
- **Subtitles.** Small, white with a dark stroke, centered around y 1525. KEYWORDS are colored yellow.
  Line breaks come from `|` in the sentence text.
- **Grade.** Light denoise, contrast and saturation lift, a slight cool balance and CAS sharpen. Tune `GRADE`.
- **Colours.** Red = persona `brand.accent`, yellow = persona `brand.highlight`; fonts = `vstudio.config.font`.

## Notes-board strategies
**progress='classic'.** A full-width bar at y 262 with chapter ticks and 2-4 character labels under it.
The active chapter gets a red pill, with a red fill and a white playhead. Readable, a bit heavy.

**callouts.** A top-left white bubble (`STYLE['callout_theme']`, default `notes-yellow`; `notes-red` = dark) with a red bar holding one full-sentence punchline for about 5-7s.
Use 1-3 where there is no panel. Config: `CALLOUTS = [(t, on_screen_sec, text)]`.

**panels (记笔记).** A white card above the subtitles with a red header, a rotated yellow 「记笔记 ↓」 tag
and red-dot bullets that reveal as the speaker says each one. They're screenshot-friendly, so viewers save the
video. Use 3-6, each with 2-5 bullets of at most 14 characters. Config:
`PANELS = [(t0, t1, title, [(t, bullet), ...])]`.

**hook_badge.** A red 「精彩预告」 pill above the hook title.

## 精剪 strategies
These came from analyzing a 精剪 vs 粗剪 comparison video (a professional editor's before/after).

**zoom.** A hard-cut punch-in per sentence, alternating 1.0 and `alt_zoom` (1.16), centered on the
tracked face. Sentence ids in `EMPH` get `emph_zoom` (1.32). This creates rhythm without any
transitions. Needs `face_track.npy` from the final body.

**pops.** One huge word or phrase in orange (`'O'`) or yellow (`'Y'`), rotated -4°, that lands with a
scale bounce and a pop SFX. Use about 1 per 15-20s, on the payoff word (a term, a number, a 2-3 character verdict like 非常长).
Put them on the shirt at y 1260-1370, never over the mouth, since the tight zoom pushes the face down.
Config: `POPS = [(t, text, 'Y'|'O', x, y, size, hold)]`.

**stamps.** A red text box with a red border, semi-white fill and a slight rotation that slams in with a
thud. For lists of complaints, give them the same end time so they stack, e.g. four 4-6 character
complaints appearing one by one as the speaker says them and leaving together.
- Keep x_left ≤ 480 so the box stays off the right-edge UI.
- Keep the bottom row ≤ y 1340 so it doesn't hit the subtitle.

Config: `STAMPS = [(t0, t1, text, x_left, y_top, angle)]`.

**circles.** The background blurs and darkens, and the face goes into a ringed circle at (540, 1100).
The title sits at y 372, with tokens popping in as the speaker says each item. `grid=True` lays out 2 columns
of black-and-yellow boxes, `False` a single column. Use this for any enumeration: "four working styles", "everything one role has to do",
"the steps after X". Config: `CIRCLES = [(t0, t1, title, [(t, token)], grid)]`.

**cards.** The frame shrinks to a 0.55x rounded card at y 600 on a blurred background, with a yellow
title and 3 lines building above it. Use one for the core thesis. Config: `CARDS = [(t0, t1, title, [(t, line)])]`.

**sfx.** Synthesized pop for pop words and tokens, thud for stamps, and whoosh for scene and hook
changes, mixed under the voice before the final loudnorm. Gains: pop 0.32, thud 0.45, whoosh 0.4.

**progress='refined'.** A thin segmented stories-style bar at y 250, one segment per chapter with 10px
gaps.
- Played parts get a pink-to-orange gradient with a soft glow and a white playhead dot. Unplayed
  segments get a faint dark backing so they read on a bright wall.
- A small dark pill underneath reads 「03 / 06 不适应」 and slides in on chapter change.
- Hidden during hooks, fades in with the body. This is the default (`progress='refined'`).

## Layout map, vertical 1080x1920 (小红书 9:16; other canvases are derived from the platform profile, see WORKFLOW.md Platforms)
| y | element |
|---|---|
| 250-300 | progress bar + chapter pill |
| 330-560 | hook title, circle/card titles + tokens, callouts at 350 |
| 600-1650 | face; card body; circle at 1100 |
| 1050-1440 | stamps and pop words, on the torso |
| 1420-1528 | 记笔记 panel bottom edge = sub_y - 60 |
| 1525 | subtitles |
