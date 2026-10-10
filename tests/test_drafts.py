"""The engine drafts the files an author checkpoint asks for (vstudio.project.drafts): promo-recut's keep spans from
the transcript + her request (a fake model: its cuts become cut.body, its labels the review), the review the Inbox
shows (the transcript with kept / cut parts, never the YAML), the decision the autopilot records, her adjustment by
selecting what to keep, "ask in plain words" (redraft), the rules when there is no model (nothing is cut, said so),
and the seeded template / SYNTHETIC example never being taken for an answer."""
import json
import os
import shutil

import pytest
import yaml

import _batch_helpers as H
from vstudio.project import autopilot as AP
from vstudio.project import drafts as DR
from vstudio.project.adapters import promo as PR
from vstudio.project.core import Project

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
TESTS = os.path.dirname(os.path.abspath(__file__))
# three sentences: an unfinished opening ("大家 好 嗯"), the talk, a detour about Hedra, the close
WORDS = [("大家", .4), ("好", .3), ("嗯。", .3),
         ("今天", .4), ("讲", .3), ("可灵", .4), ("和", .2), ("Seedance。", .5),
         ("顺便", .4), ("说", .3), ("一下", .3), ("Hedra。", .5),
         ("最后", .4), ("总结", .4), ("一下。", .35)]
