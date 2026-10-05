"""The shared 气口 / filler / repeat tool (vstudio.cleanup) wired into vlog (fun + calm), photo-story and polish.
Synthetic tone-burst speech + a whisper-like transcript from tests/test_cleanup.py; no network, no real ASR.

    python3 -m pytest tests/test_speech_cleanup_wiring.py -q
"""
import json
import pathlib
import shutil
import subprocess
import sys
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "workflows" / "vlog" / "scripts"))
sys.path.insert(0, str(ROOT / "workflows" / "photo-story" / "scripts"))

import test_cleanup as TC  # noqa: E402
from vstudio import cleanup as CL  # noqa: E402
from vstudio import media  # noqa: E402

need_ff = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


@pytest.fixture(scope="module")
def talk(tmp_path_factory):
    """talk.mov (synthetic ZH speech with pauses, fillers, repeats) + talk.words.json."""
    d = tmp_path_factory.mktemp("spc")
    s = TC.synth(TC.ZH)
    mov = TC.make_media(d, s)
    (d / "talk.words.json").write_text(json.dumps(s["words"], ensure_ascii=False))
    return types.SimpleNamespace(dir=d, mov=mov, s=s, words=s["words"], dur=s["dur"])


# ------------------------------------------------------------------ vlog: knob
def test_vlog_options_resolution():
    from funvlog import speechclean as SPC
    assert SPC.options({}, {})["enabled"] and SPC.options({}, {})["profile"] == "gentle"
    assert not SPC.options({}, {}, default=False)["enabled"]
    assert SPC.options({"tighten": True}, {})["profile"] == "standard"            # legacy alias
    assert SPC.options({"cleanup": "tight"}, {"cleanup": False})["enabled"] is False
    o = SPC.options({"cleanup": {"profile": "standard", "approve": [1]}}, {"cleanup": {"keep": [2]}})
    assert o["profile"] == "standard" and o["approve"] is None and o["keep"] == [2]   # ids are per clip
    assert SPC.options({}, {"cleanup": "pauses"})["profile"] == "pauses"
    with pytest.raises(ValueError):
        SPC.options({}, {"cleanup": "brutal"})


# ------------------------------------------------------------------ vlog fun: pieces + captions
@need_ff
def test_fun_window_cleanup_auto_only_then_approve(talk, tmp_path):
    from funvlog import speechclean as SPC
    a, b = 0.3, talk.dur - 0.1
    warn = []
    o = SPC.options({}, {"cleanup": "standard"})
    pieces, log = SPC.clean_window(talk.mov, talk.words, a, b, o, str(tmp_path / "c"), warn)
    edl = json.loads(pathlib.Path(log["edl"]).read_text())
    assert pathlib.Path(log["review"]).exists()
    auto = [e["id"] for e in edl["edits"] if e["action"] == "auto"]
    assert sorted(log["applied"]) == sorted(auto) and auto                       # auto edits only
    assert log["kept_s"] < log["source_s"] - 0.5 and len(pieces) > 1
    assert pieces == [tuple(p) for p in CL.keep_segments(edl["edits"], edl["ranges"], words=edl["words"])]
    conf = [e["id"] for e in edl["edits"] if e["action"] == "confirm"]
    assert conf and set(log["confirm_pending"]) == set(conf)
    o2 = SPC.options({}, {"cleanup": {"profile": "standard", "reply": f"确认 {conf[0]} / 保留 {auto[0]}"}})
    p2, log2 = SPC.clean_window(talk.mov, talk.words, a, b, o2, str(tmp_path / "c"), warn)
    assert conf[0] in log2["applied"] and auto[0] not in log2["applied"]
    # 气口 only: no word edit is cut
    p3, log3 = SPC.clean_window(talk.mov, talk.words, a, b, SPC.options({}, {"cleanup": "pauses"}),
                                str(tmp_path / "c"), warn)
    kinds = {e["id"]: e["kind"] for e in json.loads(pathlib.Path(log3["edl"]).read_text())["edits"]}
    assert log3["applied"] and all(kinds[i] in SPC.PAUSE_KINDS for i in log3["applied"])
    assert not warn


