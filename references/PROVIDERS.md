# AI providers: API keys, self-hosted models, or no key at all

Every AI step of video-studio goes through one of three small registries, so each step can run on

- **any API provider** (Anthropic, OpenAI, DeepSeek, Qwen, Kimi, GLM, OpenRouter, Gemini, ElevenLabs),
- **self-hosted / local models** (Ollama, LM Studio, vLLM, llama.cpp server, local whisper, a whisper or TTS
  server on your own GPU box), or
- **no API key**, through a locally installed agent CLI that is already logged in with your own subscription
  (Claude Code, Codex).

| registry | module | used by |
|---|---|---|
| text LLM | `vstudio.llm.complete()` | segment planning (`plan-segments`), caption proofreading, the per-source glossary, the claude planner (sync mode) |
| speech recognition | `vstudio.asr.transcribe(backend=...)` | every transcript (talkinghead, batch, longform, call-clips, explainer, photo-story) |
| speech synthesis | `vstudio.tts.synth(engine=...)` | explainer narration, pronunciation drills, photo-story voice |

See what works on this machine (keys present, CLIs installed, local servers reachable; nothing is sent):

```bash
cd $VSTUDIO/lib
python3 -m vstudio.llm providers            # LLM + ASR + TTS tables and the current route of each task
python3 -m vstudio.llm providers --json
python3 -m vstudio.llm route                # task -> provider / model / where that came from
python3 -m vstudio.llm test --provider ollama --model llama3.2:1b    # one tiny JSON round-trip, no secrets printed
```

Every step also works with **no model at all** (`none`): the rule-based planner, term fixes + glossary-free
proofreading, local whisper and local / free TTS engines.

## 1. Choosing the provider (routing)

Put an `llm:` section in `persona.local.yaml` (yours, gitignored) or in a client's `client.yaml`
(`python -m vstudio.batch client update --client acme --set '{"llm": {...}}'`):

```yaml
llm:
  default: {provider: claude-code}              # string shorthand works too: default: claude-code
  tasks:                                        # segment_plan | proofread | glossary | copy | script | planner | intake | output_edit
    segment_plan: {provider: anthropic, model: claude-opus-5-5, effort: medium}
    proofread:    {provider: ollama, model: "qwen3:8b"}
    glossary:     {provider: openai-compatible, base_url: "http://gpu-box:8000/v1", api_key_env: GPU_BOX_KEY,
                   model: Qwen/Qwen3-32B}
    copy:         {provider: deepseek}
  prices: {"Qwen/Qwen3-32B": [0, 0]}            # USD per million tokens (input, output); overrides the table
```

Keys never go into these files: name the environment variable (`api_key_env`); `client.yaml` rejects
`api_key` / `token` fields.

Precedence (first match wins):

1. an explicit provider / model (`--provider ollama`, spec `proofread.provider: kimi`, `complete(provider=...)`);
   `auto` means "not given"
2. env `VSTUDIO_LLM_<TASK>_PROVIDER` / `VSTUDIO_LLM_<TASK>_MODEL` (e.g. `VSTUDIO_LLM_PROOFREAD_PROVIDER=ollama`;
   `VSTUDIO_LLM_<TASK>_FALLBACK=codex,ollama` gives it a fallback chain)
3. the desk's routes file `tasks.<task>` (env `VSTUDIO_LLM_ROUTES_FILE`, JSON `{default, tasks}`, re-read on every
   call), then the client's `llm.tasks.<task>`, then the persona's `llm.tasks.<task>`
4. env `VSTUDIO_LLM_PROVIDER` / `VSTUDIO_LLM_MODEL` (+ `VSTUDIO_LLM_FALLBACK`)
5. the desk's routes file `default`, then the client's `llm.default`, then the persona's `llm.default`
6. legacy `auto`: `anthropic` when `ANTHROPIC_API_KEY` is set, else `none`. Nothing paid, remote or
   subscription-backed is ever picked implicitly beyond that.

When a provider is named explicitly and the config has an entry for the same provider, that entry's model and
options are used. The glossary follows task `glossary` (falls back to the proofread provider when the spec names
one); the batch spec key `proofread.glossary_provider` overrides it.

## 2. LLM providers

