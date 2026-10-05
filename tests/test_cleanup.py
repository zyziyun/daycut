"""vstudio.cleanup: the shared 气口 / filler / repeat cleanup tool.

Synthetic "speech" only: every word is a tone burst with its own frequency (so a fake ASR can read the
cleaned audio back), breaths are soft band-limited noise, a merged filler is a tone + dip + tone that the
transcript reports as ONE long word. Transcript timing is whisper-like (starts 40 ms early, ends 30 ms
early: the sound continues after ``te``). No network, no real ASR.

    python3 -m pytest tests/test_cleanup.py -q
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import audio, cleanup, cut  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _standard_persona(tmp_path_factory):
    """Hermetic: a creator's persona.local.yaml (e.g. cleanup.profile: tight) must not change the defaults
    these tests assert. VSTUDIO_PERSONA is merged last, also in the scripts run as subprocesses."""
    from vstudio import config as _config
    p = tmp_path_factory.mktemp("persona") / "persona.yaml"
    p.write_text("cleanup:\n  profile: standard\n", encoding="utf-8")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("VSTUDIO_PERSONA", str(p))
        _config.persona.cache_clear()                  # persona() is lru_cached
        yield
    _config.persona.cache_clear()


HAS_FF = bool(shutil.which("ffmpeg"))
need_ff = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")
FPS = 30


def W(text, dur, gap=0.06):
    return ("w", text, dur, gap)


def G(dur):
    return ("g", dur)


def B(dur):
    return ("b", dur)


def M(filler, fdur, dip, word, wdur, gap=0.06):
    return ("m", filler, fdur, dip, word, wdur, gap)


ZH = [G(0.5), W("大家", .35), W("好。", .3, 0), G(.9),
      W("嗯", .3, 0), G(.35),
      W("今天", .35), W("讲", .25), W("一下", .3), W("那个", .3), W("问题。", .4, 0), G(.8), B(.3), G(.15),
      W("像", .25), W("这个", .3), W("像", .25), W("这个", .3), W("方法", .4), W("很", .2), W("好。", .3, 0), G(.6),
      W("我", .2, .05), W("我们", .35), W("先", .25), W("看", .25), W("例子。", .4, 0), G(.6),
      W("那个", .7, 0), G(.4), W("就是", .3, 0), G(.3), W("数据", .35), W("很", .2), W("重要。", .4, 0), G(.6),
      W("我们", .3), W("明天", .3), W("去", .25, 0), G(.3), W("我们", .3), W("明天", .3), W("要", .2), W("讲", .25),
      W("模型。", .4, 0), G(.7),
      W("这个", .3), W("模型", .35), W("的", .15), W("效果", .35), W("非常", .35), W("好。", .3, 0), G(1.2),
      W("这个", .3), W("模型", .35), W("的", .15), W("效果", .35), W("真的", .35), W("非常", .35), W("好。", .3, 0), G(.6),
      M("嗯", .25, .1, "结果", .4), W("出来", .35), W("了。", .25, 0), G(.8)]

EN = [G(.4), W("So", .25, 0), G(.35), W("um", .3, 0), G(.3), W("we", .2), W("we", .2), W("need", .3), W("a", .1),
      W("plan.", .35, 0), G(.7),
      W("I", .15), W("like", .25), W("this", .25), W("idea.", .4, 0), G(.6),
      W("It's", .2), W("uh", .3, 0), G(.25), W("like", .25, 0), G(.3), W("really", .3), W("fast.", .35, 0), G(.6),
      W("You", .2), W("know", .2), W("what", .2), W("I", .15), W("mean?", .3, 0), G(.6),
      W("The", .2), W("the", .2), W("results", .4), W("are", .2), W("good.", .3, 0), G(.6)]


def synth(script, sr=48000, seed=1):
    """-> dict(x mono float32, words (whisper-like transcript), truth [{text, on, off, f, src}], breaths, freq)."""
    rng = np.random.default_rng(seed)
    t, events, breaths, words, truth = 0.0, [], [], [], []
    k = 0

    def onset(t):                                   # word onsets on frame centres (A/V check)
        return (np.floor(t * FPS) + 0.5) / FPS if (t * FPS) % 1 <= 0.5 else (np.ceil(t * FPS) + 0.5) / FPS

    for it in script:
        if it[0] == "g":
            t += it[1]
        elif it[0] == "b":
            breaths.append((t, t + it[1]))
            t += it[1]
        elif it[0] == "w":
            _, text, dur, gap = it
            t = onset(t)
            f = 280 + 31 * k
            k += 1
            events.append((t, t + dur, f))
            truth.append(dict(text=text, on=t, off=t + dur, f=f))
            words.append(dict(w=text, t=round(t - 0.04, 3), te=round(t + dur - 0.03, 3)))
            t += dur + gap
        else:
            _, ftxt, fdur, dip, text, wdur, gap = it
            t = onset(t)
            ff, fw = 280 + 31 * k, 280 + 31 * (k + 1)
            k += 2
            events.append((t, t + fdur, ff))
            truth.append(dict(text=ftxt, on=t, off=t + fdur, f=ff, merged_filler=True))
            w0 = t + fdur + dip
            events.append((w0, w0 + wdur, fw))
            truth.append(dict(text=text, on=w0, off=w0 + wdur, f=fw, merged_word=True, filler_on=t))
            words.append(dict(w=text, t=round(t - 0.04, 3), te=round(w0 + wdur - 0.03, 3)))
            t = w0 + wdur + gap
    n = int((t + 0.2) * sr)
    x = (3e-4 * rng.standard_normal(n)).astype(np.float32)
    ramp = int(0.008 * sr)
    for a, b, f in events:
        i0, i1 = int(round(a * sr)), int(round(b * sr))
        tt = np.arange(i1 - i0) / sr
        y = 0.25 * np.sin(2 * np.pi * f * tt)
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp))
        y[:ramp] *= r
        y[-ramp:] *= r[::-1]
        x[i0:i1] += y.astype(np.float32)
    for a, b in breaths:
        i0, i1 = int(a * sr), int(b * sr)
        nz = rng.standard_normal(i1 - i0)
        spec = np.fft.rfft(nz)
        fr = np.fft.rfftfreq(len(nz), 1 / sr)
        spec[(fr < 400) | (fr > 5000)] = 0
        nz = np.fft.irfft(spec, len(nz))
        nz *= 0.012 / (np.sqrt(np.mean(nz ** 2)) + 1e-9)
        nz *= np.hanning(len(nz)) ** 0.3
        x[i0:i1] += nz.astype(np.float32)
    return dict(x=x, sr=sr, words=words, truth=truth, breaths=breaths, dur=n / sr)


def fake_asr_from(truth):
    """A transcriber that 'hears' tone bursts: voiced runs -> peak frequency -> the word with that tone."""
    table = {d["f"]: d["text"] for d in truth}
    fs = np.array(sorted(table))

    def run(path):
        x = audio.decode_audio(str(path), sr=16000, channels=1)[:, 0]
        env, hop = audio.rms_envelope(x, 16000, 0.005, 0.01, db=True, smooth=1)
        out = []
        for a, b in cleanup._runs(env > -35):
            if (b - a) * hop < 0.05:
                continue
            seg = x[int(a * hop * 16000):int(b * hop * 16000)]
            sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
            f = np.fft.rfftfreq(len(seg), 1 / 16000)[int(np.argmax(sp))]
            near = fs[int(np.argmin(np.abs(fs - f)))]
            if abs(near - f) < 12:
                out.append(dict(w=table[near], t=round(a * hop, 3), te=round(b * hop, 3)))
        return out
    return run


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_media(tmp, s, name="talk", video=True):
    wav = str(tmp / f"{name}.wav")
    audio.write_wav(wav, np.stack([s["x"], s["x"]], 1), s["sr"])
    if not video:
        return wav
    out = str(tmp / f"{name}.mov")
    _ff("-f", "lavfi", "-i", f"nullsrc=s=160x90:r={FPS},geq=lum='16+mod(N\\,50)*4':cb=128:cr=128",
        "-i", wav, "-t", f"{s['dur']:.3f}", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
        "-qp", "0", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", out)
    return out


def _by_text(edits, kind=None):
    return [e for e in edits if kind is None or e["kind"] == kind]


def _truth_of(s, text, nth=0):
    return [d for d in s["truth"] if d["text"] == text and not d.get("merged_filler")][nth]


@pytest.fixture(scope="module")
def zh():
    return synth(ZH)


def _detect(s, profile="standard", **kw):
    return cleanup.detect(s["words"], audio=(s["x"], s["sr"]), profile=profile, **kw)


# ------------------------------------------------------------------ detection (pure, no ffmpeg)
def test_detect_zh_kinds_and_tiers(zh):
    E = _detect(zh)
    kinds = {e["kind"] for e in E}
    assert {"pause", "breath", "filler", "repeat", "restart", "retake", "filler-merged", "lead", "tail"} <= kinds, kinds
    hes = [e for e in E if e["kind"] == "filler" and e["text"] == "嗯"]
    assert hes and hes[0]["action"] == "auto" and hes[0]["confidence"] >= 0.9
    # 那个 inside 「讲一下那个问题」 is a determiner: never auto
    det = [e for e in E if e["kind"] == "filler" and e["text"] == "那个" and e["t0"] < _truth_of(zh, "问题。")["on"]]
    assert all(e["action"] == "keep" for e in det), det
    # sentence-initial determiner 「这个模型…」: a real word, not cut by default
    zg = [e for e in E if e["kind"] == "filler" and e["text"] == "这个" and e["t0"] > _truth_of(zh, "模型。")["off"]]
    assert zg and all(e["action"] == "keep" for e in zg), zg
    # drawn-out, pause-isolated 那个 / 就是: the creator confirms
    iso = [e for e in E if e["kind"] == "filler" and e["text"] in ("那个", "就是") and e["action"] != "keep"]
    assert len(iso) == 2 and all(e["action"] == "confirm" for e in iso), iso
    rep = _by_text(E, "repeat")
    assert rep and rep[0]["text"] == "像这个" and rep[0]["action"] == "auto"
    # first copy removed, last copy kept
    assert rep[0]["t1"] <= _truth_of(zh, "像", 1)["on"] and rep[0]["t0"] >= _truth_of(zh, "问题。")["off"]
    st = _by_text(E, "stammer")
    assert st and st[0]["text"] == "我" and st[0]["action"] == "confirm"
    rs = _by_text(E, "restart")
    assert len(rs) == 1 and rs[0]["text"] == "我们明天去" and rs[0]["action"] == "confirm"
    rt = _by_text(E, "retake")
    assert len(rt) == 1 and rt[0]["action"] == "confirm" and rt[0]["text"].startswith("这个模型的效果非常好")
    assert rt[0]["t1"] <= _truth_of(zh, "这个", 3)["on"]                  # the later take survives
    mg = _by_text(E, "filler-merged")
    w = [d for d in zh["truth"] if d.get("merged_word")][0]
    assert len(mg) == 1 and mg[0]["action"] == "confirm" and mg[0]["text"] == "结果"
    assert w["filler_on"] - 0.5 < mg[0]["t0"] < w["filler_on"] and w["on"] - 0.08 < mg[0]["t1"] <= w["on"]
    assert mg[0]["patch"][1] == mg[0]["t1"]


def test_pauses_squeezed_not_deleted(zh):
    st = cleanup.settings("standard")
    E = _detect(zh)
    p = [e for e in E if e["kind"] == "pause" and e.get("gap", 0) > 0.85][0]       # the 0.9 s sentence pause
    kept = p["gap"] - (p["t1"] - p["t0"])
    assert st["gap_sentence"] - 0.01 <= kept <= st["gap_max"] + 0.01
    for prof in ("gentle", "tight"):
        s2 = cleanup.settings(prof)
        q = [e for e in _detect(zh, prof) if e["kind"] == "pause" and e.get("gap", 0) > 0.85][0]
        k2 = q["gap"] - (q["t1"] - q["t0"])
        assert s2["gap_min"] - 0.01 <= k2 <= max(s2["gap_max"], s2["gap_sentence"]) + 0.01, (prof, k2)
    # tight removes more than standard removes more than gentle
    sec = {pr: sum(e["t1"] - e["t0"] for e in _detect(zh, pr) if e["action"] == "auto") for pr in cleanup.PROFILES}
    assert sec["tight"] > sec["standard"] > sec["gentle"] > 0


def test_breath_removed_or_kept(zh):
    (b0, b1), = zh["breaths"]
    E = _detect(zh)
    br = [e for e in E if e["kind"] == "breath"]
    assert len(br) == 1 and br[0]["t0"] <= b0 + 0.02 and br[0]["t1"] >= b1 - 0.01 and br[0]["action"] == "auto"
    Eg = _detect(zh, "gentle")
    bg = [e for e in Eg if e["kind"] == "breath"]
    assert bg and bg[0]["t1"] <= b0                                            # gentle keeps the breath


def test_word_safe_edges(zh):
    """No edit may touch the sound of a word it does not remove (whisper ends run 30 ms early)."""
    E = _detect(zh)
    W = cleanup.load_words(zh["words"])
    for e in E:
        removed = {W[i]["t"] for i in e["words"]}
        for d, w in zip([d for d in zh["truth"] if not d.get("merged_filler")], W):
            if w["t"] in removed:
                continue
            on, off = d["on"], d["off"]
            if d.get("merged_word") and e["kind"] == "filler-merged":
                assert e["t1"] <= on + 1e-6
                continue
            assert e["t1"] <= on + 1e-6 or e["t0"] >= off - 1e-6, (e, d)
        if e["kind"] in ("pause", "breath", "lead", "tail"):
            assert all(e["t1"] <= d["on"] or e["t0"] >= d["off"] for d in zh["truth"]), e


def test_detect_en():
    s = synth(EN)
    E = _detect(s)
    by = {(e["kind"], e["text"].lower()): e for e in E}
    assert by[("filler", "um")]["action"] == "auto"
    assert by[("filler", "uh")]["action"] == "auto"
    assert by[("stammer", "we")]["action"] == "auto"
    assert by[("stammer", "the")]["action"] == "auto"
    likes = [e for e in E if e["kind"] == "filler" and e["text"] == "like"]
    i_like = [e for e in likes if e["t0"] < _truth_of(s, "this")["on"]]
    assert all(e["action"] == "keep" for e in i_like)                          # "I like this": verb
    iso = [e for e in likes if e["t0"] > _truth_of(s, "this")["on"]]
    assert iso and iso[0]["action"] == "confirm"
    yk = [e for e in E if e["text"].lower().startswith("you know")]
    assert all(e["action"] == "keep" for e in yk)                              # "you know what I mean"
    assert not any(e["text"].lower().startswith("i mean") and e["action"] != "keep" for e in E)
    so = by.get(("filler", "so"))
    assert so is None or so["action"] != "auto"


def test_ranges_limit_edits(zh):
    a, b = _truth_of(zh, "像")["on"] - 0.3, _truth_of(zh, "例子。")["off"] + 0.3
    E = _detect(zh, ranges=[(a, b)])
    assert E and all(a - 1e-3 <= e["t0"] and e["t1"] <= b + 1e-3 for e in E)
    assert {e["kind"] for e in E} >= {"repeat", "stammer"}
    assert not any(e["kind"] == "retake" for e in E)
    keep = cleanup.keep_segments(E, [(a, b)])
    assert keep[0][0] >= a - 1e-3 and keep[-1][1] <= b + 1e-3
    res = cleanup.clean(zh["words"], (zh["x"], zh["sr"]), a, b)
    assert res["keep"] == keep and all(c[2] for c in res["cuts"])


def test_no_audio_fallback(zh):
    E = cleanup.detect(zh["words"])
    assert any(e["kind"] == "filler" and e["text"] == "嗯" for e in E)
    assert all(e["action"] != "auto" for e in E if e["kind"] in ("pause", "lead", "tail"))


def test_hallucinated_segment_and_persona_override(zh, monkeypatch):
    tr = dict(language="zh", segments=[
        dict(start=0.0, end=0.4, text="字幕志愿者", words=[dict(word="字幕志愿者", start=0.0, end=0.4)]),
        dict(start=0.5, end=40, text="".join(w["w"] for w in zh["words"]),
             words=[dict(word=w["w"], start=w["t"], end=w["te"]) for w in zh["words"]])])
    W, dropped, lang = cleanup._transcript_of(tr, None, None, None, cleanup.settings())
    assert lang == "zh" and dropped and dropped[0]["text"] == "字幕志愿者"
    assert not any(w["w"] == "字幕志愿者" for w in W)
    E = cleanup.detect(W, audio=(zh["x"], zh["sr"]), dropped=dropped, ranges=[(0, zh["dur"])])
    assert any(e["kind"] == "asr-noise" and e["action"] == "confirm" for e in E)
    monkeypatch.setattr(cleanup, "_persona_cleanup",
                        lambda: dict(profile="tight", crossfade=0.03, profiles=dict(tight=dict(auto_min=0.7))))
    st = cleanup.settings()
    assert st["profile"] == "tight" and st["auto_min"] == 0.7 and st["crossfade"] == 0.03
    with pytest.raises(KeyError):
        cleanup.settings(overrides=dict(nope=1))


def test_review_sheet_and_reply(zh, tmp_path):
    E = _detect(zh)
    edl = cleanup.build_edl(zh["words"], "talk.mov", None, None, "standard", duration=zh["dur"])
    edl["edits"] = E
    txt = cleanup.review_sheet(edl, tmp_path / "r.md")
    conf = [e for e in E if e["action"] == "confirm"]
    assert "待确认" in txt and f"| {conf[0]['id']} |" in txt and "【" in txt and "确认 3,5,9 / 保留 7" in txt
    assert (tmp_path / "r.md").read_text(encoding="utf-8").startswith("# ")
    r = cleanup.parse_reply("确认 3,5,9 / 保留 7")
    assert r == dict(approve={3, 5, 9}, keep={7}, all_confirm=False)
    assert cleanup.parse_reply("删 2-4 不删 6，全部确认") == dict(approve={2, 3, 4}, keep={6}, all_confirm=True)
    assert cleanup.parse_reply("approve 1, 2 keep 4")["keep"] == {4}
    assert cleanup.parse_ranges("12.5-80,1:40-2:10") == [(12.5, 80.0), (100.0, 130.0)]


def test_word_safe_edge_helpers(zh):
    """In-memory helpers for workflows that place their own edges (hooks, hand-written ranges)."""
    en = cleanup.energy_of((zh["x"], zh["sr"]), zh["words"])
    W = cleanup.load_words(zh["words"])
    k = [i for i, w in enumerate(W) if w["w"] == "方法"][0]
    T = [d for d in zh["truth"] if not d.get("merged_filler")]          # aligned with W
    prev, w, nxt = T[k - 1], T[k], T[k + 1]
    assert w["text"] == "方法"
    lo, hi = cleanup.word_limits(W, W[k]["t"] + 0.1, W[k]["te"])
    assert W[k - 1]["te"] <= lo <= W[k]["t"] + 0.1 and W[k]["te"] <= hi <= W[k + 1]["t"]
    e = cleanup.safe_edge(W, W[k]["te"], en, "end")                 # whisper end runs 30 ms early
    assert w["off"] <= e < nxt["on"], (e, w, nxt)
    s0 = cleanup.safe_edge(W, w["on"] + 0.1, en, "start")           # inside the word -> before its onset
    assert prev["off"] <= s0 <= w["on"], (s0, w)
    a, b = cleanup.snap_range(W, w["on"] + 0.1, W[k]["te"], en)
    assert prev["off"] <= a <= w["on"] and w["off"] <= b < nxt["on"]
    # a window ending on a sentence end (0.6 s pause after): extended past the real tail by the fade
    j = [i for i, x in enumerate(W) if x["w"] == "例子。"][0]
    end, after = T[j], T[j + 1]
    h1, fade, why = cleanup.extend_end(W, en, W[j - 3]["t"], W[j]["te"], fade=0.3)
    assert fade == 0.3 and h1 >= end["off"] + 0.29 and h1 <= after["on"] - 0.05 and why
    # a tight gap (很|好。 60 ms): never into the next word, the fade shrinks instead
    k2 = [i for i, x in enumerate(W) if x["w"] == "很"][0]
    h1, fade, _ = cleanup.extend_end(W, en, W[k2 - 1]["t"], W[k2]["te"], fade=0.3)
    assert h1 <= W[k2 + 1]["t"] - 0.05 + 1e-6 and fade < 0.3
    assert cleanup.extend_end(W, None, 0, W[0]["te"])[0] >= W[0]["te"]


def test_safe_edge_end_at_next_word_start_stays_put(zh):
    """Regression: an "end" edge exactly on the next word's start must not grow over that word."""
    W = cleanup.load_words([("我们", 1.0, 1.3), ("今天", 1.3, 1.7), ("讲", 2.4, 2.7)])
    assert cleanup.safe_edge(W, 1.3, None, "end") <= 1.3                      # 今天 starts at 1.3: not kept
    assert cleanup.safe_edge(W, 2.4, None, "end") <= 2.4
    assert cleanup.safe_edge(W, 1.2, None, "end") > 1.3 - 0.03                # inside 我们 -> its end (<= 今天 - 20 ms)
    en = cleanup.energy_of((zh["x"], zh["sr"]), zh["words"])
    Z = cleanup.load_words(zh["words"])
    for k in range(1, len(Z)):
        t = Z[k]["t"]
        assert cleanup.safe_edge(Z, t, en, "end") <= t + 1e-9, (Z[k]["w"], t)


