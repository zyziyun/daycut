# Style rules (design themes)

Every themed overlay (title band, captions on a paper band, notes card, 本段 chip, quote card, stamps, pop words,
progress line, chapter rule, marker sweep, number counter, lower third) reads its colours, fonts, shapes and motion
from one **design theme** (`lib/vstudio/theme.py`). These rules are what the presets encode. Follow them when you
add an effect, write a workflow script, or pick colours by hand. Report them like the aesthetics checklist
(`S3 ✓` / `S3 ✗ (where)`).

## Themes

| id | 中文 | Look | Use for |
|---|---|---|---|
| `editorial` (default) | 编辑感 | Warm paper `#F5F1EA`, deep ink, one terracotta accent `#A84F2D`; titles and quotes in Noto Serif SC; keywords get a soft marker band | Most 口播 / 复盘 / 干货. The safe premium choice |
| `mono` | 黑白灰 | Neutral paper, near-black ink, a pale yellow marker, no colour accent | Opinion / tech / 干货 where colour would distract |
| `soft` | 低饱和柔和 | Stone white, sage green accent, bigger radius, lighter shadow | Lifestyle, gentle sharing |
| `night` | 夜间 | Charcoal paper, warm ivory ink, amber accent; keywords in amber | Night talks, mood pieces, dark footage |
| `xhs-pop` | 小红书红（克制版） | The 小红书 red, on one keyword only; white cards, hairlines | When the creator wants the platform-native red |
| `classic` | 旧版 | The pre-theme look (red title half, black notes card with red header, slamming stamps) | Only to reproduce old videos; never offered as a new look |

Choosing a theme (first that is set wins): output edit `theme` op → `$VSTUDIO_THEME` → recipe / project param
`theme` → client `theme` (client.yaml) → persona `style.theme` → legacy (persona `brand.accent` set and no theme
anywhere = `classic`, so old setups do not change under the creator) → `editorial`. A layer may tint tokens:
`style: {theme: editorial, accent: "#3E5C76"}`. Explicit per-element colours (an effect's `color`, a caption
style's `color` / `highlight`, a title's `color` / `band_color`) always win; the `theme` op clears them
(`restyle: false` keeps them).

Fonts are OFL only: Noto Sans SC / Noto Serif SC (Source Han). Never ship GPL or non-commercial fonts.

## Rules

**S1. One accent per frame.** The theme accent is a signal, not a fill. Use it for one thing per frame: a short
rule, a label dot, the progress fill, one keyword. Never for a whole title half, a card header or a box border.

**S2. At most one emphasised keyword per line.** `【keyword】` runs beyond the first in a line render plain
(`emph_per_line`). Emphasis is weight + the theme's treatment (marker band on paper, colour on dark / pop themes),
never weight + colour + size + stroke at once.

**S3. No saturated red on a light background by default.** `#FF2442`-class reds on cream read as alarm. Only
`xhs-pop` uses red, and it is a deeper `#D42A43` on one keyword.

**S4. Notes are paper, not dashboards.** A notes card is a light card (theme `card`), a small tracked label with
a dot (记笔记 / 本段), the title in strong ink, a hairline rule, then rows. No coloured header bar, no black body,
no rotated tag.

**S5. Quotes are typography.** Hierarchy comes from weight and size: main line in the quote face (serif in
`editorial` / `night`), sub line smaller in secondary ink, a short accent rule above, the opening mark hanging in
the margin in secondary ink. No clip-art coloured quote glyph.

**S6. Stamps and pop words are quiet.** A stamp is a small card label (dot + tracked text), upright, rising in.
A pop word is white with a soft shadow and a thin accent bar, no thick stroke, no tilt. The 8° slam with a
2.2× overshoot belongs to `classic` / `xhs-pop` only.

**S7. Motion: 200–350 ms, ease-out, small distances.** Overlays fade and rise 1–2 % of the frame (`rise`) over
the theme's `motion.in_s` (≈ 0.28 s, cubic ease-out) and leave in ≈ 0.2 s. No overshoot unless the theme sets
`motion.overshoot`. Stage segments push 60 px, not 80+.

**S8. Grid and margins.** Keep text inside the platform safe box; align cards and labels to one left margin per
layout (≈ 40 px at 1080 wide); one radius per theme; one shadow per theme (soft, low alpha).

**S9. Captions: contrast ≥ 4.5 : 1.** On a paper band, captions are theme ink without stroke (the engine
detects a flat band under the caption). Over video they are white with a thin dark stroke and a soft shadow.
Check `theme.contrast(ink, paper) >= 4.5`; the tests enforce it for every preset.

**S10. Progress is a hairline.** A 3–4 px track in the rule colour with the accent fill, small gaps between
chapters. No knob, no glow, no pill.

**S11. New effects read the theme.** Add a token to `theme._BASE` rather than a colour literal. Accept an
explicit `color` param for one-off overrides, default `None` = theme.

## Where

- Tokens + resolution: `lib/vstudio/theme.py` (`current()`, `resolve()`, `use()`, `css_vars()` for HTML).
- Themed blocks: `lib/vstudio/overlays.py` (`title_band`, `notes_panel` paper layout, `notes_chip`,
  `quote_block`, `stamp`, `progress_line`, `marker_line`, `chapter_rule`, `counter`, `lower_third`),
  `draw.emph_layer` (theme-aware text with marker / colour / underline emphasis).
- Output edit: `{"op": "theme", "theme": "editorial"}` ("换成更高级的配色", "换成黑白", "夜间模式").
- Tests: `tests/test_theme.py`.