| provider | kind | setup | default model | JSON |
|---|---|---|---|---|
| `anthropic` (alias `claude`) | API | `pip install anthropic`, `ANTHROPIC_API_KEY` | `claude-opus-5-5` | `output_config.format` for a schema, else instruction |
| `openai` | API | `pip install openai`, `OPENAI_API_KEY` | `gpt-4.1-mini` (plan-segments: `gpt-4.1`) | `response_format` json_object / json_schema |
| `deepseek` | API | `DEEPSEEK_API_KEY` | `deepseek-chat` | json_object |
| `qwen` | API | `DASHSCOPE_API_KEY` (DashScope compatible mode) | `qwen-plus` | json_object |
| `kimi` | API | `MOONSHOT_API_KEY` | `kimi-k2-0905-preview` | json_object |
| `glm` | API | `ZHIPUAI_API_KEY` | `glm-4.6` | json_object |
| `openrouter` | API | `OPENROUTER_API_KEY` | `openai/gpt-4.1-mini` | json_object |
| `gemini` (optional) | API | `pip install google-genai`, `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-2.5-flash` | `response_mime_type` |
| `ollama` | local | `ollama serve`; `ollama pull qwen3:8b` | `qwen3:8b` | json_object |
| `lmstudio` | local | LM Studio > Developer > Start server | (set `model`) | json_schema |
| `vllm` | local | `vllm serve <model>` (port 8000) | (set `model`) | json_object |
| `llamacpp` | local | `llama-server -m model.gguf` (port 8080) | (set `model`) | json_object |
| `openai-compatible` | any | `base_url` + optional `api_key_env` (or env `VSTUDIO_LLM_BASE_URL`, `VSTUDIO_LLM_API_KEY_ENV`) | (set `model`) | json_object |
| `claude-code` | subscription CLI | Claude Code installed and logged in (`claude`, then `/login`) | the CLI's default (`model: opus` / `sonnet` to pin) | `--json-schema` for a schema |
| `codex` | subscription CLI | Codex CLI installed and logged in with ChatGPT (`codex login`) | the CLI's default | `--output-schema` for a schema |
| `none` | - | nothing | - | callers use their rule-based path |

Preset base URLs (override with `base_url:` or env `VSTUDIO_<PRESET>_BASE_URL`, e.g. the international hosts
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`, `https://api.moonshot.ai/v1`,
`https://api.z.ai/api/paas/v4` with `api_key_env: ZAI_API_KEY`): DeepSeek `https://api.deepseek.com/v1`, Qwen
`https://dashscope.aliyuncs.com/compatible-mode/v1`, Kimi `https://api.moonshot.cn/v1`, GLM
`https://open.bigmodel.cn/api/paas/v4`, OpenRouter `https://openrouter.ai/api/v1`, Ollama
`http://localhost:11434/v1`, LM Studio `http://localhost:1234/v1`, vLLM `http://localhost:8000/v1`, llama.cpp
`http://localhost:8080/v1`. The default models of the presets are examples - providers rename models often; set
`model:` to what your account / server actually has (`python -m vstudio.llm providers` lists the models a local
server reports).

Notes per backend:

- **anthropic**: thinking is adaptive by default on Claude Opus 5.5 (no `budget_tokens` is ever sent; no
  assistant prefill). `effort` goes to `output_config.effort` (proofread uses `low`, the planner `medium`).
  The server-side refusal fallback (beta) is used when the installed SDK supports it; a refusal raises.
  The claude planner's **Message Batches** mode (`plan --planner claude` without `--sync`) is an Anthropic-only
  API and stays Anthropic-only; `--sync` goes through `vstudio.llm`.
- **openai / compatible**: Chat Completions. Reasoning models (`o*`, `gpt-5*`) get `max_completion_tokens` and no
  temperature. Small local models follow JSON instructions less reliably: the tolerant parser and the one repair
  retry catch most slips; the callers' own validators (proofread's audio-faithful check, plan-segments' range
  checks) reject the rest. 7-8B models are fine for `copy`; prefer 14B+ (or an API model) for `proofread`.
- **claude-code**: runs `claude -p --output-format json --tools "" --no-session-persistence --strict-mcp-config
  --system-prompt <system>` with the prompt on stdin, in an empty temp directory, with a timeout. No tools are
  available to it, nothing is written to your project, and `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_BASE_URL` are removed from its environment so it uses your own login (set `inherit_env: true` in the
  route to keep them). Errors such as an expired login are reported as-is: run `claude` and `/login` again.
