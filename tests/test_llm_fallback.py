import pytest
from vstudio import llm


def test_fallback_chain_on_auth_failure(monkeypatch):
    calls = []

    def fake(task, system, prompt, provider=None, **kw):
        calls.append(provider)
        if provider in (None, "claude-code"):
            raise llm.LLMError("claude CLI: 401 token expired")
        return dict(text="{}", json={}, provider=provider, model="m", usage={}, cost_usd=0.0)
    monkeypatch.setattr(llm, "_complete", fake)
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("claude-code", None, {"fallback": ["codex"]}, "t"))
    out = llm.complete("intake", "s", "p", schema=True)
    assert out["provider"] == "codex" and out["fallback_from"] and calls == [None, "codex"]


def test_explicit_provider_has_no_fallback(monkeypatch):
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: (_ for _ in ()).throw(llm.LLMError("x")))
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("claude-code", None, {"fallback": ["codex"]}, "t"))
    with pytest.raises(llm.LLMError):
        llm.complete("intake", "s", "p", provider="claude-code")
