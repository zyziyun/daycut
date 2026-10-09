"""The engine runs without scipy (the Mac App Store build ships no scipy: its compiled extensions import
non-public Accelerate symbols). audio._filt replaces scipy.signal.lfilter, retouch.gaussian_filter1d replaces
scipy.ndimage.gaussian_filter1d, make_audio_assets.py writes its WAVs with soundfile. Each one is checked
against scipy when the dev environment has it, and on its own (known responses) when it does not."""
import json
import pathlib
import subprocess
import sys
import wave

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from vstudio import audio  # noqa: E402

SR = 48000
# the coefficient sets audio.py uses: BS.1770 K-weighting shelf + RLB high-pass (48 kHz)
K_SHELF = ([1.53512485958697, -2.69169618940638, 1.19839281085285], [1.0, -1.69065929318241, 0.73248077421585])
K_HP = ([1.0, -2.0, 1.0], [1.0, -1.99004745483398, 0.99007225036621])
# not used by the code, but cover a0 != 1 normalisation and a first-order section
OTHER = (([0.2, 0.4, 0.2], [2.0, -0.5, 0.25]), ([0.5, -0.5], [1.0, -0.9]))
BLOCK_SCIPY = ("import sys; sys.modules['scipy'] = None; "            # any `import scipy...` now raises ImportError
               f"sys.path.insert(0, {str(ROOT / 'lib')!r}); ")


def _naive(b, a, x):
    """Direct form II transposed, one sample at a time (the textbook definition of lfilter)."""
    b = np.asarray(b, float) / a[0]
    a = np.asarray(a, float) / a[0]
    m = max(len(a), len(b))
    b, a = np.pad(b, (0, m - len(b))), np.pad(a, (0, m - len(a)))
    x = np.asarray(x, float).reshape(len(x), -1)
    y = np.zeros_like(x)
    z = np.zeros((m, x.shape[1]))
    for i in range(len(x)):
        y[i] = b[0] * x[i] + z[0]
        for k in range(1, m):
            z[k - 1] = b[k] * x[i] - a[k] * y[i] + z[k]
    return y


# ------------------------------------------------------------------ lfilter
def _signals():
    rng = np.random.default_rng(3)
    yield rng.standard_normal(SR * 3) * 0.3                       # mono, 3 s
    yield rng.standard_normal((SR * 3, 2)) * 0.3                  # stereo, the layout integrated_lufs uses
    for n in (0, 1, 7, 255, 256, 257, 4095, 4096):                # empty, shorter than a block, block edges
        yield rng.standard_normal((n, 2))


def _jit(b, a, x):
    jit = audio._df2t_jit()
    if jit is None:
        pytest.skip("numba not installed (Intel Mac / Windows / CI use the numpy block form)")
    x2 = x.reshape(len(x), x.shape[1] if x.ndim > 1 else 1)
    return jit(*audio._ba(b, a), np.ascontiguousarray(x2), np.empty(x2.shape)).reshape(x.shape)


def _blocks(b, a, x, **kw):
    x2 = x.reshape(len(x), x.shape[1] if x.ndim > 1 else 1)
    return audio._filt_blocks(b, a, x2, **kw).reshape(x.shape)


# _filt picks numba for >= 4096 samples when installed; every path is checked on its own
PATHS = {"filt": audio._filt, "blocks": _blocks, "jit": _jit,
         "blocks-small-chunks": lambda b, a, x: _blocks(b, a, x, L=64, chunk=3)}   # many chunk edges


@pytest.mark.parametrize("path", list(PATHS))
@pytest.mark.parametrize("ba", [K_SHELF, K_HP, *OTHER])
def test_lfilter_matches_scipy(ba, path):
    signal = pytest.importorskip("scipy.signal")
    worst = 0.0
    for x in _signals():
        y = PATHS[path](*ba, x)
        ref = signal.lfilter(*ba, x, axis=0)
        assert y.shape == x.shape and y.dtype == np.float64
        if x.size:
            worst = max(worst, float(np.abs(y - ref).max()))
    assert worst < 1e-11, worst


@pytest.mark.parametrize("path", list(PATHS))
@pytest.mark.parametrize("ba", [K_SHELF, K_HP, *OTHER])
def test_lfilter_matches_the_sample_loop(ba, path):
    x = np.random.default_rng(1).standard_normal((5000, 2))
    assert np.abs(PATHS[path](*ba, x) - _naive(*ba, x)).max() < 1e-11
    assert np.abs(PATHS[path](*ba, x[:, 0]) - _naive(*ba, x[:, 0])[:, 0]).max() < 1e-11


def test_lfilter_impulse_response_of_a_known_biquad():
    # y[n] = x[n] + 0.5 y[n-1]: impulse response 0.5^n, FIR part only: b itself
    imp = np.zeros(2000)
    imp[0] = 1.0
    assert np.allclose(audio._filt([1.0, 0.0, 0.0], [1.0, -0.5, 0.0], imp), 0.5 ** np.arange(2000), atol=1e-15)
    assert np.allclose(audio._filt([0.25, 0.5, 0.25], [1.0, 0.0, 0.0], imp)[:4], [0.25, 0.5, 0.25, 0.0])
    # the K-weighting high-pass removes DC; the shelf has unit gain at DC
    dc = np.ones(SR * 2)
    assert abs(audio._filt(*K_HP, dc)[-1]) < 1e-6
    assert abs(audio._filt(*K_SHELF, dc)[-1] - sum(K_SHELF[0]) / sum(K_SHELF[1])) < 1e-9


