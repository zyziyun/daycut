"""Confirm load: the cleanup confirm policy (rules + learned per persona), batch bulk answers, caption-fix guess
flags, and the 2 fps output scan for editor popups still visible in a rendered vertical video. All synthetic."""
import json
import os
import pathlib
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from vstudio import cleanup as C  # noqa: E402
from vstudio import proofread as PR  # noqa: E402

CONNECTOR = "connector at a sentence start: often fine, confirm by ear"


@pytest.fixture(autouse=True)
def policy_file(tmp_path, monkeypatch):
    p = tmp_path / "cfg" / "cleanup_policy.json"
    monkeypatch.setenv("VSTUDIO_CLEANUP_POLICY", str(p))
    return p


def _words(spec):
    """[(text, start, end)] -> load_words dicts (a word ending in 。 ends a sentence)."""
    return C.load_words([(w, a, b) for w, a, b in spec])


def _seq(tokens, t=0.0, dur=0.2, gap=0.02):
    out = []
    for tok in tokens:
        if tok == "|":                                  # a pause
            t += 0.4
            continue
        out.append((tok, round(t, 3), round(t + dur, 3)))
        t += dur + gap
    return out


def _edit(eid, W, i, j, kind, reason, conf, text=None, **kw):
    return dict(id=eid, t0=W[i]["t"], t1=W[j]["te"], kind=kind, text=text or "".join(w["w"] for w in W[i:j + 1]),
                confidence=conf, action="confirm", reason=reason, before="", after="", words=list(range(i, j + 1)), **kw)


# --------------------------------------------------------------------------- policy rules
def test_connector_with_a_complete_clause_is_approved_a_fragment_stays_a_question():
    W = _words(_seq(["讲", "完", "了。", "|", "然后", "我们", "可以", "把", "这个", "存", "下来。", "|", "然后", "是", "pass。"]))
    i1 = next(k for k, w in enumerate(W) if w["w"] == "然后")
    i2 = max(k for k, w in enumerate(W) if w["w"] == "然后")
    E = [_edit(1, W, i1, i1, "filler", CONNECTOR, 0.4), _edit(2, W, i2, i2, "filler", CONNECTOR, 0.4)]
    assert C.edit_class(E[0]) == "filler/connector"
    r = C.apply_policy(E, W)
    assert E[0]["action"] == "auto" and E[0]["base_action"] == "confirm" and "complete clause" in E[0]["policy"]["rule"]
    assert E[1]["action"] == "confirm" and "policy" not in E[1]               # '是 pass' is not a clause on its own
    assert r == dict(auto=1, keep=0, confirm=1)
    assert C.policy_counts(E) == dict(asked=1, auto=1, keep=0)
    C.apply_policy(E, W)                                                     # idempotent
    assert [e["action"] for e in E] == ["auto", "confirm"]


def test_lead_filler_before_a_copula_object_stays_a_question():
    W = _words(_seq(["latency", "|", "就是", "一个", "用户", "感知", "的", "指标。"]))
    k = next(i for i, w in enumerate(W) if w["w"] == "就是")
    e = _edit(1, W, k, k, "filler", "semantic filler (pause before)", 0.55)
    assert C.edit_class(e) == "filler/lead"
    C.apply_policy([e], W)
    assert e["action"] == "confirm"
    W2 = _words(_seq(["层面", "|", "就是", "这", "是", "一条", "pipeline。"]))
    k2 = next(i for i, w in enumerate(W2) if w["w"] == "就是")
    e2 = _edit(1, W2, k2, k2, "filler", "semantic filler (pause before)", 0.55)
    C.apply_policy([e2], W2)
    assert e2["action"] == "auto"


def _merged(front, dip, off=0.0):
    d0 = 10.0 + front
    d1 = d0 + dip
    return dict(id=1, t0=10.0, t1=round(d1 + off, 3), kind="filler-merged", text="我们", confidence=0.45,
                action="confirm", before="", after="", words=[], patch=[10.0, round(d1 + off, 3)],
                reason=f"'我们' is 1.20s: {front:.2f}s of sound, a dip at {d0:.2f}-{d1:.2f}s, then the word - a "
                       f"filler/restart merged into it; cut up to {d1 + off:.2f}s (listen)")


