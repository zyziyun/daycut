"""One LLM interface for every AI text step (segment planning, proofreading, glossary, post copy, scripts).

    from vstudio import llm
    r = llm.complete("proofread", system="...", prompt="...", schema=True)      # routed by config / env
    r = llm.complete("copy", system, prompt, provider="ollama", model="qwen3:8b", schema={"type": "object", ...})
    r["text"], r["json"], r["usage"], r["cost_usd"], r["provider"], r["model"]
    llm.route("segment_plan")              # -> Route(provider, model, opts) without calling anything

    python -m vstudio.llm providers [--json]          # what works on this machine: keys, CLIs, local servers
    python -m vstudio.llm test --provider ollama      # one tiny round-trip (prints no secrets)

Providers (``provider=``; aliases: claude -> anthropic, chatgpt -> openai, gpt -> openai)
  anthropic          anthropic SDK (lazy import), ANTHROPIC_API_KEY; default claude-opus-5-5 (adaptive thinking is
                     that model's default: no budget_tokens, no assistant prefill); dict schema -> output_config.format
  openai             openai SDK Chat Completions, OPENAI_API_KEY; default gpt-4.1-mini; JSON mode / json_schema
  openai-compatible  any /v1/chat/completions server: ``base_url`` + ``api_key_env`` (config or VSTUDIO_LLM_BASE_URL /
                     VSTUDIO_LLM_API_KEY_ENV). Presets with their own name: deepseek, qwen (DashScope compatible mode),
                     kimi (Moonshot), glm (Zhipu), openrouter, and local servers ollama, lmstudio, vllm, llamacpp
  gemini             google-genai (lazy import), GEMINI_API_KEY / GOOGLE_API_KEY; default gemini-2.5-flash (optional)
  claude-code        the user's installed ``claude`` CLI, non-interactive (``claude -p --output-format json``), no
                     tools, temp cwd: runs on the user's own Claude login / subscription. API keys are removed from
                     its environment (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_BASE_URL) unless the
                     route sets ``inherit_env: true``
  codex              the user's installed ``codex`` CLI (``codex exec --json``, read-only sandbox, temp cwd): the
                     user's ChatGPT login
  none               no model: ``complete`` returns an empty result; callers use their rule-based path

Routing (first match wins; ``route(task, provider, model, config)``):
  1. explicit ``provider=`` / ``model=`` arguments ("auto" / None = not given)
  2. env VSTUDIO_LLM_<TASK>_PROVIDER / VSTUDIO_LLM_<TASK>_MODEL        (e.g. VSTUDIO_LLM_PROOFREAD_PROVIDER=ollama)
  3. ``config["llm"]["tasks"][task]`` (a client config), then persona ``llm.tasks.<task>``
  4. env VSTUDIO_LLM_PROVIDER / VSTUDIO_LLM_MODEL
  5. ``config["llm"]["default"]``, then persona ``llm.default``
  6. legacy auto: anthropic when ANTHROPIC_API_KEY is set, else none (nothing paid or remote is picked implicitly)
  Config shape (persona.local.yaml or a client's client.yaml):
      llm:
        default: {provider: claude-code}                  # or "claude-code" (string shorthand)
        tasks:
          segment_plan: {provider: anthropic, model: claude-opus-5-5, effort: medium}
          proofread:    {provider: ollama, model: "qwen3:8b"}
          glossary:     {provider: openai-compatible, base_url: "http://gpu-box:8000/v1", api_key_env: MY_KEY,
                         model: Qwen/Qwen3-32B}
          copy:         {provider: deepseek}
        prices: {"my-model": [0.5, 1.5]}                  # USD per million tokens (input, output), overrides PRICES

JSON: ``schema=True`` asks for any JSON object, a dict asks for that JSON schema. Native JSON mode where the
provider has one (OpenAI response_format, Anthropic output_config.format for dict schemas, Ollama / vLLM /
llama.cpp json mode, Gemini response_mime_type, claude --json-schema, codex --output-schema); otherwise (and
always as a safety net) a JSON instruction + tolerant parse (code fences, prose around the object, trailing
commas) + ONE repair retry that shows the model its broken reply. ``r["json"]`` is None when it still fails.

Retries: transient errors (429, 5xx, overloaded, connection resets, timeouts of API calls) are retried
``retries`` times with backoff; auth / bad-request errors and CLI timeouts are not.
Cost: ``PRICES`` (USD per million tokens) x usage for API providers (unknown API models: 2.5 / 10, flagged
``cost_estimated``); local servers and subscription CLIs cost 0 here (the CLI's notional figure is kept in
``usage["notional_cost_usd"]``).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

TASKS = ("segment_plan", "proofread", "glossary", "copy", "script", "planner", "test")

DEFAULT_MODELS = {"anthropic": "claude-opus-5-5", "openai": "gpt-4.1-mini", "gemini": "gemini-2.5-flash",
                  "claude-code": None, "codex": None, "openai-compatible": None, "none": None}

# USD per million tokens (input, output). Override per call (prices=) or persona llm.prices.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0), "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0), "claude-fable-5-1": (10.0, 50.0),
    "gpt-4.1": (2.0, 8.0), "gpt-4.1-mini": (0.4, 1.6), "gpt-4o": (2.5, 10.0), "gpt-4o-mini": (0.15, 0.6),
}
UNKNOWN_PRICE = (2.5, 10.0)

# openai-compatible presets: base_url, key env (None = no key), default model, json mode the server supports,
# kind (api = hosted, paid; local = a server on this machine / your network)
PRESETS = {
    "deepseek": dict(base_url="https://api.deepseek.com/v1", key_env="DEEPSEEK_API_KEY", model="deepseek-chat",
                     json_mode="json_object", kind="api"),
    "qwen": dict(base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", key_env="DASHSCOPE_API_KEY",
                 model="qwen-plus", json_mode="json_object", kind="api"),
    "kimi": dict(base_url="https://api.moonshot.cn/v1", key_env="MOONSHOT_API_KEY", model="kimi-k2-0905-preview",
                 json_mode="json_object", kind="api"),
    "glm": dict(base_url="https://open.bigmodel.cn/api/paas/v4", key_env="ZHIPUAI_API_KEY", model="glm-4.6",
                json_mode="json_object", kind="api"),
    "openrouter": dict(base_url="https://openrouter.ai/api/v1", key_env="OPENROUTER_API_KEY",
                       model="openai/gpt-4.1-mini", json_mode="json_object", kind="api"),
    "ollama": dict(base_url="http://localhost:11434/v1", key_env=None, model="qwen3:8b", json_mode="json_object",
                   kind="local"),
    "lmstudio": dict(base_url="http://localhost:1234/v1", key_env=None, model=None, json_mode="json_schema",
                     kind="local"),
    "vllm": dict(base_url="http://localhost:8000/v1", key_env=None, model=None, json_mode="json_object",
                 kind="local"),
    "llamacpp": dict(base_url="http://localhost:8080/v1", key_env=None, model=None, json_mode="json_object",
                     kind="local"),
}
BACKENDS = ("anthropic", "openai", "openai-compatible", "gemini", "claude-code", "codex", "none")
ALIASES = {"claude": "anthropic", "claude-api": "anthropic", "chatgpt": "openai", "gpt": "openai",
           "compatible": "openai-compatible", "claude_code": "claude-code", "claude-cli": "claude-code",
           "codex-cli": "codex", "lm-studio": "lmstudio", "llama.cpp": "llamacpp", "llama-cpp": "llamacpp",
           "dashscope": "qwen", "moonshot": "kimi", "zhipu": "glm", "off": "none", "rule": "none", "rules": "none"}
LOCAL = {"claude-code", "codex", "none"} | {k for k, v in PRESETS.items() if v["kind"] == "local"}
JSON_INSTRUCTION = "Reply with one JSON object only - no prose, no code fences."
CLI_STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
CODEX_STRIP_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL")


class LLMError(RuntimeError):
    """A provider failed (missing package / key, refusal, broken reply after retries, CLI error)."""


class TransientError(LLMError):
    """Worth retrying (rate limit, overload, 5xx, connection reset)."""


_sleep = time.sleep          # tests patch this


# ------------------------------------------------------------------ names, routing
def canonical(name):
    """Provider name -> canonical name (aliases, case); "auto" / "" / None -> None."""
    if name is None:
        return None
    n = str(name).strip().lower()
    if n in ("", "auto"):
        return None
    n = ALIASES.get(n, n)
    if n not in BACKENDS and n not in PRESETS:
        raise ValueError(f"unknown LLM provider {name!r}: {' | '.join(names())}")
    return n


def names():
    """Every provider name ``complete`` accepts (canonical)."""
    return list(BACKENDS[:3]) + list(PRESETS) + list(BACKENDS[3:])


def backend_of(provider):
    """Canonical provider -> the backend that runs it (presets run on openai-compatible)."""
    return "openai-compatible" if provider in PRESETS else provider


@dataclass
class Route:
    provider: str
    model: str | None = None
    opts: dict = field(default_factory=dict)
    source: str = "legacy-auto"

    def as_dict(self):
        return dict(provider=self.provider, model=self.model, source=self.source,
                    **{k: v for k, v in self.opts.items() if k != "api_key"})


def _persona_llm():
    try:
        from .config import persona
        return persona().get("llm") or {}
    except Exception:  # noqa: BLE001
        return {}


def _entry(v):
    """Config entry (dict or "provider" / "provider:model"-free string) -> dict or None."""
    if not v:
        return None
    if isinstance(v, str):
        return {"provider": v}
    return dict(v) if isinstance(v, dict) else None


def _llm_section(config):
    if not config:
        return {}
    return (config.get("llm") or {}) if "llm" in config else config if ("tasks" in config or "default" in config) \
        else {}


def route(task="default", provider=None, model=None, config=None):
    """Which provider / model / options ``task`` uses (see module doc for the precedence)."""
    task = str(task or "default")
    T = re.sub(r"[^A-Z0-9]", "_", task.upper())
    cfg, per = _llm_section(config), _persona_llm()
    p = canonical(provider)
    if p:
        opts = {}
        for src in ((cfg.get("tasks") or {}).get(task), (per.get("tasks") or {}).get(task), cfg.get("default"),
                    per.get("default")):
            e = _entry(src)
            if e and canonical(e.get("provider")) == p:      # same provider configured: keep its model / options
                opts = {k: v for k, v in e.items() if k not in ("provider",)}
                break
        mdl = model or opts.pop("model", None)
        opts.pop("model", None)
        return Route(p, mdl, opts, "argument")
    cands = [(os.environ.get(f"VSTUDIO_LLM_{T}_PROVIDER") and
              {"provider": os.environ[f"VSTUDIO_LLM_{T}_PROVIDER"], "model": os.environ.get(f"VSTUDIO_LLM_{T}_MODEL")},
              f"env VSTUDIO_LLM_{T}_PROVIDER"),
             (_entry((cfg.get("tasks") or {}).get(task)), f"config llm.tasks.{task}"),
             (_entry((per.get("tasks") or {}).get(task)), f"persona llm.tasks.{task}"),
             (os.environ.get("VSTUDIO_LLM_PROVIDER") and
              {"provider": os.environ["VSTUDIO_LLM_PROVIDER"], "model": os.environ.get("VSTUDIO_LLM_MODEL")},
              "env VSTUDIO_LLM_PROVIDER"),
             (_entry(cfg.get("default")), "config llm.default"),
             (_entry(per.get("default")), "persona llm.default")]
    for e, src in cands:
        if e and canonical(e.get("provider")):
            opts = {k: v for k, v in e.items() if k not in ("provider", "model") and v is not None}
            return Route(canonical(e["provider"]), model or e.get("model") or None, opts, src)
    return Route("anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "none", model, {}, "legacy-auto")


def default_model(provider, opts=None):
    p = canonical(provider) or "none"
    if p in PRESETS:
        return (opts or {}).get("model") or PRESETS[p]["model"]
    return DEFAULT_MODELS.get(p)


# ------------------------------------------------------------------ cost
def price_of(model, prices=None):
    """(input, output) USD per million tokens and whether it is known."""
    table = dict(PRICES)
    for k, v in (_persona_llm().get("prices") or {}).items():
        table[k] = tuple(v)
    for k, v in (prices or {}).items():
        if isinstance(v, (list, tuple)) and len(v) == 2:
            table[k] = tuple(v)
    if model in table:
        return tuple(float(x) for x in table[model]), True
    return UNKNOWN_PRICE, False


def cost_usd(provider, model, usage, prices=None):
    """USD for ``usage`` {input, output}: 0 for local servers / subscription CLIs / none."""
    p = canonical(provider) or "none"
    if p in LOCAL:
        return 0.0
    (pin, pout), _ = price_of(model, prices)
    return round((usage.get("input", 0) * pin + usage.get("output", 0) * pout) / 1e6, 5)


# ------------------------------------------------------------------ JSON helpers
def parse_json(text):
    """Tolerant JSON parse: code fences, prose around the object / array, trailing commas, smart quotes around
    keys. Returns the object or raises ValueError."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json|JSON)?\s*|\s*```\s*$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    for pat in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pat, t, re.S)
        if not m:
            continue
        frag = m.group(0)
        for cand in (frag, re.sub(r",\s*([}\]])", r"\1", frag)):
            try:
                return json.loads(cand)
            except ValueError:
                continue
    raise ValueError(f"no JSON in the reply: {t[:200]!r}")


