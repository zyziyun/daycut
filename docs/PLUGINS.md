# Plugins

Reelfold is the batch orchestrator for video work. It plans the series, keeps the storyboard, prices every shot,
runs the work in parallel lanes, checks what comes back and puts it in front of you for review. The tools that make
the pictures, and the agents that drive those tools, plug in.

Plugin API version: **1** (`vstudio.plugins.contract.API_VERSION`). Engine code: `lib/vstudio/plugins/`.

## Three kinds

| Kind | What it does | Built in |
|---|---|---|
| `importer` | Brings an external board or project in as Create shots | HyperFrames projects, shot lists (JSON / CSV / TSV / Markdown), editor timelines (CMX 3600 EDL, OpenTimelineIO, Premiere / Final Cut 7 XML, Final Cut Pro X `.fcpxml`) |
| `shot-provider` | Makes a shot | Kling (MCP), MiniMax Hailuo, Veo, Seedance (Ark), 即梦 (assisted), local MLX / ComfyUI, HyperFrames render |
| `agent-runner` | Hands one shot's job folder to an external agent or command | Claude Code (`claude -p`), Codex (`codex exec`), any command |

## Where plugins come from

1. **Built in**: `lib/vstudio/plugins/builtin/manifests/*.yaml`. On by default.
2. **Folders**: `$VSTUDIO_HOME/plugins/<name>/plugin.yaml` (`~/.config/vstudio/plugins/...` by default), plus every
   directory listed in `VSTUDIO_PLUGINS_PATH` (an `os.pathsep`-separated list), each holding `<name>/plugin.yaml`.
3. **Python packages**: an entry point in the group `reelfold.plugins` whose object is a manifest dict, a list of
   them, or a function returning either.

Third-party plugins (folders and packages) **start turned off**. You turn them on in Settings › Video generation ›
Plugins, or with `python -m vstudio.create plugins enable <kind>:<id>`. Nothing from a plugin is imported or run
until it is on and used. A broken manifest is listed with its error and never loaded. If two plugins share the
same kind and id, the first one found wins and the other is listed as a duplicate.

On / off state and per-plugin settings: `$VSTUDIO_HOME/plugins.json`.

## The manifest (`plugin.yaml`)

```yaml
id: my-renderer                 # [a-z][a-z0-9-]{1,40}, unique per kind
kind: shot-provider             # importer | shot-provider | agent-runner
name: {en: My renderer, zh: 我的渲染器}
version: 1.2.0
api: 1                          # the plugin API it was written for (must be <= Reelfold's)
entry: my_renderer:Renderer     # Python: module:attribute (a folder plugin imports from its own folder)
# command: [./run, "{job_dir}"] # importer / agent-runner only: a plain command instead of Python
description: {en: "...", zh: "..."}
homepage: https://example.com
permissions: [read-files, write-job, "exec:my-renderer", network]   # what it may do, shown to the user
cost:
  kind: local                   # free | local | subscription | paid
  notes: {en: "Runs on your GPU"}
concurrency: 2                  # default parallel lanes
timeout_s: 1800                 # agent runners / renders: per shot
exts: [.json]                   # importers: file types it reads (a hint)
rates:                          # paid shot providers: the price card, same shape as create/rates.json
  my-model: {label: My model, unit: second, cny_per_s: 1.2, min_clip_s: 2, max_clip_s: 10, step_s: 1}
```

Permissions: `read-files` (reads what you import), `write-job` (writes inside its job folder), `exec:<cli>` (runs
that program), `network`, `spend` (can cost money). A `paid` plugin must declare `spend`.

## Money: the spend gate

Nothing paid ever runs without the spend gate (estimate, confirm code, max amount, series budget, monthly cap).

* A **paid shot provider** (`cost.kind: paid`, kind `cloud` / `mcp` in its `info`) is used with the source
  `cloud:<id>/<model>`. It goes through the finals run exactly like Kling: the estimate prices it from the
  manifest's `rates`, you confirm the code, `submit` is called once and never retried.
* A **paid agent runner or render provider** is refused by `make` (`create.plugin.paid-needs-gate`).
* `subscription` (your own Claude Code, Codex or 即梦 plan) and `local` / `free` plugins run without a charge from
  Reelfold; Settings shows which is which.

