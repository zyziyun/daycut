"""Fast tests for the shared core modules on SYNTHETIC media (ffmpeg lavfi). No network, no ASR/TTS calls."""
import os
import pathlib
import sys
import wave

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import asr, audio, cut, media, subs, tts  # noqa: E402

pytestmark = pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")


def ff(*args):
    media.run(["ffmpeg", "-y", *map(str, args)])


@pytest.fixture(scope="session")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("core")


@pytest.fixture(scope="session")
def av(tmp):
    """6 s 320x240 30 fps testsrc + 440 Hz tone (mono 44.1k, quiet) - deliberately not 48k stereo."""
    p = tmp / "av.mp4"
    ff("-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=6",
       "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100:duration=6",
       "-af", "volume=0.05", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
       "-c:a", "aac", "-ac", "1", "-shortest", p)
    return str(p)


@pytest.fixture(scope="session")
def gappy_wav(tmp):
    """16 kHz mono: tone 0-2 s, digital silence 2-3.5 s, tone 3.5-5 s."""
    sr = 16000
    t = np.arange(int(5 * sr)) / sr
    x = 0.3 * np.sin(2 * np.pi * 220 * t)
    x[(t >= 2.0) & (t < 3.5)] = 0
    p = tmp / "gappy.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return str(p)


# ------------------------------------------------------------------ media
def test_probe_and_helpers(av):
    info = media.probe(av)
    assert (info["w"], info["h"]) == (320, 240)
    assert abs(info["fps"] - 30) < 0.01 and info["has_audio"] and not info["hdr"]
    assert abs(media.duration(av) - 6) < 0.1
    assert media.hdr_to_sdr_args(transfer="bt709") == ""
    assert media.hdr_to_sdr_args(transfer="arib-std-b67", warn=False)
    assert media.atempo_chain(3.0) == "atempo=2,atempo=1.5"
    assert media.atempo_chain(0.3).count("atempo=") == 2
    assert media.has_filter("loudnorm")


def test_delivery_args_bt709(tmp, av):
    out = tmp / "deliv.mp4"
    media.run(["ffmpeg", "-y", "-t", "1", "-i", av, *media.delivery_args(crf=30, preset="veryfast"), out])
    info = media.probe(str(out))
    r = media.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=color_space,color_primaries,color_transfer,profile", "-of", "csv=p=0", out], capture=True)
    assert r.stdout_text.count("bt709") == 3 and "High" in r.stdout_text
    assert info["sample_rate"] == 48000 and info["channels"] == 2
    # retag a plain (untagged) encode without re-encoding
    plain = tmp / "plain.mp4"
    ff("-t", "1", "-i", av, "-c:v", "libx264", "-preset", "ultrafast", "-an", plain)
    re_ = tmp / "retag.mp4"
    media.retag_bt709(str(plain), str(re_))
    r = media.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=color_primaries,color_transfer", "-of", "csv=p=0", re_], capture=True)
    assert r.stdout_text.count("bt709") == 2


def test_grab_frame_and_sheet(tmp, av):
    png = tmp / "f.png"
    media.grab_frame(av, 2.5, str(png))
    assert png.exists()
    out, ts = media.contact_sheet(av, str(tmp / "sheet.jpg"), every=2, cols=3, thumb_w=80)
    assert os.path.exists(out) and len(ts) == 3


# ------------------------------------------------------------------ audio
def test_loudnorm_2pass_hits_target_48k_stereo(tmp, av):
    out = tmp / "loud.wav"
    audio.loudnorm_2pass(av, str(out), lufs=-14)
    info = media.probe(str(out))
    assert info["sample_rate"] == 48000 and info["channels"] == 2
    m = audio.measure_loudness(str(out), -14)
    assert abs(m["input_i"] + 14) <= 0.5, m


