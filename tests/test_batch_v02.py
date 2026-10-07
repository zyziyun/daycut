"""vstudio.batch v0.2 (desk P0): clients, plan-segments, job edit / rerun, deliver, metrics / timing, the CLI
contract the desk app calls. Synthetic data, fake recipes, mocked LLMs - no network."""
import csv
import io
import json
import os
import shutil
import subprocess
import sys
import time

import pytest
import yaml

import _v02_helpers as V
from vstudio.batch import clients as CL
from vstudio.batch import deliver as DV
from vstudio.batch import edits as ED
from vstudio.batch import metrics as MT
from vstudio.batch import segplan as SP
from vstudio.batch import spec as S
from vstudio.batch.plan import plan_batch
from vstudio.batch.run import run_batch
from vstudio.batch.store import Store

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
GTM_HEADER = ("周,线索数,沟通数,样片数,确认试点数,交付数,回传数据数,付费数,收入(¥),交付条数,人审秒数中位数/条,返工率,质检红灯率,"
              "每条成本($),内容号播放中位数,内容号收藏率,内容号涨粉,千剪号有效线索,Release下载数,跑完一批的外部用户数,带价LOI数,B2B对话数")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("VSTUDIO_CLIENTS", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def mkbatch(tmp, jobs=None, run=True, **kw):
    spec = dict(name="v2", recipe="test-v02", plugins=["_v02_helpers"], retry={"backoff": 0},
                jobs=jobs or [dict(id="ep01", start=1, end=9, title="RAG的检索流程", body="正文", tags=["RAG"]),
                              dict(id="ep02", start=10, end=20, title="向量数据库", tags=["向量"])],
                defaults=dict(platforms=["xiaohongshu:full", "douyin"]))
    spec.update(kw)
    p = tmp / "batch.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True))
    r = plan_batch(str(p), echo=False)
    if run:
        res = run_batch(r["batch_dir"], echo=False)
        assert res["exit_code"] == 0, res
    return r["batch_dir"], str(p)


def cli(*args, env=None, cwd=None):
    e = dict(os.environ)
    e["PYTHONPATH"] = os.pathsep.join([os.path.join(ROOT, "lib"), os.path.dirname(__file__), e.get("PYTHONPATH", "")])
    e.update(env or {})
    r = subprocess.run([sys.executable, "-m", "vstudio.batch", *args], capture_output=True, text=True, env=e, cwd=cwd)
    return r


# --------------------------------------------------------------------------- clients
def test_client_init_show_update_layered_over_persona(tmp_path):
    cdir = str(tmp_path / "clients" / "acme")
    v = CL.init(cdir, dict(name="Acme 讲师", platforms=["douyin"], tags=["RAG"], brand={"accent": "#112233"},
                           fillers={"extra": ["对不对"], "keep": ["然后"]}, cleanup_profile="tight"))
    eff = v["effective"]
    assert eff["name"] == "Acme 讲师" and eff["platforms"] == ["douyin"] and eff["cleanup_profile"] == "tight"
    assert eff["brand"]["accent"] == "#112233" and eff["brand"]["ink"]      # persona brand underneath
    assert eff["delivery"]["cleanup_days"] == 0 and eff["confirm_policy"] is True     # 0 = never delete sources
    with pytest.raises(CL.ClientError):
        CL.init(cdir, dict(name="x"))
    v = CL.update(cdir, dict(glossary_add=[dict(wrong="rag", right="RAG")], tags_add=["LLM"], style="干净"))
    assert v["config"]["glossary"] == [dict(wrong="rag", right="RAG")] and v["config"]["tags"] == ["RAG", "LLM"]
    with pytest.raises(CL.ClientError):
        CL.update(cdir, dict(brand={"accent": "red"}))
    assert CL.add_glossary(cdir, [dict(wrong="rag", right="RAG"), dict(wrong="成客", right="chunk")]) == \
        [dict(wrong="成客", right="chunk")]
    # slug resolution under the clients root
    os.environ["VSTUDIO_CLIENTS"] = str(tmp_path / "clients")
    try:
        assert CL.resolve("acme") == cdir and CL.list_clients()[0]["slug"] == "acme"
    finally:
        del os.environ["VSTUDIO_CLIENTS"]


def test_batch_with_client_gets_defaults_glossary_and_persona_overlay(tmp_path):
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme", platforms=["douyin"], glossary=[dict(wrong="成客", right="chunk")],
                       brand={"accent": "#123456"}, fillers={"extra": ["对不对"]}, confirm_policy=False))
    spec = dict(name="c", recipe="test-v02", plugins=["_v02_helpers"], client=cdir, retry={"backoff": 0},
                jobs=[dict(id="a", start=1, end=9, title="t")])
    p = tmp_path / "batch.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True))
    r = plan_batch(str(p), echo=False)
    st = Store(r["batch_dir"])
    sp, j = st.spec, st.job("a")
    st.close()
    assert j["params"]["platforms"] == ["douyin"] and j["params"]["cleanup_policy"] is False
    assert [r"成客", "chunk"] in sp["subtitles"]["term_fixes"]
    per = yaml.safe_load(open(os.path.join(r["batch_dir"], "client.persona.yaml"), encoding="utf-8"))
    assert per["brand"]["accent"] == "#123456" and per["cleanup"]["fillers_extra"] == ["对不对"]
    assert per["subtitles"]["term_fixes"]["成客"] == "chunk"
    assert CL.batches(cdir)[0]["dir"] == r["batch_dir"]
    from vstudio.config import persona
    with CL.activate(r["batch_dir"]):
        assert persona()["brand"]["accent"] == "#123456"
    assert persona()["brand"].get("accent") != "#123456"


