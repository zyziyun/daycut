"""Recorder ingest: a synthetic session (ffmpeg testsrc + sine as camera / mic WebM, retake marks) -> the last good
take per line, studio sound, a talking-head project; crash recovery of a locked session; path confinement."""
import json
import os
import subprocess

import pytest

from _create_helpers import home, needs_ffmpeg  # noqa: F401

from vstudio.create import record as RE, store
from vstudio.create.i18n import CreateError


def _webm(path, seconds, video=True):
    src = ["-f", "lavfi", "-i", f"testsrc2=size=180x320:rate=24:duration={seconds}"] if video else \
        ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    codec = ["-c:v", "libvpx-vp9", "-b:v", "200k", "-deadline", "realtime"] if video else ["-c:a", "libopus"]
    subprocess.run(["ffmpeg", "-v", "error", "-y", *src, *codec, path], check=True)


def session(root, marks, seconds=6, lock=False):
    d = os.path.join(root, "recordings", "20261006-1200-side-hustle")
    os.makedirs(d, exist_ok=True)
    _webm(os.path.join(d, "camera.webm"), seconds)
    _webm(os.path.join(d, "mic.webm"), seconds, video=False)
    json.dump(dict(id="s1", slug="side-hustle", title="Side hustle", script=["Line one.", "Line two.", "Line three."],
                   tracks=dict(camera=dict(file="camera.webm", start_ms=1000), mic=dict(file="mic.webm", start_ms=1000))),
              open(os.path.join(d, "session.json"), "w"))
    json.dump(marks, open(os.path.join(d, "takes.json"), "w"))
    if lock:
        open(os.path.join(d, "recording.lock"), "w").write("live")
    return d


def test_attempts_and_last_take_per_line():
    marks = [dict(t=0.0, kind="line", line=0), dict(t=1.5, kind="retake", line=0), dict(t=3.0, kind="line", line=1),
             dict(t=4.0, kind="line", line=2), dict(t=4.6, kind="retake", line=2)]
    atts = RE.attempts(marks, 6.0, 3)
    assert atts[0] == [(0.0, 1.5), (1.5, 3.0)] and atts[2] == [(4.0, 4.6), (4.6, 6.0)]
    edl = RE.pick_best(atts)
    assert [(e["line"], e["start"], e["end"], e["attempts"]) for e in edl] == [(0, 1.5, 3.0, 2), (1, 3.0, 4.0, 1),
                                                                              (2, 4.6, 6.0, 2)]


def test_pick_best_with_words_skips_an_empty_retake():
    atts = {0: [(0.0, 2.0), (2.0, 3.0)]}
    words = [dict(word="hello", start=0.4, end=0.8), dict(word="world", start=0.9, end=1.5)]
    e = RE.pick_best(atts, words)[0]
    assert e["start"] == pytest.approx(0.25) and e["end"] == pytest.approx(1.75)    # tightened, the empty retake skipped


@needs_ffmpeg
def test_ingest_creates_talkinghead_project(home):
    d = session(str(home), [dict(t=0.0, kind="line", line=0), dict(t=1.5, kind="retake", line=0),
                            dict(t=3.0, kind="line", line=1), dict(t=4.0, kind="line", line=2),
                            dict(t=4.6, kind="retake", line=2)])
    res = RE.ingest(d)
    assert os.path.exists(res["assembled"]) and res["retakes"] == 2
    assert 3.0 < res["duration"] < 4.6                    # 1.5 + 1.0 + 1.4 s kept out of 6 s
    assert [ln["text"] for ln in res["lines"]] == ["Line one.", "Line two.", "Line three."]
    from vstudio.project import home as H
    from vstudio.project.core import Project
    p = Project(res["project_dir"])
    assert p.data["recipe"] == "talkinghead" and p.data["items"]
    assert any(os.path.realpath(x["dir"]) == os.path.realpath(res["project_dir"]) for x in H.projects())


@needs_ffmpeg
def test_ingest_assembled_only_makes_no_project_and_keeps_raw_sound(home, monkeypatch):
    d = session(str(home), [dict(t=0.0, kind="line", line=0)])
    sess = json.load(open(os.path.join(d, "session.json")))
    json.dump(dict(sess, studio=False), open(os.path.join(d, "session.json"), "w"))
    from vstudio import studiosound
    monkeypatch.setattr(studiosound, "enhance", lambda *a, **k: (_ for _ in ()).throw(AssertionError("studio sound")))
    res = RE.ingest(d, "assembled")
    assert os.path.exists(res["assembled"]) and "project_dir" not in res
    assert not os.path.exists(os.path.join(d, "project"))


@needs_ffmpeg
def test_recover_locked_session(home):
    d = session(str(home), [], seconds=2, lock=True)
    out = RE.recover()
    assert out and out[0]["id"] == os.path.basename(d) and "camera" in out[0]["tracks"]
    assert not os.path.exists(os.path.join(d, "recording.lock"))


def test_session_must_be_inside_recordings(home, tmp_path):
    os.makedirs(tmp_path / "elsewhere", exist_ok=True)
    (tmp_path / "elsewhere" / "session.json").write_text("{}")
    with pytest.raises(CreateError):
        RE.need_session(str(tmp_path / "elsewhere"))
    with pytest.raises(CreateError):
        RE.need_session(os.path.join(store.recordings_root(), "..", "series"))


def test_recorder_transcript_words_reads_words_of_keys(monkeypatch):
    from vstudio import asr
    monkeypatch.setattr(asr, "transcribe", lambda p, language=None: dict(segments=[dict(words=[
        dict(word=" 你好", start=0.4, end=0.8), dict(word="世界", start=0.9, end=1.5)])]))
    w = RE.transcript_words("x.mp4")
    assert w == [dict(word="你好", start=0.4, end=0.8), dict(word="世界", start=0.9, end=1.5)]


def test_ffmpeg_never_reads_the_callers_stdin(monkeypatch):
    # Windows: ffmpeg stalls on an inherited stdin pipe nobody writes to (the desk engine's) - the stitch never ended
    seen = {}

    def fake_run(args, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(args, 0, b"", b"")
    monkeypatch.setattr(RE.subprocess, "run", fake_run)
    RE._run(["ffmpeg", "-version"])
    assert seen.get("stdin") is subprocess.DEVNULL
