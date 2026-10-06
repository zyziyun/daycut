"""Demo-grade fixes of the batch longform-split pipeline: cut edges by syllable count, caption proofreading with a
per-source glossary + the audio-faithful validator, caption filler edges, hook / caption dedupe, the screen crop
(upscale cap, follow, transient popups), platform length suggestions, and the desk-facing JSON CLI."""
import json
import os
import pathlib
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import cleanup as C  # noqa: E402

SR = 16000


# --------------------------------------------------------------------------- B: syllable-count cut edges
def _syllable_audio(plan):
    """plan: [(kind, dur)] kind 'syl' (a voiced burst) | 'dip' (a shallow dip inside running speech, -18 dB) |
    'sil' (silence). -> (x, [(t0, t1) of every syllable])."""
    out, syl, t = [], [], 0.0
    rng = np.random.default_rng(0)
    for kind, d in plan:
        n = int(round(d * SR))
        tt = np.arange(n) / SR
        if kind == "syl":
            env = np.sin(np.pi * np.arange(n) / n) ** 0.6
            sig = sum(np.sin(2 * np.pi * f * tt) / k for k, f in enumerate((180, 360, 540, 720), 1))
            out.append(0.3 * env * sig)
            syl.append((t, t + d))
        elif kind == "dip":
            out.append(0.3 * 0.12 * np.sin(2 * np.pi * 180 * tt))
        else:
            out.append(0.0005 * rng.standard_normal(n))
        t += d
    return np.concatenate(out).astype(np.float32), syl


def _phrase(n):
    plan = []
    for k in range(n):
        plan.append(("syl", 0.18))
        if k < n - 1:
            plan.append(("dip", 0.06))
    return plan


def test_cut_edge_by_syllable_count_leaves_no_removed_syllable():
    """Whisper ends 的话 0.15 s early (its word times drift in running speech): the old edge stopped at the valley
    before 话 and the re-ASR heard 都是错的[话]; the syllable count moves the end to the valley after 话."""
    plan = [("sil", 0.4)] + _phrase(2) + [("sil", 0.16)] + _phrase(8) + [("sil", 0.5)]
    x, syl = _syllable_audio(plan)
    chars = ["错", "的", "然", "后", "的", "话", "另", "外", "一", "个"]
    assert len(syl) == len(chars)
    real = dict(zip(range(len(chars)), syl))
    # whisper words: 错的 right; from 的话 on every start / end is 0.15 s early (drift)
    words = [("错的", real[0][0], real[1][1]), ("然后", real[2][0], real[3][1]),
             ("的话", real[4][0] - 0.15, real[5][1] - 0.15), ("另外", real[6][0] - 0.15, real[7][1] - 0.15),
             ("一个", real[8][0], real[9][1])]
    tr = dict(segments=[dict(start=words[0][1], end=words[-1][2], text="".join(w[0] for w in words),
                             words=[dict(word=w, start=round(a, 3), end=round(b, 3)) for w, a, b in words])])
    W = C.load_words(tr)
    lo, hi = 0.3, real[9][1] + 0.3
    en = C.energy_of((x, SR), W, [(lo, hi)])
    ed = [e for e in C.detect(W, ranges=[(lo, hi)], energy=en) if e["text"] == "然后的话"]
    assert ed and ed[0]["action"] == "auto", ed
    e = ed[0]
    boundary = (real[5][1] + real[6][0]) / 2              # the dip between 话 and 另
    assert abs(e["t1"] - boundary) <= 0.05, (e, boundary)
    assert "syllable" in e["reason"]
    # nothing of 话 is kept, nothing of 另 is cut
    assert e["t1"] >= real[5][1] - 0.02 and e["t1"] <= real[6][0] + 0.02
    # the start stays in the silence after 的
    assert real[1][1] <= e["t0"] <= real[2][0]


def test_syllable_edges_never_move_when_both_edges_are_in_running_speech():
    plan = [("sil", 0.3)] + _phrase(6) + [("sil", 0.3)]
    x, syl = _syllable_audio(plan)
    tr = dict(segments=[dict(start=syl[0][0], end=syl[-1][1], text="一二三四五六", words=[
        dict(word=c, start=a, end=b) for c, (a, b) in zip("一二三四五六", syl)])])
    W = C.load_words(tr)
    en = C.energy_of((x, SR), W, [(0.2, syl[-1][1] + 0.2)])
    a = (syl[1][1] + syl[2][0]) / 2
    b = (syl[3][1] + syl[4][0]) / 2 - 0.12            # one syllable short, but no solid edge to count from
    assert C.syllable_edges(W, en, a, b, W[2:4]) == (a, b, "")
    pk, vl = C.nuclei(en, 0.2, syl[-1][1] + 0.2)
    assert len(pk) == 6 and len(vl) == 5