# --------------------------------------------------------------------------- plan-segments
TOPICS = [
    ("向量数据库", ["向量数据库是RAG的核心组件。", "我们把文档切块以后做embedding存进向量数据库。", "检索的时候用向量相似度找最近的块。",
                "向量数据库的索引类型决定了检索速度。", "常见的有HNSW和IVF两种索引。"]),
    ("重排序", ["召回以后还要做重排序。", "reranker用cross encoder给每个候选打分。", "重排序能明显提升top5的准确率。",
             "但是reranker的延迟比较高。", "所以一般先召回五十个再重排序取前五个。"]),
    ("评估", ["没有评估集你就不知道系统变好还是变坏。", "评估指标包括召回率和忠实度。", "Ragas可以自动计算这些评估指标。",
            "每次改动都要跑一遍评估。", "评估集至少要五十条真实问题。"]),
]


def synth_transcript(path, reps=4):
    segs, t = [], 2.0
    for _ in range(reps):
        for _name, sents in TOPICS:
            for s in sents:
                toks = [x for x in __import__("re").findall(r"[A-Za-z0-9]+|[一-鿿]|[。]", s)]
                ws = []
                for tok in toks:
                    if tok == "。":
                        continue
                    d = 0.18 if len(tok) == 1 else 0.35
                    ws.append(dict(word=tok, start=round(t, 3), end=round(t + d, 3)))
                    t += d + 0.04
                ws[-1]["word"] += "。"
                segs.append(dict(start=ws[0]["start"], end=ws[-1]["end"], text=s, words=ws))
                t += 0.7
            t += 2.0                                   # a long pause between topics
    json.dump(dict(language="zh", segments=segs), open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return t


def test_plan_segments_rule_based(tmp_path):
    tp = str(tmp_path / "tr.json")
    synth_transcript(tp)
    d = SP.plan_segments(None, transcript=tp, count=4, min_s=15, max_s=40, provider="none",
                         platforms=["xiaohongshu:full", "douyin"], out=str(tmp_path / "plan"), echo=False)
    segs = d["segments"]
    assert d["provider"] == "none" and len(segs) == 4 and d["title_max"] == 20
    tr = json.load(open(tp, encoding="utf-8"))
    starts = {w["start"] for s in tr["segments"] for w in s["words"]}
    ends = {w["end"] for s in tr["segments"] for w in s["words"]}
    for a, b in zip(segs, segs[1:]):
        assert a["end"] <= b["start"]                                  # no overlap, time order
    for s in segs:
        assert 15 * 0.85 <= s["end"] - s["start"] <= 40 * 1.15
        assert any(abs(s["start"] - x) < 0.25 for x in starts) and any(abs(s["end"] - x) < 0.25 for x in ends)
        assert set(s) >= {"id", "start", "end", "title", "chapter", "hook", "notes", "tags", "why", "risk", "score"}
        assert s["title"] and len(s["title"]) <= 20 and 0 <= s["score"] <= 1
        assert s["start"] <= s["hook"]["start"] < s["hook"]["end"] <= s["end"] + 0.3 and s["hook"]["text"]
        assert s["tags"]
    rows = S.read_rows(d["draft"])                                       # a valid segments.yaml
    assert len(rows) == 4 and rows[0]["range"][0] == segs[0]["start"] and rows[0]["hook"]["src"]
    assert S.segments_header(d["draft"])["transcript"] == os.path.abspath(tp)
    assert d["words"] and set(d["words"][0]) == {"w", "t", "te"}


def test_plan_segments_llm_providers_mocked(tmp_path, monkeypatch):
    tp = str(tmp_path / "tr.json")
    synth_transcript(tp, reps=2)
    seen = {}

    def fake(system, prompt, model):
        seen.update(system=system, prompt=prompt, model=model)
        return json.dumps({"segments": [
            {"from": 0, "to": 4, "title": "向量数据库为什么是RAG的核心组件一定要懂的事情和索引", "chapter": "向量库",
             "hook": {"from": 1, "to": 1}, "hook_alternatives": [{"from": 2, "to": 2}], "notes": ["索引决定速度"],
             "tags": ["#RAG", "向量数据库"], "why": "自成一体", "risk": "", "score": 0.9},
            {"from": 3, "to": 6, "title": "重叠的段", "score": 0.1},          # overlaps the first: dropped
            {"from": 999, "to": 1000, "title": "越界"}]}), dict(input=1000, output=200)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    d = SP.plan_segments(None, transcript=tp, count=3, min_s=10, max_s=40, provider="openai", call=fake,
                         platforms=["xiaohongshu:full"], out=str(tmp_path / "p"), echo=False)
    assert d["provider"] == "openai" and seen["model"] == "gpt-4.1" and "[0]" in seen["prompt"]
    assert "20" in seen["system"]
    s0 = d["segments"][0]
    assert s0["chapter"] == "向量库" and s0["tags"][0] == "RAG" and s0["score"] == 0.9
    from vstudio.publish import title_len
    assert title_len(s0["title"], "xiaohongshu") <= 20 < title_len("向量数据库为什么是RAG的核心组件一定要懂的事情和索引",
                                                                     "xiaohongshu")      # shortened to the 小红书 limit
    assert len(d["segments"]) == 3 and d["warnings"]                    # 2 filled by the rule-based ranking
    tr = json.load(open(tp, encoding="utf-8"))["segments"]
    assert s0["hook"]["text"] == tr[1]["text"]                          # the hook says what the audio says
    assert d["cost_usd"] > 0
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(SP.PlanError):
        SP.plan_segments(None, transcript=tp, provider="openai", echo=False, write=False)
    with pytest.raises(SP.PlanError):
        SP.plan_segments(None, transcript=tp, provider="claude", echo=False, write=False)
    assert SP.plan_segments(None, transcript=tp, provider="auto", count=2, min_s=10, max_s=40, echo=False,
                            write=False)["provider"] == "none"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    d = SP.plan_segments(None, transcript=tp, provider="auto", count=1, min_s=10, max_s=40, call=fake, echo=False,
                         write=False)
    assert d["provider"] == "claude" and seen["model"] == "claude-opus-5-5"


def test_plan_segments_shares_the_transcript_with_the_batch_asr(tmp_path, monkeypatch):
    import vstudio.config  # noqa: F401  (fonts resolved before the cache root moves)
    from vstudio.batch import transcripts as TS
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    p = TS.save("abc", dict(segments=[dict(start=0, end=1, text="x", words=[dict(word="x", start=0, end=1)])]),
                "zh", None, "auto")
    path, tr = TS.lookup("abc", "zh", None, "auto")
    assert path == p and tr["segments"][0]["text"] == "x"
    assert TS.lookup("abc", "en", None, "auto") == (None, None)
    cache = tmp_path / "asrcache.json"
    cache.write_text(json.dumps({"h1": dict(language="zh", segments=[dict(start=0, end=1, text="y", words=[])])}))
    assert TS.load_any(str(cache))["segments"][0]["text"] == "y"


# --------------------------------------------------------------------------- job edit / rerun
def _stages_ran(bdir, since):
    return [c for c in V.calls(bdir)[since:]]


def test_caption_edit_faithful_check_and_rerun_only_export(tmp_path):
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme"))
    bdir, _ = mkbatch(tmp_path, client=cdir)
    st = Store(bdir)
    st.set_job("ep01", state="approved", review="approved")
    st.close()
    r = ED.edit(bdir, "ep01", "caption", cue=0, text="今天我们讲RAG的检索流程，还有很多别的内容")
    assert not r["ok"] and not r["faithful"] and "adds" in r["reason"]
    r = ED.edit(bdir, "ep01", "caption", cue=1, text="向量数据库很重要")      # punctuation only: fine
    assert r["ok"] and r["faithful"]
    r = ED.edit(bdir, "ep01", "caption", cue=0, text="今天我们讲LAG的检索流程")
    assert r["ok"] and r["faithful"] and r["rerun"] == ["export", "qc", "preview"]
    assert r["glossary_added"] and r["glossary_added"][0]["wrong"] == "RAG"
    assert any(g["right"] == "LAG" for g in CL.load(cdir)["glossary"])
    n0 = len(V.calls(bdir))
    rr = ED.rerun(bdir, "ep01", echo=False)
    assert rr["ok"] and rr["state"] == "done" and sorted(rr["stages"]) == ["export", "preview", "qc"]
    assert sorted(s for j, s in _stages_ran(bdir, n0)) == ["export", "preview", "qc"]
    st = Store(bdir)
    ex = st.stage("ep01", "export")["out"]["exports"][0]
    j = st.job("ep01")
    pend = st.meta("pending")
    st.close()
    assert open(ex["file"], encoding="utf-8").read().startswith("今天我们讲LAG的检索流程|")
    assert j["review"] is None and "ep01" not in (pend or {})                 # back for review, nothing pending
    from vstudio.batch import api
    d = api.job_detail(bdir, "ep01")
    assert d["captions"]["cues"][0]["text"] == "今天我们讲LAG的检索流程" and d["captions"]["cues"][0]["edited"]
    assert [h["op"] for h in d["edit"]["history"]] == ["caption", "caption"]
    # undo -> back to the proofread text, stale again
    u = ED.edit(bdir, "ep01", "undo")
    assert u["ok"] and "export" in u["rerun"]
    d = api.job_detail(bdir, "ep01")
    assert d["captions"]["cues"][0]["text"] == "今天我们讲RAG的检索流程"


def test_edit_adopts_drifted_keys_instead_of_recutting(tmp_path):
    bdir, _ = mkbatch(tmp_path)
    st = Store(bdir)
    st.set_stage("ep01", "compose", key="drifted-since-the-run")      # e.g. an engine update re-keyed the cut
    st.close()
    r = ED.edit(bdir, "ep01", "caption", cue=0, text="今天我们讲LAG的检索流程")
    assert r["ok"] and "compose" in r["adopted"] and r["rerun"] == ["export", "qc", "preview"]
    n0 = len(V.calls(bdir))
    ED.rerun(bdir, "ep01", echo=False)
    assert sorted(s for _, s in V.calls(bdir)[n0:]) == ["export", "preview", "qc"]


def test_trim_hook_copy_cover_and_replan_keeps_edits(tmp_path):
    bdir, spec = mkbatch(tmp_path, jobs=[dict(id="ep01", start=1, end=9, title="RAG的检索流程", body="正文第一段",
                                               tags=["RAG"], hook_candidates=[dict(start=2, end=4, text="讲RAG"),
                                                                              dict(start=5, end=7, text="向量")])])
    r = ED.edit(bdir, "ep01", "trim", start=1.13, end=6.2)
    assert r["ok"] and r["value"]["snapped"] and r["rerun"][:1] == ["compose"]
    a, b = r["value"]["range"]
    assert a <= 1.13 and b >= 6.2 - 0.05                                     # grown to word edges, never cut into
    with pytest.raises(ED.EditError):
        ED.edit(bdir, "ep01", "trim", start=3, end=4)
    r = ED.edit(bdir, "ep01", "hook", pick=1)
    assert r["ok"] and r["value"]["hook"]["src"] == [5.0, 7.0] and "compose" in r["rerun"]
    with pytest.raises(ED.EditError):
        ED.edit(bdir, "ep01", "hook", pick=7)
    r = ED.edit(bdir, "ep01", "copy", title="这是一个非常非常非常长的小红书标题会超过二十个字的限制吧", tags="RAG,LLM")
    assert r["ok"] and r["title_ok"] is False and any("title" in w for w in r["warnings"])
    r = ED.edit(bdir, "ep01", "copy", title="新标题", body="新正文", tags="RAG,LLM")
    assert r["ok"] and "compose" in r["pending"]
    rr = ED.rerun(bdir, "ep01", echo=False)
    assert rr["ok"]
    st = Store(bdir)
    ex = st.stage("ep01", "export")["out"]["exports"][0]
    p = st.job("ep01")["params"]
    st.close()
    post = open(ex["post"], encoding="utf-8").read()
    assert post.startswith("新标题") and "新正文" in post and "#LLM" in post
    assert p["_copy_orig"]["title"] == "RAG的检索流程" and p["hook_pick"] == 1
    # a copy edit alone never re-renders: posts rewritten in place, only qc (title check) re-runs
    r = ED.edit(bdir, "ep01", "copy", body="再改一次正文")
    assert r["ok"] and r["rerun"] == [] and r["posts_rewritten"]
    assert "再改一次正文" in open(ex["post"], encoding="utf-8").read()
    r = ED.edit(bdir, "ep01", "copy", title="再改标题")
    assert r["rerun"] == ["qc"]
    # replan from the same spec: the edits survive (no re-render needed for them)
    plan_batch(spec, echo=False)
    st = Store(bdir)
    p2 = st.job("ep01")["params"]
    st.close()
    assert p2["range"] == [a, b] and p2["title"] == "再改标题" and p2["hook_pick"] == 1


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_cover_edit_speech_recipe(tmp_path):
    mp4 = str(tmp_path / "m.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=180x320:r=10:d=2", "-pix_fmt",
                    "yuv420p", mp4], check=True)
    bdir, _ = mkbatch(tmp_path, jobs=[dict(id="ep01", start=1, end=9, title="t", master_file=mp4)])
    r = ED.edit(bdir, "ep01", "cover", t=1.0, text="封面｜第二行")
    assert r["ok"] and os.path.exists(r["value"]["file"]) and r["rerun"][0] == "export"
    assert r["value"]["t"] == 1.0 and r["value"]["text"] == "封面｜第二行"


