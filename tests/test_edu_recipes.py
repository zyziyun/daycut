"""Lesson -> knowledge-point clips, interview -> Q&A clips, bilingual captions (vstudio.lesson / qa / bilingual /
clipkit / avsync), their recipes (lesson-clips, interview-qa) and the intake routes to them. Synthetic fixtures
only (tone-burst "speech" on generated video, transcripts written here); translation through a stub model passed
in by the test - the code paths are the real ones."""
import json
import os
import shutil

import numpy as np
import pytest

from vstudio import avsync, bilingual as BL, lesson as L, qa as QA, subs as S

HAS_FFMPEG = bool(shutil.which("ffmpeg"))
media = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_TRANSLATE_PROVIDER",
              "VSTUDIO_LLM_LESSON_PLAN_PROVIDER", "VSTUDIO_LLM_ROUTES_FILE", "VSTUDIO_DIARIZE_MODEL",
              "VSTUDIO_CLIENTS"):
        monkeypatch.delenv(k, raising=False)


# --------------------------------------------------------------------------- fixtures
def transcript(lines, wps=2.6, gap=0.5, start=1.0):
    """[(text, pause_after) | text] -> whisper-like segments with word timings."""
    segs, t = [], start
    for item in lines:
        text, pause = (item, gap) if isinstance(item, str) else item
        ws = []
        for w in text.split():
            d = max(0.18, len(w) / (wps * 5))
            ws.append(dict(word=" " + w, start=round(t, 3), end=round(t + d, 3)))
            t += d + 0.06
        segs.append(dict(start=ws[0]["start"], end=ws[-1]["end"], text=text, words=ws))
        t += pause
    return dict(segments=segs, language="en")


LESSON = [
    "Good morning everyone, welcome back to class.", "Today we have three things to learn.",
    ('First, the phrase "break the ice".', 0.4),
    "Break the ice means to start a conversation with someone new.",
    "For example, at a party you can tell a joke to break the ice.",
    "Another example: a teacher plays a game on the first day to break the ice.",
    "So when you meet new colleagues, think about how to break the ice.",
    ("It is a very useful expression at work.", 2.8),
    "Now a common mistake.", "Many students say I am agree.", "Don't say I am agree, say I agree.",
    "Agree is a verb, so we do not need am.", "For example, I agree with you completely.", "Or, we agree on the plan.",
    ("Remember this one, it is very common.", 3.0),
    "Next, the word reluctant.", "Reluctant means not wanting to do something.",
    "For example, she was reluctant to speak in front of the class.", "He was reluctant to leave the party early.",
    "The opposite is eager.", ("Try to use reluctant this week.", 3.0),
    "Okay, that is all for today, see you next week.",
]

INTERVIEW = [
    ("Welcome to the show, today my guest is a teacher.", 0.6),
    ("So tell me, how did you start teaching English?", 0.8),
    ("Great question.", 0.3), "I started when I was in college, I tutored my classmates.",
    "Um, it was a part time job at first.", "Then I realized I really loved it, and I decided to make it my career.",
    "I got my certificate and moved to Shanghai.", ("That was ten years ago, and I never looked back.", 1.2),
    ("What is the biggest mistake your students make?", 0.7), "Well, they translate word by word from Chinese.",
    "For example they say I am agree, which sounds strange.", "The fix is to learn chunks, whole phrases, not single words.",
    "When you learn chunks, you speak faster and more naturally.", ("That is my number one tip.", 1.0),
    ("Thanks, that was great.", 0.5),
]
INTERVIEW_SPEAKERS = ["S1", "S1", "S2", "S2", "S2", "S2", "S2", "S2", "S1", "S2", "S2", "S2", "S2", "S2", "S1"]


def stub_translator(log=None):
    """A stand-in for the routed model: '译:' + the line (tests only)."""
    def call(system, prompt):
        if log is not None:
            log.append(prompt)
        rows = []
        for ln in prompt.splitlines():
            n, _, t = ln.partition(". ")
            rows.append(dict(n=int(n), t="译:" + t.replace("break the ice", "break the ice")[:30]))
        return dict(lines=rows), dict(provider="stub")
    return call


