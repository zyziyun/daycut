# Intake: say what you want, drop the materials (`python -m vstudio.intake`)

The Reelfold desktop app's "new batch" form asked for a recipe, a segments file and budgets. Intake replaces it: the creator
describes the job in plain language and drops any mix of files and folders (video, audio, photos, pdf / docx /
pptx / md / srt). Intake inventories the materials, picks one or more recipes (mixed plans are fine), shows an
editable **plan**, and creates the projects (`vstudio.project`, references/PROJECTS.md) ready for a pilot run.

```
materials + "把后面对于自媒体的思考单独剪出来发小红书"
  -> analyze (inventory, cached)  -> plan (model or rules; validated)  -> [revise "每条 60 秒内"]*  -> apply -> projects (+ series)
```

Code: `lib/vstudio/intake/` (inventory, docs, rules, plan, estimate, apply, cli). Plan schema:
`lib/vstudio/intake/plan.schema.json` (`python -m vstudio.intake schema --json`).

## 1. Commands (run from `lib/` or with `PYTHONPATH=$VSTUDIO/lib`; every command takes `--json`)

| command | what |
|---|---|
| `analyze --inputs PATH... [--asr off\|sample\|full] [--out analysis.json] [--full]` | the material summary (compact: no paths, short excerpts) + content hashes; `--out` keeps the full analysis |
| `plan --prompt "..." --inputs PATH... [--client C] [--provider P] [--asr auto] [--auto hook,cover] [--out plan.json]` | the plan (section 3); `--analysis analysis.json` instead of `--inputs` |
| `revise --plan plan.json --prompt "只要小红书" [--in-place \| --out new.json]` | the plan updated from a follow-up instruction; the history is kept in `revisions` |
| `apply --plan plan.json [--out DIR] [--dry-run] [--run]` | creates the project folders (a series when the plan has several), returns ids, dirs and the pilot run commands; `--run` starts each pilot; exit 5 on an invalid plan |
| `schema` | the plan JSON Schema |

## 2. Inventory (`analyze`)

Folders are walked recursively (hidden files, VCS / dependency / `state` / `exports` folders and symlinks
skipped; 2000 files, depth 8). Inputs are read-only: nothing is written next to them (ASR samples are decoded to a
temp folder; the cache lives under `$VSTUDIO_CACHE/intake/`, keyed by a content hash + the analyzer version, so a
second analyze / plan / revise is instant).

| kind | facts |
|---|---|
| video | duration, size, orientation, fps, HDR, audio; speech from a short ASR sample (one 20 s window, three for files over 75 s; `--asr full` = whole track, transcript cached); on 6 frames: faces per frame (`vstudio.face`), talking head, multi-person, screen share (low saturation + flat UI), burned-in captions (bright text with a dark outline concentrated in the lower / middle band, absent elsewhere); filename hints (zoom / meet / recording / 录屏 / final / 成片 / 课 / 培训). The first 40 videos get the heavy checks, the rest probe facts only |
| audio | duration, speech vs music |
| image | size, orientation, EXIF capture time, coarse GPS (1 decimal, about 10 km), faces on up to 12 images; a folder of photos / clips becomes one group (count, time span, faces share) |
| text | pdf (pypdf or PyMuPDF), docx (python-docx), pptx (python-pptx), md / txt / srt / vtt / ass / json: title, up to 12 headings, a 300-char excerpt, language, shape (`script` 剧本 with scenes + dialogue, `slides`, `outline`, `notes`, `article`, `subtitles`), episode count, URLs found (listed, never fetched). A missing extractor is a note, not an error |

Every material also gets a **role** (what the rule planner keys on): `call`, `lecture`, `screen-recording`,
`talking-head`, `finished-edit` (burned captions or a final export with speech), `footage`, `podcast-audio`,
`voice`, `music`, `photo`, `script`, `slides`, `doc`, `notes`, `subtitles`.

## 3. Plan

