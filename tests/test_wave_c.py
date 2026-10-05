"""Wave C lib requests (collected from workflows/*/PORT_NOTES.md "## Wave B"): off-beat-proof beat
tracking, Beats.shift, true-peak limiter in loudnorm_2pass, mix_bed stems / duck_curve, subtitle join +
caption fitting + word-aware wrap, reframe from frames / region / HDR, hf_progress top + label
collisions, split_screen scale, parameterised find_cuts, redact_rects. Synthetic media only.

    python3 -m pytest tests/test_wave_c.py -q
"""
import pathlib
import shutil
import sys
import warnings
import wave

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import audio, beats, cut, draw, hf, media, overlays, reframe, subs  # noqa: E402
from vstudio import platform as P  # noqa: E402

HAS_FF = bool(shutil.which("ffmpeg"))
need_ff = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")
SR = 22050


# ------------------------------------------------------------------ beats: off-beat hats
def kick_track(bpm, dur=50.0, hats_from=24.0, hat_gain=2.0, t0=0.5, seed=0):
    """Kick on every beat (bar start louder); loud off-beat hats join at ``hats_from`` (photo-story repro)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(dur * SR) + SR)
    T = 60.0 / bpm
    times = np.arange(t0, dur, T)

    def add(s, at, g):
        i = int(round(at * SR))
        j = min(len(x), i + len(s))
        x[i:j] += g * s[:j - i]

    tk = np.arange(int(0.25 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(50 + 120 * np.exp(-tk * 30)) / SR) * np.exp(-tk * 12)
    th = np.arange(int(0.05 * SR)) / SR
    hat = np.diff(np.concatenate([[0], rng.standard_normal(len(th))])) * np.exp(-th * 80)
    for k, bt in enumerate(times):
        add(kick, bt, 1.0 if k % 4 == 0 else 0.7)
        if bt + T / 2 >= hats_from:
            add(hat, bt + T / 2, hat_gain)
    return x[:int(dur * SR)].astype(np.float32), times


def _backends():
    out = ["numpy"]
    try:
        import librosa  # noqa: F401
        out.append("librosa")
    except ImportError:
        pass
    return out


@pytest.mark.parametrize("backend", _backends())
@pytest.mark.parametrize("bpm", [90, 100, 120, 128])
def test_offbeat_hats_do_not_shift_the_grid(backend, bpm):
    x, tb = kick_track(bpm)
    b = beats.analyze(x, sr=SR, backend=backend)
    T = 60.0 / bpm
    assert abs(b.bpm - bpm) / bpm < 0.01
    # every detected beat sits on a kick (not half a beat off), before AND after the hats enter
    ph = ((b.beats - tb[0]) / T) % 1
    ph = np.minimum(ph, 1 - ph)
    assert np.mean(ph < 0.1) >= 0.97, (backend, bpm, np.round(b.beats[:8], 3))
    assert (b.beats >= 24.0).sum() > 10 and np.all(ph[b.beats >= 24.0] < 0.1)
    # the whole file is tracked, not just the stretch after the hats
    assert b.beats[0] < tb[0] + T + 0.02
    assert np.max([np.min(np.abs(b.beats - t)) for t in tb[1:-1]]) < 0.03


def test_offbeat_hats_throughout_with_numpy_tracker():
    x, tb = kick_track(110, dur=40.0, hats_from=0.0, hat_gain=4.0)
    b = beats.analyze(x, sr=SR, backend="numpy")
    assert abs(b.bpm - 110) < 1.1
    assert np.max([np.min(np.abs(b.beats - t)) for t in tb[1:-1]]) < 0.03


def test_beats_shift_music_to_video_time():
    x, _ = kick_track(120, dur=20.0, hats_from=99)
    b = beats.analyze(x, sr=SR, backend="numpy")
    v = b.shift(-2.0)
    assert np.allclose(v.beats, b.beats - 2.0) and np.allclose(v.raw_beats, b.raw_beats - 2.0)
    assert abs(v.beat_t(5) - (b.beat_t(5) - 2.0)) < 1e-9
    assert abs(v.snap(3.0) - (b.snap(5.0) - 2.0)) < 1e-9
    assert abs(v.duration - (b.duration - 2.0)) < 1e-9
    assert all(abs(h2["t"] - (h1["t"] - 2.0)) < 1e-9 for h1, h2 in zip(b.hits, v.hits))
    assert len(v.rms) == len(b.rms) - int(round(2.0 / b.rms_hop))
    assert b.beats[0] == pytest.approx(v.beats[0] + 2.0)          # original untouched
    w = b.shift(1.5)
    assert len(w.rms) == len(b.rms) + int(round(1.5 / b.rms_hop)) and abs(w.offset - b.offset - 1.5) < 1e-9


# ------------------------------------------------------------------ audio: limiter
def peaky_mix(seconds=12.0, seed=1):
    """A -20 LUFS-ish bed with sharp transients up to 0 dBFS every second (impacts / claps)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * 48000)
    t = np.arange(n) / 48000
    bed = 0.08 * np.sin(2 * np.pi * 220 * t) + 0.03 * rng.standard_normal(n)
    x = np.stack([bed, 0.9 * bed], 1)
    for k in range(1, int(seconds)):
        i, L = int(k * 48000), int(0.012 * 48000)
        x[i:i + L] += 0.95 * np.sign(rng.standard_normal((L, 1))) * np.exp(-np.arange(L) / 120)[:, None]
    return np.clip(x, -1, 1).astype(np.float32)


