"""Talking-head defaults the real-footage parity test exposed: one speed source (the format), titles within each
platform's limit at generation time, and the desk default = her look (记笔记 panels, keyword highlight, progress
bar, retouched cover, strict cleanup). Synthetic text / media only."""
import json
import os
import shutil
import subprocess

import pytest

from vstudio import clipcopy as CC
from vstudio import firstpass as FP
from vstudio import formats as F
from vstudio import publish
from vstudio.batch import stages as ST
from vstudio.batch import thfolder as TH
from vstudio.project import manifests as M
from vstudio.project.core import public_manifest

needs_ff = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


# ------------------------------------------------------------------------------------------------ 2. one speed
def test_talkinghead_recipe_reads_the_format_defaults():
    m = M.get("talkinghead")
    f = F.get("talking-head")
    d = M.param_defaults(m)
    assert d["speed"] == f["speed"]["body"] == 1.25            # not the old recipe 1.1
    assert d["hook_speed"] == f["speed"]["hook"] and d["cleanup_profile"] == f["cleanup"] == "tight"
    assert d["hook_count"] == f["hook_menu"] and d["note_cards"] is True and d["cover_retouch"] is True
    assert "default" not in m["params"]["properties"]["speed"]   # the number lives in one place only
    pub = public_manifest(m)["params"]["properties"]           # what the desk forms / intake catalog see
    assert pub["speed"]["default"] == 1.25 and pub["cleanup_profile"]["default"] == "tight"
    assert F.get("promo")["speed"]["inserts"] == 1.1          # 1.1x stays only for inserted 精选 footage


def test_persona_format_override_wins(monkeypatch):
    monkeypatch.setattr(F, "_persona_formats", lambda: {"talking-head": {"speed": {"body": 1.3}}})
    d = M.param_defaults(M.get("talkinghead"))
    assert d["speed"] == 1.3 and d["hook_speed"] == 1.5


def test_x_format_must_name_a_format_key():
    m = dict(M.get("talkinghead"))
    m["params"] = dict(m["params"], properties=dict(m["params"]["properties"],
                                                    speed=dict(m["params"]["properties"]["speed"], **{"x-format": "speed.nope"})))
    with pytest.raises(ValueError, match="speed.nope"):
        M.resolved_params(m, persona_formats={})


def test_intake_takes_speed_and_cleanup_from_the_format():
    from vstudio.intake import plan as PL
    m = M.get("talkinghead")
    params, sources = {}, {}
    ctx = dict(PL.context(), speed=1.1, cleanup="standard", cleanup_client=False)   # a generic persona speed / profile
    PL._apply_ctx_defaults(m, params, sources, ctx, {}, dict(files=[]))
    assert params["speed"] == 1.25 and params["cleanup_profile"] == "tight"
    assert sources["speed"] == sources["cleanup_profile"] == "format"
    params, sources = {}, {}
    PL._apply_ctx_defaults(m, params, sources, dict(ctx, cleanup="gentle", cleanup_client=True), {}, dict(files=[]))
    assert params["cleanup_profile"] == "gentle"              # a client's own setting still wins


def test_compose_scripts_fall_back_to_the_format():
    root = os.path.join(os.path.dirname(__file__), "..", "workflows", "talkinghead", "scripts")
    for f in ("vertical/compose.py", "build_filter.py"):
        src = open(os.path.join(root, f), encoding="utf-8").read()
        assert "formats" in src and "'body', 1.1" not in src and '"body", 1.1' not in src, f


# ------------------------------------------------------------------------------------------------ 3. titles
def test_fit_title_is_deterministic_and_says_what_it_did():
    long = "如何把一个入门岗，拍成你高攀不起的样子（真实经历分享）！！"
    t, note = publish.fit_title(long, "xiaohongshu")
    assert publish.title_len(t, "xiaohongshu") <= 20 and note and "xiaohongshu" in note and "parenthetical" in note
    assert publish.fit_title(long, "xiaohongshu") == (t, note)
    assert publish.fit_title("短标题", "xiaohongshu") == ("短标题", None)
    t, _ = publish.fit_title("How I landed an SDE offer at Amazon without a CS degree and what I learned", "xiaohongshu")
    assert publish.title_len(t, "xiaohongshu") <= 20 and not t.endswith(" ") and t.split()[-1] in (
        "How I landed an SDE offer at Amazon without a CS degree".split())          # never half a word
    t, note = publish.fit_title("学习新模式｜让AI给你做3b1b讲解视频，从零到一的完整教程", "xiaohongshu")
    assert publish.title_len(t, "xiaohongshu") <= 20 and "讲解视频" in t
    assert publish.title_limit(["instagram", "xiaohongshu:full", "douyin"]) == (20, "xiaohongshu")


