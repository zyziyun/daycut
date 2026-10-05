"""Regression tests for the call-clips demo-round fixes (2026-10), now on the shared vstudio.cleanup path:
word-safe editor-cut snap, cleanup profiles / reviewed EDL, hook
ends vs the hook->body dissolve, active-speaker smoothing, note-panel auto-fit, the stage trio layout
(privacy follows the tile), 9:16 covers, and the lib replacements of call-clips copies.
Synthetic media only (numpy tones, ffmpeg lavfi)."""
import json
import pathlib
import shutil
import subprocess
import sys
import wave

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "workflows" / "call-clips" / "scripts"
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(SCRIPTS))

from vstudio import cut as C  # noqa: E402
from vstudio import draw  # noqa: E402
from vstudio import platform as P  # noqa: E402

SR = 16000


def write_wav(path, spans, dur, dips=()):
    """Tone bursts at [(a, b)] seconds, silence elsewhere; dips = [(a, b)] forced silent inside."""
    t = np.arange(int(dur * SR)) / SR
    x = np.zeros_like(t)
    for a, b in spans:
        m = (t >= a) & (t < b)
        x[m] = 0.5 * np.sin(2 * np.pi * 220 * t[m])
    for a, b in dips:
        x[(t >= a) & (t < b)] = 0.0
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return str(path)


def segs_of(words):
    """One whisper segment holding [(text, s, e)] words."""
    return [{"start": words[0][1], "end": words[-1][2], "text": "".join(w[0] for w in words),
             "words": [{"word": w, "start": s, "end": e} for w, s, e in words]}]


# ------------------------------------------------------------------ 1. editor-cut snap (vstudio.cleanup path)
def test_classic_editor_cut_never_eats_previous_word(tmp_path):
    import cut_profiles
    # 他 很 笨 | 然 后 呢 | 你 就 ... ; 笨 has a stop-like 40 ms dip near its end (the quietest
    # frame within 0.15 s before the editor cut's start edge is INSIDE 笨: the old backward snap bug)
    words = [("他", 1.0, 1.2), ("很", 1.2, 1.4), ("笨", 1.4, 1.8),
             ("然", 1.8, 2.0), ("后", 2.0, 2.2), ("呢", 2.2, 2.4),
             ("你", 2.4, 2.6), ("就", 2.6, 2.8), ("练", 2.8, 3.4)]
    wav = write_wav(tmp_path / "a.wav", [(0.2, 0.6)] + [(s, e) for _, s, e in words] + [(4.0, 6.0)], 6.5,
                    dips=[(1.66, 1.70)])
    segs = segs_of(words)
    extra = [[1.8, 2.4, "filler: 然后呢"]]
    new = cut_profiles.find_cuts(wav, segs, 0.9, 3.5, extra, "classic")
    ed = [c for c in new if c[2].startswith("edit")]
    assert ed and ed[0][0] >= 1.8 - 1e-6, new          # starts at 笨's end, not inside it
    assert ed[0][1] <= 2.4 + 1e-6                       # never reaches into 你


def test_profile_aliases_map_to_cleanup_profiles():
    import cut_profiles
    from vstudio import cleanup
    assert cut_profiles.resolve("classic") == "gentle" and cut_profiles.resolve("word") == "standard"
    for p in cleanup.PROFILES:
        assert cut_profiles.resolve(p) == p


def test_window_cuts_are_cleanup_clean_cuts(tmp_path):
    """find_cuts == cleanup.clean(...)["cuts"] without editor cuts; the kept pieces drop the filler and squeeze
    the pause but every content word keeps its midpoint."""
    import cut_profiles
    from vstudio import cleanup
    words = [("我们", 1.0, 1.5), ("今天", 1.5, 2.0), ("嗯", 3.5, 3.8), ("讲", 4.6, 5.0), ("模型", 5.0, 5.6)]
    wav = write_wav(tmp_path / "w.wav", [(s, e) for _, s, e in words] + [(7.0, 8.0)], 8.5)
    segs = segs_of(words)
    for prof in ("classic", "word", "tight"):
        W = cleanup.load_words(segs)
        en = cleanup.energy_of(wav, W, [(0.9, 5.8)], cut_profiles.resolve(prof))
        ref = cleanup.clean(W, None, 0.9, 5.8, cut_profiles.resolve(prof), energy=en)["cuts"]
        assert cut_profiles.find_cuts(wav, segs, 0.9, 5.8, None, prof) == ref
    W = cleanup.load_words(segs)
    en = cut_profiles.energy(wav, W, None, "word")
    res = cut_profiles.window(W, en, 0.9, 5.8, None, "word")
    mids = lambda w: (w["t"] + w["te"]) / 2                                       # noqa: E731
    kept = lambda w: any(a <= mids(w) <= b for a, b in res["keep"])               # noqa: E731
    assert not kept(W[2])                                                          # 嗯 is gone
    assert all(kept(w) for k, w in enumerate(W) if k != 2)
    assert sum(b - a for a, b in res["keep"]) < 4.9 - 1.5