def _schema_hint(schema):
    if isinstance(schema, dict):
        return "Reply with one JSON object only (no prose, no code fences) matching this JSON schema:\n" + \
            json.dumps(schema, ensure_ascii=False)
    return JSON_INSTRUCTION


def _with_instruction(system, schema):
    """Append the JSON instruction unless the system prompt already demands JSON (and no dict schema)."""
    if not schema:
        return system
    if not isinstance(schema, dict) and re.search(r"\bjson\b", system or "", re.I):
        return system
    return ((system or "").rstrip() + "\n\n" + _schema_hint(schema)).strip()


# ------------------------------------------------------------------ backends
def _anthropic(system, prompt, model, schema, max_tokens, timeout, opts):
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("provider anthropic (claude) needs the anthropic package: pip install anthropic") from e
    client = anthropic.Anthropic(timeout=timeout) if timeout else anthropic.Anthropic()
    oc = {"effort": opts["effort"]} if opts.get("effort") else {}
    if isinstance(schema, dict):
        oc["format"] = {"type": "json_schema", "schema": schema}
    sysp = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}] if opts.get("cache") and system \
        else system
    kw = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
    if sysp:
        kw["system"] = sysp
    if oc:
        kw["output_config"] = oc
    try:
        try:                                      # server-side refusal fallback (beta) when the SDK knows it
            resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kw)
        except TypeError:
            resp = client.messages.create(**kw)
    except Exception as e:  # noqa: BLE001
        raise _classify(e) from e
    if getattr(resp, "stop_reason", None) == "refusal":
        raise LLMError("the model declined the request (stop_reason refusal)")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    u = getattr(resp, "usage", None)
    return text, dict(input=getattr(u, "input_tokens", 0) or 0, output=getattr(u, "output_tokens", 0) or 0), \
        getattr(resp, "model", None) or model


