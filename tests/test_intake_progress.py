"""vstudio.intake progress: the events ``plan --json-events`` streams (scan / probe / listen / faces / transcribe /
model / write), the transcription progress from the ASR backends, and reusing a transcript made before (the
per-source cache, the ``<file>.asr.json`` sidecar) instead of transcribing the same recording again."""
import json
import os
import shutil
import subprocess
import sys
import types

import pytest

from vstudio import asr
from vstudio.batch import transcripts as TS
from vstudio.intake import inventory as I
from vstudio.intake import plan as PL

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HAS_FFMPEG = bool(shutil.which("ffmpeg"))


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_INTAKE_PROVIDER",
              "VSTUDIO_CLIENTS"):
        monkeypatch.delenv(k, raising=False)


def _stages(evs):
    return [e["stage"] for e in evs if e["event"] == "stage"]


# --------------------------------------------------------------------------- inventory + plan events
@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_plan_reports_every_stage_in_order(tmp_path, monkeypatch):
    import _batch_helpers as H
    d = tmp_path / "in"
    d.mkdir()
    x, _truth, dur = H.synth_speech([("大家", .4), ("好", .3), ("今天", .4), ("讲", .3)])
    H.make_video(str(d / "talk.mp4"), x, 48000, dur)
    (d / "brief.md").write_text("# 选题\n", encoding="utf-8")
    monkeypatch.setattr(I, "TRANSCRIBE", lambda wav, lang: dict(
        language="zh", segments=[dict(start=0, end=1, text="大家好今天讲一个方法")], words=[{}] * 6))
    monkeypatch.setattr(I, "FACES", lambda img: [0.05])
    evs = []
    plan = PL.make_plan("把讲方法的部分剪出来发小红书", [str(d)], on_event=evs.append,
                        call=lambda s, b: dict(json=dict(projects=[]), model="mock", cost_usd=0.0))
    assert plan["projects"]
    assert all(e["event"] in ("stage", "progress") and "ts" in e for e in evs)
    st = _stages(evs)
    # the stages arrive in pipeline order (each first appearance)
    first = list(dict.fromkeys(st))
    assert first == ["scan", "probe", "listen", "faces", "transcribe", "model", "write"], first
    scan = [e for e in evs if e["stage"] == "scan"]
    assert scan[0]["inputs"] == 1 and scan[-1]["files"] == 2
    probes = [e for e in evs if e["stage"] == "probe"]
    assert {(e["file"], e["i"], e["n"]) for e in probes} == {("brief.md", 1, 2), ("talk.mp4", 2, 2)}
    listen = next(e for e in evs if e["stage"] == "listen")
    assert (listen["file"], listen["i"], listen["n"]) == ("talk.mp4", 2, 2)       # per-file fields carried along
    tr = next(e for e in evs if e["stage"] == "transcribe")
    assert tr["file"] == "talk.mp4" and tr["total_s"] > 0 and tr["done_s"] == 0
    assert "provider" in next(e for e in evs if e["stage"] == "model")
    # a second plan: everything is cached; the transcript is reported as reused, no listening / faces again
    evs2 = []
    PL.make_plan("把讲方法的部分剪出来发小红书", [str(d)], on_event=evs2.append,
                 call=lambda s, b: dict(json=dict(projects=[]), model="mock", cost_usd=0.0))
    assert "listen" not in _stages(evs2) and "faces" not in _stages(evs2)
    assert all(e.get("cached") for e in evs2 if e["stage"] == "probe" and e.get("cached") is not None)
    assert any(e["stage"] == "transcribe" and e.get("cached") == "analysis" for e in evs2)


