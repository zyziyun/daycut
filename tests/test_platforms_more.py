"""Platforms added 2026-10 (Facebook, LinkedIn, Threads, Reddit, Pinterest, Snapchat, 快手, 微博, 知乎, Dailymotion,
Kwai): profiles load, display order, YouTube long-form / Shorts formats, text / link / hashtag checks, publishing."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import platform as P  # noqa: E402
from vstudio import publish  # noqa: E402

NEW = ["facebook", "linkedin", "threads", "reddit", "pinterest", "snapchat", "kuaishou", "weibo", "zhihu",
       "dailymotion", "kwai"]


def test_every_platform_is_ordered_and_grouped():
    assert set(P.ORDER) == set(P.PLATFORMS)
    assert len(P.ORDER) == len(set(P.ORDER))
    assert P.ORDER[:11] == ["youtube", "youtube-shorts", "tiktok", "instagram", "x", "facebook", "linkedin",
                            "threads", "reddit", "pinterest", "snapchat"]
    assert P.ORDER[11:18] == ["xiaohongshu", "douyin", "wechat-channels", "bilibili", "kuaishou", "weibo", "zhihu"]
    assert P.ORDER[18:] == ["dailymotion", "kwai"]
    for n in P.ORDER:
        assert P.profile(n).extra.get("group") == P.group_of(n), n
        assert P.publishing(n)["auto_post"] is False


def test_new_profiles_boxes_and_limits():
    for n in NEW:
        for o in P.PLATFORMS[n]["orientations"]:
            p = P.profile(n, o)
            x0, y0, x1, y1 = P.safe_box(p)
            c0, d0, c1, d1 = P.caption_box(p)
            assert 0 <= x0 < x1 <= p.w and 0 <= y0 < y1 <= p.h, (n, o)
            assert x0 <= c0 < c1 <= x1 and y0 <= d0 < d1 <= y1, (n, o)
            assert p.length["max"] >= p.length["sweet"][1] and p.length["min"] < p.length["max"]
            t0, t1, t2, t3 = P.cover_title_safe(p)
            assert t0 < t2 and t1 < t3
            assert "clickable" in P.link_policy(p)
        assert publish.title_max(n) == P.profile(n).title_max == publish.TITLE_MAX_DEFAULT[n]


def test_ordered_connected_float_within_group():
    names = ["kwai", "douyin", "x", "youtube-shorts:vertical", "weibo", "tiktok", "nope"]
    assert P.ordered(names) == ["youtube-shorts:vertical", "tiktok", "x", "douyin", "weibo", "kwai", "nope"]
    # connected weibo goes first among the Chinese platforms, never above the English group
    assert P.ordered(names, connected=["weibo", "x"]) == ["x", "youtube-shorts:vertical", "tiktok", "weibo", "douyin",
                                                          "kwai", "nope"]
    # a YouTube channel counts for Shorts too
    assert P.ordered(["tiktok", "youtube-shorts"], connected=["youtube"]) == ["youtube-shorts", "tiktok"]


def test_youtube_one_channel_two_formats():
    assert P.channel_of("youtube-shorts") == P.channel_of("youtube") == "youtube"
    assert P.FORMATS["youtube"] == {"long": "youtube", "shorts": "youtube-shorts"}
    assert P.youtube_format("9:16", 75) == "shorts" and P.youtube_format("1:1", 170) == "shorts"
    assert P.youtube_format("9:16", 240) == "long" and P.youtube_format("16:9", 30) == "long"
    assert P.check_format(P.profile("youtube"), 9 / 16, 60)                  # vertical-only master flagged
    assert not P.check_format(P.profile("youtube"), 16 / 9, 600)
    w = P.check_format(P.profile("youtube-shorts"), 16 / 9, 200)
    assert len(w) == 2 and "180" in w[1]
    assert P.profile("shorts").extra["format"] == "shorts"


def test_text_checks_title_links_hashtags():
    assert "reddit needs a title" in P.check_text(P.profile("reddit"), title="", body="hi")
    assert any("not use hashtags" in w for w in P.check_text(P.profile("reddit"), title="t", body="x #ai"))
    assert any("link field" in w for w in P.check_text(P.profile("pinterest"), title="t", body="go to example.com"))
    assert any("not clickable" in w for w in P.check_text(P.profile("instagram"), body="https://a.co/x"))
    assert any("not clickable" in w for w in P.check_text(P.profile("youtube-shorts"), title="t", body="https://a.co"))
    assert not P.check_text(P.profile("linkedin"), body="read https://example.com/post")
    assert not P.check_text(P.profile("youtube"), title="t", body="https://example.com")
    assert any("at least 6" in w for w in P.check_text(P.profile("weibo"), title="短标题", body="正文"))
    assert any("1 hashtags" in w or "2 hashtags" in w for w in P.check_text(P.profile("threads"), body="a #one #two"))
    assert P.check_text(P.profile("threads"), body="x" * 501)


def test_publish_copy_rules():
    assert publish.hashtags(["话题一", "话题二"], "weibo", use_persona=False, warn=None) == "#话题一# #话题二#"
    assert publish.hashtags(["a", "b"], "reddit", use_persona=False, warn=None) == ""
    assert publish.hashtags(["a", "b"], "threads", use_persona=False, warn=None) == "#a"
    body = publish.post_body("Hook line", "Body.", tags=["x"], platform="linkedin", title="My title", warn=None,
                             use_persona_tags=False)
    assert body.startswith("Hook line") and "My title" not in body           # no title field on LinkedIn
    body = publish.post_body("", "Body.", platform="reddit", title="A title", warn=None, use_persona_tags=False)
    assert body.startswith("A title")


@pytest.mark.parametrize("alias,name", [("fb", "facebook"), ("快手", "kuaishou"), ("微博", "weibo"), ("知乎", "zhihu"),
                                        ("spotlight", "snapchat"), ("dm", "dailymotion")])
def test_aliases(alias, name):
    assert P.canonical(alias) == name
