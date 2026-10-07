"""Batch pilot quality fixes (synthetic transcripts / audio, no network, no ffmpeg):

* cleanup.verify compares a normalised mixed zh/en stream: whisper's sub-word latin pieces, case, spacing,
  punctuation, fillers / soft particles and ASR spelling variants are not "lost"; real content loss still is;
  words removed on purpose (sidecar ``removed``) are ignored near their cut.
* boundary snaps: an editor cut ending where whisper (late) starts the next word ends at the real onset; a hook
  never starts on a filler.
* cleanup auto-cuts stacked connectors (因为|而且, 然后的话, 另外的话 -> 另外).
* proofread: term fixes, minimal validated LLM fixes (mocked providers), low-confidence words, filler listing,
  provider resolution; the batch stage writes corrected cues + proofread.json and the review sheet lists them.
"""
import json
import os

import numpy as np
import pytest

from vstudio import cleanup as C
from vstudio import proofread as PR
from vstudio.batch import lfsplit as LS
from vstudio.batch import review
from vstudio.batch import stages as ST
from vstudio.batch.recipes import Ctx


def W(*spec):
    """("text", t, te), ... -> transcript word dicts."""
    return [dict(w=w, t=t, te=te) for w, t, te in spec]


def seq(text_tokens, t0=0.0, step=0.3):
    out, t = [], t0
    for tok in text_tokens:
        out.append(dict(w=tok, t=round(t, 3), te=round(t + step * 0.9, 3)))
        t += step
    return out


EXPECTED = seq(["我们", "可以", "对", "这个", "user", "的", "queries", "进行", "rewrite", "然后", "的话", "做", "embedding",
                "再", "去", "做", "chunking", "最后", "看", "answer", "的", "质量"])


# ------------------------------------------------------------------ verify
def test_subword_latin_pieces_case_and_punct_are_not_lost():
    got = seq(["我们", "可以", "对", "U", "ser", "的", "q", "uer", "ies,", "进行", "R", "ew", "rite。", "做", "e", "mb",
               "edding", "再去做", "T", "ron", "king", "最后看", "a", "ns", "wer", "的质量"])
    d = {}
    assert C.content_check(EXPECTED, got, details=d) == []
    # 'chunking' heard as 'trunking': the rest of the word was heard -> spelling variant, not lost
    assert not d["ignored"]


def test_fillers_and_soft_particles_dropped_by_whisper_are_not_lost():
    exp = seq(["然后", "RAG", "的话", "就是", "它", "是", "分为", "两条", "线", "另外", "的话", "一个", "点", "的话"])
    got = seq(["RAG", "它", "是", "分为", "两条", "线", "另外", "一个", "点"])
    assert C.content_check(exp, got) == []


def test_homophone_swaps_are_variants_not_lost():
    exp = seq(["其实", "现在", "比例", "很", "高", "而且", "是", "个", "完全", "取决于"])
    got = seq(["其实", "现在", "比的", "很", "高", "而且", "这个", "完全", "拒绝于"])
    d = {}
    assert C.content_check(exp, got, details=d) == []
    assert d["variants"]                                     # logged for the curious, never red


def test_real_content_loss_is_still_flagged():
    got = seq(["我们", "可以", "对", "这个", "user", "的", "queries", "进行", "rewrite", "做", "embedding",
               "最后", "看", "的", "质量"])                    # 再去做 chunking + answer gone
    flags = C.content_check(EXPECTED, got)
    texts = " ".join(f["text"] for f in flags)
    assert "chunking" in texts and "answer" in texts and "再去" in texts
    # a whole lost English word is content even when short
    flags = C.content_check(seq(["用", "RAG", "来", "做"]), seq(["用", "来", "做"]))
    assert flags and flags[0]["text"] == "rag"
    # a lost CJK phrase between kept words
    flags = C.content_check(seq(["数据", "错", "了", "你", "后面", "怎么", "做", "都是", "错", "的"]),
                            seq(["数据", "错", "了", "都是", "错", "的"]))
    assert flags and flags[0]["kind"] == "missing" and "后面怎么做" in flags[0]["text"]


def test_words_removed_on_purpose_are_ignored_near_their_cut(tmp_path):
    exp = seq(["读", "写", "两侧", "就是", "读", "写"])
    got = seq(["读", "写", "两侧"])
    assert C.content_check(exp, got)                                   # 读写 missing ...
    d = {}
    assert C.content_check(exp, got, ignore=[("读写", 1.2)], details=d) == []   # ... but it was a repeat edit
    assert d["ignored"][0]["why"].startswith("removed on purpose")
    assert C.content_check(exp, got, ignore=[("读写", 9.0)])           # far from that cut: still lost
    # through verify(): the sidecar's `removed` list
    out = str(tmp_path / "final.mp4")
    side = C.write_sidecar(out, "src.mp4", [(0.0, 3.0)], exp, "zh", removed=[dict(w="读写", t=1.2)])
    assert os.path.exists(side)
    rep = C.verify(out, got=got, write=False)
    assert rep["ok"] and rep["ignored"]


