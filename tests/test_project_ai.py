"""Project-level AI edits (vstudio.project.projai / ``python -m vstudio.project ai``): one model call grouped per
output, the fast rule check that answers needs_rerender for burned-in text on flattened outputs WITHOUT a model
call, our own text removed with plain ops, the provider timeout -> fallback notice, and the CLI events contract.
Mocked model, synthetic media."""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from vstudio import llm
from vstudio.project import outputs as O
from vstudio.project import projai as PA

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
NAMES = ("A_换圈子", "B_自媒体", "C_底气")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER",
              "VSTUDIO_LLM_OUTPUT_EDIT_FALLBACK", "VSTUDIO_LLM_FALLBACK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(O, "TRANSCRIBE", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ASR here")))


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("pai")
    f = str(d / "c.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=180x320:r=15:d=2", "-f", "lavfi",
                    "-i", "sine=f=440:d=2", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", f],
                   check=True)
    return f


def _fuye(tmp_path, clip, scripts=True):
    """A work folder like the real incident: 3 flattened clips with a burned series tag set in work/ scripts."""
    w = tmp_path / "fuye"
    (w / "final").mkdir(parents=True)
    for n in NAMES:
        shutil.copy(clip, w / "final" / f"{n}.mp4")
    (w / "REPORT.md").write_text("# fuye\n")
    if scripts:
        (w / "work").mkdir()
        (w / "work" / "clipdefs.py").write_text('CLIPS = dict(\n  A=dict(\n    kicker="副业复盘",\n  ),\n)\n',
                                                encoding="utf-8")
        (w / "work" / "compose.py").write_text("from clipdefs import CLIPS\n", encoding="utf-8")
    from vstudio.project import works
    works.adopt(str(w))
    return str(w)


