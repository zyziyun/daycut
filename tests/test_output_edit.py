"""Output-level second-pass edits (vstudio.project outputs / outrender / outfx): every op on a pipeline-made output
(talkinghead project: clean master + cues) and on a flattened file (an adopted work folder), capability flags,
undo / redo, partial re-render caching, the AI op with a mocked model, the effect catalogue and the CLI JSON
contract. Synthetic media only, no network."""
import json
import os
import shutil
import subprocess
import sys

import pytest

import _batch_helpers as H
from vstudio import effects as E
from vstudio import llm
from vstudio.project import outfx as FX
from vstudio.project import outputs as O
from vstudio.project import outrender as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HAS_FFMPEG = bool(shutil.which("ffmpeg"))
media = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")

WORDS = [("大家", .4), ("好", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35), ("方法", .4),
         ("这个", .3), ("方法", .4), ("很", .25), ("好用", .4), ("第二", .4), ("个", .25), ("例子", .4), ("也", .3),
         ("很", .25), ("重要", .4), ("最后", .4), ("总结", .4), ("一下", .35)]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_CLIENTS", "VSTUDIO_LLM_PROVIDER",
              "VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(O, "TRANSCRIBE", _fake_words)


_TRUTH = {}


def _fake_words(path, language=None):
    """A perfect ASR: the synthetic truth for the flattened clip, cue characters spread over the cue for a
    pipeline export."""
    if path in _TRUTH:
        return _TRUTH[path]
    raise RuntimeError(f"no fake transcript for {path}")


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("osynth")
    x, truth, dur = H.synth_speech(WORDS)
    src = H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    from vstudio import audio
    import numpy as np
    t = np.arange(int(48000 * 3)) / 48000
    audio.write_wav(str(d / "bgm.wav"), np.stack([0.1 * np.sin(2 * np.pi * 220 * t)] * 2, 1).astype(np.float32), 48000)
    from PIL import Image
    Image.new("RGBA", (200, 200), (255, 200, 0, 255)).save(d / "sticker.png")
    return dict(dir=d, video=src, truth=[{k: w[k] for k in ("w", "t", "te")} for w in truth], truth_path=str(tp),
                dur=dur, bgm=str(d / "bgm.wav"), sticker=str(d / "sticker.png"))


def _work(tmp_path, synth):
    w = tmp_path / "work"
    (w / "final").mkdir(parents=True)
    f = w / "final" / "clip.mp4"
    shutil.copy(synth["video"], f)
    (w / "REPORT.md").write_text("# clip\n")
    from vstudio.project import works
    works.adopt(str(w))
    _TRUTH[str(f)] = synth["truth"]
    return str(w), "final/clip.mp4"


@pytest.fixture(scope="module")
def th(tmp_path_factory, synth):
    """A talkinghead project run end to end with the fake transcriber: a pipeline-made output."""
    d = tmp_path_factory.mktemp("oth")
    old = {k: os.environ.get(k) for k in ("VSTUDIO_TEST_TRUTH", "VSTUDIO_HOME", "VSTUDIO_BATCH_BENCH")}
    os.environ.update(VSTUDIO_TEST_TRUTH=synth["truth_path"], VSTUDIO_HOME=str(d / "home"),
                      VSTUDIO_BATCH_BENCH=str(d / "bench.json"))
    try:
        from vstudio.project.core import Project
        p = Project.create(str(d / "th"), recipe="talkinghead", inputs=dict(video=[synth["video"]]),
                           params=dict(preset="ultrafast", speed=1.0, platforms=["xiaohongshu:full"]),
                           auto=["hook", "filler", "cover"],
                           spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                     asr=dict(transcriber="_batch_helpers:fake_transcriber"),
                                     proofread=dict(enabled=False)))
        p.run()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    return str(d / "th")


def _pipeline(th):
    lst = O.list_outputs(th)
    assert lst["kind"] == "project" and lst["outputs"], lst
    oid = lst["outputs"][0]["id"]
    rec = O.resolve(th, oid)
    W = []
    for c in rec["cues"]:
        chars = [ch for ch in c["text"] if ch.strip()]
        step = (c["end"] - c["start"]) / max(1, len(chars))
        W += [dict(w=ch, t=round(c["start"] + k * step, 3), te=round(c["start"] + (k + 0.9) * step, 3))
              for k, ch in enumerate(chars)]
    _TRUTH[rec["file"]] = W
    return oid, rec