def test_post_body_fits_the_title_per_platform_and_warns():
    long = "面试复盘：亚麻 SDE 入门岗是怎么拿到的，以及我踩过的所有坑和真实建议"
    warns = []
    text = publish.post_body("", "正文", platform="xiaohongshu", title=long, warn=warns.append, use_persona_tags=False)
    first = text.splitlines()[0]
    assert publish.title_len(first, "xiaohongshu") <= 20 and any("title shortened" in w for w in warns)
    yt = publish.post_body("", "正文", platform="youtube", title=long, warn=None, use_persona_tags=False)
    assert yt.splitlines()[0] == long                          # YouTube's 100 fits it as is


def test_generate_copy_asks_for_and_fits_a_title():
    seen = {}

    def fake(task, system, prompt, schema=None, provider=None):
        seen.update(system=system, schema=schema)
        return {"json": {"title": "这是一个特别特别特别特别长的小红书标题会超过二十个字的限制吧",
                         "hook": "开头", "body": "正文", "tags": ["求职"]}}
    out = publish.generate_copy("xiaohongshu", "transcript", lang="zh", complete=fake, warn=lambda *a: None)
    assert "title" in seen["schema"]["required"] and "<= 20" in seen["system"]
    assert publish.title_len(out["title"], "xiaohongshu") <= 20 and out["title_note"]
    assert out["text"].startswith(out["title"])


def test_firstpass_does_not_read_the_tag_line_as_a_title(tmp_path):
    post = tmp_path / "x.post.md"
    post.write_text("#AIEngineer #北美求职 #转码 #SDE #AI面试 #大厂面试 #程序员转行 #在职跳槽\n", encoding="utf-8")
    assert FP.load_post(str(post))[0] == ""                    # the parity "35.5-char title" was this line
    from vstudio import platform as P
    items = FP.check_post("", post.read_text(encoding="utf-8"), P.profile("xiaohongshu:full"), F.get("talking-head"))
    bad = [i for i in items if i["ok"] is False]
    assert [i["id"] for i in bad] == ["title"] and bad[0]["severity"] == "warn"


SENTS = [dict(t=float(k * 6), te=float(k * 6 + 5), text=x) for k, x in enumerate([
    "主要的原因就是你没有概念", "不知道什么样的公司是OK的", "有些大厂的组非常push", "有些地方更加注重流程",
    "我上一份工作是在亚麻", "亚麻的onboarding非常难", "landing非常的慢", "所以第一份工作的风格很重要",
    "它决定了你能不能适配一种风格", "这就是我的经验"])]


def test_clipcopy_model_draft_is_validated():
    def fake(task, system, prompt, schema=None, provider=None):
        assert task == "copy" and "[9]" in prompt and "<= 20" in system
        return {"provider": "fake", "json": {
            "title": "第一份工作的公司风格，决定了你以后能不能适应任何一种工作方式",
            "keywords": ["亚麻", "onboarding", "不存在的词"],
            "sections": [{"from": 0, "label": "选公司的概念问题", "title": "为什么会不适应",
                          "bullets": [{"at": 1, "text": "不知道什么样的公司是OK的，对吧对吧"}, {"at": 3, "text": "注重流程"}]},
                         {"from": 4, "label": "亚麻", "title": "亚麻经历",
                          "bullets": [{"at": 5, "text": "onboarding难"}, {"at": 99, "text": "landing慢"}]},
                         {"from": 2, "label": "乱序", "title": "x", "bullets": []}]}}
    d = CC.draft(SENTS, ["xiaohongshu:full"], glossary_terms=["landing"], complete=fake)
    assert d["source"] == "llm:fake"
    assert publish.title_len(d["title"], "xiaohongshu") <= 20 and d["title_note"]
    assert d["keywords"][:2] == ["亚麻", "onboarding"] and "不存在的词" not in d["keywords"] and "landing" in d["keywords"]
    assert [c[2] for c in d["chapters"]] == ["选公司的概念", "亚麻"] and d["chapters"][0][0] == 0.0
    assert d["chapters"][0][1] == d["chapters"][1][0] == 24.0 and d["chapters"][-1][1] == 59.0
    p0, p1 = d["panels"]
    assert p0[3] == [(6.0, "不知道什么样的公司是OK的"), (18.0, "注重流程")] and p0[1] <= 24.0
    assert p1[3][-1][0] == 54.0                               # an anchor past the end is clamped into its section
    assert any("dropped" in n for n in d["notes"])


def test_clipcopy_without_a_model_drafts_no_cards_and_says_so():
    d = CC.draft(SENTS, ["xiaohongshu:full"], glossary_terms=["亚麻"])
    assert d["source"] == "transcript" and d["panels"] == [] and d["chapters"] == []
    assert d["title"] and publish.title_len(d["title"], "xiaohongshu") <= 20
    assert "亚麻" in d["keywords"] and any("no text model" in n for n in d["notes"])


