"""X / Instagram / 视频号 profiles, text checks, localized post copy, export re-layout and the optional API
uploaders (fake HTTP) - all on SYNTHETIC media."""
import json
import os
import pathlib
import shutil
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "workflows" / "ai-video" / "scripts"))

from vstudio import media, publish  # noqa: E402
from vstudio import export as X  # noqa: E402
from vstudio import platform as P  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


# ----------------------------------------------------------------------------------- profiles
def test_profiles_sizes_aliases_and_safe_boxes():
    want = {"x:horizontal": (1920, 1080), "x:square": (1080, 1080), "x:vertical": (1080, 1920),
            "instagram:reels": (1080, 1920), "instagram:feed": (1080, 1350),
            "wechat-channels:vertical": (1080, 1920), "wechat-channels:horizontal": (1920, 1080)}
    for k, wh in want.items():
        p = P.profile(k)
        assert p.size == wh, k
        x0, y0, x1, y1 = P.safe_box(p)
        c0, d0, c1, d1 = P.caption_box(p)
        assert 0 <= x0 <= c0 < c1 <= x1 <= p.w and 0 <= y0 <= d0 < d1 <= y1 <= p.h, k
    assert P.profile("twitter").key == "x:horizontal" and P.profile("推特", "9:16").key == "x:vertical"
    assert P.profile("ig").key == "instagram:reels" and P.profile("ins", "4:5").key == "instagram:feed"
    assert P.profile("instagram", "feed").key == "instagram:feed"         # "feed" is not the 3:4 alias here
    assert P.profile("instagram", "vertical").key == "instagram:reels"
    assert P.profile("reels").key == "instagram:reels" and P.profile("视频号").key == "wechat-channels:vertical"
    assert P.profile("channels", "horizontal").size == (1920, 1080)
    # Instagram Reels: the safe box sits inside the 4:5 feed crop and clear of the right rail
    ig = P.profile("instagram")
    fx0, fy0, fx1, fy1 = P.feed_crop_box(ig)
    assert (fy0, fy1) == (285, 1635)
    sx0, sy0, sx1, sy1 = P.safe_box(ig)
    assert sy0 >= fy0 and sy1 <= fy1 and sx1 <= 1080 - 130
    c0, d0, c1, d1 = P.caption_box(ig)
    assert c1 <= P.keepouts(ig)[0][0]
    # X: captions recommended (muted autoplay), standard caps
    x = P.profile("x")
    assert x.extra["captions"]["burn"] == "recommended" and x.length["max"] == 140
    assert x.extra["limits"]["max_bytes"] == 512_000_000 and x.desc_max == 280 and x.title_max == 0


def test_best_orientation_and_tiers():
    assert P.best_orientation("x", 16 / 9) == "horizontal"
    assert P.best_orientation("x", "4:5") == "square"
    assert P.best_orientation("x", "9:16") == "vertical"
    keys = [p.key for p in P.parse_targets("x,instagram,x:square", master_aspect=9 / 16)]
    assert keys == ["x:vertical", "instagram:reels", "x:square"]
    assert [p.key for p in P.parse_targets("x", master_aspect=16 / 9)] == ["x:horizontal"]
    prem = P.profile("x", overrides={"account": "premium"})
    assert prem.desc_max == 25000 and prem.length["max"] > 140 and prem.extra["limits"]["max_bytes"] > 512_000_000
    assert P.check_length(P.profile("x"), 200) and not P.check_length(prem, 200)[:1] == ["over"]
    assert not any("over the" in w for w in P.check_length(prem, 200))
    assert any("non-followers" in w for w in P.check_length(P.profile("instagram"), 240))


def test_cover_crops_and_title_safe():
    ig = P.profile("instagram")
    assert P.cover_crops(ig) == ["4:5", "3:4", "1:1"]
    assert P.crop_box(1080, 1920, "4:5") == (0, 285, 1080, 1635)
    assert P.crop_box(1080, 1920, "1:1") == (0, 420, 1080, 1500)
    assert P.cover_title_safe(ig) == (60, 420, 1020, 1500)                # survives feed, grid and 1:1
    assert P.cover_crops(P.profile("instagram:feed")) == ["3:4", "1:1"]
    bili = P.profile("bilibili")
    assert P.cover_size(bili) == (1146, 717) and P.cover_crops(bili) == ["4:3", "16:9"]
    t0, t1, t2, t3 = P.cover_title_safe(bili)
    c43 = P.crop_box(1146, 717, "4:3")
    assert t0 >= c43[0] and t2 <= c43[2]
    assert bili.extra["category"]["required"]
    assert P.cover_crops(P.profile("wechat-channels")) == ["6:7"]
    assert P.profile("douyin").cover["feed_crop"] == "3:4" and P.cover_crops(P.profile("douyin")) == ["3:4"]


