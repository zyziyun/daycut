"""Recurring formats (vstudio.formats) and the first-pass check (vstudio.firstpass) run before a result is shown."""
import json
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio import firstpass as FP  # noqa: E402
from vstudio import formats as F  # noqa: E402

LIB = os.path.join(os.path.dirname(__file__), "..", "lib")


# ------------------------------------------------------------------------------------------------ formats
def test_every_format_has_every_field_and_a_real_workflow():
    root = os.path.join(os.path.dirname(__file__), "..", "workflows")
    for fid in F.names():
        f = F.get(fid, persona_formats={})
        for k in ("workflow", "speed", "hooks", "cleanup", "theme", "cover", "series_labels", "captions", "labels"):
            assert k in f, (fid, k)
        assert os.path.isfile(os.path.join(root, f["workflow"], "WORKFLOW.md")), fid
        assert f["hooks"] in ("menu", "none")
        assert f["cleanup"] in ("gentle", "standard", "tight", "off")
        assert 1.0 <= f["speed"]["body"] <= 1.4, "Chinese speech stays natural up to ~1.4x"
        assert f["speed"]["hook"] <= 1.6, "hooks above 1.6x sounded fake (加速都假了)"
        assert f["theme"] != "classic"
        assert f["cover"]["aspect"] == "video"


def test_learned_defaults():
    th = F.get("talking-head", persona_formats={})
    assert th["speed"]["body"] > 1.1 and th["hooks"] == "menu" and th["cleanup"] == "tight"
    assert th["series_labels"] is False and th["cover"]["retouch"]
    pr = F.get("promo", persona_formats={})
    assert pr["hooks"] == "none" and pr["speed"]["inserts"] == 1.1
    cc = F.get("call-clips", persona_formats={})
    assert cc["guests"] == "ask-mask" and cc["speed"]["body"] == 1.2
    assert F.get("photo-story", persona_formats={})["tag_set"] == "art"   # no career tags on an art post


def test_persona_overrides_and_aliases():
    f = F.get("口播", persona_formats={"talking-head": {"speed": {"body": 1.3}, "hooks": "none"}})
    assert f["id"] == "talking-head" and f["speed"]["body"] == 1.3 and f["speed"]["hook"] == 1.5
    assert f["hooks"] == "none"
    assert F.canonical("promo-recut") == "promo" and F.canonical("longform-to-short") == "lecture-slices"
    with pytest.raises(KeyError):
        F.get("nope")


@pytest.mark.parametrize("text,fid", [
    ("这条口播帮我剪一下发小红书", "talking-head"),
    ("宣传一下我做的 app，口播加截图", "promo"),
    ("zoom 播客切几条 3-8 分钟，把朋友的脸遮一下", "call-clips"),
    ("把这节课切成 20 条竖屏", "lecture-slices"),
    ("游泳 vlog，用我自己的录音", "vlog"),
    ("做个 3b1b 讲解视频", "explainer"),
    ("看展的照片做成文艺片", "photo-story"),
    ("用可灵做个 AI 短剧", "ai-skit"),
])
def test_detect(text, fid):
    assert F.detect(text) == fid


def test_detect_screenshots_turn_talking_head_into_promo():
    assert F.detect("口播剪一下") == "talking-head"
    assert F.detect("口播剪一下", materials={"screenshots": 3}) == "promo"
    assert F.detect("") is None


def test_summary_states_speed_hooks_and_what_is_not_done():
    s = F.summary(F.get("talking-head", persona_formats={}))
    assert "1.25x" in s and "候选" in s and "不加系列角标" in s and "同尺寸" in s
    p = F.summary(F.get("promo", persona_formats={}))
    assert "不加 hook" in p and "精选" in p
    assert "no hook montage" in F.summary("promo", "en")


