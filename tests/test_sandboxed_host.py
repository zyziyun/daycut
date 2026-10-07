"""The desk's Mac App Store (sandboxed) build: no user-installed CLIs (VSTUDIO_LLM_NO_CLI=1), no Chrome binary
(VSTUDIO_NO_CHROME=1), HTML rendered by the host app (VSTUDIO_HTML_RENDER_URL)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from vstudio import llm, llm_auth, render


def test_cli_route_is_skipped_and_the_fallback_answers(monkeypatch):
    monkeypatch.setenv("VSTUDIO_LLM_NO_CLI", "1")
    calls = []

    def fake(task, system, prompt, provider=None, **kw):
        calls.append(provider)
        return dict(text="{}", json={}, provider=provider, model="m", usage={}, cost_usd=0.0)
    monkeypatch.setattr(llm, "_complete", fake)
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("claude-code", None, {"fallback": ["codex", "openai"]}, "t"))
    out = llm.complete("intake", "s", "p", schema=True)
    assert calls == ["openai"]                      # neither CLI was run
    assert out["provider"] == "openai"
    assert [a["code"] for a in out["failed_attempts"]] == ["unavailable", "unavailable"]


def test_cli_only_route_fails_with_unavailable(monkeypatch):
    monkeypatch.setenv("VSTUDIO_LLM_NO_CLI", "1")
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: pytest.fail("nothing may run"))
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("codex", None, {}, "t"))
    with pytest.raises(llm.LLMError) as e:
        llm.complete("intake", "s", "p")
    assert llm.failure_code(e.value) == "unavailable"


def test_auth_status_and_login_command_say_unavailable(monkeypatch):
    monkeypatch.setenv("VSTUDIO_LLM_NO_CLI", "1")
    monkeypatch.setattr(llm, "find_cli", lambda *a, **k: pytest.fail("no CLI lookup"))
    rows = {r["provider"]: r for r in llm_auth.status(["claude-code", "codex"], probe=False)}
    assert rows["claude-code"]["state"] == rows["codex"]["state"] == "unavailable"
    assert not rows["codex"]["can_login"]
    cmd = llm_auth.command("claude-code")
    assert cmd["ok"] is False and cmd["message"]["code"] == "auth-unavailable"


def test_no_chrome_switch(monkeypatch):
    monkeypatch.setenv("VSTUDIO_NO_CHROME", "1")
    monkeypatch.setenv("CHROME", "/bin/sh")
    assert render.chrome_candidates() == [] and render.find_chrome() is None


class _Host(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["content-length"])))
        _Host.seen.append((self.headers.get("authorization"), body))
        with open(body["out"], "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        data = json.dumps(dict(ok=True, out=body["out"], width=body["width"], height=body["height"])).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_html_rendered_by_the_host_app(monkeypatch, tmp_path):
    srv = HTTPServer(("127.0.0.1", 0), _Host)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("VSTUDIO_HTML_RENDER_URL", f"http://127.0.0.1:{srv.server_port}/render")
        monkeypatch.setenv("VSTUDIO_HTML_RENDER_TOKEN", "t0k")
        monkeypatch.setattr(render, "find_chromes", lambda: pytest.fail("no Chrome lookup"))
        page = tmp_path / "cover.html"
        page.write_text("<html><body>hi</body></html>", encoding="utf-8")
        out = render.html_to_png(str(page), str(tmp_path / "c.png"), size=(1080, 1440), scale=2, wait=300,
                                 use_persona=False, fonts=False)
        assert out == str((tmp_path / "c.png").resolve())
        auth, body = _Host.seen[-1]
        assert auth == "Bearer t0k"
        assert body["file"] == str(page.resolve()) and (body["width"], body["height"], body["scale"]) == (1080, 1440, 2)
    finally:
        srv.shutdown()


def test_anthropic_without_the_sdk_uses_plain_https(monkeypatch):
    import builtins
    import io
    real_import = builtins.__import__

    def no_sdk(name, *a, **k):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_sdk)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    seen = {}

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        seen.update(url=req.full_url, headers={k.lower(): v for k, v in req.header_items()},
                    body=json.loads(req.data))
        return Resp(json.dumps(dict(content=[dict(type="text", text='{"ok": true}')], stop_reason="end_turn",
                                    usage=dict(input_tokens=12, output_tokens=3), model="claude-x")).encode())
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    text, usage, model = llm._anthropic("sys", "hi", "claude-x", True, 100, 30, {})
    assert text == '{"ok": true}' and usage == dict(input=12, output=3) and model == "claude-x"
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "sk-test" and seen["headers"]["anthropic-version"] == "2023-06-01"
    assert seen["body"]["messages"] == [{"role": "user", "content": "hi"}] and seen["body"]["system"] == "sys"
    row = llm_auth._api("anthropic")
    assert row["ready"] is True


def test_lgpl_ffmpeg_skips_gpl_polish_filters(monkeypatch):
    from vstudio import media
    g = ("[0:v]scale='if(gt(iw,ih),1920,1080)':-2[v];"
         "[v]hqdn3d=1.2:1.2:3:3,eq=contrast=1.06:brightness=0.015,colorbalance=rs=-0.02,format=yuv420p[vg]")
    out, dropped = media.portable_graph(g, {"scale", "colorbalance", "format"})
    assert dropped == ["hqdn3d", "eq"]
    assert out == ("[0:v]scale='if(gt(iw,ih),1920,1080)':-2[v];"
                   "[v]null,null,colorbalance=rs=-0.02,format=yuv420p[vg]")
    assert media.portable_graph("[a]eq=gamma=1.1[b]", set())[0] == "[a]null[b]"
    assert media.portable_graph(g, {"hqdn3d", "eq"}) == (g, [])
    monkeypatch.setattr(media, "_filters", lambda b: frozenset({"scale", "format"}))
    cmd = media._portable_cmd(["/x/ffmpeg", "-i", "a.mp4", "-vf", "hqdn3d=1,format=yuv420p", "b.mp4"])
    assert cmd[4] == "null,format=yuv420p"
    keep = ["/x/ffprobe", "-vf", "eq=1"]
    assert media._portable_cmd(keep) is keep


def test_glossary_without_usable_ai_falls_back_to_rules(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from vstudio import proofread as PR
    from vstudio.batch import stages
    real = PR.build_glossary
    seen = []

    def build(text, provider="auto", **kw):
        seen.append(provider)
        if provider != "none":
            err = llm.LLMError("provider openai needs OPENAI_API_KEY")
            err.attempts = [dict(provider="openai", code="key-missing", error=str(err))]
            raise err
        return real(text, provider=provider, **kw)
    monkeypatch.setattr(PR, "build_glossary", build)
    monkeypatch.setattr(stages, "transcript_text", lambda tr, tf: "hello world")
    monkeypatch.setattr(stages, "proofread_opts", lambda spec: dict(call=None, glossary_provider="openai",
                                                                     glossary_model=None, provider="openai", model=None))
    (tmp_path / "t.json").write_text("{}", encoding="utf-8")
    logs = []
    ctx = SimpleNamespace(spec={}, params={}, inputs={"asr": {"transcript": str(tmp_path / "t.json")}},
                          path=lambda n: str(tmp_path / n), log=logs.append)
    out = stages.run_glossary(ctx)
    assert seen[-1] == "none" and out["terms"] == 0
    assert any("AI unavailable (key-missing)" in m for m in logs)
    assert json.load(open(out["glossary"]))["degraded"]["codes"] == ["key-missing"]
