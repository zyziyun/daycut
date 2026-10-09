"""media.run kills an ffmpeg whose progress stops (real ffmpeg blocked on a silent FIFO) instead of hanging."""
import os
import shutil
import subprocess
import time

import pytest

from vstudio import media

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not hasattr(os, "mkfifo"), reason="needs ffmpeg + fifo")


def test_stalled_ffmpeg_is_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "STALL_S", 2.0)
    fifo = tmp_path / "silent.pcm"
    os.mkfifo(fifo)
    hold = os.open(fifo, os.O_RDWR)                  # a writer that never writes: ffmpeg blocks on read
    try:
        t0 = time.monotonic()
        with pytest.raises(media.FFmpegError, match="stalled"):
            media.run(["ffmpeg", "-y", "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", str(fifo),
                       "-f", "null", "-"])
        assert time.monotonic() - t0 < 30
    finally:
        os.close(hold)
    left = subprocess.run(["pgrep", "-f", str(fifo)], capture_output=True, text=True).stdout.strip()
    assert not left, f"orphan ffmpeg: {left}"


def test_healthy_ffmpeg_unaffected(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "STALL_S", 2.0)
    out = tmp_path / "tone.wav"
    r = media.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=d=1", str(out)], capture=True)
    assert r.returncode == 0 and out.stat().st_size > 0
    assert "-progress" not in r.args
