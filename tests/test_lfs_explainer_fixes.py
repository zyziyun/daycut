"""Demo-round fixes for workflows/longform-to-short and workflows/explainer (synthetic media only).

    python3 -m pytest tests/test_lfs_explainer_fixes.py -q
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LFS = ROOT / "workflows" / "longform-to-short" / "scripts"
EXP = ROOT / "workflows" / "explainer" / "scripts"
sys.path.insert(0, str(ROOT / "lib"))

HAS_FF = bool(shutil.which("ffmpeg"))
need_ff = pytest.mark.skipif(not HAS_FF, reason="ffmpeg not installed")


def _import(dirpath, name):
    sys.path.insert(0, str(dirpath))
    try:
        import importlib
        return importlib.import_module(name)
    finally:
        sys.path.pop(0)


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def _probe_stream(path, sel):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", sel, "-count_packets",
                          "-show_entries", "stream=duration,nb_read_packets,sample_rate",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"][0]


# ------------------------------------------------------------------ longform-to-short: render A/V exactness
@need_ff
def test_render_audio_matches_video_over_many_segments(tmp_path):
    """30 short items (clips at 1.2x, a card, a freeze, a pitch window): the joined audio must equal the video
    length within one frame (the old per-segment AAC + stream-copy concat drifted ~20-40 ms per join)."""
    work = tmp_path / "work"
    (work / "cards").mkdir(parents=True)
    src = tmp_path / "src.mp4"
    _ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=24", "-f", "lavfi", "-i", "sine=f=330:r=44100:d=24",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(src))
    from PIL import Image
    Image.new("RGB", (640, 360), (10, 10, 12)).save(work / "cards" / "card_01.png")
    rng = np.random.default_rng(3)
    tl, t, cur = [], 0.5, 0.0
    for k in range(30):
        if k == 10:
            tl.append({"kind": "card", "png": "cards/card_01.png", "dur": 0.53, "title": "c"})
            continue
        d = float(rng.uniform(0.31, 0.47))
        it = {"kind": "clip", "t0": round(t, 2), "t1": round(t + d, 2), "speed": 1.2, "crop": [600, 340, 20, 10],
              "demo_slice": None, "overlay": None, "cont_in": k % 3 != 0, "cont_out": k % 3 != 2}
        if k == 15:
            it.update(kind="freeze", still_at=t)
        if k == 20:
            it["pitch"] = 2 ** (-3 / 12)
        tl.append(it)
        t += d + 0.07
    for it in tl:
        it["final_t0"] = round(cur, 3)
        cur += it["dur"] if it["kind"] == "card" else (it["t1"] - it["t0"]) / it["speed"]
    (work / "timeline.json").write_text(json.dumps(tl))
    cfg = {"src": str(src), "out": str(tmp_path / "out"), "render": {"size": [640, 360], "fit": [600, 340], "fps": 24}}
    (work / "config.json").write_text(json.dumps(cfg))
    subprocess.run([sys.executable, str(LFS / "render.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    final = tmp_path / "out" / "final.mp4"
    v = _probe_stream(final, "v:0")
    a = _probe_stream(final, "a:0")
    vdur = int(v["nb_read_packets"]) / 24.0
    adur = float(a["duration"])
    assert abs(vdur - cur) <= 1 / 24 + 1e-6, (vdur, cur)
    assert abs(adur - vdur) < 1 / 24, (adur, vdur)
    # the PCM join itself is sample-exact
    import wave
    with wave.open(str(work / "joined.wav")) as w:
        assert w.getnframes() == round(round(cur * 24) * 48000 / 24)


def test_segment_grid_sums_to_timeline():
    L = _import(LFS, "_lfc")
    tl = [{"kind": "card", "dur": 1.6, "final_t0": 0.0}] + [
        {"kind": "clip", "t0": 0, "t1": 0.333, "speed": 1.2, "final_t0": round(1.6 + k * 0.2775, 3)} for k in range(200)]
    g = L.segment_grid(tl, 24)
    assert sum(f for f, _ in g) == round(L.total_duration(tl) * 24)
    assert sum(s for _, s in g) == sum(f for f, _ in g) * 2000


# ------------------------------------------------------------------ longform-to-short: captions at splits
def test_build_subs_keeps_words_straddling_a_zoom_split(tmp_path):
    """A zoom split at 2.05 s cuts through "面试" (1.9-2.2): it must appear whole in one piece, not as "试"."""
    work = tmp_path / "work"
    work.mkdir()
    words = [("我们", 1.0, 1.4), ("准备", 1.4, 1.9), ("面试", 1.9, 2.2), ("的时候", 2.2, 2.8), ("要讲", 2.8, 3.3)]
    asr = {"segments": [{"start": 1.0, "end": 3.3, "text": "".join(w for w, _, _ in words),
                         "words": [{"word": w, "start": a, "end": b} for w, a, b in words]}]}
    (work / "audio16k.json").write_text(json.dumps(asr, ensure_ascii=False))
    tl = [{"kind": "clip", "t0": 0.8, "t1": 2.05, "speed": 1.0, "final_t0": 0.0},
          {"kind": "clip", "t0": 2.05, "t1": 3.6, "speed": 1.0, "final_t0": 1.25}]
    (work / "timeline.json").write_text(json.dumps(tl))
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out")}))
    subprocess.run([sys.executable, str(LFS / "build_subs.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    cues = json.loads((work / "cues.json").read_text(encoding="utf-8"))
    text = "".join(c["text"] for c in cues)
    assert text.count("面试") == 1 and text.replace("面试", "").count("试") == 0
    assert text == "我们准备面试的时候要讲"


def _run_build_subs(tmp_path, segments, tl):
    work = tmp_path / "work"
    work.mkdir()
    (work / "audio16k.json").write_text(json.dumps({"segments": segments}, ensure_ascii=False))
    (work / "timeline.json").write_text(json.dumps(tl))
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out")}))
    subprocess.run([sys.executable, str(LFS / "build_subs.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    return json.loads((work / "cues.json").read_text(encoding="utf-8"))


def test_build_subs_splits_long_english_segment_on_word_boundaries(tmp_path):
    """A long English segment used to be cut every n characters ("...the database anywa" / "y."): every
    piece must hold whole words and the pieces must read back as the segment."""
    said = (" And then this filter hits the database anyway, because the cache was never warmed up. If the"
            " account was deleted we just skip it and move on to the next one in the queue, which is fine.")
    cues = _run_build_subs(tmp_path, [{"start": 0.0, "end": 12.0, "text": said}],
                           [{"kind": "clip", "t0": 0.0, "t1": 12.0, "speed": 1.0, "final_t0": 0.0}])
    assert len(cues) >= 2
    words = set(said.split())
    for c in cues:
        assert c["text"] == c["text"].strip() and set(c["text"].split()) <= words, c["text"]
    assert " ".join(c["text"] for c in cues) == said.strip()


def test_build_subs_mixed_text_keeps_latin_words_and_cjk_by_character(tmp_path):
    from vstudio.subs import text_width
    mixed = "我们今天用ClaudeCode来做一个很长的视频剪辑流程演示然后把filter和database都讲清楚再看看cache怎么warmup最后把这些都串起来"
    zh = "我们今天来做一个很长很长的视频剪辑流程演示然后把每一个步骤都讲清楚再看看缓存怎么预热最后把这些都串起来给大家看"
    cues = _run_build_subs(tmp_path, [{"start": 0.0, "end": 8.0, "text": mixed}, {"start": 9.0, "end": 17.0, "text": zh}],
                           [{"kind": "clip", "t0": 0.0, "t1": 17.0, "speed": 1.0, "final_t0": 0.0}])
    m = [c["text"] for c in cues if c["start"] < 8.5]
    assert len(m) >= 2 and "".join(m) == mixed and all(text_width(t) <= 44 for t in m)
    for latin in ("ClaudeCode", "filter", "database", "cache", "warmup"):
        assert any(latin in t for t in m), latin
    z = [c["text"] for c in cues if c["start"] >= 8.5]
    # CJK: split by character into the same two-line chunks the burn-in shows (subs.caption_chunks, 2 x 22)
    assert len(z) >= 2 and "".join(z) == zh and all(len(t) <= 44 for t in z)


def test_build_subs_short_english_piece_keeps_its_space(tmp_path):
    """A word left alone between two cuts joins the caption next to it with a space (the database)."""
    words = [(" So", 0.0, 0.3), (" we", 0.3, 0.6), (" query", 0.6, 1.0), (" the", 1.0, 1.2), (" database", 1.2, 1.9),
             (" again.", 1.9, 2.4)]
    seg = {"start": 0.0, "end": 2.4, "text": "".join(w for w, _, _ in words),
           "words": [{"word": w, "start": a, "end": b} for w, a, b in words]}
    cues = _run_build_subs(tmp_path, [seg], [{"kind": "clip", "t0": 0.0, "t1": 1.1, "speed": 1.0, "final_t0": 0.0},
                                             {"kind": "clip", "t0": 1.1, "t1": 1.25, "speed": 1.0, "final_t0": 1.1},
                                             {"kind": "clip", "t0": 1.25, "t1": 2.4, "speed": 1.0, "final_t0": 1.25}])
    assert " ".join(c["text"].strip() for c in cues) == "So we query the database again."


def test_relayout_cues_never_splits_or_glues_latin_words():
    V = _import(LFS, "_vertical")
    from vstudio import platform as PF
    from vstudio.subs import Cue
    prof = PF.parse_targets(["xiaohongshu:vertical"])[0]
    en = ("And then this filter hits the database anyway, because the cache was never warmed up. If the account "
          "was deleted we just skip it and move on to the next one in the queue.")
    mixed = "我们今天用 Claude Code 来做一个很长很长的视频剪辑流程演示，然后把 filter 和 database 都讲清楚，再看看 cache 怎么预热"
    out = V.relayout_cues([Cue(0, 6, en), Cue(6, 12, mixed)], prof)
    e = [c.text for c in out if c.start < 6 - 1e-6]
    m = [c.text for c in out if c.start >= 6 - 1e-6]
    assert len(e) >= 2 and " ".join(e) == en
    assert len(m) >= 2
    joined = "".join(m)
    for w in ("Claude Code", "filter", "database", "cache"):
        assert w in joined or w in " ".join(m), w
    assert "ClaudeCode" not in joined
    for t in e + m:
        assert set(w for w in t.split() if w.isascii()) <= set(en.split()) | set(mixed.split()), t


def test_per_episode_hook_opens_its_episode(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    keep = [{"t0": 10.0, "t1": 20.0, "chapter": "A"}, {"t0": 30.0, "t1": 40.0, "chapter": "B"},
            {"t0": 50.0, "t1": 60.0, "chapter": "C"}]
    (work / "keep_list.json").write_text(json.dumps(keep))
    cfg = {"src": "x.mp4", "out": str(tmp_path / "out"), "share": [0, 0, 1280, 720], "speeds": {"lecture": 1.0, "hook": 1.0},
           "cards": {"dur": 1.0},
           "episodes": {"items": [{"chapters": [1, 1]},
                                  {"chapters": [2, 3], "hook": {"src": [55.0, 58.0], "lines": ["钩子", "副标题"]}}]}}
    (work / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    subprocess.run([sys.executable, str(LFS / "build_timeline.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    tl = json.loads((work / "timeline.json").read_text(encoding="utf-8"))
    kinds = [(it["kind"], it.get("hook_ep")) for it in tl]
    assert kinds == [("card", None), ("clip", None), ("clip", 2), ("card", None), ("clip", None),
                     ("card", None), ("clip", None)]
    assert tl[2]["overlay"] == "hook_overlay_ep2.png" and tl[2]["hook_lines"] == ["钩子", "副标题"]
    L = _import(LFS, "_lfc")
    c = L.Config(cfg, str(work / "config.json"))
    eps = L.episode_ranges(c, tl)
    assert eps[0]["a"] == 0.0 and eps[0]["b"] == pytest.approx(11.0)     # ends where ep2's hook starts
    assert eps[1]["a"] == pytest.approx(11.0) and eps[1]["b"] is None
    # body mapping skips the hook (cover shots / panels never land on it)
    assert L.map_src(tl, 55.5) == pytest.approx(tl[-1]["final_t0"] + 5.5)


# ------------------------------------------------------------------ longform-to-short: vertical screen fill
def _screen_share_frame(line_h=8):
    """Synthetic 1280x720 meeting frame: dark canvas, white page (0,163)-(958,615) with 'text' lines."""
    fr = np.full((720, 1280, 3), 32, np.uint8)
    fr[163:615, 0:958] = 250
    rng = np.random.default_rng(1)
    y = 190
    while y < 600:
        x = 40
        while x < 700:
            w = int(rng.integers(12, 60))
            fr[y:y + line_h, x:x + w] = 30
            x += w + 7
        y += line_h + 7
    return fr


@need_ff
@pytest.mark.parametrize("target", ["xiaohongshu:vertical", "xiaohongshu:full"])
def test_vertical_split_screen_fills_frame_and_text_is_readable(tmp_path, target):
    import cv2
    V = _import(LFS, "_vertical")
    from vstudio import platform as PF
    fr = _screen_share_frame()
    cv2.imwrite(str(tmp_path / "f.png"), fr)
    vid = tmp_path / "share.mp4"
    _ff("-loop", "1", "-t", "2", "-i", str(tmp_path / "f.png"), "-r", "24", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv444p", "-crf", "8", str(vid))
    prof = PF.parse_targets([target])[0]
    L = V.layout([prof])
    bx = V.boxes(L, "split", "title")
    o = dict(V.SCREEN_DEFAULTS)
    rects, st = V.analyse_screen(str(vid), 0.0, 2.0, 1.0, 24, 48, [0, 163, 958, 615], bx["screen"], o=o,
                                 vis_h=V.visible_h(L, bx["screen"]))
    W, H = L["W"], L["H"]
    y0 = bx["screen"][1]
    assert bx["band"][3] - bx["band"][1] <= 0.17 * (L["content"][3] - L["content"][1])     # slim title band
    # the screen fills everything from the band down to the caption band, and never reaches into it: captions
    # sit in their own lower band, not over the page text (no scrim needed)
    assert bx["screen"][3] == L["content"][3] <= L["caption"][1]
    gap = (bx["screen"][3] - y0) - st["draw_h"]           # a region too short at the zoom cap is centred
    assert gap <= 0.1 * (bx["screen"][3] - y0) and abs(st["draw_y"] - gap / 2) <= 2, st
    assert st["draw_h"] / H >= 0.45, st
    # no upscale beyond 2x of the source (720p text only blurs further); readable text or the zoom at its cap
    assert st["scale"] <= o["max_upscale"] + 1e-3 and st["max_zoom"] == pytest.approx(2.0)
    assert st["line_px"] == pytest.approx(8, abs=1.5)
    assert st["text_px"] >= o["min_text_px"] - 0.5 or st["scale"] >= st["max_zoom"] - 1e-3, st
    assert st["text_small"] == (st["text_px"] < o["min_text_px"] - 0.5)
    # the reading start (first text line) is inside the visible part
    canvas = np.zeros((H, W, 3), np.uint8)
    tile = V.warp(fr, rects[0], (W, st["draw_h"]), o["sharpen"])
    y0 += st["draw_y"]
    canvas[y0:y0 + st["draw_h"]] = tile
    cv2.imwrite(str(tmp_path / f"snap_{prof.name}_{prof.orientation}.png"), canvas)
    rows = np.where((canvas[y0:L["content"][3], :, 0] < 80).mean(axis=1) > 0.05)[0]
    assert len(rows) > 0 and rows[0] < 0.4 * (L["content"][3] - y0)
    # the first demo round's layout is still available: screen under the captions, dimmed there
    fb = V.boxes(L, "split", "title", screen_to="frame")
    assert fb["screen"][3] == H
    dim = V.scrim(L, fb["screen"], H - fb["screen"][1])
    assert dim[0] == 1.0 and dim[-1] < 0.6


def test_relayout_cues_fit_caption_box_height_without_workaround():
    """_vertical.caption_fit_profile was removed: vstudio.platform.fit_text_size now fits the box height."""
    V = _import(LFS, "_vertical")
    from vstudio import platform as PF
    from vstudio.subs import Cue
    prof = PF.parse_targets(["xiaohongshu:vertical"])[0]
    cues = [Cue(0, 3, "但是六十是一个论文的经验值之类，都是测试出来的结果，然后我们再看下一个指标"), Cue(3, 4, "RRF")]
    y0, y1 = PF.caption_box(prof)[1], PF.caption_box(prof)[3]
    for c in V.relayout_cues(cues, prof):
        fit = PF.fit_text_size(prof, c.text)
        assert fit["fits"] and fit["height"] <= y1 - y0, (c.text, fit)


def test_merge_vertical_manifest_keeps_other_targets():
    V = _import(LFS, "_vertical")
    first = {"targets": ["xiaohongshu:vertical"], "masters": {"1080x1440": "a.mp4"}, "warnings": ["ep1 xiaohongshu:vertical: long"],
             "episodes": [{"n": 1, "exports": [{"file": "xiaohongshu-vertical.mp4"}]},
                          {"n": 2, "exports": [{"file": "xiaohongshu-vertical.mp4"}]}]}
    second = {"targets": ["youtube-shorts:vertical"], "masters": {"1080x1920": "b.mp4"}, "warnings": [],
              "episodes": [{"n": 1, "exports": [{"file": "youtube-shorts-vertical.mp4"}]}]}
    m = V.merge_manifest(first, second)
    assert m["targets"] == ["xiaohongshu:vertical", "youtube-shorts:vertical"]
    assert set(m["masters"]) == {"1080x1440", "1080x1920"}
    assert [e["file"] for e in m["episodes"][0]["exports"]] == ["xiaohongshu-vertical.mp4", "youtube-shorts-vertical.mp4"]
    assert len(m["episodes"]) == 2 and m["warnings"] == ["ep1 xiaohongshu:vertical: long"]
    again = V.merge_manifest(m, dict(first, warnings=[]))          # re-run of 小红书 replaces its own entries
    assert [e["file"] for e in again["episodes"][0]["exports"]].count("xiaohongshu-vertical.mp4") == 1
    assert again["warnings"] == []


def test_keep_pad_in_stops_at_previous_word(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    blocks = [{"id": 1, "t0": 10.0, "t1": 14.0}, {"id": 2, "t0": 20.0, "t1": 24.0}]
    (work / "blocks.json").write_text(json.dumps(blocks))
    asr = {"segments": [{"start": 9.0, "end": 9.95, "text": "x", "words": [{"word": "上", "start": 9.6, "end": 9.95}]},
                        {"start": 10.0, "end": 14.0, "text": "y", "words": [{"word": "面试", "start": 10.0, "end": 14.0}]},
                        {"start": 14.1, "end": 15.0, "text": "z", "words": [{"word": "下", "start": 14.1, "end": 15.0}]}]}
    (work / "audio16k.json").write_text(json.dumps(asr, ensure_ascii=False))
    (work / "config.json").write_text(json.dumps({"src": "x.mp4", "out": str(tmp_path / "out"),
                                                  "keep": {"ranges": [[1, 1]], "pad_in": 0.15, "pad_out": 0.25}}))
    subprocess.run([sys.executable, str(LFS / "build_keep_list.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    seg = json.loads((work / "keep_list.json").read_text())[0]
    assert 9.95 < seg["t0"] <= 10.0          # not back into "上" (ended 9.95)
    assert 14.0 <= seg["t1"] < 14.1          # not into "下"


@need_ff
def test_zoom_targets_text_density_fallback_on_white_page(tmp_path):
    import cv2
    work = tmp_path / "work"
    work.mkdir()
    fr = np.full((720, 1280, 3), 255, np.uint8)          # white page, no grey code block
    for y in range(420, 600, 14):
        fr[y:y + 8, 700:1180] = 20                        # text block bottom-right
    cv2.imwrite(str(tmp_path / "p.png"), fr)
    _ff("-loop", "1", "-t", "4", "-i", str(tmp_path / "p.png"), "-r", "10", "-c:v", "libx264", "-preset",
        "ultrafast", "-pix_fmt", "yuv420p", str(tmp_path / "s.mp4"))
    cfg = {"src": str(tmp_path / "s.mp4"), "share": [0, 0, 1280, 720], "zoom": {"windows": [[1, 3]], "box": [400, 200]}}
    (work / "config.json").write_text(json.dumps(cfg))
    subprocess.run([sys.executable, str(LFS / "zoom_targets.py"), str(work / "config.json")], check=True,
                   capture_output=True)
    z = json.loads((work / "zoom_windows.json").read_text())[0]
    assert z["method"] == "text"
    assert 700 <= z["cx"] <= 1180 and 420 <= z["cy"] <= 600


# ------------------------------------------------------------------ explainer
def test_make_captions_creates_compositions_dir(tmp_path):
    """A blank `hyperframes init` has no compositions/: make_captions.py used to crash with FileNotFoundError."""
    (tmp_path / "subtitles").mkdir()
    (tmp_path / "audio").mkdir()
    (tmp_path / "subtitles" / "cues.json").write_text(json.dumps(
        [{"start": 0.1, "end": 1.5, "en": "Sixteen cores.", "zh": "十六个核心。", "line": 1}], ensure_ascii=False))
    (tmp_path / "audio" / "scenes.json").write_text(json.dumps({"total": 2.0}))
    for plat in ([], ["--platform", "xiaohongshu:full"]):
        subprocess.run([sys.executable, str(EXP / "make_captions.py"), "--project", str(tmp_path), *plat],
                       check=True, capture_output=True)
        assert "Sixteen cores." in (tmp_path / "compositions" / "captions.html").read_text(encoding="utf-8")
        shutil.rmtree(tmp_path / "compositions")


@pytest.mark.parametrize("spoken,shown", [
    ("An NVIDIA H100 has sixteen thousand, eight hundred and ninety-six of them.", "An NVIDIA H100 has 16,896 of them."),
    ("about a million threads", "about 1 million threads"),
    ("A million threads", "1 million threads"),
    ("a hundred steps", "100 steps"),
    ("N is one million, forty-eight thousand, five hundred and seventy-six", "N is 1,048,576"),
    ("one thousand, two thousand, three thousand", "1,000, 2,000, 3,000"),      # a list, not 6,000
    ("sixteen thousand, and then more", "16,000, and then more"),
    ("one point five million", "1.5 million"),
    ("It costs a few hundred dollars", "It costs a few hundred dollars"),
])
def test_display_en_numbers(spoken, shown):
    D = _import(EXP, "display_en")
    assert D.display(spoken, 1, {}) == shown


def test_vo_check_normalises_numbers_and_finds_dropped_sentence():
    C = _import(EXP, "vo_check")
    script = ("An NVIDIA H100 has sixteen thousand, eight hundred and ninety-six cores. With CUDA, you write one tiny "
              "function. About a million threads run it once.")
    clean = " An NVIDIA H100 has 16,896 cores. With CUDA you write one tiny function. About 1 million threads run it once."
    r = C.check(script, clean)
    assert r["missing"] == [] and min(s["cover"] for s in r["sentences"]) == 1.0
    dropped = " An NVIDIA H100 has 16,896 cores. With CUDA you write one tiny function."
    assert C.check(script, dropped)["missing"] == ["About a million threads run it once."]
    middle = " An NVIDIA H100 has 16,896 cores. About a million threads run it once."
    assert C.check(script, middle)["missing"] == ["With CUDA, you write one tiny function."]


def test_tts_regenerates_a_take_that_drops_a_sentence(tmp_path, monkeypatch):
    """tts.py: the first take drops a sentence -> a fresh take; if every take drops it, the run fails loudly."""
    import runpy
    from vstudio import media, tts as T
    C = _import(EXP, "vo_check")
    (tmp_path / "SCRIPT.md").write_text("# Script\n\n## Line 1 — hook\n\n    One chip. Many cores.\n")
    calls = []

    def synth(text, out=None, cache=True, **k):
        calls.append(cache)
        pathlib.Path(out).write_bytes(b"")
        return out

    monkeypatch.setattr(T, "synth", synth)
    monkeypatch.setattr(media, "duration", lambda p: 1.0)
    heard = iter([" One chip.", " One chip. Many cores."])
    monkeypatch.setattr(C, "check_take", lambda wav, text, backend="auto": C.check(text, next(heard)))
    monkeypatch.setitem(sys.modules, "vo_check", C)
    monkeypatch.setattr(sys, "argv", ["tts.py", "--project", str(tmp_path)])
    runpy.run_path(str(EXP / "tts.py"), run_name="__main__")
    assert calls == [True, False]                     # cached take, then one fresh take that passes

    calls.clear()
    monkeypatch.setattr(C, "check_take", lambda wav, text, backend="auto": C.check(text, " One chip."))
    with pytest.raises(SystemExit) as e:
        runpy.run_path(str(EXP / "tts.py"), run_name="__main__")
    assert "Many cores." in str(e.value) and len(calls) == 3


def test_layout_check_flags_small_top_graphic():
    """vertical shorts: a graphic in the top half (empty band above the captions) warns; a filled scene passes."""
    LC = _import(EXP, "layout_check")
    cv = _import(EXP, "canvas").resolve(".", "xiaohongshu:full")
    mx0, my0, mx1, my1 = cv["math"]
    yy = np.linspace(0, 1, 1920)[:, None, None]
    base = (np.zeros((1920, 1080, 3)) + np.array([15, 18, 32]) * (1 - 0.3 * yy)).astype(np.uint8)   # vignette-ish
    small = base.copy()
    small[my0 + 40:my0 + 420, mx0 + 60:mx1 - 300] = (88, 196, 221)       # one graphic, top third only
    r = LC.measure(small, cv)
    assert r["warn"] and r["bottom"] > 0.5
    full = base.copy()
    full[my0 + 40:my0 + 640, mx0 + 40:mx1 - 40] = (244, 211, 94)         # wider than half the row
    full[my1 - 160:my1 - 40, mx0 + 200:mx1 - 200] = (236, 238, 242)      # result line just above the captions
    r = LC.measure(full, cv)
    assert not r["warn"], r
    assert r["width"] > 0.85 and r["height"] > 0.85


def test_render_cover_platform_outputs_never_overwrite_plain_cover(tmp_path, monkeypatch):
    import runpy
    made = []
    cover = ROOT / "workflows" / "cover" / "scripts" / "render_cover.py"
    g = runpy.run_path(str(cover), run_name="render_cover")
    main = g["main"]
    main.__globals__["render"] = lambda html, out, size, accent, wait=2000: made.append((out, tuple(size))) or out
    main.__globals__["feed_preview"] = lambda prof, out: None
    out = str(tmp_path / "cover.png")
    monkeypatch.setattr(sys, "argv", ["render_cover.py", "c.html", "-o", out, "--platform", "xiaohongshu"])
    main()
    assert made and made[0][0] != out and made[0][0].startswith(str(tmp_path / "cover.xiaohongshu-"))
    made.clear()
    monkeypatch.setattr(sys, "argv", ["render_cover.py", "c.html", "-o", out])
    main()
    assert made == [(out, (1080, 1920))]