def test_stale_stages_and_caption_overrides_helpers():
    cues = [dict(text="a"), dict(text="b"), dict(text="c")]
    out, ok, miss = ED.apply_caption_overrides(cues, [{"i": 1, "from": "b", "to": "B"}, {"i": 0, "from": "c", "to": "C"},
                                                      {"i": 5, "from": "zz", "to": "Z"}])
    assert [c["text"] for c in out] == ["a", "B", "C"] and len(ok) == 2 and len(miss) == 1
    old, new = dict(title="T", body="B1", tags=["x"]), dict(title="T2", body="B2", tags=["y"])
    assert ED.patch_post("T\n\nB1\n\n#x #persona\n", old, new) == "T2\n\nB2\n\n#y #persona\n"


def test_lfsplit_master_stash_roundtrip(tmp_path):
    from vstudio.batch import lfsplit as L
    vdir = tmp_path / "work" / "vertical" / "1080x1920"
    vdir.mkdir(parents=True)
    (vdir / "master.mp4").write_bytes(b"m")
    (vdir / "plan.json").write_text("{}")
    cfg = dict(src="s", targets=["douyin"], episodes=dict(items=[dict(title="A", big1="x", hook=dict(src=[1, 2]))]),
               publish=dict(title="A", body="b"), vertical=dict(export_preset="medium", mode="split"))
    k1 = L.master_key(cfg, [dict(kind="clip")], {}, "veryfast")
    cfg2 = json.loads(json.dumps(cfg))
    cfg2["targets"] = ["douyin", "youtube-shorts"]
    cfg2["episodes"]["items"][0].update(title="B", big1="y")
    cfg2["publish"]["body"] = "c"
    assert L.master_key(cfg2, [dict(kind="clip")], {}, "veryfast") == k1          # copy / cover / targets only
    cfg2["vertical"]["mode"] = "screen"
    assert L.master_key(cfg2, [dict(kind="clip")], {}, "veryfast") != k1
    stash = str(tmp_path / "stash")
    L.keep_masters(stash, k1, str(tmp_path / "work" / "vertical"))
    out = tmp_path / "w2" / "vertical"
    assert L.reuse_masters(stash, k1, str(out), {(1080, 1920)}) == ["1080x1920"]
    assert (out / "1080x1920" / "master.mp4").read_bytes() == b"m"
    assert L.reuse_masters(stash, "other", str(tmp_path / "w3"), {(1080, 1920)}) == []
    assert L.reuse_masters(stash, k1, str(tmp_path / "w4"), {(1080, 1920), (1080, 1440)}) == []


