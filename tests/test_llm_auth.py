"""vstudio.llm auth: status parsing (incl. a login that `auth status` calls fine but whose token expired), env
stripping, login commands, the desk routes file, and the structured fallback record."""
import json
import subprocess

import pytest
from vstudio import llm, llm_auth as A

EXPIRED_PROBE = json.dumps(dict(type="result", subtype="success", is_error=True, api_error_status=401,
                                result="Failed to authenticate. API Error: 401 token expired or incorrect"))
STATUS_OK = json.dumps(dict(loggedIn=True, authMethod="claude.ai", apiProvider="firstParty", email="me@example.com",
                            orgName="Org", subscriptionType="max"))


def test_parse_claude_status_and_probe():
    st = A.parse_claude_status(STATUS_OK)
    assert st["logged_in"] and st["account"]["plan"] == "max" and st["account"]["email"] == "me@example.com"
    assert A.parse_claude_status("not json") is None
    assert A.parse_claude_status(json.dumps(dict(loggedIn=False)))["logged_in"] is False
    assert A.parse_claude_probe(1, EXPIRED_PROBE, "")[0] == "expired"
    assert A.parse_claude_probe(0, json.dumps(dict(is_error=False, result="ok")), "")[0] == "logged-in"
    nl = json.dumps(dict(is_error=True, result="Invalid API key · Please run /login"))
    assert A.parse_claude_probe(1, nl, "")[0] == "not-logged-in"
    assert A.parse_claude_probe(1, "", "boom")[0] == "error"


def test_parse_codex_status():
    assert A.parse_codex_status(0, "Logged in using ChatGPT\n", "") == dict(logged_in=True, auth_method="chatgpt")
    k = A.parse_codex_status(0, "Logged in using an API key - sk-proj-***abcd\n", "")
    assert k == dict(logged_in=True, auth_method="api-key") and "sk-" not in json.dumps(k)
    assert A.parse_codex_status(1, "", "Not logged in")["logged_in"] is False
    ev = "\n".join(json.dumps(e) for e in [dict(type="turn.failed", error=dict(message="401 Unauthorized: token expired"))])
    assert A.parse_codex_probe(1, ev, "")[0] == "expired"


def test_strip_env_prefix():
    env = dict(PATH="/bin", OPENAI_API_KEY="k", OPENAI_ORG_ID="o", CODEX_API_KEY="c", ANTHROPIC_API_KEY="a",
               ANTHROPIC_AUTH_TOKEN="t", ANTHROPIC_BASE_URL="u", HOME="/h")
    assert set(A.cli_env("codex", env)) == {"PATH", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                                            "HOME"}
    assert set(A.cli_env("claude-code", env)) == {"PATH", "OPENAI_API_KEY", "OPENAI_ORG_ID", "CODEX_API_KEY", "HOME"}


def _fake_cli(monkeypatch, replies):
    calls = []
    monkeypatch.setattr(llm.shutil, "which", lambda n: f"/bin/{n}" if n in ("claude", "codex") else None)
    monkeypatch.setattr(llm, "_cli_version", lambda exe, timeout=10: "9.9 (test)")

    def run(cmd, input=None, capture_output=None, text=None, cwd=None, timeout=None, env=None):
        calls.append(dict(cmd=cmd, env=env, input=input))
        for key, (rc, out, err) in replies.items():
            if " ".join(cmd[1:]).startswith(key):
                return subprocess.CompletedProcess(cmd, rc, out, err)
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(A.subprocess, "run", run)
    return calls