## Importers

Python: subclass `vstudio.plugins.contract.Importer`.

```python
from vstudio.plugins.contract import Importer

class MyBoards(Importer):
    id = "my-boards"
    exts = (".myboard",)

    def sniff(self, path):           # 0..1: how sure you are that you can read path (a file or a folder)
        return 0.9 if str(path).endswith(".myboard") else 0.0

    def load(self, path):            # -> a board dict
        return {"title": "Spot", "aspect": "9:16", "shots": [{"dur": 2.5, "action": "Close-up of the cup",
                                                              "voiceover": "Morning."}]}
```

Or a command: `command: [./import, "{path}"]` printing the board as JSON on stdout (60 s limit, cwd = the plugin
folder).

**The board** (`reelfold.board/1`, `vstudio.plugins.board`):

```text
{title, aspect ("9:16" or "1080x1920"), fps?, message?, format? (a Create format id),
 shots: [{dur (seconds, or "3s" / "0:03"), title?, text? (on-screen text), action? (what we see), voiceover?,
          camera?, notes?, transition?, faces? [cast ids], source? (e.g. plugin:hyperframes, agent:codex),
          ref? {kind, ...} (what a provider needs to make it)}]}
```

Reelfold picks the enabled importer with the highest `sniff` score (falling back to the next one if it fails),
cleans the board up and either creates a new series + episode from it (Create home › Import board) or replaces an
episode's storyboard (Storyboard › Import board; takes already made are kept aside, not re-attached to new shots).

### HyperFrames

A HyperFrames project folder (`hyperframes.json`, `index.html`, usually `STORYBOARD.md` and `BRIEF.md`):

