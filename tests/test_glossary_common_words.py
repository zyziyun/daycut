"""Regression: the glossary of a 124-min English backend class (OpenAI gpt-4.1, 2026-10-07) mapped everyday words
onto glossary terms (part -> port x27, after -> avatar x45, client side -> client ID ...), OAuth both ways, and the
per-job pass turned "and private data" into "or private data", then propagated and -> or to every cue."""
import json

from vstudio import en_common as EN
from vstudio import proofread as PR

TRANSCRIPT = "\n".join([
    "In this part we open the port for the API.", "Then the second part is the client side login.",
    "After that we make the request, and after the call we check the failure.",
    "The holder of the token sends a header. The service here talks to the service layer.",
    "We use OAuth and OAuth2 with a mock server. We store public and private data.",
    "The client side code uses Hibrid search. Our avatar shows after login.",
])

BAD = [("part", "port"), ("make", "mock"), ("after", "avatar"), ("failure", "filter"), ("holder", "header"),
       ("client side", "client ID"), ("service here", "service layer")]


def _llm(fixes):
    def call(system, prompt, model):
        if system == PR.GLOSSARY_SYSTEM:
            return json.dumps({"terms": ["port", "mock", "avatar", "filter", "header", "client ID", "service layer",
                                         "OAuth", "OAuth2"],
                               "fixes": [dict(f, why="sounds like the glossary term " + f["to"], confidence=0.99)
                                         for f in fixes]}), {"input": 1, "output": 1}
        if system == PR.CHECK_SYSTEM:
            return json.dumps({"reject": []}), {"input": 1, "output": 1}
        return json.dumps({"fixes": []}), {"input": 1, "output": 1}
    return call


def test_common_english_words_are_never_glossary_sources():
    for a, b in BAD:
        assert "common English word" in PR.check_glossary_fix({"from": a, "to": b}, TRANSCRIPT), (a, b)
    assert PR.check_glossary_fix({"from": "Hibrid", "to": "Hybrid"}, TRANSCRIPT) is None     # a non-word still is
    assert EN.is_common("parts") and EN.is_common("holders") and EN.is_common("making")
    assert not EN.is_common("RM") and not EN.is_common("IT") and EN.all_function("and") and not EN.all_common("OAuth2")


def test_build_glossary_drops_common_words_and_contradictory_pairs():
    fixes = [{"from": a, "to": b} for a, b in BAD] + [{"from": "OAuth2", "to": "OAuth"}, {"from": "OAuth", "to": "OAuth2"},
                                                      {"from": "Hibrid", "to": "Hybrid"}]
    g = PR.build_glossary(TRANSCRIPT, call=_llm(fixes))
    assert {f["from"]: f["to"] for f in g["fixes"]} == {"Hibrid": "Hybrid"}
    why = {r["from"]: r["reason"] for r in g["rejected"]}
    for a, _ in BAD:
        assert "common English word" in why[a]
    assert "contradicts" in why["OAuth"] and "contradicts" in why["OAuth2"]


def test_an_old_glossary_json_with_bad_fixes_is_not_applied():
    old = dict(terms=["port"], fixes=[{"from": a, "to": b, "count": 1} for a, b in BAD]
               + [{"from": "OAuth2", "to": "OAuth"}, {"from": "OAuth", "to": "OAuth2"}, {"from": "Hibrid", "to": "Hybrid"}])
    cues = [dict(start=i, end=i + 1, text=t) for i, t in enumerate(TRANSCRIPT.splitlines())]
    res = PR.proofread(cues, provider="none", glossary=old, entities=False)
    assert [c["text"] for c in res["cues"]] == [c["text"].replace("Hibrid", "Hybrid") for c in cues]
    assert {r["from"] for r in res["rejected"] if r.get("source") == "glossary"} >= {a for a, _ in BAD} | {"OAuth"}


def test_function_word_swaps_are_rejected_and_never_propagated():
    cues = [dict(start=0, end=1, text="We store public and private data."),
            dict(start=1, end=2, text="Users and admins log in."), dict(start=2, end=3, text="Read and write.")]

    def llm(system, prompt, model):
        return json.dumps({"fixes": [{"i": 0, "from": "and", "to": "or"}]}), {"input": 1, "output": 1}
    res = PR.proofread(cues, call=llm, passes=1, entities=False)
    assert [c["text"] for c in res["cues"]] == [c["text"] for c in cues]
    assert not [c for c in res["changes"] if c["source"] in ("llm", "llm-propagated")]
    assert any("function words" in r["reason"] for r in res["rejected"])


def test_a_common_word_fix_propagates_only_in_the_same_context():
    cues = [dict(start=0, end=1, text="we open part 8080 here"), dict(start=1, end=2, text="then open part 8080 again"),
            dict(start=2, end=3, text="the first part of the class"), dict(start=3, end=4, text="Chunk the doc in trunking mode"),
            dict(start=4, end=5, text="trunking is next")]

    def llm(system, prompt, model):
        return json.dumps({"fixes": [{"i": 0, "from": "part", "to": "port"},
                                     {"i": 3, "from": "trunking", "to": "chunking"}]}), {"input": 1, "output": 1}
    res = PR.proofread(cues, call=llm, passes=1, entities=False)
    texts = [c["text"] for c in res["cues"]]
    assert texts[:3] == ["we open port 8080 here", "then open port 8080 again", "the first part of the class"]
    assert texts[4] == "chunking is next"                       # a rare token still propagates everywhere


def test_glossary_spelling_check_never_respells_common_words_or_other_terms():
    """The real source of 'sounds like the glossary term port': the entity verifier's glossary-spelling pass."""
    from vstudio import entities as E
    terms = ["port", "mock", "avatar", "filter", "header", "client ID", "service layer", "OAuth", "OAuth2", "Hybrid"]
    r = E.verify(TRANSCRIPT, glossary=terms)
    assert {f["from"]: f["to"] for f in r["fixes"]} == {"Hibrid": "Hybrid"}
    g = PR.build_glossary(TRANSCRIPT, call=_llm([]))             # the LLM proposes nothing: same result
    assert {f["from"]: f["to"] for f in g["fixes"]} == {}          # Hybrid is not in _llm's terms
    assert E.verify("we use oauth here", glossary=["OAuth", "OAuth2"])["fixes"][0]["to"] == "OAuth"   # case still fixed