def test_formats_cli():
    env = dict(os.environ, PYTHONPATH=LIB, VSTUDIO_DEFAULT_PERSONA="1")
    r = subprocess.run([sys.executable, "-m", "vstudio.formats", "detect", "播客切片", "--json"], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["format"] == "call-clips"
    r = subprocess.run([sys.executable, "-m", "vstudio.formats", "show", "promo"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "精选" in r.stdout


# ------------------------------------------------------------------------------------------------ firstpass
def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("fp")
    src = str(d / "src.mp4")
    fast = str(d / "fast.mp4")
    slow = str(d / "slow.mp4")
    mute = str(d / "mute.mp4")
    small = str(d / "small.mp4")
    v = ["-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration={d}"]
    a = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration={d}"]
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest"]

    def mk(out, dur, size="1080x1920", audio=True):
        vv = [x.format(d=dur).replace("1080x1920", size) for x in v]
        aa = [x.format(d=dur) for x in a] if audio else []
        _ff(*vv, *aa, *(enc if audio else enc[:6]), out)
    mk(src, 10)
    mk(fast, 8)          # 10 s / 1.25 = 8 s: sped up
    mk(slow, 10)         # same length as the source: the speed-up never happened
    mk(mute, 8, audio=False)
    mk(small, 8, size="540x960")
    from PIL import Image
    Image.new("RGB", (1080, 1920), (200, 200, 200)).save(d / "cover_ok.jpg")
    Image.new("RGB", (1080, 1440), (200, 200, 200)).save(d / "cover_34.jpg")
    Image.new("RGB", (1080, 1920), (20, 20, 20)).save(d / "cover_dark.jpg")
    return dict(dir=d, src=src, fast=fast, slow=slow, mute=mute, small=small)


def _ids(res, ok=False, sev=None):
    return {i["id"] for i in res["items"] if i["ok"] is ok and (sev is None or i["severity"] == sev)}


def test_speed_check_catches_a_missing_speed_up(media):
    good = FP.run(media["fast"], "talking-head", "xiaohongshu:full", [media["src"]], media_checks=False,
                  cover=str(media["dir"] / "cover_ok.jpg"))
    assert "speed" not in _ids(good)
    bad = FP.run(media["slow"], "talking-head", "xiaohongshu:full", [media["src"]], media_checks=False,
                 cover=str(media["dir"] / "cover_ok.jpg"))
    assert "speed" in _ids(bad, sev="red") and bad["ok"] is False
    hooked = FP.run(media["slow"], "talking-head", "xiaohongshu:full", [media["src"]], media_checks=False,
                    cover=str(media["dir"] / "cover_ok.jpg"), hook_seconds=3.0)
    assert "speed" not in _ids(hooked)                   # a 3 s hook montage explains the extra length


def test_no_audio_and_low_resolution_are_red(media):
    r = FP.run(media["mute"], "talking-head", "xiaohongshu:full", media_checks=False,
               cover=str(media["dir"] / "cover_ok.jpg"))
    assert "audio" in _ids(r, sev="red")
    r = FP.run(media["small"], "talking-head", "xiaohongshu:full", [media["src"]], media_checks=False,
               cover=str(media["dir"] / "cover_ok.jpg"))
    assert "resolution" in _ids(r, sev="red")


def test_cover_rules(media):
    d = media["dir"]
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", media_checks=False)
    assert "cover" in _ids(r, sev="red")
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", media_checks=False, cover=str(d / "cover_34.jpg"))
    assert "cover-aspect" in _ids(r, sev="red")              # "还是得和正片尺寸一样"
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", media_checks=False, cover=str(d / "cover_dark.jpg"))
    assert "cover-bright" in _ids(r, sev="warn") and "cover-aspect" not in _ids(r)


def test_export_cover_matches_each_output_and_firstpass_agrees(media, tmp_path):
    """Parity bug: a 1080x1920 小红书 video got a 1080x1440 cover. Each output's cover has that output's own canvas
    (the 3:4 cover only for the 3:4 version); firstpass confirms it on the real export."""
    from PIL import Image
    from vstudio import export as X
    cov = tmp_path / "picked.jpg"
    Image.new("RGB", (1080, 1920), (190, 190, 190)).save(cov)       # the picked 9:16 frame of the video
    man = X.export(media["fast"], ["xiaohongshu:full", "xiaohongshu:vertical"], str(tmp_path / "ex"),
                   covers=[str(cov)], preset="ultrafast", captions=False)
    sizes = {}
    for e in man["exports"]:
        video, cover = str(tmp_path / "ex" / e["file"]), str(tmp_path / "ex" / e["cover"])
        sizes[e["orientation"]] = Image.open(cover).size
        assert tuple(e["cover_size"]) == sizes[e["orientation"]]
        r = FP.run(video, "talking-head", f"xiaohongshu:{e['orientation']}", media_checks=False, cover=cover)
        assert not {"cover", "cover-aspect"} & _ids(r), (e["orientation"], r["items"])
    assert sizes == {"full": (1080, 1920), "vertical": (1080, 1440)}
    full = next(e for e in man["exports"] if e["orientation"] == "full")
    assert not any("blurred pad" in n for n in full["notes"])         # the 9:16 frame is used as is, not padded
    assert os.path.exists(tmp_path / "ex" / "xiaohongshu-full.cover.feed.jpg")   # the feed's centre 3:4 preview


def test_only_named_platforms_ask_for_a_cover_shape_other_than_the_video():
    """Covers follow the video's own canvas; the exceptions are upload forms that demand another shape."""
    from vstudio import platform as P
    odd = set()
    for k in P.list_profiles():
        p = P.profile(k, use_persona=False)
        cw, ch = P.cover_size(p)
        if abs((cw / ch) / (p.w / p.h) - 1) > 0.02:
            odd.add(k)
    assert odd == {"bilibili:horizontal", "bilibili:vertical", "wechat-channels:vertical"}, odd


def test_caption_checks(media, tmp_path):
    cues = [dict(start=0, end=2, text="我去了宏都拉斯"), dict(start=2, end=4, text="用 cloud code 写代码"),
            dict(start=4, end=6, text="嗯嗯 那个那个 然后"), dict(start=6, end=8, text="副业复盘01")]
    p = tmp_path / "cues.json"
    p.write_text(json.dumps({"cues": cues}, ensure_ascii=False))
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", media_checks=False, cues=str(p),
               cover=str(media["dir"] / "cover_ok.jpg"))
    bad = _ids(r)
    assert {"entities", "series-captions"} <= bad
    ent = next(i for i in r["items"] if i["id"] == "entities")
    assert any("洪都拉斯" in v for v in ent["value"])
    clean = [dict(start=0, end=2, text="我去了洪都拉斯"), dict(start=2, end=4, text="用【Claude Code】写代码")]
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", media_checks=False, cues=clean,
               cover=str(media["dir"] / "cover_ok.jpg"))
    assert not ({"entities", "terms", "series-captions"} & _ids(r))


def test_series_regex_keeps_ordinary_numbers():
    for t in ("50/50 分屏", "3:4 封面", "1.25x 加速", "2026年10月", "第一次面试"):
        assert not FP.SERIES_RE.search(t), t
    for t in ("01/04", "副业复盘02", "PART 2", "第3集", "EP.4"):
        assert FP.SERIES_RE.search(t), t


def test_post_title_and_series(media, tmp_path):
    post = tmp_path / "post.md"
    post.write_text("# 这是一个非常非常非常非常非常长的小红书标题会超出上限\n正文\n副业复盘03\n", encoding="utf-8")
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", media_checks=False, post=str(post),
               cover=str(media["dir"] / "cover_ok.jpg"))
    assert {"title", "series-post"} <= _ids(r)


