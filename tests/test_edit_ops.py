"""Field-test fixes (batch-rag v0.2): captions follow the kept audio after policy cuts, proofread cache per cue,
``job edit --op cut / notes``, ``review --accept-policy --jobs``, caption edits checked against a re-hearing.
Synthetic data, fake recipes / LLM / ASR - no media, no network."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LFS = os.path.join(ROOT, "workflows", "longform-to-short", "scripts")


# --------------------------------------------------------------------------- (a) captions follow the kept audio
def _words(spec):
    return [dict(word=w, start=a, end=b) for w, a, b in spec]


def test_filler_merged_cut_keeps_the_word_in_the_captions(tmp_path):
    """ep04 regression: the policy-accepted ``filler-merged`` cuts trimmed the merged filler in front of 只 / hybrid
    (patch = [onset, cut end]); the word is still said after the cut, but its ASR midpoint sat inside the cut, so the
    caption lost it. A fully cut filler (然后) must still leave the captions."""
    from vstudio import cleanup as C
    from vstudio.batch import lfsplit as L
    seg1 = [("现在", 440.0, 440.6), ("其实", 440.6, 441.2), ("也", 441.2, 441.5), ("很少", 441.5, 442.16),
            ("因为", 442.16, 442.5), ("只", 442.5, 444.1), ("做", 444.1, 444.24), ("RED", 444.24, 444.62)]
    seg2 = [("出来", 446.0, 446.34), ("然后", 446.6, 446.9), ("我", 446.95, 447.2), ("都是", 447.3, 447.76),
            ("hybrid", 447.76, 448.38), ("这样", 448.64, 448.78), ("的", 448.78, 448.9), ("模式", 448.9, 449.4)]
    tr = {"segments": [dict(start=440.0, end=444.62, text="".join(w for w, _, _ in seg1), words=_words(seg1)),
                       dict(start=446.0, end=449.4, text="".join(w for w, _, _ in seg2), words=_words(seg2))]}
    W = C.load_words(tr)
    i_then = next(k for k, w in enumerate(W) if w["w"] == "然后")
    edits = [dict(id=1, t0=442.67, t1=443.86, kind="filler-merged", text="只", action="confirm", words=[],
                  patch=[442.5, 443.86]),
             dict(id=2, t0=446.5, t1=446.93, kind="filler", text="然后", action="auto", words=[i_then]),
             dict(id=3, t0=447.76, t1=448.14, kind="filler-merged", text="hybrid", action="confirm", words=[],
                  patch=[447.76, 448.14]),
             dict(id=4, t0=448.4, t1=448.6, kind="pause", text="", action="confirm", words=[])]
    edl = tmp_path / "body.cleanup.json"
    edl.write_text(json.dumps(dict(ranges=[[439.9, 449.6]], edits=edits, words=W, settings=dict(min_piece=0.06))))
    work = tmp_path / "work"
    work.mkdir()
    L.whisper_json(tr, str(work / "audio16k.json"))
    pieces, ids = L._keep_pieces(dict(cleanup_reply="全部确认"), str(edl), with_ids=True)
    assert ids == [1, 2, 3, 4] and len(pieces) == 5
    assert L.cut_transcript(str(work / "audio16k.json"), str(edl), ids) == 2
    tl, t = [], 0.0
    for a, b in pieces:
        tl.append(dict(kind="clip", t0=a, t1=b, speed=1.0, final_t0=round(t, 3)))
        t += b - a
    (work / "timeline.json").write_text(json.dumps(tl))
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out")}))
    subprocess.run([sys.executable, os.path.join(LFS, "build_subs.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    text = "".join(c["text"] for c in json.loads((work / "cues.json").read_text(encoding="utf-8")))
    assert "只做RED" in text and "hybrid" in text                    # trimmed in front, still said: captioned
    assert "然后" not in text and "出来我都是" in text                  # fully cut: gone from the captions
    # nothing patched without the edits being cut (a reply that keeps them): the ASR words stay as they were
    pieces, ids = L._keep_pieces(dict(cleanup_reply="保留 1,3"), str(edl), with_ids=True)
    assert 1 not in ids and 3 not in ids


def test_patch_onsets_only_for_cut_edits():
    from vstudio import cleanup as C
    W = [dict(w="只", t=442.5, te=444.1), dict(w="做", t=444.1, te=444.24)]
    e = [dict(id=1, patch=[442.5, 443.86])]
    assert C.patch_onsets(W, e, [1])[0]["t"] == 443.86 and W[0]["t"] == 442.5        # copies, not in place
    assert C.patch_onsets(W, e, [])[0]["t"] == 442.5
    assert C.patch_onsets(W, [dict(id=1, patch=[442.5, 444.2])], [1])[0]["t"] == 442.5   # cut past its end: gone


# --------------------------------------------------------------------------- shared batch fixtures
sys.path.insert(0, os.path.dirname(__file__))
import _edit_helpers as EH  # noqa: E402
import yaml  # noqa: E402

from vstudio import proofread as PR  # noqa: E402
from vstudio.batch import edits as ED  # noqa: E402
from vstudio.batch.plan import plan_batch  # noqa: E402
from vstudio.batch.run import run_batch  # noqa: E402
from vstudio.batch.store import Store  # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CLEANUP_POLICY", str(tmp_path / "cfg" / "cleanup_policy.json"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    EH.CALLS.clear()


def mkbatch(tmp, recipe="test-edit-ops", plugins=("_edit_helpers",), **kw):
    spec = dict(name="eo", recipe=recipe, plugins=list(plugins), retry={"backoff": 0},
                jobs=[dict(id="ep01", start=1, end=9.5, title="RAG的检索流程", notes=["要点一", "要点二"])],
                defaults=dict(platforms=["xiaohongshu:full"]), proofread=dict(call="_edit_helpers:fake_llm"))
    spec.update(kw)
    p = tmp / "batch.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True))
    r = plan_batch(str(p), echo=False)
    res = run_batch(r["batch_dir"], echo=False)
    assert res["exit_code"] == 0, res
    return r["batch_dir"]


def cli(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([os.path.join(ROOT, "lib"), os.path.dirname(__file__), env.get("PYTHONPATH", "")])
    return subprocess.run([sys.executable, "-m", "vstudio.batch", *args], capture_output=True, text=True, env=env)


SHAPE = {"ok", "op", "faithful", "reason", "rerun", "pending", "glossary_added", "undone"}


# --------------------------------------------------------------------------- (c) job edit --op cut / notes
def test_cut_op_snaps_to_whole_words_appends_to_cuts_and_undoes(tmp_path):
    bdir = mkbatch(tmp_path)
    # words (fake ASR): 讲 2.0-2.4, RAG 2.5-2.9, 的 3.0-3.4, 检索 3.5-3.9 ...
    r = ED.edit(bdir, "ep01", "cut", start=2.7, end=3.65, why="口误")
    assert SHAPE <= set(r) and r["ok"] and r["faithful"] and r["reason"] is None
    assert r["value"]["cut"] == [2.5, 3.4, "口误"] and r["value"]["words"] == "RAG的"   # no word split
    assert r["rerun"] == ["cleanup", "compose", "proofread", "export", "qc", "preview"]
    assert r["pending"] == r["rerun"]
    r2 = ED.edit(bdir, "ep01", "cut", start=6.3, end=6.75)
    assert r2["value"]["cuts"] == [[2.5, 3.4, "口误"], [6.3, 6.7, ""]]
    st = Store(bdir)
    assert st.job("ep01")["params"]["cuts"] == [[2.5, 3.4, "口误"], [6.3, 6.7, ""]]
    st.close()
    rr = ED.rerun(bdir, "ep01", echo=False)
    assert rr["ok"] and "cleanup" in rr["stages"]
    st = Store(bdir)
    assert st.stage("ep01", "cleanup")["out"]["ranges"] == [[1.0, 2.5], [3.4, 6.3], [6.7, 9.5]]
    st.close()
    u = ED.edit(bdir, "ep01", "undo")
    assert u["ok"] and u["undone"]["op"] == "cut" and "cleanup" in u["rerun"]
    st = Store(bdir)
    assert st.job("ep01")["params"]["cuts"] == [[2.5, 3.4, "口误"]]
    st.close()
    with pytest.raises(ED.EditError, match="outside the job's range"):
        ED.edit(bdir, "ep01", "cut", start=0.2, end=2.0)
    with pytest.raises(ED.EditError, match="no whole word"):
        ED.edit(bdir, "ep01", "cut", start=2.75, end=2.85)
    with pytest.raises(ED.EditError, match="left"):
        ED.edit(bdir, "ep01", "cut", start=1.0, end=9.0)


def test_cut_needs_a_cleanup_stage(tmp_path):
    bdir = mkbatch(tmp_path, recipe="test-v02", plugins=("_v02_helpers",))
    with pytest.raises(ED.EditError, match="no cleanup stage"):
        ED.edit(bdir, "ep01", "cut", start=2.0, end=3.0)


def test_notes_op_reruns_only_the_notes_render_and_downstream(tmp_path):
    bdir = mkbatch(tmp_path)
    r = ED.edit(bdir, "ep01", "notes", set="新要点一|新要点二|新要点三")
    assert SHAPE <= set(r) and r["ok"] and r["value"]["notes"] == ["新要点一", "新要点二", "新要点三"]
    assert r["rerun"] == ["export", "qc", "preview"]               # not proofread / captions / cleanup
    r = ED.edit(bdir, "ep01", "notes", set="")
    assert r["ok"] and r["value"]["notes"] == []
    st = Store(bdir)
    assert "notes" not in st.job("ep01")["params"]
    st.close()
    with pytest.raises(ED.EditError):
        ED.edit(bdir, "ep01", "notes")
    # longform-split: the notes panel is the export's (vertical master) business only
    from vstudio.batch import lfsplit as L
    from vstudio.batch import stages as ST
    job = dict(params=dict(notes=["a"], range=[0, 10], title="t"), recipe="longform-split")
    job2 = dict(job, params=dict(job["params"], notes=["b"]))
    spec = dict(proofread=dict(call="_edit_helpers:fake_llm"))
    assert L._export_params(job, spec) != L._export_params(job2, spec)
    for f in (L._compose_params, ST._proofread_params,
              ST.cleanup_params("range", "cuts", "hook", "speed", "hook_speed", "cleanup_profile")):
        assert f(job, spec) == f(job2, spec)


def test_cli_cut_and_notes_json(tmp_path):
    bdir = mkbatch(tmp_path)
    r = cli("job", "edit", "--batch", bdir, "--job", "ep01", "--op", "cut", "--start", "2.7", "--end", "3.65",
            "--why", "aside", "--json")
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert SHAPE <= set(d) and d["ok"] and d["value"]["cut"] == [2.5, 3.4, "aside"] and d["rerun"][0] == "cleanup"
    r = cli("job", "edit", "--batch", bdir, "--job", "ep01", "--op", "notes", "--set", "a|b", "--json")
    d = json.loads(r.stdout)
    assert d["ok"] and d["value"]["notes"] == ["a", "b"] and "proofread" not in d["rerun"]
    r = cli("job", "edit", "--batch", bdir, "--job", "ep01", "--op", "cut", "--start", "0", "--end", "1.2", "--json")
    d = json.loads(r.stdout)
    assert r.returncode == 1 and d["ok"] is False and "outside" in d["error"]


# --------------------------------------------------------------------------- (b) proofread cache per cue
def _cues(*texts):
    return [dict(start=2.0 * k, end=2.0 * k + 1.8, text=t) for k, t in enumerate(texts)]


def test_proofread_cache_sends_only_new_cues(tmp_path):
    cache = str(tmp_path / "pc")
    cues = _cues("我们用RM来生成", "然后检索", "RM的上限")
    r1 = PR.proofread(cues, call=EH.fake_llm, cache=cache)
    assert len(EH.CALLS) == 2 and [c["text"] for c in r1["cues"]] == ["我们用LLM来生成", "然后检索", "LLM的上限"]
    assert r1["cache"] == dict(hits=0, sent=3, stored=3)
    EH.CALLS.clear()
    r2 = PR.proofread(cues, call=EH.fake_llm, cache=cache)          # a re-cut with the same cue texts
    assert EH.CALLS == [] and [c["text"] for c in r2["cues"]] == [c["text"] for c in r1["cues"]]
    assert r2["cache"]["hits"] == 3 and all(c.get("cached") for c in r2["changes"] if c["source"] == "llm")
    EH.CALLS.clear()
    r3 = PR.proofread(_cues("我们用RM来生成", "然后再检索一下", "RM的上限"), call=EH.fake_llm, cache=cache)
    assert all(len(lines) == 1 and lines[0].endswith("然后再检索一下") for lines in EH.CALLS)  # only the new cue
    assert r3["cache"] == dict(hits=2, sent=1, stored=1)
    EH.CALLS.clear()
    PR.proofread(cues, call=EH.fake_llm, cache=cache, glossary=dict(fixes=[], terms=["RAG"]))   # new glossary
    assert EH.CALLS                                                    # -> a new context hash: asked again


def test_proofread_never_touches_locked_cues(tmp_path):
    cues = _cues("我们用RM来生成", "就是", "RM的上限")
    r = PR.proofread(cues, call=EH.fake_llm, cache=str(tmp_path / "pc"), locked=[0], term_fixes=[["生成", "生成器"]])
    assert r["cues"][0]["text"] == "我们用RM来生成" and r["cues"][2]["text"] == "LLM的上限"
    assert all(not ln.startswith("0: 我们") for lines in EH.CALLS for ln in lines)
    out, _ = PR.fix_filler_edges(r["cues"], locked=[1])
    assert len(out) == 3                                               # a locked cue is never merged


def test_batch_proofread_rerun_reuses_the_cache_and_keeps_caption_edits(tmp_path):
    """Field test: every cleanup change re-ran the LLM proofread (new errors each time) and the caption overrides,
    keyed by text, silently missed afterwards."""
    from vstudio.batch import stages as ST
    from vstudio.batch.recipes import Ctx
    cues = _cues("我们用RM来生成", "向量数据库很重要", "RM的上限")
    comp = tmp_path / "compose.json"
    comp.write_text(json.dumps(dict(cues=cues), ensure_ascii=False), encoding="utf-8")
    spec = dict(proofread=dict(call="_edit_helpers:fake_llm"))
    params = dict(title="t", notes=["n1"])

    def run(p, d):
        os.makedirs(tmp_path / d, exist_ok=True)
        ctx = Ctx(dict(id="ep01", params=p, recipe="x"), spec, str(tmp_path / d), dict(compose=dict(cues=str(comp))),
                  str(tmp_path))
        return ST.run_proofread(ctx), ctx
    out, _ = run(params, "a")
    assert len(EH.CALLS) == 2
    EH.CALLS.clear()
    out2, ctx = run(dict(params, notes=["changed notes"]), "b")            # notes are a hint, not a cache key
    assert EH.CALLS == [] and json.load(open(out2["cues"]))["cues"] == json.load(open(out["cues"]))["cues"]
    assert "cache 3 hit(s)" in ctx.logs[-1]
    # a creator caption edit made on the proofread text: still applied after the proofread rewords that cue
    ov = [dict(i=2, **{"from": "LLM的上限", "to": "RM 的上限"}, asr="RM的上限", t=4.9)]
    reworded = [dict(c) for c in json.load(open(out["cues"]))["cues"]]
    reworded[2]["text"] = "LLM它的上限"                                  # what a re-roll could have produced
    got, applied, missed = ED.apply_caption_overrides(reworded, ov, asr_cues=cues)
    assert got[2]["text"] == "RM 的上限" and applied[0]["how"] == "asr" and not missed
    got, applied, missed = ED.apply_caption_overrides(reworded, [dict(ov[0], asr="完全不同")], asr_cues=cues)
    assert applied[0]["how"] == "time"                                   # same time, nearly the same words
    got, applied, missed = ED.apply_caption_overrides(reworded, [dict(ov[0], asr="完全不同", t=0.9)], asr_cues=cues)
    assert missed and got[2]["text"] == "LLM它的上限"                    # reported, never silently dropped
    # proofread leaves the edited cue alone
    EH.CALLS.clear()
    out3, ctx = run(dict(params, caption_overrides=ov), "c")
    assert json.load(open(out3["cues"]))["cues"][2]["text"] == "RM的上限" and "1 locked" in ctx.logs[-1]


def test_export_reports_a_caption_edit_it_cannot_place(tmp_path):
    bdir = mkbatch(tmp_path, recipe="test-v02", plugins=("_v02_helpers",))
    st = Store(bdir)
    p = st.job("ep01")["params"]
    p["caption_overrides"] = [dict(i=0, **{"from": "已经不存在的字幕", "to": "x"})]
    st.set_job("ep01", params=p)
    rows = st.stage_rows("ep01")
    st.close()
    from vstudio.batch import stages as ST
    from vstudio.batch.recipes import Ctx
    ctx = Ctx(dict(id="ep01", params=p, recipe="test-v02"), {}, str(tmp_path),
              dict(compose=rows["compose"]["out"], proofread=rows["proofread"]["out"]), bdir)
    ST.caption_cues(ctx)                                                 # what run_export records in its output
    assert ctx.caption_edits == dict(applied=0, missed=[dict(i=0, **{"from": "已经不存在的字幕", "to": "x"})])
    from vstudio.batch.qc import run_gates
    res = run_gates(dict(id="ep01", params=p, recipe="test-v02"), {},
                    dict(export=dict(caption_overrides=ctx.caption_edits, manifest=str(tmp_path / "none.json"))))
    assert any("caption-edit-missed" in w for w in res["warnings"])
    from vstudio.batch.api import job_detail
    assert job_detail(bdir, "ep01")["edit"]["caption_overrides_missed"]


# --------------------------------------------------------------------------- (e) caption edit vs the re-hearing
def test_caption_edit_accepted_when_the_rehearing_matches(tmp_path, monkeypatch):
    """Field test: ep02 cue 8 the audio says 性价比; the caption said 现在比的 (a guess), so the faithful check refused
    the right text. A re-hearing of the cue window decides; a refusal says why, in a sentence."""
    from vstudio.batch import clients as CL
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme"))
    bdir = mkbatch(tmp_path, recipe="test-v02", plugins=("_v02_helpers",), client=cdir)
    heard = {"text": "今天我们讲RAG的检索流程"}
    seen = []
    monkeypatch.setattr(ED, "rehear_text", lambda ctx, a, b: seen.append((a, b)) or heard["text"])
    r = ED.edit(bdir, "ep01", "caption", cue=0, text="今天我们来讲讲RAG的检索流程")
    assert r["ok"] is False and r["faithful"] is False and r["reason_code"] == "differs-from-audio"
    assert r["heard"] == "今天我们讲RAG的检索流程" and "re-heard" in r["reason"] and seen == [(0.0, 1.8)]
    heard["text"] = "今天我们来讲讲RAG的检索流程。"
    r = ED.edit(bdir, "ep01", "caption", cue=0, text="今天我们来讲讲RAG的检索流程")
    assert r["ok"] and r["matched"] == "reasr" and r["heard"] == heard["text"] and r["rerun"][0] == "export"
    assert r["glossary_added"] == []                                     # a re-hearing is not a term confusion
    # --reasr: the re-hearing decides even for a sound-alike edit
    heard["text"] = "向量数据库很重要"
    r = ED.edit(bdir, "ep01", "caption", cue=1, text="向量数据裤很重要", reasr=True)
    assert r["ok"] is False and r["reason_code"] == "differs-from-audio"
    # no composed cut to re-hear: the old refusal, with a code
    monkeypatch.setattr(ED, "rehear_text", lambda ctx, a, b: None)
    r = ED.edit(bdir, "ep01", "caption", cue=1, text="向量数据库很重要还有别的")
    assert r["reason_code"] == "not-faithful" and "adds" in r["reason"] and r["heard"] is None
    r = ED.edit(bdir, "ep01", "caption", cue=1, text="向量数据库很重要", reasr=True)
    assert r["reason_code"] == "rehear-unavailable"


def test_reverting_a_proofread_guess_teaches_the_glossary_nothing(tmp_path, monkeypatch):
    from vstudio.batch import clients as CL
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme"))
    bdir = mkbatch(tmp_path, recipe="test-v02", plugins=("_v02_helpers",), client=cdir)
    st = Store(bdir)
    pr = st.stage("ep01", "proofread")["out"]
    d = json.load(open(pr["cues"], encoding="utf-8"))
    d["cues"][0]["text"] = "今天我们讲LAG的检索流程"                       # the LLM's guess
    json.dump(d, open(pr["cues"], "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(dict(provider="custom", changes=[dict(i=0, before="今天我们讲RAG的检索流程", after="今天我们讲LAG的检索流程",
                                                    source="llm", diff=[["RAG", "LAG"]])]),
              open(pr["report"], "w", encoding="utf-8"))
    st.close()
    monkeypatch.setattr(ED, "rehear_text", lambda ctx, a, b: None)
    r = ED.edit(bdir, "ep01", "caption", cue=0, text="今天我们讲RAG的检索流程")       # back to what was said
    assert r["ok"] and r["glossary_added"] == []
    assert not any(g.get("wrong") == "LAG" for g in CL.load(cdir).get("glossary") or [])
    st = Store(bdir)
    o = st.job("ep01")["params"]["caption_overrides"][0]
    st.close()
    assert o["asr"] == "今天我们讲RAG的检索流程" and o["t"] == 0.9                 # keyed robustly


def test_cli_caption_refusal_json_fields(tmp_path):
    bdir = mkbatch(tmp_path, recipe="test-v02", plugins=("_v02_helpers",))
    r = cli("job", "edit", "--batch", bdir, "--job", "ep01", "--op", "caption", "--cue", "0", "--text", "完全不同的话",
            "--json")
    d = json.loads(r.stdout)
    assert r.returncode == 1 and d["ok"] is False and d["faithful"] is False
    assert d["reason_code"] == "not-faithful" and isinstance(d["reason"], str) and "heard" in d and d["heard"] is None
    assert {"rerun", "pending", "glossary_added", "undone"} <= set(d)


def test_seed_cache_from_a_proofread_made_before_the_cache(tmp_path):
    """batch-rag jobs were proofread before the cache: their next re-run must keep the reviewed corrections."""
    import shutil
    from vstudio.batch import stages as ST
    from vstudio.batch.recipes import Ctx
    cues = _cues("我们用RM来生成", "然后检索", "RM的上限")
    comp = tmp_path / "compose.json"
    comp.write_text(json.dumps(dict(cues=cues), ensure_ascii=False), encoding="utf-8")
    spec = dict(proofread=dict(call="_edit_helpers:fake_llm"))
    job = dict(id="ep01", params=dict(title="t"), recipe="x")
    os.makedirs(tmp_path / "a")
    out = ST.run_proofread(Ctx(job, spec, str(tmp_path / "a"), dict(compose=dict(cues=str(comp))), str(tmp_path)))
    rep = json.load(open(out["report"], encoding="utf-8"))
    rep.pop("cache")                                                     # as written by the old engine
    json.dump(rep, open(out["report"], "w", encoding="utf-8"), ensure_ascii=False)
    shutil.rmtree(tmp_path / "cache")
    rows = dict(proofread=dict(out=out), compose=dict(out=dict(cues=str(comp))))
    assert ST.seed_proofread_cache(str(tmp_path), spec, job, rows) == 3
    assert ST.seed_proofread_cache(str(tmp_path), spec, job, rows) == 0      # never overwrites
    EH.CALLS.clear()
    os.makedirs(tmp_path / "b")
    out2 = ST.run_proofread(Ctx(job, spec, str(tmp_path / "b"), dict(compose=dict(cues=str(comp))), str(tmp_path)))
    assert EH.CALLS == [] and json.load(open(out2["cues"]))["cues"][0]["text"] == "我们用LLM来生成"
