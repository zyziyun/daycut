# batch — many shorts at once (plan, run, review, package)

**Use when:** the creator wants a lot of videos from one go: "这门课切 50 条", "这 80 段口播都初剪一下",
"每条出 3 个 hook 版本", "一个母版发三个平台", "批量做、我只看有问题的". One long recording or a folder of clips + a
job list in -> per-job cleaned, captioned per-platform shorts, a review page, and a publish package with a
posting schedule out. For a single video use the matching workflow instead.

**Inputs -> Outputs:** `batch.yaml` (recipe, inputs, defaults, variants, budget) + `segments.yaml` (one row per
short) -> `batch-<name>/` with `jobs/<id>/export/exports/<platform>.mp4` (+ cover, post), `review/index.html`,
`review/decisions_needed.md`, `package/` (`schedule.csv`, `manifest.json`, confirmation code).
Full reference: `references/BATCH.md`.

## Pipeline

Run from the project folder; `export PYTHONPATH="$VSTUDIO/lib:$PYTHONPATH"`.

**Which recipe.** `talkinghead-clips`: a folder of 口播 clips. `longform-slices`: one long talking-head / podcast
recording, reframed (face / pad-blur). `longform-split`: a screen-share lecture / meeting recording - every short in
the longform-to-short split layout (title band + text-following screen crop, chapter card, 记笔记 panel, hook,
captions, cover, post) with `privacy.exclude` for participant tiles. Look at one frame first
(`ffmpeg -ss 600 -i rec.mp4 -frames:v 1 frame.png`): a tile column / name tags -> `longform-split` + an exclude.

**1. Transcript + job list.** The creator decides what gets cut. Transcribe once (or reuse
`work/audio16k.json` from longform-to-short), read it, and write `segments.yaml` with the creator - one row per
short: `id`, `range` (or `start`/`end`), `title`, optional `hook: {src: [t0, t1], lines: [..]}` or several
`hooks` for A/B variants, `body`, `tags`. Offer the list as a menu with a recommendation; don't silently choose.
```yaml
# batch.yaml
name: course-slices
recipe: longform-slices            # talkinghead-clips: inputs: {folder: raw/}
inputs: {source: raw/lecture.mp4}
segments: segments.yaml
defaults: {platforms: [xiaohongshu:full, douyin], layout: pad-blur}
variants: {by: [hook]}
budget: {max_hours: 6, max_storage_gb: 60}
```

Screen-share lecture (`longform-split`, reference section 2b) - the agent-written segments.yaml (header `source`,
`series`, `speed` + rows with `chapter`, `hook: {text, start, end}`, `cuts`, `notes`, `tags`) plugs in as is:
```yaml
# batch.yaml
name: rag
recipe: longform-split
segments: segments.yaml
privacy: {exclude: ["x >= 960"]}   # the participant tile column, checked on a real frame
vertical: {series: "RAG 面试细节"}
defaults: {platforms: ["xiaohongshu:vertical", "xiaohongshu:full", "douyin", "youtube-shorts"]}
budget: {max_hours: 8, max_storage_gb: 80}
```

**2. Plan + estimate.**
```bash
python3 -m vstudio.batch plan batch.yaml          # -> batch-course-slices/ (jobs + variants, isolated job dirs)
python3 -m vstudio.batch estimate --batch batch-course-slices
```
Tell the creator the machine time, storage and API cost before running. `run` refuses over budget.

**3. Pilot.**
```bash
python3 -m vstudio.batch run --batch batch-course-slices --pilot 3
python3 -m vstudio.batch review --batch batch-course-slices      # open review/index.html
```
Look at the pilot with the creator (layout, captions, hook, loudness). Fix the spec, `plan` again if needed.

**4. Full run.** `run --confirm-pilot`. It is resumable: after a crash or Ctrl-C just run it again. `status` shows
progress, QC lights and why the batch paused (circuit breaker: failure rate, red rate, spend) - fix the cause,
then `run --resume`.

**5. Review.** `review` -> grid page (space approve, x reject with a reason, Download decisions.json) and the
combined cleanup sheet (the creator answers `确认 3,5 / 保留 7` per job). `review --approve-green` approves the
green jobs that were not sampled; red and sampled ones need a look. Then
`review --apply decisions.json`; rejected jobs become `needs-replan` (edit their rows, `plan` again), cleanup
replies re-cut on the next `run`.

**6. Package + clean.**
```bash
python3 -m vstudio.batch package --batch batch-course-slices --per-day 2 --start 2026-10-10
python3 -m vstudio.batch clean --batch batch-course-slices   # drop regenerable intermediates; `du` for disk use
```
Read the confirmation code and item count back to the creator; nothing is uploaded.

## Gotchas
- Screen-share lectures: `recipe: longform-split`, not `longform-slices` (a face reframe of a screen is unreadable,
  a pad-blur shows the whole meeting frame). With `privacy.exclude` set, longform-slices and the pad-blur layout are
  refused at plan time; the split QC is red if a crop ever touched an excluded rect.
- Only AUTO cleanup edits are cut until the creator replies; the reply goes through the review page / sheet.
- QC green is necessary, not sufficient: always look at the pilot and the sampled greens.
- Media stays local; `asr.backend: openai` sends audio to OpenAI, the `claude` planner sends transcript text to
  Anthropic.