# --------------------------------------------------------------------------- catalogue
def test_effect_catalogue_is_registry_backed(tmp_path):
    rows = FX.catalogue(thumbs=True, thumb_dir=str(tmp_path / "th"))
    ids = [r["id"] for r in rows]
    for want in ("pop-words", "stacking-stamps", "punch-in", "quote-card", "callout-bubble", "chapter-card",
                 "notes-panel", "overlay-images", "sfx-placement", "xfade-joins", "progress-bar-pil"):
        assert want in ids
    for r in rows:
        assert r["id"] in E.REGISTRY                      # never an effect the registry does not have
        assert r["label"]["en"] and r["label"]["zh"] and r["description"]["en"] and r["description"]["zh"]
        assert r["stage"] in ("frame", "audio", "timeline")
        assert r["thumbnail"] and os.path.getsize(r["thumbnail"]) > 0
    assert FX.resolve("stamp") == "stacking-stamps" and FX.resolve("贴纸") == "overlay-images"
    assert FX.resolve("sparkle-unicorn") is None
    clean, warns = FX.validate("pop-words", dict(text="重点", size=3, bogus=1))
    assert clean["size"] == 0.25 and any("bogus" in w for w in warns) and any("lowered" in w for w in warns)
    with pytest.raises(ValueError):
        FX.validate("pop-words", {})
    assert "output_edit" in llm.TASKS


