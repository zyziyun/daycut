# Output edit: second-pass editing of every finished clip (`python -m vstudio.project output`)

Every finished video the desk app shows can be edited again (成片二次编辑): a recipe project's export
(`<item>/<platform>-<orientation>`) or a video of an adopted work folder (`final/A.mp4`; a plain skill folder is
adopted on first use). Code: `lib/vstudio/project/outputs.py` (outputs, edit document, ops, AI),
`outrender.py` (cached render), `outfx.py` (effect catalogue + frame layers). Tests: `tests/test_output_edit.py`.

## 1. Modes and capability flags

| mode | when | what a render does |
|---|---|---|
| `pipeline` | our pipeline kept the clip's clean (caption-free) master + cues: talkinghead `compose`, or a work folder's `.vstudio/masters.json` (`outputs.register_master(dir, output, master, cues)`) / `<stem>.master.mp4` / `<stem>_clean.mp4` next to it or in `work/`; the master must match the output's duration (±0.35 s) | re-composes from the master: captions are ours (text, style, position, keyword colour, on / off), other aspects are a fresh face-tracked reframe of the master |
| `flattened` | only the finished file | edits go on top of it: trims / cuts / speed re-encode, effects and a title band overlay it; captions can only be ADDED, over a mask (blur / solid box hiding the burned ones, detected band by default) or in a `band` layout (whole frame scaled into the middle, title band top, caption band bottom); burned text is never restyled; other aspects reframe the file (layout `band` keeps the whole frame) |

`show` returns `caps` (`mode, trim, cut, cut_snap, speed, loudness, effects, title_band, cover, export, undo, ai,
captions_ours, caption_text, caption_style, caption_restyle_burned, caption_toggle, caption_add,
caption_placements, relayout, relayout_layouts, burned_captions, audio`) and `caps_notes` (why a flag is off).

## 2. Files (nothing else in the project / work folder is written; the original output is never overwritten)

```
<project>/state/outputs/<slug>/      or   <work>/.vstudio/outputs/<slug>/
  edit.json          {version, output, mode, source_sig, steps [{id, at, by user|ai, note, ops, describe, revert_of?}], redo, burned}
  chat.json          {version, output, turns [{id, at, role user|ai, text, context, proposed, dropped, summary, provider,
                      model, cost_usd, seconds, status draft|applied|discarded|reverted|note, applied_step, reverted_by}]}
  transcript.json    word timings of the output (cut snapping, ai context), keyed by the file signature
  cache/<stage>-<key>.mp4|wav|jpg      stage results (4 kept per stage)
  renders/<target>.<preview|final>.mp4, <target>.cover.jpg, manifest.json {renders {target.quality: {file, key, at}}}
  .vstudio/status.json                 heartbeats of this output's renders
```

## 3. Ops (`edit --ops '[{...}]'`; one call = one undo step; all or nothing)

Times are seconds on the ORIGINAL output timeline (`"time_base": "edited"` converts from the current edited
timeline); positions are fractions of the canvas (x, y = centre).

| op | fields | notes |
|---|---|---|
| `trim` | `start?, end?, snap=true` | word-safe edges (`cleanup.snap_range`) when a transcript is cached |
| `cut` / `cut_remove` | `start, end, why?, no_snap?` / `index` | snapped to whole words with `cleanup.snap_cut` on the output's transcript (transcribed once, cached) |
| `speed` | `value` 0.5-2.5 | setpts + atempo |
| `loudness` | `lufs, tp?` | default: the target platform's profile |
| `captions` | `enabled` | pipeline only |
| `caption_text` | `cue, text, force?` | pipeline cues must stay faithful (`proofread.faithful`; `not-faithful` unless `force`); added cues (`a<n>`) any text |
| `caption_style` | `style {size 0.6-1.8, color, highlight, keywords [..], stroke, stroke_color, position bottom|middle|top|custom, y, font, box, box_color}` | flattened: applies to added captions only |
| `caption_add` / `caption_remove` | `start, end, text` or `from_transcript: true, start?, end?` / `cue` | flattened: placement auto = mask over the detected caption band |
| `caption_placement` | `mode band|mask|none, box?, style blur|solid, always?, band?` | flattened only |
| `title` | `text, sub?, color?, band_color?, y?, height?, size?` | `text: ""` removes the band |
| `effect_add` | `effect, start, end? / duration?, params {}, id?` | effect id / alias / zh label from the catalogue; params validated (unknown dropped, clamped, required checked) |
| `effect_update` | `id, start?, end?, shift?, duration?, params?` | move / retime / change params |
| `effect_remove` | `id` | |
| `cover` | `t, text, style card|plain|band` or `clear` | frame of the edited timeline |
| `export_add` / `export_remove` | `target` (`platform[:orientation]`, `3:4`, `9:16`, `16:9`), `layout auto|band` | re-layout, never a plain letterbox (band is a designed layout for flattened files) |
| `reset` | | everything back to the original (undoable) |