def test_review_sheet_saved_is_the_cut_union():
    """Regression: overlapping AUTO edits (a pause inside a filler cut) count once in 省 Xs."""
    edl = dict(source=dict(path="talk.mp4"), profile="standard", ranges=[[0.0, 10.0]], edits=[
        dict(id=1, t0=1.0, t1=2.5, kind="filler", text="嗯", confidence=0.95, action="auto", reason="", before="",
             after=""),
        dict(id=2, t0=1.5, t1=2.2, kind="pause", text="", confidence=0.97, action="auto", reason="", before="",
             after=""),
        dict(id=3, t0=4.0, t1=4.7, kind="pause", text="", confidence=0.97, action="auto", reason="", before="",
             after=""),
        dict(id=4, t0=6.0, t1=9.0, kind="retake", text="x", confidence=0.6, action="confirm", reason="", before="",
             after="")])
    assert cleanup.saved_seconds([e for e in edl["edits"] if e["action"] == "auto"]) == pytest.approx(2.2)
    assert "省 2.2s" in cleanup.review_sheet(edl)
    assert cleanup.saved_seconds([(9.5, 12.0)], [(0.0, 10.0)]) == pytest.approx(0.5)      # clipped to the ranges


def test_norm_ranges_and_join_words_public():
    assert cleanup.norm_ranges([(5, 6), (1, 2), (1.5, 3), (7, 7), (3, 4)]) == [(1.0, 4.0), (5.0, 6.0)]
    assert cleanup.norm_ranges(None) == [] and cleanup.norm_ranges([]) == []
    j = cleanup.join_words
    assert j([{"w": "我们"}, {"w": "今天"}, {"w": "讲。"}]) == "我们今天讲。"
    assert j([{"w": "hello,"}, {"w": "world"}, {"w": "!"}]) == "hello, world!"
    assert j([{"w": "用"}, {"w": "GPU"}, {"w": "训练，"}, {"w": "loss"}]) == "用GPU训练，loss"