def test_fun_captions_follow_cleanup_timemap():
    import build_fun
    from vstudio import platform as P
    words = [dict(w="大家", t=1.0, te=1.4), dict(w="嗯", t=1.6, te=1.9), dict(w="好", t=2.1, te=2.4)]
    shot = dict(speech=True, t0=10.0, t1=13.0, words=words, pieces=[(0.9, 1.5), (2.0, 2.6)])
    cues = build_fun.captions([shot], P.profile("douyin"))
    text = "".join(c.text for c in cues)
    assert "嗯" not in text and "大家" in text and "好" in text
    assert abs(cues[0].start - (10.0 + 0.1)) < 0.02                       # 1.0 - 0.9 into the shot
    tm = CL.timemap(shot["pieces"])
    hao = next(w for w in CL.remap_words(words, tm) if w["w"] == "好")
    assert abs(hao["t"] - (0.6 + 0.1)) < 0.02                              # second piece starts at 0.6


@need_ff
def test_fun_planner_logs_cleanup(talk):
    """A speech shot in the fun planner gets the gentle cleanup by default (logged in the report)."""
    from funvlog.plan import Planner
    pl = object.__new__(Planner)
    pl.cfg, pl.cache, pl.warn, pl.speech_log = {}, str(talk.dir), [], []
    pl.src_dir = pl.photo_dir = str(talk.dir)
    pl.map_slot = None
    pl.cfg.update(shots=[{"clip": "talk.mov", "speech": True, "start": 0.3, "dur": talk.dur - 0.5}])
    shots = pl.prepare()
    log = pl.speech_log[0]
    assert shots[0]["speech"] and log["cleanup"]["profile"] == "gentle"
    assert abs(sum(b - a for a, b in shots[0]["pieces"]) - log["cleanup"]["kept_s"]) < 1e-6
    pl.cfg["shots"][0]["cleanup"] = False
    pl.speech_log = []
    shots = pl.prepare()
    assert len(shots[0]["pieces"]) == 1 and "cleanup" not in pl.speech_log[0]


# ------------------------------------------------------------------ vlog calm
@need_ff
def test_calm_segment_cleaned_before_assembly(talk, tmp_path):
    import build_vlog
    cfg = dict(_src_dir=str(talk.dir), clips={"t": "talk.mov"}, ambient_audio=True,
               segments=[dict(clip="t", start=0.3, dur=talk.dur - 0.5, cleanup="standard"),
                         dict(clip="t", start=0.0, dur=2.0)])
    build_vlog.clean_speech(cfg, str(tmp_path))
    s0, s1 = cfg["segments"]
    assert s0["_src"].endswith(".mp4") and s0["start"] == 0.0 and s0["dur"] < talk.dur - 1.0
    assert abs(media.probe(s0["_src"])["duration"] - s0["dur"]) < 0.06
    assert "_src" not in s1 and s1["dur"] == 2.0                              # no speech, no knob: untouched
    cfg2 = dict(cfg, ambient_audio=False, segments=[dict(clip="t", start=0.3, dur=3.0, cleanup=True)])
    build_vlog.clean_speech(cfg2, str(tmp_path))                              # silent master: skipped
    assert "_src" not in cfg2["segments"][0]


# ------------------------------------------------------------------ photo-story
@need_ff
def test_photostory_opt_in_cleanup(talk, tmp_path):
    from photostory import speechclean as PSC
    C = types.SimpleNamespace(spec=types.SimpleNamespace(), cache_dir=str(tmp_path))
    sh = dict(src="vtalk", audio="keep", off=0.3)
    assert PSC.cleaned(C, sh, talk.mov) == (talk.mov, 0.3)                    # default: off
    C.spec.CLEANUP = "standard"
    assert PSC.cleaned(C, dict(sh, audio="duck"), talk.mov) == (talk.mov, 0.3)  # ambient clips: not cleaned
    path, off = PSC.cleaned(C, sh, talk.mov)
    assert off == 0.0 and path != talk.mov and media.probe(path)["duration"] < talk.dur - 1.0
    assert PSC.cleaned(C, sh, talk.mov) == (path, 0.0)                        # memoised
    assert PSC.cleaned(C, dict(sh, cleanup=False), talk.mov) == (talk.mov, 0.3)
    assert list((tmp_path / "cleanup").glob("*.review.md"))