def test_full_transcription_streams_throttled_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "_wav_sample", lambda src, dst, st, ln: dst)
    monkeypatch.setattr(I, "PROGRESS_EVERY_S", 0)

    def fake(wav, language=None, words=True, progress=None):
        for t in (60.0, 120.0, 300.0, 400.0):
            progress(t, 300.0)                          # past the end is clamped
        return dict(language="zh", segments=[dict(start=0, end=200, text="一段很长的讲话" * 4)])
    monkeypatch.setattr(I, "_transcribe", fake)
    evs = []
    out = I.speech_facts(str(tmp_path / "missing.mp4"), 300.0, True, "full", str(tmp_path), "k",
                         on_event=I.bind(evs.append, i=1, n=1))
    assert out["speech_basis"] == "asr full" and os.path.exists(out["transcript"])
    start = evs[0]
    assert (start["event"], start["stage"], start["file"], start["total_s"], start["done_s"]) == \
        ("stage", "transcribe", "missing.mp4", 300.0, 0)
    prog = [e for e in evs if e["event"] == "progress"]
    assert [e["done_s"] for e in prog] == [60.0, 120.0, 300.0, 300.0]
    assert all(e["stage"] == "transcribe" and e["total_s"] == 300.0 and e["i"] == 1 for e in prog)


def test_progress_is_throttled():
    evs = []
    cb = I._asr_progress(evs.append, "a.mp4", 100.0)
    for k in range(50):
        cb(k, 100.0)
    assert len(evs) == 1                               # 50 calls inside half a second: one event


def test_a_failing_consumer_never_stops_the_analysis():
    def boom(_ev):
        raise BrokenPipeError("desk went away")
    I.emit(boom, stage="scan")                         # no exception


