"""P0-4: the fallback chain works on every AI path (segplan, proofread, glossary, planner, intake, output ai,
project ai), Codex gets a strict schema or none, a total failure lists every attempt, CLI timeouts, and a known-
expired Claude login is skipped / reported at once (vstudio.llm_auth cache)."""
import json
import subprocess

import pytest
from vstudio import llm, llm_auth as A

CHAIN = llm.Route("claude-code", None, {"fallback": ["codex"]}, "persona llm.default")
EXPIRED = "claude CLI: Failed to authenticate. API Error: 401 token expired or incorrect"


def _routes(monkeypatch, r=CHAIN):
    monkeypatch.setattr(llm, "route", lambda task="default", provider=None, model=None, config=None:
                        r if not provider else llm.Route(llm.canonical(provider), model, {}, "argument"))


def _fake_complete(monkeypatch, ok=("codex",), seen=None, text='{"ok": true}'):
    def fake(task, system, prompt, provider=None, model=None, cli_timeout=None, **kw):
        p = llm.canonical(provider) or "claude-code"
        if seen is not None:
            seen.append(dict(task=task, provider=provider, model=model, cli_timeout=cli_timeout))
        if p not in ok:
            raise llm.LLMError(EXPIRED if p == "claude-code" else f"{p} CLI failed (exit 1): boom")
        return dict(text=text, json=json.loads(text), provider=p, model=f"{p}-m", usage=dict(input=1, output=1),
                    cost_usd=0.0)
    monkeypatch.setattr(llm, "_complete", fake)


# ------------------------------------------------------------------ strict schema (Codex)
def test_strict_schema_is_recursive_and_refuses_free_form_objects():
    s = llm.strict_schema({"type": "object", "properties": {
        "segments": {"type": "array", "items": {"type": "object", "properties": {
            "from": {"type": "integer"}, "note": {"type": "string"}}, "required": ["from"]}},
        "mode": {"type": "string", "enum": ["a", "b"]}}, "required": ["segments"]})
    assert s["additionalProperties"] is False and s["required"] == ["segments", "mode"]
    it = s["properties"]["segments"]["items"]
    assert it["additionalProperties"] is False and it["required"] == ["from", "note"]
    assert it["properties"]["note"]["type"] == ["string", "null"] and it["properties"]["from"]["type"] == "integer"
    assert s["properties"]["mode"]["enum"] == ["a", "b", None]
    # output ai's schema: {"ops": [free-form objects]} cannot be strict -> None (JSON by instruction)
    assert llm.strict_schema({"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}}},
                              "required": ["ops"]}) is None
    assert llm.strict_schema({"type": "object"}) is None
    assert llm.strict_schema({"type": "object", "properties": {"a": {"type": "string"}},
                              "additionalProperties": True}) is None


def _codex_run(monkeypatch, reject_schema=False):
    monkeypatch.setattr(llm.shutil, "which", lambda n: "/opt/bin/codex" if n == "codex" else None)
    calls = []

    def run(cmd, input=None, capture_output=None, text=None, cwd=None, timeout=None, env=None):
        sch = None
        if "--output-schema" in cmd:
            with open(cmd[cmd.index("--output-schema") + 1]) as f:
                sch = json.load(f)
        calls.append(dict(cmd=cmd, input=input, schema=sch, timeout=timeout))
        if reject_schema and sch is not None:
            ev = dict(type="error", message="400 invalid_json_schema: 'additionalProperties' is required to be "
                                            "supplied and to be false")
            return subprocess.CompletedProcess(cmd, 1, json.dumps(ev), "")
        with open(cmd[cmd.index("--output-last-message") + 1], "w") as f:
            f.write('{"ops": [{"op": "trim"}]}')
        return subprocess.CompletedProcess(cmd, 0, json.dumps(dict(type="turn.completed", usage={})), "")
    monkeypatch.setattr(llm.subprocess, "run", run)
    return calls


