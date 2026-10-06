# Batch production (Fleet F0): `python -m vstudio.batch`

One spec + one job list -> dozens or hundreds of shorts, run as durable per-job stage DAGs on resource-class
queues, filtered by automatic QC so a human only looks at the exceptions (red jobs, a random sample of greens,
and the cleanup edits that need a yes). Code: `lib/vstudio/batch/`. Playbook: `workflows/batch/WORKFLOW.md`.

```
plan -> estimate -> run --pilot N -> review -> run --confirm-pilot -> review (--approve-green) -> package -> clean
v0.2 (desk): client init -> plan-segments -> plan -> ... -> review + job edit / job rerun (+ timing) -> deliver
             -> metrics (--csv weekly sheet) -> cleanup-sources
```

## 1. Spec

```yaml
# batch.yaml (paths relative to this file)
name: course-slices
recipe: longform-slices            # or longform-split (screen-share lectures, section 2b), talkinghead-clips,
                                   # podcast-clips / talkinghead-folder (section 2d), a plugin
client: acme                       # optional client workspace (section 8): defaults, glossary, persona overlay
inputs:
  source: raw/lecture.mp4          # longform-*: the long recording (read-only, never copied; may come from the
                                   # segments.yaml header `source:` instead)
  transcript: work/audio16k.json   # optional: reuse an existing transcript (skips extract + asr)
  # talkinghead-clips: folder: raw/  glob: "*.mp4,*.MOV"   (or clips: [a.mp4, b.mp4])
segments: segments.yaml            # the job list (YAML / CSV); or inline `jobs: [...]`
planner: file                      # file (default) | claude (stub, see section 5)
defaults:                          # every job inherits these; any row can override
  platforms: [xiaohongshu:full, douyin]
  layout: pad-blur                 # export reframe when the aspect changes: face | center | pad-blur | letterbox
  cleanup_profile: standard        # gentle | standard | tight | off
  speed: 1.0                       # body speed (pitch-preserved); hook_speed defaults to it
  preset: medium                   # x264 preset of the exports
variants: {by: [hook, platform], include_no_hook: false}   # fan-out: one job per hook x per platform
asr: {language: zh, prompt: "LangChain, RAG", backend: auto}   # transcriber: "module:fn" to plug in another ASR
budget: {max_usd: 5, max_hours: 6, max_storage_gb: 60}         # `run` refuses when the estimate is over
concurrency: {cpu-render: 2}       # overrides of the machine defaults (section 3)
qc: {sample_pct: 10, freeze: warn} # section 4
proofread: {provider: auto, model: null, low_conf: 0.5}   # section 2c; auto = llm route, else claude with ANTHROPIC_API_KEY, else none
max_len: {douyin: 60}              # optional shorter per-platform variant (section 4b); rows may override
breaker: {max_fail_rate: 0.3, min_jobs: 4, max_red_rate: null}
retry: {backoff: 2}                # seconds, doubled per attempt (transient errors only)
schedule: {per_day: 2, start: 2026-10-10, times: ["12:00", "19:00"]}
plugins: []                        # modules that register extra recipes
```

Job rows (`segments.yaml` list, `{segments: [...]}` or CSV with the same column names):

| key | meaning |
|---|---|
| `id` | job id (default `s001`…); variants append `.h1`, `.douyin-vertical`, … |
| `range` / `start` + `end` | source seconds, `"1:02:03.5"` or numbers (`"12.5-80"` also works) |
| `title`, `body`, `tags` | post copy (`tags` as a list or `a|b`); title checked per platform |
| `hook: {src: [t0, t1], lines: [..]}` | cold open cut from the source, placed before the body; `lines` = its caption (CSV: `hook_start`, `hook_end`, `hook_lines` with `|`; segments.yaml shape `{start, end, text}` works too) |
| `cuts: [[a, b, why], ..]` | longform-split: in-range removals (source s), snapped word-safe before the cleanup pass (CSV: `a-b|c-d`) |
| `chapter`, `notes: [..]` | longform-split: chapter card title (also the title-band text); 记笔记 panel lines (`notes_src: [a, b]` / `notes_window` s, default the last 20 s of the range) |
| `big1`, `big2`, `sub`, `cover_shot` | longform-split cover copy (default: the title split at its first `：`/`，`, the chapter) and screenshot second (source s) |
| `hooks: [..]` | several hook candidates -> one variant job each (`variants.by: [hook]`) |
| `platforms`, `layout`, `speed`, `cleanup_profile`, `cover`, `captions`, `max_chars` | per-job overrides |
| `max_len`, `trims` | per-platform length cap and the source spans the shorter variant drops (section 4b) |
| `cleanup_reply` | the creator's answer to the cleanup sheet (`确认 3,5 / 保留 7`); usually set by `review --apply` |
| `file` (talkinghead-clips) | which clip the row configures; `skip: true` leaves a clip out |

Unknown keys are kept in the job params, so a plugin recipe can read its own (`why`, `risk`, `prior`,
`source_speech_s`, ... ride along untouched).

**segments.yaml adapter.** A job-list file may be a mapping with a header next to its rows - the format a Claude
Code agent writes after reading the transcript:

