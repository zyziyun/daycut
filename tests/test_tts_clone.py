"""vstudio.tts "clone" engine with a mocked model (no mlx-audio / Qwen3-TTS download needed)."""
import os
import pathlib
import shutil
import sys

import numpy as np
import pytest
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import config, tts  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


class _Res:
    def __init__(self, a):
        self.audio = a


class FakeModel:
    sample_rate = 24000

    def __init__(self):
        self.calls = []

    def generate(self, text, ref_audio, ref_text, language):
        self.calls.append(dict(text=text, ref_audio=ref_audio, ref_text=ref_text, language=language))
        t = np.arange(int(0.05 * len(text) * self.sample_rate)) / self.sample_rate
        yield _Res((0.2 * np.sin(2 * np.pi * 220 * t)).astype(np.float32))
        yield _Res(np.zeros(1200, np.float32))


@pytest.fixture
def env(tmp_path, monkeypatch):
    model = FakeModel()
    monkeypatch.setattr(tts, "_cache_dir", lambda: str(tmp_path / "cache"))
    os.makedirs(tmp_path / "cache", exist_ok=True)
    monkeypatch.setattr(tts, "_clone_model", lambda name: model)
    monkeypatch.setattr(config, "persona", lambda: {})
    ref = tmp_path / "ref.wav"
    sf.write(ref, np.random.default_rng(0).normal(0, 0.1, 24000).astype(np.float32), 24000)
    return model, ref, tmp_path


def test_clone_synth_48k_and_cache(env):
    model, ref, tmp = env
    out = tts.synth("Hello there.", engine="clone", ref_wav=str(ref), ref_text="reference words", seed=3,
                    out=str(tmp / "a.wav"))
    x, sr = sf.read(out)
    assert sr == 48000 and x.ndim == 1 and len(x) > 0.5 * 48000
    assert model.calls[-1]["language"] == "English" and model.calls[-1]["ref_text"] == "reference words"
    tts.synth("Hello there.", engine="clone", ref_wav=str(ref), ref_text="reference words", seed=3)
    assert len(model.calls) == 1                          # cache hit
    tts.synth("Hello there.", engine="clone", ref_wav=str(ref), ref_text="reference words", seed=4)
    assert len(model.calls) == 2                          # new seed = new take
    tts.synth("Hello there.", engine="clone", ref_wav=str(ref), ref_text="other words", seed=3)
    assert len(model.calls) == 3                          # ref text is part of the key
    sf.write(ref, np.random.default_rng(1).normal(0, 0.1, 24000).astype(np.float32), 24000)
    tts.synth("Hello there.", engine="clone", ref_wav=str(ref), ref_text="reference words", seed=3)
    assert len(model.calls) == 4                          # ref audio hash is part of the key
    tts.synth("你好。", engine="clone", ref_wav=str(ref), ref_text="reference words")
    assert model.calls[-1]["language"] == "Chinese"


def test_clone_reference_from_persona(env, monkeypatch):
    model, ref, tmp = env
    monkeypatch.setattr(config, "persona", lambda: {"tts": {"clone": {
        "ref_wav": str(ref), "ref_text": "from persona", "model": "my/model", "language": "en"}}})
    cfg = tts.clone_config()
    assert cfg["ref_wav"] == str(ref) and cfg["model"] == "my/model" and cfg["language"] == "English"
    tts.synth("Persona voice.", engine="clone")
    assert model.calls[-1]["ref_text"] == "from persona"


def test_clone_missing_reference(env):
    with pytest.raises(RuntimeError, match="ref_wav"):
        tts.synth("x", engine="clone")
    with pytest.raises(RuntimeError, match="ref_text"):
        tts.clone_config(ref_wav=str(env[1]))


def test_other_engines_unchanged():
    assert tts.DEFAULT_MODEL["openai"] == "gpt-4o-mini-tts"
    assert tts.cache_key("a", "openai", "cedar", 1.0, None, "gpt-4o-mini-tts") == \
        tts.cache_key("a", "openai", "cedar", 1.0, "", "gpt-4o-mini-tts")
    assert tts.pick_engine("clone") == "clone"