def test_hooks_on_a_no_hook_format_warns(media):
    r = FP.run(media["fast"], "promo", "xiaohongshu:full", media_checks=False, hook_seconds=4,
               cover=str(media["dir"] / "cover_ok.jpg"))
    assert "hooks" in _ids(r, sev="warn")


def test_media_checks_and_report(media):
    r = FP.run(media["fast"], "talking-head", "xiaohongshu:full", [media["src"]],
               cover=str(media["dir"] / "cover_ok.jpg"))
    names = {i["id"] for i in r["items"]}
    assert {"loudness", "true-peak", "av-sync", "first-frame"} <= names
    assert "loudness" in _ids(r, sev="red")              # a raw sine is not at -14 LUFS
    md = FP.report(r)
    assert md.startswith("# 首轮自检") and "必须修" in md and "1.25x" in md
    assert "First-pass check" in FP.report(r, "en")


def test_firstpass_cli_exit_code(media):
    env = dict(os.environ, PYTHONPATH=LIB, VSTUDIO_DEFAULT_PERSONA="1")
    base = [sys.executable, "-m", "vstudio.firstpass", "--format", "talking-head", "--platform", "xiaohongshu:full",
            "--source", media["src"], "--cover", str(media["dir"] / "cover_ok.jpg"), "--no-media"]
    assert subprocess.run(base + [media["fast"]], env=env, capture_output=True).returncode == 0
    r = subprocess.run(base + [media["slow"], "--json"], env=env, capture_output=True, text=True)
    assert r.returncode == 1 and json.loads(r.stdout)["ok"] is False


