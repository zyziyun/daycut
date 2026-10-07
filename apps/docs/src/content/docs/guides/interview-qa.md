---
title: Interview to Q&A clips
description: Cut an interview, podcast or coaching session into question-and-answer clips that open on the question, keep the answer tight, label speakers by role and can hide the guest's face.
---

You get one clip per question: it opens on the question (as a text card, as the asker's own voice, or both), the answer follows with the "great question" and the hesitations taken out, the question stays on screen as a header, and each speaker is labelled by role ("Host", "Guest"; "主持人", "嘉宾") unless you give names.

## Before you start

- **One recording** of the conversation. Gallery-view calls that need stacked or three-person layouts and name-label blur are better served by [podcast and interview clips](/docs/guides/podcast-clips/); this recipe writes their segment list for you.
- **Your guests' consent.** The run waits for you to confirm it; it never decides this for you.
- **Names**, if you want names instead of roles. A name is never guessed.

## In the Mac app

1. On Home, pick **Interview → Q&A clips** (or say "cut this interview into Q&A clips with Chinese and English subtitles") and drop the recording.
2. **Guest consent.** Confirm that the guests agreed to publication, faces shown or masked.
3. **Approve the Q&A pairs.** Reelfold works out who speaks when, finds each question and the answer that follows, and trims the answer. Edit the question text, the kept pieces of the answer or the roles.
4. Rendering makes one clip per pair for every platform shape, with captions (bilingual by default).
5. **Review and publish.**

## Who speaks when

Reelfold says which method it used, in the plan and in the review:

| Method | When |
|---|---|
| Local diarization (pyannote) | Installed on your machine with a local model. |
| Voice clustering | Otherwise: the voices are told apart by their sound. With similar voices the plan says the split is unsure, and you check the roles in the review. |
| None | One speaker, or too little speech: questions are still found, but no speaker labels are drawn. |

The speaker who asks the most questions is the host.

## With the Claude Code skill

```bash
python -m vstudio.qa plan --source talk.mp4 --out work/pairs.json --segments work/segments.yaml --count 8
python -m vstudio.qa render work/pairs.json --source talk.mp4 --platforms xiaohongshu:full,douyin \
    --question audio --subtitles bilingual --out out
```

## Options worth knowing

| Option | Default | What it does |
|---|---|---|
| Question | audio | `audio` (the asker's voice), `card` (a text card, read for 2.5 to 6 s), `both`. |
| Q&A clips | 8 | How many pairs to keep; answers 15 to 75 seconds. |
| Speed | 1.1 | Answer speed, pitch kept. |
| Names | (roles) | `S1=Ziyun,S2=Alex` to show names instead of "Host" / "Guest". |
| Hide the guest's face | off | `sticker` or `blur`, on the main face or the boxes you give. |
| Captions | bilingual | `bilingual`, `mono` or `translated`. |

## Example prompts

- "Cut this interview into Q&A clips with Chinese and English subtitles."
- "把这期播客切成一问一答，问题用文字卡，嘉宾遮脸"
- "Coaching call: one clip per question, names S1=Coach, S2=Student."

## Related

- [Bilingual subtitles](/docs/guides/bilingual-subtitles/)
- [Podcast and interview clips](/docs/guides/podcast-clips/)
- [Privacy](/docs/concepts/privacy/)
- [interview-qa workflow reference](/docs/reference/workflows/interview-qa/)