def speech_audio(tr, sr=16000, voices=None, seed=3):
    """Tone-burst speech under every word; ``voices`` = per-segment voice id -> a different harmonic voice."""
    rng = np.random.default_rng(seed)
    end = tr["segments"][-1]["end"] + 1.0
    x = (2e-4 * rng.standard_normal(int(end * sr))).astype(np.float32)
    for k, seg in enumerate(tr["segments"]):
        v = (voices or [0] * len(tr["segments"]))[k]
        f0, bright = (110.0, 0.35) if v == 0 else (245.0, 0.9)
        for w in seg["words"]:
            i0, i1 = int(w["start"] * sr), int(w["end"] * sr)
            tt = np.arange(i1 - i0) / sr
            y = sum((bright ** h) * np.sin(2 * np.pi * f0 * (h + 1) * tt) for h in range(8)) * 0.08
            env = np.minimum(1, np.minimum(tt, tt[::-1]) / 0.02)
            x[i0:i1] += (y * env).astype(np.float32)
    return x, sr


def make_video(path, x, sr, size="640x360", color="0x335577", shift=0.0):
    """A video whose audio is ``x`` (delayed by ``shift`` s of silence)."""
    from vstudio import audio
    if shift > 0:
        x = np.concatenate([np.zeros(int(shift * sr), np.float32), x])
    wav = str(path) + ".wav"
    audio.write_wav(wav, np.stack([x, x], 1), sr)
    dur = len(x) / sr
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=30", "-i", wav,
                    "-t", f"{dur:.3f}", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)], check=True)
    os.remove(wav)
    return str(path)


# --------------------------------------------------------------------------- lesson planning
def test_lesson_rule_points_kinds_terms_recap():
    sents = L.sentences(transcript(LESSON))
    plan = L.plan_points(sents, min_s=12, max_s=60, provider="none")
    assert plan["planner"] == "rules" and plan["lang"] == "en" and plan["gloss_lang"] == "zh"
    pts = plan["points"]
    assert [p["kind"] for p in pts] == ["phrase", "correction", "vocab"]
    assert [p["id"] for p in pts] == ["p01", "p02", "p03"]
    assert pts[0]["title"] == "break the ice" and pts[0]["gloss"].startswith("to start a conversation")
    assert pts[1]["title"] == "I am agree → I agree" and pts[1]["phrase"] == "I agree"
    assert pts[2]["title"] == "reluctant" and "not wanting" in pts[2]["gloss"]
    for a, b in zip(pts, pts[1:]):
        assert a["end"] <= b["start"]
    for p in pts:
        assert 12 * 0.6 <= p["end"] - p["start"] <= 60
        assert p["start"] <= p["anchor"][0] < p["anchor"][1] <= p["end"]
        assert not p["summary"].lower().startswith(("good morning", "okay, that is all"))
    rc = plan["recap"]
    assert rc["points"] == ["p01", "p02", "p03"] and all(1.0 <= r["range"][1] - r["range"][0] <= 7.0 for r in rc["parts"])


def test_lesson_chinese_markers_and_terms():
    assert L.kind_scores("这个短语的意思是打破僵局", "zh").get("phrase")
    assert L.kind_scores("常见错误：不要说 I am agree", "zh").get("correction")
    t = L.extract_terms("这个词是 reluctant，意思是不情愿", "zh")
    assert t and t[0]["term"] == "reluctant"
    assert L.extract_terms("Don't say I am agree, say I agree.", "en")[0] == dict(term="I agree", gloss=None,
                                                                                   kind="correction")


