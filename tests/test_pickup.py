"""Pickups (补录) with real ffmpeg: splicing a short re-recorded insert into a clip (level match, room tone, crossfaded
joins, frame-exact timing), the ``pickup`` op in a clip's edit steps (remap of existing cuts, words without
re-transcribing, undo / redo / revert, render), and the recorder's ``edit`` target (the whole take as the session's
own clip with the automatic cleanup as its first step)."""
import json
import os
import shutil

import numpy as np
import pytest

from _batch_helpers import make_video, synth_speech
from _create_helpers import home  # noqa: F401

from vstudio import audio, media, pickup as P
from vstudio.project import outputs as O, works as WK

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
SR = 48000
BASE_WORDS = [(f"b{k}", 0.35) for k in range(10)]
PICK_WORDS = [("p0", 0.3), ("p1", 0.3), ("p2", 0.3)]


def _noisy(x, level, seed):
    rng = np.random.default_rng(seed)
    return (x + level * rng.standard_normal(len(x))).astype(np.float32)


@pytest.fixture
def clips(tmp_path):
    """base: 10 tone words at 0.25 amplitude over a -46 dB noise floor; pickup: 3 quieter words (-10 dB) over a
    much quieter floor, with 0.6 s of silence before and after (trimmed by the speech span)."""
    xb, tb, db = synth_speech(BASE_WORDS, gap=0.15)
    xb = _noisy(xb, 0.005, 2)
    base = make_video(str(tmp_path / "base.mp4"), xb, SR, db)
    xp, tp, dp = synth_speech(PICK_WORDS, lead=0.6, gap=0.15, seed=3)
    xp = (xp * 0.316).astype(np.float32)
    pick = make_video(str(tmp_path / "pick.mp4"), xp, SR, dp + 0.3, size="360x640")
    return dict(base=base, base_words=tb, pick=pick, pick_words=tp, dir=tmp_path)


def _level_at(x, a, b):
    return P.speech_level(x[int(a * SR):int(b * SR)])


def _tone_power(x, t0, t1, f):
    seg = x[int(t0 * SR):int(t1 * SR)]
    if seg.ndim > 1:
        seg = seg.mean(1)
    n = np.arange(len(seg))
    return float(abs(np.dot(seg, np.exp(-2j * np.pi * f * n / SR))) / max(1, len(seg)))


def test_splice_levels_room_tone_timing_and_joins(clips):
    tb, tp = clips["base_words"], clips["pick_words"]
    at, end = tb[3]["t"] - 0.08, tb[4]["te"] + 0.1          # replace words b3, b4
    span = P.speech_span([dict(w=w["w"], t=w["t"], te=w["te"]) for w in tp], media.duration(clips["pick"]))
    out = str(clips["dir"] / "spliced.mp4")
    r = P.splice(clips["base"], clips["pick"], at, end, out=out, span=span)
    bi, oi = media.probe(clips["base"]), media.probe(out)
    # timing: the new file is the base minus [at, end) plus the insert, on the frame grid
    assert oi["w"] == bi["w"] and oi["h"] == bi["h"]
    expect = bi["duration"] - (r["end"] - r["at"]) + r["inserted"]
    assert abs(oi["duration"] - expect) < 2.5 / 30
    assert abs(r["inserted"] - (span[1] - span[0])) < 1 / 30 + 1e-6
    x = audio.decode_audio(out, SR, 2)
    assert abs(len(x) / SR - expect) < 0.05
    # level: the insert's speech was ~10 dB quieter; in the output it matches the base around it
    assert r["gain_db"] == pytest.approx(10, abs=1.5)
    ins_a, ins_b = r["at"], r["at"] + r["inserted"]
    assert abs(_level_at(x, ins_a + 0.1, ins_b - 0.1) - _level_at(x, 0, r["at"])) < 1.5
    # room tone: the insert's floor was ~30 dB lower; filled up to the base's
    assert r["room_db"] is not None
    pfloor = P.noise_floor(x[int(ins_a * SR):int(ins_b * SR)])
    bfloor = P.noise_floor(x[:int(r["at"] * SR)])
    assert abs(pfloor - bfloor) < 4
    # the base word after the replaced range (b5) moved by inserted - (end - at); the pickup's words sit inside
    d = r["inserted"] - (r["end"] - r["at"])
    f5 = 300 + 37 * 5
    t5 = tb[5]["t"] + 0.02 + d
    assert _tone_power(x, t5 + 0.05, t5 + 0.3, f5) > 5 * _tone_power(x, t5 + 0.05, t5 + 0.3, f5 + 50)
    f_p1 = 300 + 37 * 1
    tp1 = tp[1]["t"] + 0.02 - span[0] + r["at"]
    assert _tone_power(x, tp1 + 0.05, tp1 + 0.25, f_p1) > 5 * _tone_power(x, tp1 + 0.05, tp1 + 0.25, f_p1 + 50)
    # b3 / b4 are gone
    for k in (3, 4):
        f = 300 + 37 * k
        assert _tone_power(x, 0, len(x) / SR, f) < 0.2 * _tone_power(x, 0, len(x) / SR, f5)
    # joins: crossfaded, no step (the largest sample jump near a join stays at the signal's own scale)
    for j in (r["at"], ins_b):
        i = int(j * SR)
        w = x[i - 960:i + 960, 0]
        assert np.max(np.abs(np.diff(w))) < 0.08