# --------------------------------------------------------------------------- deliver / cleanup
def _approve_all(bdir):
    st = Store(bdir)
    for j in st.jobs():
        st.set_job(j["id"], state="approved", review="approved")
    st.close()


def test_deliver_package_manifest_and_source_cleanup(tmp_path):
    inside = tmp_path / "batch-v2" / "src"                  # a source copied into the batch folder
    inside.mkdir(parents=True)
    src = inside / "raw.mp4"
    src.write_bytes(b"0" * 1000)
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme 讲师", delivery={"cleanup_days": 7}))
    bdir, _ = mkbatch(tmp_path, client=cdir, inputs={"source": str(src)})
    assert os.path.realpath(bdir) == os.path.realpath(str(tmp_path / "batch-v2"))
    _approve_all(bdir)
    ED.edit(bdir, "ep02", "copy", title="改过的标题", body="改过的正文")
    r = DV.deliver(bdir, make_zip=True, today=__import__("datetime").date(2026, 10, 7))
    assert r["items"] == 4 and r["jobs"] == 2 and r["cleanup_days"] == 7 and r["cleanup_on"] == "2026-10-14"
    d = r["dir"]
    assert os.path.basename(d) == "Acme 讲师-v2-20261007" and os.path.exists(r["zip"])
    assert sorted(os.listdir(d)) == sorted(["小红书", "抖音", "文案.md", "排期表.csv", "交付说明.md", "manifest.json"])
    assert any(f.endswith("_封面.jpg") for f in os.listdir(os.path.join(d, "小红书")))
    md = open(os.path.join(d, "文案.md"), encoding="utf-8").read()
    assert "AI 标识提醒" in md and "改过的标题" in md and "改过的正文" in md
    assert open(os.path.join(d, "排期表.csv"), encoding="utf-8").read().startswith("﻿日期,时间,平台")
    assert DV.verify_delivery(os.path.join(d, "manifest.json"))["ok"]
    with open(os.path.join(d, "文案.md"), "a", encoding="utf-8") as f:
        f.write("tampered")
    assert DV.verify_delivery(os.path.join(d, "manifest.json"))["bad"] == ["文案.md"]
    # cleanup: not due yet -> nothing; due -> the dry run lists the exact files + a code; only that code deletes
    assert DV.cleanup_sources([bdir])["would_delete"] == []
    later = time.time() + 8 * 86400
    dry = DV.cleanup_sources([bdir], now=later)
    assert [x["path"] for x in dry["would_delete"]] == [str(src)] and src.exists() and dry["confirm_code"]
    with pytest.raises(ValueError):
        DV.cleanup_sources([bdir], now=later, yes=True)                  # no blanket "yes"
    with pytest.raises(ValueError):
        DV.cleanup_sources([bdir], now=later, confirm="000000000000")    # a wrong / stale code deletes nothing
    assert src.exists()
    # another batch still using the same source (not delivered) protects it
    other = tmp_path / "other"
    other.mkdir()
    mkbatch(other, run=False, inputs={"source": str(src)}, name="v3")
    kept = DV.cleanup_sources([bdir], now=later)
    assert kept["kept"][0]["path"] == str(src) and kept["would_delete"] == [] and kept["confirm_code"] is None
    shutil.rmtree(str(other))
    dry = DV.cleanup_sources([bdir], now=later)
    done = DV.cleanup_sources([bdir], now=later, confirm=dry["confirm_code"])
    assert done["deleted"][0]["path"] == str(src) and not src.exists()