def test_codex_free_form_schema_goes_by_instruction(monkeypatch):
    calls = _codex_run(monkeypatch)
    schema = {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "object"}}},
              "required": ["ops"]}
    r = llm.complete("output_edit", "SYS", "P", provider="codex", schema=schema)
    assert r["json"] == {"ops": [{"op": "trim"}]} and calls[0]["schema"] is None and "--output-schema" not in \
        calls[0]["cmd"]
    assert '"ops"' in calls[0]["input"]                       # the schema rides in the instruction


def test_codex_strict_schema_and_retry_when_rejected(monkeypatch):
    calls = _codex_run(monkeypatch)
    schema = {"type": "object", "properties": {"ops": {"type": "array", "items": {"type": "string"}}}}
    llm.complete("copy", "SYS", "P", provider="codex", schema=schema)
    assert calls[0]["schema"]["additionalProperties"] is False and calls[0]["schema"]["required"] == ["ops"]
    calls = _codex_run(monkeypatch, reject_schema=True)
    r = llm.complete("copy", "SYS", "P", provider="codex", schema=schema)
    assert len(calls) == 2 and calls[0]["schema"] and calls[1]["schema"] is None and r["json"]


# ------------------------------------------------------------------ chain, attempts, timeouts
def test_all_providers_failed_lists_every_attempt(monkeypatch):
    _routes(monkeypatch)
    _fake_complete(monkeypatch, ok=())
    with pytest.raises(llm.AllProvidersFailed) as ei:
        llm.complete("output_edit", "s", "p", schema=True)
    e = ei.value
    assert e.tried == ["claude-code", "codex"] and e.codes == ["auth-expired", "failed"]
    assert "401" in e.errors[0] and "boom" in e.errors[1] and "codex" in str(e) and e.info["code"] == "llm-all-failed"
    info = llm.error_info(e)
    assert info["tried"] == ["claude-code", "codex"] and info["code"] == "auth-expired"


def test_resolved_provider_is_not_pinned(monkeypatch):
    """A caller that resolved the route and passes the provider back keeps the chain; another provider pins."""
    _routes(monkeypatch)
    seen = []
    _fake_complete(monkeypatch, seen=seen)
    r = llm.complete("segment_plan", "s", "p", provider="claude-code", model="opus")
    assert r["provider"] == "codex" and r["fallback"]["from"] == "claude-code" and r["fallback"]["code"] == \
        "auth-expired"
    assert seen[1]["model"] is None                       # the fallback never gets the first provider's model
    assert r["failed_attempts"][0]["provider"] == "claude-code"
    with pytest.raises(llm.LLMError) as ei:
        llm.complete("segment_plan", "s", "p", provider="claude-code", fallback=False)
    assert ei.value.attempts[0]["code"] == "auth-expired"
    _fake_complete(monkeypatch, ok=("codex",))
    with pytest.raises(llm.LLMError):                      # an explicit different provider: no chain
        llm.complete("segment_plan", "s", "p", provider="ollama")


def test_cli_timeout_reaches_the_cli(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: "/opt/bin/claude" if n == "claude" else None)
    seen = []

    def run(cmd, input=None, capture_output=None, text=None, cwd=None, timeout=None, env=None):
        seen.append(timeout)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(dict(result='{"a": 1}', usage={})), "")
    monkeypatch.setattr(llm.subprocess, "run", run)
    llm.complete("output_edit", "s", "p", provider="claude-code", schema=True, timeout=600, cli_timeout=60)
    monkeypatch.setenv("VSTUDIO_LLM_CLI_TIMEOUT", "33")
    llm.complete("output_edit", "s", "p", provider="claude-code", schema=True, timeout=600)
    assert seen == [60.0, 33.0]