def test_shift_words():
    W = [dict(w=f"w{k}", t=k * 1.0, te=k * 1.0 + 0.5) for k in range(5)]
    PW = [dict(w="x", t=10.2, te=10.6), dict(w="y", t=10.7, te=11.0)]
    out = P.shift_words(W, 2.0, 3.6, 1.0, PW, 10.1)        # w2, w3 replaced by a 1 s pickup
    assert [w["w"] for w in out] == ["w0", "w1", "x", "y", "w4"]
    assert out[2]["t"] == pytest.approx(2.1) and out[4]["t"] == pytest.approx(4.0 + 1.0 - 1.6)
    ins = P.shift_words(W, 1.75, 1.75, 0.5, [dict(w="z", t=0.1, te=0.4)], 0.0)
    assert [w["w"] for w in ins] == ["w0", "w1", "z", "w2", "w3", "w4"] and ins[3]["t"] == pytest.approx(2.5)


@pytest.fixture
def work(clips, monkeypatch):
    """An adopted work folder whose final/talk.mp4 is the base clip; a perfect fake ASR per file."""
    d = clips["dir"] / "work"
    os.makedirs(d / "final")
    shutil.copy(clips["base"], d / "final" / "talk.mp4")
    WK.touch(str(d), recipe="talkinghead", title="Talk", register=False)
    truth = {"talk.mp4": clips["base_words"], "pick.mp4": clips["pick_words"]}

    def fake(path, language=None):
        name = os.path.basename(path)
        for k, ws in truth.items():
            if name == k:
                return [dict(w=w["w"], t=w["t"], te=w["te"]) for w in ws]
        raise AssertionError(f"unexpected transcription of {name}: a spliced file must not be transcribed again")
    monkeypatch.setattr(O, "TRANSCRIBE", fake)
    return str(d)


