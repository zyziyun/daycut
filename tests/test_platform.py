"""Platform profiles, reframe planning/rendering and multi-platform export on SYNTHETIC media."""
import json
import os
import pathlib
import shutil
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import audio, config, media, publish  # noqa: E402
from vstudio import export as X  # noqa: E402
from vstudio import platform as P  # noqa: E402
from vstudio import reframe as R  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def ff(*args):
    media.run(["ffmpeg", "-y", *map(str, args)])


# ----------------------------------------------------------------------------------- profiles
def test_all_profiles_load_and_boxes_inside_canvas():
    keys = P.list_profiles()
    for name in ("xiaohongshu", "douyin", "tiktok", "youtube", "youtube-shorts", "bilibili"):
        assert any(k.startswith(name + ":") for k in keys)
    for k in keys:
        p = P.profile(k)
        x0, y0, x1, y1 = P.safe_box(p)
        assert 0 <= x0 < x1 <= p.w and 0 <= y0 < y1 <= p.h, k
        c0, d0, c1, d1 = P.caption_box(p)
        assert x0 <= c0 < c1 <= x1 and y0 <= d0 < d1 <= y1, k
        assert abs((c0 + c1) / 2 - p.w / 2) <= 1, k                    # centred
        for kx0, ky0, kx1, ky1 in P.keepouts(p):                        # clear of the button column
            assert not (c1 > kx0 and d1 > ky0), k
        cw, ch = P.cover_size(p)
        assert cw > 0 and ch > 0
        t0, t1, t2, t3 = P.cover_title_safe(p)
        assert 0 <= t0 < t2 <= cw and 0 <= t1 < t3 <= ch
        assert p.loudness["lufs"] < 0 and p.loudness["tp"] < 0
        assert p.length["max"] >= p.length["sweet"][1]


def test_specific_canvases_and_publish_consistency():
    v, f, h = P.profile("xiaohongshu", "vertical"), P.profile("xhs", "9:16"), P.profile("xiaohongshu:horizontal")
    assert (v.w, v.h, f.w, f.h, h.w, h.h) == (1080, 1440, 1080, 1920, 1920, 1080)
    assert P.feed_crop_box(h) == (240, 0, 1680, 1080)                  # 4:3 centre crop in the feed
    assert P.cover_title_safe(h)[0] >= 240 and P.cover_title_safe(h)[2] <= 1680
    assert P.profile("youtube").cover["w"] == 1280 and P.profile("shorts").length["max"] == 180
    assert P.profile("bilibili").cover_aspect == "16:10"
    for name, tmax in publish.TITLE_MAX_DEFAULT.items():
        assert P.profile(name).title_max == publish.title_max(name) == tmax
    assert P.title_len(v, "ab中") == config.xhs_len("ab中") == 2.0
    with pytest.raises(KeyError):
        P.profile("tiktok", "horizontal")


def test_persona_override_deep_merged(tmp_path, monkeypatch):
    y = tmp_path / "p.yaml"
    y.write_text("platforms:\n  douyin:\n    title_max: 30\n    loudness: {lufs: -12}\n"
                 "    orientations:\n      vertical: {caption: {band: [1100, 1300]}}\n"
                 "  xiaohongshu:\n    safe_zone: {top: 200, bottom: 1700, right_lower_keepout: 200}\n")
    monkeypatch.setenv("VSTUDIO_PERSONA", str(y))
    config.persona.cache_clear()
    try:
        d = P.profile("douyin")
        assert d.title_max == 30 and d.loudness == {"lufs": -12, "tp": -1.5}      # tp kept (deep merge)
        assert d.caption["band"] == [1100, 1300] and d.caption["max_lines"] == 2
        f = P.profile("xiaohongshu", "full")
        assert P.safe_box(f)[1] == 200 and P.safe_box(f)[3] == 1700 and P.keepouts(f)[0][0] == 880
        assert P.profile("xiaohongshu", "vertical").safe["top"] == 60            # legacy key only hits 1920-tall
        assert P.profile("douyin", use_persona=False).title_max == 55
    finally:
        monkeypatch.delenv("VSTUDIO_PERSONA")
        config.persona.cache_clear()


