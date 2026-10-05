"""Beat analysis + SFX grammar on SYNTHETIC audio (numpy only, no files, no network)."""
import pathlib
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import audio, beats  # noqa: E402

SR = 22050


def drum_track(bpm=112.0, dur=30.0, drift=0.0, t0=0.37, quiet_until=0.0, seed=0):
    """Kick on every beat (downbeat louder), snare on 2 and 4, hats on the off-beats.
    drift: total relative tempo change across the track (0.015 = +1.5 %, linear).
    quiet_until: before this time only hats play (gives the novelty curve a section change)."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(dur * SR) + SR)
    T, t, times = 60.0 / bpm, t0, []
    while t < dur:
        times.append(t)
        t += T / (1 + drift * t / dur)

    def add(s, at, g):
        i = int(round(at * SR))
        j = min(len(x), i + len(s))
        x[i:j] += g * s[:j - i]

    tk = np.arange(int(0.25 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(50 + 120 * np.exp(-tk * 30)) / SR) * np.exp(-tk * 12)
    ts = np.arange(int(0.15 * SR)) / SR
    snare = np.convolve(rng.standard_normal(len(ts)), np.ones(4) / 4, "same") * np.exp(-ts * 30)
    th = np.arange(int(0.04 * SR)) / SR
    hat = np.diff(np.concatenate([[0], rng.standard_normal(len(th))])) * np.exp(-th * 120)
    for k, bt in enumerate(times):
        if bt >= quiet_until:
            add(kick, bt, 1.0 if k % 4 == 0 else 0.55)
            if k % 4 in (1, 3):
                add(snare, bt, 0.35)
        if k + 1 < len(times):
            add(hat, (bt + times[k + 1]) / 2, 0.25)
    return x[:int(dur * SR)].astype(np.float32), np.array(times)


@pytest.fixture(scope="module")
def steady():
    x, tb = drum_track()
    return beats.analyze(x, sr=SR, backend="numpy"), tb


def test_bpm_grid_and_downbeats(steady):
    b, tb = steady
    assert abs(b.bpm - 112.0) / 112.0 < 0.01
    assert b.grid_ok and b.residual_ms < 5.0
    assert b.tempo_check["chosen"] == 1.0
    # every true beat has a detected beat within 15 ms
    assert np.max([np.min(np.abs(b.beats - t)) for t in tb]) < 0.015
    # downbeat phase: detected downbeats sit on the loud (bar-start) kicks
    true_down = tb[::4]
    assert len(b.downbeats) >= 10
    assert all(np.min(np.abs(true_down - d)) < 0.02 for d in b.downbeats)
    assert abs(b.bar_t(1) - b.bar_t(0) - 4 * b.period) < 1e-9
    assert len(b.hits) > 0 and all(h["k"] in ("kick", "snare", "hat") for h in b.hits)
    assert {"kick", "snare", "hat"} <= set(b.onsets) and len(b.onsets["kick"]) >= 50
    assert b.rms is not None and len(b.rms) > 100
    assert b.to_dict()["bpm"] == b.bpm


def test_tempo_drift_keeps_raw_beats():
    x, tb = drum_track(drift=0.015)
    b = beats.analyze(x, sr=SR, backend="numpy")
    true_bpm = 60 / np.mean(np.diff(tb))
    assert abs(b.bpm - true_bpm) / true_bpm < 0.01
    assert not b.grid_ok and b.residual_ms > beats.GRID_TOL_MS
    # raw beats kept: they follow the drifting kicks closely
    assert np.max([np.min(np.abs(b.beats - t)) for t in tb[2:-2]]) < 0.015
    # snapping still lands on a real beat
    assert np.min(np.abs(tb - b.snap(20.1))) < 0.015


def test_sections_find_the_drop():
    x, _ = drum_track(dur=40.0, quiet_until=16.0)
    b = beats.analyze(x, sr=SR, backend="numpy")
    starts = [s["start"] for s in b.sections]
    assert any(abs(s - 16.0) < 1.2 for s in starts[1:]), b.sections
    assert b.sections[-1]["energy"] > b.sections[0]["energy"]


def test_snap_and_cut_plans(steady):
    b, _ = steady
    t = b.beat_t(10) + 0.1
    assert abs(b.snap(t) - b.beat_t(10)) < 1e-9
    assert abs(b.snap(t, direction="after") - b.beat_t(11)) < 1e-9
    assert abs(b.snap(t, grid="half") - b.beat_t(10)) < 1e-9
    assert abs(b.snap(b.beat_t(10.4), grid="half") - b.beat_t(10.5)) < 1e-9
    bar = b.snap(t, grid="bar", direction="before")
    assert (round(b.beat_n(bar)) - b.downbeat_phase) % 4 == 0

    every = b.cut_plan(6, 2.0, 10.0, "every-beat")
    assert len(every) == 6 and np.allclose(np.diff(every), b.period)
    two = b.cut_plan(4, 2.0, 12.0, "every-2")
    assert np.allclose(np.diff(two), 2 * b.period)

    acc = b.cut_plan(8, 4.0, 16.0, "accelerate")
    d = np.diff(acc)
    assert len(acc) == 8 and np.all(d[1:] <= d[:-1] + 1e-9) and d[-1] < d[0]
    assert all(4.0 - 1e-6 <= c <= 16.0 for c in acc)
    assert beats.verify(acc, b, grid=0.125, tol_frames=1)["ok"]
    # frames at 30 fps: the ladder ends in ~4-frame gaps
    assert round(d[-1] * 30) == 4

    drop = b.cut_plan(6, 2.0, 20.0, "drop")
    assert len(drop) == 6 and np.all(np.diff(drop) > 0)


def test_verify_flags_off_grid(steady):
    b, tb = steady
    cuts = [b.beat_t(n) for n in (4, 8, 12)] + [b.beat_t(16) + 0.2]
    rep = beats.verify(cuts, b, tol_frames=3, fps=30)
    assert not rep["ok"] and rep["bad"] == [3] and rep["n_bad"] == 1
    assert abs(rep["rows"][3]["audio_err_ms"] - 200) < 1
    assert beats.verify(cuts[:3], tb, fps=30)["ok"]


def test_energy_arc_travel(steady):
    b, _ = steady
    arc = beats.energy_arc(60.0, "travel-fun")
    assert arc[0]["name"] == "hook" and arc[0]["energy"] == 1.0
    assert abs(arc[0]["end"] / 60.0 - 0.08) < 0.01
    assert arc[-1]["name"] == "outro" and arc[-1]["end"] == 60.0
    assert arc[-2]["name"] == "finale" and arc[-2]["energy"] == 1.0
    names = [s["name"] for s in arc]
    assert sum(n.startswith("montage") for n in names) == 3 and sum(n.startswith("breather") for n in names) == 3
    assert all(a["end"] == c["start"] for a, c in zip(arc, arc[1:]))
    snapped = beats.energy_arc(28.0, "travel-fun", beats=b)
    for s in snapped[:-1]:
        assert (round(b.beat_n(s["end"])) - b.downbeat_phase) % 4 == 0
    for k in ("talking-head", "promo", "story"):
        a = beats.energy_arc(90.0, k)
        assert abs(sum(s["end"] - s["start"] for s in a) - 90.0) < 1e-6


NEW_SFX = ["riser", "impact", "impact_b", "boom", "sparkle", "shutter", "swoosh", "whip", "tick", "pop",
           "ding", "typewriter", "typing", "scratch", "stop", "soft"]


def test_every_sfx_renders(tmp_path):
    bank = audio.sfx_bank()
    assert {"whoosh", "pop", "ding", "stamp", "thud"} <= set(bank)       # originals still there
    for k in NEW_SFX:
        s = bank[k]
        assert s.dtype == np.float32 and s.ndim == 1 and len(s) > 0.02 * audio.SR, k
        assert np.abs(s).max() > 0.1, k
        assert 0 <= audio.sfx_peak(s) < len(s) / audio.SR, k
    assert audio.sfx_peak(bank["riser"]) > 2.0                          # risers peak late
    files = audio.write_sfx(str(tmp_path))
    assert "riser" in files and "boom" not in files and "thud" not in files
    x, sr = audio.read_wav(files["whip"])
    assert sr == 48000 and x.ndim == 2 and np.abs(x).max() > 0.1


def test_place_sfx_peak_align_and_trim():
    bank = audio.sfx_bank()
    for name in ("riser", "whip", "impact", "soft"):
        y = np.zeros(int(4 * audio.SR), np.float32)
        audio.place_sfx(y, [{"t": 3.0, "sfx": name}])
        assert abs(audio.sfx_peak(y) - 3.0) < 0.005, name
    # legacy tuples stay start-aligned
    y = np.zeros(audio.SR, np.float32)
    audio.place_sfx(y, [(0.2, "whip")])
    assert abs(np.flatnonzero(y)[0] / audio.SR - 0.2) < 0.001
    # gain_db and dur
    a = audio.place_sfx(np.zeros((audio.SR * 4, 2), np.float32), [{"t": 0.5, "sfx": "typing", "dur": 0.5,
                                                                     "peak_align": False}])
    nz = np.flatnonzero(np.abs(a[:, 0]) > 1e-6)
    assert nz[-1] / audio.SR <= 1.0 + 1e-3
    lo = audio.place_sfx(np.zeros(audio.SR, np.float32), [{"t": 0.1, "sfx": "pop", "gain_db": -6}])
    hi = audio.place_sfx(np.zeros(audio.SR, np.float32), [{"t": 0.1, "sfx": "pop"}])
    assert abs(np.abs(lo).max() / np.abs(hi).max() - 10 ** (-6 / 20)) < 0.01
    assert len(bank) > 20


def test_cue_sheet_grammar():
    cuts = [1.0, {"t": 1.1, "kind": "whip"}, {"t": 5.0, "kind": "beat"}, {"t": 6.0, "kind": "move"}]
    reveals = [{"t": 2.0, "kind": "photo"}, {"t": 9.0, "kind": "finale"}]
    cues = audio.cue_sheet_for(cuts, reveals, kind="travel-fun")
    names = [c["sfx"] for c in cues]
    assert all(set(c) == {"t", "sfx", "gain_db", "dur", "note"} for c in cues)
    # one transition per scene change: the scene cut and the whip 0.1 s apart collapse to one
    assert sum(1 for c in cues if c["t"] < 1.5 and c["sfx"] in ("soft", "whip")) == 1
    assert "shutter" in names and "whoosh" in names
    assert not any(abs(c["t"] - 5.0) < 0.01 for c in cues)                # beat cuts carry no SFX
    fin = [c["sfx"] for c in cues if c["t"] >= 9.0]
    assert fin == ["riser", "impact", "sparkle"]
    # repeated pops alternate variants and step down
    pops = audio.cue_sheet_for(reveals=[{"t": 10 + 0.4 * i, "kind": "item"} for i in range(3)],
                               max_per_2s=10)
    assert [c["sfx"] for c in pops] == ["pop", "pop_b", "pop"]
    assert pops[0]["gain_db"] > pops[1]["gain_db"] > pops[2]["gain_db"]
    # density cap: at most N cues in any 2 s window, the impact survives
    dense = [{"t": 20 + 0.25 * i, "kind": "text"} for i in range(12)] + [{"t": 21.0, "kind": "landing"}]
    capped = audio.cue_sheet_for(reveals=dense, max_per_2s=3)
    ts = [c["t"] for c in capped]
    assert all(sum(1 for u in ts if a <= u < a + 2.0) <= 3 for a in ts)
    assert any(c["sfx"].startswith("impact") for c in capped)
    # promo vocabulary drops the cartoon pop
    assert audio.cue_sheet_for(reveals=[{"t": 1, "kind": "item"}], kind="promo")[0]["sfx"] == "tick"
    # render: peaks land on cue times
    mix = audio.render_cue_sheet([{"t": 1.0, "sfx": "whip", "gain_db": 0, "dur": None, "note": ""}], 2.0)
    assert mix.shape == (2 * audio.SR, 2) and abs(audio.sfx_peak(mix) - 1.0) < 0.005
    full = audio.render_cue_sheet(cues, 12.0)
    assert np.abs(full).max() > 0.1 and np.abs(full).max() < 1.5


def test_cue_sheet_snaps_impacts_to_beats(steady):
    b, _ = steady
    t = b.beat_t(12) + 0.05
    cues = audio.cue_sheet_for(reveals=[{"t": t, "kind": "landing"}], beats=b)
    assert abs(cues[0]["t"] - b.beat_t(12)) < 1e-3


def test_librosa_backend_agrees():
    pytest.importorskip("librosa")
    x, tb = drum_track()
    b = beats.analyze(x, sr=SR, backend="librosa")
    assert b.backend == "librosa" and abs(b.bpm - 112.0) / 112.0 < 0.01 and b.grid_ok
    assert all(np.min(np.abs(tb[::4] - d)) < 0.02 for d in b.downbeats)
