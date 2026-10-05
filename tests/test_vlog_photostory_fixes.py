"""Demo-round fixes for the vlog (fun style + cover) and photo-story workflows. Synthetic media only.

    python3 -m pytest tests/test_vlog_photostory_fixes.py -q

vlog: speech gating (hallucinated / music-only ASR rejected, real speech kept, decision logged),
      cross-kind tag/stamp collisions, MapCard never drops a label, explicit / photo hook-finale-outro,
      A5 leak cap (no leak after every photo), keep_audio accents, lib Beats.shift / audio.limit equivalence,
      make_cover face focus + exact size default.
photo-story: cjk-serif fallback is loud, POST tag args, per-shot minimum units in music mode (no 1-bar
      collage), rotation-aware clip size, duck_curve = lib.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import types

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "workflows" / "vlog" / "scripts"))
sys.path.insert(0, str(ROOT / "workflows" / "vlog" / "tests"))
sys.path.insert(0, str(ROOT / "workflows" / "photo-story" / "scripts"))

from vstudio import audio as A  # noqa: E402
from vstudio import beats as BT  # noqa: E402
from vstudio import platform as P  # noqa: E402

HAS_FF = bool(shutil.which("ffmpeg"))
need_ff = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *map(str, args)], check=True)


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory):
    """talk.mp4 (syllabic tone bursts = speech), music.mp4 (continuous drum loop audio), song.wav, photos."""
    import synth as S
    d = tmp_path_factory.mktemp("fix")
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28", "-pix_fmt", "yuv420p"]
    S.write_wav(str(d / "speech.wav"), S.speech_track())
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=12", "-i", d / "speech.wav", *enc, "-c:a", "aac",
       "-shortest", d / "talk.mp4")
    song, _ = S.drum_track(dur=40.0, quiet_until=0.0)
    S.write_wav(str(d / "song.wav"), song)
    ff("-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=10", "-ss", "2", "-i", d / "song.wav", *enc, "-c:a", "aac",
       "-shortest", d / "music.mp4")
    from PIL import Image, ImageDraw
    for k in range(4):
        im = Image.new("RGB", (1200, 900), (40 + 50 * k, 90, 160))
        ImageDraw.Draw(im).ellipse([400, 250, 800, 650], fill=(240, 200, 60))
        im.save(d / f"p{k}.jpg", quality=90)
    return d


# =================================================================================== vlog: speech
def _fake_tr(segs):
    return dict(language="zh", backend="fake", segments=segs, text="".join(s["text"] for s in segs),
                words=[dict(w=w["word"].strip(), t=w["start"], te=w["end"]) for s in segs for w in s["words"]])


def _seg(text, a, b, n):
    ts = np.linspace(a, b, n + 1)
    return dict(start=a, end=b, text=text, words=[dict(word=text[k % len(text)] if len(text) >= n else f"w{k}",
                                                       start=float(ts[k]), end=float(ts[k + 1])) for k in range(n)])


@need_ff
def test_speech_gate_rejects_hallucinations_keeps_speech(media_dir, monkeypatch):
    import synth as S
    from vstudio import asr
    from funvlog import plan as PL
    real = _fake_tr([dict(start=a, end=b, text=w, words=[dict(word=" " + w, start=a, end=b)]) for w, a, b in S.WORDS])
    fakes = {
        "music.mp4": _fake_tr([_seg("字幕志愿者 某某某", 0.0, 9.5, 8)]),            # stock credit over music
        "talk.mp4": real,
    }
    monkeypatch.setattr(asr, "transcribe", lambda src, **k: json.loads(json.dumps(fakes[pathlib.Path(src).name])))
    warn = []
    for name, want in (("music.mp4", False), ("talk.mp4", True)):
        log = {}
        words, sents, how = PL.load_speech(str(media_dir / name), {}, {}, warn, log)
        assert bool(words) == want, (name, log)
        assert log["source"] == "asr" and log["reason"]
    # words placed where the clip is silent (whisper's end-of-clip loop) fail the loudness check
    fakes["talk.mp4"] = _fake_tr([_seg("我看你我看你我看你", 10.2, 11.8, 9)])
    log = {}
    words, _, how = PL.load_speech(str(media_dir / "talk.mp4"), {}, {}, warn, log)
    assert words is None and how == "asr-rejected" and log["overlap"] < 0.5
    assert any("rejected" in w for w in warn)


@need_ff
def test_speech_auto_decision_logged_in_plan(media_dir, monkeypatch):
    import synth as S
    from vstudio import asr
    from funvlog.plan import Planner, music_origin
    real = _fake_tr([dict(start=a, end=b, text=w, words=[dict(word=" " + w, start=a, end=b)]) for w, a, b in S.WORDS])
    monkeypatch.setattr(asr, "transcribe", lambda src, **k: json.loads(json.dumps(
        real if src.endswith("talk.mp4") else _fake_tr([_seg("请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", 0.0, 9.0, 12)]))))
    b = BT.analyze(str(media_dir / "song.wav"))
    m0 = music_origin(b)
    cfg = dict(src_dir=str(media_dir), music="song.wav", hook=False, finale=False, outro=False, _m0=m0,
               shots=[{"clip": "music.mp4", "speech": "auto"}, {"clip": "talk.mp4", "speech": "auto"}])
    pl = Planner(cfg, str(media_dir), P.profile("douyin"), b.shift(-m0), 30, str(media_dir), [])
    shots = pl.prepare()
    assert [s["speech"] for s in shots] == [False, True]
    log = {x["clip"]: x for x in pl.speech_log}
    assert log["music.mp4"]["speech"] is False and log["music.mp4"]["captions"] is False
    assert log["talk.mp4"]["speech"] is True and log["talk.mp4"]["captions"] is True


# =================================================================================== vlog: layout
def _geom(platform="douyin"):
    from funvlog import gfx as G
    prof = P.profile(platform)
    return G, G.Geometry(prof, P.safe_box(prof), P.caption_box(prof))


def test_day_stamp_and_location_tag_never_overlap():
    G, g = _geom()
    tag = G.LocationTag(g, "Hollywood Studios Galaxy's Edge", 1.12)
    day = G.DayStamp(g, "DAY 2 · 6.22", 1.10)
    date = G.DateStamp(g, "2026.06.22 09:12", 1.0, 4.0)

    def hit(a, b):
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
    assert hit(tag.box, day.box), "fixture should collide before resolution"
    moves = G.resolve_collisions([day, tag, date], g)
    assert moves and not hit(tag.box, day.box) and not hit(day.box, date.box) and not hit(tag.box, date.box)
    sx0, sy0, sx1, sy1 = g.safe
    for e in (tag, day, date):
        assert e.box[0] >= sx0 - 1 and e.box[1] >= sy0 - 1 and e.box[2] <= sx1 + 1 and e.box[3] <= sy1 + 1
    # the drawn pixels follow the moved box
    img = np.zeros((g.H, g.W, 3), np.uint8)
    day.draw(img, day.t0 + 0.5)
    ys = np.nonzero(img.max(2) > 30)[0]
    assert ys.min() >= day.box[1] - 4 and ys.max() <= day.box[3] + 4


def test_map_card_places_every_label_without_overlap():
    G, g = _geom()
    places = [{"name": "Animal Kingdom", "xy": [0.3, 0.9]}, {"name": "Hollywood Studios", "xy": [0.42, 0.88]},
              {"name": "Magic Kingdom", "xy": [0.36, 0.86]}, {"name": "Epcot", "xy": [0.5, 0.5]}]
    m = G.MapCard(g, places, 0.0, 3.0)
    labs = m.info()["labels"]
    assert [x["name"] for x in labs] == [p["name"] for p in places]
    bx = [x["box"] for x in labs]
    for i in range(len(bx)):
        a = bx[i]
        assert a[0] >= 0 and a[1] >= 0 and a[2] <= m.cw and a[3] <= m.ch
        for b in bx[i + 1:]:
            assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]), (a, b)
    # the last pin + label hold >= 1 s before the card starts leaving (A1)
    assert (m.t1 - 0.25) - (m.t0 + m.draw_to) >= 1.0 - 1e-6


# =================================================================================== vlog: transitions
def _bare_planner(cfg=None):
    from funvlog.plan import Planner
    pl = object.__new__(Planner)
    pl.cfg, pl.fps = dict(cfg or {}), 30
    return pl


def test_photos_do_not_get_a_leak_each():
    pl = _bare_planner()
    tl, n, f = [], 0, 0
    kinds = ["video"] + ["photo"] * 12 + ["video", "photo", "video", "photo", "video", "photo"] * 3
    for k, kind in enumerate(kinds):
        tl.append(dict(role="body", kind=kind, n0=n, nb=2, t0=n * 0.5, f0=f, f1=f + 30))
        n, f = n + 2, f + 30
    tl.append(dict(role="outro", kind="video", n0=n, nb=8, t0=n * 0.5, f0=f, f1=f + 120))
    cuts = pl._transitions(tl, dict(drops_used=[]))
    kinds_out = [c["kind"] for c in cuts]
    leaks = [c for c in cuts if c["kind"] == "leak"]
    assert kinds_out[-1] == "leak" and cuts[-1]["reason"] == "outro"
    assert len(leaks) <= 4
    auto = sorted(c["n"] for c in leaks if c["reason"] != "outro")
    assert all(b - a >= 16 for a, b in zip(auto, auto[1:]))
    assert not any(a == b == "leak" for a, b in zip(kinds_out, kinds_out[1:]))
    assert sum(k == "cut" for k in kinds_out) > len(kinds_out) / 2       # hard cut by default (A5)


@need_ff
def test_explicit_and_photo_hook_finale_outro(media_dir):
    from funvlog.plan import Planner, music_origin
    b = BT.analyze(str(media_dir / "song.wav"))
    m0 = music_origin(b)
    cfg = dict(src_dir=str(media_dir), music="song.wav", _m0=m0,
               hook=["p0.jpg", {"photo": "p1.jpg"}, {"clip": "music.mp4", "start": 1.0}],
               finale=["p2.jpg", "p3.jpg"], outro={"photo": "p0.jpg", "beats": 8},
               shots=[{"photo": "p1.jpg"}, {"clip": "music.mp4"}, {"photo": "p2.jpg"}])
    pl = Planner(cfg, str(media_dir), P.profile("douyin"), b.shift(-m0), 30, str(media_dir), [])
    tl, cuts, meta = pl.plan()
    hook = [s for s in tl if s["role"] == "hook"]
    fin = [s for s in tl if s["role"] == "finale"]
    out = [s for s in tl if s["role"] == "outro"]
    assert [s["kind"] for s in hook] == ["photo", "photo", "video"] and hook[2]["start"] == 1.0
    assert [s["kind"] for s in fin] == ["photo", "photo"] and all(s.get("style") == "full" for s in fin)
    assert len(out) == 1 and out[0]["kind"] == "photo" and out[0]["nb"] == 8
    # photos-only trip: the auto hook / finale fall back to photos (Ken Burns)
    cfg2 = dict(src_dir=str(media_dir), music="song.wav", _m0=m0, outro=False,
                shots=[{"photo": f"p{k}.jpg"} for k in range(4)])
    pl2 = Planner(cfg2, str(media_dir), P.profile("douyin"), b.shift(-m0), 30, str(media_dir), [])
    tl2, _, _ = pl2.plan()
    assert sum(s["role"] == "hook" for s in tl2) >= 3 and all(s["kind"] == "photo" for s in tl2 if s["role"] == "hook")


# =================================================================================== vlog: audio
@need_ff
def test_keep_audio_accents(media_dir):
    import build_fun as BF
    from funvlog import mix as MX
    tl = [dict(role="body", kind="video", src=str(media_dir / "music.mp4"), keep_audio=True, ramp_keys=[[0, 1.0], [1, 1.0]],
               src_span=(1.0, 3.0), t0=0.5),
          dict(role="body", kind="video", src=str(media_dir / "music.mp4"), keep_audio=-12, ramp_keys=[[0, 0.5], [1, 2.0]],
               src_span=(3.0, 5.0), t0=3.0),
          dict(role="body", kind="video", src=str(media_dir / "talk.mp4"), speech=True, t0=6.0)]
    warn = []
    acc = BF.accent_pieces({}, tl, warn)
    assert len(acc) == 1 and acc[0]["gain_db"] == -8.0 and any("ramped" in w for w in warn)
    x = MX.voice_stem(acc, 4.0, fade=0.03, level=-24.0)
    i0, i1 = int(0.6 * A.SR), int(2.4 * A.SR)
    assert np.abs(x[:int(0.45 * A.SR)]).max() == 0 and np.abs(x[i0:i1]).max() > 0
    assert abs(A.integrated_lufs(x[i0:i1]) - (-32.0)) < 1.5               # -24 + gain -8


def test_lib_shift_and_limit_replace_local_workarounds():
    import synth as S
    import funvlog.mix as MX
    import funvlog.plan as PL
    assert not hasattr(PL, "shift_beats") and not hasattr(MX, "limit")
    x, _ = S.drum_track(dur=20.0)
    y = np.stack([x, x], 1) * 3.0
    z = A.limit(y, -3.5)
    assert 20 * np.log10(A.true_peak(z).max()) <= -3.5 + 0.05
    q = y * 0.05
    assert np.allclose(A.limit(q, -3.5), q)


@need_ff
def test_beats_shift_matches_music_to_video_time(media_dir):
    b = BT.analyze(str(media_dir / "song.wav"))
    v = b.shift(-1.25)
    for n in (0, 7, 40):
        assert abs(float(v.beat_t(n)) - (float(b.beat_t(n)) - 1.25)) < 1e-9
    assert v.downbeat_phase == b.downbeat_phase


# =================================================================================== vlog: cover
def test_make_cover_face_focus_and_defaults(tmp_path, monkeypatch):
    import importlib.util
    # load by path: call-clips also has a top-level ``make_cover`` module (sys.modules / sys.path clash)
    spec = importlib.util.spec_from_file_location("vlog_make_cover", ROOT / "workflows" / "vlog" / "scripts" / "make_cover.py")
    MC = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(MC)
    from PIL import Image
    p = tmp_path / "flat.jpg"
    Image.new("RGB", (800, 600), (90, 120, 160)).save(p)
    assert MC.face_focus(str(p)) is None                                   # no face -> keep the default
    monkeypatch.setattr(MC, "face_focus", lambda path: "22% 31%" if path.endswith("hero.jpg") else None)
    pieces = MC.auto_pieces(["a.jpg", "b.jpg"], "hero.jpg", 1080, 1440)
    assert pieces[-1]["bgpos"] == "22% 31%" and pieces[-1]["focus"] == "face"
    assert pieces[0]["focus"] == "default"
    off = MC.auto_pieces(["a.jpg"], "hero.jpg", 1080, 1440, faces=False)
    assert off[-1]["bgpos"] == "48% 58%"
    src = (ROOT / "workflows" / "vlog" / "scripts" / "make_cover.py").read_text()
    assert 'add_argument("--scale", type=int, default=1' in src


# =================================================================================== photo-story
def test_cjk_serif_fallback_is_loud(monkeypatch, capsys):
    from photostory import ctx
    from vstudio.config import MissingAsset

    def fake(role):
        if role in ("cjk-serif", "cjk-serif-bold"):
            raise MissingAsset(role)
        return f"/fonts/{role}.otf"
    monkeypatch.setattr(ctx, "vfont", fake)
    ctx._font_path.cache_clear()
    try:
        assert ctx._font_path("cjk-serif") == "/fonts/cjk-bold.otf"
        err = capsys.readouterr().err
        assert "cjk-serif" in err and "serif" in err and "install.sh" in err
    finally:
        ctx._font_path.cache_clear()


def test_post_tag_args_pass_through(monkeypatch, capsys):
    from photostory import export as EX
    from vstudio import publish
    assert EX.tag_args(dict(use_persona_tags=False, tag_set="art")) == dict(use_persona_tags=False, tag_set="art")
    txt = publish.post_body(None, "body", tags=["#art"], platform="xiaohongshu",
                            **EX.tag_args(dict(use_persona_tags=False)), warn=None)
    assert txt.strip().endswith("#art")
    monkeypatch.setattr(publish, "post_body", lambda hook, body, chapters=None, tags=None, platform=None, title=None: "")
    assert EX.tag_args(dict(use_persona_tags=False)) == {}
    assert "use_persona_tags" in capsys.readouterr().out


def test_allot_min_never_below_minimums():
    from photostory.music import allot, allot_min
    rng = np.random.default_rng(0)
    for _ in range(500):
        n = int(rng.integers(1, 7))
        w = list(rng.uniform(0.3, 3.0, n))
        m = list(rng.integers(1, 4, n))
        T = int(rng.integers(1, 30))
        o = allot_min(w, T, m)
        assert sum(o) == max(T, sum(m)) and all(a >= b for a, b in zip(o, m))
        if all(v == 1 for v in m):
            assert o == allot(w, T)                                         # unchanged when nothing is pinned


@need_ff
def test_music_mode_late_chapter_not_squeezed(media_dir, monkeypatch, capsys):
    from photostory import music as MU
    b = BT.analyze(str(media_dir / "song.wav"))
    monkeypatch.setattr(MU, "analyze", lambda C: b)
    script = [
        (0, [("a", "甲")], [("p0", 1, "in", {}), ("p1", 1, "still", {}), ("p2", 1, "still", {})]),
        (1, [("b", "乙")], [("p3", 1, "in", {}), ("p0", 1, "still", {}), ("p1", 1, "still", {})]),
        (2, [("c", "丙")], [("collage:p0,p1,p2", 1, "still", {}), ("film:p1,p2,p3", 1, "still", {})]),
    ]
    spec = types.SimpleNamespace(MUSIC=dict(grid="bar", length=12.0), SCRIPT=script, PACING={})
    C = types.SimpleNamespace(spec=spec, SECTIONS=["一", "二", "三"])
    T = MU.MusicTimeline(C)
    unit = 4 * b.period
    late = [s for s in T.shots if s["sec"] == 2]
    assert late[0]["units"] * unit >= 2.5 - 1e-6 and late[1]["units"] * unit >= 3.0 - 1e-6
    out = capsys.readouterr().out
    assert "too short for the minimum shot times" in out and "MUSIC length=" in out
    # cuts still on the bar grid
    assert T.verify(30)["ok"]


@need_ff
def test_clip_size_is_display_frame(tmp_path):
    from photostory.shots import ffprobe_size
    src = tmp_path / "land.mp4"
    ff("-f", "lavfi", "-i", "testsrc=s=320x180:r=30:d=1", "-c:v", "libx264", "-preset", "ultrafast", src)
    rot = tmp_path / "rot.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-display_rotation", "90", "-i", str(src), "-c", "copy",
                        str(rot)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("ffmpeg without -display_rotation")
    assert ffprobe_size(str(src)) == (320, 180)
    assert ffprobe_size(str(rot)) == (180, 320)


def test_photostory_duck_curve_is_lib():
    from photostory.audiomix import duck_curve
    n = A.SR * 3
    t = np.arange(n) / A.SR
    x = np.zeros((n, 2), np.float32)
    m = (t > 1) & (t < 2)
    x[m] = 0.3 * np.sin(2 * np.pi * 220 * t[m])[:, None]
    assert np.allclose(duck_curve(x, -10, n), A.duck_curve(x, -10, n, threshold_db=-42.0))
    assert np.all(duck_curve(None, -10, n) == 1)