def test_pickup_op_remaps_edits_and_undoes(work, clips):
    out = "final/talk.mp4"
    s0 = O.show(work, out)
    W0 = O.cached_words(O._load(work, out)[1]) or O.words(O._load(work, out)[1])
    O.edit(work, out, [dict(op="cut", words=[1, 1], why="transcript"), dict(op="cut", words=[7, 7], why="transcript")])
    st1 = O.show(work, out)["state"]
    c_after_before = [c for c in st1["cuts"] if c[0] > W0[5]["t"]][0]
    r = O.pickup(work, out, clips["pick"], replace=[3, 4], sig=O.words_sig(W0))
    pk = r["pickup"]
    assert r["step"]["ops"][0]["op"] == "pickup" and r["step"]["describe"][0]["code"] == "op-pickup"
    assert pk["text"] == "p0p1p2" or pk["text"].replace(" ", "") == "p0p1p2"
    assert pk["replaced"].replace(" ", "") == "b3b4"
    # the clip now plays the spliced file; edits moved with it
    assert r["output"]["file"] == pk["out"] and os.path.isfile(pk["out"])
    d = pk["inserted"] - (pk["end"] - pk["at"])
    st = r["state"]
    assert st["cuts"][0][:2] == st1["cuts"][0][:2]                   # before the pickup: unchanged
    moved = [c for c in st["cuts"] if c[0] > pk["at"]][0]
    assert moved[0] == pytest.approx(c_after_before[0] + d, abs=1e-3)
    assert r["pickups"] == [dict(id="p1", start=pk["at"], end=pytest.approx(pk["at"] + pk["inserted"], abs=1e-4),
                                 text=pk["text"], replaced=pk["replaced"])]
    # the words: the base's + the pickup's, never re-transcribed (the fake refuses the spliced file)
    doc = O._load(work, out)[1]
    W1 = O.cached_words(doc)
    assert [w["w"] for w in W1] == ["b0", "b1", "b2", "p0", "p1", "p2"] + [f"b{k}" for k in range(5, 10)]
    assert r["paths"]["transcript"].endswith(".json") and "transcripts" in r["paths"]["transcript"]
    # a cut by words on the new timeline works (sig of the new words)
    O.edit(work, out, [dict(op="cut", words=[4, 4], why="transcript", sig=O.words_sig(W1))])
    # render: the export is the spliced file minus the cuts
    from vstudio.project import outrender as R
    rr = R.render(work, out, quality="preview", targets=["primary"])
    f = rr["targets"][0]["file"]
    edited = O.show(work, out)["timeline"]["duration"]
    assert abs(media.duration(f) - edited) < 0.15
    x = audio.decode_audio(f, SR, 2)
    assert _tone_power(x, 0, len(x) / SR, 300 + 37 * 2) > 0                      # pickup words are in the export
    # undo the cut, then the pickup: back on the original file, the cut after it back in place
    O.undo(work, out)
    u = O.undo(work, out)
    assert u["output"]["file"] == s0["output"]["file"] and u["pickups"] == []
    assert [c[:2] for c in u["state"]["cuts"]] == [c[:2] for c in st1["cuts"]]
    assert [w["w"] for w in O.cached_words(O._load(work, out)[1])] == [w["w"] for w in W0]
    re_ = O.redo(work, out)
    assert re_["output"]["file"] == pk["out"] and len(re_["pickups"]) == 1


def test_pickup_insert_and_revert_order(work, clips):
    out = "final/talk.mp4"
    W0 = O.words(O._load(work, out)[1])
    a = O.pickup(work, out, clips["pick"], at_word=2)
    pk = a["pickup"]
    assert pk["end"] == pk["at"] and W0[1]["te"] <= pk["at"] <= W0[2]["t"]
    assert media.duration(pk["out"]) == pytest.approx(media.duration(clips["base"]) + pk["inserted"], abs=0.1)
    b = O.pickup(work, out, clips["pick"], at_word=0)
    assert [p["id"] for p in b["pickups"]] == ["p1", "p2"]
    first = next(p for p in b["pickups"] if p["id"] == "p1")
    assert first["start"] == pytest.approx(pk["at"] + b["pickup"]["inserted"], abs=1e-3)   # moved by the new one
    with pytest.raises(O.OutputError) as e:
        O.revert(work, out, a["step"]["id"])
    assert e.value.info["code"] == "revert-conflict"
    O.revert(work, out, b["step"]["id"])                                  # the newest one can go
    s = O.show(work, out)
    assert s["output"]["file"] == pk["out"] and [p["id"] for p in s["pickups"]] == ["p1"]


