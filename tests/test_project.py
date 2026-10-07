"""vstudio.project: recipe manifests (JSON Schema + semantic validity, every engine variant builds), the generic
runner on three cheap recipes with synthetic media (preproduction script lint, cover, talkinghead short clip):
checkpoint round-trips, resume after an interruption, refresh after an agent edit, export, the CLI / JSON-events
contract, series / inbox / calendar. No network, fake transcriber."""
import json
import os
import shutil
import subprocess
import sys

import pytest
import yaml

import _batch_helpers as H
from vstudio.batch.store import Store
from vstudio.project import build as B
from vstudio.project import home as HM
from vstudio.project import inbox as IB
from vstudio.project import manifests as M
from vstudio.project import pubcal as CAL
from vstudio.project.core import Project, ProjectError

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HAS_FFMPEG = bool(shutil.which("ffmpeg"))
media = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")

WORDS = [("大家", .4), ("好", .3), ("嗯", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35), ("方法", .4),
         ("这个", .3), ("方法", .4), ("很", .25), ("好用", .4), ("第二", .4), ("个", .25), ("例子", .4), ("也", .3),
         ("很", .25), ("重要", .4), ("最后", .4), ("总结", .4), ("一下", .35)]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VSTUDIO_CLIENTS", raising=False)


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    """One tiny talking clip (tone-burst 'speech' + its truth words), a photo, an audio file."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("synth")
    x, truth, dur = H.synth_speech(WORDS)
    src = H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    from PIL import Image
    Image.new("RGB", (900, 1200), (120, 90, 70)).save(d / "face.jpg")
    from vstudio import audio
    import numpy as np
    audio.write_wav(str(d / "bgm.wav"), np.zeros((48000, 2), dtype=np.float32), 48000)
    return dict(dir=d, video=src, truth=str(tp), dur=dur, photo=str(d / "face.jpg"), audio=str(d / "bgm.wav"))


def cli(*args, check=True, env=None):
    e = dict(os.environ)
    e["PYTHONPATH"] = os.pathsep.join([os.path.join(ROOT, "lib"), os.path.join(ROOT, "tests"),
                                       e.get("PYTHONPATH", "")])
    e.update(env or {})
    r = subprocess.run([sys.executable, "-m", "vstudio.project", *args], capture_output=True, text=True, env=e)
    if check and r.returncode not in (0, 7):
        raise AssertionError(f"exit {r.returncode}\n{r.stdout}\n{r.stderr}")
    return r


# --------------------------------------------------------------------------- manifests
def test_every_workflow_has_a_valid_manifest():
    wfs = sorted(d for d in os.listdir(os.path.join(ROOT, "workflows"))
                 if os.path.isdir(os.path.join(ROOT, "workflows", d)))
    ms = M.reload()
    assert sorted({m["workflow"] for m in ms.values()}) == wfs, "every workflow folder exposes a recipe.yaml"
    import jsonschema
    schema = M.schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    for m in ms.values():
        data = {k: v for k, v in m.items() if not k.startswith("_")}
        jsonschema.validate(data, schema)                      # the manifest against the published schema
        assert M.validate(m) == [], m["id"]
        assert m["labels"]["zh"] and m["labels"]["en"] and m["description"]["zh"]
        for k, p in m["params"]["properties"].items():
            assert p.get("x-zh") and p.get("title"), (m["id"], k)
        for variant in B.variants(m):
            r = B.build(m, variant)
            names = [s.name for s in r.order()]
            own = [s["id"] for s in m["stages"] if not s.get("from_batch")]
            for sid in own:
                assert sid in names, (m["id"], variant, sid)
            for cp in m["checkpoints"]:
                if cp["after"] in names:
                    g = M.GATE_PREFIX + cp["id"]
                    assert g in names and names.index(g) > names.index(cp["after"])
                    for b in cp.get("blocks") or []:
                        if b in names:
                            assert names.index(b) > names.index(g)
        assert os.path.exists(os.path.join(ROOT, m["agent"]["workflow_md"]))


def test_schema_and_semantic_checks_reject_bad_manifests():
    good = M.get("preproduction")
    bad = json.loads(json.dumps({k: v for k, v in good.items() if not k.startswith("_")}))
    del bad["labels"]
    assert any("labels" in e for e in M.validate(bad))
    bad = json.loads(json.dumps({k: v for k, v in good.items() if not k.startswith("_")}))
    bad["checkpoints"][0]["kind"] = "vibe-check"
    assert M.validate(bad)
    bad = json.loads(json.dumps({k: v for k, v in good.items() if not k.startswith("_")}))
    bad["checkpoints"][0].update(kind="budget-approval", auto="default")
    assert any("auto: never" in e for e in M.validate(bad))
    bad = json.loads(json.dumps({k: v for k, v in good.items() if not k.startswith("_")}))
    bad["stages"][1]["deps"] = ["nope"]
    assert any("unknown dep" in e for e in M.validate(bad))
    bad = json.loads(json.dumps({k: v for k, v in good.items() if not k.startswith("_")}))
    bad["params"]["properties"]["format"]["default"] = "epic"
    assert any("default" in e for e in M.validate(bad))


def test_templates():
    t = dict(python="py", item_dir="/i", platforms=["douyin", "youtube"], platform="douyin", dry=False,
             out=dict(frames=dict(sheet="/s.jpg")), files=["a", "b"])
    assert M.fmt("{item_dir}/x.json", t) == "/i/x.json"
    assert M.fmt("{platforms}", t) == "douyin,youtube"
    assert M.fmt("{out.frames.sheet}", t) == "/s.jpg"
    assert M.fmt_args(["{python}", "{files*}", {"if": "dry", "args": ["--dry-run"]},
                       {"if": "platform", "args": ["--platform", "{platform}"]}], t) == \
        ["py", "a", "b", "--platform", "douyin"]
    with pytest.raises(M.Missing):
        M.fmt("{nope}", t)


@media
def test_every_recipe_plans_a_project(tmp_path, synth):
    """Each recipe: a project of synthetic inputs plans (items, stage graph, author templates seeded), shows its
    context (workflow md, commands) and status without running anything expensive."""
    kinds = dict(video=synth["video"], photos=synth["photo"], audio=synth["audio"], folder=str(synth["dir"]),
                 file=synth["truth"], script=None, text="一个选题")
    seg = tmp_path / "segments.yaml"
    seg.write_text(yaml.safe_dump(dict(segments=[dict(id="ep01", start=0.3, end=5.0, title="一个方法")]),
                                  allow_unicode=True), encoding="utf-8")
    extra = {"call-clips": dict(host_region="0,0,180,320", no_mask=True)}
    for m in M.all_manifests().values():
        inputs = {}
        for i in m["inputs"]:
            if not i["required"]:
                continue
            v = kinds[i["kind"]]
            if i["kind"] == "script":
                p = tmp_path / f"{m['id']}-script.md"
                p.write_text("# t\n\n## HOOK\n    You ask twice.\n", encoding="utf-8")
                v = str(p)
            inputs[i["key"]] = [v]
        if m["items"].get("planner"):
            inputs.setdefault("source", [synth["video"]])
            inputs["segments"] = [str(seg)]
        p = Project.create(str(tmp_path / m["id"]), recipe=m["id"], inputs=inputs, params=extra.get(m["id"]))
        if m["items"].get("planner"):
            assert p.status()["state"] == "new" and not p.data["items"]
            assert p.plan_items()["items"] == ["ep01"]
            assert p.data["items"][0]["params"]["range"] == [0.3, 5.0]
        s = p.status()
        assert s["state"] == "planned" and s["items"], m["id"]
        c = p.context()
        assert os.path.exists(c["workflow_md"]) and c["commands"]["run"] and c["edit_files"]
        assert os.path.exists(os.path.join(p.dir, "AGENTS.md"))
        for cp in m["checkpoints"]:
            a = cp.get("author") or {}
            if a.get("template") and B.when_ok(cp.get("when"), p.params()):
                f = M.fmt(a["file"], B.static_tctx(m, dict(_item_dir=os.path.join(p.dir, "items", s["items"][0]["id"]),
                                                            _project_dir=p.dir), s["items"][0]["id"]))
                assert os.path.exists(f), (m["id"], cp["id"], f)
        show = p.show()
        assert show["manifest"]["id"] == m["id"] and show["recipe_name"].startswith("project:")


# --------------------------------------------------------------------------- preproduction (script lint)
def test_preproduction_checkpoint_roundtrip_refresh_and_export(tmp_path):
    topics = tmp_path / "topics.txt"
    topics.write_text("为什么第二次请求更快\n缓存到底省了什么\n", encoding="utf-8")
    pdir = str(tmp_path / "scripts")
    r = cli("new", "--recipe", "preproduction", "--dir", pdir, "--list", str(topics), "--json")
    assert json.loads(r.stdout)["items"] == ["001", "002"]
    r = cli("run", "--dir", pdir, "--json")
    out = json.loads(r.stdout)
    assert r.returncode == 7 and out["status"] == "needs-you"
    assert {(p["item"], p["id"]) for p in out["pending"]} == {("001", "lock"), ("002", "lock")}
    pend = json.loads(cli("checkpoint", "--dir", pdir, "--item", "001", "--json").stdout)["pending"]
    assert pend[0]["lint"]["errors"] and pend[0]["default"] is None      # the skeleton has parentheses
    text = ("# 第二次更快\n\n## HOOK\n    你把同一个问题问两遍，第二次快了整整十倍。\n\n## INSIGHT\n"
            "    说到底，快只是因为被记住了。\n")
    r = cli("checkpoint", "--dir", pdir, "--id", "lock", "--item", "001", "--answer",
            json.dumps(dict(lock=True, content=text), ensure_ascii=False), "--json")
    assert json.loads(r.stdout)["rerun"]["001"] == ["lint", "cp_lock"]
    r = cli("run", "--dir", pdir, "--json")
    st = json.loads(cli("status", "--dir", pdir, "--json").stdout)
    assert {i["id"]: i["state"] for i in st["items"]} == {"001": "done", "002": "waiting"}
    # an agent edits the locked script -> refresh: lint + lock re-run, the lock is asked again
    with open(os.path.join(pdir, "items", "001", "SCRIPT.md"), "a", encoding="utf-8") as f:
        f.write("\n## CLOSE\n    快，就是被记住。\n")
    ref = json.loads(cli("refresh", "--dir", pdir, "--json").stdout)
    assert ref["stale"]["001"] == ["lint", "cp_lock"] and ref["stale"]["002"] == ["cp_lock"]
    r = cli("run", "--dir", pdir, "--json")
    assert any(p["item"] == "001" for p in json.loads(r.stdout)["pending"])
    cli("checkpoint", "--dir", pdir, "--id", "lock", "--item", "001", "--answer", '{"lock": true}', "--json")
    cli("run", "--dir", pdir, "--json")
    ex = json.loads(cli("export", "--dir", pdir, "--json").stdout)
    assert ex["items"] == ["001"] and ex["skipped"][0]["item"] == "002"
    man = json.load(open(ex["manifest"], encoding="utf-8"))
    assert {os.path.basename(e["file"]) for e in man["items"]} == {"SCRIPT.md", "lint.json"}
    assert open(os.path.join(ex["dir"], "001", "SCRIPT.md"), encoding="utf-8").read().endswith("快，就是被记住。\n")
    ctx = json.loads(cli("context", "--dir", pdir, "--json").stdout)
    assert ctx["workflow_md"].endswith("workflows/preproduction/WORKFLOW.md")
    assert any(f.replace(os.sep, "/").endswith("items/001/SCRIPT.md") for f in ctx["edit_files"])
    assert os.path.exists(os.path.join(pdir, "CLAUDE.md")) and "refresh" in ctx["commands"]
    assert ctx["pending"][0]["item"] == "002"


def test_json_events_stream_is_pure_json(tmp_path):
    pdir = str(tmp_path / "p")
    cli("new", "--recipe", "preproduction", "--dir", pdir, "--json")
    r = cli("run", "--dir", pdir, "--json-events")
    evs = [json.loads(ln) for ln in r.stdout.splitlines() if ln.strip()]
    kinds = [e["event"] for e in evs]
    assert kinds[0] == "run-start" and "checkpoint" in kinds and kinds[-1] == "project-end"
    cp = next(e for e in evs if e["event"] == "checkpoint")
    assert cp["checkpoint"] == "lock" and os.path.exists(cp["payload"])
    assert evs[-1]["exit_code"] == 7 and r.returncode == 7
    bad = cli("checkpoint", "--dir", pdir, "--id", "lock", "--answer", '{"nope": 1}', "--json", check=False)
    assert bad.returncode == 5 and "invalid" in json.loads(bad.stdout)["error"]


# --------------------------------------------------------------------------- cover
@media
def test_cover_pick_and_platform_sizes(tmp_path, synth):
    p = Project.create(str(tmp_path / "cov"), recipe="cover", inputs=dict(video=[synth["video"]]),
                       params=dict(platforms=["xiaohongshu", "douyin"], every=2))
    r = p.run()
    assert r["exit_code"] == 7 and r["pending"][0]["id"] == "pick"
    from vstudio.batch import livestatus as LS
    live = LS.read(p.dir)                                  # desk 进行中 lane: the project waits for the creator
    assert (live["state"], live["needs_you"]) == ("waiting", True) and "pick" in live["message"]
    pay = p.pending()[0]
    assert len(pay["options"]) >= 3 and all(os.path.exists(o["image"]) for o in pay["options"])
    res = p.answer("pick", dict(pick=2, title=["让 AI 给你做", "数学讲解视频"], highlight=["数学"]))
    assert res["rerun"]["talk"] == ["cp_pick", "render"]
    r = p.run()
    assert r["exit_code"] == 0, r
    ex = p.export()
    from PIL import Image
    sizes = {(e["platform"], e["orientation"]): Image.open(e["file"]).size for e in ex["entries"]
             if not e["file"].endswith(".feed.jpg") and e["platform"]}
    assert sizes[("xiaohongshu", "vertical")] == (1080, 1440)
    assert sizes[("douyin", "vertical")] == (1080, 1920)
    # a new answer re-renders only the cover
    p.answer("pick", dict(pick=0, title=["另一句"]))
    r = p.run()
    assert sorted(r["ran"]) == ["talk:cp_pick", "talk:render"]


# --------------------------------------------------------------------------- talkinghead (short clip)
class Stop(KeyboardInterrupt):
    pass


@media
def test_talkinghead_checkpoints_resume_and_publish(tmp_path, synth, monkeypatch):
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", synth["truth"])
    clips = tmp_path / "raw"
    clips.mkdir()
    shutil.copy(synth["video"], clips / "c1.mp4")
    p = Project.create(str(tmp_path / "th"), recipe="talkinghead", folder=str(clips),
                       params=dict(pipeline="fast", platforms=["xiaohongshu:full"], preset="ultrafast", speed=1.0, layout="pad-blur"),
                       spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                 asr=dict(transcriber="_batch_helpers:fake_transcriber"),
                                 proofread=dict(enabled=False)))
    assert [i["id"] for i in p.data["items"]] == ["c1"]

    # interrupt the run right after the (shared) ASR finished
    def stop_after_asr(ev):
        if ev["event"] == "stage-done" and ev.get("stage") == "asr":
            raise Stop()
    with pytest.raises(KeyboardInterrupt):
        p.run(on_event=stop_after_asr)
    s = p.status()
    assert s["state"] == "interrupted" and s["items"][0]["state"] == "interrupted"
    stages = {x["id"]: x["state"] for x in s["items"][0]["stages"]}
    assert stages["asr"] == "done"
    r = p.run()                                              # resume: ASR is not redone
    assert not any(x.endswith(":asr") or x.endswith(":probe") for x in r["ran"]), r["ran"]
    assert r["exit_code"] == 7 and r["pending"][0]["id"] == "hook"
    hook = p.pending("hook")[0]
    assert hook["options"] and hook["default"] == {"pick": -1}
    p.answer("hook", dict(pick=0))
    assert p.data["overrides"]["c1"]["hook"]["src"] == [hook["options"][0]["start"], hook["options"][0]["end"]]
    r = p.run()
    order = [x["id"] for x in r["pending"]]
    if order and order[0] == "filler":                       # CONFIRM rows exist: answer by kind (bulk)
        f = p.pending("filler")[0]
        p.answer("filler", dict(kinds=sorted(f["kinds"])))
        assert p.data["overrides"]["c1"]["cleanup_reply"].startswith("确认")
        r = p.run()
    assert r["pending"][0]["id"] == "cover"
    cov = p.pending("cover")[0]
    p.answer("cover", dict(pick=1, text="一个方法|很好用"))
    r = p.run()
    assert r["pending"][0]["id"] == "publish"
    pub = p.pending("publish")[0]
    assert pub["exports"] and os.path.exists(pub["exports"][0]["file"]) and pub["qc"]["status"] in ("green", "red")
    assert p.export()["files"] == 0                           # not approved yet
    p.answer("publish", dict(approve=True))
    r = p.run()
    assert r["exit_code"] == 0 and r["status"] == "done", r
    st = Store(p.state_dir)
    j = st.job("c1")
    assert j["review"] == "approved" and j["params"]["cover"]["file"].endswith(".jpg")
    st.close()
    ex = p.export()
    vids = [e for e in ex["entries"] if e["kind"] == "video"]
    assert vids and vids[0]["platform"] == "xiaohongshu" and os.path.exists(vids[0]["cover"])
    assert sorted(os.listdir(clips)) == ["c1.mp4"]           # the source folder is read-only
    pv = p.preview(item="c1")
    assert any(a["stage"] == "preview" and a["path"].endswith("sheet.jpg") for a in pv["items"][0]["previews"])
    assert cov["options"] and os.path.exists(cov["options"][0]["image"])


@media
def test_talkinghead_auto_policy_runs_through_to_publish(tmp_path, synth, monkeypatch):
    """--auto answers every default-able checkpoint (hook none, filler AUTO-only, cover 0) and stops at publish
    only when QC is red (the default approve exists only for non-red items)."""
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", synth["truth"])
    p = Project.create(str(tmp_path / "th2"), recipe="talkinghead", inputs=dict(video=[synth["video"]]),
                       params=dict(pipeline="fast", preset="ultrafast", speed=1.0), auto=["hook", "filler", "cover"],
                       spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                 asr=dict(transcriber="_batch_helpers:fake_transcriber"),
                                 proofread=dict(enabled=False)))
    r = p.run()
    assert [x["id"] for x in r["pending"]] == ["publish"], r
    assert p.data["answers"]["hook"]["talk"]["auto"] is True
    r = p.run(auto=["publish"])
    qc = (p.pending("publish") or [{}])[0].get("qc", {}).get("status")
    assert r["exit_code"] == 0 or qc == "red"


@media
def test_talkinghead_pilot_answers_auto_checkpoints_too(tmp_path, synth, monkeypatch):
    """The desk starts every project as `run --pilot 1` with hook/filler/cover on auto: a pilot that stops at an
    auto-answerable checkpoint must answer it and go on (it used to end as "pilot-review" at the hook, and the first
    batch of a new user never got past it)."""
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", synth["truth"])
    p = Project.create(str(tmp_path / "th3"), recipe="talkinghead", inputs=dict(video=[synth["video"]]),
                       params=dict(pipeline="fast", preset="ultrafast", speed=1.0), auto=["hook", "filler", "cover"],
                       spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                 asr=dict(transcriber="_batch_helpers:fake_transcriber"),
                                 proofread=dict(enabled=False)))
    seen = []
    r = p.run(pilot=1, on_event=lambda ev: ev["event"] == "auto-answer" and seen.append(ev["checkpoint"]))
    assert "hook" in seen and "cover" in seen, seen
    assert [x["id"] for x in r["pending"]] in (["publish"], []), r


# --------------------------------------------------------------------------- series / inbox / calendar
def test_series_inbox_bulk_and_calendar(tmp_path):
    HM.new_series("daily", "preproduction", name="每日一题", params=dict(platforms=["xiaohongshu"], format="short"),
                  cadence=dict(per_week=5))
    with pytest.raises(HM.SeriesError):
        HM.new_series("daily", "preproduction")
    a = Project.create(str(tmp_path / "a"), series="daily", episodes=2)
    b = Project.create(str(tmp_path / "b"), recipe="preproduction", episodes=1)
    assert a.data["recipe"] == "preproduction" and a.params()["platforms"] == ["xiaohongshu"]
    assert [i["id"] for i in a.data["items"]] == ["ep01", "ep02"]
    for p in (a, b):
        p.run()
    box = IB.inbox()
    assert box["total"] == 3 and box["counts"] == {"script-lock": 3}
    g = box["groups"][0]
    assert g["id"] == "lock" and g["n"] == 3
    # unlock-able by default only when lint is clean: write clean scripts for a, then bulk-answer defaults
    for it in ("ep01", "ep02"):
        with open(os.path.join(a.dir, "items", it, "SCRIPT.md"), "w", encoding="utf-8") as f:
            f.write("# t\n\n## HOOK\n    你把同一个问题问两遍，第二次快了十倍。\n\n## INSIGHT\n    说到底，快只是因为被记住了。\n")
    a.refresh()
    a.run()
    res = IB.answer_bulk(cid="lock", use_default=True)
    assert {(os.path.basename(x["project"]), x["item"]) for x in res["answered"]} == {("a", "ep01"), ("a", "ep02")}
    assert [(os.path.basename(x["project"]), x["item"]) for x in res["skipped"]] == [("b", "ep01")]
    assert "default" in res["skipped"][0]["why"]
    a.run()
    assert IB.inbox()["total"] == 1
    assert HM.series_view("daily")["projects"][0]["dir"] == a.dir
    # calendar: accounts, plan exported items into slots, state flow, gaps
    acc = CAL.add_account("xhs-main", "xiaohongshu", times=["12:00", "19:00"], per_day=1)
    assert acc["per_day"] == 1
    a.export()
    with pytest.raises(CAL.CalendarError):
        CAL.plan(b.dir)
    # preproduction exports are text: put a fake exported video entry in a's manifest to schedule
    man_path = os.path.join(a.dir, "exports", "manifest.json")
    man = json.load(open(man_path, encoding="utf-8"))
    man["items"] = [dict(item="ep01", platform="xiaohongshu", orientation="vertical", kind="video", file="/x/ep01.mp4",
                         title="第一集"), dict(item="ep02", platform="xiaohongshu", orientation="vertical",
                                               kind="video", file="/x/ep02.mp4", title="第二集")]
    json.dump(man, open(man_path, "w", encoding="utf-8"))
    r = CAL.plan(a.dir, start="2026-10-12T08:00")
    assert [x["at"] for x in r["added"]] == ["2026-10-12T12:00", "2026-10-13T12:00"]
    assert CAL.plan(a.dir, start="2026-10-12T08:00")["n"] == 0           # idempotent
    pid = r["added"][0]["id"]
    CAL.set_state(pid, "scheduled")
    with pytest.raises(CAL.CalendarError):
        CAL.set_state(pid, "planned")
    CAL.set_state(pid, "posted", url="https://example.invalid/p/1")
    ls = CAL.listing(start="2026-10-12T00:00", end="2026-10-15T00:00")
    assert ls["counts"] == {"posted": 1, "approved": 1}
    assert [gp["day"] for gp in ls["gaps"]] == ["2026-10-14"]
    r = cli("inbox", "--json")
    assert r.returncode == 0


def test_answer_validation_and_unknown_inputs(tmp_path):
    with pytest.raises(ProjectError):
        Project.create(str(tmp_path / "x"), recipe="preproduction", inputs=dict(nope=["a"]))
    with pytest.raises(ProjectError):
        Project.create(str(tmp_path / "y"), recipe="preproduction", params=dict(format="epic"))
    two = Project.create(str(tmp_path / "two"), recipe="preproduction", episodes=2)
    with pytest.raises(ProjectError):
        two.answer("lock", dict(lock=True))                  # nobody waits yet and no item named
    with pytest.raises(ProjectError):
        two.answer("lock", dict(lock=True), items=["ep09"])
    p = Project.create(str(tmp_path / "z"), recipe="preproduction")
    with pytest.raises(ProjectError):
        p.answer("lock", dict(lock="yes"))
    r = p.answer("lock", dict(lock=True, content="# ok\n\n## HOOK\n    你问两遍，第二次快十倍。\n"))
    assert r["answered"] == ["main"]                          # one item: answered ahead without naming it
    assert p.run()["exit_code"] == 0                          # the gate finds the answer: passes at once


def test_pilot_then_confirm_and_recipes_cli(tmp_path):
    p = Project.create(str(tmp_path / "pilot"), recipe="preproduction", episodes=3)
    r = p.run(pilot=1)
    assert r["exit_code"] == 4 and r["batch_status"] == "pilot-review"
    st = p.status()
    ran = [i["id"] for i in st["items"] if i["progress"]["done"] > 0]
    assert ran == ["ep01"]
    assert p.run()["exit_code"] == 4                          # still waiting for the pilot review
    r = p.run(confirm_pilot=True)
    assert r["exit_code"] == 7 and {x["item"] for x in r["pending"]} == {"ep01", "ep02", "ep03"}
    out = json.loads(cli("recipes", "--json").stdout)
    ids = {x["id"] for x in out["recipes"]}
    assert {"talkinghead", "cover", "preproduction", "ai-video", "explainer", "longform-course"} <= ids
    th = next(x for x in out["recipes"] if x["id"] == "talkinghead")
    assert set(th["graph"]) == {"talkinghead-clips", "talkinghead-folder"}
    assert any(sg["id"] == "cp_filler" and sg["gate"] for sg in th["graph"]["talkinghead-clips"])
    assert "inbox" in out["capabilities"] and os.path.exists(out["schema"])
    ls = json.loads(cli("list", "--json").stdout)
    assert any(x["dir"] == p.dir for x in ls["projects"])