# --------------------------------------------------------------------------- transcript reuse
def test_reuses_the_shared_per_source_transcript(tmp_path, monkeypatch):
    src = tmp_path / "talk.mp4"
    src.write_bytes(b"not really a video, but bytes to hash" * 100)
    tr = dict(language="zh", segments=[dict(start=0.0, end=30.0, text="之前转写过的内容" * 3)])
    TS.save(asr.file_hash(str(src)), tr, None, None, "auto")      # what plan-segments / a batch asr stage left
    monkeypatch.setattr(I, "_wav_sample", lambda *a: (_ for _ in ()).throw(AssertionError("no audio extract")))
    monkeypatch.setattr(I, "_transcribe", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ASR")))
    evs = []
    out = I.speech_facts(str(src), 60.0, True, "full", str(tmp_path), "k", language="zh", on_event=evs.append)
    assert out["speech_basis"] == "asr full (reused, shared)" and out["sentences"] == 1
    assert [e.get("cached") for e in evs if e["stage"] == "transcribe"] == [None, "shared"]
    assert not any(n.endswith(".asr.json") for n in os.listdir(tmp_path))       # inputs stay untouched


def test_reuses_the_asr_sidecar_a_cli_run_wrote(tmp_path, monkeypatch):
    src = tmp_path / "talk.mp4"
    src.write_bytes(b"x" * 4096)
    fh = asr.file_hash(str(src))
    entry = dict(language="zh", backend="mlx", source_sha1=fh,
                 segments=[dict(start=0.0, end=5.0, text="命令行转写的", words=[])])
    (tmp_path / "talk.mp4.asr.json").write_text(json.dumps({"some-other-settings-key": entry}), encoding="utf-8")
    tr, where = I.reuse_transcript(str(src), "zh")
    assert where == "sidecar" and tr["segments"][0]["text"] == "命令行转写的"
    assert I.reuse_transcript(str(src), "en") == (None, None)          # another language is not the same words
    # an entry for other bytes (the file changed since) is not reused
    src.write_bytes(b"y" * 4096)
    assert I.reuse_transcript(str(src), "zh") == (None, None)


def test_fresh_transcript_goes_to_the_shared_cache(tmp_path, monkeypatch):
    src = tmp_path / "talk.mp4"
    src.write_bytes(b"z" * 2048)
    monkeypatch.setattr(I, "_wav_sample", lambda src_, dst, st, ln: dst)
    monkeypatch.setattr(I, "_transcribe", lambda wav, language=None, words=True, progress=None: dict(
        language="zh", segments=[dict(start=0, end=20, text="新转写的内容新转写的内容")]))
    I.speech_facts(str(src), 30.0, True, "full", str(tmp_path), "k", language="zh")
    _p, tr = TS.lookup(asr.file_hash(str(src)), "zh", None, "auto")
    assert tr and tr["segments"][0]["text"].startswith("新转写")      # a batch run of this recording reuses it


def test_asr_cached_exact_and_content_match(tmp_path, monkeypatch):
    src = tmp_path / "a.wav"
    src.write_bytes(b"w" * 1000)
    monkeypatch.setattr(asr, "_backend", lambda name="auto": "mlx")
    monkeypatch.setattr(asr, "_hst", lambda path, s: None)
    fh = asr.file_hash(str(src))
    key = asr._cache_key(fh, "zh", None, True, None, "mlx", None)
    seg = dict(start=0.0, end=1.0, text="精确命中", words=[dict(word="精确", start=0.0, end=0.5)])
    (tmp_path / "a.wav.asr.json").write_text(json.dumps({key: dict(language="zh", backend="mlx", segments=[seg])}),
                                             encoding="utf-8")
    assert asr.cached(str(src), language="zh")["text"] == "精确命中"
    assert asr.cached(str(src), language="zh", prompt="other terms") is None   # old entry: no source_sha1 to match
    assert asr.cached(str(tmp_path / "none.wav"), language="zh") is None


def test_cli_wav_transcript_found_through_the_content_index(tmp_path, monkeypatch):
    """A CLI run extracted ``work/audio.wav`` from the recording and cached ``audio.wav.asr.json`` next to it; the
    planner's own extraction has the same bytes, so after one ``index_sidecar`` (sidecars written before the index
    existed) or any new ``transcribe`` it reuses that transcript instead of running whisper for minutes."""
    work = tmp_path / "Projects" / "talk" / "work"
    work.mkdir(parents=True)
    pcm = b"RIFF....WAVEfmt " + bytes(range(256)) * 64
    (work / "audio.wav").write_bytes(pcm)
    old = dict(language="zh", backend="mlx", segments=[dict(start=0.0, end=9.0, text="命令行之前转写的内容", words=[])])
    (work / "audio.wav.asr.json").write_text(json.dumps({"k-old": old}), encoding="utf-8")
    src = tmp_path / "talk.mp4"
    src.write_bytes(b"the recording" * 50)

    def extract(src_, dst, st, ln):
        with open(dst, "wb") as f:
            f.write(pcm)                                    # same ffmpeg, same params: the same bytes
        return dst
    monkeypatch.setattr(I, "_wav_sample", extract)
    monkeypatch.setattr(I, "_transcribe", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no ASR")))
    first = I.speech_facts(str(src), 60.0, True, "full", str(tmp_path), "k", language="zh")
    assert not first["speech_basis"].startswith("asr full")      # not indexed yet: whisper was the only way
    assert asr.index_sidecar(str(work / "audio.wav.asr.json"), fh=asr.file_hash(str(work / "audio.wav")))
    evs = []
    out = I.speech_facts(str(src), 60.0, True, "full", str(tmp_path), "k2", language="zh", on_event=evs.append)
    assert out["speech_basis"] == "asr full (reused, audio)"
    assert [e.get("cached") for e in evs if e["stage"] == "transcribe"] == [None, "audio"]
    _p, shared = TS.lookup(asr.file_hash(str(src)), "zh", None, "auto")
    assert shared["segments"][0]["text"] == "命令行之前转写的内容"         # and kept per source from now on


def test_transcribe_indexes_what_it_caches(tmp_path, monkeypatch):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    import numpy as np
    from vstudio import audio
    a = tmp_path / "a" / "audio.wav"
    a.parent.mkdir()
    audio.write_wav(str(a), np.zeros((16000, 1), dtype=np.float32), 16000)
    monkeypatch.setitem(asr._RUN, "mlx", lambda wav, language, *x, **k: [dict(start=0.0, end=1.0, text="索引", words=[])])
    monkeypatch.setattr(asr, "_backend", lambda name="auto": "mlx")
    asr.transcribe(str(a), language="zh", prompt="some terms")
    b = tmp_path / "b.wav"
    shutil.copy(a, b)
    assert asr.cached(str(b), language="zh")["text"] == "索引"           # same bytes elsewhere, no sidecar there
    assert asr.cached(str(b), language="en") is None
    assert not (tmp_path / "b.wav.asr.json").exists()


# --------------------------------------------------------------------------- ASR progress hooks
def test_transcribe_reports_progress_and_restores(tmp_path, monkeypatch):
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg not installed")
    import numpy as np
    from vstudio import audio
    src = tmp_path / "a.wav"
    audio.write_wav(str(src), np.zeros((16000, 1), dtype=np.float32), 16000)

    def run(wav, language, *a, **k):
        asr._report(0.5, 1.0)
        return [dict(start=0.0, end=1.0, text="好", words=[])]
    monkeypatch.setitem(asr._RUN, "mlx", run)
    monkeypatch.setattr(asr, "_backend", lambda name="auto": "mlx")
    got = []
    asr.transcribe(str(src), language="zh", cache=False, progress=lambda d, t: got.append((d, t)))
    assert got == [(0.5, 1.0)] and asr._PROGRESS is None
    asr.transcribe(str(src), language="zh", cache=False)                        # no callback: nothing reported
    assert got == [(0.5, 1.0)]


def test_mlx_frame_bar_is_captured(monkeypatch):
    class Bar:                                          # the real tqdm bar (untouched outside the context)
        def __init__(self, **kw):
            pass
    mod = types.ModuleType("mlx_whisper.transcribe")
    mod.tqdm = types.SimpleNamespace(tqdm=Bar)
    monkeypatch.setitem(sys.modules, "mlx_whisper.transcribe", mod)
    got = []
    monkeypatch.setattr(asr, "_PROGRESS", lambda d, t: got.append((d, t)))
    with asr._mlx_progress(True):
        with mod.tqdm.tqdm(total=76400, unit="frames", disable=True) as bar:    # 764 s at 100 frames / s
            bar.update(25000)
            bar.update(25000)
    assert got == [(250.0, 764.0), (500.0, 764.0)]
    assert mod.tqdm.tqdm is Bar


# --------------------------------------------------------------------------- CLI
def test_cli_plan_json_events(tmp_path):
    (tmp_path / "notes.md").write_text("# 讲稿\n今天讲三个方法。\n", encoding="utf-8")
    e = dict(os.environ)
    e["PYTHONPATH"] = os.path.join(ROOT, "lib") + os.pathsep + e.get("PYTHONPATH", "")
    out = tmp_path / "plan.json"
    r = subprocess.run([sys.executable, "-m", "vstudio.intake", "plan", "--prompt", "用这份讲稿做 3 条讲解短视频",
                        "--inputs", str(tmp_path / "notes.md"), "--provider", "none", "--asr", "off", "--json",
                        "--json-events", "--out", str(out)], capture_output=True, text=True, env=e)
    assert r.returncode == 0, r.stderr
    lines = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]       # stdout: JSON lines only
    assert lines[-1]["event"] == "done" and lines[-1]["plan"]["kind"] == "vstudio.intake.plan"
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == lines[-1]["plan"]["id"]
    assert _stages(lines[:-1]) == ["scan", "scan", "probe", "write"]


def test_cli_plan_json_events_error(tmp_path):
    e = dict(os.environ)
    e["PYTHONPATH"] = os.path.join(ROOT, "lib") + os.pathsep + e.get("PYTHONPATH", "")
    r = subprocess.run([sys.executable, "-m", "vstudio.intake", "plan", "--prompt", "x", "--provider", "none",
                        "--json-events"], capture_output=True, text=True, env=e)
    assert r.returncode != 0
    last = json.loads(r.stdout.strip().splitlines()[-1])
    assert last["event"] == "error" and "no inputs" in last["error"]