def test_lesson_model_planner_validates_ranges_and_errors():
    sents = L.sentences(transcript(LESSON))
    n = len(sents)

    def call(system, prompt):
        assert "TEACHING POINTS" in system and "[0]" in prompt
        return dict(points=[dict(**{"from": 2, "to": 6}, kind="phrase", title="break the ice", phrase="break the ice",
                                 gloss="打破僵局", terms=[dict(term="break the ice", gloss="打破僵局")]),
                            dict(**{"from": 4, "to": 8}, kind="vocab", title="overlaps"),       # overlaps: dropped
                            dict(**{"from": n + 3, "to": n + 9}, kind="vocab", title="out of range"),
                            dict(**{"from": 15, "to": 19}, kind="nonsense", title="reluctant")])
    plan = L.plan_points(sents, count=3, min_s=12, max_s=60, provider="auto", call=call)
    assert plan["planner"] == "llm"
    assert [p["title"] for p in plan["points"]] == ["break the ice", "reluctant"]
    assert plan["points"][0]["gloss"] == "打破僵局" and plan["points"][0]["terms"][0]["t"] is not None
    assert plan["points"][1]["kind"] in L.KINDS
    with pytest.raises(RuntimeError, match="no usable points"):
        L.plan_points(sents, provider="auto", call=lambda s, p: dict(points=[]))
    assert L.planner_of("none") == "rules" and L.planner_of("auto") == "rules"     # no model routed in tests


def test_study_notes_markdown_and_pdf(tmp_path):
    plan = L.plan_points(L.sentences(transcript(LESSON)), min_s=12, max_s=60, provider="none")
    md = L.notes_markdown(plan, "Small talk", ui="zh")
    assert md.startswith("# Small talk") and "## 1. 今日短语: break the ice" in md and "## 本课回顾" in md
    assert "易错点" in md and "**意思**" in md
    en = L.notes_markdown(plan, ui="en")
    assert "Today's phrase: break the ice" in en and "Lesson recap" in en
    L.write_notes(plan, str(tmp_path / "notes.md"), "Small talk", pdf=str(tmp_path / "notes.pdf"))
    assert (tmp_path / "notes.pdf").read_bytes()[:5] == b"%PDF-"


def test_lesson_clip_specs_cards_terms_recap():
    plan = L.plan_points(L.sentences(transcript(LESSON)), min_s=12, max_s=60, provider="none")
    specs = L.clip_specs(plan, "lesson.mp4", mode="bilingual", subs={"I am agree → I agree": "我同意"},
                         lesson_title="Small talk")
    ids = [s["id"] for s in specs]
    assert ids == ["p01", "p02", "p03", "recap"]
    p1 = specs[0]
    assert p1["parts"][0]["kind"] == "card" and p1["parts"][0]["kicker"] == "Today's phrase · 今日短语"
    assert p1["parts"][0]["sub"].startswith("to start") and p1["header"]["title"] == "break the ice"
    assert p1["terms"] and p1["terms"][0]["label"] == "Key term" and "break the ice" in p1["highlight"]
    assert specs[1]["parts"][0]["sub"] == "我同意"
    rec = specs[-1]
    assert rec["parts"][0]["title"] == "Small talk" and sum(p["kind"] == "src" for p in rec["parts"]) == 3
    mono = L.clip_specs(plan, "lesson.mp4", mode="mono", recap_clip=False)
    assert [s["id"] for s in mono] == ["p01", "p02", "p03"] and mono[0]["parts"][0]["kicker"] == "Today's phrase"


# --------------------------------------------------------------------------- Q&A planning
@pytest.mark.parametrize("text,lang,q", [
    ("How did you start teaching English?", "en", True), ("So tell me, how did you start teaching", "en", True),
    ("Do you think chunks help", "en", True), ("When you learn chunks, you speak faster.", "en", False),
    ("What a great day it was!", "en", False), ("你是怎么开始教英语的", "zh", True), ("你觉得难吗", "zh", True),
    ("我从大学开始教。", "zh", False), ("请问你最大的建议是", "zh", True),
])
def test_is_question(text, lang, q):
    assert QA.is_question(text, lang) is q


def _interview():
    tr = transcript(INTERVIEW)
    from vstudio.cleanup import load_words
    from vstudio.batch.segplan import sentences_of
    W = load_words(tr)
    return tr, W, sentences_of(W)