def test_status_expired_even_when_status_says_logged_in(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    calls = _fake_cli(monkeypatch, {"auth status": (0, STATUS_OK, ""), "-p": (1, EXPIRED_PROBE, ""),
                                    "login status": (0, "Logged in using ChatGPT", "")})
    rows = {r["provider"]: r for r in A.status(["claude-code", "codex", "deepseek"])}
    cc = rows["claude-code"]
    assert cc["state"] == "expired" and not cc["ready"] and cc["account"]["plan"] == "max"
    assert cc["message"]["code"] == "auth-expired" and cc["message"]["message_zh"] == "登录已过期，请重新登录"
    assert rows["codex"]["state"] == "logged-in" and rows["codex"]["ready"]
    assert rows["deepseek"]["state"] == "not-configured" and rows["deepseek"]["key_env"] == "DEEPSEEK_API_KEY"
    for c in calls:
        own = "ANTHROPIC_" if c["cmd"][0].endswith("claude") else "OPENAI_"
        assert not any(k.startswith(own) for k in c["env"]), c["cmd"]
    probe = next(c for c in calls if "-p" in c["cmd"])
    assert probe["cmd"][probe["cmd"].index("--tools") + 1] == "" and "--no-session-persistence" in probe["cmd"]
    assert "must-not-leak" not in json.dumps(rows)
    # no probe: the status command alone (not verified)
    r = A.status(["claude-code"], probe=False)[0]
    assert r["state"] == "logged-in" and r["verified"] is False


def test_status_not_installed_and_key_present(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    monkeypatch.setenv("MOONSHOT_API_KEY", "sk-secret-value")
    rows = {r["provider"]: r for r in A.status(["claude-code", "codex", "kimi"], probe=False)}
    assert rows["claude-code"]["state"] == "not-installed" and rows["claude-code"]["install"]["url"].startswith("https")
    assert rows["kimi"]["state"] == "configured" and "sk-secret-value" not in json.dumps(rows)


def test_login_commands(monkeypatch):
    _fake_cli(monkeypatch, {"auth --help": (0, "Commands:\n  login [options]  Sign in\n  logout  Log out\n", ""),
                            "login --help": (0, "  --device-auth\n", "")})
    d = A.command("claude-code")
    assert d["ok"] and d["command"] == ["/bin/claude", "auth", "login"] and "ANTHROPIC_API_KEY" in d["env_unset"]
    assert A.command("claude-code", "logout")["command"] == ["/bin/claude", "auth", "logout"]
    c = A.command("codex", variant="device")
    assert c["command"] == ["/bin/codex", "login", "--device-auth"] and "OPENAI_*" in c["env_unset"]
    assert A.command("codex", "logout")["display"] == "codex logout"
    assert A.command("deepseek")["ok"] is False


def test_cli_entry(monkeypatch, capsys):
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    assert llm.main(["auth", "status", "--json", "--no-probe", "--provider", "codex"]) == 0
    assert json.loads(capsys.readouterr().out)["providers"][0]["state"] == "not-installed"
    assert llm.main(["auth", "login", "--provider", "codex", "--json"]) == 1


def test_routes_file_and_env_fallback(monkeypatch, tmp_path):
    f = tmp_path / "routes.json"
    f.write_text(json.dumps({"default": {"provider": "codex", "fallback": ["claude-code"]},
                             "tasks": {"output_edit": {"provider": "ollama", "model": "qwen3:8b",
                                                       "fallback": ["codex"]}}}))
    monkeypatch.setenv("VSTUDIO_LLM_ROUTES_FILE", str(f))
    r = llm.route("output_edit")
    assert (r.provider, r.model, r.opts["fallback"], r.source) == ("ollama", "qwen3:8b", ["codex"],
                                                                   "desk llm.tasks.output_edit")
    assert llm.route("copy").provider == "codex" and llm.route("copy").source == "desk llm.default"
    monkeypatch.setenv("VSTUDIO_LLM_COPY_PROVIDER", "kimi")
    monkeypatch.setenv("VSTUDIO_LLM_COPY_FALLBACK", "codex, ollama")
    assert llm.route("copy").opts["fallback"] == ["codex", "ollama"]
    f.write_text("{broken")
    assert llm.route("output_edit").source != "desk llm.tasks.output_edit"


def test_fallback_record(monkeypatch):
    def fake(task, system, prompt, provider=None, **kw):
        if provider in (None, "claude-code"):
            raise llm.LLMError("claude CLI: Failed to authenticate. API Error: 401 token expired or incorrect")
        return dict(text="{}", json={}, provider=provider, model="m", usage={}, cost_usd=0.0)
    monkeypatch.setattr(llm, "_complete", fake)
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("claude-code", None,
                                                                 {"fallback": ["claude-code", "codex"]}, "t"))
    out = llm.complete("output_edit", "s", "p", schema=True)
    fb = out["fallback"]
    assert fb["from"] == "claude-code" and fb["to"] == "codex" and fb["code"] == "auth-expired"


@pytest.mark.parametrize("text,code", [
    ("claude CLI: Not logged in · Please run /login", "not-logged-in"),
    ("claude CLI: 401 token expired", "auth-expired"),
    ("provider codex needs the Codex CLI (`codex`) on PATH", "not-installed"),
    ("provider deepseek needs DEEPSEEK_API_KEY", "key-missing"),
    ("codex CLI: rate limit reached", "rate-limited"),
    ("claude CLI timed out after 60 s", "timeout"),
    ("something else", "failed")])
def test_failure_code(text, code):
    assert llm.failure_code(text) == code
