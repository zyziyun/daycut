"""The talkinghead pipeline and vstudio.firstpass agree: speeds come from the format, the cover has the video's
canvas, and the exported post never carries an over-limit (or misread) title."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio import firstpass as FP  # noqa: E402
from vstudio import formats as F  # noqa: E402
from vstudio import platform as P  # noqa: E402
from vstudio import publish  # noqa: E402
from vstudio.project import manifests as M  # noqa: E402

TH = os.path.join(os.path.dirname(__file__), "..", "workflows", "talkinghead", "recipe.yaml")


# ------------------------------------------------------------------------------------------- speed from the format
def test_talkinghead_defaults_come_from_the_talking_head_format():
    f = F.get("talking-head")
    d = M.param_defaults(M.get("talkinghead"))
    assert d["speed"] == f["speed"]["body"] == 1.25
    assert d["hook_speed"] == f["speed"]["hook"]
    assert d["cleanup_profile"] == f["cleanup"]
    assert d["cover_canvas"] == f["cover"]["aspect"] == "video"


def test_persona_format_override_reaches_the_recipe_default(monkeypatch):
    monkeypatch.setattr(F, "_persona_formats", lambda: {"talking-head": {"speed": {"body": 1.3}}})
    assert M.param_defaults(M.load(TH))["speed"] == 1.3


def test_x_format_param_may_not_hard_code_a_default():
    m = M.load(TH)
    m["params"]["properties"]["speed"]["default"] = 1.1
    with pytest.raises(M.ManifestError, match="both x-format and a default"):
        M.format_defaults(m)


def test_unknown_x_format_path_is_an_error():
    m = M.load(TH)
    sch = m["params"]["properties"]["speed"]
    sch.pop("default")
    sch["x-format"] = "speed.nope"
    with pytest.raises(M.ManifestError, match="not in format"):
        M.format_defaults(m)


def test_every_x_format_default_is_valid():
    for rid, m in M.all_manifests().items():
        assert not M._param_default_errors(m), rid


# ------------------------------------------------------------------------------------------- cover on the video canvas
def test_xiaohongshu_full_cover_follows_the_video_canvas():
    p = P.profile("xiaohongshu", "full")
    assert P.cover_size(p) == (1080, 1440)                    # the platform's own upload shape is unchanged
    v = P.video_canvas_cover(p)
    assert P.cover_size(v) == (1080, 1920) and v.cover_aspect == "9:16"
    assert v.cover["feed_crop"] == "3:4"
    x0, y0, x1, y1 = P.cover_title_safe(v)
    c0, d0, c1, d1 = P.crop_box(1080, 1920, "3:4")
    assert c0 <= x0 < x1 <= c1 and d0 <= y0 < y1 <= d1      # the headline survives the 3:4 feed tile
    same = P.profile("xiaohongshu", "vertical")
    assert P.video_canvas_cover(same) is same                # 3:4 video: the cover already matches


def test_make_cover_on_the_video_canvas_writes_a_feed_preview(tmp_path):
    from PIL import Image
    from vstudio import export as X
    src = tmp_path / "cover.png"
    Image.new("RGB", (1080, 1920), (200, 190, 180)).save(src)
    p = P.video_canvas_cover(P.profile("xiaohongshu", "full"))
    out, notes = X.make_cover(p, [str(src)], None, str(tmp_path / "x.cover.jpg"))
    assert Image.open(out).size == (1080, 1920)
    assert Image.open(tmp_path / "x.cover.feed.jpg").size == (1080, 1440)
    assert any("3:4" in n for n in notes)


def test_export_stage_passes_the_cover_canvas_only_when_set():
    from vstudio.batch import stages as ST
    job = dict(params=dict(platforms=["xiaohongshu:full"], cover_canvas="video"))
    assert ST._export_params(job, {})["cover_canvas"] == "video"
    assert "cover_canvas" not in ST._export_params(dict(params=dict(platforms=["douyin"])), {})


# ------------------------------------------------------------------------------------------- post title
@pytest.mark.parametrize("title, want", [
    ("如何把一个入门岗，拍成你高攀不起的样子（北美求职真实经历分享）", "如何把一个入门岗，拍成你高攀不起的样子"),
    ("AI Engineer面试复盘｜我是怎么从零准备到拿到大厂offer的", "我是怎么从零准备到拿到大厂offer的"),
    ("学习新模式｜让AI给你做3b1b讲解视频", "学习新模式｜让AI给你做3b1b讲解视频"),
])
def test_fit_title(title, want):
    out = publish.fit_title(title, "xiaohongshu")
    assert out == want and publish.check_title(out, "xiaohongshu")[0]


def test_fit_title_never_ends_in_half_a_word_and_skips_no_title_platforms():
    out = publish.fit_title("我准备 AI Engineer interview 的全部过程和踩过的坑总结", "xiaohongshu")
    assert publish.check_title(out, "xiaohongshu")[0] and not out.endswith(("interv", "Engin"))
    long = "x" * 400
    assert publish.fit_title(long, "x") == long                # X has no title field


def test_post_body_shortens_an_over_limit_title_before_writing():
    warns = []
    text = publish.post_body("", "正文", platform="xiaohongshu", warn=warns.append, use_persona_tags=False,
                             title="如何把一个入门岗，拍成你高攀不起的样子（北美求职真实经历分享）")
    assert text.splitlines()[0] == "如何把一个入门岗，拍成你高攀不起的样子"
    assert any("shortened" in w for w in warns)


def test_firstpass_does_not_read_a_hashtag_line_as_the_title(tmp_path):
    post = tmp_path / "xiaohongshu-full.post.md"
    post.write_text("#AIEngineer #北美求职 #转码 #SDE #AI面试 #大厂面试 #程序员转行 #在职跳槽\n", encoding="utf-8")
    assert FP.load_post(str(post))[0] == ""
    prof = P.profile("xiaohongshu", "full")
    items = FP.check_post("", post.read_text(encoding="utf-8"), prof, None, post_given=True)
    t = [i for i in items if i["id"] == "title"]
    assert t and t[0]["ok"] is False and "有标题" in t[0]["zh"]
    post.write_text("# 我的标题\n\n正文\n", encoding="utf-8")
    assert FP.load_post(str(post))[0] == "我的标题"
