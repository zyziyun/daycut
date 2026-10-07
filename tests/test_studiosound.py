"""Studio sound (vstudio.studiosound): synthetic voice + noise / hum / room -> the noise goes down, the voice stays;
file path keeps the picture; output-edit effect, polish flag and recorder wiring."""
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

from vstudio import audio as A
from vstudio import studiosound as SS

need_ff = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
SR = SS.SR
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def voice(seconds=6.0, seed=1):
    """Syllables of a harmonic 'voice' (f0 170-230 Hz, formant-ish rolloff) with gaps between words."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = np.zeros_like(t)
    on = np.zeros_like(t, bool)
    s = 0.3
    while s < seconds - 0.5:
        d = rng.uniform(0.18, 0.4)
        m = (t >= s) & (t < s + d)
        f0 = rng.uniform(170, 230)
        env = np.sin(np.pi * (t[m] - s) / d) ** 0.5
        x[m] += env * sum(np.sin(2 * np.pi * f0 * h * t[m]) / h ** 1.2 for h in range(1, 18))
        on |= m
        s += d + rng.uniform(0.15, 0.5)
    x = x / np.max(np.abs(x)) * 0.5
    return x.astype(np.float32), on


def db(v):
    return 10 * np.log10(max(float(np.mean(np.asarray(v, np.float64) ** 2)), 1e-20))


def test_strength_aliases():
    assert SS.strength_of(None) == "standard" and SS.strength_of("强") == "strong" and SS.strength_of("轻") == "light"
    assert SS.strength_of(0.9) == "strong" and SS.strength_of("medium") == "standard"
    with pytest.raises(ValueError):
        SS.strength_of("max")


@need_ff
def test_noise_goes_down_voice_stays():
    x, on = voice()
    rng = np.random.default_rng(3)
    n = rng.standard_normal(len(x)).astype(np.float32) * 0.02            # ~ 20 dB under the voice
    y, info = SS.enhance_array(x + n, SR, "standard")
    gap = ~on
    gap[:SR // 10] = False                                                  # skip the edges
    assert db((x + n)[gap]) - db(y[gap]) >= 12                              # gaps: noise down a lot
    snr_in = db(x[on]) - db(n[gap])
    assert (db(y[on]) - db(y[gap])) - snr_in >= 6                           # whole chain (incl. compressor)
    d = SS._spectral(x + n, SS.STRENGTHS["standard"], None)                 # the denoiser alone (no EQ / comp)
    assert (db(d[on]) - db(d[gap])) - snr_in >= 10                          # voice-to-gap ratio up >= 10 dB
    assert abs(db(d[on]) - db(x[on])) < 1.5                                 # syllables keep their level
    assert np.corrcoef(d[on], x[on])[0, 1] > 0.97                           # ... and their shape
    assert info["noise_drop_db"] > 6
    y_light, _ = SS.enhance_array(x + n, SR, "light")
    y_strong, _ = SS.enhance_array(x + n, SR, "strong")
    assert db(y_strong[gap]) < db(y[gap]) < db(y_light[gap])                # strength orders the result


@need_ff
def test_stereo_shape_and_silence_passthrough():
    x, _ = voice(3.0)
    st = np.stack([x, x * 0.8], 1)
    y, _ = SS.enhance_array(st, SR, "light")
    assert y.shape == st.shape
    z = np.zeros((SR, 2), np.float32)
    y0, info = SS.enhance_array(z, SR)
    assert info.get("skipped") and not np.any(y0)


def test_hum_and_reverb_analysis():
    x, _ = voice(5.0)
    t = np.arange(len(x)) / SR
    hum = (0.02 * np.sin(2 * np.pi * 60 * t) + 0.01 * np.sin(2 * np.pi * 120 * t)
           + 0.006 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    rng = np.random.default_rng(0)
    floor = rng.standard_normal(len(x)).astype(np.float32) * 0.0005
    assert SS.analyze(x + hum + floor)["hum_hz"] == 60.0
    assert SS.analyze(x + floor)["hum_hz"] is None
    ir_t = np.arange(int(0.9 * SR)) / SR
    ir = rng.standard_normal(len(ir_t)) * np.exp(-6.9 * ir_t / 0.9)
    ir[0] = 4.0
    wet = np.convolve(x, ir)[:len(x)]
    wet = (wet / np.max(np.abs(wet)) * 0.5).astype(np.float32)
    dry, room = SS.analyze(x + floor)["t60"], SS.analyze(wet + floor)["t60"]
    assert room is not None and (dry is None or room > dry)


def test_tone_chain_notches_only_with_hum():
    assert "bandreject" not in SS.tone_chain(1.0, None)
    assert SS.tone_chain(1.0, 50.0).count("bandreject") == 4
    assert "equalizer" not in SS.tone_chain(0.0, None)


@need_ff
def test_enhance_file_keeps_picture_and_sets_loudness(tmp_path):
    x, _ = voice(4.0)
    rng = np.random.default_rng(5)
    wav = tmp_path / "v.wav"
    A.write_wav(str(wav), x * 0.3 + rng.standard_normal(len(x)).astype(np.float32) * 0.01, SR)
    src = tmp_path / "take.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x284:rate=30:duration=4",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
                   check=True)
    out = tmp_path / "take.studio.mp4"
    rep = SS.enhance(str(src), str(out), "standard", report=str(tmp_path / "r.json"))
    from vstudio import media
    a, b = media.probe(str(src)), media.probe(str(out))
    assert b["has_video"] and b["has_audio"] and abs(a["duration"] - b["duration"]) < 0.1
    assert (b["w"], b["h"]) == (a["w"], a["h"])
    assert abs(A.measure_loudness(str(out))["input_i"] - (-14.0)) < 1.0
    assert rep["after"]["noise_db"] < rep["before"]["noise_db"] and (tmp_path / "r.json").exists()


@need_ff
def test_ab_writes_level_matched_clips(tmp_path):
    x, _ = voice(4.0)
    wav = tmp_path / "v.wav"
    A.write_wav(str(wav), x + np.random.default_rng(2).standard_normal(len(x)).astype(np.float32) * 0.02, SR)
    rep = SS.ab(str(wav), str(tmp_path / "ab"), 0.5, 3.0, strengths=("light", "strong"))
    names = sorted(os.listdir(tmp_path / "ab"))
    assert names == ["0_original.wav", "1_light.wav", "2_strong.wav", "report.json"]
    lv = [A.measure_loudness(r["file"])["input_i"] for r in rep["rows"]]
    assert max(lv) - min(lv) < 1.5                                          # same loudness: fair listening


def test_output_edit_effect_registered():
    from vstudio import effects
    from vstudio.project import outfx as FX
    assert "studio-sound" in effects.REGISTRY
    assert FX.resolve("降噪") == "studio-sound" and FX.resolve("人声增强") == "studio-sound"
    row = next(r for r in FX.catalogue() if r["id"] == "studio-sound")
    assert row["stage"] == "audio" and row["params"]["strength"]["default"] == "standard"
    clean, _ = FX.validate("studio-sound", {"strength": "strong"})
    assert clean["strength"] == "strong"


@need_ff
def test_polish_studio_sound_flag(tmp_path):
    x, _ = voice(3.0)
    wav = tmp_path / "v.wav"
    A.write_wav(str(wav), x * 0.2 + np.random.default_rng(4).standard_normal(len(x)).astype(np.float32) * 0.01, SR)
    src = tmp_path / "export.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=160x284:rate=30:duration=3",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
                   check=True)
    out = tmp_path / "final.mp4"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "workflows/polish/scripts/polish.py"), str(src), "-o",
                        str(out), "--studio-sound", "--crf", "23", "--preset", "veryfast"],
                       capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "lib")))
    assert r.returncode == 0, r.stderr[-1500:]
    assert "studio sound (standard)" in r.stdout and out.exists()


@need_ff
def test_output_edit_renders_studio_sound_and_builtin_music(tmp_path, monkeypatch):
    """A finished clip gets 「降噪」 + a built-in music bed through the output editor and renders."""
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VSTUDIO_CACHE", str(tmp_path / "cache"))
    from vstudio import media
    from vstudio.project import outputs as O, outrender as R, works
    x, _ = voice(5.0)
    wav = tmp_path / "v.wav"
    A.write_wav(str(wav), x * 0.3 + np.random.default_rng(6).standard_normal(len(x)).astype(np.float32) * 0.01, SR)
    w = tmp_path / "work"
    (w / "final").mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=5",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(w / "final" / "clip.mp4")], check=True)
    (w / "REPORT.md").write_text("# clip\n")
    works.adopt(str(w))
    oid = "final/clip.mp4"
    r = O.edit(str(w), oid, [dict(op="effect_add", effect="降噪", start=0, params=dict(strength="strong")),
                             dict(op="effect_add", effect="music-bed", start=0, params=dict(mood="calm"))])
    kinds = {e["effect"]: e["params"] for e in r["state"]["effects"]}
    assert kinds["studio-sound"]["strength"] == "strong" and kinds["music-bed"]["mood"] == "calm"
    res = R.render(str(w), oid, quality="preview")
    out = res["targets"][0]["file"]
    p = media.probe(out)
    assert p["has_audio"] and abs(p["duration"] - 5.0) < 0.3
    assert abs(A.measure_loudness(out)["input_i"] - (-14.0)) < 1.5