def test_fit_text_size_and_checks():
    p = P.profile("xiaohongshu", "vertical")
    short = P.fit_text_size(p, "短句")
    assert short["fits"] and short["size"] == p.caption["size"][1] and short["lines"] == ["短句"]
    long = P.fit_text_size(p, "这是一条比较长的字幕，需要换行才能放得下，看看效果")
    lo, hi = p.caption["size"]
    assert lo <= long["size"] <= hi and 1 < len(long["lines"]) <= p.caption["max_lines"]
    assert P.check_length(p, 2000) and not P.check_length(p, 60)
    assert P.check_text(p, title="一" * 21) and not P.check_text(p, title="一" * 20)


# ----------------------------------------------------------------------------------- reframe
@pytest.fixture(scope="module")
def square_video(tmp_path_factory):
    """6 s 640x360: an orange square sweeps right (0-3 s), then a hard cut to a new background with the
    square jumped far left and jittering by 2 px."""
    d = tmp_path_factory.mktemp("rf")
    p = d / "sq.mp4"
    ff("-f", "lavfi", "-i", "color=c=0x203040:s=640x360:r=30:d=3", "-f", "lavfi", "-i", "color=c=0x806020:s=640x360:r=30:d=3",
       "-f", "lavfi", "-i", "color=c=orange:s=60x60:r=30:d=6",
       "-filter_complex", "[0][2]overlay=x='120+90*t':y=150:shortest=1[a];[1][2]overlay=x='60+2*mod(n,2)':y=200:shortest=1[b];"
                          "[a][b]concat=n=2:v=1:a=0[v]",
       "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", p)
    return str(p)


def square_detector(bgr):
    m = (bgr[..., 2] > 200) & (bgr[..., 1] > 100) & (bgr[..., 0] < 80)      # orange in BGR
    ys, xs = np.nonzero(m)
    if len(xs) < 50:
        return []
    return [(float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()))]


@needs_ffmpeg
def test_reframe_plan_tracks_smoothly_and_resets_on_cut(square_video):
    pl = R.plan(square_video, 270, 360, mode="face", detector=square_detector, every=3)
    assert pl["mode_used"] == "face" and pl["hit_rate"] == 1.0
    assert any(85 <= c <= 95 for c in pl["cuts"]), pl["cuts"]
    r = np.array(pl["rects"])
    assert len(r) == pl["n_frames"] >= 170
    cw = r[0, 2]
    assert np.all(r[:, 0] >= 0) and np.all(r[:, 0] + cw <= 640 + 1e-6) and np.all(r[:, 1] == 0)
    cut = [c for c in pl["cuts"] if 85 <= c <= 95][0]
    v = np.abs(np.diff(r[:, 0])) * pl["fps"] / cw
    v_nocut = np.delete(v, cut - 1)
    assert v_nocut.max() <= R.DEFAULTS["max_speed"] + 1e-6               # speed limit
    assert pl["stats"]["max_speed"] <= R.DEFAULTS["max_speed"] + 1e-6
    acc = np.abs(np.diff(v_nocut[: cut - 2])) * pl["fps"]
    assert acc.max() <= R.DEFAULTS["max_accel"] * 1.05                  # eased (bounded accel)
    # follows the sweep: the square stays inside the crop before the cut
    for i in range(10, cut - 1, 10):
        sx = 120 + 90 * i / pl["fps"]
        assert r[i, 0] - 5 <= sx and sx + 60 <= r[i, 0] + cw + 5, i
    # hard cut = camera jumps to the new subject (left), then the 2 px jitter is inside the dead zone
    assert r[cut, 0] < r[cut - 1, 0] - 100
    assert np.ptp(r[cut + 5:, 0]) < 1.0