def test_audio_utils(tmp, gappy_wav):
    sil = audio.silence_spans(gappy_wav, noise_db=-40, min_dur=0.5)
    assert len(sil) == 1 and abs(sil[0][0] - 2.0) < 0.05 and abs(sil[0][1] - 3.5) < 0.05
    snd = audio.sounded_spans(sil, 5.0, pad=0)
    assert len(snd) == 2 and abs(snd[1][0] - 3.5) < 0.05 and snd[1][1] == 5.0
    x, sr = audio.read_wav(gappy_wav)
    env, hop = audio.rms_envelope(x, sr)
    runs = audio.voiced_runs(env, hop, threshold_db=-40, max_gap=0.2)
    assert len(runs) == 2 and abs(runs[1][0] - 3.5) < 0.05
    f = audio.pitch_shift_filter(-3)
    assert "asetrate=" in f and "atempo=" in f
    bank = audio.sfx_bank()
    assert {"whoosh", "pop", "ding", "stamp"} <= set(bank)
    y = np.zeros((48000, 2), np.float32)
    audio.place_sfx(y, [(0.1, "pop"), (0.5, "ding")])
    assert np.abs(y).max() > 0


def test_mix_bed_ducks(tmp, gappy_wav):
    music = tmp / "music.wav"
    ff("-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=3", "-ac", "2", music)
    out = tmp / "mix.wav"
    audio.mix_bed(gappy_wav, str(music), str(out), duck_db=-12, fade_in=0, fade_out=0)
    x, sr = audio.read_wav(str(out), mono=True)
    assert sr == 48000 and abs(len(x) / sr - 5.0) < 0.05
    # in the gap (2.2-3.3 s) only the un-ducked bed plays; compare to a ducked region
    gap = np.sqrt(np.mean(x[int(2.4 * sr):int(3.2 * sr)] ** 2))
    assert gap > 0


# ------------------------------------------------------------------ cut
def test_timemap_round_trip():
    tm = cut.TimeMap()
    tm.add_segment(1.0, 3.0, 1.0)
    tm.add_hold(1.5, label="card")
    tm.add_segment(5.0, 8.0, 1.25, xfade=0.3)
    for t in (1.0, 1.7, 2.9, 5.6, 6.0, 7.9):
        f = tm.to_final(t)
        assert f is not None
        assert abs(tm.to_source(f) - t) < 1e-6, t
    assert tm.to_final(4.0) is None
    assert abs(tm.to_final(4.0, "fwd") - tm.to_final(5.0)) < 1e-9
    assert abs(tm.to_final(4.0, "back") - 2.0) < 1e-9
    assert tm.to_source(2.5) is None                     # inside the card
    assert abs(tm.duration - (2.0 + 1.5 + 2.4 - 0.3)) < 1e-9
    tm2 = cut.TimeMap.from_list(tm.to_list())
    assert abs(tm2.to_final(6.0) - tm.to_final(6.0)) < 1e-12


def test_tighten_squeezes_gap():
    words = [dict(w="我们", t=0.02, te=0.5), dict(w="今天", t=0.55, te=1.0),
             dict(w="聊聊", t=3.0, te=3.5), dict(w="嗯", t=3.6, te=3.8), dict(w="剪辑", t=3.85, te=4.3)]
    segs = cut.tighten(words, keep=[(0.0, 5.0)], drop=[(3.6, 3.82)], pause_threshold=0.35, squeeze=0.06)
    assert segs[0][0] >= 0.0                            # negative start clamped
    assert len(segs) == 3
    kept = sum(b - a for a, b in segs)
    assert kept < 4.3 - 0.02 - 1.5                       # the 2 s pause is gone
    gap_kept = (segs[0][1] - 1.0) + (3.0 - segs[1][0])
    assert 0.0 < gap_kept <= 0.2
    assert not any(a < 3.7 < b for a, b in segs)        # the dropped filler is out