def test_merged_filler_short_sound_and_clear_dip_is_approved_shallow_dip_kept_long_sound_asked():
    ok, shallow, long_front = _merged(0.15, 0.40), _merged(0.15, 0.06), _merged(0.55, 0.40)
    off = _merged(0.15, 0.40, off=0.3)                                       # cut point not on the rise
    E = [ok, shallow, long_front, off]
    C.apply_policy(E, [])                                                    # facts parsed back out of the reason
    assert [e["action"] for e in E] == ["auto", "keep", "confirm", "confirm"]
    f = dict(front=0.1, d0=1.0, d1=1.3, cut_to=1.3)                          # new EDLs carry the facts
    e = dict(_merged(0.9, 0.05), feat=f)
    C.apply_policy([e], [])
    assert e["action"] == "auto"


def test_parallel_phrase_restart_is_kept_a_real_restart_is_asked():
    W = _words(_seq(["两条", "线", "一条", "是", "读", "一条", "是", "写。"]))
    par = _edit(1, W, 2, 4, "restart", "starts '一条是', breaks off, restarts as '一条是写'", 0.62)
    W2 = _words(_seq(["你", "召回", "完了", "之后", "可能", "你", "召回", "了", "一个。"]))
    real = _edit(1, W2, 0, 4, "restart", "starts '你召回', breaks off, restarts as '你召回了一个'", 0.62)
    C.apply_policy([par], W)
    C.apply_policy([real], W2)
    assert par["action"] == "keep" and "parallel" in par["policy"]["rule"]
    assert real["action"] == "confirm"


def test_real_word_classes_are_kept_and_retakes_always_asked(policy_file):
    W = _words(_seq(["这个", "模型", "很", "好。"]))
    det = _edit(1, W, 0, 0, "filler", "sentence-initial determiner before '模型' (这个模型): usually a real word", 0.25)
    rt = _edit(2, W, 0, 3, "retake", "sentence said again 2.0s later (similarity 0.70): keep the last take", 0.6)
    C.apply_policy([det, rt], W)
    assert det["action"] == "keep" and rt["action"] == "confirm"
    C.learn([rt] * 1, approve={2})                                           # even a creator who always cuts them
    for _ in range(20):
        C.learn([rt], approve={2})
    rt2 = dict(rt, action="confirm")
    rt2.pop("base_action", None)
    C.apply_policy([rt2], W)
    assert rt2["action"] == "confirm"                                        # never_approve


# --------------------------------------------------------------------------- learning
def test_learned_answers_persist_per_persona_and_change_the_policy(policy_file):
    W = _words(_seq(["这个", "|", "东西", "就", "没有", "办法。"]))
    drawn = lambda eid: _edit(eid, W, 0, 0, "filler", "semantic filler (drawn out)", 0.45)   # noqa: E731
    e = drawn(1)
    C.apply_policy([e], W)
    assert e["action"] == "confirm" and C.edit_class(e) == "filler/drawn"
    for _ in range(8):                                                        # the creator keeps saying yes
        C.learn([drawn(1)], approve={1})
    d = json.loads(policy_file.read_text(encoding="utf-8"))
    st = d["personas"][C.persona_key()]["stats"]
    assert st["filler/drawn"] == [8.0, 0.0] and st["filler/drawn|这个"] == [8.0, 0.0]
    assert str(policy_file).startswith(str(policy_file.parents[1]))          # outside the repo (tmp here)
    e2 = drawn(1)
    C.apply_policy([e2], W)
    assert e2["action"] == "auto" and "creator history" in e2["policy"]["rule"]
    # another persona has its own history
    assert C.load_policy(persona="someone-else")["stats"] == {}
    # a creator who keeps a policy cut: counted as kept, the class swings back
    for _ in range(30):
        C.learn([dict(e2)], keep={1})
    e3 = drawn(1)
    C.apply_policy([e3], W)
    assert e3["action"] != "auto"


