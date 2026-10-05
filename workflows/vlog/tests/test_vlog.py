"""vlog workflow tests on SYNTHETIC media (lavfi clips, a numpy drum track, generated photos).

    python3 -m pytest workflows/vlog/tests -q          # ~6-8 min: two fun renders + calm regression

Fun style, rendered for xiaohongshu:full (1080x1920) and youtube (1920x1080):
  canvas + duration, every cut within +-1 frame of a TRUE beat of the synthetic song (and beats.verify),
  hard cuts visible as frame-difference spikes on the planned frame, transitions rendered (flash = white
  frame, leak = brighter frame, whip = horizontal motion blur, zoom/glitch = spike), loudness at the profile
  target, captions inside platform.caption_box (master vs clean master), SFX peaks at cue times in the
  no-music version, speech kept whole, true slow-mo from the 120 fps clip (no repeated frames), HEIC photo,
  overlay boxes inside the safe box, <= 3 full-frame hits >= 16 beats apart.
Calm style: build_vlog.py output identical to the HEAD version (no regression), and a platform-wired run.
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
LIB = ROOT / "lib"
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(HERE))

from vstudio import audio as A  # noqa: E402
from vstudio import platform as P  # noqa: E402

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

FPS = 30


def run(*cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-3000:] + r.stdout[-2000:]
    return r.stdout


@pytest.fixture(scope="module")
def synth(tmp_path_factory):
    """Synthetic project dir. VLOG_TEST_DIR=/some/dir keeps media + renders between runs (debugging)."""
    import synth as S
    keep = os.environ.get("VLOG_TEST_DIR")
    d = pathlib.Path(keep) if keep else tmp_path_factory.mktemp("vlog")
    if not (d / "music" / "song.truth.json").exists():
        S.main(str(d))
    (d / "work").mkdir(exist_ok=True)
    return d


FUN_XHS = {
    "style": "fun", "platform": "xiaohongshu:full", "src_dir": "../footage", "photo_dir": "../photos",
    "music": "../music/song.wav", "drops": [16.5], "preset": "ultrafast",
    "title": {"text": "Harbour Weekend", "sub": "3 days by the sea"},
    "map": {"places": [{"name": "Old Town", "lat": 38.71, "lon": -9.14},
                       {"name": "Harbour", "lat": 38.69, "lon": -9.21},
                       {"name": "Cape", "lat": 38.78, "lon": -9.50}], "beats": 8},
    "word_pops": ["GO"], "end_card": {"text": "See you next trip", "sub": "@your-handle"},
    "shots": [
        {"clip": "scenery.mp4", "place": "Old Town", "day": 1, "date": "2026.05.01 09:12"},
        {"clip": "portrait.mp4", "place": "Old Town", "day": 1},
        {"clip": "talk.mp4", "speech": "auto", "place": "Old Town", "day": 1},
        {"clip": "slowmo.mp4", "ramp": "slowmo", "place": "Harbour", "day": 2},
        {"photo": "photo1.jpg", "place": "Harbour", "day": 2},
        {"clip": "scenery.mp4", "place": "Harbour", "day": 2, "freeze": True},
        {"clip": "portrait.mp4", "place": "Cape", "day": 3, "ramp": "slow-fast"},
        {"photo": "photo2.heic", "place": "Cape", "day": 3, "style": "full"}],
    "out": "fun_xhs.mp4",
}

FUN_YT = {
    "style": "fun", "platform": "youtube", "src_dir": "../footage", "photo_dir": "../photos",
    "music": "../music/song.wav", "preset": "ultrafast", "tighten": True,
    "title": "Coast Trip", "end_card": "Thanks for watching",
    "shots": [
        {"clip": "scenery.mp4", "place": "Bay"},
        {"clip": "talk.mp4", "speech": True, "start": 2.0, "dur": 1.0, "place": "Bay"},
        {"clip": "slowmo.mp4", "ramp": "fast-slow-fast", "place": "Pier"},
        {"clip": "portrait.mp4", "place": "Hill", "pop": "WOW"},
        {"photo": "photo1.jpg", "place": "Market"},
        {"clip": "scenery.mp4", "place": "Beach", "transition": "zoom"}],
    "out": "fun_yt.mp4",
}


def build(synth, cfg, *flags):
    p = synth / "work" / (os.path.splitext(cfg["out"])[0] + ".json")
    stem = synth / "work" / os.path.splitext(cfg["out"])[0]
    rp = stem.parent / (stem.name + ".report.json")
    reuse = os.environ.get("VLOG_TEST_DIR") and rp.exists() and p.exists() and json.loads(p.read_text()) == cfg \
        and not json.loads(rp.read_text()).get("dry_run")
    if not reuse:
        p.write_text(json.dumps(cfg))
        run(sys.executable, SCRIPTS / "build_fun.py", p, "--no-asr", *flags)
    return stem, json.loads((stem.parent / (stem.name + ".report.json")).read_text())


@pytest.fixture(scope="module")
def xhs(synth):
    return build(synth, FUN_XHS, "--clean-master")


@pytest.fixture(scope="module")
def yt(synth):
    return build(synth, FUN_YT, "--clean-master")


def probe(path):
    from vstudio import media
    return media.probe(str(path))


def grey_frames(path, w=96):
    from vstudio import media
    info = media.probe(str(path))
    h = int(round(info["h"] * w / info["w"] / 2) * 2)
    raw = subprocess.run([media.ffmpeg_bin(), "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h}", "-f",
                          "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3).astype(np.float32)


def frame_at(path, f, fps=FPS):
    from vstudio import media
    info = media.probe(str(path))
    raw = subprocess.run([media.ffmpeg_bin(), "-v", "error", "-i", str(path), "-vf", f"select=eq(n\\,{f})",
                          "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(info["h"], info["w"], 3).astype(np.float32)


# ------------------------------------------------------------------------------------------- fun
@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_canvas_duration_loudness(which, request):
    stem, rep = request.getfixturevalue(which)
    prof = P.profile(rep["platform"])
    info = probe(str(stem) + ".mp4")
    assert (info["w"], info["h"]) == (prof.w, prof.h)
    assert abs(info["duration"] - rep["duration"]) < 2.5 / FPS
    assert rep["frames_written"] == rep["frames"]
    m = A.measure_loudness(str(stem) + ".mp4")
    assert abs(m["input_i"] - prof.loudness["lufs"]) <= 1.0, m
    assert m["input_tp"] <= prof.loudness["tp"] + 0.6
    assert not P.check_length(prof, rep["duration"]) or rep["warnings"]


@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_cuts_on_true_beats(which, request, synth):
    stem, rep = request.getfixturevalue(which)
    truth = json.loads((synth / "music" / "song.truth.json").read_text())
    beats_v = np.array(truth["beats"]) - rep["music_start"]
    period = 60.0 / truth["bpm"]
    cuts = [c["t"] for c in rep["cuts"]]
    assert len(cuts) >= 8
    for t in cuts:
        k = np.round((t - beats_v[0]) / period)
        tb = beats_v[0] + k * period                    # true grid (extrapolated past the analysed range)
        assert abs(round(t * FPS) / FPS - tb) <= 1.0 / FPS + 1e-6, (t, tb)
    assert rep["verify"]["ok"] and rep["verify"]["max_abs_frames"] <= 1.0
    assert abs(rep["bpm"] - truth["bpm"]) < 0.5


@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_cut_spikes_and_transitions(which, request):
    stem, rep = request.getfixturevalue(which)
    fr = grey_frames(str(stem) + ".clean.mp4")
    diff = np.abs(np.diff(fr, axis=0)).mean(axis=(1, 2, 3))     # diff[k] = frame k+1 vs k
    lum = fr.mean(axis=(1, 2, 3))
    med = float(np.median(diff))
    kinds = set()
    for c in rep["cuts"]:
        f = c["frame"]
        kinds.add(c["kind"])
        win = diff[max(0, f - 3):f + 2]
        assert win.max() > max(4.0, 3 * med), (c, win, med)          # visible change around the cut
        if c["kind"] == "cut":
            assert np.argmax(diff[f - 2:f + 1]) in (0, 1, 2), c        # the spike is the planned frame +-1
        elif c["kind"] == "flash":
            assert lum[f] > 200, (c, lum[f])
        elif c["kind"] == "leak":
            assert lum[f] > lum[f - 8] + 20, (c, lum[f], lum[f - 8])
    for c in rep["cuts"]:
        if c["kind"] == "whip":
            full = frame_at(str(stem) + ".clean.mp4", c["frame"] - 1)
            before = frame_at(str(stem) + ".clean.mp4", c["frame"] - 8)
            gx = lambda im: (np.diff(im.mean(2), axis=1) ** 2).mean()   # gradient ENERGY (blur kills it)
            assert gx(full) < 0.25 * gx(before) + 1e-3                  # horizontal motion blur
            assert rep["whip"]["peak_px_per_frame"] >= 300
    assert kinds - {"cut"}, "no styled transition rendered"


def test_transition_variety_and_budget(xhs, yt):
    allk = {c["kind"] for _, r in (xhs, yt) for c in r["cuts"]}
    assert {"whip", "flash", "leak", "zoom", "glitch"} <= allk, allk
    for _, r in (xhs, yt):
        hits = r["hits"]
        assert len(hits) <= 3
        ns = sorted(h["n"] for h in hits)
        assert all(b - a >= 16 for a, b in zip(ns, ns[1:]))
        assert all(c["kind"] in ("cut", "whip", "zoom", "flash", "leak", "glitch") for c in r["cuts"])
    _, rx = xhs
    assert any(c["reason"] == "drop" and c["kind"] == "zoom" for c in rx["cuts"])


@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_captions_inside_caption_box(which, request):
    stem, rep = request.getfixturevalue(which)
    assert rep["captions"], "speech shot produced no captions"
    x0, y0, x1, y1 = rep["caption_box"]
    for c in rep["captions"]:
        f = int(round((c["start"] + c["end"]) / 2 * FPS))
        a = frame_at(str(stem) + ".mp4", f)
        b = frame_at(str(stem) + ".clean.mp4", f)
        m = np.abs(a - b).max(2) > 40
        ys, xs = np.nonzero(m)
        assert len(xs) > 200, c
        assert xs.min() >= x0 - 2 and xs.max() <= x1 + 2 and ys.min() >= y0 - 2 and ys.max() <= y1 + 2, \
            (c, (xs.min(), ys.min(), xs.max(), ys.max()), rep["caption_box"])


@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_overlays_inside_safe_box(which, request):
    _, rep = request.getfixturevalue(which)
    sx0, sy0, sx1, sy1 = rep["safe_box"]
    kinds = set()
    for e in rep["elements"]:
        kinds.add(e["kind"])
        bx0, by0, bx1, by1 = e["box"]
        assert bx0 >= sx0 - 1 and by0 >= sy0 - 1 and bx1 <= sx1 + 1 and by1 <= sy1 + 1, (e, rep["safe_box"])
    assert {"title", "location", "end"} <= kinds


def test_xhs_graphics_present(xhs):
    _, rep = xhs
    kinds = {e["kind"] for e in rep["elements"]}
    assert {"title", "location", "day", "date", "word", "map", "end"} <= kinds
    shots = rep["shots"]
    assert any(s["kind"] == "photo" and s["src"].endswith(".heic") for s in shots)
    assert any(s["role"] == "hook" for s in shots) and any(s["role"] == "finale" for s in shots)


@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_sfx_peaks_at_cues(which, request):
    stem, rep = request.getfixturevalue(which)
    x, sr = A.read_wav(_wav(str(stem) + ".nomusic.mp4"), mono=True)
    env, hop = A.rms_envelope(x, sr, hop=0.005, win=0.01)
    speech = [(s["t0"], s["t1"]) for s in rep["shots"] if s["speech"]]
    checked = 0
    for c in rep["cue_sheet"]:
        t = c["t"]
        if any(t - 2.1 < b and a < t + 0.3 for a, b in speech) or c["sfx"] in ("riser",):
            continue
        i = int(t / hop)
        peak = env[max(0, i - 12):i + 12].max()
        base = np.percentile(env[max(0, i - 400):max(1, i - 100)], 20) if i > 120 else -120
        assert peak > -45 and peak > base + 15, (c, peak, base)
        checked += 1
    assert checked >= 3


def _wav(mp4):
    out = mp4 + ".test.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", mp4, "-ac", "1", "-ar", "48000", out], check=True)
    return out


@pytest.mark.parametrize("which", ["xhs", "yt"])
def test_speech_kept_whole_and_ducked(which, request, synth):
    stem, rep = request.getfixturevalue(which)
    import synth as S
    sp = [s for s in rep["shots"] if s["speech"]]
    assert len(sp) == 1
    w0, w1 = sp[0]["window"]
    needed = [(a, b) for a, b in S.SPEECH if b > w0 and a < w1]
    assert needed and all(w0 <= a - 0.03 and b + 0.03 <= w1 for a, b in needed), (sp[0]["window"], needed)
    # music measurably ducked under speech (music-in-mix vs the bed, speech vs elsewhere)
    assert rep["mix"]["duck_measured_db"] is not None and rep["mix"]["duck_measured_db"] < -6, rep["mix"]


def test_true_slowmo_from_120fps(xhs):
    stem, rep = xhs
    s = next(s for s in rep["shots"] if s["src"] == "slowmo.mp4" and s["role"] == "body")
    fr = grey_frames(str(stem) + ".clean.mp4")
    f0, f1 = int(round(s["t0"] * FPS)), int(round(s["t1"] * FPS))
    d = np.abs(np.diff(fr[f0 + 6:f1 - 6], axis=0)).mean(axis=(1, 2, 3))
    assert (d > 0.05).all(), d                       # every output frame is a new source frame
    w0, w1 = s["window"]
    assert abs((w1 - w0) - (s["t1"] - s["t0"]) * 0.25) < 0.05


def test_dry_run_and_help(synth):
    out = run(sys.executable, SCRIPTS / "build_fun.py", "--help")
    assert "--clean-master" in out and "--platform" in out
    cfg = dict(FUN_YT, out="dry.mp4", platform="douyin")
    p = synth / "work" / "dry.json"
    p.write_text(json.dumps(cfg))
    run(sys.executable, SCRIPTS / "build_fun.py", p, "--no-asr", "--dry-run")
    rep = json.loads((synth / "work" / "dry.report.json").read_text())
    assert rep["canvas"] == [1080, 1920] and rep["dry_run"]
    assert not (synth / "work" / "dry.mp4").exists()


# ------------------------------------------------------------------------------------------- calm
CALM = [
    {"src_dir": "../footage", "clips": {"s": "scenery.mp4", "p": "portrait.mp4", "m": "slowmo.mp4"},
     "res": [640, 360], "fps": 30, "xfade": 0.6, "fade_out": 1.0, "fit": "crop", "out": "calm_h.mp4",
     "segments": [{"clip": "s", "start": 1, "dur": 4, "kind": "empty"}, {"clip": "p", "start": 2, "dur": 3},
                  {"clip": "m", "start": 0, "dur": 2, "speed": 0.5}]},
    {"src_dir": "../footage", "clips": {"s": "scenery.mp4", "p": "portrait.mp4"},
     "res": [360, 640], "fps": 30, "xfade": 0.5, "fade_out": 1.0, "fit": "blur", "ambient_audio": True,
     "out": "calm_v.mp4",
     "segments": [{"clip": "p", "start": 1, "dur": 3, "speed": 0.5}, {"clip": "s", "start": 2, "dur": 5, "speed": 2.5}]},
]


def _head_build_vlog(tmp):
    """HEAD's build_vlog.py with its bootstrap pointed at this repo's lib (regression baseline)."""
    try:
        src = subprocess.run(["git", "-C", str(ROOT), "show", "HEAD:workflows/vlog/scripts/build_vlog.py"],
                             capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    lines = src.splitlines()
    lines = [f"import sys; sys.path.insert(0, {str(LIB)!r})" if ln.startswith("import sys, pathlib; sys.path.insert")
             else ln for ln in lines]
    p = tmp / "head_build_vlog.py"
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.mark.parametrize("k", [0, 1])
def test_calm_unchanged_vs_head(k, synth, tmp_path):
    head = _head_build_vlog(tmp_path)
    if head is None:
        pytest.skip("not a git checkout")
    work = synth / "work"
    cfg = dict(CALM[k])
    outs = {}
    for name, script in (("head", head), ("new", SCRIPTS / "build_vlog.py")):
        c = dict(cfg, out=f"{name}_{cfg['out']}")
        p = work / f"{name}_{k}.json"
        p.write_text(json.dumps(c))
        run(sys.executable, script, p)
        outs[name] = work / c["out"]
    fa, fb = grey_frames(outs["head"], 64), grey_frames(outs["new"], 64)
    assert fa.shape == fb.shape
    assert np.abs(fa - fb).max() < 1e-6
    ia, ib = probe(outs["head"]), probe(outs["new"])
    assert abs(ia["duration"] - ib["duration"]) < 1e-3 and ia["has_audio"] == ib["has_audio"]


def test_calm_platform_wiring(synth):
    work = synth / "work"
    cfg = dict(CALM[0], out="calm_yts.mp4", platform="youtube-shorts")
    cfg.pop("res")
    p = work / "calm_yts.json"
    p.write_text(json.dumps(cfg))
    out = run(sys.executable, SCRIPTS / "build_vlog.py", p)
    info = probe(work / "calm_yts.mp4")
    prof = P.profile("youtube-shorts")
    assert (info["w"], info["h"]) == (prof.w, prof.h)
    assert "youtube-shorts" in out
    # add_music --platform: loudness from the profile
    out = run(sys.executable, SCRIPTS / "add_music.py", work / "calm_yts.mp4", synth / "music" / "song.wav",
              work / "calm_yts_music.mp4", "--platform", "youtube-shorts")
    assert f"target={prof.loudness['lufs']} LUFS" in out
    m = A.measure_loudness(str(work / "calm_yts_music.mp4"))
    # the synthetic drum track is very peaky (crest ~20 dB): loudnorm's true-peak guard undershoots a little
    assert abs(m["input_i"] - prof.loudness["lufs"]) <= 2.5


def test_style_fun_dispatch_from_build_vlog(synth):
    cfg = dict(FUN_YT, out="dispatch.mp4")
    p = synth / "work" / "dispatch.json"
    p.write_text(json.dumps(cfg))
    out = run(sys.executable, SCRIPTS / "build_vlog.py", p, "--dry-run")
    assert "[fun]" in out