def _reasoning_model(model):
    return bool(re.match(r"(o\d|gpt-5)", str(model or "")))


def _openai_chat(system, prompt, model, schema, max_tokens, timeout, opts, base_url=None, api_key=None,
                 json_mode="json_schema", official=True):
    try:
        from openai import OpenAI
    except ImportError as e:
        raise LLMError("this provider needs the openai package: pip install openai") from e
    kw = {}
    if base_url:
        kw["base_url"] = base_url
    if timeout:
        kw["timeout"] = timeout
    client = OpenAI(api_key=api_key, **kw)
    req = dict(model=model, messages=([{"role": "system", "content": system}] if system else []) +
               [{"role": "user", "content": prompt}])
    if official:
        req["max_completion_tokens" if _reasoning_model(model) else "max_tokens"] = max_tokens
    else:
        req["max_tokens"] = max_tokens
    if opts.get("temperature") is not None and not _reasoning_model(model):
        req["temperature"] = opts["temperature"]
    if schema and json_mode:
        if isinstance(schema, dict) and json_mode == "json_schema":
            req["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "output", "schema": schema, "strict": False}}
        elif json_mode == "json_object":
            req["response_format"] = {"type": "json_object"}
        elif json_mode == "json_schema":         # LM Studio: no json_object, a permissive object schema
            req["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "output", "schema": {"type": "object"}}}
    try:
        resp = client.chat.completions.create(**req)
    except Exception as e:  # noqa: BLE001
        raise _classify(e) from e
    u = getattr(resp, "usage", None)
    ch = resp.choices[0]
    if getattr(ch, "finish_reason", None) == "content_filter":
        raise LLMError("the model declined the request (content_filter)")
    return ch.message.content or "", dict(input=getattr(u, "prompt_tokens", 0) or 0,
                                          output=getattr(u, "completion_tokens", 0) or 0), \
        getattr(resp, "model", None) or model


def _openai(system, prompt, model, schema, max_tokens, timeout, opts):
    if not os.environ.get("OPENAI_API_KEY"):
        raise LLMError("provider openai needs OPENAI_API_KEY")
    return _openai_chat(system, prompt, model, schema, max_tokens, timeout, opts,
                        base_url=opts.get("base_url"), api_key=os.environ["OPENAI_API_KEY"], official=True)


def compatible_target(provider, opts):
    """(base_url, key env name or None, json_mode, kind) of an openai-compatible provider / preset."""
    pre = PRESETS.get(provider, {})
    base = opts.get("base_url") or os.environ.get(f"VSTUDIO_{provider.upper().replace('-', '_')}_BASE_URL") \
        or pre.get("base_url") or os.environ.get("VSTUDIO_LLM_BASE_URL")
    key_env = opts.get("api_key_env", pre.get("key_env") if pre else os.environ.get("VSTUDIO_LLM_API_KEY_ENV"))
    jm = opts.get("json_mode", pre.get("json_mode", "json_object"))
    kind = pre.get("kind") or ("local" if base and re.match(r"https?://(localhost|127\.|\[::1\])", base) else "api")
    return base, key_env, jm, kind


def _compatible(provider):
    def run(system, prompt, model, schema, max_tokens, timeout, opts):
        base, key_env, jm, _ = compatible_target(provider, opts)
        if not base:
            raise LLMError(f"provider {provider} needs base_url (route option or VSTUDIO_LLM_BASE_URL)")
        key = os.environ.get(key_env) if key_env else None
        if key_env and not key:
            raise LLMError(f"provider {provider} needs {key_env}")
        if not model:
            raise LLMError(f"provider {provider} needs a model (route option model: or --model)")
        return _openai_chat(system, prompt, model, schema, max_tokens, timeout, opts, base_url=base,
                            api_key=key or "not-needed", json_mode=jm, official=False)
    return run


def _gemini(system, prompt, model, schema, max_tokens, timeout, opts):
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise LLMError("provider gemini needs google-genai: pip install google-genai") from e
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise LLMError("provider gemini needs GEMINI_API_KEY (or GOOGLE_API_KEY)")
    client = genai.Client(api_key=key)
    cfg = dict(system_instruction=system or None, max_output_tokens=max_tokens)
    if schema:
        cfg["response_mime_type"] = "application/json"
    if opts.get("temperature") is not None:
        cfg["temperature"] = opts["temperature"]
    try:
        resp = client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(**cfg))
    except Exception as e:  # noqa: BLE001
        raise _classify(e) from e
    um = getattr(resp, "usage_metadata", None)
    return getattr(resp, "text", "") or "", dict(input=getattr(um, "prompt_token_count", 0) or 0,
                                                 output=getattr(um, "candidates_token_count", 0) or 0), model


def _cli_env(strip, opts):
    env = dict(os.environ)
    if not opts.get("inherit_env"):
        for k in strip:
            env.pop(k, None)
    return env


def _claude_code(system, prompt, model, schema, max_tokens, timeout, opts):
    exe = opts.get("cli") or shutil.which("claude")
    if not exe:
        raise LLMError("provider claude-code needs the Claude Code CLI (`claude`) on PATH")
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--no-session-persistence", "--strict-mcp-config"]
    if system:
        cmd += ["--system-prompt", system]
    if model:
        cmd += ["--model", model]
    if isinstance(schema, dict):
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    with tempfile.TemporaryDirectory(prefix="vstudio-llm-") as tmp:
        try:
            r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=tmp, timeout=timeout,
                               env=_cli_env(CLI_STRIP_ENV, opts))
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"claude CLI timed out after {timeout} s") from e
    try:
        d = json.loads(r.stdout or "")
    except ValueError:
        d = None
    if not isinstance(d, dict):
        raise LLMError(f"claude CLI failed (exit {r.returncode}): {(r.stderr or r.stdout or '').strip()[:300]}")
    if d.get("is_error") or r.returncode:
        msg = str(d.get("result") or d.get("subtype") or "error")[:300]
        if re.search(r"overloaded|rate.?limit|\b5\d\d\b|\b429\b", msg, re.I):
            raise TransientError(f"claude CLI: {msg}")
        raise LLMError(f"claude CLI: {msg}")
    text = d.get("result") or ""
    if d.get("structured_output") is not None:
        text = json.dumps(d["structured_output"], ensure_ascii=False)
    u = d.get("usage") or {}
    usage = dict(input=int(u.get("input_tokens", 0) or 0) + int(u.get("cache_read_input_tokens", 0) or 0) +
                 int(u.get("cache_creation_input_tokens", 0) or 0), output=int(u.get("output_tokens", 0) or 0))
    if d.get("total_cost_usd") is not None:
        usage["notional_cost_usd"] = d["total_cost_usd"]
    mu = list((d.get("modelUsage") or {}).keys())
    return text, usage, model or (mu[0] if mu else "claude-code-default")