def test_qa_pairs_roles_and_tight_answers():
    tr, W, sents = _interview()
    assert len(sents) == len(INTERVIEW_SPEAKERS)
    plan = QA.plan_pairs(sents, INTERVIEW_SPEAKERS, "en", min_s=5, max_s=60, words=W, ui="en")
    pairs = plan["pairs"]
    assert [p["id"] for p in pairs] == ["q01", "q02"] and plan["speakers_known"]
    assert plan["roles"]["S1"]["role"] == "host" and plan["roles"]["S1"]["label"] == "Host"
    q1 = pairs[0]
    assert q1["title"] == "How did you start teaching English?"
    assert q1["question"]["role"] == "Host" and q1["answer"]["role"] == "Guest"
    great = next(s for s in sents if s["text"].startswith("Great question"))
    assert q1["answer"]["windows"][0][0] >= great["te"] - 0.01            # the acknowledgement is not in the answer
    assert q1["answer"]["kept_s"] < q1["answer"]["end"] - q1["answer"]["start"]   # pauses / fillers cut
    q2 = pairs[1]
    well = next(w for w in W if w["w"].lower().startswith("well"))
    assert q2["answer"]["windows"][0][0] > well["t"]                       # "Well," dropped at word level
    assert q2["answer"]["end"] <= next(s for s in sents if s["text"].startswith("Thanks"))["t"]
    zh = QA.plan_pairs(sents, INTERVIEW_SPEAKERS, "en", min_s=5, max_s=60, words=W, names={"S2": "Alex"})
    assert zh["pairs"][0]["question"]["role"] == "主持人" and zh["pairs"][0]["answer"]["role"] == "Alex"
    rows = QA.to_segments(plan, "audio")
    assert rows[0]["windows"][0] == [q1["question"]["start"], q1["question"]["end"]]
    assert QA.to_segments(plan, "card")[0]["windows"][0] == q1["answer"]["windows"][0]


def test_qa_without_speakers_is_said_not_guessed(monkeypatch):
    tr, W, sents = _interview()
    plan = QA.plan_pairs(sents, None, "en", min_s=5, max_s=60, words=W)
    assert plan["speakers_known"] is False and plan["roles"] == {}
    assert plan["pairs"] and all(p["question"]["role"] is None and p["answer"]["role"] is None for p in plan["pairs"])
    one = QA.diarize("x.mp4", sents, n=1)
    assert one["labels"] is None and one["method"] == "none" and one["note"]
    with pytest.raises(QA.DiarizeError):
        QA.diarize("x.mp4", sents, method="pyannote")
    with pytest.raises(QA.DiarizeError):
        QA.diarize("x.mp4", sents, method="tiles")
    specs = QA.clip_specs(plan, "talk.mp4", question="audio", mode="mono")
    assert all(not s["labels"] for s in specs)                              # no role labels drawn


def test_voice_diarization_separates_two_voices():
    tr, W, sents = _interview()
    x, sr = speech_audio(tr, voices=[0 if s == "S1" else 1 for s in INTERVIEW_SPEAKERS])
    r = QA.diarize((x, sr), sents, n=2, method="voice")
    assert r["method"] == "voice" and r["confidence"] >= 0.3
    want = INTERVIEW_SPEAKERS
    agree = sum(a == b for a, b in zip(r["labels"], want))
    assert agree >= len(want) - 1, (r["labels"], want)


def test_qa_clip_specs_question_modes():
    tr, W, sents = _interview()
    plan = QA.plan_pairs(sents, INTERVIEW_SPEAKERS, "en", min_s=5, max_s=60, words=W, ui="en")
    card = QA.clip_specs(plan, "t.mp4", question="card", mode="bilingual", subs={plan["pairs"][0]["title"]: "你怎么开始教英语？"})
    s = card[0]
    assert s["parts"][0]["kind"] == "card" and s["parts"][0]["sub"] == "你怎么开始教英语？"
    assert 2.5 <= s["parts"][0]["dur"] <= 6.0 and s["parts"][0]["footer"] == "— Host"
    assert all(p["kind"] == "src" for p in s["parts"][1:]) and [lb["text"] for lb in s["labels"]] == ["Guest"]
    both = QA.clip_specs(plan, "t.mp4", question="both", mode="mono")[0]
    assert [p["kind"] for p in both["parts"][:2]] == ["card", "src"] and [lb["text"] for lb in both["labels"]] == ["Host", "Guest"]