def test_find_disfluencies_on_tone_with_gaps(gappy_wav):
    a = cut.Audio(gappy_wav)
    segs = [dict(start=0.1, end=1.9, text="以后以后我们", words=[
                dict(word="以后", start=0.1, end=0.5), dict(word="以后", start=0.55, end=0.95),
                dict(word="我们", start=1.0, end=1.9)]),
            dict(start=3.6, end=4.9, text="继续", words=[dict(word="继续", start=3.6, end=4.9)])]
    cuts = cut.find_cuts(a, segs, 0.0, 5.0)
    kinds = [c[2] for c in cuts]
    assert any(k.startswith("pause") for k in kinds)
    assert any("repeat:以后" in k for k in kinds)
    pause = next(c for c in cuts if "pause" in c[2])
    assert abs(pause[0] - 2.18) < 0.06 and abs(pause[1] - 3.32) < 0.06
    keep = cut.split_window(0.0, 5.0, cuts)
    assert keep and all(b > a for a, b in keep)


def test_suggest_fillers():
    words = [dict(w="嗯", t=0.0, te=0.2), dict(w="这个", t=0.3, te=0.6), dict(w="这个", t=0.65, te=0.9),
             dict(w="um", t=1.0, te=1.2)]
    kinds = [s["kind"] for s in cut.suggest_fillers(words)]
    assert kinds.count("filler") == 2 and "repeat" in kinds


def test_cut_segments_frame_exact(tmp, av):
    out = tmp / "cut.mp4"
    tm = cut.cut_segments(av, [(0.5, 1.5), (3.0, 4.2)], str(out), crf=30, preset="ultrafast")
    info = media.probe(str(out))
    assert abs(info["duration"] - 2.2) < 0.06
    assert info["sample_rate"] == 48000 and info["channels"] == 2
    assert abs(tm.duration - 2.2) < 1e-6 and abs(tm.to_final(3.0) - 1.0) < 1e-6


def test_xfade_assemble(tmp, av):
    asm = cut.xfade_assemble([(0.0, 1.5), (2.0, 3.5), (4.0, 5.5)], xfade=0.3, speeds=[1.25, 1.0, 1.0],
                             size="320:240", src_durations=[6.0])
    assert asm.pieces[0]["start"] - asm.pieces[0]["head"] >= 0           # head pad clamped at 0
    assert asm.pieces[1]["head"] > 0 and asm.pieces[0]["tail"] > 0      # muted pads both sides
    out = tmp / "asm.mp4"
    cut.render_assembly(asm, [av], str(out), args=media.delivery_args(crf=30, preset="ultrafast"))
    assert abs(media.duration(str(out)) - asm.total) < 0.07
    assert abs(asm.offsets[1] - (asm.durations[0] - asm.xfades[1])) < 1e-9


# ------------------------------------------------------------------ subs
def test_srt_never_prints_1000(tmp):
    cues = [subs.Cue(0.9996, 59.9996, "一"), subs.Cue(59.9996, 61.0004, "二"), subs.Cue(-0.2, 0.0004, "零")]
    p = tmp / "t.srt"
    n = subs.srt_write(cues, str(p))
    txt = p.read_text(encoding="utf-8")
    assert n == 3 and ",1000" not in txt
    assert "00:00:01,000 --> 00:01:00,000" in txt
    assert subs.srt_ts(3599.9999) == "01:00:00,000"
    assert subs.ass_ts(59.999) == "0:01:00.00"
    back = subs.srt_read(str(p))
    assert len(back) == 3 and back[2].text == "二"


def test_wrap_cjk_keeps_latin_words():
    text = "我们今天用Claude Code和HyperFrames做一个视频教程给大家看看吧"
    lines = subs.wrap_cjk(text, 10)
    assert len(lines) >= 2
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")
    joined = " | ".join(lines)
    assert "HyperFrames" in joined and ("Claude Code" in joined or ("Claude" in joined and "Code" in joined))
    for w in ("Claude", "Code", "HyperFrames"):
        assert any(w in ln for ln in lines)
    assert all(subs.text_width(subs.strip_markup(ln)) <= 10 for ln in lines)
    assert all(len(ln) > 1 for ln in lines)                     # no orphan last char
    hl = subs.wrap_cjk("这是一个【非常重要的概念】需要大家记住它好吗", 8)
    assert all(ln.count("【") == ln.count("】") for ln in hl)
    assert subs.parse_highlight("a**b**c") == [("a", False), ("b", True), ("c", False)]