def _codex(system, prompt, model, schema, max_tokens, timeout, opts):
    exe = opts.get("cli") or shutil.which("codex")
    if not exe:
        raise LLMError("provider codex needs the Codex CLI (`codex`) on PATH")
    with tempfile.TemporaryDirectory(prefix="vstudio-llm-") as tmp:
        last = os.path.join(tmp, "last.txt")
        cmd = [exe, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "--cd", tmp,
               "--output-last-message", last]
        if model:
            cmd += ["--model", model]
        if isinstance(schema, dict):
            sp = os.path.join(tmp, "schema.json")
            with open(sp, "w", encoding="utf-8") as f:
                json.dump(schema, f)
            cmd += ["--output-schema", sp]
        cmd.append("-")                                    # prompt from stdin
        full = (f"{system}\n\n---\n\n{prompt}" if system else prompt)
        try:
            r = subprocess.run(cmd, input=full, capture_output=True, text=True, cwd=tmp, timeout=timeout,
                               env=_cli_env(CODEX_STRIP_ENV, opts))
        except subprocess.TimeoutExpired as e:
            raise LLMError(f"codex CLI timed out after {timeout} s") from e
        text = open(last, encoding="utf-8").read() if os.path.exists(last) else ""
    usage, err, agent = dict(input=0, output=0), None, ""
    for ln in (r.stdout or "").splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        typ = ev.get("type") or ""
        if typ == "turn.completed":
            u = ev.get("usage") or {}
            usage["input"] += int(u.get("input_tokens", 0) or 0)
            usage["output"] += int(u.get("output_tokens", 0) or 0)
        elif typ in ("turn.failed", "error"):
            err = str((ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict) else
                      ev.get("message") or ev.get("error") or typ)
        elif typ == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
            agent = (ev["item"].get("text") or agent)
    if r.returncode or (err and not text):
        raise LLMError(f"codex CLI failed (exit {r.returncode}): {(err or r.stderr or '').strip()[:300]}")
    return text or agent, usage, model or "codex-default"