* every `## Frame N — Title` of `STORYBOARD.md` becomes a shot: the built clip's `data-duration` from `index.html`
  (else the frame's `duration`), `scene` as the action, `voiceover`, `transition_in`, the narrative and any extra
  keys as notes, and `ref: {kind: hyperframes, project, src, frame, status}`;
* without a storyboard, the root composition's clips (`data-composition-src` / `data-duration`) become the shots;
* the title comes from `BRIEF.md` / `meta.json` / the folder name, the aspect from the storyboard `format` or the
  root composition's size;
* a frame whose composition file exists is routed to `plugin:hyperframes`; the others follow the series' policy.

The **HyperFrames render** provider (kind `render`, free) renders one frame with the project's own CLI:
`hyperframes render --composition <src> --quality draft --output <job>/outputs/<shot>.mp4`, using
`node_modules/.bin/hyperframes` or a `hyperframes` on `PATH`, never an `npx` download. Without a CLI the shot
waits for you (`create.plugin.external`): render it in HyperFrames and drop the file on the shot.

## Shot providers

The Create provider protocol (`vstudio.create.providers.base.Provider`):

```text
info      {id, label {en, zh, fr}, kind cloud | mcp | manual | local | render, needs [env vars], models,
           concurrency}
status()  {ready, code, params}            no network; test() may make one cheap read-only call
submit(job) -> task id                     PAID: only after the spend gate, never retried
poll(task_id) -> {status pending | done | failed, urls, raw}
download(url, path)                        (= fetch)
```

The estimate comes from `rates` (`costs.price_job`). Built-ins register through the same manifests; turning one
off in Settings removes it from routing.

`render` providers are free local renderers (HyperFrames; Remotion or manim later). Instead of submit / poll they
implement `render(job) -> [files]` and are run by `make` in lanes (below). Use them with the source
`plugin:<id>`.

## Agent runners and the job-folder protocol

Route a shot to `agent:<runner>` (the shot's source popover, a shot list's `source` column, or
`python -m vstudio.create board set EID --shot 07 --source agent:claude-code`), then **Make** (the storyboard's
primary button, or `python -m vstudio.create make EID [--only 01,02] [--lanes N]`).

Each shot gets a job folder, `<episode>/work/ai/jobs/<shot>/` (`reelfold.agent-job/1`):

```text
job.json      {schema, id, episode, series, shot, runner, kind, spec {dur, aspect, action, camera, lines, notes,
               faces, ref}, want, deadline_s, created}
brief.md      the shot in plain words: what to make, length, aspect, the series rules (the agent's prompt)
inputs/       still.jpg (the storyboard frame), bible.yaml (cast, rules), ref.json (e.g. the HyperFrames project)
outputs/      the agent writes the finished .mp4 / .mov / .webm or .png / .jpg here; optional result.json
              {files, notes}
status.json   {state, progress 0..1, message, heartbeat, pid, started, finished, exit_code, code, error}
log.txt       the runner's stdout + stderr
```

How a runner is run:

* cwd = the job folder; command runners get `brief.md` on stdin; environment `REELFOLD_JOB_DIR`,
  `REELFOLD_OUTPUTS`, `REELFOLD_STATUS`, `REELFOLD_SHOT`;
* its own process group: a stop or a timeout (`timeout_s`) ends the CLI and everything it started;
* Reelfold refreshes `heartbeat` every second while the process lives; the agent may write `progress` and
  `message` into `status.json` and they show on the storyboard;
* **QC gate**: the shot only counts if `outputs/` holds a playable video (ffprobe: a video stream, duration > 0)
  or an image. Otherwise it fails with `create.agent.qc-no-output`;
* what passes is copied into the episode's takes (`u<shot>_v<n>.mp4`): one take is picked at once, several go to
  "Pick takes";
* failures (with the last log line) and shots waiting for you appear in the Making view and the Inbox;
* **lanes**: shots run in parallel per runner, `min(manifest concurrency, your lanes setting or --lanes, Fleet's
  agent:<id> resource class, 8)`; different runners run side by side;
* **resume**: a shot already made by the same runner is not run again; failed, stopped or waiting ones are. Every
  new attempt starts with an empty `outputs/`. `python -m vstudio.create stop EID` stops every lane.

Python runners subclass `vstudio.plugins.contract.AgentRunner` and implement `command(job) -> argv` (and optionally
`env(job)`, `status()`); `stdin_brief = False` if the prompt is passed another way. A command runner needs no
Python:

```yaml
id: my-agent
kind: agent-runner
version: 0.1.0
api: 1
command: [./agent, "{job_dir}"]   # placeholders: {job_dir} {inputs} {outputs} {brief} {job_json} {shot} {episode}
permissions: [write-job, "exec:agent"]
cost: {kind: local}
concurrency: 3
timeout_s: 900
```

Built-in runners:

* **Claude Code**: `claude -p "<protocol prompt>" --output-format json --permission-mode acceptEdits --allowedTools
  Read,Write,Edit,Glob,Grep,Bash(hyperframes:*),Bash(./node_modules/.bin/hyperframes:*),Bash(ffmpeg:*),Bash(ffprobe:*)`
  (override with the setting `allowed_tools`; `model` too). Your own subscription: API keys are removed from its
  environment.
* **Codex**: `codex exec --sandbox workspace-write --skip-git-repo-check --cd <job folder> "<protocol prompt>"`.
* **Any command**: set its command line in Settings (`settings.command`, an argv list with the placeholders).

## Commands

```text
python -m vstudio.create plugins [--json]                        every plugin, on / off, status, errors
python -m vstudio.create plugins enable|disable <kind>:<id>
python -m vstudio.create plugins set agent-runner:shell --settings-json '{"command": ["mytool", "{job_dir}"]}'
python -m vstudio.create import PATH [--into EID] [--importer ID] [--format F] [--sniff]
python -m vstudio.create make EID [--only 01,02] [--lanes N]
```

Desk sidecar routes: `GET /api/create/plugins`, `POST /api/create/plugins/<kind>:<id> {enabled?, settings?}`,
`POST /api/create/import {path}` (job), `POST /api/create/import/sniff {path}`,
`POST /api/create/episodes/<eid>/import-board {path}` (job), `POST /api/create/episodes/<eid>/make {only?, lanes?}`
(job).

## Versioning

`api` is a single integer. Additions that old plugins can ignore (a new optional manifest key, a new board field)
keep the number; anything that would break a plugin written for version N bumps it to N + 1, and Reelfold keeps
loading version N plugins for at least one release after that.
