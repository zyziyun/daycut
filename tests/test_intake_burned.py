"""P1-8: a finished edit with burned-in captions (the fuye case: 多元副业复盘_final.mp4, 10:53 横屏成片, 字幕 /
进度条 / 记笔记已烧录) cut into 小红书 slices defaults to the band layout (old captions cropped off, new ones below),
and 小红书 defaults to 3:4 from the persona / platform default unless the creator names a shape."""
import pytest

from vstudio.intake import plan as PL
from test_intake import build


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_INTAKE_PROVIDER", "VSTUDIO_LLM_ROUTES_FILE"):
        monkeypatch.delenv(k, raising=False)


def _th(plan):
    ps = [p for p in plan["projects"] if p["recipe"] == "talkinghead"]
    assert ps, [p["recipe"] for p in plan["projects"]]
    return ps[0]


def test_fuye_finished_edit_to_xhs_slices_uses_band_and_3x4(tmp_path):
    a = build("finished", tmp_path)
    a["files"][0]["caption_band"] = "lower"
    plan = PL.make_plan("把后面自媒体的思考单独剪出来发小红书", analysis=a, asr="off")
    p = _th(plan)
    pr = p["params"]
    assert pr["layout"] == "band" and pr["crop_bottom"] == 0.28 and pr["captions"] is True
    assert pr["platforms"] == ["xiaohongshu:vertical"]                      # 3:4
    assert pr["speed"] == 1.0 and pr["cleanup_profile"] == "gentle"
    assert "裁掉旧字幕" in plan["summary_zh"] and "保留原字幕" not in plan["summary_zh"]
    assert PL.validate(plan) == []


def test_keep_old_captions_when_asked(tmp_path):
    plan = PL.make_plan("把后面自媒体的思考单独剪出来，保留原字幕", analysis=build("finished", tmp_path), asr="off")
    pr = _th(plan)["params"]
    assert pr["captions"] is False and pr.get("layout") != "band" and "crop_bottom" not in pr


def test_persona_keep_and_explicit_9x16(tmp_path, monkeypatch):
    from vstudio import config
    real = config.persona()
    monkeypatch.setattr(PL, "context", lambda client=None, _c=PL.context: dict(_c(client), burned="keep"))
    pr = _th(PL.make_plan("把后面自媒体的思考单独剪出来", analysis=build("finished", tmp_path), asr="off"))["params"]
    assert pr["captions"] is False and pr.get("layout") != "band"
    monkeypatch.undo()
    pr = _th(PL.make_plan("这段口播剪干净发小红书 9:16", analysis=build("talk", tmp_path / "t"), asr="off"))["params"]
    assert pr["platforms"] == ["xiaohongshu:full"]
    assert real is config.persona()


def test_persona_post_shape_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(PL, "context", lambda client=None, _c=PL.context: dict(
        _c(client), shapes={"xiaohongshu": "full"}))
    pr = _th(PL.make_plan("这段口播剪干净发小红书", analysis=build("talk", tmp_path), asr="off"))["params"]
    assert pr["platforms"] == ["xiaohongshu:full"]


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")
def test_export_band_layout_crops_old_captions(tmp_path):
    """layout band: the bottom 28 % (old burned captions) is cropped off, the rest fitted on the 3:4 canvas."""
    import subprocess
    from vstudio import export as X, platform as PF
    src = tmp_path / "m.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25", "-f", "lavfi",
                    "-i", "sine=f=440:sample_rate=48000", "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(src)], check=True)
    e = X.export_one(str(src), PF.profile("xiaohongshu", "vertical"), str(tmp_path), mode="band", crop_bottom=0.28,
                     captions=False)
    assert (e["w"], e["h"]) == (1080, 1440)
    assert e["reframe"]["band"]["region"] == [0, 0, 640, 258] and e["reframe"]["mode_used"] == "pad-blur"
