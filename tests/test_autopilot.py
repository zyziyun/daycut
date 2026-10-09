"""vstudio.project autopilot: the rules per checkpoint kind (consent / spend cap / red QC / missing input are the only
blockers), the AI judge (a fake model: its pick is used and recorded with its reason; a broken reply or no model
falls back to the rules), the decision log, `run --autopilot` on a real talking-head project (no pilot stop, no
question, every decision listed), and taking one decision back into her Inbox."""
import json
import os
import shutil
import subprocess
import sys

import pytest

import _batch_helpers as H
from vstudio.project import autopilot as AP
from vstudio.project import inbox as IB
from vstudio.project.core import Project

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HAS_FFMPEG = bool(shutil.which("ffmpeg"))
WORDS = [("大家", .4), ("好", .3), ("嗯", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35), ("方法", .4),
         ("这个", .3), ("方法", .4), ("很", .25), ("好用", .4), ("第二", .4), ("个", .25), ("例子", .4), ("也", .3),
         ("很", .25), ("重要", .4), ("最后", .4), ("总结", .4), ("一下", .35)]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    monkeypatch.setenv("VSTUDIO_LLM_PROVIDER", "none")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def cp(kind, **kw):
    return dict(id=kw.pop("id", kind), kind=kind, scope=kw.pop("scope", "item"), labels={"en": kind}, **kw)


# --------------------------------------------------------------------------- rules
def test_rules_only_block_on_consent_spend_red_qc_and_missing_input():
    assert AP.rules(cp("consent"), {})["blocker"] == "consent"
    b = AP.rules(cp("budget-approval"), dict(total_credits=40, unknown_items=[]), spend_cap=20)
    assert b["blocker"] == "spend-cap" and b["params"] == dict(total=40.0, cap=20)
    ok = AP.rules(cp("budget-approval"), dict(total_credits=12, unknown_items=[]), spend_cap=20)
    assert ok["value"] == dict(approve=True, budget=12.0) and ok["by"] == "rules"
    assert AP.rules(cp("budget-approval"), dict(total_credits=0, unknown_items=["a"]), spend_cap=99)["blocker"] == \
        "spend-cap"
    red = AP.rules(cp("publish"), dict(default=None, qc=dict(status="red", reasons=["caption missing"])))
    assert red["blocker"] == "qc-red" and red["params"]["reasons"] == ["caption missing"]
    green = AP.rules(cp("publish"), dict(default=dict(approve=True), qc=dict(status="green")))
    assert green["value"] == dict(approve=True) and green["reason_code"] == "qc-passed"
    assert AP.rules(cp("author"), dict(default=None, file="/x/SCRIPT.md"))["blocker"] == "needs-input"
    assert AP.rules(cp("author"), dict(default=dict(done=True)))["value"] == dict(done=True)
    f = AP.rules(cp("filler-confirm"), dict(options=[dict(id=1, confidence=.9), dict(id=2, confidence=.3),
                                                      dict(id=3)], default=dict(approve=[], keep=[])))
    assert f["value"] == dict(approve=[1], keep=[2, 3]) and f["params"] == dict(cut=1, kept=2, n=3)
    assert AP.rules(cp("hook-pick"), dict(default=dict(pick=-1)))["params"] == dict(pick=-1)
    assert AP.rules(cp("cover-pick"), dict(default=dict(pick=0)))["value"] == dict(pick=0)


# --------------------------------------------------------------------------- the AI judge
def fake_model(reply, seen=None):
    def complete(task, system, prompt, **kw):
        if seen is not None:
            seen.append(dict(task=task, prompt=prompt))
        return dict(json=reply, text=json.dumps(reply), provider="claude-code", model="test")
    return complete


def test_judge_uses_the_models_pick_with_its_reason_and_falls_back_to_rules():
    c = cp("filler-confirm")
    pay = dict(options=[dict(id=1, text="嗯", confidence=.4), dict(id=2, text="然后", confidence=.9)])
    seen = []
    d = AP.judge(c, pay, "cut this talk", "zh", complete=fake_model(dict(approve=[1, 2, 9], reason="都是口癖"), seen))
    assert d["value"] == dict(approve=[1, 2], keep=[]) and d["by"] == "ai" and d["reason"] == "都是口癖"
    assert d["provider"] == "claude-code" and d["params"] == dict(cut=2, kept=0, n=2)
    assert seen[0]["task"] == "planner" and "Simplified Chinese" in seen[0]["prompt"]
    # hooks are never picked by a model (her rule: no cold open unless her format asks)
    assert AP.judge(cp("hook-pick"), dict(options=[dict(text="a")]), complete=fake_model(dict(pick=0))) is None
    bad = AP.judge(c, pay, complete=fake_model(dict(pick=7)))
    assert bad == dict(error="the model's answer did not fit the options")

    def boom(*a, **k):
        raise RuntimeError("401 not logged in")
    assert "401" in AP.judge(c, pay, complete=boom)["error"]
    assert AP.judge(cp("cover-pick"), dict(options=[1]), complete=boom) is None     # not a taste call for a model


# --------------------------------------------------------------------------- a real project
def _preproduction(tmp_path, episodes=2):
    return Project.create(str(tmp_path / "pp"), recipe="preproduction", episodes=episodes)