`ai`: `output ai --instruction "..." [--apply]` (or `edit --op ai`): the routed model (task `output_edit` of
`vstudio.llm`; `claude-code` / `codex` / API / local routes all work) gets the output facts, caps, current state,
the op list, the effect catalogue and the captions / transcript, and answers `{ops, summary}`. Every proposed op
goes through the same validator as `edit`; invented effects / ops / params, out-of-range values and ops the caps
forbid are dropped with their error. Without `--apply` nothing changes (the desk shows `proposed` for confirmation,
then calls `edit --ops` with `ops`, or `ai --apply`). No model configured: a literal-phrase fallback (speed, head /
tail trim, platform exports, LUFS, progress bar, fade) with warning `no-model`.

**Selective revert** (`output revert --step <id>`): cancels ONE earlier step and keeps every step after it. It is
recorded as a new step `{op: revert, step}` (`revert_of` on the step; undo / redo it like any step; reverting a
revert brings its target back); the state is folded without the cancelled step (`history.steps[].reverted`).
Refused with `revert-conflict {steps, n}` when a later step builds on it (edits / removes an effect or added caption
it created, removes a cut by index after it changed the cut list, or a later `reset`): the honest alternative is
undo back to it. Also `unknown-step`, `already-reverted`.

**Context** (`ai --context '{"range": [12, 18], "cues": ["c4"], "effect": "fx2"}'`): what the creator points at
(timeline selection, caption cues, one effect instance). Validated (`bad-context`, `unknown-effect-instance`), passed
to the model as `focus` (cue text and the effect instance spelled out) with "this / here / 这段 mean the focus";
the literal fallback understands "剪掉这段 / cut this" and "zoom" on the range. Echoed as `context`.

**Chat transcript** (`chat.json`, `output chat`): every `ai` call records a turn (`--no-record` to skip) with its
proposals, provider, model, cost and seconds, status `draft`; `edit --turn ID` marks it `applied` with the step
id; `revert` of that step marks it `reverted`. The desk adds its own turns (slash-command cards) with
`chat --add JSON` and patches status with `chat --turn ID --set JSON`. `show` returns `chat` so the conversation
is rebuilt after a reopen.

## 4. Effects (`output effects --json [--no-thumbs]`)

Each id is a row of the effects registry (`vstudio.effects`); `{id, label {en, zh}, description {en, zh}, kind,
stage, params (JSON-Schema subset with x-zh), required, default_dur, aliases, thumbnail}`; thumbnails are sample
frames rendered once into `$VSTUDIO_CACHE/output_fx/`.

| id | zh | stage | params |
|---|---|---|---|
| `pop-words` | 弹出大字 | frame | text, color, size, angle, anim, x, y |
| `stacking-stamps` | 印章 | frame | text, angle, scale, anim, x, y |
| `punch-in` | 推镜放大 | frame | scale, in_dur, out_dur, hold return|stay, x, y (origin) |
| `quote-card` | 金句卡 | frame | text, speaker, width, theme, anim, x, y |
| `callout-bubble` | 标注气泡 / 箭头 | frame | text, arrow_x, arrow_y, theme, anim, x, y |
| `chapter-card` | 章节卡 | frame | title, index, total, accent |
| `notes-panel` | 记笔记面板 | frame | title, bullets, theme, width, anim, x, y |
| `overlay-images` | 贴纸 / 标签 | frame | image, text, style tag|chip|badge|star|image, color, scale, angle, anim, x, y |
| `badge` | 角标 | frame | text, color, scale, anim, x, y |
| `red-box` | 框选高亮 | frame | x, y, w, h, color, width, anim |
| `progress-bar-pil` | 进度条 | frame | style, chapters [{start, end, label}], y, theme (whole clip) |
| `sfx-placement` | 音效 | audio | name (the synthesized bank), gain |
| `music-bed` | 背景音乐 | audio | file, duck_db, music_lufs (whole clip) |
| `xfade-joins` | 转场 | timeline | transition (any `vstudio.xfade` name), duration: at a cut join = an xfade, elsewhere a flash / dip |
| `end-fade` | 结尾淡出 | timeline | duration |
| `vlog-grade` | 调色 | timeline | sat, contrast, warm |