def _no_model(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the model must not be called")
    monkeypatch.setattr(llm, "complete", boom)
    monkeypatch.setenv("VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER", "claude-code")


def test_classify_rules():
    c = PA.classify("把副业复盘01，02，03都去掉，这不是一组视频，是单独放的")
    assert c["kind"] == "text-remove" and c["stems"] == ["副业复盘"]
    assert PA.classify("把副业复盘改成个人成长")["kind"] == "text-replace"
    assert PA.classify("字幕大一点，换成黄色")["kind"] in ("caption-restyle", "text-replace")
    assert PA.classify("字幕再大一点")["kind"] == "caption-restyle"
    assert PA.classify('remove the "Side hustle 01" label from all clips')["stems"] == ["Side hustle"]
    for t in ("去掉开头3秒", "把停顿都去掉", "再紧凑一点", "加个进度条", "1.2倍速"):
        assert PA.classify(t)["kind"] is None, t


def test_burned_text_on_flattened_outputs_needs_rerender_fast_without_model(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip)
    _no_model(monkeypatch)
    t0 = time.time()
    r = PA.plan(w, "把副业复盘01，02，03都去掉，这不是一组视频，是单独放的")
    assert time.time() - t0 < 2.0 and r["seconds"] < 2.0
    assert r["answer"] == "needs_rerender" and r["model_called"] is False and not r["groups"]
    n = r["needs_rerender"]
    assert sorted(n["outputs"]) == sorted(f"final/{x}.mp4" for x in NAMES)          # every clip, not just A
    assert n["code"] == "burned-text" and n["reason"]["message_zh"] and n["targets"] == ["副业复盘"]
    p = n["paths"][0]
    assert p["kind"] == "rerender-scripts"
    assert any(h["file"] == os.path.join("work", "clipdefs.py") and h["line"] == 3 for h in p["files"])
    kinds = [a["kind"] for a in p["actions"]]
    assert kinds[0] == "copy-prompt" and "open-file" in kinds
    assert "副业复盘" in p["prompt"] and "work/" in p["prompt"]
    assert all(a["label"]["code"].startswith("act-") for a in p["actions"])


def test_no_scripts_offers_re_export(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip, scripts=False)
    _no_model(monkeypatch)
    r = PA.plan(w, "把所有片子上的标题文字去掉")
    assert r["answer"] == "needs_rerender" and r["needs_rerender"]["paths"][0]["kind"] == "re-export"


def test_caption_restyle_on_burned_captions_needs_rerender(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip)
    _no_model(monkeypatch)
    r = PA.plan(w, "字幕都大一点")
    assert r["answer"] == "needs_rerender" and r["needs_rerender"]["code"] == "burned-captions-restyle"


def test_our_own_title_band_is_removed_with_ops_not_rerender(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip)
    O.edit(w, f"final/{NAMES[0]}.mp4", [dict(op="title", text="副业复盘 01")])
    _no_model(monkeypatch)
    r = PA.plan(w, "把副业复盘01，02，03都去掉")
    assert r["answer"] == "mixed" and r["model_called"] is False
    g = r["groups"][0]
    assert g["output"] == f"final/{NAMES[0]}.mp4" and g["ops"] == [dict(op="title", text="")]
    assert f"final/{NAMES[0]}.mp4" not in r["needs_rerender"]["outputs"] and len(r["needs_rerender"]["outputs"]) == 2


def test_project_request_one_model_call_grouped_per_output(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip)
    monkeypatch.setenv("VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER", "claude-code")
    calls = []

    def fake(task, system, prompt, schema=None, provider=None, model=None, timeout=None, **kw):
        calls.append(dict(task=task, prompt=prompt, timeout=timeout))
        ctx = json.loads(prompt.split("Context (JSON):\n", 1)[1])
        ids = [o["id"] for o in ctx["outputs"]]
        return dict(json=dict(summary="faster + progress bar", groups=[
            dict(output=i, ops=[dict(op="speed", value=1.1), dict(op="effect_add", effect="progress-bar-pil", start=0),
                                dict(op="effect_add", effect="laser-unicorn", start=0)]) for i in ids]),
            text="", usage={}, cost_usd=0.01, provider="claude-code", model="m")
    monkeypatch.setattr(llm, "complete", fake)
    events = []
    r = PA.plan(w, "所有片子都 1.1 倍速，加个进度条", on_event=events.append)
    assert len(calls) == 1 and calls[0]["task"] == "output_edit" and calls[0]["timeout"] == PA.DEFAULT_TIMEOUT
    assert all(f"final/{n}.mp4" in calls[0]["prompt"] for n in NAMES)
    assert r["answer"] == "changes" and r["model_called"] and r["needs_rerender"] is None
    assert [g["output"] for g in r["groups"]] == [f"final/{n}.mp4" for n in NAMES]
    for g in r["groups"]:
        assert [p["normalized"]["op"] for p in g["proposed"]] == ["speed", "effect_add"]
        assert [d["error"]["code"] for d in g["dropped"]] == ["unknown-effect"]
        assert g["ops"][0] == dict(op="speed", value=1.1)
    assert r["apply_all"] == dict(outputs=[f"final/{n}.mp4" for n in NAMES], ops=6)
    assert [e["stage"] for e in events if e["event"] == "stage"] == ["read", "check", "ask", "plan"]
    assert O.show(w, f"final/{NAMES[0]}.mp4")["history"]["undo"] == 0                 # nothing applied


def test_filler_word_is_not_treated_as_burned_text(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip)
    monkeypatch.setenv("VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER", "claude-code")
    seen = []
    monkeypatch.setattr(llm, "complete", lambda *a, **k: seen.append(1) or dict(
        json=dict(groups=[]), text="", usage={}, cost_usd=0, provider="claude-code", model="m"))
    r = PA.plan(w, "把「嗯」都去掉")
    assert seen and r["needs_rerender"] is None and r["answer"] == "nothing"


def test_timeout_falls_back_to_the_next_provider_with_a_notice(tmp_path, clip, monkeypatch):
    w = _fuye(tmp_path, clip)
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("claude-code", None, {"fallback": ["codex"]}, "t"))
    seen = []

    def fake(task, system, prompt, provider=None, timeout=None, **kw):
        seen.append((provider, timeout))
        if provider in (None, "claude-code"):
            raise llm.LLMError(f"claude CLI timed out after {timeout:g} s")
        return dict(text="", json=dict(groups=[]), provider="codex", model="m", usage={}, cost_usd=0.0)
    monkeypatch.setattr(llm, "_complete", fake)
    events = []
    r = PA.plan(w, "所有片子加个进度条", timeout=120, on_event=events.append)
    assert seen == [(None, 120), ("codex", 120)]
    fb = [e for e in events if e["event"] == "fallback"]
    assert fb and fb[0]["from"] == "claude-code" and fb[0]["to"] == "codex" and fb[0]["code"] == "timeout"
    assert r["provider"] == "codex" and r["fallback"]["code"] == "timeout"


def test_unknown_output_and_cli_events(tmp_path, clip):
    w = _fuye(tmp_path, clip)
    with pytest.raises(O.OutputError):
        PA.plan(w, "x", outputs="final/nope.mp4")
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib"), VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER="claude-code",
               PATH="/usr/bin:/bin:" + os.path.dirname(shutil.which("ffmpeg")))
    p = subprocess.run([sys.executable, "-m", "vstudio.project", "ai", "--project", w, "--instruction",
                        "把副业复盘01，02，03都去掉", "--outputs", f"final/{NAMES[0]}.mp4,final/{NAMES[1]}.mp4",
                        "--json-events"], capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0, p.stderr
    evs = [json.loads(x) for x in p.stdout.splitlines()]
    assert [e.get("stage") for e in evs[:2]] == ["read", "check"] and evs[-1]["event"] == "done"
    res = evs[-1]["result"]
    assert res["answer"] == "needs_rerender" and len(res["needs_rerender"]["outputs"]) == 2
    p = subprocess.run([sys.executable, "-m", "vstudio.project", "ai", "--project", w, "--instruction", "x",
                        "--outputs", "nope", "--json-events"], capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 5 and json.loads(p.stdout.splitlines()[-1])["code"] == "unknown-output"