def test_known_expired_login_is_skipped_at_once(monkeypatch):
    """After one 401 the expired Claude login is cached: the next call goes straight to Codex (no claude run)."""
    monkeypatch.setattr(llm.shutil, "which", lambda n: f"/opt/bin/{n}" if n in ("claude", "codex") else None)
    runs = []

    def run(cmd, input=None, capture_output=None, text=None, cwd=None, timeout=None, env=None):
        runs.append(" ".join(cmd[1:3]))
        if cmd[0].endswith("claude"):
            if cmd[1:3] == ["auth", "status"]:
                return subprocess.CompletedProcess(cmd, 0, '{"loggedIn": true}', "")
            return subprocess.CompletedProcess(cmd, 1, json.dumps(dict(is_error=True, result=EXPIRED)), "")
        if cmd[1:3] == ["login", "status"]:
            return subprocess.CompletedProcess(cmd, 0, "Logged in using ChatGPT", "")
        with open(cmd[cmd.index("--output-last-message") + 1], "w") as f:
            f.write('{"ok": true}')
        return subprocess.CompletedProcess(cmd, 0, json.dumps(dict(type="turn.completed", usage={})), "")
    monkeypatch.setattr(llm.subprocess, "run", run)
    monkeypatch.setattr(A.subprocess, "run", run)
    monkeypatch.setattr(llm, "_persona_llm", lambda: {"default": {"provider": "claude-code", "fallback": ["codex"]}})
    r1 = llm.complete("intake", "s", "p", schema=True, retries=0)
    assert r1["provider"] == "codex" and A.known_expired("claude-code")
    runs.clear()
    r2 = llm.complete("intake", "s", "p", schema=True, retries=0)
    assert r2["provider"] == "codex" and r2["failed_attempts"][0]["cached"]
    assert "-p --output-format" not in runs                 # claude -p never ran again
    # auth status reports it instantly too
    row = A.status(["claude-code"])[0]
    assert row["state"] == "expired" and row["probe"]["cached"]
    A.forget("claude-code")
    assert not A.known_expired("claude-code")


# ------------------------------------------------------------------ the callers
def _transcript(tmp_path):
    words = [dict(word=f" w{i}", start=i * 0.5, end=i * 0.5 + 0.4) for i in range(200)]
    segs = [dict(start=words[k]["start"], end=words[k + 9]["end"], text="".join(w["word"] for w in words[k:k + 10])
                 + ".", words=words[k:k + 10]) for k in range(0, 200, 10)]
    tp = tmp_path / "t.json"
    tp.write_text(json.dumps(dict(language="en", segments=segs)))
    return str(tp)


def test_plan_segments_auto_falls_back(tmp_path, monkeypatch):
    from vstudio.batch import segplan as SP
    _routes(monkeypatch)
    seen = []
    _fake_complete(monkeypatch, seen=seen, text=json.dumps({"segments": [{"from": 0, "to": 5, "title": "T",
                                                                          "score": 0.9}]}))
    monkeypatch.setattr(llm, "check", lambda *a, **k: dict(ready=False, detail="`claude` not on PATH"))
    d = SP.plan_segments(None, transcript=_transcript(tmp_path), provider="auto", count=1, min_s=10, max_s=40,
                         echo=False, write=False)
    assert d["provider"] == "codex" and d["fallback"]["from"] == "claude-code" and d["fallback"]["routed"] == \
        "claude-code"
    assert any(n["code"] == "plan-fallback" for n in d["notices"])
    assert seen[0]["provider"] is None and seen[0]["cli_timeout"] == SP.DEFAULT_CLI_TIMEOUT


def test_plan_segments_cli_reports_every_attempt(tmp_path, monkeypatch, capfd):
    from vstudio.batch import cli as BC
    _routes(monkeypatch)
    _fake_complete(monkeypatch, ok=())
    rc = BC.main(["plan-segments", "--transcript", _transcript(tmp_path), "--source", _transcript(tmp_path),
                  "--json", "--count", "1", "--min", "10", "--max", "40", "--out", str(tmp_path / "o")])
    d = json.loads(capfd.readouterr().out)
    assert rc == 5 and d["ok"] is False and d["tried"] == ["claude-code", "codex"] and d["codes"][0] == "auth-expired"


def test_proofread_and_glossary_fall_back(monkeypatch):
    from vstudio import proofread as PR
    _routes(monkeypatch)
    _fake_complete(monkeypatch, text='{"fixes": []}')
    cues = [dict(start=0, end=1, text="这个模型很好用")]
    r = PR.proofread(cues, provider="auto", passes=1)
    assert r["fallback"] and r["fallback"]["to"] == "codex"
    _fake_complete(monkeypatch, text='{"terms": ["LLM"], "fixes": []}')
    g = PR.build_glossary("我们讲 LLM", provider="auto")
    assert g["terms"] == ["LLM"]


