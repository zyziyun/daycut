# lesson-clips: a lesson recording → one clip per teaching point, a recap, study notes

**Use when:** a teacher, tutor or coach hands over a class recording (a 60-minute English lesson, a
grammar class, a coaching session; screen share, camera, or both as two files) and wants it cut by
**teaching point** rather than by length: "把这节课切成知识点", "每个短语一条", "cut this lesson into
knowledge-point clips", "today's phrase clips with Chinese and English subtitles", "顺便出一份学习笔记".
Not for a course master + episodes (`longform-to-short`, recipe `longform-course`) or plain N slices
of a talk (`longform-to-short`).

**Inputs → Outputs:** `lesson.mp4` (+ optional `camera.mov` of the same lesson) → per point
`out/<pNN>/<platform>-<orientation>.mp4` (title card "Today's phrase · 今日短语", the explanation with a
persistent header, key-term cards at their first mention, captions with the target phrase highlighted,
bilingual by default), a designed cover per platform shape, post copy, `<pNN>.<lang>.srt/.vtt` per
language; `out/recap/` (a mini card + the teacher's own line per point); `out/notes.md` + `out/notes.pdf`
(study notes); `out/report.json` (firstpass per export).

## Defaults (format `lesson-points`)
State before the first render: "按「课堂知识点切片」默认：原速（语言课不加速），不加 hook，每条一个知识点 + 标题卡，
中英双语字幕（目标短语高亮），每节课附学习笔记和回顾". Language lessons are never sped up; no hook montage;
no series labels. Student names / faces never go in: list lines that name a student before keeping them.

## Steps

```bash
export PYTHONPATH="$VSTUDIO/lib:$PYTHONPATH"
python -m vstudio.project new lessons/week12 --recipe lesson-clips --input source=lesson.mp4 \
    [--input camera=cam.mov] [--param layout=pip] [--param subtitles=bilingual]
python -m vstudio.project run --dir lessons/week12          # stops at "审核知识点"
```

Or by hand (same modules the stages run):

1. **Sync** (only with a camera file): `python -m vstudio.lesson sync --source lesson.mp4 --camera cam.mov
   --out work/sync.json`. Audio cross-correlation of the two tracks; `confidence` < 0.3 = a guess, then the
   container timestamps are used (or pass `--offset`, camera = source + offset).
2. **Plan**: `python -m vstudio.lesson plan --source lesson.mp4 --out work/points.json [--count 6]
   [--provider auto|none]`. Transcribes once (shared cache), then finds the points: `phrase`, `vocab`,
   `concept`, `correction` (examples attach to the point they illustrate). The routed model (task
   `lesson_plan`) picks sentence ranges + kinds + glosses; the rules fill in and always work offline.
3. **Review** `work/points.json` with her (checkpoint `points`): kind, start / end, title, gloss (the
   meaning in the other language), terms. Set `"edited": true` after editing so a re-plan keeps it.
4. **Render**: `python -m vstudio.lesson render work/points.json --source lesson.mp4 [--camera cam.mov
   --sync work/sync.json] --layout auto|screen|pip|band|camera --platforms xiaohongshu:full,douyin
   --subtitles bilingual|mono|translated [--to zh] [--mask sticker --mask-target camera] --recap --out out`.
5. **Notes**: `python -m vstudio.lesson notes work/points.json --out out/notes.md --pdf out/notes.pdf
   [--title "Small talk at work"]`.
6. **Check**: `out/report.json` lists firstpass per export (red items fail the stage gate); look at the
   title card, one term card and one bilingual caption frame before handing over.

## Layouts (two files)
`screen` (the screen share only), `pip` (camera inset bottom right, default when a camera is given),
`band` (vertical: screen band + camera band under it; horizontal: screen + camera column), `camera`.
One master per canvas among the platforms (9:16 and 16:9 render separately), so nothing is cropped later.

## Captions
`vstudio.bilingual`: the source line + the translation as a smaller second line in the theme's secondary
ink (`over_ink2`); `translated` shows only the translation. The translation goes through `vstudio.llm`
task `translate` (its fallback chain); persona `subtitles.glossary` ({source: target}) is enforced and
`subtitles.term_fixes` are applied first. If every provider fails the clip is rendered mono and the report
says so. Per-language SRT / VTT tracks are written for YouTube / B站 uploads.

## Privacy
`--mask sticker|blur` hides the tracked face (call-clips' cat sticker) in the picture (`all`), the camera
tile (`camera`) or the screen (`screen`); `report.json` warns when a face was found on under half of a
part's frames. Look at the frames before publishing. Pinyin / IPA lines are not drawn (gap).