# --------------------------------------------------------------------------- bilingual
def test_translate_cues_cache_glossary_modes(tmp_path):
    cues = [S.Cue(0, 1.5, "First, the phrase break the ice."), S.Cue(1.5, 3, "It means to start a conversation."),
            S.Cue(3, 4, "")]
    log = []
    cache = str(tmp_path / "tr.json")
    out, info = BL.translate_cues(cues, "en", "zh", gl={"conversation": "对话"}, cache=cache, call=stub_translator(log))
    assert info["translated"] == 2 and info["missing"] == 0 and not info["error"] and len(log) == 1
    assert out[0].alt.startswith("译:") and out[2].alt == ""
    assert info["glossary_misses"] and info["glossary_misses"][0]["term"] == "conversation"   # not rendered: said
    out2, info2 = BL.translate_cues(cues, "en", "zh", gl={"conversation": "对话"}, cache=cache, call=stub_translator(log))
    assert len(log) == 1 and info2["cached"] == 2 and [c.alt for c in out2] == [c.alt for c in out]
    fixed, miss = BL.enforce_glossary("say break the ice", "说 break the ice", {"break the ice": "打破僵局"})
    assert fixed == "说 打破僵局" and not miss
    assert [c.alt for c in BL.apply_mode(out, "mono")] == ["", "", ""]
    tr = BL.apply_mode(out, "translated")
    assert tr[0].text.startswith("译:") and tr[2].text == "" and not tr[0].alt
    with pytest.raises(ValueError):
        BL.apply_mode(out, "both")
    hi = BL.highlight(out, ["break the ice"])
    assert "【break the ice】" in hi[0].text and hi[1].text == out[1].text


def test_translation_failure_is_an_error_not_mono():
    def boom(system, prompt):
        raise RuntimeError("all providers failed")
    out, info = BL.translate_cues([S.Cue(0, 1, "hello there")], "en", "zh", call=boom)
    assert info["error"] and out[0].alt == "" and info["missing"] == 1
    _, none = BL.translate_texts(["hello"], "en", "zh", call=lambda s, p: (None, dict(provider="none")))
    assert "no translation provider" in none["error"]
    from vstudio import clipkit as CK
    with pytest.raises(CK.TranslationError):
        CK.translate_lines(["hello"], "en", "zh", call=boom)


def test_tracks_srt_vtt(tmp_path):
    cues = [S.Cue(0.5, 2.0, "Break 【the ice】", "打破僵局"), S.Cue(2.0, 3.25, "Say I agree", "说我同意")]
    out = BL.write_tracks(cues, str(tmp_path / "p01"), "en", "zh")
    assert set(out) == {"en", "zh", "bi"}
    vtt = open(out["en"]["vtt"], encoding="utf-8").read()
    assert vtt.startswith("WEBVTT\n\n1\n00:00:00.500 --> 00:00:02.000\nBreak the ice\n")
    assert "说我同意" in open(out["zh"]["srt"], encoding="utf-8").read()
    bi = open(out["bi"]["srt"], encoding="utf-8").read()
    assert "Break the ice\n打破僵局" in bi
    mono = BL.write_tracks([S.Cue(0, 1, "hi")], str(tmp_path / "m"), "en", "zh")
    assert set(mono) == {"en"}


def test_caption_quote_spacing():
    ws = [dict(w="the", t=0.0, te=0.2), dict(w="phrase", t=0.25, te=0.5), dict(w='"break', t=0.55, te=0.8),
          dict(w='ice".', t=0.85, te=1.0)]
    assert S.cues_from_words(ws, fixes=False)[0].text == 'the phrase "break ice".'