@needs_ffmpeg
def test_reframe_no_face_falls_back_and_renders(square_video, tmp_path):
    pl = R.plan(square_video, 270, 360, mode="face", detector=lambda fr: [], fallback="pad-blur")
    assert pl["mode_used"] == "pad-blur" and pl["hit_rate"] == 0 and "fallback_reason" in pl
    out = tmp_path / "pb.mp4"
    R.render(square_video, str(out), pl, encode_args=["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    info = media.probe(str(out))
    assert (info["w"], info["h"]) == (270, 360) and abs(info["duration"] - 6) < 0.2
    c = R.plan(square_video, 270, 360, mode="center")
    assert c["fixed"][0] == pytest.approx((640 - 270) / 2)
    pl2 = R.reframe(square_video, str(tmp_path / "c.mp4"), 270, 360, mode="center",
                    encode_args=["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"])
    assert os.path.exists(pl2["plan_json"])


# ----------------------------------------------------------------------------------- export
@pytest.fixture(scope="module")
def master(tmp_path_factory):
    d = tmp_path_factory.mktemp("ex")
    p = d / "master.mp4"
    ff("-f", "lavfi", "-i", "color=c=0x203040:s=1280x720:r=30:d=6", "-f", "lavfi", "-i", "color=c=orange:s=120x120:r=30:d=6",
       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
       "-filter_complex", "[0][1]overlay=x='200+100*t':y=300:shortest=1[v]", "-map", "[v]", "-map", "2",
       "-af", "volume=0.08", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", p)
    return str(p)


@needs_ffmpeg
def test_export_multi_platform(master, tmp_path):
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps([{"start": 0.5, "end": 2.5, "text": "这是一条测试字幕"},
                                {"start": 3.0, "end": 4.0, "text": "Second caption"}]), encoding="utf-8")
    from PIL import Image
    cov = tmp_path / "cover.png"
    Image.new("RGB", (1920, 1080), (200, 30, 60)).save(cov)
    out = tmp_path / "exports"
    man = X.export(master, "xiaohongshu:vertical,youtube", str(out), cues=str(cues), covers=[str(cov)],
                   post={"title": "测试标题", "hook": "hook", "body": "body", "tags": ["测试"]}, preset="ultrafast")
    assert os.path.exists(out / "manifest.json")
    on_disk = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert [e["file"] for e in on_disk["exports"]] == ["xiaohongshu-vertical.mp4", "youtube-horizontal.mp4"]
    for e, (W, H), cover in zip(man["exports"], [(1080, 1440), (1920, 1080)], [(1080, 1440), (1280, 720)]):
        f = str(out / e["file"])
        info = media.probe(f)
        assert (info["w"], info["h"]) == (W, H) and abs(info["duration"] - 6.0) < 0.15
        assert info["has_audio"] and info["sample_rate"] == 48000
        m = audio.measure_loudness(f)
        assert abs(m["input_i"] - e["target_loudness"]["lufs"]) <= 0.5, m
        assert Image.open(out / e["cover"]).size == cover
        assert (out / e["post"]).read_text(encoding="utf-8").startswith("测试标题")
        assert e["captions"] == 2
        prof = P.profile(e["platform"], e["orientation"])
        x0, y0, x1, y1 = P.caption_box(prof)
        on, off = tmp_path / "on.png", tmp_path / "off.png"
        media.grab_frame(f, 1.5, str(on))
        media.grab_frame(f, 5.5, str(off))

        def white(png):
            a = np.asarray(Image.open(png).convert("RGB")).astype(int)[y0:y1, x0:x1]
            return int(((a > 235).all(axis=-1)).sum())
        assert white(on) > 800 and white(off) < 50, (white(on), white(off))
    xhs, yt = man["exports"]
    assert xhs["reframe"]["mode_used"] == "pad-blur"             # synthetic: no face -> blurred fill
    assert yt["reframe"]["mode_used"] == "letterbox"             # same aspect -> plain scale
    assert any("sweet spot" in w for w in xhs["warnings"])
    assert any("re-fitted" in n for n in xhs["notes"])