def _none(*a, **k):
    return "", dict(input=0, output=0), None


BACKEND_FNS = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini, "claude-code": _claude_code,
               "codex": _codex, "none": _none}


def _fn(provider):
    if provider in BACKEND_FNS:
        return BACKEND_FNS[provider]
    return _compatible(provider)


def _classify(e):
    """Exception from an SDK -> TransientError (retry) or LLMError (give up), message kept."""
    if isinstance(e, LLMError):
        return e
    name = type(e).__name__
    status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
    msg = f"{name}: {str(e)[:300]}"
    if name in ("RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError",
                "ServiceUnavailableError", "OverloadedError", "ConnectionError", "TimeoutError",
                "RemoteDisconnected", "ServerError") or (isinstance(status, int) and (status == 429 or status >= 500)):
        return TransientError(msg)
    if isinstance(e, (ConnectionError, TimeoutError, urllib.error.URLError)):
        return TransientError(msg)
    return LLMError(msg)


# ------------------------------------------------------------------ public
def complete(task, system, prompt, schema=None, provider=None, model=None, max_tokens=16000, timeout=600,
             config=None, effort=None, temperature=None, retries=2, repair=True, prices=None, **opts):
    """One LLM call. Returns dict(text, json, usage {input, output}, cost_usd, provider, model, route, attempts).

    task: routing key (segment_plan | proofread | glossary | copy | script | ...); schema: None (text), True (any
    JSON object) or a JSON-schema dict; provider / model: override the route; config: a client config with an
    ``llm`` section; effort (anthropic output_config.effort), temperature, cache (anthropic: cache the system
    prompt), base_url / api_key_env (openai-compatible), inherit_env / cli (CLIs) go to the backend.
    Raises LLMError when the provider fails after the retries (never for a JSON problem: ``json`` is None then).
    """
    r = route(task, provider, model, config)
    o = dict(r.opts)
    o.update({k: v for k, v in opts.items() if v is not None})
    if effort is not None:
        o["effort"] = effort
    if temperature is not None:
        o["temperature"] = temperature
    p = r.provider
    mdl = r.model or default_model(p, o)
    out = dict(text="", json=None, usage=dict(input=0, output=0), cost_usd=0.0, provider=p, model=mdl,
               route=r.source, attempts=0)
    if p == "none":
        return out
    fn = _fn(p)
    sysp = _with_instruction(system, schema)

    def call(sys_, prompt_):
        last = None
        for k in range(max(0, int(retries)) + 1):
            out["attempts"] += 1
            try:
                return fn(sys_, prompt_, mdl, schema, max_tokens, timeout, o)
            except TransientError as e:
                last = e
                if k < retries:
                    _sleep(min(30.0, 2.0 * (2 ** k)))
            except LLMError:
                raise
            except Exception as e:  # noqa: BLE001
                ce = _classify(e)
                if not isinstance(ce, TransientError):
                    raise ce from e
                last = ce
                if k < retries:
                    _sleep(min(30.0, 2.0 * (2 ** k)))
        raise last

    def add(u):
        for k, v in u.items():
            if isinstance(v, (int, float)):
                out["usage"][k] = out["usage"].get(k, 0) + v

    text, u, used = call(sysp, prompt)
    add(u)
    out["text"], out["model"] = text or "", used or mdl
    if schema:
        try:
            out["json"] = parse_json(out["text"])
        except ValueError as e:
            if repair:
                fix = (f"Your previous reply was not valid JSON ({str(e)[:120]}). Return the same answer as one "
                       f"valid JSON object only.\n\nPrevious reply:\n{out['text'][:20000]}")
                t2, u2, _ = call(_with_instruction(system, schema if isinstance(schema, dict) else True), fix)
                add(u2)
                try:
                    out["json"] = parse_json(t2)
                    out["text"] = t2 or ""
                except ValueError:
                    out["json"] = None
    out["cost_usd"] = cost_usd(p, out["model"], out["usage"], prices)
    out["cost_estimated"] = p not in LOCAL and not price_of(out["model"], prices)[1]
    return out


