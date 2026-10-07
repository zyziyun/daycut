"""vstudio.llm + the asr / tts registries: every backend mocked (SDK modules faked, CLIs via subprocess), JSON repair,
retries, routing precedence, availability probes, cost, and the migrated call sites (proofread / plan-segments)."""
import json
import os
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from vstudio import asr, llm, tts  # noqa: E402

KEYS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "GEMINI_API_KEY",
        "GOOGLE_API_KEY", "DEEPSEEK_API_KEY", "DASHSCOPE_API_KEY", "MOONSHOT_API_KEY", "ZHIPUAI_API_KEY",
        "OPENROUTER_API_KEY", "ELEVENLABS_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_MODEL",
        "VSTUDIO_LLM_BASE_URL", "VSTUDIO_LLM_API_KEY_ENV", "VSTUDIO_ASR_BACKEND", "VSTUDIO_ASR_BASE_URL",
        "VSTUDIO_TTS_ENGINE", "VSTUDIO_TTS_BASE_URL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in list(os.environ):
        if k in KEYS or k.startswith("VSTUDIO_LLM_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm, "_persona_llm", lambda: {})
    monkeypatch.setattr(llm, "_sleep", lambda s: None)


# --------------------------------------------------------------------------- fake SDKs
def fake_anthropic(monkeypatch, replies, seen, beta=True):
    """A fake ``anthropic`` module: replies = list of (text, stop_reason) or exceptions."""
    replies = list(replies)

    def create(**kw):
        seen.append(kw)
        r = replies.pop(0)
        if isinstance(r, Exception):
            raise r
        text, stop = r
        return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=text)], stop_reason=stop,
                                     usage=types.SimpleNamespace(input_tokens=100, output_tokens=20),
                                     model=kw["model"])

    class Messages:
        def create(self, **kw):
            return create(**kw)

    class BetaMessages:
        def create(self, betas=None, fallbacks=None, **kw):
            if not beta:
                raise TypeError("unexpected keyword 'fallbacks'")
            return create(**dict(kw, _betas=betas, _fallbacks=fallbacks))

    class Anthropic:
        def __init__(self, **kw):
            self.messages = Messages()
            self.beta = types.SimpleNamespace(messages=BetaMessages())

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=Anthropic))


def fake_openai(monkeypatch, replies, seen, finish="stop"):
    replies = list(replies)

    class Completions:
        def __init__(self, client):
            self.client = client

        def create(self, **kw):
            seen.append(dict(kw, _client=self.client.kw))
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=r), finish_reason=finish)],
                usage=types.SimpleNamespace(prompt_tokens=50, completion_tokens=10), model=kw["model"])

    class OpenAI:
        def __init__(self, **kw):
            self.kw = kw
            self.chat = types.SimpleNamespace(completions=Completions(self))
            self.audio = types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=self._tr))

        def _tr(self, **kw):
            seen.append(dict(kw, _client=self.kw, file=None))
            return replies.pop(0)

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAI))


class RateLimitError(Exception):
    pass


class BadRequestError(Exception):
    status_code = 400


# --------------------------------------------------------------------------- anthropic
def test_anthropic_native_json_schema_effort_no_budget_no_prefill(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen = []
    fake_anthropic(monkeypatch, [('{"ok": true}', "end_turn")], seen)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"],
              "additionalProperties": False}
    r = llm.complete("copy", "Write copy.", "hi", schema=schema, effort="low")
    kw = seen[0]
    assert r["json"] == {"ok": True} and r["provider"] == "anthropic" and r["model"] == "claude-opus-5-5"
    assert kw["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": schema}}
    assert "thinking" not in kw and "budget_tokens" not in json.dumps(kw)       # adaptive is the model default
    assert [m["role"] for m in kw["messages"]] == ["user"]                       # no assistant prefill
    assert kw["_fallbacks"] == "default" and kw["_betas"] == ["server-side-fallback-2026-07-01"]
    assert r["usage"] == {"input": 100, "output": 20} and r["cost_usd"] == round((100 * 4 + 20 * 20) / 1e6, 5)