# --------------------------------------------------------------------------- avsync
def test_offset_from_envelopes():
    rng = np.random.default_rng(7)
    sr = avsync.SR
    x = np.zeros(sr * 40, np.float32)
    for t in rng.uniform(1, 38, 60):
        i = int(t * sr)
        x[i:i + 400] += rng.standard_normal(400).astype(np.float32)
    y = np.concatenate([np.zeros(int(1.37 * sr), np.float32), x])          # the camera started 1.37 s earlier
    off, conf = avsync.offset_from_envelopes(avsync.envelope(x), avsync.envelope(y), max_offset=10)
    assert abs(off - 1.37) < 0.02 and conf > 0.5
    noise = rng.standard_normal(sr * 40).astype(np.float32) * 0.01
    _, low = avsync.offset_from_envelopes(avsync.envelope(x), avsync.envelope(noise), max_offset=10)
    assert low < conf


# --------------------------------------------------------------------------- intake / formats
@pytest.mark.parametrize("prompt,recipe", [
    ("把这节课切成知识点", "lesson-clips"),
    ("英语课切成今日短语，再出学习笔记", "lesson-clips"),
    ("cut this lesson into knowledge-point clips", "lesson-clips"),
    ("cut this interview into Q&A clips with Chinese and English subtitles", "interview-qa"),
    ("把这期播客切成一问一答，中英字幕", "interview-qa"),
    ("把这节课切成一组竖屏切片", "longform-to-short"),
    ("zoom 播客切几条 3-8 分钟，把朋友的脸遮一下", "call-clips"),
])
def test_intake_phrases(prompt, recipe):
    from vstudio.intake import rules as R
    sc = R.recipe_scores(prompt)
    assert max(sc, key=sc.get) == recipe


def test_intake_subtitle_wishes_are_not_speech_language():
    from vstudio.intake import rules as R
    it = R.parse_prompt("cut this interview into Q&A clips with Chinese and English subtitles")
    assert it["subtitles"] == "bilingual" and "language" not in it
    it = R.parse_prompt("英语课切成今日短语，只要中文字幕")
    assert it["subtitles"] == "translated" and it["subtitle_lang"] == "zh" and it["language"] == "en"
    assert R.subtitles_of("不要翻译") == dict(subtitles="mono")


def _analysis(tmp_path, files):
    from vstudio.intake import inventory as I
    out = []
    for k, (name, facts) in enumerate(files):
        p = tmp_path / name
        p.write_bytes(b"x")
        base = dict(duration=3600, width=1920, height=1080, orientation="horizontal", has_audio=True, speech=True,
                    language="en", talking_head=False, multi_person=False, screen_share=False, burned_captions=False)
        base.update(facts)
        out.append(dict(id=f"f{k + 1}", path=str(p), rel=name, kind="video", size=1, qhash=f"h{k}", **base))
    return dict(version=I.VERSION, kind="vstudio.intake.analysis", inputs=[str(tmp_path)], digest="d" * 16, asr="sample",
                totals=dict(videos=len(out), video_s=3600.0 * len(out), audio=0, audio_s=0.0, images=0, texts=0, other=0),
                files=out, groups=[], urls=[], notes=[])


def test_intake_plans_lesson_with_camera_and_interview(tmp_path):
    from vstudio.intake import plan as PL
    (tmp_path / "a").mkdir()
    a = _analysis(tmp_path / "a", [("lesson-week12.mp4", dict(screen_share=True, name_hints=["lecture"])),
                                   ("camera.mov", dict(duration=3610, talking_head=True))])
    plan = PL.make_plan("把这节课切成知识点，中英双语字幕", analysis=a, asr="off")
    p = plan["projects"][0]
    assert p["recipe"] == "lesson-clips" and PL.validate(plan) == []
    assert p["inputs"]["source"][0].endswith("lesson-week12.mp4") and p["inputs"]["camera"].endswith("camera.mov")
    assert p["params"]["layout"] == "pip" and p["params"]["subtitles"] == "bilingual" and p["params"]["language"] == "en"
    assert any(c["id"] == "points" for c in p["checkpoints"])
    (tmp_path / "b").mkdir()
    b = _analysis(tmp_path / "b", [("podcast-ep7.mp4", dict(multi_person=True, name_hints=["call"]))])
    plan = PL.make_plan("cut this interview into Q&A clips with Chinese and English subtitles, mask the guest's face",
                        analysis=b, asr="off")
    p = plan["projects"][0]
    assert p["recipe"] == "interview-qa" and p["params"]["mask"] == "sticker" and p["params"]["subtitles"] == "bilingual"
    assert any(c["id"] == "consent" and c["needs_you"] for c in p["checkpoints"]) and PL.validate(plan) == []