def test_x_weighted_length_and_text_checks():
    assert P.x_weighted_len("hello") == 5
    assert P.x_weighted_len("你好") == 4                                   # CJK = 2
    assert P.x_weighted_len("see https://example.com/a/very/long/path?x=1") == 4 + 23
    assert P.x_weighted_len("😀") == 2 and P.x_weighted_len("👍🏽") == 2 and P.x_weighted_len("👨‍👩‍👧") == 2
    assert P.x_weighted_len("“quote”—ok") == 10                           # general punctuation = 1
    x = P.profile("x")
    assert not P.check_text(x, body="a" * 280)
    assert P.check_text(x, body="中" * 141)                                # 282 weighted > 280
    assert not P.check_text(x, body="中" * 140)
    assert any("weighted" in w for w in P.check_text(x, body="中" * 141))
    ig = P.profile("instagram")
    assert not P.check_text(ig, body="caption #a #b #c", tags=["a", "d"])  # 4 distinct
    w = P.check_text(ig, body="caption #a #b #c #e", tags=["d", "f"])     # 6 distinct -> over the hard 5
    assert w and "hard limit" in w[0]
    assert P.hashtags_in("x #One #two #one, #三") == ["one", "two", "三"]


# ----------------------------------------------------------------------------------- post copy
POST = {"en": {"title": "Cut one talk into ten shorts", "hook": "One recording, ten clips.",
               "body": "Here is how it works. " * 30, "tags": ["video", "editing", "ai", "shorts", "creator", "tips"]},
        "zh": {"title": "一条长视频切十条", "hook": "一次录制，十条短视频。", "body": "方法如下。", "tags": ["剪辑", "AI"]}}


def test_localized_copy_english_default_and_bilingual():
    msgs = []
    text, c = publish.platform_post(POST, "x", content_lang="en", warn=msgs.append)
    assert c["lang"] == "en" and text.startswith("One recording, ten clips.")
    assert P.x_weighted_len(text) <= 280 and text.rstrip().endswith("#video #editing")   # X: 2 tags
    assert any("shortened" in m for m in msgs)
    text, c = publish.platform_post(POST, "instagram", content_lang="en", warn=msgs.append)
    assert c["lang"] == "en" and len(P.hashtags_in(text)) == 5 and not text.startswith("Cut one")  # no title line
    text, c = publish.platform_post(POST, "instagram", content_lang="en", bilingual=True, warn=msgs.append)
    assert c["lang"] == "en+zh" and "方法如下" in text and text.index("Here is") < text.index("方法如下")
    assert len(P.hashtags_in(text)) == 5
    zh, c = publish.platform_post(POST, "xiaohongshu", content_lang="zh", warn=msgs.append)
    assert c["lang"] == "zh" and zh.startswith("一条长视频切十条")
    # no content language: international platforms pick English when there is an English block
    assert publish.localize_post(POST, "instagram")["lang"] == "en"
    assert publish.localize_post(POST, "douyin")["lang"] == "zh"
    assert publish.localize_post(dict(POST, lang_by_platform={"x": "zh"}), "x", content_lang="en")["lang"] == "zh"
    assert publish.detect_lang(["This is English speech"]) == "en" and publish.detect_lang("这是中文") == "zh"
    ok, n, hints = publish.check_title("anything", "x")
    assert ok and "no title field" in hints[0]


def test_generate_copy_uses_llm_and_fits_x():
    calls = []

    def fake_complete(task, system, prompt, schema=None, provider=None):
        calls.append((task, system))
        return {"json": {"hook": "Hook line.", "body": "Body sentence. " * 40, "tags": ["a", "b", "c"]}}
    out = publish.generate_copy("x", "transcript text", lang="en", complete=fake_complete, warn=lambda *a: None)
    assert calls[0][0] == "copy" and "280" in calls[0][1] and "weighted" in calls[0][1]
    assert P.x_weighted_len(out["text"]) <= 280 and out["text"].startswith("Hook line.")
    assert publish.generate_copy("x", "t", complete=lambda *a, **k: {"json": None}) is None