# ------------------------------------------------------------------ boundary snaps
SR = 16000


def _audio(bursts, dur, seed=0):
    rng = np.random.default_rng(seed)
    x = rng.normal(0, 1e-4, int(dur * SR)).astype(np.float32)
    for a, b in bursts:
        i0, i1 = int(a * SR), int(b * SR)
        tt = np.arange(i1 - i0) / SR
        x[i0:i1] += 0.3 * np.sin(2 * np.pi * 220 * tt).astype(np.float32)
    return x


def _energy(x, words):
    en = C.Energy.from_any((x, SR))
    return en.calibrate(C.load_words(words), C.settings())


def test_cut_end_moves_to_the_real_onset_whisper_starts_late():
    # removed 'prom' sounds 1.00-1.40, real gap 1.40-1.55, kept 或者 sounds from 1.55; whisper says prom ends and
    # 或者 starts at 1.75 (it swallowed the gap + the onset)
    words = W(("去", 0.4, 0.8), ("prom", 1.0, 1.75), ("或者", 1.75, 2.1), ("comp", 2.1, 2.4))
    x = _audio([(0.4, 0.8), (1.0, 1.4), (1.55, 2.4)], 3.0)
    en = _energy(x, words)
    a, b = C.snap_cut(words, en, 0.9, 1.75)
    assert 1.38 <= b <= 1.56, b                     # ends in the gap, before 或者's real onset
    a0, b0 = C.snap_cut(words, None, 0.9, 1.75)     # without audio: whisper times only (unchanged behaviour)
    assert b0 == 1.75


def test_hook_never_starts_on_a_filler():
    # 然后 (whisper 0.0-1.0) is a soft mumble at 0.5-0.6, RAG sounds from 1.15
    words = C.load_words(W(("然后", 0.0, 1.0), ("RAG", 1.0, 1.4), ("的话", 1.4, 1.6), ("分为", 1.6, 2.0),
                           ("两条", 2.0, 2.4), ("线", 2.4, 2.7), ("一条", 2.7, 3.1), ("是", 3.1, 3.3), ("读", 3.3, 3.6)))
    x = _audio([(0.5, 0.6), (1.15, 3.6)], 4.0)
    en = _energy(x, words)
    ha = LS.hook_skip_lead_fillers(words, en, 0.0, 3.6)
    assert 0.6 < ha <= 1.15, ha
    # no filler first -> unchanged; no audio -> unchanged (cannot place a safe edge)
    assert LS.hook_skip_lead_fillers(words[1:], en, 1.0, 3.6) == 1.0
    assert LS.hook_skip_lead_fillers(words, None, 0.0, 3.6) == 0.0


def test_stacked_connectors_are_auto_cut():
    words = seq(["错", "的", "然后", "的话", "另外", "的话", "一个", "点", "很", "重要", "因为", "而且", "这个", "东西",
                 "其实", "很", "高", "但是", "因为", "它", "大"], step=0.3)
    x = _audio([(w["t"], w["te"]) for w in words], words[-1]["te"] + 0.5)
    en = _energy(x, words)
    E = C.detect(words, profile="standard", energy=en)
    by = {e["text"]: e for e in E}
    assert by["然后的话"]["action"] == "auto"
    assert "的话" in by and by["的话"]["action"] == "auto" and by["的话"]["t0"] >= 1.45   # only the 的话 after 另外
    assert by["因为"]["action"] == "auto" and by["因为"]["kind"] == "restart"
    assert not any(e["text"] == "但是" for e in E)            # 但是因为 is grammatical: kept
    assert not any(e["text"] == "然后" for e in E)            # folded into 然后的话, not listed twice
    gentle = {e["text"]: e for e in C.detect(words, profile="gentle", energy=en)}
    assert gentle["因为"]["action"] == "confirm"


# ------------------------------------------------------------------ proofread
CUES = [dict(start=0.0, end=2.0, text="因为而且这个东西其实现在比的很高"),
        dict(start=2.0, end=4.0, text="称爆你整个的RM的context"),
        dict(start=4.0, end=6.0, text="而且还会丢定度"),
        dict(start=6.0, end=8.0, text="然后的话另外的话一个点")]


