"""Background music library (vstudio.music): built-in generated beds (tempo, fades, cache), mood words, your own
folders + sidecars, and the wiring into the output-edit music bed, the offline phrase fallback and polish --music."""
import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

from vstudio import audio as A
from vstudio import music as MU

need_ff = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("VSTUDIO_MUSIC_DIRS", "")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))


def test_mood_words():
    assert MU.mood_of("加一个轻的背景音乐") == "calm"
    assert MU.mood_of("温暖一点的 vlog 配乐") == "warm"
    assert MU.mood_of("AI 产品讲解") == "tech"
    assert MU.mood_of("欢快 卡点") == "bright"
    assert MU.mood_of("文艺 回忆") == "story"
    assert MU.mood_of("") == "calm" and set(MU.moods()) == {"calm", "warm", "bright", "tech", "story"}


@pytest.mark.parametrize("mood", ["calm", "bright"])
def test_generate_shape_level_fades(mood):
    y = MU.generate(mood, 12.0, seed=0)
    assert y.shape == (12 * MU.SR, 2) and y.dtype == np.float32 and not np.isnan(y).any()
    assert 0.45 < float(np.max(np.abs(y))) <= 0.5 + 1e-6
    head, tail = np.abs(y[:int(0.05 * MU.SR)]).max(), np.abs(y[-int(0.05 * MU.SR):]).max()
    assert head < 0.05 and tail < 0.05                          # fades in and out, no click at the ends
    assert np.abs(y[int(5 * MU.SR):int(7 * MU.SR)]).max() > 0.1   # music in the middle
    assert not np.allclose(y[:, 0], y[:, 1])                     # stereo, not mono copied


@need_ff
def test_generated_tempo_matches_style(tmp_path):
    from vstudio import beats
    p = MU.make("bright", 16.0, out=str(tmp_path / "b.wav"))
    b = beats.analyze(p)
    assert abs(b.bpm - MU.STYLES["bright"]["bpm"]) < 3


def test_seed_varies_and_cache_reuses(tmp_path):
    a, b = MU.generate("tech", 8.0, seed=0), MU.generate("tech", 8.0, seed=3)
    assert not np.allclose(a, b)
    p1 = MU.make("calm", 6.0)
    m = os.path.getmtime(p1)
    assert MU.make("calm", 6.0) == p1 and os.path.getmtime(p1) == m


def test_own_folder_tracks_and_sidecar(tmp_path, monkeypatch):
    d = tmp_path / "mymusic"
    d.mkdir()
    A.write_wav(str(d / "sunny_upbeat_day.wav"), np.zeros((4800, 2), np.float32), 48000)
    A.write_wav(str(d / "x.wav"), np.zeros((4800, 2), np.float32), 48000)
    (d / "x.wav.json").write_text(json.dumps(dict(mood="story", license="CC0", source="freepd.com", title="Night")))
    monkeypatch.setenv("VSTUDIO_MUSIC_DIRS", str(d))
    rows = {t["title"]: t for t in MU.tracks() if t["source"] == "file"}
    assert rows["sunny_upbeat_day"]["mood"] == "bright" and rows["Night"]["mood"] == "story"
    assert rows["Night"]["license"] == "CC0"
    assert MU.resolve("Night") == str(d / "x.wav")
    assert MU.resolve(None, text="文艺一点") == str(d / "x.wav")   # own track of that mood wins
    assert MU.resolve("builtin:story", 5.0).endswith(".wav") and "x.wav" not in MU.resolve("builtin:story", 5.0)
    with pytest.raises(ValueError):
        MU.resolve("no such song")
    builtins = [t for t in MU.tracks() if t["source"] == "builtin"]
    assert len(builtins) == 5 and all("MIT" in t["license"] for t in builtins)


def test_output_edit_music_bed_accepts_a_mood():
    from vstudio.project import outfx as FX
    clean, _ = FX.validate("music-bed", {"mood": "warm"})
    assert clean["mood"] == "warm" and not clean.get("file")
    clean, _ = FX.validate("music-bed", {"file": "builtin:calm"})
    assert clean["mood"] == "calm" and not clean.get("file")
    with pytest.raises(ValueError):
        FX.validate("music-bed", {})
    with pytest.raises(ValueError):
        FX.validate("music-bed", {"file": "/nope/missing.mp3"})


def test_offline_phrases_add_music_and_studio_sound():
    from vstudio.project import outputs as OUT
    ops = OUT._rule_ops("加一个温暖的背景音乐，再降噪一下", 60.0)
    effs = {o["effect"]: o.get("params") for o in ops if o["op"] == "effect_add"}
    assert effs["music-bed"] == {"mood": "warm"} and effs["studio-sound"] == {"strength": "standard"}
    assert not [o for o in OUT._rule_ops("去掉背景音乐", 60.0) if o.get("effect") == "music-bed"]
    strong = OUT._rule_ops("太吵了，强力降噪", 60.0)
    assert strong[0]["params"]["strength"] == "strong"


@need_ff
def test_polish_music_flag(tmp_path):
    src = tmp_path / "export.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x284:rate=30:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=220:duration=4", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)], check=True)
    out = tmp_path / "final.mp4"
    env = dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib"))
    r = subprocess.run([sys.executable, os.path.join(ROOT, "workflows/polish/scripts/polish.py"), str(src), "-o",
                        str(out), "--music", "calm", "--crf", "23", "--preset", "veryfast"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr[-1500:]
    assert "music bed" in r.stdout and out.exists()