# ----------------------------------------------------------------------------------- export
@pytest.fixture(scope="module")
def master(tmp_path_factory):
    d = tmp_path_factory.mktemp("intl")
    p = d / "master.mp4"
    media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x203040:s=1280x720:r=30:d=3",
               "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3", "-af", "volume=0.08",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)])
    return str(p)


@needs_ffmpeg
def test_export_relayout_x_and_instagram(master, tmp_path):
    from PIL import Image, ImageDraw
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps([{"start": 0.3, "end": 2.6, "text": "This is an English caption"}]), encoding="utf-8")
    cov = tmp_path / "cover916.png"
    im = Image.new("RGB", (1080, 1920), (30, 30, 40))
    d = ImageDraw.Draw(im)
    for y in range(60, 250, 50):                                  # glyph-like "headline" at the very top: cut by 4:5/1:1
        for x in range(80, 1000, 34):
            d.rectangle((x, y, x + 22, y + 30), fill=(255, 255, 255))
    im.save(cov)
    out = tmp_path / "exports"
    man = X.export(master, "x,instagram,instagram:feed", str(out), cues=str(cues),
                   covers=[f"instagram={cov}"], post=POST, preset="ultrafast")
    e = {f"{x['platform']}:{x['orientation']}": x for x in man["exports"]}
    assert set(e) == {"x:horizontal", "instagram:reels", "instagram:feed"}      # 16:9 master -> x:horizontal
    assert e["x:horizontal"]["reframe"]["mode_used"] == "scale"                 # same aspect: no letterbox
    for k, wh in (("x:horizontal", (1920, 1080)), ("instagram:reels", (1080, 1920)), ("instagram:feed", (1080, 1350))):
        info = media.probe(str(out / e[k]["file"]))
        assert (info["w"], info["h"]) == wh, k
        assert e[k]["post_lang"] == "en"                                          # English cues -> English copy
    xtxt = (out / e["x:horizontal"]["post"]).read_text(encoding="utf-8")
    assert P.x_weighted_len(xtxt) <= 280 and e["x:horizontal"]["post_len"] <= 280
    igtxt = (out / e["instagram:reels"]["post"]).read_text(encoding="utf-8")
    assert len(P.hashtags_in(igtxt)) <= 5
    # captions burned inside the caption box (white pixels there while the cue is on)
    prof = P.profile("instagram")
    x0, y0, x1, y1 = P.caption_box(prof)
    fr = tmp_path / "f.png"
    media.grab_frame(str(out / e["instagram:reels"]["file"]), 1.0, str(fr))
    a = np.asarray(Image.open(fr).convert("RGB")).astype(int)[y0:y1, x0:x1]
    assert int(((a > 235).all(axis=-1)).sum()) > 300
    # covers: exact sizes, per-crop previews + crop sheet, a warning for the top headline
    assert Image.open(out / e["instagram:reels"]["cover"]).size == (1080, 1920)
    for a_ in ("4x5", "3x4", "1x1"):
        assert (out / f"instagram-reels.cover.crop-{a_}.jpg").exists()
    assert (out / "instagram-reels.cover.crops.jpg").exists()
    assert any("crop cuts off" in w for w in e["instagram:reels"]["warnings"])
    assert any("4:5" in n and "feed" in n for n in e["instagram:reels"]["notes"])
    chk = X.cover_crop_check(str(out / "instagram-feed.cover.jpg"), P.profile("instagram:feed"))
    assert [c["aspect"] for c in chk["crops"]] == ["3:4", "1:1"]


@needs_ffmpeg
def test_export_x_without_cues_warns_and_vertical_master(tmp_path):
    v = tmp_path / "v.mp4"
    media.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=540x960:r=30:d=1.5",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(v)])
    man = X.export(str(v), "x", str(tmp_path / "o"), preset="ultrafast")
    e = man["exports"][0]
    assert (e["platform"], e["orientation"], e["w"], e["h"]) == ("x", "vertical", 1080, 1920)
    assert e["reframe"]["mode_used"] == "scale"
    assert any("autoplays video muted" in w for w in e["warnings"])


# ----------------------------------------------------------------------------------- API uploaders (fake HTTP)
class _Resp:
    def __init__(self, data, headers=None):
        self._d, self.headers, self.text = data, headers or {}, json.dumps(data)

    def json(self):
        return self._d

    def raise_for_status(self):
        pass


