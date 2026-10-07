"""Regression: proofreading ON damaged the English demo captions (batch p34, 2026-10-07): the glossary respelled
everyday words by sound (part -> port x27, make -> mock, after -> avatar) and one LLM edit and -> or was copied to
every cue. Now: glossary spellings are whole-word / case-aware and never respell a plain English word by sound in
English speech, an LLM edit of an everyday English word needs ASR evidence (low confidence or a disagreeing second
hearing), and only a glossary term is propagated. Chinese keeps its homophone / place-name fixes."""
import json

from vstudio import entities as E
from vstudio import proofread as PR

PART_LINES = [f"here's the part {k} people get wrong" if k % 2 else f"the refresh part number {k}" for k in range(27)]


def _cues(texts):
    return [dict(start=float(i), end=float(i) + 1.0, text=t) for i, t in enumerate(texts)]


def _heard(cues, p=0.97, low=()):
    """Second-hearing words for every cue: each word at ``p`` (``low``: words heard at 0.2)."""
    out = []
    for c in cues:
        ws = c["text"].split()
        for k, w in enumerate(ws):
            t = c["start"] + k * (c["end"] - c["start"]) / len(ws)
            out.append(dict(word=" " + w, start=t, end=t + 0.1, p=0.2 if w.strip(".,").lower() in low else p))
    return out


def _llm(fixes):
    def call(system, prompt, model):
        return json.dumps({"fixes": fixes}), {"input": 1, "output": 1}
    return call


def test_glossary_never_respells_part_make_after():
    text = "\n".join(PART_LINES + ["then the planner starts to make bad choices", "after login the avatar loads"])
    r = E.verify(text, glossary=["port", "mock", "avatar", "JWT"])
    assert r["fixes"] == []
    old = dict(terms=["port", "mock", "avatar"], fixes=[{"from": "part", "to": "port"}, {"from": "make", "to": "mock"},
                                                        {"from": "after", "to": "avatar"}])
    cues = _cues(PART_LINES + ["then the planner starts to make bad choices"])
    res = PR.proofread(cues, provider="none", glossary=old)
    assert [c["text"] for c in res["cues"]] == [c["text"] for c in cues]       # 0 of 27 "part" touched
    assert not [c for c in res["changes"] if c["source"] in ("glossary", "entity")]


def test_glossary_spelling_is_case_aware_and_whole_word():
    r = E.verify("Port 8080 is open. We use redis and oauth here. Rediscover the airport.",
                 glossary=["port", "Redis", "OAuth"])
    got = {f["from"]: f["to"] for f in r["fixes"]}
    assert got == {"redis": "Redis", "oauth": "OAuth"}                 # never Port -> port, never inside a word
    assert E.fix_text("Rediscover redis", r["fixes"]) == "Rediscover Redis"


def test_sound_alike_respelling_is_for_terms_inside_chinese_speech_only():
    en = "two failure modes and a radish salad"                      # real words that sound like terms
    assert E.verify(en, glossary=["models", "Redis"])["fixes"] == []
    zh = E.verify("我们用radish做缓存", glossary=["Redis"])["fixes"]     # an English term written by ear
    assert [(f["from"], f["to"]) for f in zh] == [("radish", "Redis")]
    assert E.verify("we use Hibrid search here", glossary=["Hybrid"])["fixes"][0]["to"] == "Hybrid"   # a mangled token


def test_llm_edit_of_a_clearly_heard_everyday_word_is_rejected():
    cues = _cues(["then the planner starts to make bad choices", "we read the client side code"])
    fixes = [{"i": 0, "from": "make", "to": "mock"}, {"i": 1, "from": "client side", "to": "client ID"}]
    res = PR.proofread(cues, call=_llm(fixes), passes=1, entities=False, heard=_heard(cues))
    assert [c["text"] for c in res["cues"]] == [c["text"] for c in cues]
    why = " ".join(r["reason"] for r in res["rejected"])
    assert "'make' was heard clearly (p=0.97)" in why and "'side' was heard clearly" in why
    res = PR.proofread(cues, call=_llm(fixes[:1]), passes=1, entities=False)                 # no ASR data at all
    assert res["cues"][0]["text"] == cues[0]["text"]
    assert "no ASR confidence" in res["rejected"][0]["reason"]


