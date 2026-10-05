# 发布文案 (title + chapter timeline + body + tags)

`python3 $VSTUDIO/workflows/talkinghead/scripts/caption.py work/config.py --title "候选一" --title "候选二"`
checks title lengths, prints the chapter timeline in final-video time, the chapter line, the persona
tags and voice rules. The method behind it:

## Title: ≤ persona `platforms.xiaohongshu.title_max` (20) 小红书 chars
小红书 counts a Chinese char as 1 and a latin letter / digit / space as 0.5 (`vstudio.config.xhs_len`).
So "2026 Python入门的三个误区" = 4×0.5 + 0.5 + 6×0.5 + 7 = 12.5. Two angles:
- **干货/搜索向** (collection, search): keyword-dense, e.g. `2026Python入门三个误区`.
- **钩子向** (clicks): add the video's signature punchline after a `｜`, e.g. `Python入门三个误区｜第二个最坑`.
Keep year + region if the content is time- or region-specific (SEO + audience targeting). Don't
overclaim: a title implying a result the speaker didn't get ("拿到offer") reads as clickbait; use
面/复盘/逻辑-type words when it was an exploration.
When the creator proposes a title, count it, give an honest verdict, and offer 3-4 tightened variants.

## Chapter timeline: final-video time
The hook montage occupies `0 .. hook_dur`. A chapter at body / original second `o` lands at
`BODY_START + o / BODY_SPEED` (V track: from `timeline.json`; H track: `main_start = hook_dur - XFADE`).
List the hook montage as `00:00 高光预告`, then each chapter. These line up with the burned
progress-bar labels, which is a good QC check: they should match.

## Body
First line: the hook plus the honest setup, one or two sentences. Then persona `publish.chapter_line`
(default "时间线在下面，按需跳👇"), then the timeline. Follow persona `voice.rules` (e.g. no parentheses,
no em-dashes, one 干货 reframe that goes a layer deeper than the obvious) and `voice.persona`.

## Tags
Persona `publish.tags` holds the creator's default list. Mix big-traffic tags with precise-niche ones,
about 8-16; put the 8 most important first so a shorter cut-down is just the head of the list.