The routed model (task `intake` of `vstudio.llm`: `llm.tasks.intake` or `llm.default` in the persona / client;
e.g. `claude-code` = the creator's own Claude Code login; `--provider` overrides) gets the request, the compact
materials, the persona / client defaults, the recipe catalog (every manifest: inputs, item sources, params with
enums / defaults, platforms, checkpoints), the SKILL.md phrase table and, when the request selects content from a
recording ("剪出来", "截取", "有意思的部分", "单独发"), the time-coded transcript of that recording (`--asr auto`:
transcribed once, cached, for videos up to 45 min). The code then validates and completes the answer:

* recipe ids, input keys, input kinds / extensions, param names and values (each param's JSON Schema from the
  manifest), item keys: anything unknown or invalid is dropped or reset to the default and listed in `warnings`;
  a sub-project with an invented recipe or without its required input is dropped. **No recipe is ever invented.**
* params: recipe default < persona / client (`platforms`, body `speed`, `cleanup_profile`, `language`) < materials
  (a finished edit with burned captions -> talkinghead `captions: false`, gentle cleanup, 1.0x; a screen share ->
  longform `layout_mode: split`) < the model < what the request literally says (platforms, counts, "每条 60 秒内",
  "1.2 倍", 英文, 剪干净, 遮脸 / 不遮脸, 卡点). `param_sources` says where each value came from.
* platforms are mapped to the recipe's ids (`小红书` -> `xiaohongshu:full` for talkinghead, `xiaohongshu:vertical`
  for longform slices).
* focus rows: ranges are clamped to the media; a focus sub-project without rows gets them from the rule matcher
  (focus terms + position words 前面 / 中间 / 后面 over the transcript); if no transcript exists yet, `apply`
  transcribes and resolves it.
* checkpoints from the manifest (`needs_you`: `auto: never` ones, budget / consent always, the rest unless listed in
  `--auto`), estimates (section 4), a template Chinese summary when the model gave none.

When no model is routed, the call fails (expired login, network) or nothing survives validation, the **rule
planner** builds the plan: the phrase table per clause (`另外` / `以及` / `；` split the request), material roles
(a call -> call-clips, a lecture -> longform-to-short, photos + clips -> photo-story or vlog, a 剧本 -> ai-video, a
PDF -> explainer topics from its headings, notes -> preproduction), negations ("不要讲解视频") and the same
parameter extraction. `planner.fallback: true` + `planner.reason` say so.

```jsonc
{
  "version": 1, "kind": "vstudio.intake.plan", "id": "20261006-124604-x", "prompt": "...", "client": null,
  "planner": {"provider": "codex", "model": "...", "route": "argument", "fallback": false, "cost_usd": 0, "seconds": 26},
  "analysis": {"digest": "...", "inputs": ["/abs/..."], "totals": {...}, "asr": "sample"},
  "materials": [{"id": "f1", "path": "/abs/x.mp4", "kind": "video", "role": "finished-edit", "duration": 653.2,
                 "burned_captions": true, "transcript": "<cache>/....transcript.json"}],
  "projects": [{
    "id": "p1", "recipe": "talkinghead", "recipe_label": "口播精剪", "name": "...", "why": "...", "materials": ["f1"],
    "inputs": {"video": ["/abs/x.mp4"]},                       // project-level inputs (abs paths or text)
    "items": {"method": "focus",                                // per-file | single | planner | focus | episodes | list
              "count": 3, "focus": "后面关于自媒体的思考；中间的感悟",
              "rows": [{"id": "s01", "inputs": {"video": "/abs/x.mp4"}, "params": {"range": [535.0, 610.0], "title": "..."},
                        "why": "..."}]},
    "params": {"platforms": ["xiaohongshu:full"], "captions": false, "speed": 1.0, "cleanup_profile": "gentle"},
    "param_sources": {"platforms": "prompt", "captions": "material", "speed": "planner"},
    "checkpoints": [{"id": "filler", "kind": "filler-confirm", "label": "确认去 filler", "needs_you": true, "auto": "default"}],
    "estimate": {"machine_min": 3.7, "wall_min": 1.8, "storage_mb": 383, "api_usd": 0.0, "credits": null,
                 "measured": true, "paid_steps": [], "basis": {"source_s": 653, "output_s": 222, "items": 3, "platforms": 1}},
    "outputs": {"platforms": ["xiaohongshu:full"], "videos": 3, "workflow_md": "workflows/talkinghead/WORKFLOW.md"}
  }],
  "series": null,                                               // {id, name} when there are several sub-projects
  "questions": [{"id": "q1", "project": "p1", "text": "...", "options": [...], "default": "..."}],
  "risks": ["..."], "warnings": ["..."],
  "estimate": {"machine_min": ..., "wall_min": ..., "api_usd": ..., "paid_steps": [...]},
  "run": {"pilot": 1, "auto": []},
  "summary_zh": "一段中文说明：做什么、用什么、关键设置、需要你确认什么、时间 / 费用",
  "revisions": [{"prompt": "每条 60 秒内", "at": "...", "planner": {...}, "changes": [...]}]
}
```