def test_llm_edit_is_allowed_with_asr_evidence_or_on_a_rare_token():
    cues = _cues(["what is the old data here", "we mock it with Mokito"])
    fixes = [{"i": 0, "from": "old", "to": "stale"}, {"i": 1, "from": "Mokito", "to": "Mockito"}]
    res = PR.proofread(cues, call=_llm(fixes), passes=1, entities=False, heard=_heard(cues, low={"old"}))
    assert [c["text"] for c in res["cues"]] == ["what is the stale data here", "we mock it with Mockito"]
    ev = PR.cue_evidence([dict(word=" trade", start=0.1, end=0.3, p=0.9), dict(word="-off", start=0.3, end=0.5, p=0.4)],
                         cues)
    assert ev[0] == {"trade": [0.4], "off": [0.4]} and ev[1] is None       # whisper pieces join their word


def test_one_and_to_or_edit_is_never_propagated():
    cues = _cues(["never put secrets and private data in a JWT", "and I didn't need any secret to read it.",
                  "The subject is the email and there's an issue", "and it stops working."])
    res = PR.proofread(cues, call=_llm([{"i": 0, "from": "and", "to": "or"}]), passes=1, entities=False,
                       heard=_heard(cues, low={"and"}))
    assert [c["text"] for c in res["cues"]] == [c["text"] for c in cues]
    assert not [c for c in res["changes"] if c["source"] == "llm-propagated"]


def test_only_a_glossary_term_is_propagated():
    cues = _cues(["is that look up in Redis with a short expir", "the expir is short", "RM is a large model",
                  "every RM call costs money"])
    fixes = [{"i": 0, "from": "expir", "to": "expiry"}, {"i": 2, "from": "RM", "to": "LLM"}]
    res = PR.proofread(cues, call=_llm(fixes), passes=1, entities=False, context=dict(glossary=["LLM"]))
    assert [c["text"] for c in res["cues"]] == ["is that look up in Redis with a short expiry", "the expir is short",
                                                "LLM is a large model", "every LLM call costs money"]
    assert [c["i"] for c in res["changes"] if c["source"] == "llm-propagated"] == [3]


def test_a_cached_bad_fix_is_not_reapplied(tmp_path):
    cues = _cues(["then the planner starts to make bad choices"])
    cache = PR.CueCache(str(tmp_path))
    ok = PR.proofread(cues, call=_llm([{"i": 0, "from": "make", "to": "mock"}]), passes=1, entities=False,
                      heard=_heard(cues, low={"make"}), cache=cache)
    assert ok["cues"][0]["text"] == "then the planner starts to mock bad choices" and ok["cache"]["stored"] == 1
    res = PR.proofread(cues, call=_llm([]), passes=1, entities=False, heard=_heard(cues), cache=cache)
    assert res["cues"][0]["text"] == cues[0]["text"] and res["cache"]["sent"] == 1     # re-asked, not re-applied


def test_chinese_fixes_still_work():
    res = PR.proofread(_cues(["他后来去了宏都拉斯", "这个模型的显存会被称爆"]), passes=1, locked=None,
                       call=_llm([{"i": 1, "from": "称爆", "to": "撑爆"}]), entities="zh_Hans")
    assert [c["text"] for c in res["cues"]] == ["他后来去了洪都拉斯", "这个模型的显存会被撑爆"]
    g = dict(terms=["LLM"], fixes=[{"from": "准缺率", "to": "准确率"}])
    res = PR.proofread(_cues(["模型的准缺率很高", "准缺率又提高了"]), provider="none", glossary=g, entities=False)
    assert [c["text"] for c in res["cues"]] == ["模型的准确率很高", "准确率又提高了"]


def test_a_case_only_glossary_fix_is_not_its_own_contradiction():
    rej = []
    ok = PR._drop_contradictions([{"from": "redis", "to": "Redis"}, {"from": "OAuth2", "to": "OAuth"},
                                  {"from": "OAuth", "to": "OAuth2"}], rej)
    assert [(f["from"], f["to"]) for f in ok] == [("redis", "Redis")]
    assert {r["from"] for r in rej} == {"OAuth", "OAuth2"}
    assert E.verify("we cache it in redis", glossary=["Redis"])["fixes"][0]["to"] == "Redis"   # case: entities
