"""Shared fixtures for the Create engine tests: an isolated store home, fake services and a fake AI (create_fake.py),
no model calls."""
import pathlib
import shutil
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture
def home(tmp_path, monkeypatch):
    import create_fake as fake
    from vstudio.create import costs, store
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "vhome"))
    monkeypatch.delenv("KLING_MCP_TOKEN", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store.configure(str(tmp_path / "vhome"))
    fake.install()
    fake.reset()
    costs.set_cap(300)
    yield tmp_path / "vhome"
    fake.uninstall()
    store.configure(None)


def sample_episode(lang="en"):
    from vstudio.create import sample
    r = sample.open_sample(lang)
    return r["series"], r["episode"]