def test_source_cleanup_never_touches_sources_outside_the_batch(tmp_path):
    rec = tmp_path / "my recordings" / "lecture.mp4"          # the creator's own recording, next to the batch
    rec.parent.mkdir()
    rec.write_bytes(b"0" * 500)
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme", delivery={"cleanup_days": 3}))
    bdir, _ = mkbatch(tmp_path, client=cdir, inputs={"source": str(rec)})
    _approve_all(bdir)
    assert DV.deliver(bdir)["cleanup_days"] == 3
    later = time.time() + 4 * 86400
    dry = DV.cleanup_sources([bdir], now=later)
    assert dry["would_delete"] == [] and dry["confirm_code"] is None
    assert [x["path"] for x in dry["outside"]] == [str(rec)] and "never deleted" in dry["outside"][0]["why"]
    r = cli("cleanup-sources", "--batch", bdir, "--yes", "--json")
    assert r.returncode == 1 and "--confirm-delete" in r.stdout and rec.exists()
    r = cli("cleanup-sources", "--batch", bdir, "--json")
    assert r.returncode == 0 and json.loads(r.stdout)["dry_run"] is True and rec.exists()


def test_deliver_defaults_never_delete_and_own_workspace(tmp_path):
    src = tmp_path / "raw.mp4"
    src.write_bytes(b"0")
    bdir, _ = mkbatch(tmp_path, inputs={"source": str(src)})        # no client: the creator's own workspace
    _approve_all(bdir)
    r = DV.deliver(bdir, cleanup_days=30)
    assert r["cleanup_days"] == 0 and r["cleanup_on"] is None and "own workspace" in r["cleanup_note"]
    me = str(tmp_path / "clients" / "self")
    CL.init(me, dict(name="自己的账号", delivery={"cleanup_days": 7}))
    assert DV.deliver(bdir, client=me, cleanup_days=5)["cleanup_days"] == 0
    other = str(tmp_path / "clients" / "acme")
    CL.init(other, dict(name="Acme"))                              # a client that never set cleanup_days
    assert DV.deliver(bdir, client=other)["cleanup_days"] == 0
    assert CL.effective(CL.load(other))["delivery"]["cleanup_days"] == 0