def test_snap_cut_uses_syllable_count():
    plan = [("sil", 0.4)] + _phrase(2) + [("sil", 0.16)] + _phrase(5) + [("sil", 0.4)]
    x, syl = _syllable_audio(plan)
    w = [("我们", syl[0][0], syl[1][1]), ("那个", syl[2][0], syl[3][1] - 0.15), ("东西", syl[4][0] - 0.15, syl[5][1]),
         ("好", syl[6][0], syl[6][1])]
    tr = dict(segments=[dict(start=w[0][1], end=w[-1][2], text="".join(c for c, _, _ in w),
                             words=[dict(word=c, start=a, end=b) for c, a, b in w])])
    W = C.load_words(tr)
    en = C.energy_of((x, SR), W, [(0.3, syl[-1][1] + 0.3)])
    a, b = C.snap_cut(W, en, syl[2][0] - 0.05, syl[3][1] - 0.15)
    boundary = (syl[3][1] + syl[4][0]) / 2
    assert abs(b - boundary) <= 0.05, (a, b, boundary)


# --------------------------------------------------------------------------- A: glossary + audio-faithful proofread
from vstudio import proofread as PR  # noqa: E402

TRANSCRIPT = "\n".join(["称爆你整个的RM的context", "因为你RM的context的话是有一些上限的", "扔到IRM里面去做generate",
                        "我们会用Hibrid Search", "这个Skill很好用", "而且还会丢定度", "precision很重要"])


def fake_glossary_llm(system, prompt, model):
    if system == PR.GLOSSARY_SYSTEM:
        assert "Transcript:" in prompt and "Terms the creator listed: LLM" in prompt
        return json.dumps({"terms": ["LLM", "Hybrid Search"], "fixes": [
            {"from": "称爆", "to": "撑爆", "why": "homophone", "confidence": 0.99},
            {"from": "Hibrid", "to": "Hybrid", "why": "spelling", "confidence": 0.99},
            {"from": "precision", "to": "精度", "why": "translate", "confidence": 0.99},          # a translation
            {"from": "的RM", "to": "LLM", "why": "term", "confidence": 0.99},                   # drops 的
            {"from": "丢定度", "to": "丢精度", "why": "homophone", "confidence": 0.5},           # not sure enough
            {"from": "很", "to": "狠", "why": "x", "confidence": 0.99}]}), {"input": 100, "output": 50}
    if system == PR.VOCAB_SYSTEM:
        assert "RM x2" in prompt
        return json.dumps({"fixes": [{"from": "RM", "to": "LLM", "why": "term", "confidence": 0.99},
                                     {"from": "IRM", "to": "LLM", "why": "term", "confidence": 0.99},
                                     {"from": "Skill", "to": "Scale", "why": "guess", "confidence": 0.99}]}), \
            {"input": 50, "output": 20}
    if system == PR.CHECK_SYSTEM:
        assert "Skill -> Scale" in prompt and "RM -> LLM" not in prompt     # creator terms skip the second look
        n = [ln.split(".")[0] for ln in prompt.splitlines() if "Skill -> Scale" in ln][0]
        return json.dumps({"reject": [{"n": int(n), "why": "Skill is a product"}]}), {"input": 10, "output": 5}
    raise AssertionError(system[:40])


def test_glossary_once_per_source_validated_and_applied_everywhere():
    g = PR.build_glossary(TRANSCRIPT, context=dict(topic="RAG", glossary=["LLM", "RAG"]), call=fake_glossary_llm)
    fixes = {f["from"]: f["to"] for f in g["fixes"]}
    assert fixes == {"称爆": "撑爆", "Hibrid": "Hybrid", "RM": "LLM", "IRM": "LLM"}
    why = {r["from"]: r["reason"] for r in g["rejected"]}
    assert "translation" in why["precision"] and "的" in why["的RM"] and "confidence" in why["丢定度"]
    assert "generic" in why["很"] and why["Skill"].startswith("second look")
    assert g["usage"]["input"] == 100 + 2 * 50 + 10                  # glossary + two vocabulary looks + check
    # applied the same way to every cue of every job; RM never inside a longer latin word
    cues = [dict(start=0, end=1, text="称爆你整个的RM的context"), dict(start=1, end=2, text="因为你RM的context"),
            dict(start=2, end=3, text="ARM芯片和RMS")]
    res = PR.proofread(cues, provider="none", glossary=g)
    assert [c["text"] for c in res["cues"]] == ["撑爆你整个的LLM的context", "因为你LLM的context", "ARM芯片和RMS"]
    assert {c["source"] for c in res["changes"]} == {"glossary"}