# --------------------------------------------------------------------------- flattened
@media
def test_flattened_every_op_caps_and_render(tmp_path, synth):
    w, oid = _work(tmp_path, synth)
    s = O.show(w, oid)
    assert s["output"]["mode"] == "flattened"
    c = s["caps"]
    assert c["captions_ours"] is False and c["caption_text"] is False and c["caption_add"] is True
    assert c["caption_placements"] == ["band", "mask"] and c["relayout"] == "reframe-file"
    assert {n["code"] for n in s["caps_notes"]} >= {"flattened", "captions-add-only"}
    assert all("message" in n and "params" in n for n in s["caps_notes"])

    # refusals carry a stable code
    for op, code in ((dict(op="captions", enabled=False), "captions-not-ours"),
                     (dict(op="effect_add", effect="sparkle-unicorn", start=1), "unknown-effect"),
                     (dict(op="frobnicate"), "unknown-op"),
                     (dict(op="trim", start=2.0, end=2.4), "too-short"),
                     (dict(op="cut", start=2.0, end=1.0), "bad-time"),
                     (dict(op="export_add", target="myspace"), "unknown-target")):
        with pytest.raises(O.OutputError) as ei:
            O.edit(w, oid, op)
        assert ei.value.info["code"] == code, (op, ei.value.info)

    r = O.edit(w, oid, [dict(op="trim", start=0.3), dict(op="cut", start=2.1, end=2.6, why="aside")])
    cut = r["values"][1]["cut"]
    starts = {x["t"] for x in synth["truth"]}
    ends = {x["te"] for x in synth["truth"]}
    assert r["values"][1]["snapped"] and r["values"][1]["words"]
    assert any(abs(cut[0] - t) < 0.2 for t in ends | starts)          # word-snapped edges
    assert os.path.exists(os.path.join(r["paths"]["dir"], "transcript.json"))   # cached transcript
    ops = [dict(op="speed", value=1.1), dict(op="loudness", lufs=-16),
           dict(op="caption_add", start=0.5, end=1.5, text="新的字幕"),
           dict(op="caption_style", style=dict(size=1.2, color="#FFFFFF", highlight="#FFD60A", keywords=["字幕"])),
           dict(op="title", text="一个方法", sub="很好用"),
           dict(op="cover", t=1.0, text="一个方法|很好用", style="card")]
    fx = [("pop-words", dict(text="重点")), ("stacking-stamps", dict(text="亲测")), ("punch-in", {}),
          ("quote-card", dict(text="方法很好用", speaker="Speaker A")),
          ("callout-bubble", dict(text="看这里", arrow_x=0.7, arrow_y=0.6)),
          ("chapter-card", dict(title="第二部分", index=2, total=3)),
          ("notes-panel", dict(title="要点", bullets=["一", "二"])), ("overlay-images", dict(image=synth["sticker"],
                                                                                         style="image")),
          ("badge", dict(text="精选")), ("red-box", {}), ("progress-bar-pil", {}),
          ("sfx-placement", dict(name="pop")), ("music-bed", dict(file=synth["bgm"])),
          ("xfade-joins", dict(transition="fade")), ("end-fade", {}), ("vlog-grade", {})]
    for k, (eid, params) in enumerate(fx):
        start = 2.1 if eid == "xfade-joins" else 0.6 + 0.3 * k % 3
        ops.append(dict(op="effect_add", effect=eid, start=start, params=params))
    r = O.edit(w, oid, ops)
    assert {e["effect"] for e in r["state"]["effects"]} == {x[0] for x in fx}
    assert any(wn["code"] == "placement-auto" for wn in r["warnings"])          # flattened captions sit on a mask
    assert r["state"]["captions"]["placement"]["mode"] == "mask"
    assert r["timeline"]["joins"] and r["timeline"]["joins"][0]["transition"] == "fade"
    with pytest.raises(O.OutputError) as ei:                                     # burned captions: not ours
        O.edit(w, oid, dict(op="caption_text", cue="0", text="x"))
    assert ei.value.info["code"] == "unknown-cue"
    added = r["state"]["captions"]["added"][0]["id"]
    O.edit(w, oid, dict(op="caption_text", cue=added, text="改过的字幕"))
    fid = next(e["id"] for e in r["state"]["effects"] if e["effect"] == "pop-words")
    r = O.edit(w, oid, [dict(op="effect_update", id=fid, shift=0.2, params=dict(text="必看")),
                        dict(op="caption_placement", mode="band", band=0.22),
                        dict(op="export_add", target="9:16"), dict(op="export_add", target="16:9"),
                        dict(op="export_remove", target="16:9"), dict(op="cut_remove", index=0),
                        dict(op="cut", start=2.1, end=2.6)])
    e = next(e for e in r["state"]["effects"] if e["id"] == fid)
    assert e["params"]["text"] == "必看" and [x["target"] for x in r["state"]["exports"]] == ["douyin:vertical"]
    O.edit(w, oid, dict(op="effect_remove", id=next(e["id"] for e in r["state"]["effects"]
                                                     if e["effect"] == "badge")))

    res = R.render(w, oid, quality="preview", targets=["all"])
    tl = O.show(w, oid)["timeline"]
    assert [t["target"] for t in res["targets"]] == ["primary", "douyin:vertical"]
    from vstudio import media as M
    for t in res["targets"]:
        i = M.probe(t["file"])
        assert (i["w"], i["h"]) == tuple(t["canvas"])
        assert abs(i["duration"] - tl["duration"]) < 0.25, (i["duration"], tl)
        assert t["cover"] and os.path.exists(t["cover"])
    assert (M.probe(res["targets"][1]["file"])["w"], M.probe(res["targets"][1]["file"])["h"]) == (1080, 1920)
    assert os.path.exists(os.path.join(w, "final", "clip.mp4"))               # the original is never touched
    st = json.load(open(os.path.join(res["edit_dir"], ".vstudio", "status.json")))
    assert st["status"] == "done" and st["updated_by"] == "output-edit"
    assert json.load(open(os.path.join(w, ".vstudio", "status.json")))["heartbeat"]