class FakeHTTP:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _do(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for (m, frag), fn in self.routes.items():
            if m == method and frag in url:
                return _Resp(fn(kw) if callable(fn) else fn)
        raise AssertionError(f"unexpected {method} {url}")

    def post(self, url, **kw):
        return self._do("POST", url, **kw)

    def get(self, url, **kw):
        return self._do("GET", url, **kw)


def test_x_api_publish_flow(tmp_path):
    import package as PK
    v = tmp_path / "v.mp4"
    v.write_bytes(os.urandom(10_000))
    states = iter([{"data": {"processing_info": {"state": "in_progress", "check_after_secs": 1}}},
                   {"data": {"processing_info": {"state": "succeeded"}}}])
    http = FakeHTTP({("POST", "/media/upload/initialize"): {"data": {"id": "M1"}},
                     ("POST", "/append"): {},
                     ("POST", "/finalize"): {"data": {"processing_info": {"state": "pending", "check_after_secs": 1}}},
                     ("GET", "/media/upload"): lambda kw: next(states),
                     ("POST", "/tweets"): {"data": {"id": "T9"}}})
    res = PK.x_publish(http, "tok", {"body": "hello #ai"}, str(v), chunk=4000, poll=lambda s: None)
    assert res["url"].endswith("/T9") and res["status"] == "published"
    appends = [c for c in http.calls if c[1].endswith("/append")]
    assert len(appends) == 3 and appends[0][2]["headers"]["Authorization"] == "Bearer tok"
    tweet = [c for c in http.calls if c[1].endswith("/tweets")][0][2]["json"]
    assert tweet == {"text": "hello #ai", "media": {"media_ids": ["M1"]}}


def test_instagram_api_publish_flow_and_refusals():
    import package as PK
    st = iter([{"status_code": "IN_PROGRESS"}, {"status_code": "FINISHED"}])
    http = FakeHTTP({("POST", "/U1/media_publish"): {"id": "MED"},
                     ("POST", "/U1/media"): {"id": "C1"},
                     ("GET", "/C1"): lambda kw: next(st),
                     ("GET", "/MED"): {"permalink": "https://www.instagram.com/reel/abc/"}})
    cred = {"access_token": "t", "ig_user_id": "U1"}
    post = {"body": "cap", "video_url": "https://cdn.example.com/v.mp4", "share_to_feed": True}
    res = PK.instagram_publish(http, cred, post, poll=lambda: None)
    assert res["url"] == "https://www.instagram.com/reel/abc/"
    create = [c for c in http.calls if c[1].endswith("/U1/media")][0][2]["data"]
    assert create["media_type"] == "REELS" and create["video_url"] == post["video_url"]
    with pytest.raises(PK.UploadRefused):
        PK.instagram_publish(http, cred, dict(post, video_url="file:///local.mp4"))
    with pytest.raises(PK.UploadRefused):
        PK.x_api_uploader({"publish_at": "2030-01-01 20:00 UTC", "body": ""}, "v.mp4", None)


def test_api_uploaders_are_gated_by_series_and_confirm(tmp_path, monkeypatch):
    import package as PK
    import yaml
    src = ROOT / "workflows" / "ai-video" / "examples" / "demo-series" / "series.yaml"
    cfg = yaml.safe_load(src.read_text(encoding="utf-8"))
    cfg["platforms"] = {"x": {"lang": "en", "variant": "en", "cover": "16x9", "uploader": "x-api"},
                        "instagram": {"lang": "en", "variant": "en", "cover": "9x16", "uploader": "instagram-api",
                                      "public_video_url": "https://cdn.example.com/{slug}/ig.mp4"}}
    (tmp_path / "series.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    s = PK.load(str(tmp_path / "series.yaml"))
    px = PK.build_post(s, 1, "x")
    assert px["title"] == "" and "pay-per-use" in px["api"] and len([t for t in px["tags"]]) <= 2
    pi = PK.build_post(s, 1, "instagram")
    assert pi["video_url"].startswith("https://cdn.example.com/") and "App Review" in pi["api"]
    assert len(pi["tags"]) <= 5
    # the confirm code covers the public URL: changing it needs a new plan
    pd = tmp_path / "pkg"
    pd.mkdir()
    (pd / "video.mp4").write_bytes(b"x" * 100)
    c1 = PK.confirm_code(pi, str(pd / "video.mp4"), None)
    assert PK.confirm_code(dict(pi, video_url="https://other.example.com/v.mp4"), str(pd / "video.mp4"), None) != c1
    # secrets never inside the repo
    monkeypatch.setenv("VSTUDIO_SECRETS", str(ROOT / "secrets"))
    with pytest.raises(PK.UploadRefused):
        PK.secrets_dir()