def test_true_peak_and_limiter_numpy():
    x = peaky_mix(6.0) * 3.0                                   # +9.5 dB: peaks far over 0 dBFS
    assert 20 * np.log10(audio.true_peak(x).max()) > 5
    y = audio.limit(x, ceiling_dbtp=-1.5, lookahead_ms=5, release_ms=50)
    assert y.shape == x.shape
    assert 20 * np.log10(audio.true_peak(y).max()) <= -1.5 + 0.02
    quiet = np.abs(x).max(1) < 0.3                             # the bed between hits stays nearly untouched
    mid = np.zeros(len(x), bool)
    for k in range(1, 6):                                     # far from any transient (release done)
        mid[int((k + 0.4) * 48000):int((k + 0.9) * 48000)] = True
    assert np.allclose(y[mid & quiet], x[mid & quiet], atol=1e-3)
    z = audio.limit(x * 0.01)                                  # below the ceiling: untouched
    assert np.array_equal(z, (x * 0.01).astype(np.float32))
    assert abs(audio.integrated_lufs(np.tile(np.sin(2 * np.pi * 1000 * np.arange(48000 * 3) / 48000)[:, None] * 0.1, (1, 2)))
               - (20 * np.log10(0.1) - 3.01 + 3.01)) < 0.3   # 1 kHz sine @ -20 dBFS, 2 ch -> ~-20 LUFS


@need_ff
@pytest.mark.parametrize("ext", ["wav", "m4a"])
def test_loudnorm_2pass_limits_true_peak(tmp_path, ext):
    src = str(tmp_path / "peaky.wav")
    audio.write_wav(src, peaky_mix())
    dst = str(tmp_path / f"out.{ext}")
    m = audio.loudnorm_2pass(src, dst, lufs=-14, tp=-1.5)
    o = audio.measure_loudness(dst)
    assert abs(o["input_i"] - (-14)) <= 0.5, o
    assert o["input_tp"] <= -1.5 + 0.1, o
    assert "output_tp" in m and "limit_ceiling" in m
    # the old path is still there (and is the one that overshoots / goes dynamic)
    old = str(tmp_path / f"old.{ext}")
    m2 = audio.loudnorm_2pass(src, old, lufs=-14, tp=-1.5, limit=False)
    assert "output_tp" not in m2


