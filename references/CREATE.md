# Create (创作): series studio engine

`lib/vstudio/create/` plans and makes short series from one sentence: series ads, product spots, interviews / street
Q&A, talk-show bits, comedy sketches, and recordings of yourself. No anime / micro-drama formats. The desk's Create
page (behind `Settings.createPage`) is a UI over this package; everything also works from the CLI.

```
python -m vstudio.create formats --json
python -m vstudio.create plan --prompt "5-episode series ad for my matcha brand, 30 s, Chinese + English" --json
python -m vstudio.create series new --draft-json '<plan draft>' --json
python -m vstudio.create episodes add SID --ideas i1,i2 --json          # scripts + storyboard + free frames
python -m vstudio.create board show EID --json                          # shots, routes, options, estimate
python -m vstudio.create board set EID --shot 07 --source cloud:minimax/MiniMax-Hailuo-02
python -m vstudio.create run EID --stage animatic --json                # free
python -m vstudio.create estimate EID --stage finals --json             # -> id + confirm_code + max_cny
python -m vstudio.create run EID --stage finals --estimate ID --confirm CODE --max-cny N --json   # PAID
python -m vstudio.create takes pick EID --shot 07 --take u07_v2.mp4
python -m vstudio.create handoff EID --languages zh,en,fr --json        # -> a normal work folder (editor, calendar)
python -m vstudio.create record ingest DIR --target project:talkinghead --json
```
Global flags: `--home DIR` (another store root), `--fake` (fake services, no model calls - tests and demos).
Errors are `{"error": {"code": "create.<code>", "params": {...}}}` with exit code 2 (codes: `create/i18n.py`).

## Ladder (cheap first)

| Stage | Cost | What |
|---|---|---|
| stills | free | storyboard frames (placeholder sketches today; a local image model later) |
| animatic | free | frames + timing as a video |
| drafts | free | local draft video (phase 2, second flag `VSTUDIO_CREATE_LOCAL=1`; the MVP only detects) |
| finals | paid | each shot from its routed service (Kling MCP, MiniMax Hailuo API, Veo API, Seedance via Ark) or 即梦 assisted |
| assemble | free | ai-video `assemble.py` (text cards made in post), then the hand-off |

## Spend gate (never relaxed)

- A paid run needs an estimate id, its 8-hex confirm code (15 min), and `--max-cny` covering the estimate's maximum
  (subtotal + 30 % retry allowance). The plan is rebuilt at run time: any change (a shot's service, a price table
  update) refuses with `create.plan-changed`.
- Refusals before any submit: series budget, monthly cap (`$VSTUDIO_HOME/create/spend-month.json`), unknown prices
  (unless allowed), Kling credits lower than needed, a service not connected, a service quoting > 5 % above the
  estimate.
- Hardest shots first; when 2 of the first 3 hard shots fail, the run pauses (`create.hard-shots-failed`).
- `submit` is called once per unit, ever. A timeout after the request left = `unknown-charge` (ledger row + an alert);
  a retry is a new estimate + confirm for that shot. Polling / downloading may retry.
- Every submit is appended to `series/<sid>/spend.jsonl` and the month counter before polling starts; task ids go to
  `work/ai/state.json` (generate.py's format) at once.
- Keys only from the environment (the desk puts them there from the OS keychain): `KLING_MCP_TOKEN`,
  `MINIMAX_API_KEY`, `GEMINI_API_KEY`, `ARK_API_KEY`. Nothing secret is written to any Create file (the store refuses).
- 即梦 / Hailuo / Kling consumer web apps are never automated: Create writes the prompts, the creator presses Generate
  on the site and adds the downloads (`takes import`).

## Data (`schema_version: 1`, human-readable)

```
$VSTUDIO_HOME/series/<sid>/series.yaml       normal series file; Create fields under spec.create
$VSTUDIO_HOME/series/<sid>/bible.yaml        engine, beats, cast, rules, languages, aspect, length_s
$VSTUDIO_HOME/series/<sid>/ideas.yaml        [{id, title, logline, est_cny, picked, episode?}]
$VSTUDIO_HOME/series/<sid>/spend.jsonl       append-only ledger
$VSTUDIO_HOME/series/<sid>/episodes/<eid>/create.yaml   script, shots, routes, ladder, estimates, takes, picks, run
$VSTUDIO_HOME/series/<sid>/episodes/<eid>/work/ai/      ai-video project.yaml, takes/, state.json, stills/, sheets/
$VSTUDIO_HOME/series/<sid>/delivered/<eid>/  the hand-off work folder (final/<clip>.mp4, .srt per language, post.md)
$VSTUDIO_HOME/recordings/<ts>-<slug>/        recorder sessions (session.json, camera.webm, mic.webm, takes.json)
```

## Prices

`create/rates.json` (versioned; `verified: false` = from docs or observed in-app, re-check before relying on it).
Minimum clip lengths are billed: Kling ≥ 5 s, Hailuo 6 / 10 s, Veo 4 / 6 / 8 s. The service's own price shown at
submit time wins.

## Local models (offered only when their licence allows commercial use)

| Use | Model | Licence | Offered |
|---|---|---|---|
| Draft video | LTX-2 distilled | LTX-2 Community (free below $10M revenue) | yes, after the revenue tick |
| Draft video | Wan 2.2 TI2V-5B | Apache-2.0 | NVIDIA PC only |
| Draft video | HunyuanVideo 1.5 | Tencent community (not EU/UK/KR) | hidden |
| Stills | Z-Image-Turbo, FLUX.1 schnell | Apache-2.0 | yes |
| Stills | FLUX.1 dev, Qwen-Image | non-commercial | never |
| TTS | Qwen3-TTS, CosyVoice, Kokoro | Apache-2.0 | yes |
| TTS | F5-TTS weights, Fish / OpenAudio | non-commercial | never |
| Lip-sync | Wav2Lip | non-commercial | never |
| Denoise | ffmpeg afftdn + loudnorm | ffmpeg (LGPL build) | MVP studio sound |

No model weights or GPL / non-commercial code are vendored in this repository.