def test_formats():
    from vstudio import formats as F
    assert F.detect("把这节课切成知识点") == "lesson-points"
    assert F.detect("cut this interview into Q&A clips") == "interview-qa"
    assert F.detect("把这节课切成 20 条竖屏") == "lecture-slices"
    lp = F.get("lesson-points", persona_formats={})
    assert lp["speed"]["body"] == 1.0 and lp["hooks"] == "none" and lp["captions"] == "bilingual"
    assert F.canonical("lesson-clips") == "lesson-points" and F.canonical("interview-qa") == "interview-qa"


# --------------------------------------------------------------------------- rendering (ffmpeg)
@pytest.fixture(scope="module")
def lesson_media(tmp_path_factory):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    d = tmp_path_factory.mktemp("lesson")
    lines = [('First, the phrase "break the ice".', 0.3), "Break the ice means to start a conversation.",
             "For example, tell a joke to break the ice.", ("It is a useful expression.", 1.5),
             "Now a common mistake.", "Don't say I am agree, say I agree.", "Agree is a verb.",
             ("For example, I agree with you.", 1.0)]
    tr = transcript(lines, start=0.5)
    (d / "tr.json").write_text(json.dumps(tr), encoding="utf-8")
    x, sr = speech_audio(tr, sr=48000)
    src = make_video(d / "lesson.mp4", x, sr, size="640x360")
    cam = make_video(d / "camera.mp4", x, sr, size="320x240", color="0x775533", shift=2.0)
    return dict(dir=d, tr=str(d / "tr.json"), src=src, cam=cam, transcript=tr)


@media
def test_sync_and_render_two_file_lesson_bilingual(tmp_path, lesson_media):
    from vstudio import media as MD
    s = avsync.sync(lesson_media["src"], lesson_media["cam"])
    assert s["method"] == "audio" and abs(s["offset"] - 2.0) < 0.05
    plan = L.plan_points(L.sentences(lesson_media["transcript"]), min_s=5, max_s=20, provider="none")
    plan.update(transcript=lesson_media["tr"], source=lesson_media["src"])
    stub = stub_translator()
    res = L.render(plan, lesson_media["src"], str(tmp_path / "out"), ["douyin"], camera=lesson_media["cam"],
                   offset=s["offset"], layout="pip", mode="bilingual", only=["p01"], call=stub,
                   translate=lambda cs, a, b: BL.translate_cues(cs, a, b, call=stub))
    assert [c["id"] for c in res["clips"]] == ["p01"] and res["ok"], res
    d = tmp_path / "out" / "p01"
    rep = json.loads((d / "report.json").read_text())
    vid = d / "p01-douyin-vertical.mp4"
    assert vid.exists() and (d / "p01-douyin-vertical.cover.jpg").exists()
    info = MD.probe(str(vid))
    p1 = plan["points"][0]
    assert (info["w"], info["h"]) == (1080, 1920)
    assert abs(info["duration"] - (2.2 + p1["end"] - p1["start"])) < 0.6
    assert rep["firstpass"] and all(f["ok"] for f in rep["firstpass"]), rep["firstpass"]
    assert "译:" in (d / "p01.zh.srt").read_text(encoding="utf-8") and (d / "p01.en.vtt").exists()
    cues = json.loads((d / "cues.1080x1920.json").read_text())
    assert cues["cues"][0]["start"] >= 2.2 - 0.01                     # captions start after the title card
    assert any("【break the ice】" in c["text"] for c in cues["cues"]) and any(c.get("alt") for c in cues["cues"])
    assert {k["kind"] for k in cues["keepouts"]} >= {"header", "term"}
    man = json.loads((d / "manifest.json").read_text())
    assert man["exports"][0]["file"] == "p01-douyin-vertical.mp4"