@need_ff
def test_limit_path_and_mix_bed_stems(tmp_path):
    src = str(tmp_path / "p.wav")
    audio.write_wav(src, peaky_mix(4.0) * 0.9)
    out = audio.limit(src, ceiling_dbtp=-6.0, out=str(tmp_path / "lim.wav"))
    assert audio.measure_loudness(out)["input_tp"] <= -6.0 + 0.15
    # voice: tone 0-1.5 s, silence, tone 3-4.5 s; music: noise bed
    t = np.arange(int(5 * 48000)) / 48000
    v = 0.3 * np.sin(2 * np.pi * 200 * t)
    v[(t > 1.5) & (t < 3.0)] = 0
    audio.write_wav(str(tmp_path / "v.wav"), np.stack([v, v], 1))
    audio.write_wav(str(tmp_path / "m.wav"), np.stack([0.1 * np.sin(2 * np.pi * 330 * t)] * 2, 1))
    res = audio.mix_bed(str(tmp_path / "v.wav"), str(tmp_path / "m.wav"), str(tmp_path / "mix.wav"),
                        duck_db=-12, fade_in=0, fade_out=0, return_stems=True)
    out, st = res
    assert out.endswith("mix.wav") and st["sr"] == 48000
    n = len(st["gain"])
    assert st["music"].shape == (n, 2) and st["voice"].shape == (n, 2)
    d_speech = 20 * np.log10(st["duck"][int(0.8 * 48000)])
    d_gap = 20 * np.log10(st["duck"][int(2.6 * 48000)])
    assert d_speech < -10 and d_gap > -1.0
    # plain call still returns the path only
    assert audio.mix_bed(str(tmp_path / "v.wav"), str(tmp_path / "m.wav"), str(tmp_path / "mix2.wav")) \
        == str(tmp_path / "mix2.wav")
    # duck_curve with an absolute threshold on a stem that is digital silence between events
    g = audio.duck_curve(np.stack([v, v], 1), -10, threshold_db=-42)
    assert 20 * np.log10(g[int(0.8 * 48000)]) < -9 and g[int(2.6 * 48000)] > 0.9
    assert np.all(audio.duck_curve(np.zeros((100, 2)), -10) == 1)


# ------------------------------------------------------------------ subs
def test_cues_from_words_keeps_space_after_latin_punctuation():
    ws = [dict(w="Hi", t=0, te=0.2), dict(w="everyone,", t=0.25, te=0.6), dict(w="welcome.", t=0.65, te=1.0),
          dict(w="It's", t=1.05, te=1.2), dict(w="3.5", t=1.25, te=1.4), dict(w="times", t=1.45, te=1.7)]
    c = subs.cues_from_words(ws, max_chars=60, fixes=False)
    assert c[0].text == "Hi everyone, welcome. It's 3.5 times"
    zh = [dict(w="大家好，", t=0, te=0.4), dict(w="欢迎", t=0.45, te=0.8), dict(w="来到", t=0.85, te=1.0)]
    assert subs.cues_from_words(zh, max_chars=60, fixes=False)[0].text == "大家好，欢迎来到"
    num = [dict(w="1,", t=0, te=0.1), dict(w="000", t=0.12, te=0.3)]
    assert subs.cues_from_words(num, fixes=False)[0].text == "1,000"


def test_word_aware_break_preferences():
    toks = subs._tokens("我们去了公园然后吃了很多好吃的东西")
    bonus = subs._break_bonus(toks)
    after_le = [j for j in range(1, len(toks)) if toks[j - 1][0] == "了"]
    assert all(bonus[j] < 0 for j in after_le)
    assert subs._break_bonus(toks, word_aware=False) == [0.0] * (len(toks) + 1)
    lines = subs.balanced_wrap("我们去了公园然后吃了很多好吃的东西", 10)
    assert "".join(lines) == "我们去了公园然后吃了很多好吃的东西" and len(lines) == 2


def test_word_aware_wrap_with_jieba():
    pytest.importorskip("jieba")
    lines = subs.balanced_wrap("我们重新设计了整套前端组件库的接口", 9)
    assert not any(ln.endswith("组") for ln in lines), lines


def test_fit_caption_respects_height_and_width():
    box = (60, 1080, 1020, 1270)                             # 960 x 190 band (xiaohongshu 3:4)
    r = subs.fit_caption("这是一条比较长的字幕，需要换行才能放得下，看看效果如何呢", "cjk-bold", box, max_lines=2,
                         sizes=(28, 96))
    assert r["fits"] and len(r["lines"]) <= 2
    assert r["height"] <= 190 and r["width"] <= 960
    f = draw.load_font("cjk-bold", r["size"])
    assert r["height"] == subs.caption_block_height(len(r["lines"]), f, max(2, int(r["size"] * 0.08)))
    bigger = subs.fit_caption("短句", "cjk-bold", (960, 400), sizes=(28, 96))
    assert bigger["size"] >= r["size"] and len(bigger["lines"]) == 1
    capped = subs.fit_caption("这是一条比较长的字幕需要换行才能放得下看看效果如何", "cjk-bold", box, sizes=(28, 96),
                              max_chars=8)
    assert all(subs.text_width(ln) <= 8 for ln in capped["lines"]) or not capped["fits"]