def test_implicit_keep_counts_only_shown_questions(policy_file):
    W = _words(_seq(["讲", "完", "了。", "|", "然后", "是", "pass。", "|", "然后", "我们", "去", "看", "代码。"]))
    ks = [k for k, w in enumerate(W) if w["w"] == "然后"]
    E = [_edit(1, W, ks[0], ks[0], "filler", CONNECTOR, 0.4), _edit(2, W, ks[1], ks[1], "filler", CONNECTOR, 0.4)]
    C.apply_policy(E, W)                                                     # 2 is answered (auto), 1 is shown
    C.learn(E, approve=set(), keep={99})                                     # a reply was given, 1 not approved
    st = C.load_policy()["stats"]
    assert st["filler/connector"] == [0.0, 0.5]


def test_detect_applies_the_policy_only_when_on():
    spec = _seq(["我们", "讲", "完", "了。"]) + _seq(["然后", "我们", "来", "看", "第二", "部分。"], t=1.4)
    W = _words(spec)
    off = C.detect(W, profile="tight")
    on = C.detect(W, profile="tight", overrides=dict(policy=True))
    c_off = [e for e in off if e["text"] == "然后"]
    c_on = [e for e in on if e["text"] == "然后"]
    assert c_off and c_off[0]["action"] == "confirm"
    assert c_on and c_on[0]["action"] == "auto" and c_on[0]["base_action"] == "confirm"
    assert C.settings("tight")["policy"] is False


# --------------------------------------------------------------------------- batch review: view, bulk, learning
def _batch(tmp_path):
    from vstudio.batch.store import Store
    W = _words(_seq(["讲", "完", "了。", "|", "然后", "我们", "可以", "存", "下来。", "|", "然后", "是", "pass。"]))
    ks = [k for k, w in enumerate(W) if w["w"] == "然后"]
    E = [_edit(1, W, ks[0], ks[0], "filler", CONNECTOR, 0.4), _edit(2, W, ks[1], ks[1], "filler", CONNECTOR, 0.4),
         _merged(0.6, 0.3), dict(_merged(0.6, 0.3), id=4)]
    E[2]["id"] = 3
    edl = dict(words=[dict(w=w["w"], t=w["t"], te=w["te"], seg=w["seg"], end=w["end"]) for w in W], edits=E,
               ranges=[[0, 10]], settings={})
    bdir = tmp_path / "b"
    st = Store(str(bdir), create=True)
    st.set_meta("spec", {"name": "t"})
    edl_p = tmp_path / "body.cleanup.json"
    edl_p.write_text(json.dumps(edl, ensure_ascii=False), encoding="utf-8")
    rep = tmp_path / "proofread.json"
    rep.write_text(json.dumps(dict(provider="custom", changes=[
        dict(i=0, start=1.0, before="现在比的很高", after="现在壁垒很高", source="llm", why="sound-alike",
             diff=[["比的", "壁垒"]]),
        dict(i=1, start=2.0, before="Rewanking", after="reranking", source="glossary", why="glossary")])),
        encoding="utf-8")
    for jid in ("ep01", "ep02"):
        st.upsert_job(dict(id=jid, recipe="longform-split", item=jid, params=dict(title=jid), state="done"))
        st.set_stage(jid, "cleanup", state="done", out=dict(body=str(edl_p)))
        st.set_stage(jid, "proofread", state="done", out=dict(report=str(rep)))
    st.close()
    return str(bdir)