def test_snap_cut_and_clean_extra(zh):
    """Public word-safe manual cut: snap_cut / snap_cuts, and clean(extra=) cuts them with the edits."""
    en = cleanup.energy_of((zh["x"], zh["sr"]), zh["words"])
    Z = cleanup.load_words(zh["words"])
    T = [d for d in zh["truth"] if not d.get("merged_filler")]
    k = [i for i, w in enumerate(Z) if w["w"] == "数据"][0]            # cut 数据很 out of 数据很重要。
    a, b = cleanup.snap_cut(Z, en, Z[k]["t"] + 0.05, Z[k + 1]["te"] - 0.02)
    assert T[k - 1]["off"] <= a <= T[k]["on"] and Z[k + 1]["te"] <= b <= T[k + 2]["on"], (a, b)
    assert cleanup.snap_cut(Z, en, 0.0, 0.01) is None
    lo, hi = Z[k - 4]["t"] - 0.2, Z[k + 2]["te"] + 0.3
    sc = cleanup.snap_cuts(Z, en, [(a, b, "too much"), (900, 901)], [(lo, hi)])
    assert sc == [[a, b, "edit: too much"]]                               # outside the window -> dropped
    res = cleanup.clean(Z, None, lo, hi, "standard", energy=en, extra=[(Z[k]["t"] + 0.05, Z[k + 1]["te"] - 0.02, "too much")])
    assert res["extra"] == sc and sc[0] in res["cuts"]
    mid = lambda w: (w["t"] + w["te"]) / 2                                 # noqa: E731
    kept = lambda w: any(x <= mid(w) <= y for x, y in res["keep"])         # noqa: E731
    assert not kept(Z[k]) and not kept(Z[k + 1]) and kept(Z[k + 2]) and kept(Z[k - 1])
    ref = cleanup.keep_segments(res["edits"], [(lo, hi)], extra=sc,
                                words=[w for w in Z if lo <= mid(w) <= hi])
    assert res["keep"] == ref