def test_fit_text_size_respects_band_height():
    p = P.profile("xiaohongshu", "vertical")
    x0, y0, x1, y1 = P.caption_box(p)
    r = P.fit_text_size(p, "这是一条比较长的字幕，需要换行才能放得下，看看效果如何呢朋友们")
    if r["fits"]:
        assert r["height"] <= y1 - y0
    long_line = "一二三四五六七八九十一二三四五六七八九十一二三四五六七"   # 27 CJK chars
    r2 = P.fit_text_size(p, long_line)
    assert all(subs.text_width(ln) <= p.caption["max_chars_zh"] for ln in r2["lines"]) or not r2["fits"]
    assert len(r2["lines"]) >= 2


# ------------------------------------------------------------------ reframe
@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    if not HAS_FF:
        pytest.skip("ffmpeg not installed")
    p = tmp_path_factory.mktemp("wc") / "src.mp4"
    media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=2",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(p)])
    return str(p)


def _frames(path):
    import cv2
    cap = cv2.VideoCapture(path)
    out = []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        out.append(fr)
    cap.release()
    return out


def test_reframe_plan_from_frames_and_region(clip, tmp_path):
    pytest.importorskip("cv2")
    det = lambda fr: [(fr.shape[1] * 0.6, fr.shape[0] * 0.3, fr.shape[1] * 0.75, fr.shape[0] * 0.6)]  # noqa: E731
    a = reframe.plan(clip, 360, 640, mode="face", detector=det)
    frames = _frames(clip)
    b = reframe.plan(clip, 360, 640, mode="face", detector=det, frames=frames)
    c = reframe.plan(None, 360, 640, mode="face", detector=det, frames=iter(frames), fps=30)
    assert a["n_frames"] == b["n_frames"] == c["n_frames"] == len(frames)
    assert a["rects"] == b["rects"] == c["rects"]
    assert a["scale"] == pytest.approx(360 / a["crop_w"], abs=1e-3)
    pr = reframe.plan_region(clip, (320, 0, 320, 360), 360, 640, detector=det)
    assert pr["src_w"] == 320 and pr["region"] == [320, 0, 320, 360] and pr["full_w"] == 640
    assert all(0 <= r[0] <= 320 - r[2] + 1e-6 for r in pr["rects"])
    out = reframe.render(clip, str(tmp_path / "r.mp4"), pr)
    assert media.probe(out)["w"] == 360
    out2 = reframe.render(None, str(tmp_path / "f.mp4"), c, frames=frames)
    assert media.probe(out2)["h"] == 640
    assert reframe.interp_targets({0: 0.0, 10: 10.0}, 11)[5] == pytest.approx(5.0)


# ------------------------------------------------------------------ overlays / hf
def test_hf_progress_top_and_label_collisions():
    ch = [(0, 30, "开场"), (30, 31, "很长的一个章节名字"), (31, 32, "另一个很长的章节"), (32, 60, "结尾总结")]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        s = overlays.hf_progress(ch, 0.0, 60.0, "vertical", position="top")
    assert s["notes"] and any("hf_progress" in str(x.message) for x in w)
    assert "to top" in s["css"] and "top: 110px" in s["css"] and "top: 160px" in s["css"]
    labels, rows, notes = overlays.layout_chapter_labels(ch, 0.0, 60.0, 60, 960, 24)
    assert any(rows) or any(lab.endswith("…") or lab == "" for lab in labels)
    clean = [(0, 20, "一"), (20, 40, "二"), (40, 60, "三")]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        s2 = overlays.hf_progress(clean, 0.0, 60.0, "horizontal")
    assert s2["notes"] == [] and "\"ROWS\"" not in s2["js"] and "to bottom" in s2["css"]


def test_split_screen_scale():
    base = hf.split_screen([[3.0, 9.5]], "inset(40px 520px 120px 500px round 28px)", x=-440)
    assert "scale" not in base["js"]
    s = hf.split_screen([[3.0, 9.5]], "inset(40px 520px 120px 500px round 28px)", x=-440, scale=0.8)
    assert "scale: 0.8" in s["js"] and "scale: 1" in s["js"]