def test_integrated_lufs_of_a_reference_sine():
    # BS.1770: a 997 Hz sine at -20 dBFS in one channel reads -23.0 LUFS (-3.01 dB offset of a sine)
    t = np.arange(SR * 5) / SR
    x = 0.1 * np.sin(2 * np.pi * 997 * t)
    assert abs(audio.integrated_lufs(x) - (-23.01)) < 0.05
    assert abs(audio.integrated_lufs(np.stack([x, x], 1)) - (-20.0)) < 0.05


# ------------------------------------------------------------------ gaussian_filter1d
def _retouch():
    pytest.importorskip("cv2")
    from vstudio import retouch
    return retouch


@pytest.mark.parametrize("sigma", [3.0, 7.3, 38.4])
def test_gaussian_matches_scipy(sigma):
    ndimage = pytest.importorskip("scipy.ndimage")
    R = _retouch()
    rng = np.random.default_rng(5)
    # body_slim smooths per-row centres / half-widths / presence of an image column (length = image height);
    # include signals shorter than the kernel radius (int(4 sigma + 0.5)), where 'reflect' repeats
    for n in (1, 2, 5, 12, 13, 100, 720, 1920):
        x = np.cumsum(rng.standard_normal(n)) + 500
        y = R.gaussian_filter1d(x, sigma)
        assert y.shape == x.shape
        assert np.abs(y - ndimage.gaussian_filter1d(x, sigma)).max() < 1e-9
        p = (rng.random(n) > .5).astype(float)                    # 0/1 presence row like body_slim's
        assert np.abs(R.gaussian_filter1d(p, sigma) - ndimage.gaussian_filter1d(p, sigma)).max() < 1e-12


def test_gaussian_basic_properties():
    R = _retouch()
    for n in (3, 50, 1000):
        assert np.allclose(R.gaussian_filter1d(np.full(n, 4.2), 3.0), 4.2, atol=1e-12)   # constant unchanged
    imp = np.zeros(401)
    imp[200] = 1.0
    k = R.gaussian_filter1d(imp, 10.0)
    assert abs(k.sum() - 1.0) < 1e-12 and np.allclose(k, k[::-1])                         # normalised, symmetric
    assert k[200 - 40] > 0 and k[200 - 41] == 0                                           # radius int(4 * 10 + .5)
    assert abs(np.sum((np.arange(401) - 200) ** 2 * k) - 100.0) < 0.2                     # variance ~sigma^2
    # 'reflect' = half-sample symmetric: a ramp's ends bend toward the edge sample, not past it
    assert np.allclose(R.gaussian_filter1d(np.array([1.0, 2.0]), 3.0), [1.5, 1.5], atol=.05)


# ------------------------------------------------------------------ WAV writer + no-scipy imports
def _run_make_audio_assets(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out")}))
    script = ROOT / "workflows" / "longform-to-short" / "scripts" / "make_audio_assets.py"
    code = BLOCK_SCIPY + (f"sys.argv = [{str(script)!r}, {str(work / 'config.json')!r}, '--hook-bed']; "
                          f"sys.path.insert(0, {str(script.parent)!r}); import runpy; runpy.run_path({str(script)!r}, run_name='__main__')")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return work


def test_make_audio_assets_writes_pcm16_stereo_wavs_without_scipy(tmp_path):
    work = _run_make_audio_assets(tmp_path)
    for name, dur, peak_db in (("card_sting.wav", 1.6, -19.0), ("hook_bgm.wav", 12.0, -21.0)):
        with wave.open(str(work / name)) as w:                    # plain PCM WAV the stdlib can read
            assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (2, 2, SR)
            assert w.getnframes() == int(SR * dur)
            pcm = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)
        assert abs(20 * np.log10(np.abs(pcm).max() / 32767) - peak_db) < 0.1
        assert np.array_equal(pcm[:, 1], np.roll(pcm[:, 0], 180 if name == "card_sting.wav" else 240))


def test_make_audio_assets_wav_reads_back_identically_in_scipy(tmp_path):
    wavfile = pytest.importorskip("scipy.io.wavfile")
    sf = pytest.importorskip("soundfile")
    work = _run_make_audio_assets(tmp_path)
    rate, data = wavfile.read(str(work / "card_sting.wav"))
    ref, rate2 = sf.read(str(work / "card_sting.wav"), dtype="int16")
    assert rate == rate2 == SR and data.dtype == np.int16 and np.array_equal(data, ref)
    assert sf.info(str(work / "card_sting.wav")).subtype == "PCM_16"


@pytest.mark.parametrize("numba", ["numba if installed", "no numba"])
def test_engine_modules_work_with_scipy_blocked(numba):
    pytest.importorskip("cv2")
    code = BLOCK_SCIPY + ("sys.modules['numba'] = None; " if numba == "no numba" else "") + (
        "import numpy as np; from vstudio import audio, retouch; "
        "x = np.random.default_rng(0).standard_normal((48000 * 3, 2)) * 0.1; "
        "print(round(audio.integrated_lufs(x), 2)); "
        "print(retouch.gaussian_filter1d(np.arange(50.0), 3.0)[25]); "
        "print(any(m == 'scipy' or m.startswith('scipy.') for m, v in sys.modules.items() if v is not None))")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lufs, mid, leaked = r.stdout.split()
    assert -16 < float(lufs) < -11 and abs(float(mid) - 25.0) < 1e-9 and leaked == "False"
