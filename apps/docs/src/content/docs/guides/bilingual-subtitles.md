---
title: Bilingual subtitles
description: Captions in the spoken language with a translated second line (Chinese and English), styled by your theme, plus per-language SRT and VTT files for uploads.
---

Lesson and interview clips can carry two caption lines: what was said, and its translation as a smaller second line in the theme's secondary colour. You can also show only the translation, or only the original. Every clip also gets subtitle files per language for YouTube, Bilibili or your own player.

## Caption modes

| Mode | On screen |
|---|---|
| `bilingual` (default for lessons and Q&A) | The spoken line, the translation below it. |
| `mono` | The spoken line only. |
| `translated` | The translation only, as the main line. |

The target language is the other of Chinese and English unless you pick one ("只要中文字幕" gives translated captions in Chinese).

## Where the translation comes from

Your AI provider routing, task `translate` (Settings → AI in the Mac app, or `llm.tasks.translate` in `persona.local.yaml`), with its fallback chain. Lines are translated one by one in numbered batches, so a caption never borrows its neighbour's words, and every translation is cached: a re-render does not pay twice.

If no provider can translate, the run stops and says so. It never quietly renders single-language captions when you asked for two.

## Getting terms right

- **Glossary.** `subtitles.glossary` in your persona fixes translations: `{"break the ice": "打破僵局"}`. A glossary term left untranslated is replaced; one that is missing is listed in the review.
- **Mis-hearings first.** `subtitles.term_fixes` (the speech-recognition fixes) are applied before translating, so a misheard name is not translated wrong.
- **Language learning.** In lesson clips the target phrase is highlighted in the caption, the way the theme emphasises keywords.

## Files you get

Next to each clip: `<clip>.en.srt`, `<clip>.en.vtt`, `<clip>.zh.srt`, `<clip>.zh.vtt` and `<clip>.bi.srt` (both lines). With the skill you can also translate any captions file:

```bash
python -m vstudio.bilingual translate cues.json --from en --to zh --mode bilingual --stem out/clip01
python -m vstudio.bilingual tracks cues.bilingual.json --from en --to zh --stem out/clip01
```

## Related

- [Lesson to knowledge-point clips](/docs/guides/lesson-clips/)
- [Interview to Q&A clips](/docs/guides/interview-qa/)
- [Captions reference](/docs/reference/captions/)
- [AI providers](/docs/concepts/ai-providers/)