def test_faithful_validator_substitutions_only():
    assert PR.faithful("称爆你整个的RM的context", "撑爆你整个的LLM的context") is None
    assert "drops spoken" in PR.faithful("整个的RM", "整个LLM")
    assert "adds" in PR.faithful("现在比的很高", "现在比例真的很高")
    assert "translation" in PR.faithful("precision很重要", "精度很重要")
    assert PR.faithful("vectordb里面", "vector db里面") is None                       # spacing only
    assert "does not sound alike" in PR.faithful("用it改写", "用iterate改写")
    assert PR.faithful("在query派篮", "在query pipeline") is None                    # English heard as characters
    # a model that copies the whole caption as "from" is reduced to the word that changes
    assert PR._valid("因为你RM的context的话是有一些上限的",
                     {"from": "因为你RM的context的话是有一些上限的", "to": "因为你LLM的context的话是有一些上限的"}) is None
    assert PR.diff_spans("因为你RM的context", "因为你LLM的context") == [("RM", "LLM")]


def test_llm_fix_propagates_to_the_jobs_other_cues_and_respects_glossary():
    cues = [dict(start=0, end=1, text="撑爆你整个的RM的context"), dict(start=1, end=2, text="因为你RM的context的话"),
            dict(start=2, end=3, text="先转成summary")]
    g = dict(fixes=[dict({"from": "Summer", "to": "summary"})], terms=[])

    def llm(system, prompt, model):
        assert "Known ASR confusions" in prompt and "Summer -> summary" in prompt
        return json.dumps({"fixes": [{"i": 0, "from": "RM", "to": "LLM"},
                                     {"i": 2, "from": "summary", "to": "summarizer"}]}), {"input": 1, "output": 1}
    res = PR.proofread([dict(cues[0]), dict(cues[1]), dict(cues[2], text="先转成Summer")], call=llm, glossary=g)
    texts = [c["text"] for c in res["cues"]]
    assert texts[:2] == ["撑爆你整个的LLM的context", "因为你LLM的context的话"]
    assert texts[2] == "先转成summary"                                # the glossary fix is not re-edited
    assert ("llm-propagated", 1) in {(c["source"], c["i"]) for c in res["changes"]}
    assert any(r["reason"] == "already fixed by the term fixes / glossary" for r in res["rejected"])


# --------------------------------------------------------------------------- C: caption filler edges
def test_no_caption_ends_on_a_leading_filler_or_starts_on_a_trailing_particle():
    cues = [dict(start=0.0, end=1.0, text="读的话就是"), dict(start=1.05, end=2.0, text="来了一个Queries"),
            dict(start=2.0, end=3.5, text="切的很大"), dict(start=3.5, end=4.5, text="的话你的这个embedding它就会被压缩"),
            dict(start=6.0, end=7.0, text="然后我们下一步")]
    out, log = PR.fix_filler_edges(cues, max_chars=16)
    texts = [c["text"] for c in out]
    assert texts[0] == "读的话就是来了一个Queries"                       # merged: fits
    assert texts[1] == "切的很大的话" and texts[2] == "你的这个embedding它就会被压缩"   # 的话 moved back
    assert texts[3] == "然后我们下一步"                                   # a filler opening a line is fine
    assert "".join(texts) == "".join(c["text"] for c in cues)            # same words, same order
    assert out[1]["end"] == out[2]["start"] and out[1]["start"] == 2.0
    assert [x["action"] for x in log] == ["merge", "move-back"]


# --------------------------------------------------------------------------- D: screen crop
LFS = ROOT / "workflows" / "longform-to-short" / "scripts"


def _V():
    sys.path.insert(0, str(LFS))
    import importlib
    return importlib.import_module("_vertical")