def call_fn(task, provider=None, schema=True, config=None, **kw):
    """Adapter for the older ``fn(system, prompt, model) -> (text, usage)`` call sites (proofread, segplan)."""
    def fn(system, prompt, model):
        r = complete(task, system, prompt, schema=schema, provider=provider, model=model, config=config, **kw)
        return r["text"], dict(r["usage"])
    return fn


# ------------------------------------------------------------------ availability
def _probe_url(url, timeout=0.6):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vstudio"}),
                                    timeout=timeout) as r:
            return r.status < 500, r.read(200000)
    except urllib.error.HTTPError as e:
        return e.code < 500, b""
    except Exception:  # noqa: BLE001
        return False, b""


def _cli_version(exe, timeout=10):
    try:
        r = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr).strip().splitlines()[0] if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def _has(mod):
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def check(provider, opts=None, probe=True):
    """dict(provider, kind, ready, detail) - no network call to paid APIs; local servers get a 0.6 s GET
    /models; CLIs run ``--version``."""
    p = canonical(provider) or "none"
    o = opts or {}
    if p == "none":
        return dict(provider=p, kind="rule-based", ready=True, detail="always available (no model)")
    if p == "anthropic":
        miss = [x for x, ok in (("pip install anthropic", _has("anthropic")),
                                ("ANTHROPIC_API_KEY", bool(os.environ.get("ANTHROPIC_API_KEY")))) if not ok]
        return dict(provider=p, kind="api", ready=not miss, detail="needs " + ", ".join(miss) if miss else
                    f"key set, default {DEFAULT_MODELS[p]}")
    if p == "openai":
        miss = [x for x, ok in (("pip install openai", _has("openai")),
                                ("OPENAI_API_KEY", bool(os.environ.get("OPENAI_API_KEY")))) if not ok]
        return dict(provider=p, kind="api", ready=not miss, detail="needs " + ", ".join(miss) if miss else
                    f"key set, default {DEFAULT_MODELS[p]}")
    if p == "gemini":
        miss = [x for x, ok in (("pip install google-genai", _has("google.genai")),
                                ("GEMINI_API_KEY", bool(os.environ.get("GEMINI_API_KEY") or
                                                        os.environ.get("GOOGLE_API_KEY")))) if not ok]
        return dict(provider=p, kind="api", ready=not miss, detail="needs " + ", ".join(miss) if miss else
                    f"key set, default {DEFAULT_MODELS[p]}")
    if p in ("claude-code", "codex"):
        exe = o.get("cli") or shutil.which("claude" if p == "claude-code" else "codex")
        if not exe:
            return dict(provider=p, kind="subscription-cli", ready=False,
                        detail=f"`{'claude' if p == 'claude-code' else 'codex'}` not on PATH")
        v = _cli_version(exe) if probe else "found"
        return dict(provider=p, kind="subscription-cli", ready=bool(v),
                    detail=(f"{v} (uses your own login; run `python -m vstudio.llm test --provider {p}` to check it)"
                            if v else "installed but `--version` failed"))
    base, key_env, _, kind = compatible_target(p, o)
    if not base:
        return dict(provider=p, kind=kind, ready=False, detail="needs base_url (config or VSTUDIO_LLM_BASE_URL)")
    if kind == "api":
        ok = bool(key_env and os.environ.get(key_env)) and _has("openai")
        need = [x for x, c in ((key_env or "api_key_env", bool(key_env and os.environ.get(key_env))),
                               ("pip install openai", _has("openai"))) if not c]
        return dict(provider=p, kind="api", ready=ok, detail=f"{base}: " + ("key set" if ok else
                                                                          "needs " + ", ".join(need)))
    if not probe:
        return dict(provider=p, kind="local", ready=False, detail=f"{base} (not probed)")
    up, body = _probe_url(base.rstrip("/") + "/models")
    models = []
    try:
        models = [m.get("id") for m in json.loads(body or b"{}").get("data") or [] if m.get("id")]
    except ValueError:
        pass
    if not up:
        return dict(provider=p, kind="local", ready=False, detail=f"{base}: no server answering")
    return dict(provider=p, kind="local", ready=True, detail=f"{base}: up" +
                (f", models: {', '.join(models[:6])}" + (" ..." if len(models) > 6 else "") if models else ""),
                models=models)