# ------------------------------------------------------------------ polish
@need_ff
def test_polish_cleanup_optional_and_never_twice(talk, tmp_path):
    script = ROOT / "workflows" / "polish" / "scripts" / "polish.py"
    out = tmp_path / "final.mp4"
    common = ["--no-loudnorm", "--crf", "23", "--preset", "ultrafast"]
    r = subprocess.run([sys.executable, script, talk.mov, "-o", out, "--cleanup", "standard",
                        "--cleanup-transcript", str(talk.dir / "talk.words.json"), *common],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:] + r.stdout[-2000:]
    assert "cleanup (standard)" in r.stdout and (tmp_path / "final_review.md").exists()
    d = media.probe(str(out))["duration"]
    assert d < talk.dur - 1.0
    cleaned = next(p for p in tmp_path.glob("talk.clean.*.mp4"))
    # a cleaned file is never cut again
    r2 = subprocess.run([sys.executable, script, cleaned, "-o", tmp_path / "again.mp4", "--cleanup", "tight",
                         *common], capture_output=True, text=True)
    assert r2.returncode == 0 and "not cut again" in r2.stdout, r2.stdout[-2000:]
    assert abs(media.probe(str(tmp_path / "again.mp4"))["duration"] - media.probe(str(cleaned))["duration"]) < 0.05
    # ... nor through the original's EDL (cleanup.apply's duration guard)
    cp = tmp_path / "copy.mp4"
    shutil.copy(cleaned, cp)
    r3 = subprocess.run([sys.executable, script, cp, "-o", tmp_path / "x.mp4", "--cleanup", "standard",
                         "--cleanup-edl", str(tmp_path / "final.cleanup.json"), *common], capture_output=True, text=True)
    assert r3.returncode != 0 and "ORIGINAL" in (r3.stdout + r3.stderr)
    # default: no cleanup step at all
    r4 = subprocess.run([sys.executable, script, talk.mov, "-o", tmp_path / "plain.mp4", *common],
                        capture_output=True, text=True)
    assert r4.returncode == 0 and "0/4 cleanup" not in r4.stdout
    assert abs(media.probe(str(tmp_path / "plain.mp4"))["duration"] - media.probe(talk.mov)["duration"]) < 0.1


def test_fun_speech_shot_stretch_never_runs_into_next_sentence():
    """A (cleaned, so shorter) speech shot stretched to the beat grid grows up to the next sentence, then as a
    lead-in, never into other speech (regression: the stretch pulled in the next sentence's first words)."""
    from funvlog.plan import Planner
    pl = object.__new__(Planner)
    pl.fps, pl.period, pl.n0 = 30, 0.5, 0
    pl.bv = types.SimpleNamespace(beat_t=lambda n: 0.5 * n)
    s = dict(kind="video", speech=True, n0=0, nb=10, pieces=[(0.85, 2.0), (2.3, 4.45)], room=(0.3, 5.88))
    pl._windows([s])
    a, b = s["src_span"]
    assert b <= 5.88 + 1e-9 and a >= 0.3 - 1e-9
    assert abs(sum(y - x for x, y in s["pieces"]) - 5.0) < 1e-6          # 10 beats filled from the room
    s2 = dict(kind="video", speech=True, n0=0, nb=16, pieces=[(0.85, 4.45)], room=(0.3, 5.88))
    pl._windows([s2])
    assert s2["src_span"] == pytest.approx((0.3, 5.88))                                # rest: picture runs on, voice silent