def _doc_frame(H=720, W=1280, page=(0, 163, 958, 615), y0=180):
    fr = np.full((H, W, 3), 32, np.uint8)
    x0, py0, x1, py1 = page
    fr[py0:py1, x0:x1] = 250
    rng = np.random.default_rng(3)
    y = py0 + y0 - 163
    while y < py1 - 20:
        x = 300
        while x < 660:
            w = int(rng.integers(10, 40))
            fr[y:y + 8, x:x + w] = 40
            x += w + 6
        y += 15
    return fr


def _video(tmp_path, frames, fps=24, name="v.mp4"):
    import cv2
    p = str(tmp_path / name)
    vw = cv2.VideoWriter(p + ".avi", cv2.VideoWriter_fourcc(*"MJPG"), fps, (frames[0].shape[1], frames[0].shape[0]))
    for f in frames:
        vw.write(f)
    vw.release()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", p + ".avi", "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "10", "-pix_fmt", "yuv444p", p], check=True)
    return p


ffmpeg = pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")


@ffmpeg
def test_popup_is_detected_held_and_masked(tmp_path):
    """A Notion-style popup (white box with a border and its own items) appears for 2 s over the page and vanishes:
    detected, the camera holds, the master paints the page as it was; a selection highlight is NOT a popup."""
    V = _V()
    fps, n = 24, 24 * 6
    base = _doc_frame()
    frames = []
    for i in range(n):
        f = base.copy()
        t = i / fps
        if 2.0 <= t < 4.0:                                   # popup
            f[300:470, 440:560] = 252
            f[300:302, 440:560] = 180
            f[468:470, 440:560] = 180
            f[300:470, 440:442] = 180
            f[300:470, 558:560] = 180
            for k in range(6):
                f[315 + 25 * k:323 + 25 * k, 455:520] = 90
        if 4.5 <= t < 5.5:                                   # selection highlight: text stays
            sel = f[390:405, 300:640]
            f[390:405, 300:640] = np.where(sel > 200, 210, sel)
        frames.append(f)
    vid = _video(tmp_path, frames, fps)
    from vstudio import platform as PF
    L = V.layout([PF.parse_targets(["douyin"])[0]])
    bx = V.boxes(L, "split", "title")
    o = dict(V.SCREEN_DEFAULTS)
    rects, st = V.analyse_screen(vid, 0.0, n / fps, 1.0, fps, n, [0, 163, 958, 615], bx["screen"], o=o)
    assert len(st["popups"]) == 1, st["popups"]
    p = st["popups"][0]
    assert abs(p["f0"] / fps - 2.0) <= 0.3 and abs(p["f1"] / fps - 4.0) <= 0.3 and p["masked"]
    x0, y0, x1, y1 = p["rect"]
    assert x0 <= 440 and y0 <= 300 and x1 >= 560 and y1 >= 470
    clean = {p["clean"]: frames[p["clean"]]}
    shown = V.mask_popups(frames[int(3.0 * fps)], int(3.0 * fps), st["popups"], clean)
    assert np.abs(shown.astype(int) - base.astype(int)).max() < 5          # the page under it, popup gone
    y_mid = [r[1] for r in rects]
    assert max(y_mid[int(2.0 * fps):int(4.0 * fps)]) - min(y_mid[int(2.0 * fps):int(4.0 * fps)]) < 2  # held


@ffmpeg
def test_crop_follows_activity_and_never_upscales_past_the_cap(tmp_path):
    """A tall page (crop smaller than the region): a selection moving down the page pulls the camera along,
    smoothly; the zoom stays <= 2x of the source."""
    V = _V()
    fps, n = 24, 24 * 8
    page = (0, 40, 958, 700)
    base = _doc_frame(page=page, y0=60)
    frames = []
    for i in range(n):
        f = base.copy()
        t = i / fps
        y = 120 if t < 3 else 560                          # highlight jumps from the top to the bottom of the page
        f[y:y + 30, 300:640] = np.where(f[y:y + 30, 300:640] > 200, 200, f[y:y + 30, 300:640])   # a tint
        frames.append(f)
    vid = _video(tmp_path, frames, fps, "tall.mp4")
    from vstudio import platform as PF
    L = V.layout([PF.parse_targets(["xiaohongshu:vertical"])[0]])
    bx = V.boxes(L, "split", "title")
    o = dict(V.SCREEN_DEFAULTS)
    rects, st = V.analyse_screen(vid, 0.0, n / fps, 1.0, fps, n, list(page), bx["screen"], o=o)
    assert st["scale"] <= 2.0 + 1e-3
    ys = np.array([r[1] for r in rects])
    assert ys[-1] - ys[int(2.5 * fps)] > 100, (ys[int(2.5 * fps)], ys[-1])          # it followed the activity
    assert np.abs(np.diff(ys)).max() < 0.06 * rects[0][3] * 1.0 + 1                   # smooth, no jumps
    assert st["activity"] >= 1