def test_id_offset_and_multi_window_numbering(zh):
    """One numbering across windows (clean(ranges=)) and across clips / windows (id_offset)."""
    en = cleanup.energy_of((zh["x"], zh["sr"]), zh["words"])
    Z = cleanup.load_words(zh["words"])
    split = [w for w in Z if w["w"] == "例子。"][0]["te"] + 0.2
    r1, r2 = (Z[0]["t"] - 0.3, split), (split + 0.1, Z[-1]["te"] + 0.3)
    one = cleanup.clean(Z, None, *r1, profile="standard", energy=en)
    two = cleanup.clean(Z, None, *r2, profile="standard", energy=en, id_offset=len(one["edits"]))
    both = cleanup.clean(Z, None, profile="standard", energy=en, ranges=[r1, r2])
    assert [e["id"] for e in both["edits"]] == list(range(1, len(both["edits"]) + 1))
    assert [e["id"] for e in two["edits"]][0] == len(one["edits"]) + 1
    strip = lambda E: [{k: v for k, v in e.items() if k != "id"} for e in E]      # noqa: E731
    assert strip(both["edits"]) == strip(one["edits"] + two["edits"])
    assert both["keep"] == one["keep"] + two["keep"]
    e5 = cleanup.detect(Z, ranges=[r1], profile="standard", energy=en, id_offset=5)
    assert e5[0]["id"] == 6 and strip(e5) == strip(one["edits"])
    edl = cleanup.build_edl(Z, "talk.mov", en, [r2], "standard", duration=zh["dur"], id_offset=40)
    assert edl["id_offset"] == 40 and edl["edits"][0]["id"] == 41
    assert "id_offset" not in cleanup.build_edl(Z, "talk.mov", en, [r2], "standard", duration=zh["dur"])
    with pytest.raises(ValueError):
        cleanup.clean(Z, None)