def test_claude_planner_uses_the_route(monkeypatch, tmp_path):
    from vstudio.batch import planner as PL
    _routes(monkeypatch)
    seen = []
    _fake_complete(monkeypatch, seen=seen, text='{"segments": [{"range": ["0:00", "0:20"], "title": "A"}]}')
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(PL, "build_requests", lambda spec, words: [dict(custom_id="c1", params=dict(
        model="claude-opus-5-5", max_tokens=100, system=[dict(text="S")], messages=[dict(content="M")]))])
    monkeypatch.setattr(PL, "_transcript_words", lambda tr: [])
    tr = tmp_path / "tr.json"
    tr.write_text("{}")
    with pytest.raises(PL.PlannerUnavailable, match="wrote 1"):
        PL.ClaudePlanner(sync=True).rows(dict(_dir=str(tmp_path), inputs=dict(transcript=str(tr))))
    assert seen[0]["provider"] is None and seen[-1]["provider"] == "codex"


def test_output_ai_error_lists_attempts(monkeypatch):
    from vstudio.project import outputs as O
    e = O.llm_failed(llm.AllProvidersFailed([dict(provider="claude-code", code="auth-expired", error=EXPIRED),
                                             dict(provider="codex", code="failed", error="codex: 400")]),
                     "claude-code")
    p = e.info["params"]
    assert e.info["code"] == "llm-failed" and p["tried"] == ["claude-code", "codex"] and p["codes"] == \
        ["auth-expired", "failed"] and "codex" in e.info["message"] and e.info["message_zh"].startswith("所有")


def test_a_cli_that_timed_out_is_skipped_for_a_while(monkeypatch, tmp_path):
    """A dead / hung `claude -p` costs the full CLI timeout once; the next calls go straight to Codex until it answers
    again (bug bash: real-engine planning took 146 s every time, 120 s of it waiting for Claude Code)."""
    monkeypatch.setenv("VSTUDIO_AUTH_CACHE", str(tmp_path / "auth.json"))
    _routes(monkeypatch)
    calls = []

    def fake(task, system, prompt, provider=None, model=None, cli_timeout=None, **kw):
        p = llm.canonical(provider) or "claude-code"
        calls.append(p)
        if p == "claude-code":
            raise llm.LLMError("claude CLI timed out after 120 s")
        return dict(text="{}", json={}, provider=p, model="m", usage=dict(input=1, output=1), cost_usd=0.0)
    monkeypatch.setattr(llm, "_complete", fake)
    monkeypatch.setattr(A, "fingerprint", lambda provider, status_out=None: "fp")
    r1 = llm.complete("intake", "s", "p", retries=0)
    assert r1["provider"] == "codex" and calls == ["claude-code", "codex"] and A.known_unresponsive("claude-code")
    calls.clear()
    r2 = llm.complete("intake", "s", "p", retries=0)
    assert r2["provider"] == "codex" and calls == ["codex"]                     # no second 120 s wait
    assert r2["failed_attempts"][0]["code"] == "timeout" and r2["failed_attempts"][0]["cached"]
    # without a fallback it is still tried (better a slow answer than none)
    calls.clear()
    with pytest.raises(llm.LLMError):
        llm.complete("intake", "s", "p", retries=0, fallback=False)
    assert calls == ["claude-code"]
    # it answers again -> the record clears
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: dict(text="{}", json={}, provider="claude-code", model="m",
                                                                usage=dict(input=1, output=1), cost_usd=0.0))
    monkeypatch.setenv("VSTUDIO_LLM_UNRESPONSIVE_TTL", "0")
    assert not A.known_unresponsive("claude-code")
    llm.complete("intake", "s", "p", retries=0)
    monkeypatch.delenv("VSTUDIO_LLM_UNRESPONSIVE_TTL")
    assert not A.known_unresponsive("claude-code")