# ------------------------------------------------------------------ cut
@pytest.fixture(scope="module")
def gappy(tmp_path_factory):
    sr = 16000
    t = np.arange(int(6 * sr)) / sr
    x = 0.3 * np.sin(2 * np.pi * 220 * t)
    x[(t >= 2.0) & (t < 2.7)] = 0                          # 0.70 s pause
    x[(t >= 4.0) & (t < 4.55)] = 0                         # 0.55 s pause
    p = tmp_path_factory.mktemp("wc_cut") / "g.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return cut.Audio(str(p))


def test_find_cuts_parameters(gappy):
    segs = [dict(start=0.1, end=1.9, text="以后以后我们", words=[
                dict(word="以后", start=0.1, end=0.5), dict(word="以后", start=0.55, end=0.95),
                dict(word="我们", start=1.0, end=1.9)]),
            dict(start=2.8, end=3.9, text="继续", words=[dict(word="继续", start=2.8, end=3.9)]),
            dict(start=4.6, end=5.8, text="好的", words=[dict(word="好的", start=4.6, end=5.8)])]
    d = cut.find_cuts(gappy, segs, 0.0, 6.0)
    same = cut.find_cuts(gappy, segs, 0.0, 6.0, pause_min=cut.PAUSE_MIN, pause_keep=2 * cut.PAUSE_EDGE,
                         snap="word", min_cut=cut.MIN_CUT)
    assert d == same
    assert sum("pause" in c[2] for c in d) == 1               # 0.70 s yes, 0.55 s no
    classic = cut.find_cuts(gappy, segs, 0.0, 6.0, pause_min=0.75, pause_keep=0.30, snap="back")
    assert not any("pause" in c[2] for c in classic) and any("repeat" in c[2] for c in classic)
    loose = cut.find_cuts(gappy, segs, 0.0, 6.0, pause_min=0.5, pause_keep=0.2)
    assert sum("pause" in c[2] for c in loose) == 2
    ed = cut.find_cuts(gappy, segs, 0.0, 6.0, extra=[(5.0, 5.4, "x")], pause_min=0.75, editor_pause_min=0.5,
                       editor_pause_keep=0.25, snap="back")
    assert sum("pause" in c[2] for c in ed) == 2
    with pytest.raises(ValueError):
        cut.find_cuts(gappy, segs, 0.0, 6.0, snap="nope")


# ------------------------------------------------------------------ redaction
def test_redact_rects_frame_modes():
    rng = np.random.default_rng(0)
    fr = rng.integers(0, 255, (120, 200, 3), dtype=np.uint8)
    orig = fr.copy()
    out = draw.redact_rects(fr, [(20, 30, 64, 32)], mode="blur")
    assert out is fr
    assert np.array_equal(fr[:30], orig[:30]) and not np.array_equal(fr[30:62, 20:84], orig[30:62, 20:84])
    assert fr[30:62, 20:84].std() < orig[30:62, 20:84].std() / 3
    fr2 = orig.copy()
    draw.redact_rects(fr2, [(0, 0, 50, 20)], mode="cover", color=(10, 20, 30))
    assert np.all(fr2[:20, :50] == (10, 20, 30)) and np.array_equal(fr2[20:], orig[20:])
    fr3 = orig.copy()
    draw.redact_rects(fr3, [(-10, 100, 40, 40)], mode="pixelate")  # clipped at the frame edge
    assert np.array_equal(fr3[:100], orig[:100])
    with pytest.raises(ValueError):
        draw.redact_rects(orig.copy(), [(0, 0, 1, 1)], mode="smear")


@need_ff
def test_redact_rects_video(clip, tmp_path):
    out = draw.redact_rects(clip, [(0, 0, 200, 60)], mode="cover", color="#102030", out=str(tmp_path / "c.mp4"))
    png = str(tmp_path / "f.png")
    media.grab_frame(out, 1.0, png)
    from PIL import Image
    a = np.asarray(Image.open(png).convert("RGB")).astype(int)
    assert np.abs(a[10:50, 10:190].reshape(-1, 3).mean(0) - (0x10, 0x20, 0x30)).max() < 8
    b = draw.redact_rects(clip, [(100, 100, 128, 64), (300, 50, 64, 64)], mode="blur", out=str(tmp_path / "b.mp4"))
    assert media.probe(b)["w"] == 640
    assert media.ffprobe_value(b, "format=duration", cast=float) == pytest.approx(2.0, abs=0.1)
    assert media.ffprobe_value(b, "stream=width", stream="v:0", cast=int) == 640