def test_reviewed_edl_decisions_drive_the_window(tmp_path):
    """find_disfluencies.py writes a cleanup EDL + review sheet; a creator's 保留 N keeps that edit."""
    import cut_profiles
    import find_disfluencies
    from vstudio import cleanup
    words = [("我们", 1.0, 1.5), ("今天", 1.5, 2.0), ("嗯", 3.5, 3.8), ("讲", 4.6, 5.0), ("模型", 5.0, 5.6)]
    wav = write_wav(tmp_path / "w.wav", [(s, e) for _, s, e in words] + [(7.0, 8.0)], 8.5)
    js = tmp_path / "w.json"
    js.write_text(json.dumps({"segments": segs_of(words)}, ensure_ascii=False))
    out = tmp_path / "work" / "cleanup.json"
    find_disfluencies.main([str(wav), str(js), "--windows", "0.9-5.8", "--out", str(out), "--profile", "word"])
    edl = json.loads(out.read_text())
    assert (tmp_path / "work" / "cleanup_review.md").exists()
    filler = next(e for e in edl["edits"] if e["kind"] == "filler")
    W = cleanup.load_words(edl["words"])
    dec = cleanup.parse_reply(f"保留 {filler['id']}")
    res = cut_profiles.window(W, None, 0.9, 5.8, None, "word", edits=edl["edits"], **dec)
    assert any(a <= 3.65 <= b for a, b in res["keep"])                            # 嗯 kept on request
    res2 = cut_profiles.window(W, None, 0.9, 5.8, None, "word", edits=edl["edits"])
    assert not any(a <= 3.65 <= b for a, b in res2["keep"])


# ------------------------------------------------------------------ 2. hook end vs dissolve (cleanup.extend_end)
def _hook_words(spec):
    from vstudio import cleanup
    return cleanup.load_words([(f"w{k}", s, e) for k, (s, e) in enumerate(spec)])


def test_hook_end_moves_past_the_sounding_tail(tmp_path):
    from vstudio import cleanup
    # the last hook word really sounds 1.0-1.6 s, whisper says it ends at 1.3; next word at 2.6
    wav = write_wav(tmp_path / "h.wav", [(0.2, 0.8), (1.0, 1.6), (2.6, 3.4), (4.0, 6.0)], 6.5)
    words = _hook_words([(0.2, 0.8), (1.0, 1.3), (2.6, 3.4)])
    en = cleanup.energy_of(wav, words)
    h1, fade, info = cleanup.extend_end(words, en, 0.2, 1.3, 0.5, 1.35)
    assert fade == 0.5 and info
    assert h1 >= 1.6 + 0.5 * 1.35 - 0.03                  # the whole fade lands in the silence
    assert h1 < 2.6                                        # and never reaches the next word


def test_hook_fade_shortened_when_the_gap_is_tight(tmp_path):
    from vstudio import cleanup
    wav = write_wav(tmp_path / "t.wav", [(0.2, 0.8), (1.0, 1.6), (1.9, 2.6), (3.0, 5.0)], 5.5)
    words = _hook_words([(0.2, 0.8), (1.0, 1.3), (1.9, 2.6)])
    en = cleanup.energy_of(wav, words)
    h1, fade, _ = cleanup.extend_end(words, en, 0.2, 1.3, 0.5, 1.35)
    assert 1.6 <= h1 <= 1.9 - 0.04
    assert 0.12 <= fade < 0.5
    assert h1 - fade * 1.35 >= 1.6 - 0.03                  # fade starts after the word's tail


