"""vstudio.batch with real media: QC gates on synthetic files, and the longform-slices / talkinghead-clips recipes
end to end (fake transcriber, tiny 9:16 clips, ultrafast encodes)."""
import json
import os
import shutil
import subprocess

import pytest
import yaml

import _batch_helpers as H
from vstudio import audio
from vstudio import platform as P
from vstudio.batch import qc, review
from vstudio.batch.package import package
from vstudio.batch.plan import plan_batch
from vstudio.batch.run import run_batch
from vstudio.batch.store import Store

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

WORDS = [("大家", .4), ("好", .3), ("嗯", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35), ("方法", .4),
         ("这个", .3), ("方法", .4), ("很", .25), ("好用", .4), ("第二", .4), ("个", .25), ("例子", .4), ("也", .3),
         ("很", .25), ("重要", .4), ("最后", .4), ("总结", .4), ("一下", .35)]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))


@pytest.fixture(scope="module")
def talk(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    x, truth, dur = H.synth_speech(WORDS)
    src = H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    return dict(dir=d, src=src, truth=str(tp), dur=dur, x=x)


# --------------------------------------------------------------------------- QC gates
def test_qc_gates_green_and_red(tmp_path, talk):
    good = talk["src"]
    o = qc.opts({}, "talkinghead-clips")
    # A/V sync + black / frozen on a clean file
    assert qc.check_av_sync(good)["ok"] is True
    assert all(c["ok"] for c in qc.check_black_frozen(good, o))
    # black frames -> red
    bad = H.make_video(str(tmp_path / "black.mp4"), talk["x"], 48000, talk["dur"], black=(2.0, 3.2))
    bf = {c["name"]: c for c in qc.check_black_frozen(bad, o)}
    assert bf["black-frames"]["ok"] is False and bf["black-frames"]["severity"] == "red"
    assert 1.9 <= bf["black-frames"]["value"][0][0] <= 2.1
    # audio shorter than video -> A/V sync red
    short = str(tmp_path / "short.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", good, "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                    "-map", "0:v", "-map", "1:a", "-t", "4", "-c:v", "copy", "-c:a", "aac", "-shortest", "-t", "4",
                    short], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", good, "-i", short, "-map", "0:v", "-map", "1:a", "-c", "copy",
                    str(tmp_path / "desync.mp4")], check=True)
    assert qc.check_av_sync(str(tmp_path / "desync.mp4"))["ok"] is False
    # loudness: a quiet clip is far from -14 LUFS -> red; normalised -> green
    tgt = dict(lufs=-14.0, tp=-1.5)
    quiet = H.make_video(str(tmp_path / "quiet.mp4"), talk["x"] * 0.03, 48000, talk["dur"])
    lo = {c["name"]: c for c in qc.check_loudness(quiet, tgt)}
    assert lo["loudness"]["ok"] is False and lo["loudness"]["value"] < -25
    norm = str(tmp_path / "norm.mp4")
    audio.loudnorm_2pass(quiet, norm, lufs=-14.0, tp=-1.5)
    assert all(c["ok"] for c in qc.check_loudness(norm, tgt))
    # hallucinated caption, platform length / title
    assert qc.check_hallucinations([dict(start=0, end=1, text="字幕志愿者 李宗盛")])["ok"] is False
    assert qc.check_hallucinations([dict(start=0, end=1, text="今天讲一个方法")])["ok"] is True
    prof = P.profile("douyin")
    assert qc.check_length(prof, 1000.0)[0]["ok"] is False
    assert qc.check_length(prof, 30.0)[0]["ok"] is True
    assert qc.check_title("这是一个非常非常非常非常非常非常非常长的小红书标题会超过限制", "xiaohongshu")["ok"] is False
    assert qc.check_title("短标题", "xiaohongshu")["ok"] is True
    # safe zone from a manifest entry
    e = dict(w=prof.w, h=prof.h, safe_box=list(P.safe_box(prof)), caption_box=list(P.caption_box(prof)), warnings=[])
    assert all(c["ok"] for c in qc.check_safe_zone(e, prof))
    e["warnings"] = ["captions overlap a burned overlay (keepout) on 12 frames: no free spot in the safe box"]
    assert not all(c["ok"] for c in qc.check_safe_zone(e, prof))
    # sampling is deterministic and roughly the requested share
    s = [qc.sampled(f"j{i}", 10) for i in range(2000)]
    assert s == [qc.sampled(f"j{i}", 10) for i in range(2000)] and 120 < sum(s) < 280


