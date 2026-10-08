"""Attached B-roll is never dropped by the intake planner: a promo-recut plan keeps every recording / folder clip she
attached (``broll`` input), extra files of a one-file input move to ``broll``, and what no project uses is listed
back (``plan.unused`` + a risk line). No network, no media work (the analysis is synthetic)."""
import os

import pytest

from vstudio.intake import apply as AP
from vstudio.intake import plan as PL
from vstudio.project.core import Project


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_INTAKE_PROVIDER"):
        monkeypatch.delenv(k, raising=False)


def _analysis(d):
    """talk.mp4 + 3 screen recordings + 2 screenshots + a folder of finished cuts (group g1), attached one by one."""
    files, n = [], 0

    def add(rel, kind, **kw):
        nonlocal n
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
        n += 1
        f = dict(id=f"f{n}", path=str(p), rel=rel, kind=kind, size=1, qhash=f"h{n}", **kw)
        files.append(f)
        return f
    v = dict(width=1920, height=1080, orientation="horizontal", has_audio=True, speech=True, language="zh")
    add("talk.mp4", "video", duration=760, talking_head=True, **v)
    for k in range(3):
        add(f"Screen Recording {k}.mov", "video", duration=60, screen_share=True, **v)
    add("shot1.png", "image", width=2000, height=1200, orientation="horizontal")
    add("shot2.png", "image", width=2000, height=1200, orientation="horizontal")
    cuts = [add(f"cuts/ad{k}.mp4", "video", duration=30, **v)["id"] for k in range(2)]
    tops = [f["path"] for f in files if not f["rel"].startswith("cuts/")] + [str(d / "cuts")]   # rel: "/" on every OS
    tot = dict(videos=6, video_s=1000, audio=0, audio_s=0.0, images=2, texts=0, other=0)
    return dict(version=1, kind="vstudio.intake.analysis", inputs=tops, digest="d" * 16, asr="sample", totals=tot,
                files=files, groups=[dict(id="g1", kind="clip-set", folder=str(d / "cuts"), files=cuts, n=2)],
                urls=[], notes=[])


def _plan(tmp_path, reply):
    a = _analysis(tmp_path / "m")
    return PL.make_plan("剪这条口播，录屏、截图和文件夹里的成片都是插片素材", analysis=a, asr="off",
                        call=lambda s, b: dict(json=dict(projects=[reply]), model="mock", cost_usd=0.0)), a


def test_catalog_offers_broll_for_promo():
    cat = {r["id"]: r for r in PL.catalog()}
    keys = {i["key"]: i for i in cat["promo-recut"]["inputs"]}
    assert keys["broll"]["multiple"] and keys["broll"]["kind"] == "video" and not keys["highlights"]["multiple"]
    assert "broll" in PL.SYSTEM


def test_model_squeezing_videos_into_highlights_keeps_them_as_broll(tmp_path):
    # the model of the bug report: talk + screenshots, recordings named only as materials / in the one-file input
    plan, a = _plan(tmp_path, dict(recipe="promo-recut", name="评测", materials=["f1", "f2", "f3", "f4", "f5", "f6"],
                                   inputs=dict(talk=["f1"], screenshots=["f5", "f6"], highlights=["f2", "f3"]),
                                   items=dict(method="single")))
    p = plan["projects"][0]
    by = {f["id"]: f["path"] for f in a["files"]}
    assert p["inputs"]["highlights"] == by["f2"]
    assert p["inputs"]["broll"] == [by["f3"], by["f4"]]              # f3: overflow, f4: listed in materials
    assert any("broll" in w for w in plan["warnings"])
    # the folder of finished cuts was attached but used nowhere: listed back, never silently gone
    assert [u["name"] for u in plan["unused"]] == ["cuts"] and plan["unused"][0]["files"] == 2
    assert any(r["code"] == "intake.risk.unused-inputs" for r in plan["risks_info"])
    assert not PL.validate(plan)


def test_attached_recordings_the_model_forgot_go_to_broll(tmp_path):
    plan, a = _plan(tmp_path, dict(recipe="promo-recut", name="评测", inputs=dict(talk=["f1"], screenshots=["f5", "f6"],
                                                                               broll=["g1"])))
    by = {f["id"]: f["path"] for f in a["files"]}
    br = plan["projects"][0]["inputs"]["broll"]
    assert set(br) == {by[k] for k in ("f2", "f3", "f4", "f7", "f8")}  # the folder (g1) + the loose recordings
    assert plan["unused"] == [] and not any("没有用在" in r for r in plan["risks"])


def test_apply_writes_broll_into_project_yaml(tmp_path):
    plan, a = _plan(tmp_path, dict(recipe="promo-recut", name="评测", inputs=dict(talk=["f1"], broll=["f2", "g1"])))
    res = AP.apply_plan(plan, str(tmp_path / "out"))
    pr = Project(res["projects"][0]["dir"])
    br = pr.data["inputs"]["broll"]
    assert len(br) == 5 and all(os.path.isabs(x) for x in br)
    rows = pr.jobs_rows()
    assert rows and rows[0]["_inputs"]["broll"] == br                 # every item sees (and prepare links) them