@media
def test_lesson_project_runs_to_publish_and_export(tmp_path, lesson_media):
    from vstudio.project.core import Project
    p = Project.create(str(tmp_path / "proj"), recipe="lesson-clips",
                       inputs=dict(source=[lesson_media["src"]], transcript=[lesson_media["tr"]]),
                       params=dict(planner="none", platforms=["douyin"], subtitles="mono", min_s=5, max_s=20, count=2,
                                   recap=False, title="Small talk"))
    r = p.run()
    assert r["exit_code"] == 7 and r["pending"][0]["id"] == "points"
    pts = json.loads(open(p.pending("points")[0]["file"], encoding="utf-8").read())
    assert pts["planner"] == "rules" and len(pts["points"]) == 2
    p.answer("points", dict(done=True))
    r = p.run()
    assert [x["id"] for x in r["pending"]] == ["publish"]
    pub = p.pending("publish")[0]
    assert len(pub["exports"]) == 2 and pub["qc"]["status"] == "green" and pub["default"] == {"approve": True}
    p.answer("publish", dict(approve=True))
    assert p.run()["status"] == "done"
    ex = p.export()
    names = sorted(os.path.basename(e["file"]) for e in ex["entries"])
    assert "p01-douyin-vertical.mp4" in names and "p02-douyin-vertical.mp4" in names
    assert "notes.pdf" in names and "p01.en.srt" in names
    notes = open(os.path.join(p.dir, "items", "lesson", "out", "notes.md"), encoding="utf-8").read()
    assert notes.startswith("# Small talk")


@media
def test_interview_project_waits_for_consent_then_renders(tmp_path):
    from vstudio.project.core import Project
    d = tmp_path / "m"
    d.mkdir()
    lines = [("So tell me, how did you start teaching English?", 0.8), ("Great question.", 0.3),
             "I started in college, I tutored my classmates.", ("Then I decided to make it my career.", 1.2),
             ("Thanks, that was great.", 0.5)]
    tr = transcript(lines, start=0.5)
    (d / "tr.json").write_text(json.dumps(tr), encoding="utf-8")
    x, sr = speech_audio(tr, sr=48000, voices=[0, 1, 1, 1, 0])
    src = make_video(d / "talk.mp4", x, sr)
    p = Project.create(str(tmp_path / "proj"), recipe="interview-qa",
                       inputs=dict(source=[src], transcript=[str(d / "tr.json")]),
                       params=dict(platforms=["douyin"], subtitles="mono", min_s=3, max_s=30, question="card",
                                   speakers=2))
    r = p.run()
    waiting = sorted(x["id"] for x in r["pending"])
    assert "consent" in waiting
    plan = json.loads(open(os.path.join(p.dir, "items", "talk", "work", "pairs.json"), encoding="utf-8").read())
    assert plan["diarization"]["method"] in ("voice", "none") and plan["diarization"]["note"]
    assert len(plan["pairs"]) == 1 and plan["pairs"][0]["title"].startswith("How did you start")
    p.answer("consent", dict(consent=True, who="the guest"))
    for _ in range(3):                                   # the pairs review comes up once consent is given
        if p.pending("pairs"):
            p.answer("pairs", dict(done=True))
        r = p.run()
        if [x["id"] for x in r["pending"]] != ["pairs"]:
            break
    assert [x["id"] for x in r["pending"]] == ["publish"], r
    pub = p.pending("publish")[0]
    assert pub["exports"] and pub["exports"][0]["file"].endswith("q01-douyin-vertical.mp4")
    assert os.path.exists(os.path.join(p.dir, "items", "talk", "out", "q01", "q01.en.srt"))