- **codex**: runs `codex exec --json --sandbox read-only --skip-git-repo-check --cd <temp dir>
  --output-last-message <file> [--model M] [--output-schema F] -` (system + prompt on stdin), with
  `OPENAI_API_KEY` removed from its environment so it uses your ChatGPT login. The flags follow the Codex CLI's
  documented `exec` options; check `codex exec --help` on your machine if the CLI changed.
- Retries: rate limits, overload, 5xx and connection errors are retried twice with backoff; bad requests, auth
  errors, refusals and CLI timeouts are not. A broken JSON reply gets one repair round (the model sees its own
  reply and is asked for valid JSON); after that the caller gets `json=None` and falls back (proofread: glossary /
  term fixes only for that chunk; plan-segments: rule-based fill).

### Fallback chains

A route entry may name `fallback: [codex, ollama]`: when the routed provider fails (login expired, CLI missing,
outage), the next one runs. The result records it - `fallback_from` (the error texts) and
`fallback: {from, to, code, error, tried}` with `code` one of `auth-expired | not-logged-in | not-installed |
key-missing | rate-limited | timeout | failed` - and `output ai` / the intake planner pass it on (`routed`,
`fallback`, `provider_fallback`), so an app can say "Claude's login expired, Codex answered this time". An explicit
provider (`--provider`) never falls back.

### Login status and login commands

```bash
python3 -m vstudio.llm auth status --json         # every provider: state, account (email / plan), key present?, server up?
python3 -m vstudio.llm auth status --no-probe     # skip the tiny claude round-trip (faster, but cannot see expiry)
python3 -m vstudio.llm auth status --deep         # also a tiny codex round-trip
python3 -m vstudio.llm auth login --provider claude-code --json    # the command to run yourself (nothing is run)
python3 -m vstudio.llm auth logout --provider codex --json
```

States: `logged-in`, `expired`, `not-logged-in`, `not-installed` (CLIs); `configured`, `not-configured` (API keys:
only whether the variable is set, never its value); `ready`, `server-down`, `no-models` (local servers). Each row has
a `message` `{code, params, message, message_zh}`. claude-code is checked with `claude auth status --json` (plan,
email, auth method) **and** a one-line `claude -p` on the cheapest model, because `auth status` still says
`loggedIn: true` after the OAuth token expired (the round-trip then answers 401). codex uses `codex login status`.
Every CLI call (status, probe, the real work) runs with `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` /
`ANTHROPIC_BASE_URL` (claude) or `OPENAI_*` / `CODEX_API_KEY` (codex) removed from its environment. The CLIs are
found on `PATH`, then in `~/.local/bin`, `~/.claude/local`, `/opt/homebrew/bin`, `/usr/local/bin`, ... (env
`VSTUDIO_CLI_EXTRA_DIRS` replaces that list). `auth login` prints `claude auth login` / `codex login` (variants:
`--console`, `--sso`, `--device-auth`) and the variables to remove; the engine never sees a password or token.

### Subscription CLIs: your own local use

`claude-code` and `codex` reuse the plan you are logged into. They are meant for **your own local use** of this
tool. Subscription plans come with their own usage limits and terms; before using a subscription CLI to produce
paid work for clients (an agency pipeline, `deliver` packages, many batch jobs), check the provider's current
consumer / subscription terms and usage policies, and use an API key (or a self-hosted model) where the terms call
for it. `python -m vstudio.llm providers` never sends anything through them; `test` sends one tiny prompt.

## 3. Speech recognition (ASR)

| backend | kind | setup |
|---|---|---|
| `mlx` | local (Apple Silicon) | `pip install mlx-whisper` (model `VSTUDIO_WHISPER_MLX`, default whisper-large-v3-turbo) |
| `faster` | local (any OS) | `pip install faster-whisper` (model `VSTUDIO_WHISPER_FW`) |
| `openai` | API | `OPENAI_API_KEY` (whisper-1, about $0.006 / min) |
| `openai-compatible` | self-hosted | a `/v1/audio/transcriptions` server: `VSTUDIO_ASR_BASE_URL` (or persona `asr.base_url`), optional `asr.api_key_env`, `asr.model` |