def fake_llm(system, prompt, model):
    assert "Captions" in prompt and "0: 因为而且" in prompt and "[unsure: 比的]" in prompt
    return json.dumps({"fixes": [
        {"i": 0, "from": "比的", "to": "比例", "why": "homophone"},
        {"i": 1, "from": "RM", "to": "LLM", "why": "term"},
        {"i": 2, "from": "丢定度", "to": "丢精度", "why": "homophone"},
        {"i": 3, "from": "然后的话另外的话一个点", "to": "另一个要点是关于数据清洗的部分", "why": "rewrite"},   # too much
        {"i": 9, "from": "x", "to": "y"},                                                          # no such cue
        {"i": 1, "from": "不存在", "to": "z"},
        {"i": 1, "from": "的context", "to": "context"},                                             # drops 的
        {"i": 2, "from": "还 会", "to": "还会"}]}), {"input": 1000, "output": 200}             # no-op once squeezed


def test_proofread_minimal_fixes_logged_and_validated():
    heard = [dict(word="比的", start=1.0, end=1.2, p=0.31), dict(word="很", start=1.2, end=1.3, p=0.99)]
    res = PR.proofread(CUES, term_fixes=[["称爆", "撑爆"]], call=fake_llm, heard=heard, context=dict(topic="RAG"),
                       passes=1)
    texts = [c["text"] for c in res["cues"]]
    assert texts[0] == "因为而且这个东西其实现在比例很高"
    assert texts[1] == "撑爆你整个的LLM的context"                           # 的 kept
    assert texts[2] == "而且还会丢精度"
    assert texts[3] == CUES[3]["text"]                                     # the rewrite was refused
    assert [c["start"] for c in res["cues"]] == [c["start"] for c in CUES]  # timing untouched
    src = [(c["i"], c["source"]) for c in res["changes"]]
    assert (1, "term_fix") in src and (0, "llm") in src and (2, "llm") in src
    assert {r["reason"] for r in res["rejected"]} >= {"changes too much of the caption",
                                                      "caption index out of range", "'from' is not in the caption",
                                                      "drops spoken word(s) 的 (captions must match the audio)"}
    assert res["low_confidence"] == [dict(i=0, word="比的", p=0.31, t=1.0)]
    assert PR._locate("RM的context", "RM的cont ext") == "RM的context"           # model copied a spaced span
    assert [f["i"] for f in res["fillers_left"]] == [0, 3] and "然后的话" in res["fillers_left"][1]["fillers"]
    assert res["usage"] == {"input": 1000, "output": 200}