def test_review_shows_the_policy_view_bulk_buttons_and_yellow_guesses(tmp_path, monkeypatch):
    table = {"比": "bi", "的": "de", "壁": "bi", "垒": "lei", "很": "hen", "高": "gao"}
    monkeypatch.setattr(PR, "_PINYIN_FN", lambda s: [table[c] for c in s])
    from vstudio.batch import review
    b = _batch(tmp_path)
    r = review.generate(b)
    assert r["confirm_edits"] == 2 * 3                                      # edit 1 answered by the policy
    assert r["policy"] == dict(asked=6, auto=2, keep=0, pending=2)
    assert r["caption_guesses"] == 2
    items = json.loads((pathlib.Path(b) / "review" / "items.json").read_text(encoding="utf-8"))
    assert [e["id"] for e in items[0]["confirm"]] == [2, 3, 4]
    assert items[0]["confirm"][1]["cls"] == "filler-merged"
    g = [c for c in items[0]["captions"]["changes"] if c["source"] == "llm"][0]
    assert g["guess"] and "weak sound match" in g["support"]
    assert not [c for c in items[0]["captions"]["changes"] if c["source"] == "glossary"][0]["guess"]
    page = (pathlib.Path(b) / "review" / "index.html").read_text(encoding="utf-8")
    assert 'id="bulk"' in page and "confirm_kinds" in page and "accept_policy" in page and ".cap.guess" in page
    md = (pathlib.Path(b) / "review" / "decisions_needed.md").read_text(encoding="utf-8")
    assert "<mark>**GUESS**</mark>" in md and "`filler-merged` (4)" in md and "Confirm policy answered 2" in md


def test_apply_confirm_kinds_and_accept_policy_become_replies_and_are_learned(tmp_path, policy_file):
    from vstudio.batch import review
    from vstudio.batch.store import Store
    b = _batch(tmp_path)
    r = review.apply_decisions(b, json.dumps({"confirm_kinds": {"ep01": ["filler-merged"]}, "accept_policy": True,
                                              "cleanup": {"ep02": "保留 2"}}))
    assert r["bulk"]["ep01"] == [1, 3, 4] and r["bulk"]["ep02"] == [1]
    st = Store(b)
    try:
        p1, p2 = st.job("ep01")["params"], st.job("ep02")["params"]
        assert C.parse_reply(p1["cleanup_reply"])["approve"] == {1, 3, 4}
        assert C.parse_reply(p2["cleanup_reply"]) == dict(approve={1}, keep={2}, all_confirm=False)
        assert st.job("ep01")["state"] == "planned"
    finally:
        st.close()
    stats = C.load_policy()["stats"]
    assert stats["filler-merged"][0] == 2.0                                  # bulk yes counted (ep01: 3, 4)
    assert stats["filler/connector"] == [0.0, 1.0]                           # ep02 kept 2; the accepted policy cut 1
    assert r["learned"] >= 3                                                 # is not evidence
    # kinds as a plain list match sub-classes: "filler" -> filler/connector. The kept connector above was learned:
    # the policy no longer cuts edit 1 on its own, so it is a question again (and bulk-confirmed here)
    b2 = _batch(tmp_path / "x")
    r2 = review.apply_decisions(b2, {"confirm_kinds": ["filler"]})
    assert r2["bulk"] == {"ep01": [1, 2], "ep02": [1, 2]}


# --------------------------------------------------------------------------- caption guesses
def test_guess_flags_use_glossary_and_sound_alike(monkeypatch):
    table = {"比": "bi", "的": "de", "壁": "bi", "垒": "lei", "纹": "wen", "文": "wen"}
    monkeypatch.setattr(PR, "_PINYIN_FN", lambda s: [table[c] for c in s])
    gl = dict(terms=["LLM", "reranking"], fixes=[{"from": "RM", "to": "LLM"}])
    ch = [dict(source="llm", before="比的很高", after="壁垒很高", diff=[["比的", "壁垒"]]),
          dict(source="llm", before="上下纹", after="上下文", diff=[["纹", "文"]]),
          dict(source="llm", before="RM的上限", after="LLM的上限", diff=[["RM", "LLM"]]),
          dict(source="llm", before="Rewanking", after="reranking", diff=[["Rewanking", "reranking"]]),
          dict(source="llm", before="mort这个", after="merge这个", diff=[["mort", "merge"]]),
          dict(source="term_fix", before="x", after="y"),
          dict(source="llm", before="trade structure", after="tree structure", diff=[["trade", "tree"]]),
          dict(source="llm", before="tree", after="trade", diff=[["tree", "trade"]])]
    n = PR.flag_guesses(ch, gl)
    assert [c["guess"] for c in ch] == [True, False, False, False, True, False, True, True]
    assert n == 4 and "contradicts" in ch[6]["support"]
    assert PR.sound_alike("peer", "pair") >= 0.8 and PR.sound_alike("mort", "merge") < 0.8
    monkeypatch.setattr(PR, "_PINYIN_FN", False)                             # no pinyin backend: CJK swaps are guesses
    assert PR.guess_check(dict(source="llm", diff=[["纹", "文"]]))[0] is True


