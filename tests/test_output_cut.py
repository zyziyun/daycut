"""Transcript ("Descript-style") cuts of a finished output (vstudio.project outputs / outrender): cuts by word index
and by pause, stale selections, one Apply = one undo step with captions / effects re-timed in it, zero-crossing
edges, cut strategies of flattened files (burned captions), preview-edl parity with the renderer and the transcript
marks. Synthetic media only, no network."""
import json
import os
import shutil

import numpy as np
import pytest

import _batch_helpers as H
from test_output_edit import _cli, _iso, _pipeline, _TRUTH, _work, media, synth, th  # noqa: F401  (fixtures)
from vstudio.project import outputs as O
from vstudio.project import outrender as R

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
SR = 48000

# (text, seconds, pause after): a 1.0 s pause after 好, fillers 嗯 / 那个 / 就是
PZ_WORDS = [("大家", .4, .12), ("好", .3, 1.0), ("嗯", .3, .35), ("今天", .4, .12), ("那个", .35, .35), ("讲", .3, .12),
            ("一个", .35, .12), ("方法", .4, .12), ("就是", .3, .12), ("很", .25, .12), ("好用", .4, .12),
            ("最后", .4, .12), ("总结", .4, .12), ("一下", .35, .12)]


def _clip(path, words, bed=0.0, amp=0.25, lead=0.4):
    """A synthetic talking clip: one tone burst per word (``synth_speech`` style, own pause per word), optionally
    over a continuous 190 Hz bed (so every cut slices a waveform). -> (video, truth words, duration)."""
    rng = np.random.default_rng(3)
    t, ev, truth = lead, [], []
    for k, (text, dur, gap) in enumerate(words):
        ev.append((t, t + dur, 300 + 37 * k))
        truth.append(dict(w=text, t=round(t - 0.02, 3), te=round(t + dur - 0.02, 3)))
        t += dur + gap
    n = int((t + 0.4) * SR)
    tt = np.arange(n) / SR
    x = (3e-4 * rng.standard_normal(n) + bed * np.sin(2 * np.pi * 190 * tt + 0.7)).astype(np.float32)
    ramp = int(0.008 * SR)
    for a, b, f in ev:
        i0, i1 = int(a * SR), int(b * SR)
        y = amp * np.sin(2 * np.pi * f * np.arange(i1 - i0) / SR)
        r = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, ramp))
        y[:ramp] *= r
        y[-ramp:] *= r[::-1]
        x[i0:i1] += y.astype(np.float32)
    H.make_video(path, x, SR, n / SR)
    return path, truth, n / SR