REQUEST = "剪辑这条口播：删掉开头没讲完的开场，以及讲 Hedra 的整段。正文 1.5 倍速。"


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    monkeypatch.setenv("VSTUDIO_LLM_PROVIDER", "none")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(scope="module")
def talk(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("talk")
    x, truth, dur = H.synth_speech(WORDS)                    # short pauses: one sentence per "。"
    src = H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    tp = d / "truth.json"
    tp.write_text(json.dumps([{k: w[k] for k in ("w", "t", "te")} for w in truth], ensure_ascii=False))
    return dict(video=src, truth=str(tp))


def fake_model(reply, seen=None):
    def complete(task, system, prompt, **kw):
        if seen is not None:
            seen.append(dict(task=task, system=system, prompt=prompt))
        return dict(json=reply, text=json.dumps(reply), provider="claude-code", model="test")
    return complete


def promo(tmp_path, talk, monkeypatch, name="p"):
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", talk["truth"])
    p = Project.create(str(tmp_path / name), recipe="promo-recut", inputs=dict(talk=[talk["video"]]),
                       params=dict(language="zh"),
                       spec=dict(plugin_paths=[TESTS], asr=dict(transcriber="_batch_helpers:fake_transcriber")))
    p.data["prompt"] = REQUEST
    p.save()
    return p


def keep_payload(p):
    pend = [x for x in p.pending() if x["id"] == "keep"]
    assert pend, p.pending()
    with open(os.path.join(p.state_dir, "checkpoints", pend[0]["item"], "keep.json"), encoding="utf-8") as f:
        return pend[0]["item"], json.load(f)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_keep_spans_are_drafted_from_the_transcript_and_her_request(tmp_path, talk, monkeypatch):
    seen = []
    monkeypatch.setattr("vstudio.llm.complete", fake_model(dict(
        cuts=[dict(**{"from": 1, "to": 1}, label="没讲完的开场"), dict(**{"from": 3, "to": 3}, label="Hedra 那段")],
        hooks=[], summary="去掉开场和 Hedra"), seen))
    p = promo(tmp_path, talk, monkeypatch)
    p.run()
    item, pay = keep_payload(p)
    # the file is a real draft for HER video: no SYNTHETIC example, the cut she asked for, the speed she named
    cfg_path = pay["file"]
    text = open(cfg_path, encoding="utf-8").read()
    assert "SYNTHETIC" not in text and "drafted by Reelfold" in text
    cfg = yaml.safe_load(text)
    sents = PR.sentences(PR.transcript(DR.Ctx(p.dir, item, dict(_inputs=dict(talk=[talk["video"]])), "promo-recut")))
    assert [s["text"] for s in sents] == ["大家好嗯。", "今天讲可灵和Seedance。", "顺便说一下Hedra。", "最后总结一下。"]
    body = cfg["cut"]["body"]
    assert len(body) == 2 and body[0][0] < sents[1]["t"] < body[0][1] and body[1][0] < sents[3]["t"] < body[1][1]
    assert not any(a <= (sents[2]["t"] + sents[2]["te"]) / 2 <= b for a, b in body)
    assert cfg["rates"]["body"] == 1.5
    # the model read the transcript and the request (in the reply language)
    assert seen[0]["task"] == "planner" and "[3]" in seen[0]["prompt"] and "Hedra" in seen[0]["prompt"]
    assert "Simplified Chinese" in seen[0]["system"]
    # the payload: a default answer (a real draft), and the review the Inbox shows instead of the file
    assert pay["draft_state"] == "drafted" and pay["default"] == dict(done=True) and pay["draft_by"] == "ai"
    rv = pay["review"]
    assert rv["kind"] == "keep-spans" and [s["keep"] for s in rv["segments"]] == [False, True, False, True]
    assert rv["segments"][2]["label"] == "Hedra 那段"
    assert rv["summary"]["code"] == "draft.keep" and rv["summary"]["params"]["cuts"] == ["没讲完的开场", "Hedra 那段"]
    assert 0 < rv["kept_s"] < rv["total_s"]
    # on autopilot this is decided by the AI's draft, recorded with its reason
    d = AP.decide(p, dict(pay, id="keep", item=item))
    assert d["by"] == "ai" and d["value"] == dict(done=True) and d["reason_code"] == "drafted"
    assert d["params"]["summary"] == "draft.keep" and d["params"]["kept"] == rv["kept_s"]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_her_selection_and_plain_words_change_the_draft(tmp_path, talk, monkeypatch):
    monkeypatch.setattr("vstudio.llm.complete", fake_model(dict(cuts=[dict(**{"from": 3, "to": 3}, label="Hedra")])))
    p = promo(tmp_path, talk, monkeypatch, "q")
    p.run()
    item, pay = keep_payload(p)
    segs = pay["review"]["segments"]
    # "ask in plain words": keep the Hedra part after all -> a new draft, the stored payload updated at once
    monkeypatch.setattr("vstudio.llm.complete", fake_model(dict(cuts=[dict(**{"from": 1, "to": 1}, label="开场")])))
    r = DR.redraft(Project(p.dir), "keep", item, instruction="Hedra 那段留着，只删开场")
    assert r["ok"] and [s["keep"] for s in r["review"]["segments"]] == [False, True, True, True]
    _, pay2 = keep_payload(Project(p.dir))
    assert [s["keep"] for s in pay2["review"]["segments"]] == [False, True, True, True]
    assert any(e["event"] == "redrafted" and e["instruction"] for e in AP.history(Project(p.dir)))
    # she selects what to keep in the transcript: cut.body becomes exactly that, the review follows
    keep = [[segs[1]["t"], segs[1]["te"]], [segs[3]["t"], segs[3]["te"]]]
    p = Project(p.dir)
    p.answer("keep", dict(done=True, spans=keep), items=[item])
    cfg = yaml.safe_load(open(pay["file"], encoding="utf-8"))
    assert cfg["cut"]["body"] == [[round(a, 2), round(b, 2)] for a, b in keep]
    side = DR.read_side(pay["file"], "keep")
    assert side["by"] == "her" and [s["keep"] for s in side["review"]["segments"]] == [False, True, False, True]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_no_model_keeps_everything_and_says_so(tmp_path, talk, monkeypatch):
    p = promo(tmp_path, talk, monkeypatch, "r")
    p.run()
    _, pay = keep_payload(p)
    rv = pay["review"]
    assert pay["draft_state"] == "drafted" and pay["draft_by"] == "rules"
    assert all(s["keep"] for s in rv["segments"]) and rv["summary"]["code"] == "draft.keep-all-rules"
    assert "SYNTHETIC" not in open(pay["file"], encoding="utf-8").read()


def test_a_seeded_template_is_never_an_answer(tmp_path, monkeypatch):
    """launch-kit's config is seeded with its example: with no model nothing is drafted, the autopilot blocks (her
    Inbox asks), it never runs on "Acme Notes"; with a model the AI writes the real file and that is the answer."""
    p = Project.create(str(tmp_path / "lk"), recipe="launch-kit", params={})
    p.data["prompt"] = "Launch video for Inkwell, my note app"
    p.save()
    r = p.run(autopilot=True)
    assert {b["checkpoint"] for b in r["blocked"]} == {"config"}
    pend = [x for x in p.pending() if x["id"] == "config"][0]
    pay_path = os.path.join(p.state_dir, "checkpoints", pend["item"], "config.json")
    pay = json.load(open(pay_path, encoding="utf-8"))
    assert pay["draft_state"] == "template" and pay["default"] is None and pay["review"] is None
    assert pay.get("content") is None                        # the example is never shown as hers
    ev = [e for e in AP.history(p) if e["event"] == "blocked"]
    assert ev and ev[0]["blocker"] == "needs-input"
    # with a model: the AI drafts it, the payload has a plain review, the autopilot takes it (recorded as the AI's)
    good = "product:\n  name: Inkwell\n  tagline: Notes that write back\nfeatures:\n  - Quick capture\n  - Search\n"
    monkeypatch.setattr("vstudio.llm.complete", fake_model(dict(content=good, summary="Inkwell 的产品信息")))
    res = DR.redraft(Project(p.dir), "config", pend["item"])
    assert res["ok"] and res["state"] == "drafted"
    rv = res["review"]
    assert rv["kind"] == "outline" and rv["summary"] == dict(code="draft.generic", params=dict(text="Inkwell 的产品信息"))
    assert dict(code="draft.kn", params=dict(label="Features", n=2)) in rv["lines"]
    pay = json.load(open(pay_path, encoding="utf-8"))
    assert pay["default"] == dict(done=True) and pay["draft_state"] == "drafted"
    # a reply that is not the format (or the template itself) is not a draft
    monkeypatch.setattr("vstudio.llm.complete", fake_model(dict(content="{not: [yaml")))
    assert DR.generic(DR.Ctx(p.dir, pend["item"], {}, "launch-kit"), p.checkpoint("config"),
                      str(tmp_path / "x.yaml")) is None


def test_states_and_the_outline_never_show_syntax(tmp_path):
    f = tmp_path / "a.yaml"
    assert DR.state(str(f)) == "missing"
    f.write_text("# SYNTHETIC example\nname: Acme\n")
    assert DR.state(str(f)) == "template"
    f.write_text("name: Mine\nitems: [1, 2, 3]\nnested: {title: Hello}\n")
    assert DR.state(str(f), cp="c") == "hers"
    rv = DR.outline_review(str(f))
    assert rv["lines"] == [dict(code="draft.kv", params=dict(label="Name", value="Mine")),
                           dict(code="draft.kn", params=dict(label="Items", n=3)),
                           dict(code="draft.kv", params=dict(label="Nested", value="Hello"))]
    j = tmp_path / "pairs.json"
    j.write_text(json.dumps([dict(question="Why?", answer="Because"), dict(question="How?")]))
    assert DR.outline_review(str(j))["lines"][0]["params"]["label"] == "Why?"
    m = tmp_path / "SCRIPT.md"
    m.write_text("# Hook\nSpoken line\n# Idea\n")
    rv = DR.outline_review(str(m))
    assert rv["kind"] == "text" and "Spoken line" in rv["text"] and rv["summary"]["params"]["n"] == 2


def test_speeds_named_in_the_request():
    assert PR.speeds("hooks 按 1,2,6,7 的顺序 2 倍速，正文 1.5 倍速") == dict(body=1.5, hooks=2.0)
    assert PR.speeds("hooks at 2x, the rest at 1.25x") == dict(body=1.25, hooks=2.0)
    assert PR.speeds("剪干净") == dict(body=None, hooks=None)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_packaging_is_drafted_from_the_kept_talk_and_her_files(tmp_path, talk, monkeypatch):
    """Captions from the cut; her screen recording full screen while she talks about it, a screenshot card, the
    finished clip in the montage, chapters / end card / cover / post - each placement checked (inside the kept
    talk, no overlap, real files); without a model only the captions (said so)."""
    import subprocess
    monkeypatch.setenv("VSTUDIO_TEST_TRUTH", talk["truth"])
    media = tmp_path / "m"
    media.mkdir()
    rec = str(media / "Screen Recording 2026-10-07 at 21.16.22.mov")
    fin = str(media / "FinePrint_kling-en.mp4")
    for f in (rec, fin):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=6",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", f], check=True)
    shot = media / "截图1-MiniMax画布.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=white:s=400x300", "-frames:v", "1",
                    str(shot)], check=True)
    item = tmp_path / "items" / "AIGC"
    (item / "work").mkdir(parents=True)
    (tmp_path / "project.yaml").write_text(yaml.safe_dump(dict(prompt=REQUEST, name="AIGC")), encoding="utf-8")
    params = dict(_inputs=dict(talk=[talk["video"]], broll=[rec, fin], screenshots=[str(shot)]), language="zh",
                  _item_dir=str(item), _project_dir=str(tmp_path))
    ctx = DR.Ctx(str(tmp_path), "AIGC", params, "promo-recut",
                 dict(plugin_paths=[TESTS], asr=dict(transcriber="_batch_helpers:fake_transcriber")))
    sents = PR.sentences(PR.transcript(ctx))
    cfg = item / "promo.config.yaml"
    body = [[sents[1]["t"] - .05, sents[1]["te"] + .05], [sents[3]["t"] - .05, sents[3]["te"] + .05]]
    cfg.write_text(yaml.safe_dump(dict(cut=dict(body=body))), encoding="utf-8")
    (item / "work" / "draft_subs.txt").write_text(
        "[\n" + ",\n".join(json.dumps([s["t"], s["te"], s["text"]], ensure_ascii=False) for s in (sents[1], sents[3]))
        + "\n]\n\nEdit the text ...\n", encoding="utf-8")
    a, b = sents[1]["t"], sents[1]["te"]
    seen = []
    monkeypatch.setattr("vstudio.llm.complete", fake_model(dict(
        pip=[dict(file=os.path.basename(rec), start=a, end=b, media_start=1.0, tag="MiniMax 画布")],
        cards=[dict(file=shot.name, start=a + .2, end=b - .2),                       # overlaps the recording: dropped
               dict(file=shot.name, start=sents[3]["t"], end=sents[3]["te"])],
        montage=[dict(file=os.path.basename(fin), start=1.0, end=4.0, label="可灵"),
                 dict(file="made-up.mp4", start=0, end=2)],                          # not her file: dropped
        chapters=[["start", "开场"], [sents[3]["t"], "总结"]], end_card=dict(main="你最想用哪个？", sub="评论区告诉我"),
        cover=dict(title=["AIGC 视频", "四家横评"], talk_at=a), post=dict(title="四家 AI 视频横评", body=["一句话"], tags=["AI"]),
        summary="放好了"), seen))
    cp = Project.create(str(tmp_path / "x"), recipe="promo-recut", inputs=dict(talk=[talk["video"]])).checkpoint("package")
    rec_ = DR.ensure(ctx, cp, str(cfg))
    assert rec_["by"] == "ai" and "MiniMax" not in seen[0]["system"] and "Screen Recording" in seen[0]["prompt"]
    out = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert out["cut"]["body"] == body                                     # her cut stays as it was
    assert [s[2] for s in out["subtitles"]["body"]] == [sents[1]["text"], sents[3]["text"]]
    assert out["pip"] == [dict(start=round(a, 2), end=round(b, 2), video=rec, media_start=1.0, tag="MiniMax 画布")]
    assert [c["start"] for c in out["cards"]] == [round(sents[3]["t"], 2)]
    assert out["montage"]["clips"] == [[os.path.basename(fin), 1.0, 4.0, "可灵"]]
    assert out["chapters"][0] == ["start", "开场"] and out["end_card"]["main"] == "你最想用哪个？"
    assert out["cover"] == dict(title=["AIGC 视频", "四家横评"], photo=dict(talk_at=a))
    rv = DR.review(ctx, cp, str(cfg))
    assert rv["kind"] == "package" and rv["summary"]["code"] == "draft.package"
    codes = {x["code"]: x["params"] for x in rv["lines"]}
    assert codes["draft.pkg.captions"] == dict(n=2) and codes["draft.pkg.pip"]["n"] == 1
    assert codes["draft.pkg.cards"] == dict(n=1, of=1) and codes["draft.pkg.montage"] == dict(n=1, of=1)
    # no model: the captions only, and the review says the footage was not placed
    monkeypatch.setattr("vstudio.llm.complete", lambda *a, **k: dict(provider="none"))
    DR.ensure(ctx, cp, str(cfg), force=True)
    out = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert "pip" not in out and len(out["subtitles"]["body"]) == 2
    assert DR.review(ctx, cp, str(cfg))["summary"] == dict(code="draft.package-rules", params=dict(captions=2, placed=0,
                                                                                                  left=2))


def test_explainer_subtitle_pairing_is_the_workflows_own_draft(tmp_path):
    """Explainer "Subtitle pairing" asked her to fix cues.draft.txt and save it as cues.txt: the engine takes its own
    pairing as the draft (rules), she only checks it."""
    item = tmp_path / "items" / "e1"
    (item / "subtitles").mkdir(parents=True)
    (item / "subtitles" / "cues.draft.txt").write_text("## 1\nHello there || 你好\n## 2\nNext idea || 下一个想法\n",
                                                      encoding="utf-8")
    p = Project.create(str(tmp_path / "ex"), recipe="explainer", inputs=dict(topic="sleep"))
    cp = p.checkpoint("cues")
    ctx = DR.Ctx(str(tmp_path), "e1", dict(_item_dir=str(item)), "explainer")
    path = str(item / "subtitles" / "cues.txt")
    assert DR.state(path, None, cp, "explainer") == "missing"
    rec = DR.ensure(ctx, cp, path)
    assert rec["by"] == "rules" and open(path, encoding="utf-8").read().startswith("## 1\nHello there || 你好")
    assert DR.state(path, None, cp, "explainer") == "drafted"
    assert DR.review(ctx, cp, path)["summary"] == dict(code="draft.items", params=dict(n=2))
