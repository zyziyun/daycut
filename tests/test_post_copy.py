"""Post copy for the talking-head recipes: a title + short body drafted from the final captions when the creator
gave none (vstudio.clipcopy.draft_post, the batch ``copy`` stage), shown in the publish checkpoint as a draft and
used as the baseline of a review copy edit. The text model is a fake injected through ``spec.copy.call``."""
import json
import os
import shutil

import pytest
import yaml

from vstudio import clipcopy as CC
from vstudio import firstpass as FP
from vstudio import platform as PF
from vstudio import publish
from vstudio.batch import api as API
from vstudio.batch import edits as ED
from vstudio.batch import thfolder as TH
from vstudio.batch.plan import plan_batch
from vstudio.batch.run import run_batch
from vstudio.batch.store import Store
from vstudio.project.adapters import common as CM

from test_batch_p1 import tiny

needs_ff = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

LINES = ["副业最重要的不是赚钱", "副业让我换了一个圈子", "我认识了很多做自媒体的朋友", "这些朋友让我看到了不同的生活方式",
         "副业也反过来帮助了我的主业", "所以我觉得副业是值得做的", "做副业要先想清楚自己想要什么", "副业不一定要赚很多钱"]
SENTS = [dict(t=k * 3.0, te=k * 3.0 + 2.5, text=x) for k, x in enumerate(LINES)]
CALLS = []


def fake_copy(task, system, prompt, schema=None, provider=None):
    """The routed ``copy`` model: a title too long for 视频号 and a body with a hashtag and an em-dash."""
    CALLS.append(dict(task=task, system=system, prompt=prompt, schema=schema))
    return {"provider": "fake", "json": {
        "title": "副业带给我的不是钱而是一个新的圈子和看世界的方式",
        "body": "这条聊聊我做副业两年的感受——最大的收获不是赚钱，是换了一个圈子。#副业 也反过来帮了我的主业。"}}


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    CALLS.clear()


# ------------------------------------------------------------------------------------------------ draft_post
def test_model_copy_title_passes_every_platform_and_body_follows_the_voice_rules():
    plats = ["xiaohongshu:full", "wechat-channels", "douyin"]
    d = CC.draft_post(SENTS, plats, complete=fake_copy)
    assert CALLS[0]["task"] == "copy" and "[7]" in CALLS[0]["prompt"] and "body" in CALLS[0]["system"]
    assert d["source"] == "llm:fake" and d["drafted"] == ["title", "body"]
    for pl in ("xiaohongshu", "wechat-channels", "douyin"):
        assert publish.check_title(d["title"], pl)[0], (pl, d["title"])
    assert d["title_note"] and "wechat-channels" in d["title_note"]          # the shortening is said, not silent
    assert "—" not in d["body"] and "#" not in d["body"] and "换了一个圈子" in d["body"]
    assert any("em-dash" in n for n in d["notes"]) and d["warnings"] == []
    assert len(d["body"]) <= CC.BODY_MAX["zh"]


def test_creator_copy_is_kept_and_only_the_missing_part_is_drafted():
    d = CC.draft_post(SENTS, ["xiaohongshu:full"], title="她自己写的", body="她自己的正文", complete=fake_copy)
    assert d == dict(d, title="她自己写的", body="她自己的正文", drafted=[], source="given") and not CALLS
    d = CC.draft_post(SENTS, ["xiaohongshu:full"], title="她自己写的", complete=fake_copy)
    assert d["title"] == "她自己写的" and d["drafted"] == ["body"] and d["body"]
    assert "keep exactly '她自己写的'" in CALLS[0]["system"]


def test_without_a_model_the_copy_is_spoken_lines_and_says_so():
    d = CC.draft_post(SENTS, ["xiaohongshu:full", "wechat-channels"])
    assert d["source"] == "transcript" and d["drafted"] == ["title", "body"]
    assert publish.check_title(d["title"], "wechat-channels")[0] and publish.check_title(d["title"], "xiaohongshu")[0]
    assert d["body"] and d["title"] not in d["body"]                         # the title is not repeated as a line
    assert any("edit them before publishing" in n for n in d["notes"])


def test_a_failing_model_raises_instead_of_inventing_copy():
    def broken(*a, **k):
        return {"provider": "fake", "text": "sorry"}
    with pytest.raises(ValueError, match="no JSON"):
        CC.draft_post(SENTS, ["xiaohongshu:full"], complete=broken)


# ------------------------------------------------------------------------------------------------ the batch stage
def _fake_th(raw_lines):
    def fake_run(cmd, cwd, log, env=None, timeout=None):
        name = os.path.basename(str(cmd[1]))
        if name == "prep_sources.sh":
            shutil.copyfile(str(cmd[3]), os.path.join(cwd, "sdr1.mp4"))
            open(os.path.join(cwd, "a1.wav"), "wb").write(b"RIFF")
            json.dump(dict(language="zh", segments=[dict(start=k * 3.0, end=k * 3.0 + 2.5, text=x, words=[
                dict(word=x, start=k * 3.0, end=k * 3.0 + 2.5)]) for k, x in enumerate(raw_lines)]),
                open(os.path.join(cwd, "a1.json"), "w", encoding="utf-8"), ensure_ascii=False)
        elif name == "cut_pass1.py":
            json.dump(dict(edits=[]), open(os.path.join(cwd, "cleanup.c1.json"), "w"))
            shutil.copyfile(os.path.join(cwd, "sdr1.mp4"), os.path.join(cwd, "body_v.mp4"))
        elif name == "strict_pass.py":
            shutil.copyfile(os.path.join(cwd, "body_v.mp4"), os.path.join(cwd, "body2_v.mp4"))
            open(os.path.join(cwd, "body2_a.wav"), "wb").write(b"RIFF")
            json.dump(dict(subs=[], total=2.0), open(os.path.join(cwd, "segs.json"), "w"))
        elif name == "face_track.py":
            raise RuntimeError("no face model")
        elif name == "compose.py":
            cfg = {}
            exec(open(os.path.join(cwd, "config.py"), encoding="utf-8").read(), cfg)
            stem = os.path.splitext(cfg["OUT"])[0]
            tiny(os.path.join(cwd, stem + ".clean.mp4"), 2.5)
            json.dump(dict(cues=[dict(start=k * 0.3, end=k * 0.3 + 0.28, text=x) for k, x in enumerate(raw_lines)]),
                      open(os.path.join(cwd, stem + ".cues.json"), "w", encoding="utf-8"), ensure_ascii=False)
        return "ok"
    return fake_run