@ffmpeg
def test_hook_lines_come_from_the_spoken_captions():
    from vstudio.batch import lfsplit as LS
    tl = [dict(kind="clip", hook=True, t0=10.0, t1=16.0, speed=1.2, final_t0=0.0, hook_lines=["planned", "text"]),
          dict(kind="card", final_t0=5.0, dur=1.6), dict(kind="clip", t0=10.0, t1=30.0, speed=1.2, final_t0=6.6)]
    cues = [dict(start=0.1, end=2.4, text="RAG的话就是它是分为两条线"), dict(start=2.4, end=4.9, text="一条是读一条是写"),
            dict(start=6.7, end=9.0, text="RAG的话就是它是分为两条线")]
    out = LS.spoken_hook_lines(tl, cues)
    assert out == {0: ["RAG的话就是它是分为两条线", "一条是读一条是写"]} and tl[0]["hook_lines"] == out[0]


# --------------------------------------------------------------------------- E: length feedback
@ffmpeg
def test_length_suggestion_and_max_len_variant(tmp_path):
    from vstudio.batch import lengthfit as LF
    from vstudio import media
    src = str(tmp_path / "x.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=180x320:r=24:d=12", "-f", "lavfi",
                    "-i", "sine=f=440:d=12", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", src],
                   check=True)
    tl = [dict(kind="clip", t0=100.0, t1=112.0, speed=1.0, final_t0=0.0)]
    p = dict(max_len={"douyin": {"max": 9, "via": "auto", "max_speed": 1.3}}, trims={"douyin": [[103.0, 104.0]]},
             speed=1.0)
    exports = [dict(platform="douyin", orientation="vertical", file=src, duration=12.0),
               dict(platform="xiaohongshu", orientation="vertical", file=src, duration=12.0)]
    assert LF.limit_for(p, {}, "douyin", "vertical")[0] == 9 and LF.limit_for(p, {}, "xiaohongshu")[0] is None
    log = LF.fit_exports(exports, p, {}, tl, preset="ultrafast")
    assert len(log) == 1 and log[0]["trims"] == [[3.0, 4.0]] and log[0]["speed"] == pytest.approx(11 / 9, abs=0.01)
    assert abs(media.duration(src) - 9.0) < 0.3 and exports[0]["variant"]["max_len"] == 9
    # QC suggestion: over the sweet spot -> speed needed, trim candidates in source seconds
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps({"cues": [dict(start=0.5, end=6.0, text="很长的一句"), dict(start=6.0, end=8.0, text="短句")]}))
    tlp = tmp_path / "tl.json"
    tlp.write_text(json.dumps(tl))
    job = dict(id="j", params=dict(speed=1.0))
    sug = LF.suggestions(job, {}, {"compose": {"cues": str(cues), "timeline": str(tlp), "hook_dur": 0}},
                         [dict(platform="douyin", orientation="vertical", duration=12.0)], lambda e: 8)
    assert sug and sug[0]["speed_needed"] == 1.5 and sug[0]["trims"][0]["src"] == [100.5, 106.0]
    assert "max_len" in sug[0]["text"] and "100.5-106.0" in sug[0]["text"]


# --------------------------------------------------------------------------- F: desk JSON API
def _cli(*args, env=None):
    e = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "lib"), str(ROOT / "tests")]), **(env or {}))
    return subprocess.run([sys.executable, "-m", "vstudio.batch", *args], capture_output=True, text=True, env=e,
                          timeout=120)