def test_export_drafts_the_title_from_compose_notes(tmp_path):
    notes = tmp_path / "notes.json"
    notes.write_text(json.dumps(dict(title="一个超过二十个字的标题一个超过二十个字的标题一个超过", source="llm:fake")),
                     encoding="utf-8")
    d = ST.draft_title(dict(title=""), None, ["xiaohongshu:full", "douyin"], str(notes))
    assert d["source"] == "llm:fake" and publish.title_len(d["title"], "xiaohongshu") <= 20 and d["note"]
    assert ST.draft_title(dict(title="她自己写的"), None, ["xiaohongshu"], str(notes)) is None
    cues = tmp_path / "cues.json"
    cues.write_text(json.dumps(dict(cues=[dict(start=s["t"], end=s["te"], text=s["text"]) for s in SENTS]),
                               ensure_ascii=False), encoding="utf-8")
    d = ST.draft_title(dict(), str(cues), ["xiaohongshu:full"])
    assert d["source"] == "transcript" and publish.title_len(d["title"], "xiaohongshu") <= 20


# ------------------------------------------------------------------------------------------------ 4. her look
def test_desk_default_engine_is_her_talking_head_look():
    d = M.param_defaults(M.get("talkinghead"))
    assert d["pipeline"] == "vtrack" and d["edit_style"] == "mixed"
    style = M.get("talkinghead")["params"]["properties"]["edit_style"]["x-map"]["mixed"]
    assert style["panels"] is True and style["progress"] == "refined"
    hooks = next(s for s in M.get("talkinghead")["stages"] if s["id"] == "hooks")
    assert "when" not in hooks                                 # the hook menu is offered on the default engine too


def test_note_cards_switch_does_not_collide_with_job_notes():
    """A job's ``notes`` are note lines (proofread context reads them as a list): the card switch is its own param."""
    ctx = ST.proofread_context({}, dict(note_cards=True, notes=["要点一"]))
    assert ctx["notes"] == ["要点一"] and "notes" not in M.param_defaults(M.get("talkinghead"))


def test_vtrack_config_carries_hooks_panels_chapters_keywords():
    sids = [[0.3, 1.0, "第一句"], [1.4, 2.6, "第二句是钩子"], [3.0, 4.0, "第三句"]]
    subs = [dict(sid=0, start=0.0, end=0.7, text="第一句"), dict(sid=1, start=0.7, end=1.8, text="第二句是钩子"),
            dict(sid=2, start=1.8, end=2.6, text="第三句")]
    hooks = TH.hook_ranges(dict(src=[1.35, 2.7]), sids, subs)
    assert hooks == [[(0.7, 1.8)]]
    assert TH.hook_ranges(dict(src=[9, 10]), sids, subs) == [] and TH.hook_ranges(None, sids, subs) == []
    notes = dict(keywords=["亚麻"], panels=[(0.7, 2.6, "要点", [(0.7, "第二句")])], chapters=[(0.0, 2.6, "开场")])
    ns = {}
    exec(TH.config_file(dict(_clip_id="c1", platforms=["xiaohongshu:full"], speed=1.25, hook_speed=1.5,
                             keywords=["RAG"]), {}, False, hooks, notes), ns)
    assert ns["HOOKS"] == hooks and ns["PANELS"] == notes["panels"] and ns["CHAPTERS"] == notes["chapters"]
    assert ns["KEYWORDS"] == ["RAG", "亚麻"] and ns["BODY_SPEED"] == 1.25 and ns["HOOK_SPEED"] == 1.5
    ns = {}
    exec(TH.config_file(dict(_clip_id="c1", speed=1.0), {}, False), ns)
    assert ns["BODY_SPEED"] == 1.0                             # "no speed-up" is kept, not replaced by a default


def test_draft_notes_applies_glossary_fixes_before_drafting():
    seen = {}

    def fake(task, system, prompt, schema=None, provider=None):
        seen["prompt"] = prompt
        return {"provider": "fake", "json": {"title": "t", "keywords": [], "sections": []}}
    subs = [dict(sid=0, start=0.0, end=2.0, text="我上一份工作在压码")]
    TH.draft_notes(subs, ["xiaohongshu:full"], dict(terms=["亚麻"], fixes=[{"from": "压码", "to": "亚麻"}]), None, fake)
    assert "亚麻" in seen["prompt"] and "压码" not in seen["prompt"]


@needs_ff
def test_cover_retouch_without_a_face_keeps_the_frame_and_says_so(tmp_path):
    from PIL import Image
    from vstudio.project.adapters.common import retouch_cover_frame
    fr = tmp_path / "f.jpg"
    Image.new("RGB", (1080, 1920), (180, 170, 160)).save(fr)
    out, ok = retouch_cover_frame(str(fr), str(tmp_path / "f.retouched.jpg"))
    assert (out, ok) == (str(fr), False)