## 5. Render (`output render [--quality preview|final] [--targets primary,douyin:vertical|all] [--json-events]`)

Stages per target: `canvas` (reframe the master / file to the target canvas) -> `timeline` (trim, cuts, joins,
speed, grade, end fade) -> `audio` (SFX, music bed, two-pass loudness) -> `final` (frame pass: mask / band layout,
punch-in, overlays, cards, title band, captions, progress bar; encode) -> `cover`. Each stage key hashes its input
key + only the ops it uses, so a caption / overlay change re-runs `final` only, an SFX change `audio` + `final`, a
cut everything from `timeline`; an unchanged render (or one undone back to) is all cache hits. `preview` = same
resolution, low bitrate (ultrafast, CRF 30, 2 Mb/s); `final` = the platform delivery encode. `show.renders` says
which renders are `fresh` for the current state. Every render writes `.vstudio/status.json` heartbeats
(`output-edit:<stage>`, progress during the frame pass) into the edit folder and the owning project / work
folder; the owner's previous record is restored afterwards.

## 6. JSON contract (desk app)

All commands take `--json` (paths absolute). Every user-facing message (caps notes, warnings, refusals, op
descriptions) is `{code, params, message (English), message_zh}`: the desk localises by `code` + `params`; content
(captions, titles, cover text) stays in the project's content language.

| command | stdout |
|---|---|
| `output list --project P` | `{ok, dir, kind project|work, outputs [{id, file, title, item, platform, orientation, edited, steps, mode, edit_dir}]}` |
| `output show --project P --output O` | `{ok, output {id, file, mode, canvas, fps, duration, platform, master}, caps, caps_notes, state, captions [{id, start, end, text, original, edited, removed, added}], effects [{id, effect, start, end, params, label, edited [a, b]}], timeline {segments, joins, speed, duration}, history {steps [{id, at, by, note, describe}], undo, redo}, renders [{target, quality, file, fresh}], warnings, paths}` |
| `output edit ... --ops JSON` | the `show` document + `{step, values [per op], warnings}` |
| `output ai ... --instruction T [--context JSON] [--apply]` | `{ok, context, proposed [{op, normalized, describe, why, warnings}], ops, dropped [{op, error}], summary, provider, model, cost_usd, seconds, warnings, turn, applied, step?}` |
| `output render ...` | `{ok, output, mode, quality, targets [{target, file, cover, canvas, layout, duration, key, cached, stages [{stage, key, cached, seconds}], warnings}], seconds}`; `--json-events`: `target-start`, `stage-done`, `target-done`, `render-done` lines; `--with-ops JSON`: a before / after preview of ops that are not applied, into `renders/<target>.compare.mp4` (`compare: true`; edit.json and the manifest untouched) |
| `output revert ... --step ID` | the `show` document + `{step, reverted}` |
| `output chat ...` [`--add JSON` / `--turn ID --set JSON`] | `{ok, turns}` / `{ok, turn}` |
| `output undo|redo ...` | the `show` document + `undone` / `redone` step |
| `output effects` | `{ok, effects [...], n}` |

Errors: exit 5 + `{ok: false, error, code, params, message, message_zh}`. Codes: `unknown-owner`,
`unknown-output`, `unknown-op`, `bad-op`, `no-ops`, `unknown-effect`, `unknown-effect-instance`,
`duplicate-effect`, `bad-param`, `bad-time`, `too-short`, `cut-no-word`, `unknown-cut`, `no-audio`, `no-words`,
`transcribe-failed`, `captions-not-ours`, `unknown-cue`, `empty-text`, `not-faithful`, `placement-pipeline`,
`unknown-target`, `nothing-to-undo`, `nothing-to-redo`, `unknown-step`, `already-reverted`, `revert-conflict`,
`bad-context`, `unknown-turn`, `llm-failed`, `llm-bad-json`, `render-failed`.
Warnings / notes: `flattened`, `captions-add-only`, `relayout-crops-burned`, `no-master`, `master-mismatch`,
`source-changed`, `placement-auto`, `style-added-only`, `band-pipeline`, `effect-cut-away`, `param-adjusted`,
`unknown-param`, `no-model`, `length`. Op descriptions: `op-<op>` (e.g. `op-effect-add {effect, start, end}`,
`op-revert {step, what}`).