def test_anthropic_refusal_and_sdk_without_fallback_param(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen = []
    fake_anthropic(monkeypatch, [("", "refusal")], seen)
    with pytest.raises(llm.LLMError, match="declined"):
        llm.complete("copy", "s", "p", provider="claude")
    fake_anthropic(monkeypatch, [("plain text", "end_turn")], seen, beta=False)
    r = llm.complete("copy", "s", "p", provider="anthropic", cache=True)
    assert r["text"] == "plain text" and r["json"] is None
    assert seen[-1]["system"][0]["cache_control"] == {"type": "ephemeral"} and "_betas" not in seen[-1]


def test_anthropic_missing_sdk_says_how_to_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(RuntimeError, match="pip install anthropic"):
        llm.complete("copy", "s", "p", provider="anthropic")


# --------------------------------------------------------------------------- openai + compatible presets
def test_openai_json_modes_and_reasoning_models(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    seen = []
    fake_openai(monkeypatch, ['{"a": 1}', '{"b": 2}', '{"c": 3}'], seen)
    r = llm.complete("copy", "Return JSON.", "x", provider="openai", schema=True, temperature=0, max_tokens=8000)
    assert r["json"] == {"a": 1} and seen[0]["response_format"] == {"type": "json_object"}
    assert seen[0]["temperature"] == 0 and seen[0]["max_tokens"] == 8000 and r["model"] == "gpt-4.1-mini"
    llm.complete("copy", "s", "x", provider="openai", schema={"type": "object"})
    assert seen[1]["response_format"]["type"] == "json_schema"
    assert "json" in seen[1]["messages"][0]["content"].lower()                # the instruction rides along
    llm.complete("copy", "s", "x", provider="openai", model="o4-mini", schema=True, temperature=0.3)
    assert "max_completion_tokens" in seen[2] and "temperature" not in seen[2]
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(llm.LLMError, match="OPENAI_API_KEY"):
        llm.complete("copy", "s", "x", provider="openai")


@pytest.mark.parametrize("name", sorted(llm.PRESETS))
def test_every_openai_compatible_preset(monkeypatch, name):
    pre = llm.PRESETS[name]
    seen = []
    fake_openai(monkeypatch, ['{"ok": true}'], seen)
    model = pre["model"] or "some-local-model"
    if pre["key_env"]:
        with pytest.raises(llm.LLMError, match=pre["key_env"]):
            llm.complete("copy", "s", "p", provider=name, model=model)
        monkeypatch.setenv(pre["key_env"], "k-test")
    r = llm.complete("copy", "s", "p", provider=name, model=model, schema=True)
    c = seen[-1]["_client"]
    assert c["base_url"] == pre["base_url"] and r["json"] == {"ok": True} and r["provider"] == name
    assert c["api_key"] == ("k-test" if pre["key_env"] else "not-needed")
    if pre["json_mode"] == "json_object":
        assert seen[-1]["response_format"] == {"type": "json_object"}
    else:
        assert seen[-1]["response_format"]["type"] == "json_schema"
    assert (r["cost_usd"] == 0.0) == (pre["kind"] == "local")


def test_generic_openai_compatible_endpoint_needs_base_url_and_model(monkeypatch):
    seen = []
    fake_openai(monkeypatch, ['{"x": 1}'], seen)
    with pytest.raises(llm.LLMError, match="base_url"):
        llm.complete("copy", "s", "p", provider="openai-compatible", model="m")
    monkeypatch.setenv("VSTUDIO_LLM_BASE_URL", "http://gpu-box:8000/v1")
    with pytest.raises(llm.LLMError, match="model"):
        llm.complete("copy", "s", "p", provider="openai-compatible")
    r = llm.complete("copy", "s", "p", provider="openai-compatible", model="Qwen/Qwen3-32B", schema=True)
    assert seen[-1]["_client"]["base_url"] == "http://gpu-box:8000/v1" and r["json"] == {"x": 1}


# --------------------------------------------------------------------------- gemini
def test_gemini_mocked(monkeypatch):
    seen = {}

    class Models:
        def generate_content(self, model, contents, config):
            seen.update(model=model, contents=contents, config=config)
            return types.SimpleNamespace(text='{"g": 1}', usage_metadata=types.SimpleNamespace(
                prompt_token_count=7, candidates_token_count=3))

    class Client:
        def __init__(self, api_key=None):
            seen["key_given"] = bool(api_key)
            self.models = Models()

    gtypes = types.SimpleNamespace(GenerateContentConfig=lambda **kw: kw)
    genai = types.SimpleNamespace(Client=Client, types=gtypes)
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace(genai=genai))
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", gtypes)
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        llm.complete("copy", "s", "p", provider="gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    r = llm.complete("copy", "sys", "p", provider="gemini", schema=True)
    assert r["json"] == {"g": 1} and seen["config"]["response_mime_type"] == "application/json"
    assert seen["model"] == "gemini-2.5-flash" and seen["config"]["system_instruction"].startswith("sys")


# --------------------------------------------------------------------------- subscription CLIs (subprocess mocked)
def test_claude_code_cli(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "must-not-leak")
    monkeypatch.setattr(llm.shutil, "which", lambda n: "/usr/local/bin/claude" if n == "claude" else None)
    calls = []

    def run(cmd, input=None, capture_output=None, text=None, cwd=None, timeout=None, env=None, **kw):
        calls.append(dict(cmd=cmd, input=input, cwd=cwd, timeout=timeout, env=env))
        out = dict(type="result", subtype="success", is_error=False, result="ignored",
                   structured_output={"ok": True}, total_cost_usd=0.01,
                   usage=dict(input_tokens=10, cache_read_input_tokens=5, output_tokens=4),
                   modelUsage={"claude-opus-5-5": {}})
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
    monkeypatch.setattr(llm.subprocess, "run", run)
    r = llm.complete("proofread", "SYSTEM", "PROMPT", provider="claude-code", schema={"type": "object"}, timeout=90)
    c = calls[0]
    assert c["cmd"][:4] == ["/usr/local/bin/claude", "-p", "--output-format", "json"]
    assert c["cmd"][c["cmd"].index("--tools") + 1] == ""                       # no tools at all
    assert "--system-prompt" in c["cmd"] and c["cmd"][c["cmd"].index("--system-prompt") + 1].startswith("SYSTEM")
    assert "--json-schema" in c["cmd"] and "--no-session-persistence" in c["cmd"]
    assert c["input"] == "PROMPT" and c["timeout"] == 90 and "vstudio-llm-" in c["cwd"]
    assert not any(k in c["env"] for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"))   # the user's login only
    assert "must-not-leak" not in " ".join(c["cmd"])
    assert r["json"] == {"ok": True} and r["cost_usd"] == 0.0 and r["usage"]["input"] == 15
    assert r["usage"]["notional_cost_usd"] == 0.01 and r["model"] == "claude-opus-5-5"

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, json.dumps(dict(is_error=True, result="401 token expired")), "")
    monkeypatch.setattr(llm.subprocess, "run", failing)
    with pytest.raises(llm.LLMError, match="token expired"):
        llm.complete("proofread", "s", "p", provider="claude-code")

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
    monkeypatch.setattr(llm.subprocess, "run", slow)
    with pytest.raises(llm.LLMError, match="timed out"):
        llm.complete("proofread", "s", "p", provider="claude-code", timeout=1)


def test_codex_cli(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setattr(llm.shutil, "which", lambda n: "/opt/bin/codex" if n == "codex" else None)
    calls = []

    def run(cmd, input=None, capture_output=None, text=None, cwd=None, timeout=None, env=None, **kw):
        calls.append(dict(cmd=cmd, input=input, cwd=cwd, env=env))
        with open(cmd[cmd.index("--output-last-message") + 1], "w") as f:
            f.write('```json\n{"c": 3}\n```')
        events = [dict(type="thread.started"), dict(type="item.completed", item=dict(type="agent_message", text="x")),
                  dict(type="turn.completed", usage=dict(input_tokens=30, cached_input_tokens=10, output_tokens=6))]
        return subprocess.CompletedProcess(cmd, 0, "\n".join(json.dumps(e) for e in events), "")
    monkeypatch.setattr(llm.subprocess, "run", run)
    r = llm.complete("copy", "SYS", "P", provider="codex", schema={"type": "object",
                                                                   "properties": {"c": {"type": "integer"}}})
    c = calls[0]
    assert c["cmd"][:3] == ["/opt/bin/codex", "exec", "--json"] and c["cmd"][-1] == "-"
    assert c["cmd"][c["cmd"].index("--sandbox") + 1] == "read-only" and "--skip-git-repo-check" in c["cmd"]
    assert c["cmd"][c["cmd"].index("--cd") + 1] == c["cwd"] and "--output-schema" in c["cmd"]
    assert c["input"].startswith("SYS") and c["input"].endswith("P") and "OPENAI_API_KEY" not in c["env"]
    assert r["json"] == {"c": 3} and r["usage"] == {"input": 30, "output": 6} and r["cost_usd"] == 0.0


def test_cli_missing_and_none_provider(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    with pytest.raises(llm.LLMError, match="not|PATH"):
        llm.complete("copy", "s", "p", provider="claude-code")
    with pytest.raises(llm.LLMError, match="PATH"):
        llm.complete("copy", "s", "p", provider="codex")
    r = llm.complete("copy", "s", "p", provider="none", schema=True)
    assert r["text"] == "" and r["json"] is None and r["attempts"] == 0 and r["cost_usd"] == 0.0


# --------------------------------------------------------------------------- JSON repair, retries
def test_tolerant_parse():
    assert llm.parse_json('Sure!\n```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}
    assert llm.parse_json('here: [{"i": 1}] ok') == [{"i": 1}]
    with pytest.raises(ValueError):
        llm.parse_json("no json here")


def test_json_repair_retry_once(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    seen = []
    fake_openai(monkeypatch, ['{"fixes": [ broken', '{"fixes": []}'], seen)
    r = llm.complete("proofread", "JSON please", "p", provider="openai", schema=True)
    assert r["json"] == {"fixes": []} and r["attempts"] == 2 and r["usage"]["input"] == 100
    assert "not valid JSON" in seen[1]["messages"][-1]["content"] and "broken" in seen[1]["messages"][-1]["content"]
    fake_openai(monkeypatch, ["nope", "still nope"], seen)
    r = llm.complete("proofread", "JSON please", "p", provider="openai", schema=True)
    assert r["json"] is None and r["text"] == "nope"                    # never raises for a JSON problem
    fake_openai(monkeypatch, ["nope"], seen)
    assert llm.complete("proofread", "JSON", "p", provider="openai", schema=True, repair=False)["attempts"] == 1


def test_transient_errors_retry_others_do_not(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    sleeps = []
    monkeypatch.setattr(llm, "_sleep", sleeps.append)
    seen = []
    fake_openai(monkeypatch, [RateLimitError("429"), RateLimitError("429"), '{"ok": 1}'], seen)
    r = llm.complete("copy", "s", "p", provider="openai", schema=True)
    assert r["json"] == {"ok": 1} and r["attempts"] == 3 and sleeps == [2.0, 4.0]
    fake_openai(monkeypatch, [BadRequestError("bad"), '{"ok": 1}'], seen)
    with pytest.raises(llm.LLMError, match="BadRequestError"):
        llm.complete("copy", "s", "p", provider="openai")
    fake_openai(monkeypatch, [RateLimitError("a"), RateLimitError("b")], seen)
    with pytest.raises(llm.TransientError):
        llm.complete("copy", "s", "p", provider="openai", retries=1)


# --------------------------------------------------------------------------- routing
def test_routing_precedence(monkeypatch):
    persona = {"default": {"provider": "ollama", "model": "p-default"},
               "tasks": {"proofread": {"provider": "glm", "model": "p-task"}}}
    client = {"llm": {"default": "deepseek", "tasks": {"proofread": {"provider": "kimi", "model": "c-task"}}}}
    monkeypatch.setattr(llm, "_persona_llm", lambda: persona)
    assert llm.route("glossary").provider == "ollama" and llm.route("glossary").model == "p-default"
    assert llm.route("proofread").as_dict()["source"] == "persona llm.tasks.proofread"
    assert llm.route("glossary", config=client).provider == "deepseek"           # client default > persona default
    monkeypatch.setenv("VSTUDIO_LLM_PROVIDER", "lmstudio")
    assert llm.route("glossary", config=client).provider == "lmstudio"           # env default > config defaults
    assert llm.route("proofread").model == "p-task"                              # but a task entry is more specific
    assert (llm.route("proofread", config=client).provider, llm.route("proofread", config=client).model) == \
        ("kimi", "c-task")                                                       # client task > persona task
    monkeypatch.setenv("VSTUDIO_LLM_PROOFREAD_PROVIDER", "codex")
    monkeypatch.setenv("VSTUDIO_LLM_PROOFREAD_MODEL", "gpt-5-codex")
    r = llm.route("proofread", config=client)
    assert (r.provider, r.model, r.source) == ("codex", "gpt-5-codex", "env VSTUDIO_LLM_PROOFREAD_PROVIDER")
    r = llm.route("proofread", provider="claude", model="m", config=client)
    assert (r.provider, r.model, r.source) == ("anthropic", "m", "argument")
    r = llm.route("proofread", provider="kimi", config=client)                   # explicit provider keeps its options
    assert r.model == "c-task"


def test_routing_legacy_auto_and_unknown(monkeypatch):
    assert llm.route("proofread").provider == "none"
    monkeypatch.setenv("OPENAI_API_KEY", "sk")
    assert llm.route("proofread").provider == "none"                             # never picked implicitly
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert llm.route("proofread").provider == "anthropic"
    assert llm.route("proofread", provider="auto").provider == "anthropic"
    with pytest.raises(ValueError):
        llm.route("proofread", provider="nonsense")
    assert llm.canonical("Claude") == "anthropic" and llm.canonical("LM-Studio") == "lmstudio"


def test_route_options_reach_the_backend(monkeypatch):
    monkeypatch.setattr(llm, "_persona_llm", lambda: {"tasks": {"copy": {
        "provider": "openai-compatible", "base_url": "http://box:9000/v1", "api_key_env": "BOX_KEY", "model": "m1"}}})
    monkeypatch.setenv("BOX_KEY", "secret")
    seen = []
    fake_openai(monkeypatch, ["hello"], seen)
    r = llm.complete("copy", "s", "p")
    assert seen[0]["_client"] == dict(api_key="secret", base_url="http://box:9000/v1", timeout=600)
    assert r["provider"] == "openai-compatible" and r["model"] == "m1" and r["route"] == "persona llm.tasks.copy"
    assert "secret" not in json.dumps(llm.route("copy").as_dict())


# --------------------------------------------------------------------------- availability probe + cost
def test_availability_probe(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: "/bin/" + n if n == "claude" else None)
    monkeypatch.setattr(llm, "_cli_version", lambda exe, timeout=10: "2.1.0 (Claude Code)")
    monkeypatch.setattr(llm, "_probe_url", lambda url, timeout=0.6: (
        (True, json.dumps({"data": [{"id": "llama3.2:1b"}]}).encode()) if "11434" in url else (False, b"")))
    rows = {r["provider"]: r for r in llm.providers()}
    assert rows["claude-code"]["ready"] and "2.1.0" in rows["claude-code"]["detail"]
    assert not rows["codex"]["ready"] and "not on PATH" in rows["codex"]["detail"]
    assert rows["ollama"]["ready"] and rows["ollama"]["models"] == ["llama3.2:1b"]
    assert not rows["lmstudio"]["ready"] and rows["none"]["ready"]
    assert not rows["anthropic"]["ready"] and "ANTHROPIC_API_KEY" in rows["anthropic"]["detail"]
    assert not rows["deepseek"]["ready"] and "DEEPSEEK_API_KEY" in rows["deepseek"]["detail"]
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    assert llm.check("deepseek")["ready"] == llm._has("openai")
    assert set(rows) >= set(llm.PRESETS) | {"anthropic", "openai", "gemini", "claude-code", "codex", "none"}


def test_cost_table_and_overrides():
    u = dict(input=1_000_000, output=100_000)
    assert llm.cost_usd("anthropic", "claude-opus-5-5", u) == 6.0
    assert llm.cost_usd("ollama", "qwen3:8b", u) == 0.0 and llm.cost_usd("claude-code", None, u) == 0.0
    assert llm.cost_usd("deepseek", "deepseek-chat", u) == 3.5                       # unknown: the 2.5 / 10 estimate
    assert llm.cost_usd("deepseek", "deepseek-chat", u, prices={"deepseek-chat": [0.3, 1.0]}) == 0.4


def test_cli_commands_run(capsys, monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    assert llm.main(["providers", "--json", "--no-probe"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert {"llm", "asr", "tts", "routes"} <= set(d) and d["routes"]["proofread"]["provider"] == "none"
    assert llm.main(["test", "--provider", "codex"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False


# --------------------------------------------------------------------------- migrated call sites
def test_proofread_through_a_local_server(monkeypatch):
    from vstudio import proofread as PR
    seen = []
    fake_openai(monkeypatch, [json.dumps({"fixes": [{"i": 0, "from": "模形", "to": "模型", "why": "homophone"}]})] * 4,
                seen)
    cues = [dict(start=0.0, end=2.0, text="这个模形很好用")]
    res = PR.proofread(cues, provider="ollama", model="qwen3:8b", passes=1)
    assert res["provider"] == "ollama" and res["cues"][0]["text"] == "这个模型很好用" and res["cost_usd"] == 0.0
    assert seen[0]["_client"]["base_url"] == "http://localhost:11434/v1" and seen[0]["temperature"] == 0
    monkeypatch.setattr(llm, "_persona_llm", lambda: {"tasks": {"proofread": {"provider": "lmstudio",
                                                                              "model": "local-7b"}}})
    assert PR.resolve_provider("auto") == "lmstudio" and PR.default_model("lmstudio") == "local-7b"
    assert PR.resolve_provider("auto", task="glossary") == "none"


def test_plan_segments_with_any_provider(tmp_path, monkeypatch):
    from vstudio.batch import segplan as SP
    monkeypatch.setattr(llm, "_probe_url", lambda url, timeout=0.6: (False, b""))
    words = [dict(word=f" w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(200)]
    segs = [dict(start=words[k]["start"], end=words[k + 9]["end"], text="".join(w["word"] for w in words[k:k + 10]) + ".",
                 words=words[k:k + 10]) for k in range(0, 200, 10)]
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(dict(language="en", segments=segs)))
    with pytest.raises(SP.PlanError, match="no server answering"):
        SP.plan_segments(None, transcript=str(tp), provider="ollama", echo=False, write=False)
    with pytest.raises(SP.PlanError):
        SP.plan_segments(None, transcript=str(tp), provider="nonsense", echo=False, write=False)
    seen = {}

    def fake(system, prompt, model):
        seen["model"] = model
        return json.dumps({"segments": [{"from": 0, "to": 5, "title": "T", "score": 0.9}]}), dict(input=10, output=5)
    d = SP.plan_segments(None, transcript=str(tp), provider="ollama", call=fake, count=1, min_s=10, max_s=40,
                         echo=False, write=False)
    assert d["provider"] == "ollama" and seen["model"] == "qwen3:8b" and d["cost_usd"] > 0     # custom call: priced


def test_client_llm_section_is_validated():
    from vstudio.batch import clients as CL
    ok = CL.validate({"llm": {"default": {"provider": "ollama"}, "tasks": {"copy": "deepseek"}}})
    assert ok["llm"]["tasks"]["copy"] == "deepseek" and "_unknown" not in ok
    with pytest.raises(CL.ClientError, match="API keys"):
        CL.validate({"llm": {"default": {"provider": "deepseek", "api_key": "sk-123"}}})
    with pytest.raises(CL.ClientError):
        CL.validate({"llm": "ollama"})


# --------------------------------------------------------------------------- ASR / TTS registries
def test_asr_backend_resolution_and_compatible_server(monkeypatch):
    monkeypatch.setenv("VSTUDIO_ASR_BACKEND", "whisper-server")
    assert asr.resolve_backend("auto") == "openai-compatible" and asr.resolve_backend("mlx") == "mlx"
    with pytest.raises(ValueError):
        asr.resolve_backend("nope")
    with pytest.raises(RuntimeError, match="VSTUDIO_ASR_BASE_URL"):
        asr._run_compatible("a.wav", "zh", None, True, None)
    monkeypatch.setenv("VSTUDIO_ASR_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setattr(asr.media, "run", lambda cmd: open(cmd[-1], "wb").close())
    seen = []
    seg = dict(start=0.0, end=1.0, text="你好 world", avg_logprob=-0.2)
    fake_openai(monkeypatch, [dict(segments=[seg], words=[])], seen)
    wav = os.path.join(os.path.dirname(__file__), "..", "README.md")             # any file: ffmpeg is mocked
    out = asr._run_compatible(wav, "zh", "terms", True, None)
    assert seen[0]["_client"]["base_url"] == "http://localhost:8000/v1" and seen[0]["model"] == "whisper-1"
    assert out[0]["approx_words"] and [w["word"] for w in out[0]["words"]] == ["你", "好", " world"]
    assert out[0]["avg_logprob"] == -0.2
    rows = {r["provider"]: r for r in asr.providers(probe=False)}
    assert set(rows) == {"mlx", "faster", "openai", "openai-compatible"} and "not probed" in rows["openai-compatible"]["detail"]


def test_tts_engines_compatible_and_elevenlabs(monkeypatch, tmp_path):
    monkeypatch.setenv("VSTUDIO_TTS_ENGINE", "compatible")
    assert tts.pick_engine("auto") == "openai-compatible" and tts.pick_engine("eleven") == "elevenlabs"
    calls = []
    monkeypatch.setattr(tts, "_speech_http", lambda url, body, headers, dst, timeout=300: calls.append(
        (url, body, headers)) or open(dst, "wb").close())
    with pytest.raises(RuntimeError, match="VSTUDIO_TTS_BASE_URL"):
        tts._compatible("hi", "v", 1.0, None, "kokoro", str(tmp_path / "a.wav"))
    monkeypatch.setenv("VSTUDIO_TTS_BASE_URL", "http://localhost:8880/v1")
    tts._compatible("hi", "af_heart", 1.1, "calm", "kokoro", str(tmp_path / "a.wav"))
    assert calls[-1][0] == "http://localhost:8880/v1/audio/speech" and calls[-1][1]["speed"] == 1.1
    assert calls[-1][2] == {} and calls[-1][1]["instructions"] == "calm"
    with pytest.raises(RuntimeError, match="ELEVENLABS_API_KEY"):
        tts._elevenlabs("hi", "vid", 1.0, "eleven_multilingual_v2", str(tmp_path / "b.mp3"))
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test")
    tts._elevenlabs("hi", "vid", 2.0, "eleven_multilingual_v2", str(tmp_path / "b.mp3"))
    assert calls[-1][0].startswith("https://api.elevenlabs.io/v1/text-to-speech/vid")
    assert calls[-1][1]["voice_settings"]["speed"] == 1.2 and calls[-1][2]["xi-api-key"] == "el-test"
    rows = {r["provider"] for r in tts.providers(probe=False)}
    assert rows == {"openai", "kokoro", "edge", "clone", "elevenlabs", "openai-compatible"}
    assert tts.default_voice("elevenlabs") and tts.default_voice("openai-compatible")