# --------------------------------------------------------------------------- pipeline
@media
def test_pipeline_output_recomposes_from_master(th, monkeypatch):
    oid, rec = _pipeline(th)
    s = O.show(th, oid)
    assert s["output"]["mode"] == "pipeline" and s["output"]["master"]
    c = s["caps"]
    assert c["captions_ours"] and c["caption_text"] and c["caption_toggle"] and c["relayout"] == "master"
    assert s["captions"] and s["captions"][0]["id"] == "0"
    first = s["captions"][0]
    # a sound-alike fix is faithful; a rewrite is refused unless forced
    with pytest.raises(O.OutputError) as ei:
        O.edit(th, oid, dict(op="caption_text", cue="0", text="完全不同的一句新话"))
    assert ei.value.info["code"] == "not-faithful"
    O.edit(th, oid, dict(op="caption_text", cue="0", text="完全不同的一句新话", force=True))
    with pytest.raises(O.OutputError) as ei:
        O.edit(th, oid, dict(op="caption_placement", mode="mask"))
    assert ei.value.info["code"] == "placement-pipeline"
    r = O.edit(th, oid, [dict(op="caption_style", style=dict(position="middle", highlight="#00FF88", size=1.1)),
                         dict(op="caption_remove", cue="1") if len(s["captions"]) > 1 else dict(op="speed", value=1.0),
                         dict(op="cut", start=first["end"] + 0.05, end=first["end"] + 0.6),
                         dict(op="effect_add", effect="pop-words", start=0.5, params=dict(text="重点")),
                         dict(op="effect_add", effect="progress-bar", start=0),
                         dict(op="export_add", target="xiaohongshu:vertical")])
    assert r["state"]["captions"]["overrides"]["0"] == "完全不同的一句新话"
    res = R.render(th, oid, quality="final", targets="all")
    from vstudio import media as M
    sizes = {t["target"]: (M.probe(t["file"])["w"], M.probe(t["file"])["h"]) for t in res["targets"]}
    assert sizes["xiaohongshu:vertical"] == (1080, 1440)
    stages = {t["target"]: [x["stage"] for x in t["stages"]] for t in res["targets"]}
    assert "canvas" in stages["xiaohongshu:vertical"]                          # a fresh reframe of the master
    assert all(t["quality"] == "final" for t in res["targets"])
    # captions off is a pipeline-only toggle and changes only the final stage
    O.edit(th, oid, dict(op="captions", enabled=False))
    r2 = R.render(th, oid, quality="final")
    st = {x["stage"]: x["cached"] for x in r2["targets"][0]["stages"]}
    assert st.get("timeline", True) and st["final"] is False


# --------------------------------------------------------------------------- caching / undo
@media
def test_partial_rerender_cache_and_undo(tmp_path, synth):
    w, oid = _work(tmp_path, synth)
    O.edit(w, oid, [dict(op="trim", start=0.3, snap=False),
                    dict(op="effect_add", effect="stamp", start=1.0, params=dict(text="亲测")),
                    dict(op="effect_add", effect="sfx", start=1.0, params=dict(name="ding"))])
    r1 = R.render(w, oid)
    s1 = {x["stage"]: x["cached"] for x in r1["targets"][0]["stages"]}
    assert s1 == dict(timeline=False, audio=False, final=False)
    assert O.show(w, oid)["renders"][0]["fresh"] is True
    r2 = R.render(w, oid)                                                        # nothing changed: all cache hits
    assert r2["targets"][0]["cached"] is True
    fid = O.show(w, oid)["state"]["effects"][0]["id"]
    O.edit(w, oid, dict(op="effect_update", id=fid, params=dict(text="必看")))   # visual only
    assert O.show(w, oid)["renders"][0]["fresh"] is False
    s3 = {x["stage"]: x["cached"] for x in R.render(w, oid)["targets"][0]["stages"]}
    assert s3 == dict(timeline=True, audio=True, final=False)
    sid = O.show(w, oid)["state"]["effects"][1]["id"]
    O.edit(w, oid, dict(op="effect_update", id=sid, params=dict(name="pop")))    # audio only
    s4 = {x["stage"]: x["cached"] for x in R.render(w, oid)["targets"][0]["stages"]}
    assert s4 == dict(timeline=True, audio=False, final=False)

    # undo returns to the previous render (a cache hit), redo comes back; a new edit clears redo
    u = O.undo(w, oid)
    assert u["undone"]["ops"][0]["op"] == "effect_update" and u["history"]["redo"] == 1
    assert u["state"]["effects"][1]["params"]["name"] == "ding"
    assert R.render(w, oid)["targets"][0]["cached"] is True
    rd = O.redo(w, oid)
    assert rd["state"]["effects"][1]["params"]["name"] == "pop"
    O.undo(w, oid)
    O.edit(w, oid, dict(op="speed", value=1.2))
    with pytest.raises(O.OutputError) as ei:
        O.redo(w, oid)
    assert ei.value.info["code"] == "nothing-to-redo"
    for _ in range(len(O.show(w, oid)["history"]["steps"])):
        O.undo(w, oid)
    st0 = O.show(w, oid)["state"]
    assert st0["effects"] == [] and st0["trim"] == [None, None] and st0["speed"] == 1.0
    with pytest.raises(O.OutputError) as ei:
        O.undo(w, oid)
    assert ei.value.info["code"] == "nothing-to-undo"