def test_hook_end_already_in_silence_is_kept(tmp_path):
    from vstudio import cleanup
    wav = write_wav(tmp_path / "k.wav", [(0.2, 0.8), (1.0, 1.6), (3.0, 5.0)], 5.5)
    words = _hook_words([(0.2, 0.8), (1.0, 1.3), (3.0, 3.4)])
    en = cleanup.energy_of(wav, words)
    h1, fade, info = cleanup.extend_end(words, en, 0.2, 2.6, 0.5, 1.35)
    assert (h1, fade, info) == (2.6, 0.5, "")


# ------------------------------------------------------------------ 3. active speaker
def test_active_speaker_smoothing_ignores_short_words():
    import active_speaker as A
    raw = ["gA"] * 30 + ["host"] * 3 + ["gA"] * 20 + [None] * 5 + ["both" if False else None] * 2 \
        + ["gB"] * 30 + ["gA"] * 4 + ["gB"] * 25
    sm = A.smooth(raw, step=0.1, min_run=1.6)
    sw = A.switches(sm)
    assert [x for _, x in sw] == ["gA", "gB"]
    assert abs(sw[1][0] - 5.7) < 0.6                       # switches at the real turn, not later


def test_active_speaker_to_final_through_timemap():
    import active_speaker as A
    tm = C.TimeMap()
    tm.add_segment(10.0, 12.0, speed=1.0)
    tm.add_segment(20.0, 22.0, speed=1.0)
    times = [10 + 0.2 * k for k in range(70)]
    labels = ["gA" if t < 21 else "host" for t in times]
    raw = A.to_final(times, labels, tm, tm.duration, valid={"gA", "host"})
    assert raw[5] == "gA" and raw[-2] == "host"


# ------------------------------------------------------------------ 4. panels + stage layout
def test_fit_panel_fits_and_warns(capsys):
    import render_trio
    bullets = ["没人维护这个合成要点的一条很长很长的说明文字", "第二条", "第三条", "第四条"]
    im = render_trio.fit_panel("合成标题", bullets, 940, 300)
    assert im.shape[0] <= 300
    assert "WARN panel" in capsys.readouterr().out
    im = render_trio.fit_panel("合成标题", ["一条"], 940, 600)
    assert "WARN" not in capsys.readouterr().out