def _batch(tmp_path, monkeypatch, **spec_kw):
    raw = tmp_path / "raw"
    raw.mkdir()
    tiny(raw / "fuye.mp4", 3.0)
    tiny(raw / "given.mp4", 3.0)
    monkeypatch.setattr(TH, "_run", _fake_th(LINES))
    spec = dict(name="th", recipe="talkinghead-folder", inputs=dict(folder=str(raw)), retry={"backoff": 0},
                proofread={"provider": "none"}, qc={"sample_pct": 0},
                jobs=[dict(id="given", file="given.mp4", title="她自己的标题", body="她自己的正文")],
                defaults=dict(platforms=["xiaohongshu:full"], preset="ultrafast", note_cards=False))
    spec.update(spec_kw)
    sp = tmp_path / "batch.yaml"
    sp.write_text(yaml.safe_dump(spec, allow_unicode=True))
    r = plan_batch(str(sp), echo=False)
    res = run_batch(r["batch_dir"], echo=False)
    assert res["exit_code"] == 0, res
    return r["batch_dir"]


class _Env:
    def __init__(self, params, inputs):
        self.params, self.inputs = params, inputs


@needs_ff
def test_talkinghead_post_gets_a_drafted_title_and_body_shown_for_review(tmp_path, monkeypatch):
    bdir = _batch(tmp_path, monkeypatch, copy={"call": "test_post_copy:fake_copy"})
    st = Store(bdir)
    cp = st.stage("fuye", "copy")["out"]
    ex = st.stage("fuye", "export")["out"]
    qc = st.stage("fuye", "qc")["out"]
    given = st.stage("given", "copy")["out"]
    params = st.job("fuye")["params"]
    st.close()
    assert cp["source"] == "llm:fake" and cp["drafted"] == ["title", "body"]
    post = open(ex["exports"][0]["post"], encoding="utf-8").read()
    assert post.startswith(cp["title"] + "\n\n" + cp["body"])
    assert ex["title_source"] == ex["body_source"] == "llm:fake"
    assert not any(c["name"] == "title" and c.get("ok") is None for c in qc.get("checks") or [])
    title, text = FP.load_post(ex["exports"][0]["post"])               # the firstpass 文案有标题 check passes
    items = FP.check_post(title, text, PF.parse_targets(["xiaohongshu:full"])[0], fmt={})
    assert title == cp["title"] and items and all(i["ok"] for i in items), items
    # the creator's own copy is kept, nothing drafted
    assert given["source"] == "given" and given["drafted"] == [] and given["title"] == "她自己的标题"
    # the publish checkpoint shows the draft, where it came from and how to edit it
    pc = CM.publish_copy(_Env(params, dict(copy=cp, export=ex)))
    assert pc["title"] == cp["title"] and pc["body"] == cp["body"] and pc["drafted"] == ["title", "body"]
    assert pc["source"] == "llm:fake" and "--op copy" in pc["edit"]


@needs_ff
def test_without_a_model_the_stage_drafts_from_the_transcript(tmp_path, monkeypatch):
    bdir = _batch(tmp_path, monkeypatch)
    st = Store(bdir)
    cp = st.stage("fuye", "copy")["out"]
    ex = st.stage("fuye", "export")["out"]
    st.close()
    assert cp["source"] == "transcript" and cp["title"] and cp["body"]
    assert publish.check_title(cp["title"], "xiaohongshu")[0]
    post = open(ex["exports"][0]["post"], encoding="utf-8").read()
    assert post.startswith(cp["title"] + "\n\n" + cp["body"])


@needs_ff
def test_a_review_copy_edit_starts_from_the_drafted_copy(tmp_path, monkeypatch):
    bdir = _batch(tmp_path, monkeypatch, copy={"call": "test_post_copy:fake_copy"})
    st = Store(bdir)
    cp = st.stage("fuye", "copy")["out"]
    pp = st.stage("fuye", "export")["out"]["exports"][0]["post"]
    st.close()
    ed = API.job_detail(bdir, "fuye", words=False)["edit"]                # the desk copy editor starts from the draft
    assert ed["copy"]["title"] == cp["title"] and ed["copy_drafted"]["keys"] == ["title", "body"]
    r = ED.edit(bdir, "fuye", "copy", title="换了圈子，才知道副业的意义")
    assert r["ok"] and r["before"]["title"] == cp["title"] and r["value"]["body"] == cp["body"]
    post = open(pp, encoding="utf-8").read()
    assert post.startswith("换了圈子，才知道副业的意义\n\n" + cp["body"]) and post.count(cp["body"]) == 1
    assert cp["title"] not in post
    assert API.job_detail(bdir, "fuye", words=False)["edit"]["copy_drafted"] is None   # now hers
    ED.edit(bdir, "fuye", "undo")
    assert open(pp, encoding="utf-8").read().startswith(cp["title"] + "\n\n" + cp["body"])