def test_write_sidecar_for_a_derived_cut(zh, tmp_path):
    """A cut made outside apply (a retouched body cut by the workflow's own renderer): write_sidecar gives
    verify its expected words + TimeMap, the tag is stable for the same cut."""
    Z = cleanup.load_words(zh["words"])
    k = [i for i, w in enumerate(Z) if w["w"] == "方法"][0]
    gap0 = (Z[k - 1]["te"] + Z[k]["t"]) / 2
    gap1 = (Z[k]["te"] + Z[k + 1]["t"]) / 2
    keep = [(0.0, gap0), (gap1, zh["dur"])]                                 # 方法 dropped
    out = str(tmp_path / "body.strict.wav")
    side = cleanup.write_sidecar(out, "body.wav", keep, Z, "zh", fps=30, applied=[3])
    S = json.loads(pathlib.Path(side).read_text(encoding="utf-8"))
    assert side.endswith("body.strict.cleanup.json") and S["applied"] == [3] and S["fps"] == 30.0
    assert "方法" not in [w["w"] for w in S["expected"]] and len(S["expected"]) == len(Z) - 1
    tag = S["tag"]
    assert json.loads(pathlib.Path(cleanup.write_sidecar(out, "body.wav", keep, Z, "zh", fps=30, applied=[3]))
                      .read_text(encoding="utf-8"))["tag"] == tag
    got = [dict(w=w["w"], t=w["t"], te=w["te"]) for w in S["words"]]       # a perfect re-ASR of the cut
    assert cleanup.verify(out, got=got, write=False)["ok"]
    lost = [w for w in got if w["w"] != "例子。"]
    rep = cleanup.verify(out, got=lost, write=False)
    assert not rep["ok"] and "例子" in rep["missing"][0]["text"]


