"""A pipeline cut's transcript without a second ASR pass (``batch.transcripts.mapped_words``): the source words the
``apply`` stage already re-timed onto the cut, played through compose's hook + speed. The editor opens a clip with
its words at once; the times must match a fresh hearing of the cut within 50 ms.

    python3 -m pytest tests/test_mapped_words.py -q
"""
import json
import os
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))

from vstudio import cleanup, media  # noqa: E402
from vstudio.batch.transcripts import job_dir_of, mapped_words  # noqa: E402

HAS_FF = bool(shutil.which("ffmpeg"))


def _job(tmp, params=None):
    jd = tmp / "jobs" / "j001"
    (jd / "apply").mkdir(parents=True)
    (jd / "export" / "exports").mkdir(parents=True)
    (jd / "job.json").write_text(json.dumps(dict(id="j001", params=params or {})), encoding="utf-8")
    return jd


def _sidecar(path, keep, words):
    cleanup.write_sidecar(str(path).replace(".cleanup.json", ".mp4"), "src.mp4", keep, words, path=str(path))


SRC = [dict(w=w, t=t, te=t + 0.3) for w, t in
       (("one", 0.5), ("two", 1.0), ("um", 1.5), ("three", 2.2), ("four", 3.0), ("five", 4.0))]


def test_body_only_and_cut_words_dropped(tmp_path):
    jd = _job(tmp_path)
    _sidecar(jd / "apply" / "body.cleanup.json", [(0.4, 1.4), (2.1, 4.4)], SRC)   # "um" cut out
    f = jd / "export" / "exports" / "x.mp4"
    f.write_bytes(b"")
    assert job_dir_of(str(f)) == str(jd)
    W = mapped_words(str(f), duration=3.3)
    assert [w["w"] for w in W] == ["one", "two", "three", "four", "five"]
    # "three" starts 0.1 s into the second kept span, which starts at 1.0 s of the cut
    three = W[2]
    assert three["t"] == pytest.approx(1.1, abs=0.01) and three["te"] == pytest.approx(1.4, abs=0.01)


def test_hook_then_sped_up_body(tmp_path):
    jd = _job(tmp_path, dict(speed=1.25, hook_speed=1.0))
    _sidecar(jd / "apply" / "hook.cleanup.json", [(3.9, 4.4)], SRC)               # "five" as the hook
    _sidecar(jd / "apply" / "body.cleanup.json", [(0.4, 2.0)], SRC)
    f = jd / "export" / "exports" / "x.mp4"
    f.write_bytes(b"")
    W = mapped_words(str(f), duration=0.5 + 1.6 / 1.25)
    assert [w["w"] for w in W] == ["five", "one", "two", "um"]
    assert W[0]["t"] == pytest.approx(0.1, abs=0.01)
    assert W[1]["t"] == pytest.approx(0.5 + 0.1 / 1.25, abs=0.01)                # after the hook, at 1.25x
    assert W[3]["te"] == pytest.approx(0.5 + 1.4 / 1.25, abs=0.01)


def test_not_a_pipeline_cut_or_another_length(tmp_path):
    loose = tmp_path / "clip.mp4"
    loose.write_bytes(b"")
    assert mapped_words(str(loose), duration=3) is None
    jd = _job(tmp_path)
    _sidecar(jd / "apply" / "body.cleanup.json", [(0.4, 1.4)], SRC)
    f = jd / "export" / "exports" / "x.mp4"
    f.write_bytes(b"")
    assert mapped_words(str(f), duration=1.0)
    assert mapped_words(str(f), duration=0.6) is None                              # a shorter platform variant
    (jd / "apply" / "body.cleanup.json").unlink()
    assert mapped_words(str(f), duration=1.0) is None


@pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")
def test_mapped_times_match_a_fresh_hearing_within_50ms(tmp_path):
    """A real cut (tone-burst 'speech', ffmpeg, many cuts): the mapped words vs what a transcriber hears in it."""
    from test_cleanup import EN, ZH, fake_asr_from, make_media, synth
    s = synth(ZH + EN)
    src = make_media(tmp_path, s)
    jd = _job(tmp_path)
    edl = str(tmp_path / "cleanup.json")
    cleanup.analyze(src, transcript=s["words"], out=edl, review=str(tmp_path / "review.md"))
    res = cleanup.apply(edl, all_confirm=True, out=str(jd / "apply" / "body.mp4"), media_path=src, force=True)
    assert os.path.exists(jd / "apply" / "body.cleanup.json")
    exp = jd / "export" / "exports" / "xiaohongshu-vertical.mp4"
    shutil.copy(res["out"], exp)
    W = mapped_words(str(exp), duration=media.probe(str(exp))["duration"])
    heard = fake_asr_from(s["truth"])(str(exp))
    assert len(W) >= 40
    # whisper-like transcript starts are 40 ms before the sound (synth); the hearing reads the sound itself
    errs, j = [], 0
    for h in heard:
        while j < len(W) and W[j]["t"] + 0.04 < h["t"] - 0.2:
            j += 1
        cands = [w for w in W[max(0, j - 2):j + 3] if w["w"] == h["w"]]
        if cands:
            errs.append(min(abs(w["t"] + 0.04 - h["t"]) for w in cands))
    assert len(errs) >= 0.8 * len(heard), (len(errs), len(heard))
    assert max(errs) < 0.05, sorted(errs)[-5:]