```yaml
source: "/abs/path/Recording.mp4"   # -> inputs.source when the spec has none
series: "RAG 面试细节"               # every header key (series, speed, ...) -> a job default below spec `defaults`
speed: 1.2
segments:
  - {id: ep01, start: 157.34, end: 308.92, title: "...", chapter: "RAG全景",
     hook: {text: "...", start: 157.34, end: 164.08}, cuts: [[169.60, 172.06, "aside"]],
     notes: ["...", "..."], tags: [RAG, LLM], why: "...", risk: "...", prior: "..."}
```
Spec top-level `source:` / `speed:` / `series:` work the same, so `plan segments.yaml --recipe longform-split`
plans such a file directly (no batch.yaml; then the spec sections below can't be set).

## 2. Recipes and stages

`python -m vstudio.batch recipes` lists them. `longform-slices` and `talkinghead-clips` run this DAG (`longform-split`: 2b):

| stage | resource | what | shared |
|---|---|---|---|
| probe | io | `media.probe` + content sha1 of the source | per source |
| extract | io | 16 kHz mono wav (skipped when `inputs.transcript` is given) | per source |
| asr | asr (`api:openai` with the OpenAI backend) | `asr.transcribe` (cached by content hash) -> transcript.json | per source |
| cleanup | cpu | `cleanup.analyze` on the job range (+ hook range, one edit numbering) -> EDLs, review sheets, confirm list | |
| apply | cpu-render | `cleanup.apply`: auto edits + `cleanup_reply`, frame-exact, word-safe | |
| compose | cpu-render | hook + body (speed), final-time `cues.json` (hook lines, then words via the cleanup TimeMap), `post.json` | |
| export | cpu-render (`face` for layout face) | `vstudio.export`: per-platform canvas, captions in the caption box, loudness, cover, post | |
| verify | asr | `cleanup.verify` re-ASR: lost content words (the re-ASR is kept as `heard.json`) | |
| glossary | cpu / `api:claude` / `api:openai` | ONE caption glossary per source from the whole transcript: terms + recurring ASR confusions (2c) | per source |
| proofread | cpu / `api:claude` / `api:openai` | captions before burn-in: term fixes + glossary + minimal LLM fixes + low-confidence words (2c) | |
| qc | cpu | gates (section 4) | |
| preview | cpu-render | contact sheet + 3 s snippet (same resolution, low bitrate) for the review page | |

`longform-slices` = vertical slices cut straight from one long recording with `vstudio.export`'s reframe of the
WHOLE frame (pad-blur / face / center / letterbox). It refuses to plan while `privacy.exclude` is set: a pad-blur
of a meeting recording shows the participant tiles. Screen-share lectures: `longform-split` (2b).

### 2b. `longform-split` (screen-share lectures)

Every job goes through the vertical pipeline of `workflows/longform-to-short` (its scripts run unchanged, as
subprocesses on a per-job `config.json` the batch writes): title band (series + chapter; during the cold open the
hook lines - the proofread captions of what the hook SAYS - with the captions under it hidden, so the hook is never
shown twice: `vertical.hook_captions: hide | show`) or the host's camera band on top, the screen below as a
content-following crop zoomed until a text line is >= `screen.min_text_px` tall but never upscaled past
`screen.max_upscale` (2.0: a 720p share only blurs beyond that; text that would need more is shown at the cap,
a tighter region, Lanczos + light unsharp `screen.sharpen`), the captions in their own lower band below the screen
(no dark fade over the page; `vertical.split.screen_to: frame` brings back the screen under a scrim), chapter card (`01 / 24` = the job's place in the list), 记笔记 panel from `notes`,
captions re-laid into each platform's caption box, the per-job cold-open hook, a cover per canvas (`<series> ·
k/N`, title copy, a screenshot cut from the source through the privacy guards) and the post (`title`, `body` or
the notes as bullets, `tags`). Platforms: vertical targets only (`xiaohongshu:vertical` 3:4,
`xiaohongshu:full` / `douyin` / `youtube-shorts` 9:16; one master per canvas, one export per target).

```yaml
recipe: longform-split
segments: segments.yaml                    # header gives source / series / speed
inputs: {transcript: work/audio16k.json}   # optional: reuse an existing transcript (skips extract + asr)
privacy:
  exclude: ["x >= 960"]                    # [x0, y0, x1, y1] (null = frame edge), {x0: 960}, or "x >= 960"
screen:                                    # all optional
  region: [0, 90, 960, 630]                # skip detection; default: geometry step once per source
  geometry: {step: 10, bright: 160}        # longform-to-short geometry.* knobs (dark-mode shares: lower bright)
  min_scale: 1.6
  max_scale: 2.4
  max_upscale: 2.0                         # hard cap of the source -> canvas scale
  min_text_px: 28
  sharpen: 0.6                             # unsharp amount on upscaled crops (0 = off)
  popups: mask                             # transient editor popups / context menus: mask | hold | off
  popup_max_s: 20                          # a box that closes within this many seconds is a popup (also one
                                           # open at a cut: masked until it closes / the clip ends)
vertical: {mode: split, series: "RAG 面试细节", split: {band_frac: 0.16}, master_preset: veryfast}
subtitles: {term_fixes: [["[Tt]runking", "chunking"]]}  # per-video ASR fixes (regex), as in the workflow
notes: {window: 20, tag: 记笔记}
defaults: {platforms: ["xiaohongshu:vertical", "xiaohongshu:full", "douyin", "youtube-shorts"], preset: medium}
```

| stage | resource | what | shared |
|---|---|---|---|
| probe / extract / asr | io / io / asr | as above: ONE transcript per source (or `inputs.transcript`) | per source |
| geometry | cpu | the workflow's `analyze.py` geo frames + `geometry.py` -> crop spans (shared page minus browser chrome), each clipped against `privacy.exclude`; `screen.region` skips detection | per source |
| cleanup | cpu | range edges snapped word-safe (+ end over the last word's tail), row `cuts` snapped and removed, `vstudio.cleanup.analyze` on the rest -> EDL, review sheet, confirm list (the same reply loop); hook edge snapped | |
| compose | cpu-render | work dir: `keep_list.json` (EDL + reply), `hook_edges.json`, crop spans, the shared transcript as `audio16k.json` (as the cut leaves it: a cut `filler-merged` edit moves the word it trimmed past the cut, so the word keeps its caption while it is still heard - `lfsplit.cut_transcript`) -> `build_timeline` -> `make_audio_assets` -> `render.py` (`render.audio_only`: PCM grid + loudnorm, no 16:9 picture) -> `build_subs` (term fixes) | |
| export | cpu-render | `make_vertical.py --targets <platforms>`: vertical master per canvas from the SOURCE + `vstudio.export.export_one` per target (captions, loudness, cover, post) | |
| verify / proofread | asr / api | re-ASR of the job's audio (lost words); caption proofreading (2c) -> the cues `make_vertical` burns | |
| qc / preview | cpu / cpu-render | the gates of section 4 + privacy; contact sheet + snippet | |

### 2d. `podcast-clips` and `talkinghead-folder` (P1 recipes)

`podcast-clips` runs `workflows/call-clips` per job: the batch writes a one-clip `clips.json` (windows from the
row range or `windows`, up to 2 cold-open pulls from `hook` / `hooks` / `hook_candidates`, title lines from the
title, a 记笔记 panel from `notes`, the spec `call:` tiles / stickers / name mask / auto-trim) and runs
`build_clips.py --only <id> --clean-master` (selection -> auto-trim -> hook montage -> face tracks + masks / name
blur -> layout -> captions) -> caption-free master + cues; `coverage` re-runs `verify_coverage.py` on every guest
track (QC `face-mask-coverage`: under 100 % is red); then proofread / export (captions re-laid per platform) / qc
/ preview. `call: {host_region, guests: [{name, region, sticker, label}], no_mask, renderer: render_vertical.py |
render_trio.py, name_mask, auto_trim, cut_profile, renderer_args: [scale=2.4], notes_panels}`.

`talkinghead-folder` runs the talkinghead V track per clip of `inputs.folder` / `inputs.clips`: `asr`
(prep_sources.sh: HDR -> SDR + whisper) -> `cleanup` (edit_list.py = every whisper sentence, within the row range
when trimmed -> cut_pass1.py (word-safe edges, 气口) -> strict_pass.py apply with the row's `cleanup_reply`; CONFIRM
rows go to the review page) -> `face` (face_track.py; optional) -> `compose` (config.py -> compose.py all
--clean-master with `talkinghead: {style, keywords, hook_speed, body_speed}`) -> proofread / export / qc / preview.
Both recipes' lost-word gate is the workflow's own (no batch `verify` re-hearing); the workflow scripts run
unchanged, as subprocesses.

### 2c. Caption proofreading (`proofread`, both recipe families)

Captions must match the audio, so proofreading only fixes recognition errors, before burn-in:
(a) the spec `subtitles.term_fixes` + persona `subtitles.term_fixes` + `asr.GENERIC_TERM_FIXES` (the creator's
own list: applied even when a fix deletes words, but such a fix is listed under `warnings`);
(b) the source glossary (stage `glossary`, shared: built ONCE per source, applied identically to every job of it):
the LLM reads the WHOLE transcript and lists the domain terms and the recurring confusions (`RM -> LLM`,
`称爆 -> 撑爆`), a second focused look goes over every latin token with its contexts, and a third look rejects
guesses; each fix is validated (a term: latin or 2+ characters, found in the transcript, confidence >= 0.97,
sound-alike, no words dropped or added, no translation, not case-only) and applied with word boundaries (RM never
hits ARM / RMS). `glossary.json` keeps terms, fixes, rejected ones with the reason and the raw replies;
(c) an LLM pass per job (`vstudio.proofread`, two looks for recall): it sees the cues, the glossary (known
confusions), the verify re-ASR of the same audio (a second hearing), the low-confidence words and the topic
(asr prompt, term-fix targets, series, chapter, notes) and returns minimal per-cue fixes as JSON
(`{"fixes": [{"i", "from", "to", "why"}]}`). The audio-faithful validator (`proofread.faithful`) accepts only
substitutions of mis-heard spans: on the spoken units (one per CJK character / latin word) no unit may be deleted
(`整个的RM -> 整个LLM` drops 的) or added, each replaced run must sound alike (syllables within 1) and stay in its
language; the cue stays >= 60 % similar; a whole-caption "from" is reduced to the words that change. A span the
term fixes / glossary already fixed is never re-edited, and an accepted term fix is applied to the job's other cues
with the same span (`llm-propagated`). Everything rejected is logged with the reason. Providers:
`auto` (default: the configured `vstudio.llm` route for tasks `proofread` / `glossary`, else `claude` when
`ANTHROPIC_API_KEY` is set, else `none`), `claude` (anthropic SDK, imported lazily; `claude-opus-5-5`), `openai` (only
when set explicitly; `OPENAI_API_KEY`; default `gpt-4.1-mini`), any other `vstudio.llm` provider (deepseek, qwen,
kimi, glm, openrouter, gemini, ollama, lmstudio, vllm, llamacpp, claude-code, codex - references/PROVIDERS.md;
`proofread.glossary_provider` picks the glossary's), `none`;
`proofread.call: "module:fn"` plugs in any other `fn(system, prompt, model) -> (text, usage)`. Cost is booked to
the budget (`prices.proofread_in` / `proofread_out` per MTok override the table). The LLM result of every cue is
cached per batch (`cache/proofread-cues/`, key = the normalized ASR cue text + a hash of the prompt, provider /
model, glossary, term fixes and topic - not the notes, which are a hint only and never re-run proofread): a re-cut
re-sends only the cues whose text changed, so the corrections of unchanged cues are never re-rolled
(`proofread.json` `cache {hits, sent, stored}`; a job proofread before the cache is seeded from its reviewed
report on `job rerun`). Cues the creator fixed with `job edit --op caption` are locked: no term fix, glossary,
LLM or filler-edge pass touches them;
(d) fillers are never removed from captions (they are in the audio): cleanup auto-cuts the obvious caption fillers
(stacked connectors: an abandoned `因为|而且`, `然后的话`, the `的话` of `另外的话`) and the stacks still spoken are
listed per job in `decisions_needed.md` / on the review card, to cut with the cleanup reply. No caption ends on a
filler that leads into the next words (`就是`, `然后`, `那个`, `嗯`) or starts on a particle that closes the words
before (`的话`, `嘛`, `吧`): the two cues merge when they fit the caption box, else the filler moves across the
boundary (`proofread.fix_filler_edges`, after the per-platform re-layout too; logged as `filler_edges`);
(e) words with an ASR probability < `low_conf` (from the verify re-ASR) are flagged.
Everything lands in `jobs/<id>/proofread/proofread.json` (`changes` with before / after / source term_fix |
glossary | llm | llm-propagated / why, `rejected`, `warnings`, `low_confidence`, `fillers_left`, `filler_edges`);
the review card shows the changed cues (before struck through) and the unsure words. `proofread: {enabled: false}`
skips the stage, `glossary: false` the glossary, `filler_edges: false` the edge pass; `glossary_model` overrides
the model of the glossary only.

**Cut edges.** Every word cut (cleanup edits, row `cuts`) is placed word-safe on the energy curve, and when one
edge sits in running speech the syllables are counted from the other, solid edge (`cleanup.syllable_edges`: energy
nuclei vs `cut.syllables` of the removed words) - whisper's word times drift 0.1-0.2 s in fluent speech, and a cut
stopping one valley short left a syllable of the removed word (re-ASR heard 都是错的[话] where 然后的话 was cut).

**Privacy.** `privacy.exclude` rects are painted out of every source frame before any crop (masters, freeze
stills, the cover screenshot); the screen region is the geometry crop (or `screen.region`) with every exclude that
spans its height / width cut off, so the crop never even reaches the excluded column; `vertical.speaker.region`
overlapping an exclude is refused at plan time; `layout` / `vertical.mode: pad-blur` is refused while an exclude
is set. QC adds `privacy-overlap` (the workflow's `privacy_overlap_frames` must be 0) and `privacy-layout`. Set the
exclude from a real frame of the recording (Meet / Zoom put the participant strip in the right column).
Layouts (`layout` per row, `defaults.layout`, or `vertical.mode`): `split` (default), `screen`, `speaker` (needs
`vertical.speaker.region` = the HOST's own camera), `pad-blur` (only without excludes). Chapter cards are dark on
purpose: black-frame QC ignores the card windows.

A finished longform-to-short project's `work/audio16k.json` can be passed as `inputs.transcript` (any recipe), so
the batch reuses that transcription.

**Adding a recipe** (plugin module listed in `plugins:`; `plugin_paths:` adds folders to `sys.path`):

```python
from vstudio.batch.recipes import Recipe, Stage, register
from vstudio.batch.stages import speech_stages          # reuse, or write your own Stage list

def expand(spec, rows):                                  # rows = the job list, already normalised
    return [dict(item=r["id"], params=dict(spec["defaults"], **r, source=..., _dur=...)) for r in rows]

register(Recipe("my-recipe", speech_stages(), expand, "what it makes"))
```

A stage function receives `ctx` (`ctx.job`, `ctx.params`, `ctx.spec`, `ctx.dir` - an empty folder for its
outputs, `ctx.inputs[dep]` - each dependency's output dict) and returns a JSON-able dict: `files` (checked on
resume / after `clean`), optional `digest` (content hash feeding downstream keys), optional `cost_usd`.
Stage options: `shared`, `params` (everything that changes the output - the key), `units` (media seconds, for
the bench table), `cost` (USD estimate), `enabled`, `retries`, `paid` (never auto-resubmitted), `purge` (globs
of regenerable outputs), `version`.

## 3. Scheduler

* **State**: `<batch>/batch.db` (SQLite, WAL): jobs, stage rows (state, input key, outputs, attempts, timings),
  shared artifacts, events, bench. Job folders `<batch>/jobs/<id>/<stage>/`, shared outputs `<batch>/cache/`.
* **Resume**: every stage start / finish is committed. After a crash or Ctrl-C the next `run` turns stale
  `running` rows back to `pending` and continues; finished stages are not redone. One `run` per batch at a time
  (file lock).
* **Idempotent keys**: `sha1(stage, version, params, dep keys + digests)`. Changing one job's title re-runs only
  compose -> export -> qc -> preview of that job; a new cleanup reply re-cuts from `apply`; the shared ASR is
  never repeated for the same source and settings.
* **Resource classes** (defaults from the machine; 10 cores / 32 GB gives): `asr` 1 (whisper owns the GPU),
  `cpu` 5, `cpu-render` 3 (x264 is itself multi-threaded), `browser` 2, `face` 2, `io` 4, `api:*` 4. Override
  in the spec (`concurrency:`) or per run (`--concurrency cpu-render=2`).
* **Retries**: transient only (timeouts, connection resets, 429 / 5xx, `TransientError`), exponential backoff;
  deterministic errors fail the job at once; `paid` stages never retry.
* **Circuit breaker**: pause when this run's finished-job failure rate > `max_fail_rate` (after `min_jobs`), the QC
  red rate > `max_red_rate` (optional), API spend > `budget.max_usd`, or any pilot job fails / goes red.
  `status` shows the reason; `run --resume` continues.
* **Pilot**: `run --pilot 5` runs 5 jobs end to end and stops in `pilot-review`; after a look, `run --confirm-pilot`.
* Exit codes: 0 ok, 1 some jobs failed, 2 refused over budget, 3 paused, 4 pilot waiting, 6 another run active.

On a pause no new job and no expensive stage starts, but a job whose render stages are all finished still runs its
cheap tail (`verify` / `qc` / `preview`; `Stage.drain`), so an exported job is never left without QC / preview.
Whatever is still open when `run` exits (pause, Ctrl-C, error) is marked `interrupted`; `status` also shows a
`running` row as `interrupted` when no `run` holds the lock (a killed process). `run --pilot N` after a pause keeps
the same pilot jobs (finished ones are re-checked from cache); `run --jobs a,b` re-checks named jobs even when done.

Job states: `planned -> running -> done (QC green / red) | failed | interrupted`; review: `approved | needs-replan`;
`packaged`; `dropped` (no longer in the job list).

## 4. Estimate and QC

**Estimate** (`estimate`, also checked by `run`): per stage units x seconds-per-unit from the bench table ->
machine time, wall time (slowest resource queue: work / limit), storage, API cost (OpenAI whisper backend
per minute, a Claude planner if used; `prices:` overrides). Shared stages count once per source. The table
starts from built-in guesses and is replaced by measurements: each finished stage updates the batch table and
the machine table (`$VSTUDIO_CACHE/batch_bench.json`, default `~/.cache/vstudio/`; `VSTUDIO_BATCH_BENCH`
overrides), so run one pilot on an otherwise idle machine to calibrate (`bench` prints the table).

**QC gates** (job is green when no red-severity check fails):

| gate | how | status |
|---|---|---|
| loudness / true peak | export manifest measurement (`audio.measure_loudness`), re-measured if missing; ±`lufs_tol` 1 LU, TP <= target + 0.5 | existing |
| lost words | `cleanup.verify` re-ASR of every cut (`qc.verify: false` skips); compared on a normalised zh/en character stream: latin sub-word pieces merge (`q uer ies` = `queries`), case / spaces / punctuation ignored, fillers and soft particles (`的话`, `嘛`, ...) never "lost", a replacement of similar weight is an ASR variant (`比例`/`比的`, `assumption`/`assum`; listed as `variants`), words removed on purpose (sidecar `removed`) are ignored near their cut; a span still missing is re-heard on its own window (whisper on a whole file sometimes skips a passage, e.g. a body repeating its cold open) and dropped when it is there (`rechecked`). Red only for real loss: >= 2 CJK chars or a whole latin word heard as (almost) nothing | existing |
| caption hallucination | burned cues through `asr.drop_hallucinations` | existing |
| length window | `platform.check_length` (hard min / max red, sweet spot warn) | existing |
| title length | `publish.check_title` per platform (`title_required` makes a missing title red) | existing |
| safe zone / caption box | export manifest: canvas size, caption box inside the safe box, caption keep-out / overflow warnings | existing |
| A/V sync | video vs audio stream duration (`av_tol` 0.1 s) | new |
| black / frozen frames | ffmpeg blackdetect (`black_min` 0.5 s; chapter-card windows exempt) + freezedetect (`freeze_min` 3 s; warn for longform-slices / longform-split) | new |
| privacy (longform-split) | `privacy_overlap_frames` == 0 in every canvas plan; no pad-blur item while an exclude is set | new |
| length plan | over the platform sweet spot (or `max_len`): warn `length-plan` with a suggestion - speed needed, the cold open that could go, pending cleanup edits, trim candidates in source seconds (also `suggestions` in qc.json / review items); over `max_len` after the variant: red `max-len` | new |
| screen (longform-split) | `screen-popup-visible`: make_vertical samples every rendered master at 2 fps (`_vertical.scan_popups`: each screen item, 记笔记 panels / hook boxes masked, pans stabilised, forward + backward `detect_popups`) and any popup still on screen > `qc.popup_s` (1 s) covering >= `qc.popup_scan_cover` (0.02) -> warn with its output times (`scan_popups.py VIDEO --plan plan.json` re-checks an older export); `screen-popup`: an editor popup left visible (one that stays open past `popup_max_s`, or `popups: hold / off`) covering > `qc.popup_cover` (0.05) of the crop for > `qc.popup_s` (1 s) -> warn (masked ones are listed only); `screen-overlay-static`: persistent UI chrome inside the crop - an editor's block / selection menu or a toolbar left open over whole items, which the popup scan misses because it neither opens nor closes inside one item (V02 field test: the Notion menu of ep02 / 03 / 04 / 06). make_vertical also runs `_vertical.scan_static_overlays` on every master (2 fps at full canvas width; a card = four faint thin border lines, page-coloured fill, not touching the crop edge or cut by one side edge; tracked across items with the same screen box) and keeps a card shown >= `qc.overlay_s` (1 s) with evidence `shadow` (a drop-shadow halo outside its left / right borders), `pinned` (the page around it changes, it stays) or `appeared` / `vanished` (over an unchanged page) -> warn with output times + canvas box (`hug`: the crop edge cutting it - a crop shift could hide it); a bordered box that is part of a static page / slide (no shadow, nothing changes around it) is not flagged; one already reported by `screen-popup-visible` is not repeated. Warn only: nothing is masked or re-cropped. plan.json `static_overlays`; job detail JSON `qc.screen[canvas].static_overlays` (also `visible_popups`); `vertical.overlay_scan: false` turns it off, a dict overrides `_vertical.OVERLAY_DEFAULTS`; a reused master without the scan is scanned on the next export; `scan_popups.py` re-checks a rendered file (both scans, `--no-static`); `screen-text`: text lines drawn < `qc.text_px_min` (14) px -> warn | new |
| face-mask coverage, generic layout check, sensitive words, sameness across the batch | - | to build (F1) |

`sample_pct` (default 10) of green jobs are flagged (deterministic per job id + `seed`) for a human look.

### 4b. Platform length -> plan

Every export longer than its platform's sweet spot (抖音 60 s, ...) gets a `length-plan` suggestion. To make a
shorter variant for one platform only, set `max_len` (spec top level, `defaults` or a row):

```yaml
max_len: {douyin: 60}                                  # or {douyin: {max: 60, via: auto|speed|trim|suggest, max_speed: 1.25}}
segments:
  - {id: ep01, ..., trims: {douyin: [[272.1, 286.5]]}}   # source seconds the douyin variant drops (from the suggestion)
```

At export the over-long platform files are cut (the row's `trims`, 30 / 40 ms fades at each join) and then sped
up (pitch kept) up to `max_speed`; the other platforms keep the full cut. The manifest entry says `variant`
{max_len, speed, trims}; still over `max_len` -> QC red `max-len` (add trims).

## 5. Planning, review, packaging, storage

* **Planner `file`**: the job list is written by a human or a Claude Code agent from the transcript. Rejected jobs
  come back as `needs-replan` with the reviewer's reason (`status`); edit their rows, `plan` again (only the
  affected stages re-run).
* **Planner `claude`** (stub; needs `pip install anthropic` + `ANTHROPIC_API_KEY`, never used in tests): proposes
  segments from `inputs.transcript`. `--sync` uses the regular API (pilot / interactive); otherwise it submits a
  Message Batch (half price, results can take up to 24 h), a later `plan` collects it and writes
  `segments.claude.yaml` for a human to check before planning it with `--planner file`.
* **Review**: `review` writes `review/index.html` (grid: contact sheet, 3 s snippet on hover, QC light, red reasons,
  warnings, sample / pilot badges; keys: space approve, x reject with a reason, u undo, j / k move, d download)
  and `review/decisions_needed.md` (every pending cleanup edit across jobs). The page saves `decisions.json`;
  `review --apply decisions.json` ingests it. `review --approve-green` approves green, unsampled jobs in one go.
  The page and sheet show each job's questions under the CURRENT confirm policy (`vstudio.cleanup.apply_policy`
  re-run on the job's EDL; answered ones are counted, policy cuts not in the render yet are listed), per-class
  bulk buttons (`"confirm_kinds": ["filler-merged", "filler/lead"]` or `{"ep03": [...], "*": [...]}` in
  decisions.json, or `review --confirm-kinds a,b`; a kind matches its sub-classes) and `"accept_policy": true`
  (`--accept-policy`) to cut the pending policy approvals; `"jobs": ["ep02", "ep04"]` (`review --accept-policy
  --jobs ep02,ep04`) limits both bulk answers to those jobs. Every creator reply is learned per persona
  (`vstudio.cleanup.learn`) - only the answers new in that reply, never the policy approvals `accept_policy` cuts
  (they are the policy's, not the creator's). Caption fixes not backed by the glossary or a strong sound-alike
  (`vstudio.proofread.flag_guesses`: pinyin via pypinyin or macOS Foundation, a latin phonetic key) are GUESSES:
  yellow on the page, `<mark>GUESS</mark>` in the sheet.
* **Package**: approved jobs -> `package/<platform>-<orientation>/<NNN>_<job>/` (`video.mp4`, `cover.jpg`,
  `post.md`, hard links), `schedule.csv` (`per_day` per platform), `manifest.json`; the manifest hash is the
  confirmation code (any change to files, order or dates -> a new code). Nothing is uploaded in F0.
* **Storage**: `clean` deletes regenerable intermediates (cuts, masters, 16 kHz wavs, and exports once packaged)
  of finished jobs, keeping JSON, covers, sheets, snippets and keys; a later change rebuilds what it needs.
  `du` reports the batch folder by part and by stage.

## 6. Privacy and limits

* Media stays on this machine. With `asr.backend: openai` the audio goes to OpenAI; with the `claude` planner
  the transcript text goes to Anthropic. Nothing else leaves the machine.
* F0 is one machine, one process (threads). Remote workers, variant compare / cherry-pick, a web board and
  phone review are F1 / F2 (see the design notes).

## 8. v0.2: clients, segment planning, review edits, delivery, metrics

**Clients** (`clients.py`). `client init|show|update|list --client C [--set JSON]`; `C` = a folder or a slug under
`$VSTUDIO_CLIENTS` (default `$VSTUDIO_HOME/clients`, `~/.config/vstudio/clients`). `client.yaml`: `name, style,
platforms, tags, glossary [{wrong, right, source, batch, job}], fillers {extra, keep}, brand {accent, highlight,
ink, ground}, cover_style frame|collage|face|text, cleanup_profile, confirm_policy, language, asr_prompt, delivery
{cleanup_days 0 = never, per_day, times}, notes, crm {history [{stage, at}], revenue [{at, amount}], posts, price_next}`.
`effective` = persona-derived defaults <- client.yaml. `update` also takes `glossary_add`, `glossary_remove`,
`tags_add`. A batch with `client:` gets, at plan time, the client's platforms / cleanup profile / confirm policy /
asr prompt as defaults (the spec wins), its glossary appended to `subtitles.term_fixes` (in the stage keys) and
`client.persona.yaml` (persona + brand, fillers, tags, term fixes) which every `run` activates
(`VSTUDIO_PERSONA`). Planned batches are registered in `$VSTUDIO_HOME/batches.json` (+ the client's
`batches.json`) for `metrics --client / --all` and `cleanup-sources`.

**plan-segments** (`segplan.py`). `--source F [--transcript T] [--client C] [--count N] [--min S --max S]
[--platforms a,b] [--provider auto|claude|openai|<any vstudio.llm provider>|none] [--model M] [--out DIR]` -> `segments.draft.yaml` (a
segments.yaml: `source:` + `transcript:` header, rows `{id, start, end, title, chapter, hook {start, end, text},
hook_candidates, notes, tags, why, risk, score}`) + `plan.json`. The transcript comes from `--transcript` or
`vstudio.asr` and is stored in the shared per-source cache (`transcripts.py`, keyed by the source's content hash),
which the batch `asr` stage reads - one whisper run per recording. Sentences from pauses / punctuation; edges on
word boundaries (`cleanup.snap_range`). Providers: `none` (rule-based: TextTiling topic shifts + long pauses ->
chapters; windows of whole sentences in [min, max] scored on tf-idf keyword density, self-containedness - no opening
connective / back-reference, complete ending, no topic shift inside, not followed by its own conclusion - filler
ratio and speech share; extractive titles / hooks / notes), `claude` (anthropic SDK, claude-opus-5-5, only with
ANTHROPIC_API_KEY; `auto` picks it unless a `segment_plan` llm route is configured), `openai` (named explicitly,
OPENAI_API_KEY, gpt-4.1), any other `vstudio.llm` provider (local servers, claude-code / codex, presets; checked
before planning; references/PROVIDERS.md). The LLM gets numbered
sentences and answers sentence-index ranges; too few / overlapping / invalid picks are filled from the rule-based
ranking; titles are checked against `publish.title_max` of every target platform (小红书 counts latin as 0.5) and
shortened when over; hook text is always the transcript of the hook range. Measured on a 72-min lecture against a
hand-made 24-segment plan (count 24, 45-160 s): openai gpt-4.1 covered 71 % of the hand segments by at least half,
time recall 0.73 / precision 0.67, 2 of 24 ranges identical, $0.09, 27 s; the rule-based planner 0.48 / 0.56
(random placement of the same lengths: 0.46 / 0.54), titles noisy - use it offline, review every row.

**Review edits** (`edits.py`). `job edit --batch B --job J --op caption --cue I --text T [--reasr] | trim --start A
--end B | cut --start A --end B [--why TEXT] | notes --set "a|b|c" | hook --pick K | cover --t S --text T | copy
--title --body --tags a,b | undo` -> `{ok, faithful, reason, reason_code, heard, rerun, pending, glossary_added,
undone, adopted, value, warnings}`. Each edit changes the job params (kept in the `edits` table, re-applied by a
later `plan`) and reports the stages whose input key changes (`rerun`; `pending` accumulates until `job rerun`).
Caption: accepted when `proofread.faithful` passes against the cue, the ASR text under it or the verify re-hearing
(sound-alike swaps only); otherwise the cue's window of the composed cut is re-heard (`edits.rehear_text`: the
batch transcriber / `vstudio.asr`, backend `asr.rehear_backend` > `asr.backend`) and the text is accepted when it
says what was heard (`matched: "reasr"`; normalized similarity >= 0.9, no added phrase). `--reasr` skips the
sound-alike check: the re-hearing decides. A refusal is `{ok: false, faithful: false, reason: "<a sentence>",
reason_code: empty-text | not-faithful | differs-from-audio | rehear-failed | rehear-unavailable, heard: "<re-heard
text>" | null}`. Stored as `caption_overrides [{i, from, to, asr, t, src}]` (the ASR text under the cue and its
output / source time, so the edit still lands after a re-proofread or re-cut: by index, text, ASR text, a cue
holding `from`, or time; one that cannot be placed is logged, listed in the export output `caption_overrides
{applied, missed}`, `job show` `edit.caption_overrides_missed` and a QC warning `caption-edit-missed`), applied at
export; proofread never touches the cues they cover. The fixed spans go to the client glossary (undo removes them)
- not a span that only reverts a proofread guess, nor a re-heard rewrite that is no sound-alike. Trim: source
seconds snapped to word edges. Cut: an inner cut inside the job's range, snapped to whole words (start -> a word
start, end -> a word end, never splitting one), appended to the row's `cuts` `[a, b, why]` (`value {cut, words,
cuts, kept_s}`; re-runs cleanup and everything after; `undo` removes it). Notes: the 记笔记 panel lines (`|`
separated; `""` clears it) - only the panel render (export) and what follows re-run, never proofread / captions /
cleanup. Hook: `hook_candidates` / `hooks` index, -1 = none. Cover: output seconds ->
source (`cover_shot`, longform-split) or a frame + text card (other recipes); text `a|b` = two lines. Copy: title
length checked per platform; the published `post.md` files are rewritten in place, stage keys keep the planned
copy (`_copy_orig`), only QC re-runs. A reviewed job whose keys drifted since its run (engine update, learned
policy) has those outputs adopted (`adopted`), so an edit never silently re-cuts. `job rerun --batch B --job J
[--json-events]` re-runs exactly the stale stages and puts the job back for review; the batch state is left as it
was. longform-split keeps the caption-free vertical masters in `jobs/<id>/export.masters/` (keyed by everything they
depend on) and re-exports with `make_vertical.py --reuse-masters`: on the 72-min lecture batch a caption edit of
one job re-burned 4 platform exports in 57 s (the first export took 175 s).

**Deliver** (`deliver.py`). `deliver --batch B [--client C] [--zip] [--cleanup-days N] [--out DIR]` packages first
when needed, then `<batch>/delivery/<client>-<batch>-<date>/`: one folder per platform (小红书, 抖音, ...;
`NN_<title>.mp4` + `_封面.jpg`), `文案.md` (title / body / tags per post + the AI-content label reminder),
`排期表.csv`, `交付说明.md` (counts, duration, platforms, QC notes, cleanup date), `manifest.json` (sha256 + bytes of
every file, the package confirmation code, a delivery code; `deliver.verify_delivery`) and the zip. Recorded in the
store with the cleanup due date (default the client's `delivery.cleanup_days`, else 0 = never; always 0 for the own
workspace: no client / client `self`). `cleanup-sources [--batch B | --client C | --all]` is a dry run: the exact files
of deliveries past due + `confirm_code` (hash of that list); `--confirm-delete CODE` deletes exactly those (a stale
code deletes nothing). Never deleted: a file a registered batch that is not delivered / due still uses, and any source
outside the batch / project folder (reported in `outside`).

**Metrics + timing** (`metrics.py`). `timing --batch B --job J --event start|stop|add --what review [--seconds S]`
-> the `timing` table (review seconds = the stop events' active seconds, else stop - start). `metrics --batch B |
--client C | --all [--csv]` -> `{scope, summary {jobs, done, approved, review_s_total, review_s_median, rework_rate,
red_rate, cost_per_clip, deliveries, delivered_clips, turnaround_h, ...}, jobs [...], batches [...]}`; `--csv` adds
`columns`, `rows`, `csv` - the weekly pilot sheet (周, 线索数, 沟通数, 样片数, 确认试点数, 交付数, 回传数据数, 付费数, 收入(¥),
交付条数, 人审秒数中位数/条, 返工率, 质检红灯率, 每条成本($), 内容号播放中位数, 内容号收藏率, 内容号涨粉, 工作室号有效线索; funnel
columns from client.yaml `crm`, content columns left blank; W1 = the week of `$VSTUDIO_WEEK0`, default
2026-10-06). Without `--json`, `--csv` prints the CSV.

## 7. JSON API (desk app, scripts)

Every command a UI needs has a JSON form; paths are absolute; with `--json` stdout carries only the JSON document
(logs go to stderr).

| command | stdout |
|---|---|
| `plan SPEC --json` | `{ok, batch_dir, jobs, created, updated, unchanged, dropped}` |
| `run ... --json-events` | one JSON object per line: `run-start` {jobs, limits, total_stages, stages}, `stage-start` {job, stage, resource, attempt}, `stage-done` {job, stage, seconds, cached, cost_usd}, `stage-retry`, `stage-fail` {error}, `job-done` {state, qc, reasons}, `progress` {done_stages, total_stages, jobs_done, jobs_total}, `pause` {reason}, `log` {msg}, `run-end` {status, exit_code}; every event has `event` and `ts`. The process's own fd 1 is pointed at stderr, so stage code / child processes can never corrupt the stream |
| `review --json` | `{page, decisions_needed, jobs, red, sampled, confirm_jobs, confirm_edits, items: [...]}`; items as on the review page with absolute `sheet` / `snippet` / `files`, plus `exports` and QC `suggestions` |
| `review --apply decisions.json --json` | `{ok, approved, rejected, replied, bulk, learned, skipped: [{job, why}], jobs}` (also with `--confirm-kinds a,b` / `--accept-policy`, limited by `--jobs a,b`) |
| `job ID --json [--no-words]` | `{job, recipe, stages, events, cleanup {reply, parts [{part, ranges, stats, edits [{id, t0, t1, kind, text, action, reason, cut}]}], row_cuts, edges, hook_edge}, transcript [{range, text, words [{w, t, te, cut}]}], captions {cues, changes, rejected, warnings, low_confidence, fillers_left, filler_edges}, verify, qc {status, reasons, warnings, checks, suggestions}, media {final, exports, length_fit, sheet, snippet}}` - `cut` is the effective state under the job's current cleanup reply |
| `package --json` | `{dir, code, items, jobs, manifest, manifest_data, verify}` |
| `verify-manifest MANIFEST` | `{ok, code, stored, items, reason}` (exit 1 on a mismatch) |
| `recipes --json` | `{recipes: [{name, label, description, inputs: [{key, label, kind file|dir|text|rects|rect, required, accept, help}], row_keys, stages: [{name, deps, shared, resource}]}], capabilities: [plan-segments, client, job-edit, job-rerun, deliver, metrics, timing, ...]}` |
| `plan-segments ... --json` | `{provider, model, duration, draft, transcript, segments: [{id, start, end, title, chapter, hook {start, end, text}, hook_candidates, notes, tags, why, risk, score}], chapters, words: [{w, t, te}], cost_usd, warnings}` (exit 5: provider unavailable) |
| `client init/show/update --client C [--set JSON] --json` | `{ok, dir, path, config, effective, batches}` |
| `job edit ... --json` | `{ok, op, faithful, reason, reason_code, heard, rerun, pending, glossary_added, undone, adopted, value, warnings}` (exit 1 when refused; `reason_code` / `heard` set on caption refusals; ops caption, trim, cut, notes, hook, cover, copy, undo) |
| `job rerun --job J [--json / --json-events]` | `{ok, job, state, qc, stages, seconds}` / the `run` events + `rerun-done` |
| `job show ID --json` (or `job ID`) | as `job` below, plus `edit {range, hook, hook_pick, hook_candidates, cover, copy, caption_overrides, caption_overrides_missed, history, pending, review_s}` |
| `deliver ... --json` | `{ok, dir, zip, items, jobs, duration_s, code, package_code, manifest, manifest_data, cleanup_on}` |
| `metrics ... --json [--csv]` | `{scope, summary, jobs, batches, deliveries? , columns?, rows?, csv?}` |
| `timing ... --json` | `{ok, job, event, what, seconds, total_s, review_s}` |
| `status --json`, `estimate --json` | as before |

In Python: `from vstudio.batch import verify_manifest` (also `vstudio.batch.package.verify_manifest`) and
`vstudio.batch.api` (`recipes()`, `review_items(dir)`, `job_detail(dir, id)`).
