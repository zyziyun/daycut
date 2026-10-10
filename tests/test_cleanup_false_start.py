"""Cleanup edits the 2026-10 review found inconsistent: a broken-off sentence said again ("The first habit is." ->
"The first habit is to plan the beats ...") is cut the same way whatever the pause before the restart, and a
recording that stops mid-sentence ends on the sentence before (a clip never ends mid-sentence)."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio import cleanup as C  # noqa: E402


def talk(gap_after_first, tail=0.6, cut_off=False):
    words, t = [], 0.5
    sents = [["The", "first", "habit", "is."],
             ["The", "first", "habit", "is", "to", "plan", "the", "beats", "before", "you", "press", "record."],
             ["Write", "down", "three", "to", "five", "points,", "one", "sentence", "each."]]
    if cut_off:
        sents.append(["The", "editor", "keeps", "the", "last", "good", "take", "and"])
    for si, s in enumerate(sents):
        for k, w in enumerate(s):
            words.append(dict(w=w, t=round(t, 3), te=round(t + 0.3, 3)))
            t += 0.3 + (0.1 if k < len(s) - 1 else (gap_after_first if si == 0 else 0.6))
    end = words[-1]["te"] + (0.05 if cut_off else tail)
    sr = 16000
    x = (1e-4 * np.random.default_rng(0).standard_normal(int(end * sr))).astype(np.float32)
    for w in words:                                   # a tone where each word is: energy says speech
        a, b = int(w["t"] * sr), int(w["te"] * sr)
        x[a:b] += 0.2 * np.sin(2 * np.pi * 220 * np.arange(b - a) / sr).astype(np.float32)
    return words, C.Energy(x, sr)


def test_false_start_is_cut_the_same_way_whatever_the_pause():
    acts = set()
    for gap in (0.25, 0.5, 0.9, 2.5):
        w, en = talk(gap)
        e = [x for x in C.detect(w, energy=en, profile="standard") if x["text"].startswith("The first habit is.")]
        assert len(e) == 1, (gap, e)
        assert e[0]["confidence"] >= 0.88 and e[0]["action"] == "auto", (gap, e[0])
        acts.add(e[0]["action"])
    assert acts == {"auto"}
    w, en = talk(0.5)
    e = [x for x in C.detect(w, energy=en, profile="gentle") if x["text"].startswith("The first habit is.")]
    assert e and e[0]["action"] == "confirm"          # gentle asks rather than cuts - but always finds it


def test_a_recording_cut_mid_sentence_ends_on_the_sentence_before():
    w, en = talk(0.5, cut_off=True)
    e = [x for x in C.detect(w, energy=en, profile="standard") if x["kind"] == "cut-off"]
    assert len(e) == 1 and e[0]["text"].startswith("The editor keeps") and e[0]["action"] == "auto"
    w, en = talk(0.5)                                 # ends on a full stop with room after: nothing cut
    assert not [x for x in C.detect(w, energy=en, profile="standard") if x["kind"] == "cut-off"]


def test_glossary_words_are_spelt_her_way(monkeypatch):
    from vstudio import asr
    monkeypatch.setattr(asr, "persona_terms", lambda: ["Reelfold", "HyperFrames"])
    assert asr.apply_term_fixes("a sample that ships with Realfold, so") == "a sample that ships with Reelfold, so"
    assert asr.apply_term_fixes("reel fold makes clips") == "Reelfold makes clips"
    assert asr.apply_term_fixes("hyper frames renders it") == "HyperFrames renders it"
    assert asr.apply_term_fixes("a real fold in the paper, the realm folds") == "a real fold in the paper, the realm folds"
    monkeypatch.setattr(asr, "persona_terms", lambda: [])
    assert asr.apply_term_fixes("ships with Realfold") == "ships with Reelfold"      # the app's own name, always


def test_vtrack_sentences_leave_out_false_starts_and_a_cut_off_end():
    from vstudio.batch.thfolder import drop_broken_sentences
    rows = [(1, [(27.4, 29.2)], " The first habit is"),
            (1, [(29.6, 33.5)], " The first habit is to plan the beats before you press record."),
            (1, [(34.3, 37.5)], " Write down three to five points, one sentence each."),
            (1, [(67.8, 69.95)], " The editor keeps the last good take and")]
    kept, dropped = drop_broken_sentences(rows, 70.0)
    assert [r[2] for r in kept] == [rows[1][2], rows[2][2]]
    assert [k for k, _ in dropped] == ["false-start", "cut-off"]
    kept, dropped = drop_broken_sentences(rows, 75.0)          # the recording goes on after it: not cut off
    assert len(kept) == 3 and [k for k, _ in dropped] == ["false-start"]
    zh = [(1, [(0.0, 1.0)], "第一个习惯是"), (1, [(1.4, 4.0)], "第一个习惯是先把要点写下来。")]
    assert [k for k, _ in drop_broken_sentences(zh, 9.0)[1]] == ["false-start"]


def test_a_whisper_sentence_with_whole_sentences_before_the_fragment_keeps_them():
    from vstudio.batch.thfolder import drop_broken_sentences
    words = [dict(word=w, start=s, end=e) for w, s, e in (
        (" If", 60.9, 61.1), (" you", 61.1, 61.3), (" stumble,", 61.3, 61.8), (" restart", 62.0, 62.5),
        (" the", 62.5, 62.6), (" sentence.", 62.6, 63.2), (" The", 67.8, 68.0), (" editor", 68.0, 68.4),
        (" keeps", 68.4, 68.8), (" the", 68.8, 69.0), (" last", 69.0, 69.3), (" good", 69.3, 69.6), (" take", 69.6, 69.95))]
    rows = [(1, [(53.7, 60.0)], " Leave a short pause between points."),
            (1, [(60.9, 69.95)], " If you stumble, restart the sentence. The editor keeps the last good take")]
    kept, dropped = drop_broken_sentences(rows, 70.0, last_words=words)
    assert kept[-1] == (1, [(60.9, 63.2)], "If you stumble, restart the sentence.")
    assert dropped == [("cut-off", "The editor keeps the last good take")]


def test_captions_leave_out_the_hesitations_the_sound_lost():
    from vstudio.batch.thfolder import drop_hesitations
    assert drop_hesitations("Um, the idea is simple") == "the idea is simple"
    assert drop_hesitations("and um know how you") == "and know how you"
    assert drop_hesitations("嗯，这个方法很好") == "这个方法很好"
    assert drop_hesitations("summary umbrella") == "summary umbrella"
    assert drop_hesitations("Uh.") == ""