# ------------------------------------------------------------------ apply / verify (ffmpeg)
@pytest.fixture(scope="module")
def project(tmp_path_factory):
    if not HAS_FF:
        pytest.skip("ffmpeg not installed")
    tmp = tmp_path_factory.mktemp("cleanup")
    s = synth(ZH + ZH[1:] + EN)
    src = make_media(tmp, s)
    edl = cleanup.analyze(src, transcript=s["words"], out=str(tmp / "cleanup.json"),
                          review=str(tmp / "cleanup_review.md"))
    return dict(tmp=tmp, s=s, src=src, edl=edl, path=str(tmp / "cleanup.json"))


def _decode_frames(path):
    """Mean raw Y (limited range, no RGB/full-range conversion) of every frame."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=8:8,format=yuv420p", "-f", "rawvideo",
                        "-pix_fmt", "yuv420p", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, 96)[:, :64].mean(1)


@need_ff
def test_apply_av_sync_over_many_cuts(project):
    s, edl = project["s"], project["edl"]
    assert os.path.exists(project["tmp"] / "cleanup_review.md")
    res = cleanup.apply(project["path"], all_confirm=True)
    assert len(res["applied"]) >= 20 and len(res["keep"]) >= 21, (len(res["applied"]), len(res["keep"]))
    out = res["out"]
    assert ".clean." in out and os.path.exists(out) and os.path.exists(res["sidecar"])
    from vstudio import media
    vd = float(media.ffprobe_value(out, "stream=duration", "v:0"))
    ad = float(media.ffprobe_value(out, "stream=duration", "a:0"))
    assert abs(vd - res["duration"]) < 1.0 / FPS and abs(ad - vd) < 1.0 / FPS
    y = audio.decode_audio(out, sr=48000, channels=1)[:, 0]
    env = np.abs(y)
    lum = _decode_frames(out)
    tm = res["timemap"]
    cutspans = [(e["t0"], e["t1"]) for e in edl["edits"] if e["id"] in set(res["applied"])]
    checked = 0
    for d in s["truth"]:
        if d.get("merged_filler") or any(a <= (d["on"] + d["off"]) / 2 <= b for a, b in cutspans):
            continue
        exp = tm.to_final(d["on"])
        assert exp is not None, d
        i0 = int((exp - 0.03) * 48000)
        hit = i0 + int(np.argmax(env[i0:i0 + 4800] > 0.05))
        da = hit / 48000 - exp
        assert -0.003 < da < 0.008, (d["text"], da)                             # audio where the TimeMap says
        n = int(exp * FPS)
        code = int(round((lum[n] - 16) / 4)) % 50
        assert code == int(d["on"] * FPS) % 50, (d["text"], code, int(d["on"] * FPS) % 50)   # same frame as source
        checked += 1
    assert checked >= 60
    # removed things are gone from the TimeMap; kept words map, cut-out times snap forward
    um = [d for d in s["truth"] if d["text"] == "um"][0]
    assert tm.to_final((um["on"] + um["off"]) / 2) is None
    assert tm.to_final((um["on"] + um["off"]) / 2, "fwd") is not None
    side = json.load(open(res["sidecar"], encoding="utf-8"))
    assert side["words"] and side["words"][0]["t"] >= 0 and cut.TimeMap(side["timemap"]).duration == pytest.approx(
        res["duration"])


@need_ff
def test_apply_idempotent_and_versioned(project):
    h0 = hashlib.sha1(open(project["path"], "rb").read()).hexdigest()
    r1 = cleanup.apply(project["path"])
    m1 = os.path.getmtime(r1["out"])
    r2 = cleanup.apply(project["path"])
    assert r2["reused"] and r2["out"] == r1["out"] and os.path.getmtime(r1["out"]) == m1
    conf = [e["id"] for e in project["edl"]["edits"] if e["action"] == "confirm"]
    auto = [e["id"] for e in project["edl"]["edits"] if e["action"] == "auto"]
    r3 = cleanup.apply(project["path"], reply=f"确认 {conf[0]} / 保留 {auto[0]}")
    assert r3["out"] != r1["out"] and conf[0] in r3["applied"] and auto[0] not in r3["applied"]
    assert os.path.exists(r1["out"])                                           # earlier version untouched
    assert hashlib.sha1(open(project["path"], "rb").read()).hexdigest() == h0  # EDL never rewritten
    with pytest.raises(ValueError):
        cleanup.apply(project["path"], approve=[9999])
    with pytest.raises(SystemExit):                                            # never cut an already-cut file
        cleanup.apply(project["path"], media_path=r1["out"])


@need_ff
def test_verify_ok_and_catches_lost_word(project):
    s = project["s"]
    asr_fake = fake_asr_from(s["truth"])
    r1 = cleanup.apply(project["path"])
    rep = cleanup.verify(r1["out"], transcriber=asr_fake)
    assert rep["ok"], rep["missing"]
    w = _truth_of(s, "方法")
    # whisper mis-timed 「方法」 (reported 0.3 s late) and an editor cut lands on its real sound: the EDL
    # still expects the word, the cut file lacks it -> verify must fail loudly
    edl = json.load(open(project["path"], encoding="utf-8"))
    ww = [x for x in edl["words"] if x["w"] == "方法"][0]
    ww["t"], ww["te"] = round(w["off"] + 0.02, 3), round(w["off"] + 0.32, 3)
    bad = cleanup.apply(edl, extra_cuts=[(w["on"] - 0.05, w["off"] + 0.03)], media_path=project["src"],
                        out=str(project["tmp"] / "bad.mp4"))
    rep2 = cleanup.verify(bad["out"], transcriber=asr_fake)
    assert not rep2["ok"]
    assert any("方法" in f["text"] and abs(f["t_src"] - ww["t"]) < 0.1 for f in rep2["missing"]), rep2["missing"]
    with pytest.raises(RuntimeError):
        cleanup.verify(bad["out"], transcriber=asr_fake, raise_on_fail=True)


@need_ff
def test_cli_audio_only(tmp_path):
    s = synth(EN)
    wav = make_media(tmp_path, s, video=False)
    tj = tmp_path / "t.json"
    tj.write_text(json.dumps(s["words"]), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "lib"))
    run = lambda *a: subprocess.run([sys.executable, "-m", "vstudio.cleanup", *a], cwd=tmp_path, env=env,  # noqa: E731
                                    capture_output=True, text=True)
    r = run("analyze", wav, "--transcript", str(tj), "--profile", "standard")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "cleanup.json").exists() and (tmp_path / "cleanup_review.md").exists()
    r = run("apply", "cleanup.json", "--keep", "1")
    assert r.returncode == 0, r.stderr
    out = r.stdout.strip().splitlines()[-1]
    assert out.endswith(".wav") and os.path.exists(out)
    edl = json.load(open(tmp_path / "cleanup.json", encoding="utf-8"))
    x, sr = audio.read_wav(out)
    side = json.load(open(os.path.splitext(out)[0] + ".cleanup.json", encoding="utf-8"))
    assert len(x) / sr == pytest.approx(side["duration"], abs=1e-3)
    assert len(x) / sr < edl["source"]["duration"] - 1.0
    got = tmp_path / "got.json"
    got.write_text(json.dumps(fake_asr_from(s["truth"])(out)), encoding="utf-8")
    assert run("verify", out, "--transcript", str(got)).returncode == 0