# --------------------------------------------------------------------------- metrics / timing
def test_timing_and_metrics_json_and_weekly_csv(tmp_path):
    cdir = str(tmp_path / "acme")
    CL.init(cdir, dict(name="Acme", crm={"history": [{"stage": "lead", "at": "2026-10-07"},
                                                    {"stage": "pilot", "at": "2026-10-08"}],
                                        "revenue": [{"at": "2026-10-09", "amount": 1999}]}))
    bdir, _ = mkbatch(tmp_path, client=cdir)
    t0 = time.time()
    MT.timing(bdir, "ep01", "start", ts=t0)
    r = MT.timing(bdir, "ep01", "stop", seconds=41.5, ts=t0 + 60)
    assert r["review_s"] == 41.5
    MT.timing(bdir, "ep02", "start", ts=t0)
    assert MT.timing(bdir, "ep02", "stop", ts=t0 + 20)["review_s"] == 20.0      # no seconds: stop - start
    with pytest.raises(ValueError):
        MT.timing(bdir, "ep02", "pause")
    with pytest.raises(KeyError):
        MT.timing(bdir, "nope", "start")
    ED.edit(bdir, "ep01", "copy", body="x")
    m = MT.metrics(batch=bdir)
    js = {j["id"]: j for j in m["jobs"]}
    assert js["ep01"]["review_s"] == 41.5 and js["ep01"]["rework"] and not js["ep02"]["rework"]
    assert m["summary"]["review_s_median"] == 30.8 and m["summary"]["red_rate"] == 0.0
    _approve_all(bdir)
    DV.deliver(bdir)
    c = MT.metrics(client=cdir, csv_=True)
    assert c["summary"]["delivered_clips"] == 2 and c["batches"][0]["dir"] == bdir
    assert c["csv"].splitlines()[0] == GTM_HEADER
    rows = list(csv.DictReader(io.StringIO(c["csv"])))
    wk = MT.week_of(time.time())
    row = rows[wk - 1]
    assert row["交付数"] == "1" and row["交付条数"] == "2" and row["人审秒数中位数/条"] == "30.8"
    assert rows[0]["线索数"] == "1" and rows[0]["确认试点数"] == "1" and rows[0]["收入(¥)"] == "1999.0"
    assert row["内容号播放中位数"] == ""
    a = MT.metrics(all_=True)
    assert any(b["dir"] == bdir for b in a["batches"])