def providers(probe=True):
    """``check`` for every provider (+ the configured openai-compatible endpoint, if any)."""
    rows = [check(p, probe=probe) for p in names() if p != "openai-compatible"]
    if os.environ.get("VSTUDIO_LLM_BASE_URL"):
        rows.append(check("openai-compatible", probe=probe))
    return rows


# ------------------------------------------------------------------ CLI
def _print_rows(title, rows):
    print(title)
    for r in rows:
        print(f"  {'ready' if r['ready'] else '  -  '}  {r['provider']:<18} {r['kind']:<17} {r['detail']}")


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m vstudio.llm", description="LLM / ASR / TTS providers on this machine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pp = sub.add_parser("providers", help="list LLM, ASR and TTS providers and whether they work here")
    pp.add_argument("--json", action="store_true")
    pp.add_argument("--no-probe", action="store_true", help="skip local-server / CLI probes")
    pr = sub.add_parser("route", help="show which provider each task would use")
    pr.add_argument("--task", action="append")
    pt = sub.add_parser("test", help="one tiny JSON round-trip")
    pt.add_argument("--provider", required=True)
    pt.add_argument("--model")
    pt.add_argument("--base-url")
    pt.add_argument("--timeout", type=float, default=180)
    a = ap.parse_args(argv)
    if a.cmd == "providers":
        from . import asr, tts
        data = dict(llm=providers(not a.no_probe), asr=asr.providers(not a.no_probe),
                    tts=tts.providers(not a.no_probe),
                    routes={t: route(t).as_dict() for t in ("segment_plan", "proofread", "glossary", "copy")})
        if a.json:
            print(json.dumps(data, indent=2, ensure_ascii=False))
            return 0
        _print_rows("LLM", data["llm"])
        _print_rows("ASR", data["asr"])
        _print_rows("TTS", data["tts"])
        print("Routes (task -> provider, from)")
        for t, r in data["routes"].items():
            print(f"  {t:<13} {r['provider']}{' / ' + r['model'] if r.get('model') else ''}  ({r['source']})")
        return 0
    if a.cmd == "route":
        for t in a.task or ["segment_plan", "proofread", "glossary", "copy"]:
            print(json.dumps(dict(task=t, **route(t).as_dict()), ensure_ascii=False))
        return 0
    t0 = time.time()
    try:
        r = complete("test", "You are a connectivity check. Reply with JSON only.",
                     'Return exactly {"ok": true, "sum": <2+2 as a number>}.', schema=True, provider=a.provider,
                     model=a.model, max_tokens=2000, timeout=a.timeout, retries=0, base_url=a.base_url)
    except (LLMError, ValueError) as e:
        print(json.dumps(dict(ok=False, provider=a.provider, error=str(e)[:400]), ensure_ascii=False))
        return 1
    ok = isinstance(r["json"], dict) and str(r["json"].get("sum")) in ("4", "4.0")
    print(json.dumps(dict(ok=ok, provider=r["provider"], model=r["model"], json=r["json"], usage=r["usage"],
                          cost_usd=r["cost_usd"], seconds=round(time.time() - t0, 1)), ensure_ascii=False))
    return 0 if ok else 2


__all__ = ["complete", "route", "Route", "check", "providers", "parse_json", "cost_usd", "price_of", "canonical",
           "names", "default_model", "call_fn", "LLMError", "TransientError", "PRESETS", "PRICES", "DEFAULT_MODELS"]

if __name__ == "__main__":
    sys.exit(main())