`auto` = persona `asr.backend` / env `VSTUDIO_ASR_BACKEND`, else mlx -> faster -> openai (a server is only used
when named). Self-hosted servers that speak this API: faster-whisper-server / speaches (port 8000, model e.g.
`Systran/faster-whisper-large-v3`), whisper.cpp `whisper-server --inference-path /v1/audio/transcriptions`,
LocalAI. Word timestamps come from the server when it returns them (`verbose_json` + word granularity); a server
that returns only segments gets evenly spread words per segment (marked `approx_words`; cuts on those are less
exact - prefer local mlx / faster for tight edits). Results are cached per backend (+ server URL).

FunASR / SenseVoice (strong for Chinese) are not built in: the FunASR toolkit is MIT, but the SenseVoice /
Paraformer model weights ship under the FunASR model license, not Apache / MIT. If you run them yourself behind an
OpenAI-compatible transcription server, use the `openai-compatible` backend.

## 4. Speech synthesis (TTS)

| engine | kind | setup |
|---|---|---|
| `openai` | API | `OPENAI_API_KEY`; `gpt-4o-mini-tts` with per-line `instructions` (delivery direction) |
| `kokoro` | local (Apple Silicon) | `pip install mlx-audio` |
| `edge` | online, no key | `pip install edge-tts` (Microsoft online voices) |
| `clone` | local (Apple Silicon) | `mlx-audio` + persona `tts.clone.ref_wav` / `ref_text` (your own voice only) |
| `openai-compatible` | self-hosted | a `/v1/audio/speech` server (Kokoro-FastAPI on port 8880, openedai-speech, LocalAI): `VSTUDIO_TTS_BASE_URL` or persona `tts.server.{base_url, api_key_env, model, voice}` |
| `elevenlabs` | API (optional) | `ELEVENLABS_API_KEY`; voice = a voice id (persona `tts.elevenlabs_voice`), model `eleven_multilingual_v2`, speed 0.7-1.2 |

`auto` = persona `tts.engine` / env `VSTUDIO_TTS_ENGINE`, else kokoro (Apple Silicon) -> edge -> openai. The
explainer narration takes `--engine`; drills take `--engine`. Takes are cached by engine + model (+ server URL) +
voice + speed + direction + text.

## 5. What each step sends

| step | task / registry | sent to the provider | not sent |
|---|---|---|---|
| plan-segments | `segment_plan` | the whole transcript as numbered sentences with times (chunks of ~150k chars), platform title rules, the client's style text and preferred tags | audio, video, file paths |
| intake plan / revise | `intake` | the request, the material summary (file names, durations, roles, short excerpts, document headings), the recipe catalog; when the request selects content from a recording, its time-coded transcript (up to 60k chars) | audio, video, full documents |
| output edit `ai` | `output_edit` | the instruction, the output's duration / canvas / mode / capability flags, the current edit state (trim, cuts, effect instances), the op list and the effect catalogue, the caption cues or a time-coded transcript of the output (up to 400 lines) | audio, video, file paths of the media |
| glossary | `glossary` | the whole transcript text of one source, the series / topic, the creator's term list; then the latin tokens with short contexts; then each proposed fix with up to 5 contexts | audio, video |
| proofread | `proofread` | the captions of one job (chunks of 120 cues), a second ASR hearing of the same span, low-confidence words, topic / title / chapter / notes, the glossary | audio, video |
| claude planner | `planner` (Anthropic) | the transcript in ~15 min chunks with times | audio, video |
| ASR `openai` / `openai-compatible` | asr | the audio track (mono 16 kHz, 32 kbps mp3), language, the ASR prompt (term list) | video |
| TTS `openai` / `elevenlabs` / `edge` / server | tts | the narration text, voice, speed, delivery direction | anything else |
| `clone` TTS, `mlx` / `faster` ASR, local LLM servers on localhost | - | nothing leaves the machine | |

Transcripts can hold names and private details of the people recorded: for client work prefer a local or
self-hosted model, or a provider whose data terms (retention, training use, region) your client accepts.

## 6. Cost

API calls are costed from `vstudio.llm.PRICES` (USD per million tokens; persona `llm.prices`, a call's `prices=`,
or the batch spec `prices.proofread_in / proofread_out` override it; unknown API models are estimated at 2.5 / 10
and flagged `cost_estimated`). Local servers and subscription CLIs are booked at 0 (the CLI's own notional figure
is kept in `usage.notional_cost_usd`). Whisper API minutes use `prices.openai_whisper_min`.