# --------------------------------------------------------------------------- CLI contract (desk)
def test_cli_contract(tmp_path):
    env = {"VSTUDIO_HOME": str(tmp_path / "home")}
    h = cli("--help", env=env).stdout
    for c in ("plan-segments", "client", "deliver", "metrics", "timing", "job"):
        assert c in h.split("{", 1)[1].split("}", 1)[0]
    jh = cli("job", "--help", env=env).stdout
    assert "{show,edit,rerun}" in jh
    ch = cli("client", "--help", env=env).stdout
    assert "init" in ch and "update" in ch
    cdir = str(tmp_path / "c1")
    r = cli("client", "init", "--client", cdir, "--set", json.dumps({"name": "C1", "platforms": ["douyin"]}),
            "--json", env=env)
    doc = json.loads(r.stdout)
    assert doc["ok"] and doc["effective"]["platforms"] == ["douyin"] and doc["config"]["name"] == "C1"
    r = cli("client", "update", "--client", cdir, "--set", json.dumps({"glossary_add": [{"wrong": "a", "right": "b"}]}),
            "--json", env=env)
    assert json.loads(r.stdout)["config"]["glossary"][0]["right"] == "b"
    bdir, _ = mkbatch(tmp_path)
    r = cli("job", "ep01", "--batch", bdir, "--json", "--no-words", env=env)       # F0 form still works
    assert json.loads(r.stdout)["job"]["id"] == "ep01"
    r = cli("job", "edit", "--batch", bdir, "--job", "ep01", "--op", "caption", "--cue", "0", "--text",
            "今天我们讲LAG的检索流程", "--json", env=env)
    doc = json.loads(r.stdout)
    assert r.returncode == 0 and doc["ok"] and doc["faithful"] and doc["rerun"] == ["export", "qc", "preview"]
    r = cli("job", "edit", "--batch", bdir, "--job", "ep01", "--op", "caption", "--cue", "0", "--text", "完全不同的话",
            "--json", env=env)
    doc = json.loads(r.stdout)
    assert r.returncode == 1 and not doc["ok"] and not doc["faithful"] and doc["reason"]
    r = cli("job", "rerun", "--batch", bdir, "--job", "ep01", "--json-events", env=env)
    evs = [json.loads(x) for x in r.stdout.splitlines()]
    assert r.returncode == 0 and evs[-1]["event"] == "rerun-done" and sorted(evs[-1]["stages"]) == ["export", "preview", "qc"]
    assert any(e["event"] == "stage-start" for e in evs)
    r = cli("timing", "--batch", bdir, "--job", "ep01", "--event", "stop", "--what", "review", "--seconds", "12",
            "--json", env=env)
    assert json.loads(r.stdout)["review_s"] == 12.0
    r = cli("metrics", "--batch", bdir, "--json", env=env)
    assert json.loads(r.stdout)["summary"]["review_s_total"] == 12.0
    r = cli("metrics", "--all", "--csv", env=env)
    assert r.stdout.splitlines()[0] == GTM_HEADER
    r = cli("metrics", "--all", "--csv", "--json", env=env)
    assert json.loads(r.stdout)["csv"].startswith("周,")
    _approve_all(bdir)
    r = cli("deliver", "--batch", bdir, "--zip", "--cleanup-days", "0", "--json", env=env)
    doc = json.loads(r.stdout)
    assert doc["ok"] and os.path.exists(doc["zip"]) and doc["manifest_data"]["items"] and doc["cleanup_on"] is None
    tp = str(tmp_path / "tr.json")
    synth_transcript(tp, reps=2)
    r = cli("plan-segments", "--source", tp, "--transcript", tp, "--count", "2", "--min", "10", "--max", "40",
            "--provider", "none", "--out", str(tmp_path / "plan"), "--json", env=env)
    doc = json.loads(r.stdout)
    assert len(doc["segments"]) == 2 and os.path.exists(doc["draft"]) and doc["words"]
    r = cli("plan-segments", "--source", tp, "--transcript", tp, "--provider", "openai", "--json", env=env)
    assert r.returncode == 5 and "OPENAI_API_KEY" in json.loads(r.stdout)["error"]