def test_retime_bilingual_ass(tmp):
    tm = cut.TimeMap.from_segments([(0.0, 2.0), (5.0, 9.0)])
    cues = [subs.Cue(0.5, 1.5, "第一句"), subs.Cue(2.5, 4.5, "被剪掉"), subs.Cue(5.5, 7.0, "第三【句】")]
    rt = subs.retime(cues, tm)
    assert [c.text for c in rt] == ["第一句", "第三【句】"] and abs(rt[1].start - 2.5) < 1e-9
    en = [subs.Cue(0.4, 1.6, "first"), subs.Cue(2.4, 4.1, "third")]
    bi = subs.pair_bilingual(rt, en)
    assert bi[0].alt == "first" and bi[1].alt == "third"
    p = tmp / "t.ass"
    assert subs.ass_write(bi, str(p), w=1080, h=1920, font_name="Noto Sans SC") == 2
    assert "\\c&H" in p.read_text(encoding="utf-8")
    cs = subs.cues_from_words([dict(w="hello", t=0, te=0.4), dict(w="world", t=0.45, te=0.9),
                               dict(w="再见", t=2.0, te=2.5)], max_chars=18, fixes=False)
    assert [c.text for c in cs] == ["hello world", "再见"]


# ------------------------------------------------------------------ asr / tts (offline parts only)
def test_term_fixes_and_alignment():
    assert asr.apply_term_fixes("我用chat gpt和github", extra={"用": "使用"}) == "我使用ChatGPT和GitHub"
    assert asr.apply_term_fixes("x", extra=[[r"x", "y"]]) == "y"
    words = [dict(w="hello", t=0.0, te=0.4), dict(w="there", t=0.5, te=0.9), dict(w="friend", t=1.0, te=1.5)]
    al = asr.align_script(["Hello there,", "friend!"], words, 2.0)
    assert al[0] == {"start": 0.0, "end": 0.9} and al[1]["start"] == 1.0
    tr = {"segments": [{"words": [{"word": " a", "start": 0, "end": 0.2}]}]}
    assert asr.words_of(tr) == [{"w": "a", "t": 0.0, "te": 0.2}]


def test_tts_cache_key_offline():
    k1 = tts.cache_key("hi", "openai", "cedar", 1.0, None, "gpt-4o-mini-tts")
    assert k1 == tts.cache_key("hi", "openai", "cedar", 1.0, "", "gpt-4o-mini-tts")
    assert k1 != tts.cache_key("hi", "openai", "marin", 1.0, None, "gpt-4o-mini-tts")


def test_voiced_gaps_and_tighten_guard():
    """A word gap that still holds speech (ASR skipped a phrase) is reported and never squeezed."""
    sr = 16000
    t = np.arange(int(4 * sr)) / sr
    x = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    x[int(2.6 * sr):int(3.0 * sr)] = 0                       # one real pause
    words = [("a", 0.1, 0.5), ("b", 0.5, 0.9), ("c", 1.9, 2.3), ("d", 2.3, 2.6), ("e", 3.0, 3.4)]
    gaps = cut.voiced_gaps(words, (x, sr))
    assert [g[:2] for g in gaps] == [(0.9, 1.9)]               # 0.9-1.9 is speech with no words
    segs = cut.tighten(words, [(0.0, 4.0)], guard=(x, sr), pause_threshold=0.35)
    assert any(s <= 1.0 and e >= 1.8 for s, e in segs)        # kept whole
    assert not any(s < 2.75 < e for s, e in segs)             # the silent pause is still squeezed


def test_syllables_and_loop_score():
    assert cut.syllables("ization") == 3 and cut.syllables("我觉得") == 3 and cut.syllables("3") == 1
    assert asr.loop_score([{"text": "除了这个" + "区区" * 10}]) >= 20
    assert asr.loop_score([{"text": "我觉得效果真的很不错"}]) == 0


def test_contact_sheet_labels_are_exact(tmp, av):
    _, ts = media.contact_sheet(str(av), str(tmp / "cs_exact.jpg"), every=2.0, start=0)
    assert ts[:3] == [0, 2.0, 4.0]