def test_stage_geometry_uses_the_canvas():
    import layout
    import render_trio
    prof = layout.resolve("xiaohongshu", "vertical")
    G = render_trio.stage_geometry(prof, [[["合成标题", False]]], "副标题", 16 / 9)
    sx0, sy0, sx1, sy1 = P.safe_box(prof)
    cx0, cy0, cx1, cy1 = P.caption_box(prof)
    bx, by, bw, bh = G["big"]
    assert bw == prof.w and by >= sy0
    for x, y, w, h in G["small"]:
        assert y == by + bh + render_trio.GAP and y + h == sy1     # down to the safe bottom
        assert h >= render_trio.MIN_SMALL
    p0, p1 = G["panel"]
    assert G["small"][0][1] < p0 < p1 <= cy0                       # panels above the captions
    assert not (p0 < by + bh and p1 > by)                          # never over the big (talking) tile


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_stage_preview_big_tile_follows_speaker_and_stays_masked(tmp_path):
    # 3-tile gallery: tile colours identify who is where; a pure-white "face" box per guest
    v = tmp_path / "c.mp4"
    fx = ("[0]drawbox=x=0:y=0:w=640:h=360:c=0x884422:t=fill,drawbox=x=320:y=360:w=640:h=360:c=0x228844:t=fill,"
          "drawbox=x=640:y=0:w=640:h=360:c=0x224488:t=fill,drawbox=x=280:y=120:w=80:h=100:c=white:t=fill,"
          "drawbox=x=600:y=480:w=80:h=100:c=white:t=fill[v]")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=0x101010:s=1280x720:r=25:d=3",
                    "-filter_complex", fx, "-map", "[v]", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(v)],
                   check=True)
    n = 75
    sticker = ROOT / "workflows" / "call-clips" / "assets" / "cat.png"
    for name, cx, cy in (("a", 320, 170), ("b", 640, 530)):
        json.dump({"cx": [cx] * n, "cy": [cy] * n, "w": [90] * n}, open(tmp_path / f"t{name}.json", "w"))
    json.dump([{"name": "gA", "region": "0,0,640,360", "sticker": str(sticker), "label": "A",
                "track": str(tmp_path / "ta.json")},
               {"name": "gB", "region": "320,360,640,360", "sticker": str(sticker), "label": "B",
                "track": str(tmp_path / "tb.json")}], open(tmp_path / "g.json", "w"))
    json.dump([], open(tmp_path / "s.json", "w"))
    json.dump({"title": [[["合成标题", False]]], "accent": ""}, open(tmp_path / "m.json", "w"))
    json.dump({"step": 0.1, "labels": ["gB"] * 15 + ["host"] * 15}, open(tmp_path / "spk.json", "w"))
    import cv2
    import layout
    import render_trio
    prof = layout.resolve("xiaohongshu", "vertical")
    G = render_trio.stage_geometry(prof, [[["合成标题", False]]], "", 16 / 9)
    bx, by, bw, bh = G["big"]
    for t, colour in ((0.6, (0x22, 0x88, 0x44)), (2.6, (0x22, 0x44, 0x88))):     # gB green, then host blue
        out = tmp_path / f"p{t}.jpg"
        subprocess.run([sys.executable, str(SCRIPTS / "render_trio.py"), str(v), "--guests-json",
                        str(tmp_path / "g.json"), "--subs", str(tmp_path / "s.json"), "--title-json",
                        str(tmp_path / "m.json"), "--host-region", "640,0,640,360", "--platform", "xiaohongshu",
                        "--speakers", str(tmp_path / "spk.json"), "--preview", str(t), "--out", str(out)],
                       check=True, capture_output=True)
        im = cv2.imread(str(out))[:, :, ::-1].astype(int)
        corner = im[by + 30:by + 60, bx + bw - 60:bx + bw - 30].reshape(-1, 3).mean(0)
        assert np.abs(corner - colour).max() < 30, (t, corner)
        white = (im.min(axis=2) > 235)
        # no uncovered white "face" (>= 5,000 px once scaled) anywhere in the tiles; chip text and the
        # sticker's own highlights stay far below that (title text is above the big tile)
        assert white[by:].sum() < 3000, (t, white[by:].sum())


# ------------------------------------------------------------------ 5. covers + lib replacements
def test_cover_canvas_size_is_9x16():
    import importlib.util
    import layout
    # load by path: the vlog workflow also has a top-level ``make_cover`` module (sys.modules clash)
    spec = importlib.util.spec_from_file_location("callclips_make_cover", SCRIPTS / "make_cover.py")
    mc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mc)
    cover_geometry = mc.cover_geometry
    prof = layout.resolve("xiaohongshu:full", "vertical")
    W, H, safe = cover_geometry(prof, canvas=True)
    assert (W, H) == (1080, 1920) and safe == tuple(P.safe_box(prof))
    assert cover_geometry(prof)[:2] == P.cover_size(prof)


def _old_mask_names(frame, rects, mode="blur"):
    import cv2
    H, W = frame.shape[:2]
    for x, y, w, h in rects:
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        reg = frame[y0:y1, x0:x1]
        if mode == "cover":
            reg[:] = np.median(reg.reshape(-1, 3), axis=0).astype(np.uint8)
        else:
            small = cv2.resize(reg, (max(1, (x1 - x0) // 16), max(1, (y1 - y0) // 16)), interpolation=cv2.INTER_AREA)
            reg[:] = cv2.GaussianBlur(cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR), (0, 0), 3)
    return frame


def test_mask_names_is_lib_redact_rects_pixel_identical():
    pytest.importorskip("cv2")
    import layout
    rng = np.random.default_rng(1)
    rects = [(0, 324, 256, 36), (600, 300, 100, 100), (-5, -5, 30, 30), (10, 10, 3, 3)]
    for mode in ("blur", "cover"):
        f = rng.integers(0, 255, (360, 640, 3), dtype=np.uint8)
        assert (layout.mask_names(f.copy(), rects, mode) == _old_mask_names(f.copy(), rects, mode)).all()
        assert (draw.redact_rects(f.copy(), rects, mode) == _old_mask_names(f.copy(), rects, mode)).all()