def test_pickup_refuses_silence_and_bad_points(work, clips, monkeypatch):
    out = "final/talk.mp4"
    O.words(O._load(work, out)[1])
    with pytest.raises(O.OutputError) as e:
        O.pickup(work, out, clips["pick"], replace=[3, 99])
    assert e.value.info["code"] == "bad-param"
    with pytest.raises(O.OutputError) as e:
        O.pickup(work, out, clips["pick"], at_word=1, sig="nope")
    assert e.value.info["code"] == "stale-words"
    base_fake = O.TRANSCRIBE
    monkeypatch.setattr(O, "TRANSCRIBE", lambda p, language=None: [] if p.endswith("pick.mp4") else base_fake(p))
    with pytest.raises(O.OutputError) as e:
        O.pickup(work, out, clips["pick"], at_word=1)
    assert e.value.info["code"] == "pickup-silent"
    assert O.show(work, out)["history"]["undo"] == 0


def _session(root, name, seconds, marks, words_file=None):
    from test_create_record import _webm
    d = os.path.join(root, "recordings", name)
    os.makedirs(d, exist_ok=True)
    _webm(os.path.join(d, "camera.webm"), seconds)
    _webm(os.path.join(d, "mic.webm"), seconds, video=False)
    json.dump(dict(id=name, slug="take", title="My take", script=["Line one.", "Line two."], studio=False,
                   tracks=dict(camera=dict(file="camera.webm", start_ms=1000), mic=dict(file="mic.webm", start_ms=1000))),
              open(os.path.join(d, "session.json"), "w"))
    json.dump(marks, open(os.path.join(d, "takes.json"), "w"))
    return d


def test_record_edit_target_then_pickup_from_a_session(home, monkeypatch):  # noqa: F811
    from vstudio.create import record as RE
    # 8 s take: line 0 said, said again after a retake mark at 3 s (the first attempt is dropped), line 1 at 5.5 s;
    # an "um" inside the kept part and a long pause before line 1
    words = [dict(w="hello", t=0.5, te=0.9), dict(w="there", t=1.0, te=1.4),
             dict(w="hello", t=3.3, te=3.7), dict(w="um", t=3.8, te=4.1), dict(w="there", t=4.2, te=4.6),
             dict(w="line", t=5.6, te=6.0), dict(w="two", t=6.1, te=6.5)]
    pick_words = [dict(w="again", t=0.4, te=0.9), dict(w="better", t=1.0, te=1.5)]

    def fake(path, language=None):
        return pick_words if "pickups" in path else words
    monkeypatch.setattr(O, "TRANSCRIBE", fake)
    d = _session(str(home), "20261010-140200-take", 8,
                 [dict(t=0.0, kind="line", line=0), dict(t=3.0, kind="retake", line=0), dict(t=5.3, kind="line", line=1)])
    r = RE.ingest(d, "edit")
    assert r["output"] == "final/recording.mp4" and os.path.isfile(r["file"]) and r["words"] == len(words)
    assert r["cuts"]["retake"] == 1 and r["cuts"]["filler"] == 1
    rec = json.load(open(WK.record_path(d)))
    assert rec["kind"] == "work" and rec["recording"]["session"] == os.path.basename(d)
    s = O.show(d, r["output"])
    steps = s["history"]["steps"]
    assert len(steps) == 1 and steps[0]["by"] == "auto"
    whys = sorted({c[2] for c in s["state"]["cuts"]})
    assert "retake" in " ".join(whys) and "filler" in " ".join(whys)
    retake = next(c for c in s["state"]["cuts"] if "retake" in c[2])
    assert retake[0] <= 0.5 and retake[1] >= 1.4                        # the first "hello there" is out
    # the take registered as a work (All projects lists it)
    from vstudio.project import home as H
    assert any(os.path.realpath(x["dir"]) == os.path.realpath(d) for x in H.projects())
    # a pickup recorded with the same recorder (a session folder) goes in before "line two"
    p = _session(str(home), "20261010-140500-pickup", 3, [])
    out = O.pickup(d, r["output"], p, at_word=5)
    assert out["pickup"]["text"].replace(" ", "") == "againbetter"
    W = O.cached_words(O._load(d, r["output"])[1])
    assert [w["w"] for w in W][5:7] == ["again", "better"]
    assert len(out["history"]["steps"]) == 2 and out["state"]["cuts"]              # the auto cuts survive
