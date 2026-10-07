"""Spoken language: "auto" detects it per recording (the desk app sets VSTUDIO_ASR_LANGUAGE=auto for a creator without
a persona, whose bundled example persona says "zh"); the intake samples detect once and reuse it."""
import shutil

import pytest

from vstudio import asr
from vstudio.intake import inventory as I


def test_default_language_env_then_persona(monkeypatch):
    monkeypatch.delenv("VSTUDIO_ASR_LANGUAGE", raising=False)
    assert asr.default_language() == asr._persona_language()
    monkeypatch.setenv("VSTUDIO_ASR_LANGUAGE", "Auto")
    assert asr.default_language() == "auto"


def test_auto_detects_before_transcribing(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    src = tmp_path / "a.wav"
    import numpy as np
    from vstudio import audio
    audio.write_wav(str(src), np.zeros((16000, 1), dtype=np.float32), 16000)
    calls = []
    monkeypatch.setitem(asr._DETECT, "mlx", lambda wav, model: "en")
    monkeypatch.setitem(asr._RUN, "mlx", lambda wav, language, *a, **k: calls.append(language) or [])
    monkeypatch.setattr(asr, "_backend", lambda name="auto": "mlx")
    monkeypatch.setenv("VSTUDIO_ASR_LANGUAGE", "auto")
    tr = asr.transcribe(str(src), cache=False)
    assert calls and calls[0] == "en" and tr["language"] == "en"
    # a detection that fails falls back to the persona's language, never crashes the transcription
    monkeypatch.setitem(asr._DETECT, "mlx", lambda wav, model: (_ for _ in ()).throw(RuntimeError("no model")))
    calls.clear()
    asr.transcribe(str(src), cache=False)
    assert calls[0] == asr._persona_language()


def test_intake_samples_detect_once(tmp_path, monkeypatch):
    langs = []

    def fake(wav, language):
        langs.append(language)
        return dict(language="en", segments=[dict(start=0, end=2, text="hello there everyone")], words=[])
    monkeypatch.setattr(I, "TRANSCRIBE", fake)
    monkeypatch.setattr(I, "_wav_sample", lambda src, dst, st, ln: dst)
    out = I.speech_facts("x.mp4", 300.0, True, "sample", str(tmp_path), "k")
    assert out["language"] == "en"
    assert langs == [None, "en", "en"]           # the first sample detects, the next two reuse it