def test_proofread_marks_its_changes():
    res = PR.proofread([dict(start=0, end=1, text="用Rewanking排序")], provider="none",
                       glossary=dict(fixes=[{"from": "Rewanking", "to": "reranking"}]))
    assert res["changes"] and res["changes"][0]["guess"] is False and res["changes"][0]["support"] == "glossary"


# --------------------------------------------------------------------------- popups: analysis + output scan
ffmpeg = pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")


def _menu(f, x0=440, y0=300):
    f[y0:y0 + 170, x0:x0 + 120] = 252
    f[y0:y0 + 2, x0:x0 + 120] = 180
    f[y0 + 168:y0 + 170, x0:x0 + 120] = 180
    for k in range(6):
        f[y0 + 15 + 25 * k:y0 + 23 + 25 * k, x0 + 15:x0 + 80] = 90


@ffmpeg
def test_popup_closing_inside_the_clip_is_not_repainted_as_a_new_one(tmp_path):
    """Open when the clip starts, closes at 2 s: the closing used to read as a popup OPENING (its 'clean page' a
    popup frame), which painted the menu back over the rest of the clip. Only the open-from-start one is kept."""
    import test_demo_grade as TDG
    V = TDG._V()
    fps, n = 24, 24 * 6
    base = TDG._doc_frame()
    frames = []
    for i in range(n):
        f = base.copy()
        if i / fps < 2.0:
            _menu(f)
        frames.append(f)
    stack = []
    import cv2
    for f in frames[::6]:
        g = cv2.cvtColor(cv2.resize(f[163:615, 0:958], (480, 226), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        stack.append(g)
    st = np.stack(stack).astype(np.int16)
    pops = V.find_popups(st, dict(V.SCREEN_DEFAULTS), 4.0)
    assert len(pops) == 1 and pops[0]["j0"] == 0 and pops[0].get("clean_after") is not None


@ffmpeg
def test_output_scan_flags_a_popup_left_visible_and_ignores_panels(tmp_path):
    """A rendered vertical video (title band + screen) where a menu stays visible from 2 s to the end and a notes
    panel (an overlay) shows from 3 s: the 2 fps scan reports the menu with its time, never the panel; a clean
    render reports nothing."""
    import cv2
    import test_demo_grade as TDG
    V = TDG._V()
    from vstudio import platform as PF
    L = V.layout([PF.parse_targets(["xiaohongshu:vertical"])[0]])
    bx = V.boxes(L, "split", "title")["screen"]
    W, H = L["W"], L["H"]
    fps, n = 24, 24 * 6
    page = cv2.resize(TDG._doc_frame()[163:615, 0:958], (bx[2] - bx[0], bx[3] - bx[1]))
    panel = [W - 420, bx[1] + 16, W - 40, bx[1] + 300]

    def render(menu):
        out = []
        for i in range(n):
            f = np.zeros((H, W, 3), np.uint8)
            f[bx[1]:bx[3], bx[0]:bx[2]] = page
            if menu and i / fps >= 2.0:
                _menu(f, 420, bx[1] + 380)
            if i / fps >= 3.0:
                f[panel[1]:panel[3], panel[0]:panel[2]] = 30
            out.append(f)
        return TDG._video(tmp_path, out, fps, f"v{int(menu)}.mp4")
    plan = dict(canvas=[W, H], layout=L, band="title", items=[dict(item=0, kind="clip", mode="split", band="title",
                                                                   frames=n, screen=dict(popups=[]), box=list(bx))])
    tl = [dict(kind="clip", t0=0.0, t1=n / fps, speed=1.0, final_t0=0.0)]
    segs = V.output_segments(plan, tl, fps)
    assert segs == [(0.0, n / fps, list(bx), 0)]
    ov = [dict(a=3.0, b=6.0, rect=panel)]
    found = V.scan_popups(render(True), segs, ov)
    assert len(found) == 1 and abs(found[0]["t"] - 2.0) <= 0.5 and found[0]["dur"] > 3.0, found
    assert V.scan_popups(render(False), segs, ov) == []


def test_qc_warns_on_visible_popups_with_timestamps():
    from vstudio.batch import lfsplit as LS
    plan = dict(items=[], visible_popups=[dict(t=29.5, dur=15.5, cover=0.05, box=[1, 2, 3, 4], item=6),
                                          dict(t=3.0, dur=0.5, cover=0.2, box=[1, 2, 3, 4], item=1)])
    sc = LS.screen_summary(plan, [], 24)
    assert sc["visible"] and len(sc["visible"]) == 2
    out = LS.screen_checks({}, {}, dict(privacy=dict(plans={"1080x1440": dict(screen=sc)})))
    chk = [c for c in out if c["name"] == "screen-popup-visible"][0]
    assert not chk["ok"] and "29.5-45.0s" in chk["reason"] and "3.0" not in chk["reason"]
    assert LS.screen_summary(dict(items=[]), [], 24)["visible"] is None     # plans before the scan: no check


# --------------------------------------------------------------------------- review --accept-policy --jobs
def test_accept_policy_for_named_jobs_only_and_never_learned(tmp_path, policy_file):
    """Field test: accept-policy was batch-wide and the per-job workaround (an explicit 确认 reply) was learned as
    creator answers (51 fake ones). ``jobs`` limits it; the accepted policy cuts are the policy's, not learned."""
    from vstudio.batch import review
    from vstudio.batch.store import Store
    b = _batch(tmp_path)
    r = review.apply_decisions(b, {"accept_policy": True, "jobs": ["ep01"]})
    assert r["bulk"] == {"ep01": [1]} and r["replied"] == ["ep01"] and r["learned"] == 0
    assert not policy_file.exists() or not (C.load_policy().get("stats") or {})
    st = Store(b)
    try:
        assert C.parse_reply(st.job("ep01")["params"]["cleanup_reply"])["approve"] == {1}
        assert not st.job("ep02")["params"].get("cleanup_reply") and st.job("ep02")["state"] == "done"
    finally:
        st.close()
    # an explicit reply on a job outside --jobs is still applied (and learned: the creator said it)
    r = review.apply_decisions(b, {"accept_policy": True, "jobs": "ep01", "cleanup": {"ep02": "保留 2"}})
    assert "ep02" in r["replied"] and "ep02" not in r["bulk"] and r["learned"] == 1


def test_a_reply_is_learned_once_not_again_with_every_later_reply(tmp_path, policy_file):
    from vstudio.batch import review
    b = _batch(tmp_path)
    review.apply_decisions(b, {"cleanup": {"ep02": "保留 2"}})
    s1 = C.load_policy()["stats"]["filler/connector"]
    r = review.apply_decisions(b, {"cleanup": {"ep02": "保留 2 确认 3"}})
    assert r["learned"] == 1                                                 # only 确认 3 is new
    assert C.load_policy()["stats"]["filler/connector"] == s1


def test_cli_review_accept_policy_jobs_json(tmp_path, policy_file):
    import subprocess
    b = _batch(tmp_path)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "lib"), os.environ.get("PYTHONPATH", "")]))
    r = subprocess.run([sys.executable, "-m", "vstudio.batch", "review", "--batch", b, "--accept-policy", "--jobs",
                        "ep02", "--json"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["ok"] and d["bulk"] == {"ep02": [1]} and d["jobs"] == ["ep02"] and d["learned"] == 0