def test_autopilot_records_blockers_and_skips_the_pilot(tmp_path):
    """A script only she can write is a real blocker: autopilot runs every item (no pilot stop), parks each at the
    lock, logs why, and the Inbox asks her."""
    p = _preproduction(tmp_path)
    r = p.run(pilot=1, autopilot=True)
    assert r["batch_status"] != "pilot-review" and r["autopilot"] is True
    assert {x["item"] for x in r["pending"]} == {"ep01", "ep02"} and r["exit_code"] == 7
    assert {b["item"] for b in r["blocked"]} == {"ep01", "ep02"}
    ev = [e for e in AP.history(p) if e["event"] == "blocked"]
    assert {e["blocker"] for e in ev} == {"needs-input"}
    assert Project(p.dir).data["autopilot"]["on"] is True          # kept for the next resume
    assert {e["item"] for e in IB.inbox()["entries"] if e.get("project") == p.dir} == {"ep01", "ep02"}


def cli(*args):
    e = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(ROOT, "lib"), os.path.join(ROOT, "tests")]))
    return subprocess.run([sys.executable, "-m", "vstudio.project", *args], capture_output=True, text=True, env=e)


def test_cli_autopilot_flags_persist_and_ask_first_switches_back(tmp_path):
    p = _preproduction(tmp_path, episodes=1)
    r = cli("run", "--dir", p.dir, "--autopilot", "--spend-cap", "15", "--lang", "fr", "--json")
    assert r.returncode == 7, r.stderr
    d = json.loads(cli("decisions", "--dir", p.dir, "--history", "--json").stdout)
    assert d["autopilot"] == dict(on=True, spend_cap=15.0, judge=True, ask=[], lang="fr")
    assert d["decisions"] == [] and d["history"][0]["blocker"] == "needs-input"
    r = cli("resume", "--dir", p.dir, "--ask-first", "--json")
    assert json.loads(r.stdout)["autopilot"] is False
    r = cli("autopilot", "--dir", p.dir, "--on", "--spend-cap", "3", "--no-judge", "--json")   # switch, no run
    assert json.loads(r.stdout)["autopilot"] == dict(on=True, spend_cap=3.0, judge=False, ask=[], lang="fr")


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("synth")
    x, truth, dur = H.synth_speech(WORDS)
    src = H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    return dict(video=src, truth=str(tp))


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_talkinghead_on_autopilot_runs_to_done_and_a_decision_can_be_taken_back(tmp_path, synth, monkeypatch):
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", synth["truth"])
    p = Project.create(str(tmp_path / "th"), recipe="talkinghead", inputs=dict(video=[synth["video"]]),
                       params=dict(pipeline="fast", preset="ultrafast", speed=1.0),
                       spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                 asr=dict(transcriber="_batch_helpers:fake_transcriber"),
                                 proofread=dict(enabled=False)))
    asked = []
    judge = fake_model(dict(approve=[], keep=[1], reason="keep the pauses that carry emphasis"), asked)
    events = []
    r = p.run(pilot=1, autopilot=True, judge=judge, on_event=events.append)
    qc_red = any(b["checkpoint"] == "publish" for b in r["blocked"])
    assert r["exit_code"] == 0 or (qc_red and r["exit_code"] == 7), r
    assert not [x for x in r["pending"] if x["id"] != "publish"]                # nothing but a red QC waits
    ds = {d["checkpoint"]: d for d in AP.decisions(Project(p.dir))}
    assert {"hook", "cover"} <= set(ds), ds
    assert ds["hook"]["by"] == "rules" and ds["hook"]["reason_code"] == "hook-default"
    assert ds["hook"]["value"] == dict(pick=-1)                                  # no cold open: her style
    assert ds["cover"]["by"] == "rules" and ds["cover"]["reason_code"] == "cover-best"
    assert ds["hook"]["payload"] and os.path.exists(ds["hook"]["payload"])      # what was decided on
    if "filler" in ds:                                                           # unsure cuts: the AI judged them
        assert ds["filler"]["by"] == "ai" and ds["filler"]["reason"] == "keep the pauses that carry emphasis"
        assert asked and asked[0]["task"] == "planner"
    assert all(e.get("by") for e in events if e["event"] == "auto-answer")
    # she takes the cover back: the next run stops at it and leaves it to her (the Inbox asks)
    q = Project(p.dir)
    out = AP.reopen(q, "cover", "talk")
    assert out["rerun"]["talk"][0] == "cp_cover"
    r = Project(p.dir).run(judge=judge)
    assert [x["id"] for x in r["pending"]] == ["cover"] and r["exit_code"] == 7
    assert {"checkpoint": "cover", "item": "talk"} in r["blocked"]
    assert any(d.get("asked") for d in AP.decisions(Project(p.dir)))
    q = Project(p.dir)
    q.answer("cover", dict(pick=1, text="一个方法"))
    assert Project(p.dir).data["autopilot"]["ask"] == []
    r = Project(p.dir).run(judge=judge)
    assert r["exit_code"] == 0 or any(b["checkpoint"] == "publish" for b in r["blocked"]), r
    assert "cover" not in {d["checkpoint"] for d in AP.decisions(Project(p.dir))}   # hers now, not the AI's
    cov = [(e["event"], e.get("blocker")) for e in AP.history(Project(p.dir)) if e.get("checkpoint") == "cover"]
    assert cov[0][0] == "decided" and ("reopened", None) in cov and ("blocked", "asked") in cov


def test_projects_registered_at_once_all_stay_listed(tmp_path, monkeypatch):
    """Several projects started together (the desk's autopilot runs them side by side) all keep their registry row."""
    from concurrent.futures import ProcessPoolExecutor
    from vstudio.project import home as HM
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "shared"))
    os.makedirs(str(tmp_path / "shared"), exist_ok=True)
    dirs = [str(tmp_path / "shared" / f"p{k}") for k in range(12)]
    with ProcessPoolExecutor(6) as ex:
        list(ex.map(HM.register, dirs))
    assert {p["dir"] for p in HM.projects()} == set(dirs)