# --------------------------------------------------------------------------- AI
@media
def test_ai_op_with_mocked_model(tmp_path, synth, monkeypatch):
    w, oid = _work(tmp_path, synth)
    monkeypatch.setenv("VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER", "claude-code")
    seen = {}

    def fake_complete(task, system, prompt, schema=None, provider=None, model=None, **kw):
        seen.update(task=task, prompt=prompt)
        return dict(text="", json=dict(summary="punchier", ops=[
            dict(op="effect_add", effect="pop-words", start=1.0, params=dict(text="重点"), why="emphasis"),
            dict(op="effect_add", effect="laser-unicorn", start=2.0),              # invented: dropped
            dict(op="speed", value=9),                                             # out of range: dropped
            dict(op="export_add", target="douyin"),
            dict(op="caption_text", cue="0", text="x")]),                          # flattened: no such cue
            usage={}, cost_usd=0.0, provider="claude-code", model="m")
    monkeypatch.setattr(llm, "complete", fake_complete)
    r = O.ai(w, oid, "加个重点大字，再导出抖音版")
    assert seen["task"] == "output_edit" and "pop-words" in seen["prompt"] and "大家" in seen["prompt"]
    assert [p["normalized"]["op"] for p in r["proposed"]] == ["effect_add", "export_add"]
    assert all(p["describe"]["code"].startswith("op-") for p in r["proposed"])
    codes = sorted(d["error"]["code"] for d in r["dropped"])
    assert codes == ["bad-param", "unknown-cue", "unknown-effect"]
    assert r["applied"] is False and O.show(w, oid)["history"]["undo"] == 0
    r = O.ai(w, oid, "加个重点大字，再导出抖音版", apply=True)
    s = O.show(w, oid)
    assert r["applied"] and s["history"]["steps"][0]["by"] == "ai"
    assert s["state"]["exports"][0]["target"] == "douyin:vertical"
    # no model configured: literal phrases only, said so with a code
    monkeypatch.delenv("VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER")
    monkeypatch.setattr(llm, "route", lambda *a, **k: llm.Route("none", None, {}, "test"))
    r = O.ai(w, oid, "1.2倍速，去掉开头1秒，导出小红书版")
    assert r["provider"] == "rules" and any(x["code"] == "no-model" for x in r["warnings"])
    assert {p["normalized"]["op"] for p in r["proposed"]} == {"speed", "trim", "export_add"}


# --------------------------------------------------------------------------- CLI
def _cli(*args, env=None):
    e = dict(os.environ)
    e["PYTHONPATH"] = os.pathsep.join([os.path.join(ROOT, "lib"), os.path.join(ROOT, "tests"), e.get("PYTHONPATH", "")])
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "vstudio.project", "output", *args], capture_output=True, text=True,
                          env=e)


@media
def test_cli_json_contract(tmp_path, synth):
    w, oid = _work(tmp_path, synth)
    r = _cli("list", "--project", w, "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["outputs"][0]["id"] == oid
    r = _cli("show", "--project", w, "--output", oid, "--json")
    s = json.loads(r.stdout)
    assert s["ok"] and s["output"]["mode"] == "flattened" and "caps" in s and "history" in s
    r = _cli("edit", "--project", w, "--output", oid, "--ops", json.dumps([dict(op="speed", value=1.25)]), "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["state"]["speed"] == 1.25
    r = _cli("edit", "--project", w, "--output", oid, "--op", "effect_add", "--param", "effect=stamp",
             "--param", "start=1", "--set", json.dumps(dict(params=dict(text="亲测"))), "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    r = _cli("edit", "--project", w, "--output", oid, "--op", "effect_add", "--param", "effect=nope", "--param",
             "start=1", "--json")
    err = json.loads(r.stdout)
    assert r.returncode == 5 and err["ok"] is False and err["code"] == "unknown-effect" and err["message"]
    r = _cli("undo", "--project", w, "--output", oid, "--json")
    assert json.loads(r.stdout)["history"]["undo"] == 1
    r = _cli("render", "--project", w, "--output", oid, "--json-events")
    evs = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
    assert r.returncode == 0 and evs[-1]["event"] == "render-done" and os.path.exists(evs[-1]["targets"][0]["file"])
    r = _cli("effects", "--json", "--no-thumbs")
    assert len(json.loads(r.stdout)["effects"]) == len(FX.SPECS)
    r = _cli("show", "--project", w, "--output", "nope.mp4", "--json")
    assert r.returncode == 5 and json.loads(r.stdout)["code"] == "unknown-output"
