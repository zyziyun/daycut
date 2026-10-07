"""Named-entity verification after ASR (vstudio.entities): CLDR place names + cities with sound-alike correction
(宏都拉斯 -> 洪都拉斯), regional variants kept per content locale (纽西兰 / 新西兰), glossary + model spellings for
other entities (Wells Fargo), and ONE set of fixes for captions, cards and post copy."""
import json

import pytest

from vstudio import entities as E, proofread as PR

pytestmark = pytest.mark.skipif(not E.territories("zh_Hans") or PR.pinyin_of("洪") is None,
                                reason="needs babel + a pinyin backend (requirements.txt)")


def test_honduras_homophone_is_corrected_in_zh_hans():
    r = E.verify("这次去了宏都拉斯，宏都拉斯的咖啡很好喝", locale="zh_Hans")
    f = r["fixes"][0]
    assert (f["from"], f["to"], f["source"], f["guess"], f["count"]) == ("宏都拉斯", "洪都拉斯", "cldr", False, 2)
    assert PR.faithful("宏都拉斯", "洪都拉斯") is None                  # a sound-alike: passes the validator
    assert E.fix_text("宏都拉斯的咖啡", r["fixes"]) == "洪都拉斯的咖啡"


def test_regional_variant_kept_per_content_locale():
    r = E.verify("我在纽西兰住过，新西兰很美", locale="zh_Hans")
    assert r["fixes"] == []                                            # 纽西兰 sounds different: the speaker's word
    v = next(e for e in r["entities"] if e["text"] == "纽西兰")
    assert v["variant"] == "regional"
    assert any(e["text"] == "新西兰" and e["source"] == "cldr" for e in r["entities"])
    tw = E.verify("他去了洪都拉斯和紐西蘭", locale="zh-TW")             # zh_Hant content: the TW standard
    assert [(f["from"], f["to"]) for f in tw["fixes"]] == [("洪都拉斯", "宏都拉斯")]


def test_ordinary_speech_is_not_a_place():
    assert E.verify("圣诞到了，我们去纽约过节", locale="zh_Hans")["fixes"] == []


def test_english_entity_from_glossary_and_model():
    r = E.verify("I opened an account at wells fargo, then Wels Fargo called.", glossary=["Wells Fargo"])
    assert {(f["from"], f["to"]) for f in r["fixes"]} == {("wells fargo", "Wells Fargo"), ("Wels Fargo", "Wells Fargo")}
    fixes, flagged = E.parse_llm([dict(text="Wels Fargo", standard="Wells Fargo", kind="org", certain=True),
                                  dict(text="Goldman", standard="Goldman Sachs", kind="org", certain=False)],
                                 "Wels Fargo and Goldman")
    assert [(f["from"], f["to"]) for f in fixes] == [("Wels Fargo", "Wells Fargo")]
    assert flagged[0]["guess"] and flagged[0]["to"] == "Goldman Sachs"


def test_proofread_applies_entities_to_captions_without_a_model():
    cues = [dict(start=0, end=2, text="我去年去了宏都拉斯"), dict(start=2, end=4, text="后来又去了纽西兰")]
    r = PR.proofread(cues, provider="none")
    assert r["cues"][0]["text"] == "我去年去了洪都拉斯" and r["cues"][1]["text"] == "后来又去了纽西兰"
    ch = next(c for c in r["changes"] if c["source"] == "entity")
    assert "宏都拉斯 -> 洪都拉斯" in ch["why"] and not ch.get("guess")
    assert r["entities"]["fixes"][0]["to"] == "洪都拉斯"
    off = PR.proofread(cues, provider="none", entities=False)
    assert off["cues"][0]["text"] == "我去年去了宏都拉斯"


def test_glossary_merges_the_models_entity_answers():
    def call(system, prompt, model):
        if "entities" in system:
            return json.dumps({"terms": ["Wells Fargo"], "fixes": [], "entities": [
                {"text": "Wels Fargo", "standard": "Wells Fargo", "kind": "org", "certain": True},
                {"text": "Goldman", "standard": "Goldman Sachs", "kind": "org", "certain": False}]}), {}
        return json.dumps({"fixes": [], "reject": []}), {}
    g = PR.build_glossary("I banked at Wels Fargo. Goldman too. 后来去了宏都拉斯。", call=call)
    got = {(f["from"], f["to"]) for f in g["fixes"]}
    assert ("Wels Fargo", "Wells Fargo") in got and ("宏都拉斯", "洪都拉斯") in got
    assert any(x["to"] == "Goldman Sachs" for x in g["entities"]["flagged"])


def test_one_truth_for_captions_cards_and_post_copy():
    from vstudio.batch.stages import entity_post
    cues = [dict(start=0, end=2, text="宏都拉斯的咖啡")]
    fixes = PR.proofread(cues, provider="none")["entities"]["fixes"]
    post = entity_post(dict(title="宏都拉斯咖啡之旅", body="在宏都拉斯喝咖啡", tags=["宏都拉斯", "旅行"],
                            notes=["宏都拉斯 很远"]), fixes)
    assert post["title"] == "洪都拉斯咖啡之旅" and post["body"] == "在洪都拉斯喝咖啡"
    assert post["tags"] == ["洪都拉斯", "旅行"] and post["notes"] == ["洪都拉斯 很远"]
    # without proofread output the copy is still checked on its own text
    assert entity_post(dict(title="宏都拉斯"))["title"] == "洪都拉斯"