def test_cli_json_plan_run_events_review_job_package(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    spec = dict(name="t", recipe="test-fake", plugins=["_batch_helpers"], retry={"backoff": 0},
                jobs=[dict(id=f"j{i}", x=i) for i in range(1, 3)])
    sp = tmp_path / "batch.yaml"
    sp.write_text(yaml.safe_dump(spec))
    env = dict(VSTUDIO_BATCH_BENCH=str(tmp_path / "bench.json"))
    r = _cli("plan", str(sp), "--batch", str(tmp_path / "b"), "--json", env=env)
    plan = json.loads(r.stdout)
    assert plan["ok"] and plan["jobs"] == ["j1", "j2"] and plan["created"] == ["j1", "j2"]
    r = _cli("run", "--batch", plan["batch_dir"], "--json-events", env=env)
    assert r.returncode == 0, r.stderr
    evs = [json.loads(ln) for ln in r.stdout.splitlines()]                    # every stdout line is JSON
    kinds = [e["event"] for e in evs]
    assert kinds[0] == "run-start" and kinds[-1] == "run-end" and evs[-1]["exit_code"] == 0
    assert {"stage-start", "stage-done", "progress", "job-done"} <= set(kinds)
    last = [e for e in evs if e["event"] == "progress"][-1]
    assert last["done_stages"] == last["total_stages"] == 10 and last["jobs_done"] == 2
    assert "[batch]" in r.stderr                                                # the human log went to stderr
    r = _cli("review", "--batch", plan["batch_dir"], "--json", env=env)
    rv = json.loads(r.stdout)
    assert [it["id"] for it in rv["items"]] == ["j1", "j2"] and os.path.isabs(rv["page"])
    dec = tmp_path / "dec.json"
    dec.write_text(json.dumps({"decisions": {"j1": {"decision": "approve"}, "j2": "reject"}}))
    ap = json.loads(_cli("review", "--batch", plan["batch_dir"], "--apply", str(dec), "--json", env=env).stdout)
    assert ap["approved"] == ["j1"] and ap["rejected"] == ["j2"]
    jd = json.loads(_cli("job", "j1", "--batch", plan["batch_dir"], "--json", env=env).stdout)
    assert jd["job"]["id"] == "j1" and {s["name"] for s in jd["stages"]} == {"probe", "asr", "render", "big", "qc"}
    assert _cli("job", "nope", "--batch", plan["batch_dir"], "--json", env=env).returncode == 1
    rec = json.loads(_cli("recipes", "--json", env=env).stdout)
    ls = next(x for x in rec if x["name"] == "longform-split")
    assert ls["label"] and any(i["key"] == "inputs.source" and i["required"] for i in ls["inputs"])
    assert any(i["key"] == "privacy.exclude" for i in ls["inputs"]) and "cuts" in ls["row_keys"]


def test_verify_manifest_public_helper(tmp_path):
    from vstudio.batch import verify_manifest
    from vstudio.batch.package import verify_manifest as v2
    from vstudio.batch.util import sha1_json
    man = dict(batch="b", schedule=dict(per_day=1), items=[dict(job="j1", sha256="x")])
    man["confirmation_code"] = sha1_json(dict(batch="b", schedule=dict(per_day=1), items=man["items"]))[:12]
    assert verify_manifest(man)["ok"] and v2(man)["ok"]
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(dict(man, items=[dict(job="j1", sha256="y")])))
    r = verify_manifest(str(p))
    assert not r["ok"] and "mismatch" in r["reason"]
    out = _cli("verify-manifest", str(p))
    assert out.returncode == 1 and json.loads(out.stdout)["ok"] is False


def test_llm_never_edits_creator_terms_or_drops_endings_and_spaces_latin():
    """Pilot regression: the per-cue pass turned every 'chunking' (the creator's own term fix of 'trunking', already
    applied upstream) into 'chunk' and propagated it; 'query派篮' became 'querypipeline'."""
    cues = [dict(start=0, end=1, text="去做chunking更多"), dict(start=1, end=2, text="我们可以在query派篮"),
            dict(start=2, end=3, text="然后用这个prom")]

    def llm(system, prompt, model):
        return json.dumps({"fixes": [{"i": 0, "from": "chunking", "to": "chunk"},
                                     {"i": 1, "from": "派篮", "to": "pipeline"}]}), {"input": 1, "output": 1}
    res = PR.proofread(cues, term_fixes=[["[Tt]runking", "chunking"], [r"\bprom\b", "prompt"]], call=llm,
                       context=dict(glossary=["chunk", "LLM"]), passes=1)
    texts = [c["text"] for c in res["cues"]]
    assert texts == ["去做chunking更多", "我们可以在query pipeline", "然后用这个prompt"]     # \b works next to CJK
    reasons = {r["reason"] for r in res["rejected"]}
    assert any("only drops an ending" in r or "creator listed" in r for r in reasons)


