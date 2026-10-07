---
title: Lesson to knowledge-point clips
description: Cut a class recording into one clip per teaching point (a phrase, a word, a rule, a common mistake), each with a "Today's phrase" title card, key-term cards and bilingual captions, plus a recap clip and study notes.
---

For teachers, tutors and coaches who record the same kind of session every week. You hand over a 60-minute lesson and get one short clip per **teaching point** instead of clips cut by length: "Today's phrase: break the ice", "Common mistake: I am agree → I agree", "Word of the day: reluctant". Each clip opens on a title card, keeps the teacher's own explanation and examples, shows the key term on a card when it is first said, and carries captions in the lesson's language with a translation under it. A recap clip strings every point together, and the lesson's study notes come as Markdown and PDF.

## Before you start

- **The recording.** A screen share, a camera recording, or both as two files. With two files Reelfold lines them up by their sound, so they do not have to start at the same moment.
- **Your students.** Names and faces of students should not end up in a public clip. Reelfold lists lines that name someone before keeping them; hide faces with a mask (below) or crop them out of the recording first.
- **A translation model** if you want bilingual captions (the default). The translation goes through your AI provider routing (task `translate`); without one, choose captions in the lesson's language only.

## In the Mac app

1. On Home, pick **Lesson → knowledge-point clips** (or describe it: "把这节课切成知识点，中英双语字幕，再出一份学习笔记") and drop the recording, plus the camera file if you have one.
2. The **plan** names the recipe, the layout (with a camera: picture-in-picture), the caption mode and the platforms.
3. **Approve the points.** Reelfold transcribes once and lists the teaching points it found: kind, start and end, title, meaning, key terms. Edit, drop or keep them.
4. Rendering makes one clip per point for every platform shape (9:16 and 16:9 render separately, so nothing is cropped later), the recap, and the study notes.
5. **Review and publish.** Every file was checked before you see it (sound, loudness, first frame, captions, cover); a red item blocks the default approval.

## With the Claude Code skill

The skill follows `workflows/lesson-clips`:

```bash
python -m vstudio.lesson plan --source lesson.mp4 --out work/points.json --count 6
python -m vstudio.lesson sync --source lesson.mp4 --camera cam.mov --out work/sync.json     # two files only
python -m vstudio.lesson render work/points.json --source lesson.mp4 --camera cam.mov --sync work/sync.json \
    --layout pip --platforms xiaohongshu:full,douyin --subtitles bilingual --recap --out out
python -m vstudio.lesson notes work/points.json --out out/notes.md --pdf out/notes.pdf --title "Small talk at work"
```

## What a clip looks like

| Part | What it shows |
|---|---|
| Title card (2.2 s) | The kind ("Today's phrase · 今日短语"), the phrase or point, its meaning in the other language. Also the cover. |
| The explanation | The teacher's own segment at the original speed, under a header that keeps the point on screen. |
| Key-term card | The term and its meaning, shown for a few seconds when it is first said. |
| Captions | The spoken line with the target phrase highlighted, the translation as a smaller second line. |

Points come in four kinds: **phrase**, **vocab**, **concept** (a rule or a difference) and **correction** (a common mistake and its fix). Examples attach to the point they illustrate.

## Layouts with a camera file

| Layout | What it does |
|---|---|
| `screen` | The screen share only. |
| `pip` | Screen share with the camera as a small inset (default when a camera is given). |
| `band` | Vertical: screen band with the camera band under it. Horizontal: screen plus a camera column. |
| `camera` | The camera only. |

If the two recordings cannot be lined up by sound, the run stops and asks for the offset instead of guessing.

## Options worth knowing

| Option | Default | What it does |
|---|---|---|
| Captions | bilingual | `bilingual`, `mono` (the lesson's language only) or `translated` (the translation only). |
| Translate to | auto | The other of Chinese and English; or pick one. |
| Points | 6 | How many teaching points to cut, each 20 to 90 seconds. |
| Speed | 1.0 | Language lessons stay at the original speed. |
| Hide faces | off | `sticker` or `blur` on the whole picture, the camera tile or the screen. A face found on fewer than half the frames is flagged red. |
| Recap | on | One clip with a mini card and the teacher's own line per point. |

## Example prompts

- "把这节课切成知识点，每条一个短语，中英双语字幕，再出一份学习笔记"
- "Cut this English lesson into today's-phrase clips with Chinese subtitles only."
- "Screen share and camera are two files: picture-in-picture, mask my face."

## Related

- [Bilingual subtitles](/docs/guides/bilingual-subtitles/)
- [Interview to Q&A clips](/docs/guides/interview-qa/)
- [Course slicing](/docs/guides/course-slicing/) (a course master and episodes instead of points)
- [lesson-clips workflow reference](/docs/reference/workflows/lesson-clips/)
