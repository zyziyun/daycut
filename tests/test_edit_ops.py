"""Field-test fixes (batch-rag v0.2): captions follow the kept audio after policy cuts, proofread cache per cue,
``job edit --op cut / notes``, ``review --accept-policy --jobs``, caption edits checked against a re-hearing.
Synthetic data, fake recipes / LLM / ASR - no media, no network."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LFS = os.path.join(ROOT, "workflows", "longform-to-short", "scripts")


# --------------------------------------------------------------------------- (a) captions follow the kept audio
def _words(spec):
    return [dict(word=w, start=a, end=b) for w, a, b in spec]


def test_filler_merged_cut_keeps_the_word_in_the_captions(tmp_path):
    """ep04 regression: the policy-accepted ``filler-merged`` cuts trimmed the merged filler in front of 只 / hybrid
    (patch = [onset, cut end]); the word is still said after the cut, but its ASR midpoint sat inside the cut, so the
    caption lost it. A fully cut filler (然后) must still leave the captions."""
    from vstudio import cleanup as C
    from vstudio.batch import lfsplit as L
    seg1 = [("现在", 440.0, 440.6), ("其实", 440.6, 441.2), ("也", 441.2, 441.5), ("很少", 441.5, 442.16),
            ("因为", 442.16, 442.5), ("只", 442.5, 444.1), ("做", 444.1, 444.24), ("RED", 444.24, 444.62)]
    seg2 = [("出来", 446.0, 446.34), ("然后", 446.6, 446.9), ("我", 446.95, 447.2), ("都是", 447.3, 447.76),
            ("hybrid", 447.76, 448.38), ("这样", 448.64, 448.78), ("的", 448.78, 448.9), ("模式", 448.9, 449.4)]
    tr = {"segments": [dict(start=440.0, end=444.62, text="".join(w for w, _, _ in seg1), words=_words(seg1)),
                       dict(start=446.0, end=449.4, text="".join(w for w, _, _ in seg2), words=_words(seg2))]}
    W = C.load_words(tr)
    i_then = next(k for k, w in enumerate(W) if w["w"] == "然后")
    edits = [dict(id=1, t0=442.67, t1=443.86, kind="filler-merged", text="只", action="confirm", words=[],
                  patch=[442.5, 443.86]),
             dict(id=2, t0=446.5, t1=446.93, kind="filler", text="然后", action="auto", words=[i_then]),
             dict(id=3, t0=447.76, t1=448.14, kind="filler-merged", text="hybrid", action="confirm", words=[],
                  patch=[447.76, 448.14]),
             dict(id=4, t0=448.4, t1=448.6, kind="pause", text="", action="confirm", words=[])]
    edl = tmp_path / "body.cleanup.json"
    edl.write_text(json.dumps(dict(ranges=[[439.9, 449.6]], edits=edits, words=W, settings=dict(min_piece=0.06))))
    work = tmp_path / "work"
    work.mkdir()
    L.whisper_json(tr, str(work / "audio16k.json"))
    pieces, ids = L._keep_pieces(dict(cleanup_reply="全部确认"), str(edl), with_ids=True)
    assert ids == [1, 2, 3, 4] and len(pieces) == 5
    assert L.cut_transcript(str(work / "audio16k.json"), str(edl), ids) == 2
    tl, t = [], 0.0
    for a, b in pieces:
        tl.append(dict(kind="clip", t0=a, t1=b, speed=1.0, final_t0=round(t, 3)))
        t += b - a
    (work / "timeline.json").write_text(json.dumps(tl))
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out")}))
    subprocess.run([sys.executable, os.path.join(LFS, "build_subs.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    text = "".join(c["text"] for c in json.loads((work / "cues.json").read_text(encoding="utf-8")))
    assert "只做RED" in text and "hybrid" in text                    # trimmed in front, still said: captioned
    assert "然后" not in text and "出来我都是" in text                  # fully cut: gone from the captions
    # nothing patched without the edits being cut (a reply that keeps them): the ASR words stay as they were
    pieces, ids = L._keep_pieces(dict(cleanup_reply="保留 1,3"), str(edl), with_ids=True)
    assert 1 not in ids and 3 not in ids


def test_patch_onsets_only_for_cut_edits():
    from vstudio import cleanup as C
    W = [dict(w="只", t=442.5, te=444.1), dict(w="做", t=444.1, te=444.24)]
    e = [dict(id=1, patch=[442.5, 443.86])]
    assert C.patch_onsets(W, e, [1])[0]["t"] == 443.86 and W[0]["t"] == 442.5        # copies, not in place
    assert C.patch_onsets(W, e, [])[0]["t"] == 442.5
    assert C.patch_onsets(W, [dict(id=1, patch=[442.5, 444.2])], [1])[0]["t"] == 442.5   # cut past its end: gone