def test_intake_routes_a_podcast_cut_into_clips_to_call_clips():
    from vstudio.intake.rules import recipe_scores
    for t in ("播客切片", "把这期播客切成几条"):
        sc = recipe_scores(t)
        assert max(sc, key=sc.get) == "call-clips", (t, sc)
    sc = recipe_scores("把这节课切片")
    assert max(sc, key=sc.get) == "longform-to-short"


def test_promo_post_never_gets_the_default_career_tags():
    """A promo / review post uses persona publish.tag_sets.promo, or only its own tags when there is none."""
    assert F.get("promo", persona_formats={})["tag_set"] == "promo"
    assert F.post_tags("promo", {}, persona_formats={}, tag_sets={}) == (False, None)
    assert F.post_tags("promo", {}, persona_formats={}, tag_sets={"promo": ["AI视频"]}) == (True, "promo")
    assert F.post_tags("promo", {"tag_set": "tech"}, persona_formats={}, tag_sets={}) == (True, "tech")
    assert F.post_tags("promo", {"use_persona_tags": False}, persona_formats={}, tag_sets={"promo": ["x"]}) == (False, None)
    assert F.post_tags("talking-head", {}, persona_formats={}, tag_sets={}) == (True, None)   # default tags stay
    assert F.post_tags("lesson-points", {}, persona_formats={}, tag_sets={"": ["x"]}) == (False, None)


def test_promo_post_copy_script_drops_career_tags(tmp_path, monkeypatch):
    import subprocess
    import sys
    import yaml
    home = tmp_path / "home"
    home.mkdir()
    (home / "persona.local.yaml").write_text(yaml.safe_dump(
        {"publish": {"tags": ["AIEngineer", "北美求职", "转码"]}}, allow_unicode=True), encoding="utf-8")
    cfg = tmp_path / "promo.config.yaml"
    cfg.write_text(yaml.safe_dump({"talk": "t.mp4", "post": {"title": "四个 AI 视频平台横评", "body": ["实测对比"],
                                                              "tags": ["AI视频", "可灵"], "chapters": False}},
                                  allow_unicode=True), encoding="utf-8")
    script = pathlib.Path(__file__).resolve().parents[1] / "workflows" / "promo-recut" / "scripts" / "post_copy.py"
    env = dict(os.environ, VSTUDIO_DEFAULT_PERSONA="1", VSTUDIO_PERSONA=str(home / "persona.local.yaml"))
    r = subprocess.run([sys.executable, str(script), str(cfg), "--platform", "xiaohongshu"], capture_output=True,
                       text=True, encoding="utf-8", env=env)
    assert r.returncode == 0, r.stderr
    text = (tmp_path / "post.md").read_text(encoding="utf-8")
    assert "#AI视频" in text and "#可灵" in text
    assert "北美求职" not in text and "AIEngineer" not in text
