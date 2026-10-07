---
title: 双语字幕
description: 原文字幕加一行译文（中英），按主题配色；每条视频另附各语言的 SRT 和 VTT 字幕文件，方便上传。
---

课堂和问答切片可以带两行字幕：说的原话，以及下面一行小一点、用主题次要色的译文。也可以只显示译文，或只显示原文。每条视频还会附上各语言的字幕文件，可直接传 YouTube、B站或自己的播放器。

## 字幕方式

| 方式 | 画面上 |
|---|---|
| `bilingual`（课堂和问答默认） | 原话在上，译文在下。 |
| `mono` | 只有原话。 |
| `translated` | 只有译文，作为主字幕。 |

目标语言默认是中英互译，也可以指定（说「只要中文字幕」就是只显示中文译文）。

## 译文从哪里来

走你的 AI 路由，任务 `translate`（Mac 应用的 设置 → AI，或 `persona.local.yaml` 里的 `llm.tasks.translate`），包括它的备用链。字幕一行一行编号翻译，不会把下一行的词挪到这一行；每行译文都会缓存，重新渲染不会再花一次钱。

如果没有任何模型能翻译，流程会停下来告诉你原因，绝不会在你要双语时悄悄只出单语字幕。

## 让术语译对

- **术语表**：人设里的 `subtitles.glossary` 固定译法，比如 `{"break the ice": "打破僵局"}`。术语没被翻译会被替换；译文里缺了会在审核时列出来。
- **先改错听**：翻译之前先套用 `subtitles.term_fixes`（语音识别纠错），名字听错了不会被错误地翻译。
- **语言学习**：课堂切片里，目标短语在字幕里按主题强调关键词的方式高亮。

## 得到的文件

每条视频旁边：`<clip>.en.srt`、`<clip>.en.vtt`、`<clip>.zh.srt`、`<clip>.zh.vtt` 和 `<clip>.bi.srt`（两行都有）。用技能也可以单独翻译任何字幕文件：

```bash
python -m vstudio.bilingual translate cues.json --from en --to zh --mode bilingual --stem out/clip01
python -m vstudio.bilingual tracks cues.bilingual.json --from en --to zh --stem out/clip01
```

## 相关

- [课堂切成知识点](/docs/zh/guides/lesson-clips/)
- [访谈切成问答](/docs/zh/guides/interview-qa/)
- [字幕参考](/docs/reference/captions/)
- [AI 模型](/docs/zh/concepts/ai-providers/)