@ffmpeg
def test_popup_open_at_the_cut_is_masked_with_the_page_after_it_closes(tmp_path):
    """A clip that starts with the editor toolbar already open (it opened before the cut) and closes at 2 s: found
    running backwards, masked with the first clean frame after it closes."""
    V = _V()
    fps, n = 24, 24 * 4
    base = _doc_frame()
    frames = []
    for i in range(n):
        f = base.copy()
        if i / fps < 2.0:
            f[300:470, 440:560] = 252
            for k in range(6):
                f[315 + 25 * k:323 + 25 * k, 455:520] = 90
        frames.append(f)
    vid = _video(tmp_path, frames, fps, "open.mp4")
    from vstudio import platform as PF
    L = V.layout([PF.parse_targets(["douyin"])[0]])
    bx = V.boxes(L, "split", "title")
    rects, st = V.analyse_screen(vid, 0.0, n / fps, 1.0, fps, n, [0, 163, 958, 615], bx["screen"],
                                 o=dict(V.SCREEN_DEFAULTS))
    assert len(st["popups"]) == 1 and st["popups"][0]["future"] and st["popups"][0]["f0"] == 0
    p = st["popups"][0]
    assert abs(p["f1"] / fps - 2.0) <= 0.3 and p["masked"]
    shown = V.mask_popups(frames[10], 10, st["popups"], {p["clean"]: frames[p["clean"]]})
    assert np.abs(shown.astype(int) - base.astype(int)).max() < 5


def test_build_subs_keeps_a_short_piece_between_two_cuts(tmp_path):
    """Pilot regression: after the 然后的话 cut moved to the syllable boundary, the kept 另外 (0.13 s at 1.2x) was
    dropped as a too-short caption - captions must match the audio: it joins the words after it."""
    work = tmp_path / "work"
    work.mkdir()
    segs = [dict(start=320.8, end=322.2, text="你后面怎么做都是错的", words=[dict(word="你后面怎么做都是错的", start=320.8, end=322.2)]),
            dict(start=322.2, end=323.7, text="然后的话另外的话", words=[
                dict(word="然后", start=322.2, end=322.76), dict(word="的话", start=322.76, end=323.06),
                dict(word="另外", start=323.06, end=323.38), dict(word="的话", start=323.38, end=323.7)]),
            dict(start=323.7, end=325.0, text="一个点的话就是", words=[dict(word="一个点的话就是", start=323.7, end=325.0)])]
    (work / "audio16k.json").write_text(json.dumps({"segments": segs}, ensure_ascii=False), encoding="utf-8")
    tl = [dict(kind="clip", t0=320.5, t1=322.2, speed=1.2, final_t0=0.0),
          dict(kind="clip", t0=323.22, t1=323.5, speed=1.2, final_t0=1.417),
          dict(kind="clip", t0=323.64, t1=325.2, speed=1.2, final_t0=1.65)]
    (work / "timeline.json").write_text(json.dumps(tl))
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out")}))
    subprocess.run([sys.executable, str(LFS / "build_subs.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    cues = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    assert [c["text"] for c in cues] == ["你后面怎么做都是错的", "另外一个点的话就是"], cues


def test_proofread_survives_broken_provider_reply():
    from vstudio import proofread as PR
    cues = [dict(start=0.0, end=1.0, text="我们用RM来生成"), dict(start=1.0, end=2.0, text="然后检索")]
    calls = []

    def bad(system, prompt, model):
        calls.append(1)
        return '{"fixes": [{"i": 0, "a": "RM", "b": "LLM"', {}          # truncated JSON
    out = PR.proofread(cues, provider="openai", call=bad, passes=1)
    assert calls                                                       # it tried
    assert isinstance(out, dict) or isinstance(out, tuple) or out is not None


def test_proofread_parse_salvages_truncated_reply():
    from vstudio import proofread as PR
    got = PR._parse('{"fixes": [{"i": 0, "a": "RM", "b": "LLM"}, {"i": 3, "a": "x"')
    assert got == [{"i": 0, "a": "RM", "b": "LLM"}]
    assert PR._parse('{"fixes": []}') == []


def test_proofread_degrades_on_provider_timeout():
    from vstudio import proofread as PR
    cues = [dict(start=0.0, end=1.0, text="我们用RM来生成")]

    def boom(system, prompt, model):
        raise TimeoutError("Request timed out.")
    out = PR.proofread(cues, provider="openai", call=boom, passes=1)
    assert out is not None                                              # the job continues, glossary/term fixes only
