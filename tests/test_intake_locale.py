"""vstudio.intake: the plan card's model-written texts (questions, risks, why) follow the caller's UI language
(``ui_lang`` / ``--ui-lang``), else the request's - never a hard-coded Chinese. Mocked model, no media work."""
import json

import pytest

from test_intake import _iso, build  # noqa: F401 - the isolation fixture + fake analyses

from vstudio.intake import cli as CLI
from vstudio.intake import inventory as I
from vstudio.intake import plan as PL

PROMPT = "Cut this talk into vertical clips for TikTok and Xiaohongshu"


def _model(seen, question="Which speaker is the host?"):
    def call(system, body):
        seen.update(system=system, doc=json.loads(body.split("\n\n")[0]))
        return dict(json=dict(projects=[dict(recipe="talkinghead", name="talk", materials=["f1"],
                                             inputs=dict(video=["f1"]), items=dict(method="per-file"))],
                              questions=[dict(project=0, text=question, options=["A", "B"], default="A")],
                              risks=["Short source"], summary_zh="Four clips."), model="mock")
    return call


def test_system_prompt_has_no_hard_coded_chinese_for_card_texts():
    s = PL.SYSTEM.format(phrases="")
    assert "<zh" not in s and "for a Chinese creator" not in s
    assert '"text": "<reply_language>"' in s and '"risks": ["<reply_language>"]' in s
    assert "reply_language" in s.split("Phrase table")[0]         # the rule that explains it


@pytest.mark.parametrize("ui,expect", [("en", "English"), ("zh", "Simplified Chinese"), ("zh-CN", "Simplified Chinese"),
                                       ("fr", "French"), (None, "English")])
def test_reply_language_follows_ui_then_request(tmp_path, ui, expect):
    seen = {}
    plan = PL.make_plan(PROMPT, analysis=build("talk", tmp_path), asr="off", call=_model(seen), ui_lang=ui)
    assert seen["doc"]["reply_language"] == expect
    assert plan["ui_lang"] == {"English": "en", "Simplified Chinese": "zh", "French": "fr"}[expect]
    assert plan["questions"][0]["text"] == "Which speaker is the host?"
    assert not PL.validate(plan)


def test_default_language_for_a_chinese_request_and_an_unknown_ui(tmp_path):
    seen = {}
    PL.make_plan("这段口播剪干净发小红书", analysis=build("talk", tmp_path), asr="off", call=_model(seen), ui_lang="de")
    assert seen["doc"]["reply_language"] == "Simplified Chinese"
    assert PL.reply_lang(PROMPT) == "en" and PL.reply_lang("剪一条", "fr-FR") == "fr"


def test_revise_keeps_the_plan_language_unless_told(tmp_path, monkeypatch):
    a = build("talk", tmp_path)
    plan = PL.make_plan(PROMPT, analysis=a, asr="off", call=_model({}), ui_lang="fr")
    monkeypatch.setattr(I, "analyze", lambda *a_, **k: a)
    seen = {}
    p2 = PL.revise(plan, "也发抖音", call=_model(seen))                # a Chinese follow-up: still French
    assert seen["doc"]["reply_language"] == "French" and p2["ui_lang"] == "fr"
    p3 = PL.revise(p2, "only TikTok", call=_model(seen), ui_lang="zh")
    assert seen["doc"]["reply_language"] == "Simplified Chinese" and p3["ui_lang"] == "zh"


def test_cli_ui_lang_flag():
    ap = CLI.build_parser()
    assert ap.parse_args(["plan", "--prompt", "x", "--ui-lang", "fr"]).ui_lang == "fr"
    assert ap.parse_args(["revise", "--plan", "p.json", "--prompt", "x", "--ui-lang", "en"]).ui_lang == "en"
    assert ap.parse_args(["plan", "--prompt", "x"]).ui_lang is None
    with pytest.raises(SystemExit):
        ap.parse_args(["plan", "--prompt", "x", "--ui-lang", "de"])
