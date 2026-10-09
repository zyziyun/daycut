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


# --------------------------------------------------------------------------- no AI: the rule planner's texts
FALLBACK = {
    "en": ("Whose faces should be hidden?", ["Hide everyone but me", "Hide no one (they agreed)", "I'll pick"],
           ["Narration", "Music only"]),
    "zh": ("要遮哪几位的脸？", ["除我以外全部遮", "都不遮（已获同意）", "我来指定"], ["旁白", "纯音乐"]),
    "fr": ("Quels visages masquer ?", ["Masquer tout le monde sauf moi", "Ne masquer personne (accord donné)",
                                       "Je choisis"], ["Narration", "Musique seule"]),
}


@pytest.mark.parametrize("ui", ["en", "zh", "fr"])
def test_rule_planner_questions_and_options_follow_the_ui(tmp_path, ui):
    q_start, mask, narration = FALLBACK[ui]
    p = PL.make_plan("Cut this podcast into clips", analysis=build("podcast", tmp_path / "a"), asr="off",
                     provider="none", ui_lang=ui)
    assert p["planner"]["fallback"] is True
    q = p["questions"][0]
    assert q["text"].startswith(q_start) and q["options"] == mask and q["default"] == mask[0]
    assert q["message"]["code"] == "intake.question.mask-faces"          # still coded for the desk
    p = PL.make_plan("Make a photo story from my trip", analysis=build("photos", tmp_path / "b"), asr="off",
                     provider="none", ui_lang=ui)
    assert p["questions"][0]["options"] == narration and p["questions"][0]["default"] == narration[0]


@pytest.mark.parametrize("ui,want", [("en", "no export preset yet"), ("zh", "还没有导出预设"),
                                     ("fr", "pas encore de préréglage")])
def test_rule_risks_follow_the_ui(tmp_path, ui, want):
    p = PL.make_plan("这段口播剪干净，发快手", analysis=build("talk", tmp_path), asr="off", provider="none", ui_lang=ui)
    risk = next(r for r in p["risks_info"] if r["code"] == "intake.risk.unsupported-platform")
    text = p["risks"][p["risks_info"].index(risk)]
    assert want in text


def test_revise_not_understood_in_the_plan_language(tmp_path, monkeypatch):
    a = build("talk", tmp_path)
    plan = PL.make_plan(PROMPT, analysis=a, asr="off", provider="none", ui_lang="fr")
    monkeypatch.setattr(I, "analyze", lambda *a_, **k: a)
    p2 = PL.revise(plan, "qwerty zzz", provider="none")
    assert any(w.startswith("Modification non comprise : qwerty zzz") for w in p2["warnings"]), p2["warnings"]


# --------------------------------------------------------------------------- the summary's language tag
def test_summary_lang_from_the_model_or_the_template(tmp_path):
    def call(lang):
        def c(system, body):
            js = _model({})(system, body)
            js["json"].update(summary_zh="Quatre clips.", **({"summary_lang": lang} if lang else {}))
            return js
        return c
    p = PL.make_plan("Coupe cette vidéo en clips", analysis=build("talk", tmp_path), asr="off", call=call("fr"))
    assert p["summary_lang"] == "fr" and p["summary_zh"] == "Quatre clips."     # no English look line on French
    p = PL.make_plan(PROMPT, analysis=build("talk", tmp_path), asr="off", call=call("EN-us"))
    assert p["summary_lang"] == "en" and "look:" in p["summary_zh"]
    p = PL.make_plan(PROMPT, analysis=build("talk", tmp_path), asr="off", call=call("??"))
    assert p["summary_lang"] == "en"                                           # unreadable: the request's
    p = PL.make_plan("这段口播剪干净", analysis=build("talk", tmp_path), asr="off", provider="none", ui_lang="en")
    assert p["planner"]["fallback"] and p["summary_lang"] == "zh"             # the template follows the request
    assert '"summary_lang"' in PL.SYSTEM and not PL.validate(p)


def test_messages_in_french_and_lists():
    from vstudio import messages as M
    s = M.cs("intake.risk.no-video", "fr", recipe="vlog")
    assert s == "vlog : aucune vidéo trouvée" and s.info["code"] == "intake.risk.no-video"
    assert M.cs("intake.question", "fr", text="libre") == "libre"
    assert M.join(["a", "b"], "zh") == "a、b" and M.join(["a", "b"], "fr") == "a, b"