# --------------------------------------------------------------------------- end to end
def _spec(tmp, talk, **kw):
    spec = dict(name="e2e", recipe="longform-slices", inputs=dict(source=talk["src"]), plugins=["_batch_helpers"],
                asr=dict(transcriber="_batch_helpers:fake_transcriber", language="zh"),
                defaults=dict(platforms=["xiaohongshu:full"], layout="pad-blur", preset="ultrafast"),
                jobs=[dict(id="a", range=[0.3, 6.5], title="一个方法", body="正文",
                           hooks=[dict(src=[3.3, 4.6], lines=["这个方法很好用"])]),
                      dict(id="b", start=4.0, end=9.6, title="第二个例子")],
                variants=dict(by=["hook"]), qc=dict(sample_pct=0), budget=dict(max_hours=1))
    spec.update(kw)
    p = tmp / "batch.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True))
    return str(p)


def test_longform_slices_end_to_end(tmp_path, talk, monkeypatch):
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", talk["truth"])
    r = plan_batch(_spec(tmp_path, talk), echo=False)
    bdir = r["batch_dir"]
    assert r["jobs"] == ["a.h1", "b"]
    res = run_batch(bdir, echo=False)
    assert res["exit_code"] == 0, res
    # one probe / extract / asr for the shared source, reused by the other job
    assert sum(1 for _, s in res["ran"] if s == "asr") == 1
    assert any(s == "asr" for _, s in res["cached"])
    st = Store(bdir)
    for j in st.jobs():
        assert j["state"] == "done" and j["qc"] == "green", (j["id"], j["qc_reasons"])
    ex = st.stage("a.h1", "export")["out"]["exports"][0]
    assert os.path.exists(ex["file"]) and os.path.exists(ex["cover"])
    comp = st.stage("a.h1", "compose")["out"]
    assert comp["hook_dur"] > 1.0 and comp["duration"] > 6.0
    cues = json.load(open(comp["cues"], encoding="utf-8"))["cues"]
    assert cues[0]["text"] == "这个方法很好用" and cues[0]["meta"]["kind"] == "hook"
    n_confirm = st.stage("a.h1", "cleanup")["out"]["confirm"]
    st.close()
    assert sorted(os.listdir(talk["dir"])) == ["talk.mp4", "truth.json"]    # source folder untouched (read-only)
    # review page + combined decisions sheet; a cleanup reply re-cuts from `apply` on, ASR / analysis reused
    rv = review.generate(bdir)
    assert rv["jobs"] == 2 and rv["confirm_edits"] >= n_confirm
    review.apply_decisions(bdir, {"cleanup": {"a.h1": "全部确认"}, "decisions": {"b": {"decision": "approve"}}})
    res2 = run_batch(bdir, echo=False)
    assert res2["exit_code"] == 0
    assert {s for _, s in res2["ran"]} <= {"apply", "compose", "verify", "proofread", "export", "qc", "preview"}
    assert ("a.h1", "apply") in res2["ran"] and not any(j == "b" for j, _ in res2["ran"])
    review.apply_decisions(bdir, {"decisions": {"a.h1": {"decision": "approve"}}})
    pk = package(bdir, per_day=1, start="2026-10-10")
    assert pk["items"] == 2 and len(pk["code"]) == 12
    assert os.path.exists(os.path.join(pk["dir"], "xiaohongshu-full", "001_a.h1", "video.mp4"))


def test_talkinghead_clips_expand(tmp_path, talk, monkeypatch):
    clips = tmp_path / "raw"
    clips.mkdir()
    for n in ("c1", "c2"):
        shutil.copy(talk["src"], clips / f"{n}.mp4")
    (clips / "notes.txt").write_text("x")
    p = tmp_path / "th.yaml"
    p.write_text(yaml.safe_dump(dict(recipe="talkinghead-clips", inputs=dict(folder="raw"),
                                     jobs=[dict(file="c2.mp4", title="第二条", range=[0.5, 5.0])]), allow_unicode=True))
    r = plan_batch(str(p), echo=False)
    assert r["jobs"] == ["c1", "c2"]
    st = Store(r["batch_dir"])
    c2 = st.job("c2")["params"]
    assert c2["title"] == "第二条" and c2["range"] == [0.5, 5.0] and abs(c2["_dur"] - 4.5) < 1e-6
    assert st.job("c1")["params"]["source"].endswith("c1.mp4")
    st.close()