@pytest.fixture(scope="module")
def pz(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("opz")
    v, truth, dur = _clip(str(d / "pz.mp4"), PZ_WORDS)
    vb, truth_b, dur_b = _clip(str(d / "bed.mp4"), PZ_WORDS, bed=0.15, amp=0.2)
    return dict(video=v, truth=truth, dur=dur, bed=vb, bed_truth=truth_b)


def _adopt(tmp_path, video, truth, name="work"):
    w = tmp_path / name
    (w / "final").mkdir(parents=True)
    f = w / "final" / "clip.mp4"
    shutil.copy(video, f)
    (w / "REPORT.md").write_text("# clip\n")
    from vstudio.project import works
    works.adopt(str(w))
    _TRUTH[str(f)] = truth
    return str(w), "final/clip.mp4"


def _words(w, oid):
    rec, doc = O._load(w, oid)
    W = O.words(doc)
    return W, O.words_sig(W)


def _set_burned(w, oid, captions):
    rec, doc = O._load(w, oid)
    doc.d["burned"] = dict(captions=captions, band="lower" if captions else None,
                           box=[0.06, 0.70, 0.94, 0.96] if captions else None)
    doc.save()


# --------------------------------------------------------------------------- pure helpers
def test_zero_cross_finds_the_nearest_sign_change():
    sr, f, t0 = 48000, 200.0, 1.0
    x = np.sin(2 * np.pi * f * (np.arange(int(0.02 * sr)) / sr) + 0.3)     # crossings every 2.5 ms
    for t in (1.0061, 1.0093, 1.0124):
        z = O.zero_cross(x, sr, t, t0)
        assert abs(z - t) <= 0.005 + 1e-9
        # a real sign change: the interpolated sine value at z is ~0
        assert abs(np.sin(2 * np.pi * f * (z - t0) + 0.3)) < 0.01
        crossings = [(k * np.pi - 0.3) / (2 * np.pi * f) + t0 for k in range(1, 10)]
        assert abs(z - min(crossings, key=lambda c: abs(c - t))) < 2e-5
    assert O.zero_cross(np.full(960, 0.2), sr, 1.01, t0) == 1.01           # no crossing: unchanged
    assert O.zero_cross(np.array([]), sr, 1.01, t0) == 1.01


def test_snap_captions_pure():
    W = [dict(w=c, t=round(0.2 * k, 3), te=round(0.2 * k + 0.15, 3)) for k, c in enumerate("abcde")]
    W += [dict(w=c, t=round(1.6 + 0.2 * k, 3), te=round(1.6 + 0.2 * k + 0.15, 3)) for k, c in enumerate("fghij")]
    gaps = O._caption_gaps(W)
    assert any(a == 0.95 and b == 1.6 for a, b in gaps)                    # the line break between e and f
    s, e, warns = O._snap_captions(W, 0.775, 1.575)                        # start between d and e: 0.205 s away
    assert s == 0.98 and e == 1.575 and warns == []
    s, e, warns = O._snap_captions(W, 0.375, 1.575)                        # between b and c: too far from a break
    assert s == 0.375 and [x["code"] for x in warns] == ["cut-splits-burned-caption"]
    assert warns[0]["message_zh"] and warns[0]["params"]["at"] == 0.38


def test_marks_and_words_sig_pure():
    W = [dict(w="大家", t=0.0, te=0.3), dict(w="好", t=0.35, te=0.6), dict(w="嗯", t=1.4, te=1.7),
         dict(w="今天", t=2.1, te=2.5), dict(w="那个", t=3.0, te=3.35), dict(w="讲", t=3.8, te=4.1, p=0.3),
         dict(w="一个", t=4.15, te=4.5), dict(w="方法", t=4.55, te=4.9)]
    m = O.marks(W)
    kinds = {(x["kind"], x["i0"], x["i1"]) for x in m}
    assert ("filler", 2, 2) in kinds and ("filler", 4, 4) in kinds
    f = next(x for x in m if x["kind"] == "filler" and x["i0"] == 2)
    assert f["text"] == "嗯" and f["group"] == "嗯" and f["save_s"] > 0
    assert {x["group"] for x in m if x["kind"] == "filler"} >= {"嗯", "那个"}
    p = [x for x in m if x["kind"] == "pause"]
    assert (1, 2) in {(x["i0"], x["i1"]) for x in p}                       # 0.8 s after 好
    assert all(float(W[x["i1"]]["t"]) - float(W[x["i0"]]["te"]) > 0.6 for x in p)
    p1 = next(x for x in p if x["i0"] == 1)
    assert p1["text"] == "0.8s" and abs(p1["save_s"] - 0.55) <= 0.051
    assert [(x["i0"], x["text"]) for x in m if x["kind"] == "lowconf"] == [(5, "讲")]
    assert O.marks(W) == m and len(O.marks(W, limit=2)) == 2
    sig = O.words_sig(W)
    assert sig == O.words_sig([dict(x) for x in W]) and len(sig) == 10
    assert sig != O.words_sig(W[:-1])
    # the probability survives transcription (asr dict shape)
    raw = dict(segments=[dict(words=[dict(word=" 好", start=0.1, end=0.3, probability=0.42),
                                     dict(word=" ", start=0.3, end=0.31)])])
    assert O._flat_words(raw) == [dict(w="好", t=0.1, te=0.3, p=0.42)]


# --------------------------------------------------------------------------- cut by words / by pause
@media
def test_cut_by_word_index_gap_and_stale_selection(tmp_path, pz):
    w, oid = _adopt(tmp_path, pz["video"], pz["truth"])
    s = O.show(w, oid)
    assert s["words_sig"] is None and s["marks"] == []                     # nothing transcribed by show
    assert s["caps"]["cut_words"] is True and s["caps"]["cut_strategy"] == "hard"
    W, sig = _words(w, oid)
    s = O.show(w, oid)
    assert s["words_sig"] == sig and O.show(w, oid)["words_sig"] == sig   # stable
    assert any(m["kind"] == "pause" and m["i0"] == 1 for m in s["marks"])
    assert any(m["kind"] == "filler" and m["text"] == "嗯" for m in s["marks"])

    for op, code in ((dict(op="cut", words=[5, 6], sig="0000000000"), "stale-words"),
                     (dict(op="cut", words=[6, 5]), "bad-param"), (dict(op="cut", words=[0, 999]), "bad-param"),
                     (dict(op="cut", words=["a", 1]), "bad-param"), (dict(op="cut", words=[1, 2, 3]), "bad-param"),
                     (dict(op="cut", gap=0), "bad-param"),                 # a 0.12 s pause cannot keep 0.25 s
                     (dict(op="cut", gap=len(W) - 1), "bad-param")):
        with pytest.raises(O.OutputError) as ei:
            O.edit(w, oid, op)
        assert ei.value.info["code"] == code, (op, ei.value.info)
        if code == "stale-words":
            assert ei.value.info["params"] == dict(expected=sig, got="0000000000", index=0)
            assert ei.value.info["message_zh"] == "文字稿已更新，请重新选择"
    assert O.show(w, oid)["history"]["undo"] == 0

    fr = 1 / 30
    r = O.edit(w, oid, dict(op="cut", words=[5, 6], sig=sig, why="transcript"))
    a, b = r["values"][0]["cut"]
    assert W[4]["te"] - fr <= a <= W[5]["t"] + fr and W[6]["te"] - fr <= b <= W[7]["t"] + fr
    assert r["values"][0]["words"] == "讲一个" and r["values"][0]["word_range"] == [5, 6]
    d = r["step"]["describe"][0]
    assert d["code"] == "op-cut" and d["params"]["said"] == "讲一个" and d["params"]["why"] == "transcript"
    assert r["step"]["retimed"]["targets"] == ["primary"]
    assert r["history"]["steps"][-1]["retimed"] == r["step"]["retimed"]

    r = O.edit(w, oid, dict(op="cut", gap=1, sig=sig))
    a, b = r["values"][0]["cut"]
    assert r["state"]["cuts"][0][2] == "pause"
    assert abs(a - (W[1]["te"] + 0.125)) <= 0.0051 and abs(b - (W[2]["t"] - 0.125)) <= 0.0051
    assert abs((a - W[1]["te"]) + (W[2]["t"] - b) - 0.25) < 0.011            # 0.25 s of the pause kept
    r = O.edit(w, oid, dict(op="cut", gap=8, keep=0.05, sig=sig))           # 就是|很: 0.12 s, keep clamped 0.05
    a, b = r["values"][0]["cut"]
    assert r["values"][0]["keep_s"] == 0.05 and W[8]["te"] < a < b < W[9]["t"]


# --------------------------------------------------------------------------- one step, effects, undo
@media
def test_three_cuts_one_step_effects_retimed_and_undo(tmp_path, synth):
    w, oid = _work(tmp_path, synth)
    W, sig = _words(w, oid)
    T = synth["truth"]
    assert [x["w"] for x in W] == [x["w"] for x in T]
    fx = O.edit(w, oid, [
        dict(op="effect_add", effect="pop-words", start=W[6]["t"], params=dict(text="方法")),      # bound to W6
        dict(op="effect_add", effect="stamp", start=W[11]["t"] + 0.05, end=W[13]["te"] - 0.05,
             params=dict(text="亲测")),                                                              # fully cut
        dict(op="effect_add", effect="badge", start=W[15]["t"], end=W[17]["te"], params=dict(text="精选")),  # partial
        dict(op="effect_add", effect="sfx", start=W[12]["t"] + 0.1, params=dict(name="pop")),        # inside a cut
        dict(op="effect_add", effect="music-bed", start=0, params=dict(file=synth["bgm"])),
        dict(op="effect_add", effect="punch-in", start=W[0]["t"], end=W[2]["te"])])                  # untouched
    ids = {e["effect"]: e["id"] for e in fx["state"]["effects"]}
    before = O.show(w, oid)
    r = O.edit(w, oid, [dict(op="cut", words=[6, 6], sig=sig, why="transcript"),
                        dict(op="cut", words=[11, 13], sig=sig, why="transcript"),
                        dict(op="cut", words=[16, 16], sig=sig, why="filler")])
    assert r["history"]["undo"] == before["history"]["undo"] + 1           # one Apply = one step
    assert len(r["state"]["cuts"]) == 3
    rt = r["step"]["retimed"]
    assert {x["id"] for x in rt["effects"]["removed"]} == {ids["pop-words"], ids["stacking-stamps"]}
    assert all(x["label"]["en"] and x["label"]["zh"] for x in rt["effects"]["removed"])
    tr = rt["effects"]["trimmed"]
    assert [x["id"] for x in tr] == [ids["badge"]] and tr[0]["from_s"] > tr[0]["to_s"] >= 0.4
    assert rt["sfx_removed"] == 1 and rt["captions"] == dict(retimed=0, shortened=0, removed=0)
    left = {e["effect"] for e in r["state"]["effects"]}
    assert left == {"badge", "music-bed", "punch-in"}                      # music-bed never touched
    ops = [o["op"] for o in r["step"]["ops"]]
    assert ops.count("cut") == 3 and ops.count("effect_remove") == 3
    assert {d["code"] for d in r["step"]["describe"]} == {"op-cut", "op-effect-remove"}
    # a single undo restores everything
    u = O.undo(w, oid)
    assert u["state"]["cuts"] == [] and u["state"]["effects"] == before["state"]["effects"]
    assert O.redo(w, oid)["state"]["cuts"] == r["state"]["cuts"]


# --------------------------------------------------------------------------- pipeline captions
@media
def test_pipeline_cut_retimes_captions(th):
    oid, rec = _pipeline(th)
    W, sig = _words(th, oid)
    s0 = O.show(th, oid)
    assert s0["caps"]["cut_strategy"] == "remaster" and s0["caps"]["cut_words"]
    cues = [c for c in s0["captions"] if not c["removed"]]

    def idx(c):
        return [i for i, w in enumerate(W) if c["start"] - 1e-3 <= (w["t"] + w["te"]) / 2 <= c["end"] + 1e-3]
    assert len(cues) >= 2
    mid, full = cues[0], cues[-1]                 # cut two words inside the first cue, the whole last cue
    assert len(idx(mid)) >= 5 and len(idx(full)) >= 2
    mi, fi = idx(mid), idx(full)
    r = O.edit(th, oid, [dict(op="cut", words=[mi[2], mi[3]], sig=sig, why="transcript"),
                         dict(op="cut", words=[fi[0], fi[-1]], sig=sig, why="transcript")])
    rt = r["step"]["retimed"]["captions"]
    assert rt["shortened"] >= 1 and rt["removed"] >= 1 and rt["retimed"] >= 1
    rows = {c["id"]: c for c in r["captions"]}
    cuts = [(a, b) for a, b, _ in r["state"]["cuts"]]
    kept = [W[i] for i in mi if not any(a <= (W[i]["t"] + W[i]["te"]) / 2 <= b for a, b in cuts)]
    from vstudio import cleanup as C
    assert rows[mid["id"]]["text"] == C.join_words(kept)
    assert len(kept) == len(mi) - 2 and W[mi[2]] not in kept and W[mi[3]] not in kept   # exactly the two words
    assert rows[full["id"]]["removed"] is True
    ops = {(o["op"], o.get("cue")) for o in r["step"]["ops"]}
    assert ("caption_text", mid["id"]) in ops and ("caption_remove", full["id"]) in ops
    u = O.undo(th, oid)
    rows = {c["id"]: c for c in u["captions"]}
    assert rows[mid["id"]]["text"] == mid["text"] and not rows[full["id"]]["removed"] and u["state"]["cuts"] == []


# --------------------------------------------------------------------------- zero crossings: no click at the join
@media
def test_cut_edges_on_zero_crossings_and_no_click(tmp_path, pz):
    w, oid = _adopt(tmp_path, pz["bed"], pz["bed_truth"])
    _set_burned(w, oid, True)                    # snap_captions: no join fade, the join is the raw cut
    W = pz["bed_truth"]
    a0, b0 = W[7]["te"] + 0.06, W[10]["te"] + 0.07          # a plain cut, inside the bed between words
    r = O.edit(w, oid, dict(op="cut", start=a0, end=b0, why="filler"))
    v = r["values"][0]
    assert v.get("zero_cross") is True
    a, b = v["cut"]
    src = r["output"]["file"]
    for t in (a, b):                              # the source crosses zero at both edges
        x, sr, t0 = O._pcm_window(src, t)
        i = (t - t0) * sr
        k = int(np.floor(i))
        val = x[k] + (x[k + 1] - x[k]) * (i - k)
        assert abs(val) < 0.02 * float(np.abs(x).max()) + 1e-4, (t, val)
    res = R.render(w, oid, quality="preview")
    from vstudio import audio as A
    y = A.decode_audio(res["targets"][0]["file"], sr=SR, channels=1)[:, 0]
    seg0 = r["timeline"]["segments"][0]
    j = int(round((seg0[1] - seg0[0]) * SR))
    dy = np.abs(np.diff(y))
    win = int(0.015 * SR)
    at_join = dy[j - win:j + win].max()
    bed = dy[int(0.05 * SR):int(0.3 * SR)].max()          # the bed's own largest sample step (lead, no words)
    assert at_join <= 2.0 * bed, (at_join, bed)                             # the join is not a click (unrefined: ~40x)


# --------------------------------------------------------------------------- flattened strategies
@media
def test_flattened_cut_strategy_and_burned_caption_snap(tmp_path, synth):
    w, oid = _work(tmp_path, synth)
    s = O.show(w, oid)
    assert s["caps"]["cut_strategy"] == "hard" and s["caps"]["burned_captions"] is False
    rec, doc = O._load(w, oid)
    st = doc.state()
    st = O.fold(st, dict(op="cut", start=2.0, end=2.5, why=""))
    tl = R.plan(rec, doc, st, R.targets_of(rec, st)[0], "preview")["timeline"]
    assert tl["join_fade"] == round(2 / 30, 4)                             # hard: a 2-frame audio fade at joins
    _set_burned(w, oid, True)
    s = O.show(w, oid)
    assert s["caps"]["cut_strategy"] == "snap_captions" and s["caps"]["burned_captions"] is True
    rec, doc = O._load(w, oid)
    assert "join_fade" not in R.plan(rec, doc, st, R.targets_of(rec, st)[0], "preview")["timeline"]
    W, sig = _words(w, oid)
    r = O.edit(w, oid, dict(op="cut", words=[4, 4], sig=sig, why="transcript"))   # 讲, mid-line
    assert [x["code"] for x in r["warnings"] if x["code"] == "cut-splits-burned-caption"]
    assert r["values"][0]["caption_snap"] is False
    gaps = O._caption_gaps(W)
    mids = [(x["t"] + x["te"]) / 2 for x in W]
    line = [i for i, m in enumerate(mids) if gaps[1][1] <= m <= gaps[2][0]]   # the second burned line
    r = O.edit(w, oid, dict(op="cut", words=[line[0], line[-1]], sig=sig, why="transcript"))
    assert not [x for x in r["warnings"] if x["code"] == "cut-splits-burned-caption"]
    assert r["values"][0]["caption_snap"] is True


# --------------------------------------------------------------------------- two targets, preview-edl parity
@media
def test_two_targets_same_duration_after_cut(tmp_path, pz):
    w, oid = _adopt(tmp_path, pz["video"], pz["truth"])
    W, sig = _words(w, oid)
    r = O.edit(w, oid, [dict(op="export_add", target="9:16"), dict(op="cut", words=[3, 5], sig=sig, why="transcript")])
    assert r["step"]["retimed"]["targets"] == ["primary", "douyin:vertical"]
    res = R.render(w, oid, quality="preview", targets=["all"])
    from vstudio import media as M
    durs = [M.probe(t["file"])["duration"] for t in res["targets"]]
    assert len(durs) == 2 and abs(durs[0] - durs[1]) < 0.1, durs
    assert abs(durs[0] - r["timeline"]["duration"]) < 0.15 and durs[0] < pz["dur"] - 1.0


@media
def test_preview_edl_parity_with_the_renderer(tmp_path, pz):
    w, oid = _adopt(tmp_path, pz["video"], pz["truth"])
    W, sig = _words(w, oid)
    drafts = [dict(op="cut", words=[5, 6], sig=sig, why="transcript"),
              dict(op="cut", gap=1, sig=sig),
              dict(op="cut", words=[99, 100], sig=sig),                     # bad: dropped, reported
              dict(op="cut", start=W[9]["t"] - 0.02, end=W[9]["te"] + 0.02, why="filler")]
    pe = O.preview_edl(w, oid, drafts)
    assert pe["ok"] and [x["index"] for x in pe["dropped"]] == [2]
    assert pe["dropped"][0]["error"]["code"] == "bad-param"
    assert [x["index"] for x in pe["ops"]] == [0, 1, 3] and pe["ops"][0]["describe"]["code"] == "op-cut"
    assert abs(pe["source_duration"] - pz["dur"]) < 0.1 and pe["duration"] < pe["source_duration"] - 1.0
    s = O.show(w, oid)
    assert s["history"]["undo"] == 0 and s["state"]["cuts"] == []           # nothing written
    r = O.edit(w, oid, [drafts[0], drafts[1], drafts[3]])
    rec, doc = O._load(w, oid)
    st = doc.state()
    dur = rec["info"]["duration"]
    assert pe["keep"] == O.Timeline(st, dur).segs == O.segments(st, dur)
    assert pe["keep"] == R.plan(rec, doc, st, R.targets_of(rec, st)[0], "preview")["timeline"]["segs"]
    assert pe["cuts"] == [[a, b] for a, b, _ in r["state"]["cuts"]]
    assert abs(pe["duration"] - r["timeline"]["duration"]) < 1e-6
    # the CLI verb answers the same thing (against the edited state now: empty draft list = current keep)
    c = _cli("preview-edl", "--project", w, "--output", oid, "--ops", json.dumps([]), "--json")
    j = json.loads(c.stdout)
    assert c.returncode == 0 and j["keep"] == pe["keep"] and j["dropped"] == [], c.stdout + c.stderr
    c = _cli("show", "--project", w, "--output", oid, "--json")
    j = json.loads(c.stdout)
    assert j["words_sig"] == sig and isinstance(j["marks"], list) and j["caps"]["cut_strategy"] == "hard"
    c = _cli("edit", "--project", w, "--output", oid, "--ops",
             json.dumps(dict(op="cut", words=[11, 12], sig=sig, why="transcript")), "--json")
    j = json.loads(c.stdout)
    assert c.returncode == 0 and j["step"]["retimed"] and  j["values"][0]["words"] == "最后总结", c.stdout + c.stderr