The plan is plain JSON: the app (or the creator) may edit params, rows, ranges, names or drop a sub-project before
`apply`; `apply` validates it again.

Questions are only for what can't be defaulted and changes the result (whose face to hide, narration vs music);
everything a checkpoint already covers (segment approval, filler cuts, cover, publish review, budget) is not asked
up front.

## 4. Estimates

Speech recipes: the `vstudio.batch` bench table (this machine's measured seconds per unit when a batch has run
here - `measured: true` - else the built-in guesses) over the stages probe / extract / asr / (geometry) / cleanup /
apply / compose / export x platforms / verify / qc / preview, with source seconds and planned output seconds
(rows' ranges, planner count x the mean of min_s / max_s, or the files' durations). Render recipes: seconds per
output second (explainer 6, promo 4, photo-story 2, vlog 1.5). API cost: 0 when the LLM tasks route to a
subscription CLI, a local server or none; else about $0.01 per source minute; OpenAI TTS about $0.015 per narrated
minute; AIGC credits are quoted at the ai-video budget checkpoint (never auto). Wall time assumes two lanes.

## 5. Revise

`revise` sends the current plan + the instruction to the model ("keep what the instruction does not change") and
validates the result like a new plan. Without a model, rules handle the common follow-ups: `只要 / 只发 <平台>`
(replace) or a platform alone (add), `每条 N 秒内` (max_s; rows longer than that get a note), `N 条`, `不要 <配方词>`
(drop those sub-projects), `1.2 倍` / `原速`, `英文`, `剪干净 / 轻一点`, `遮脸 / 不遮脸`, `加 / 不要 hook`, `横屏 / 竖屏`,
`卡点 / 舒缓`. An instruction nothing understood leaves the plan unchanged with a warning.

## 6. Apply

One sub-project -> `<out>/<NN>-<name>/` via `Project.create` (recipe, params, client, auto policy; rows become
items with their `range` / inputs; `per-file` -> one item per file; `episodes` -> N episodes; planner recipes
without rows keep their segment planner, run at the first `run` and approved at the `segments` checkpoint).
Several sub-projects share a **series** (`intake-...`; the first recipe is the series recipe, each project names its
own) so the desk shows them as one job. `<out>/intake.json` = the plan as applied + the project dirs. Default
`<out>`: `$VSTUDIO_HOME/projects/<plan id>`. Next step per project: `python -m vstudio.project run --dir D --pilot 1
--json-events` (exit 4 = the pilot waits for review, 7 = a checkpoint needs the creator).

## 7. Validated

Golden tests (`tests/test_intake.py`, mocked model + rule planner, no media work): 12 request x material mixes -
lesson -> 20 vertical slices, 口播 -> cleaned 小红书 short, finished horizontal edit with burned captions -> focus
ranges in its later part, photos + clips -> 文艺片, PDF -> 5 explainer shorts, 剧本 -> 6 AI episodes, Zoom podcast
-> clips with face masks + consent, a mixed course folder -> longform + explainer + 口播稿 (series), DJI clips ->
卡点 vlog for 抖音, a finished export -> polish, screen recordings -> course for B站, notes -> 3 scripts; plus revise
(rules and model), apply (projects, series, ranged items), the inventory on synthetic media / documents, the CLI.
A real run (a 10.9 min finished horizontal 口播 with burned captions, "把后面对于自媒体的思考，以及中间的一些感悟剪出来，单独发小红书",
provider codex): role finished-edit detected (talking head, burned captions, final export), whole track transcribed
for the focus, plan = talkinghead x 3 focus rows (301-363 s and 450-535 s: 副业 / 跨行业 感悟; 535-610 s: 自媒体), captions
kept (`captions: false`), gentle cleanup, 1.0x, `xiaohongshu:full`, about 2 min wall, $0 (subscription CLI), in
about 70 s end to end on first analysis.