def test_provider_resolution_and_mocked_sdks(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert PR.resolve_provider(None) == "none" and PR.resolve_provider("auto") == "none"
    res = PR.proofread(CUES, provider="auto")
    assert res["provider"] == "none" and res["cost_usd"] == 0.0 and not [c for c in res["changes"] if c["source"] == "llm"]
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert PR.resolve_provider("auto") == "none"                  # OpenAI is never picked implicitly
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    assert PR.resolve_provider("auto") == "claude"
    with pytest.raises(ValueError):
        PR.resolve_provider("no-such-llm")                       # gemini & co are vstudio.llm providers now
    assert PR.resolve_provider("gemini") == "gemini" and PR.resolve_provider("anthropic") == "claude"
    seen = {}

    def fake(name):
        def call(system, prompt, model):
            seen[name] = model
            return '```json\n{"fixes": [{"i": 2, "from": "丢定度", "to": "丢精度"}]}\n```', {"input": 10, "output": 5}
        return call
    monkeypatch.setitem(PR.CALLS, "claude", fake("claude"))
    monkeypatch.setitem(PR.CALLS, "openai", fake("openai"))
    r1 = PR.proofread(CUES, provider="auto")
    assert seen["claude"] == "claude-opus-5-5" and r1["cues"][2]["text"] == "而且还会丢精度" and r1["cost_usd"] > 0
    r2 = PR.proofread(CUES, provider="openai", model="gpt-x")
    assert seen["openai"] == "gpt-x" and r2["provider"] == "openai"


def test_claude_provider_without_sdk_needs_a_key(monkeypatch):
    import builtins
    real = builtins.__import__

    def no_anthropic(name, *a, **k):
        if name == "anthropic":
            raise ImportError("no anthropic")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # no SDK: the Messages API over plain HTTPS, which needs the key
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        PR._call_claude("s", "p", "claude-opus-5-5")


def batch_fake_llm(system, prompt, model):           # spec proofread.call target (module:fn)
    return json.dumps({"fixes": [{"i": 0, "from": "比的", "to": "比例", "why": "homophone"}]}), {"input": 1, "output": 1}


def test_proofread_stage_and_review_sheet(tmp_path):
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps({"cues": CUES}, ensure_ascii=False), encoding="utf-8")
    heard = tmp_path / "heard.json"
    heard.write_text(json.dumps({"segments": [{"start": 0, "end": 8, "text": "", "words": [
        dict(word="丢定度", start=4.5, end=5.0, p=0.2)]}]}, ensure_ascii=False), encoding="utf-8")
    spec = dict(proofread=dict(provider="none", call="test_batch_quality:batch_fake_llm"),
                subtitles=dict(term_fixes=[["RM", "LLM"]]), asr=dict(prompt="RAG, LLM"))
    job = dict(id="ep02", params=dict(title="T", chapter="C"), recipe="longform-split")
    d = tmp_path / "proofread"
    d.mkdir()
    ctx = Ctx(job, spec, str(d), {"compose": {"cues": str(cues)}, "verify": {"heard": str(heard)}}, str(tmp_path))
    out = ST.run_proofread(ctx)
    got = json.load(open(out["cues"], encoding="utf-8"))["cues"]
    assert got[0]["text"].endswith("比例很高") and got[1]["text"] == "称爆你整个的LLM的context"
    rep = json.load(open(out["report"], encoding="utf-8"))
    assert rep["low_confidence"][0]["word"] == "丢定度" and out["changes"] == 2
    assert ST.caption_cues(Ctx(job, spec, str(d), {"proofread": out, "compose": {"cues": str(cues)}}, "")) == out["cues"]
    # the key carries the provider + term fixes; with an LLM also the prompt context (title, chapter, ...)
    pk = ST._proofread_params(job, spec)
    assert pk["term_fixes"] == [["RM", "LLM"]] and pk["title"] == "T"
    assert "title" not in ST._proofread_params(job, dict(spec, proofread={"provider": "none"}))
    # review: changed cues, unsure words and leftover fillers reach the decisions sheet
    item = dict(id="ep02", title="T", state="done", confirm=[], reply="",
                captions=dict(provider="custom", model=None, rejected=0, low=rep["low_confidence"],
                              fillers=rep["fillers_left"],
                              changes=[dict(i=c["i"], start=c["start"], before=c["before"], after=c["after"],
                                            source=c["source"], why=c["why"]) for c in rep["changes"]]))
    md, nj, ne = review.decisions_needed_md([item], "b")
    assert nj == 1 and ne == 0 and "比例很高" in md and "丢定度 (0.20)" in md and "然后的话" in md
    assert "capHtml" in review.PAGE


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not installed")
def test_flag_rechecked_on_its_own_window(tmp_path):
    """Whisper on the whole file skipped a passage that IS in the audio (a body repeating the cold open): verify
    re-hears just that window and drops the flag; a word missing in the window too stays lost."""
    from vstudio.audio import write_wav
    exp = seq(["数据", "的", "质量", "是", "上限", "就是", "垃圾", "进", "垃圾", "出", "也", "就是", "说", "数据",
               "的", "质量", "是", "上限"], t0=0.2, step=0.3)
    out = str(tmp_path / "final.wav")
    write_wav(out, _audio([(w["t"], w["te"]) for w in exp], 6.0), SR)
    C.write_sidecar(out, "src.wav", [(0.0, 6.0)], exp, "zh")
    gap = [w for w in exp if not (1.7 <= w["t"] <= 2.9)]               # whole-file ASR skipped 垃圾进垃圾出

    def hear(path, drop_in_window=()):
        if path == out:
            return gap
        a = max(0.0, 1.7 - 1.5)
        return [dict(w=w["w"], t=w["t"] - a, te=w["te"] - a) for w in exp if w["w"] not in drop_in_window]
    rep = C.verify(out, transcriber=hear, recheck=True, write=False)
    assert rep["ok"] and rep["rechecked"] and "垃圾进垃圾出" in rep["rechecked"][0]["text"]
    rep = C.verify(out, transcriber=lambda p: hear(p, ("垃圾", "进", "出")), recheck=True, write=False)
    # missing in the window too, but no cut joint anywhere near it: editing cannot have lost it -> ASR variance
    assert rep["ok"] and rep["asr_variance"] and "垃圾" in rep["asr_variance"][0]["text"]
    rep = C.verify(out, transcriber=hear, write=False)                   # a custom transcriber: no re-check unless asked
    assert rep["ok"] and rep["asr_variance"]


def test_flag_at_a_cut_joint_is_a_real_loss(tmp_path):
    """A word missing right where two kept pieces meet is the one case editing can cause: it stays red."""
    from vstudio.audio import write_wav
    exp = seq(["我们", "先", "看", "数据", "模型", "再", "看", "结果"], t0=0.2, step=0.4)
    out = str(tmp_path / "final.wav")
    write_wav(out, _audio([(w["t"], w["te"]) for w in exp], 4.0), SR)
    C.write_sidecar(out, "src.wav", [(0.0, 1.78), (1.79, 4.0)], exp, "zh")   # joint right before 模型
    got = [w for w in exp if w["w"] != "模型"]
    rep = C.verify(out, transcriber=lambda p: got, write=False)
    assert not rep["ok"] and rep["missing"][0]["text"] == "模型"
