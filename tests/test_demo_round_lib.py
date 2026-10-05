"""Lib fixes from the 2026-10 demo round: MediaPipe VIDEO timestamps, ASR hallucination filter,
AAC true-peak headroom, persona tag sets, cjk-serif / .ttc faces, export same-aspect / covers /
caption keep-outs, beat-grid steadiness on jittery-but-steady tracks. Synthetic data only.

    python3 -m pytest tests/test_demo_round_lib.py -q
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import asr, audio, beats, config, publish  # noqa: E402
from vstudio import export as X  # noqa: E402
from vstudio import platform as P  # noqa: E402

HAS_FF = bool(shutil.which("ffmpeg"))
need_ff = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *map(str, args)], check=True)


# ------------------------------------------------------------------ 1. face: monotonic VIDEO timestamps
class _FakeVideoLandmarker:
    """Mimics MediaPipe VIDEO mode: raises on a non-increasing timestamp."""

    def __init__(self):
        self.ts = []

    def detect_for_video(self, img, ts):
        if self.ts and ts <= self.ts[-1]:
            raise ValueError("Input timestamp must be monotonically increasing.")
        self.ts.append(ts)

        class R:
            face_landmarks, face_blendshapes = [], []
        return R()


def test_detect_makes_video_timestamps_strictly_increasing():
    pytest.importorskip("mediapipe")
    pytest.importorskip("cv2")
    from vstudio import face as F
    lm = _FakeVideoLandmarker()
    img = np.zeros((32, 32, 3), np.uint8)
    for ts in (0, 0, 33, 33, 33, 20, 67):          # re-acquire on the same frame, then a regression
        F.detect(lm, img, ts)
    assert lm.ts == sorted(set(lm.ts)) and len(lm.ts) == 7
    assert lm.ts[-1] == 67


def test_video_tracker_failure_names_the_frame():
    from vstudio import face as F
    tr = F.VideoFaceTracker.__new__(F.VideoFaceTracker)
    tr.fps = 30.0

    def boom(bgr, idx):
        raise ValueError("mediapipe said no")
    tr._track = boom
    with pytest.raises(RuntimeError, match=r"frame 45 \(t=1\.500s\)"):
        tr(np.zeros((8, 8, 3), np.uint8), 45)


# ------------------------------------------------------------------ 2. ASR hallucinations
def _seg(text, **stats):
    p = stats.pop("p", None)
    return dict(start=0.0, end=1.0, text=text, **stats,
                words=[dict(word=c, start=0.0, end=1.0, p=p) for c in text if c.strip()])


def _tr(*segs):
    return asr._finish(dict(language="zh", backend="test", segments=list(segs)), None, False)


def test_drop_hallucinations_on_music_only_audio():
    tr = _tr(_seg("字幕志愿者 杨茜茜"), _seg("请不吝点赞 订阅 转发 打赏支持明镜与点点栏目"),
             _seg(" Thanks for watching!", no_speech_prob=0.5, avg_logprob=-0.9))
    out = asr.drop_hallucinations(tr)
    assert out["segments"] == [] and out["words"] == [] and out["text"] == ""
    assert len(out["dropped"]) == 3 and all(d["reason"] for d in out["dropped"])
    assert not asr.has_speech(tr)
    assert not asr.has_speech(tr["segments"])
    assert not asr.has_speech(None)


def test_real_speech_survives_including_a_confident_sign_off():
    tr = _tr(_seg("今天我们聊一下职业发展初期", no_speech_prob=0.01, avg_logprob=-0.2),
             _seg("谢谢观看", no_speech_prob=0.02, avg_logprob=-0.15, p=0.95))
    out = asr.drop_hallucinations(tr)
    assert len(out["segments"]) == 2 and out["dropped"] == []
    assert asr.has_speech(tr) and asr.has_speech(tr, min_words=4)
    assert not asr.has_speech(tr, min_words=100)


def test_whisper_silence_gate_and_loop():
    silent = _seg("嗯嗯好的", no_speech_prob=0.9, avg_logprob=-1.4)
    loop = _seg("区区区区区区区区区区区区", no_speech_prob=0.1, avg_logprob=-0.3)
    assert asr.drop_hallucinations([silent, loop]) == []


def test_transcribe_finish_applies_filter_by_default():
    raw = dict(language="zh", backend="test", segments=[_seg("字幕志愿者 某某"), _seg("这一段是真的在说话")])
    on = asr._finish(raw, None, False, drop_hallucinated=True)
    off = asr._finish(raw, None, False, drop_hallucinated=False)
    assert len(on["segments"]) == 1 and len(off["segments"]) == 2
    import inspect
    assert inspect.signature(asr.transcribe).parameters["drop_hallucinated"].default is True


# ------------------------------------------------------------------ 3. loudness: AAC true-peak headroom
def _hot_mix(sr=48000, dur=6.0):
    t = np.arange(int(sr * dur)) / sr
    x = 0.25 * np.sin(2 * np.pi * 220 * t) * (1 + 0.5 * np.sin(2 * np.pi * 0.7 * t))
    x[::4800] += 0.9                                   # transients that hit the limiter
    return np.stack([x, x * 0.9], 1).astype(np.float32)


@need_ff
def test_wav_master_keeps_headroom_for_the_later_aac_encode(tmp_path):
    src = str(tmp_path / "mix_raw.wav")
    audio.write_wav(src, _hot_mix())
    wav = str(tmp_path / "mix.wav")
    audio.loudnorm_2pass(src, wav, lufs=-14, tp=-1.5)
    assert audio.measure_loudness(wav)["input_tp"] <= -1.5 - audio.WAV_HEADROOM_DB + 0.1
    m4a = str(tmp_path / "mux.m4a")                       # what a compose step does afterwards
    _ff("-i", wav, "-c:a", "aac", "-b:a", "192k", m4a)
    o = audio.measure_loudness(m4a)
    assert o["input_tp"] <= -1.5 + 0.05, o
    assert abs(o["input_i"] + 14) <= 0.6, o


@need_ff
def test_ensure_loudness_fixes_an_encoded_overshoot(tmp_path):
    src = str(tmp_path / "hot.wav")
    audio.write_wav(src, np.clip(_hot_mix() * 3.0, -1, 1))
    m4a = str(tmp_path / "hot.m4a")
    _ff("-i", src, "-c:a", "aac", "-b:a", "192k", m4a)
    assert audio.measure_loudness(m4a)["input_tp"] > -1.5
    r = audio.ensure_loudness(m4a, lufs=-14, tp=-1.5)
    assert r["fixed"] and r["input_tp"] <= -1.5 + 0.05 and abs(r["input_i"] + 14) <= 0.5
    assert not audio.ensure_loudness(m4a, lufs=-14, tp=-1.5)["fixed"]


# ------------------------------------------------------------------ 4. publish: persona tag sets
@pytest.fixture
def tag_persona(monkeypatch):
    data = {"publish": {"tags": ["AIEngineer", "北美求职"], "tag_sets": {"art": ["看展", "艺术"]}}}
    monkeypatch.setattr(publish, "persona", lambda: data)
    return data


def test_post_body_tag_controls(tag_persona):
    base = publish.post_body("hook", "body", tags=["拉斐尔"], platform="xiaohongshu", warn=None)
    assert "#拉斐尔" in base and "#AIEngineer" in base        # historical default kept
    own = publish.post_body("hook", "body", tags=["拉斐尔"], platform="xiaohongshu", warn=None,
                            use_persona_tags=False)
    assert "#拉斐尔" in own and "#AIEngineer" not in own
    art = publish.post_body("hook", "body", tags=["拉斐尔"], platform="xiaohongshu", warn=None, tag_set="art")
    assert "#看展" in art and "#AIEngineer" not in art
    msgs = []
    none = publish.hashtags(["x"], "xiaohongshu", tag_set="nope", warn=msgs.append)
    assert none == "#x" and msgs and "nope" in msgs[0]


# ------------------------------------------------------------------ 5. fonts: cjk-serif role, .ttc#N faces
def test_cjk_serif_roles_registered_and_missing_font_warns(tmp_path, monkeypatch, capsys):
    assert config.FONTS["cjk-serif"] and config.FONTS["cjk-serif-bold"]
    monkeypatch.setattr(config, "FONT_DIR", str(tmp_path))
    monkeypatch.setattr(config, "persona", lambda: {"fonts": {}})
    config._WARNED.clear()
    with pytest.raises(config.MissingAsset):
        config.font("cjk-serif")
    assert "cjk-serif" in capsys.readouterr().err


def test_missing_cjk_serif_draws_with_cjk_loudly(monkeypatch, capsys):
    from vstudio import draw
    if not os.path.exists(os.path.join(config.FONT_DIR, "NotoSansSC-Regular.otf")):
        pytest.skip("run ./install.sh for the Noto Sans SC font")
    real = draw.font

    def fake(role):
        if role.startswith("cjk-serif"):
            raise config.MissingAsset(role)
        return real(role)
    monkeypatch.setattr(draw, "font", fake)
    draw.load_font.cache_clear()
    f = draw.load_font("cjk-serif", 41)
    draw.load_font.cache_clear()
    assert "NotoSansSC" in os.path.basename(f.path)          # a CJK face, not Pillow's default bitmap
    assert "'cjk-serif' missing" in capsys.readouterr().out


def test_ttc_face_index_from_persona(tmp_path, monkeypatch, capsys):
    ttl = pytest.importorskip("fontTools.ttLib")
    srcs = [os.path.join(config.FONT_DIR, n) for n in ("STIXTwoText-Regular.ttf", "STIXTwoText-Italic.ttf")]
    if not all(os.path.exists(p) for p in srcs):
        pytest.skip("run ./install.sh for the STIX fonts")
    coll = ttl.TTCollection()
    coll.fonts = [ttl.TTFont(p) for p in srcs]
    ttc = str(tmp_path / "Pair.ttc")
    coll.save(ttc)
    monkeypatch.setattr(config, "FONT_DIR", str(tmp_path / "fonts"))
    monkeypatch.setattr(config, "persona", lambda: {"fonts": {"cjk-serif": ttc + "#1", "bad": "/nope.ttf"}})
    config._WARNED.clear()
    p = config.font("cjk-serif")
    assert p.startswith(str(tmp_path / "fonts" / "extracted"))
    sub = ttl.TTFont(p)["name"].getDebugName(2)
    assert "Italic" in sub
    with pytest.raises(config.MissingAsset):
        config.font("bad")
    assert "does not exist" in capsys.readouterr().err


# ------------------------------------------------------------------ 6. export
def test_parse_covers_and_target_match():
    gen, per = X.parse_covers(["a.png", "xiaohongshu=c34.png", "douyin:vertical=c916.png"])
    assert gen == ["a.png"] and per == {"xiaohongshu": "c34.png", "douyin:vertical": "c916.png"}
    assert X._cover_for(P.profile("xiaohongshu"), per) == "c34.png"
    assert X._cover_for(P.profile("douyin"), per) == "c916.png"
    assert X._cover_for(P.profile("youtube"), per) is None


def test_cover_of_other_aspect_is_padded_not_cropped(tmp_path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (1080, 1920), (20, 20, 20))
    ImageDraw.Draw(im).rectangle((100, 150, 980, 350), fill=(255, 0, 0))    # the "headline" near the top
    src = str(tmp_path / "c916.png")
    im.save(src)
    prof = P.profile("xiaohongshu")                                         # 3:4 cover
    warns = []
    out, notes = X.make_cover(prof, [src], None, str(tmp_path / "x.jpg"), warnings=warns)
    got = np.asarray(Image.open(out).convert("RGB")).astype(int)
    red = (got[..., 0] > 180) & (got[..., 1] < 80)
    W, H = P.cover_size(prof)
    assert red.sum() > 0.6 * (880 * 200) * (H / 1920) ** 2                 # whole headline still there
    assert warns and "xiaohongshu=" in warns[0]


def test_hl_spans_and_markup_rebalance():
    c = X._cue_from_dict(dict(start=0, end=1, text="面试又不考AWS真的", hl=["AWS"], style={"highlight": "#00FF00"}))
    assert c.text == "面试又不考【AWS】真的" and c.meta["style"]["highlight"] == "#00FF00"
    c2 = X._cue_from_dict(dict(start=0, end=1, text="abcdef", hl=[[1, 3]]))
    assert c2.text == "a【bc】def"
    assert X._rebalance(["前【关键", "词】后"], "【】") == ["前【关键】", "【词】后"]


def test_map_box_through_plans():
    fit = dict(target=[1080, 1920], src_w=540, src_h=960, mode_used="letterbox")
    assert X.map_box(fit, (0, 480, 540, 100)) == (0, 960, 1080, 1160)
    crop = dict(target=[1080, 1440], src_w=1080, src_h=1920, mode_used="face", rects=None, fixed=[0, 240, 1080, 1440])
    assert X.map_box(crop, (100, 340, 200, 100)) == (100, 100, 300, 200)


@need_ff
def test_export_same_aspect_scales_and_captions_avoid_keepouts(tmp_path):
    try:
        config.font("cjk-bold")
    except config.MissingAsset:
        pytest.skip("run ./install.sh for fonts")
    master = str(tmp_path / "m.mp4")
    _ff("-f", "lavfi", "-i", "testsrc=size=540x960:rate=30:duration=2", "-f", "lavfi",
        "-i", "sine=frequency=330:sample_rate=48000:duration=2", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", master)
    prof = P.profile("douyin")
    cx0, cy0, cx1, cy1 = P.caption_box(prof)
    s = 540 / prof.w                                       # master px per target px
    box = [0, int(cy0 * s) - 10, 540, int((cy1 - cy0) * s) + 20]  # a panel right over the caption band
    cues = str(tmp_path / "cues.json")
    json.dump(dict(cues=[dict(start=0.0, end=2.0, text="面试又不考AWS", hl=["AWS"])],
                   keepouts=[dict(t0=0.0, t1=1.0, box=box, kind="panel")], size=[540, 960]),
              open(cues, "w"), ensure_ascii=False)
    out = str(tmp_path / "ex")
    os.makedirs(out)
    e = X.export_one(master, prof, out, cues=cues)
    assert e["reframe"]["mode_used"] == "scale" and e["keepouts"] == 1
    assert e["captions_moved_frames"] >= 25                 # ~1 s at 30 fps moved off the panel
    e2 = X.export_one(master, prof, out, cues=cues, captions=False)
    assert e2["captions"] == 0 and e2["reframe"]["mode_used"] == "scale"


# ------------------------------------------------------------------ 7. beats: steady but jittery
def test_steady_grid_accepts_jittery_steady_tempo_and_rejects_drift():
    rng = np.random.default_rng(3)
    period = 60 / 128
    n = int(360 / period)                                 # a 6-minute track at 128 BPM
    t = 0.4 + np.arange(n) * period + rng.normal(0, 0.022, n)   # IBI 0.469 +- ~0.03 s
    p, off, res, idx = beats._fit(t)
    assert abs(p - period) < 5e-4 and idx[-1] == n - 1     # no index slip over 768 beats
    ok, st = beats.steady_grid(res, p)
    assert ok and st["rule"] == "relative", st
    # same jitter on a tempo that drifts 3 % across the track -> not a grid
    T, tt, times = period, 0.4, []
    while tt < 120:
        times.append(tt)
        tt += T / (1 + 0.03 * tt / 120)
    times = np.array(times) + rng.normal(0, 0.01, len(times))
    p2, _, res2, _ = beats._fit(times)
    assert not beats.steady_grid(res2, p2)[0]
    # clean grid still takes the strict rule
    p3, _, res3, _ = beats._fit(0.1 + np.arange(64) * 0.5)
    assert beats.steady_grid(res3, p3) == (True, beats.steady_grid(res3, p3)[1]) and \
        beats.steady_grid(res3, p3)[1]["rule"] == "strict"


def test_analyze_jittered_kicks_reports_a_grid():
    sr = 22050
    rng = np.random.default_rng(1)
    period, dur = 60 / 128, 60.0
    x = np.zeros(int(dur * sr))
    tk = np.arange(int(0.2 * sr)) / sr
    kick = np.sin(2 * np.pi * np.cumsum(55 + 110 * np.exp(-tk * 30)) / sr) * np.exp(-tk * 12)
    k = 0
    while 0.5 + k * period < dur - 0.3:
        i = int((0.5 + k * period + rng.normal(0, 0.018)) * sr)
        x[i:i + len(kick)] += (1.0 if k % 4 == 0 else 0.6) * kick[:len(x) - i]
        k += 1
    b = beats.analyze(x.astype(np.float32), sr=sr, backend="numpy")
    assert abs(b.bpm - 128) < 1.0
    assert b.grid_ok, b.tempo_check.get("grid")
