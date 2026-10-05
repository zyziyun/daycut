"""longform-to-short on the shared speech-cleanup tool (vstudio.cleanup): build_keep_list.py cleans every kept
segment per window, writes a per-episode review sheet and accepts the creator's reply; build_timeline.py turns
the kept pieces into clips (fades at real cuts) and uses the word-safe hook edges. Synthetic tones only."""
import json
import pathlib
import subprocess
import sys
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
LFS = ROOT / "workflows" / "longform-to-short" / "scripts"
SR = 16000
WORDS = [("我们", 1.0, 1.5), ("今天", 1.5, 2.0), ("嗯", 3.5, 3.8), ("讲", 4.6, 5.0), ("模型", 5.0, 5.6),
         ("第二", 10.0, 10.5), ("部分", 10.5, 11.0), ("开始", 11.0, 11.6)]


def _project(tmp_path, extra_cfg=None):
    work = tmp_path / "work"
    work.mkdir()
    t = np.arange(int(13 * SR)) / SR
    x = np.random.RandomState(0).randn(len(t)) * 0.001
    for _, a, b in WORDS:
        m = (t >= a) & (t < b)
        x[m] += 0.4 * np.sin(2 * np.pi * 220 * t[m])
    with wave.open(str(work / "audio16k.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    segs = [{"start": 1.0, "end": 5.6, "text": "".join(w for w, _, _ in WORDS[:5]),
             "words": [{"word": w, "start": a, "end": b} for w, a, b in WORDS[:5]]},
            {"start": 10.0, "end": 11.6, "text": "".join(w for w, _, _ in WORDS[5:]),
             "words": [{"word": w, "start": a, "end": b} for w, a, b in WORDS[5:]]}]
    (work / "audio16k.json").write_text(json.dumps({"segments": segs}, ensure_ascii=False))
    (work / "blocks.json").write_text(json.dumps([{"id": 1, "t0": 1.0, "t1": 5.6}, {"id": 2, "t0": 10.0, "t1": 11.6}]))
    cfg = {"src": "x.mp4", "out": str(tmp_path / "out"), "share": [0, 0, 1280, 720],
           "keep": {"ranges": [[1, 2]], "chapters": {"1": "A", "2": "B"}},
           "episodes": {"items": [{"chapters": [1, 1]}, {"chapters": [2, 2]}]},
           "hook": {"src": [4.6, 5.4]}}
    cfg.update(extra_cfg or {})
    (work / "config.json").write_text(json.dumps(cfg, ensure_ascii=False))
    return work


def _run(work, script, *args):
    r = subprocess.run([sys.executable, str(LFS / script), str(work / "config.json"), *args],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def _in(t, pieces):
    return any(a <= t <= b for a, b in pieces)


def test_keep_list_is_cleaned_per_window_with_a_review_sheet_per_episode(tmp_path):
    work = _project(tmp_path)
    out = _run(work, "build_keep_list.py")
    keep = json.loads((work / "keep_list.json").read_text())
    pieces = keep[0]["keep"]
    assert not _in(3.65, pieces)                                     # 嗯 removed (AUTO)
    for _, a, b in WORDS[:2] + WORDS[3:5]:
        assert _in((a + b) / 2, pieces)                              # every content word kept
    assert sum(b - a for a, b in pieces) < (keep[0]["t1"] - keep[0]["t0"]) - 1.5   # 气口 squeezed
    assert (work / "cleanup_review.ep1.md").exists() and "ep1" in out
    assert keep[0]["episode"] == 1 and keep[1]["episode"] == 2
    edl = json.loads((work / "cleanup.ep1.json").read_text())
    assert [e["id"] for e in edl["edits"]] == list(range(1, len(edl["edits"]) + 1))
    # the creator keeps the filler: 保留 N on sheet 1
    fid = next(e["id"] for e in edl["edits"] if e["kind"] == "filler")
    _run(work, "build_keep_list.py", "--reply", f"1:保留 {fid}")
    assert _in(3.65, json.loads((work / "keep_list.json").read_text())[0]["keep"])
    # the hook (hand-written range) is word-safe and its end covers the last word plus the fade
    hk = json.loads((work / "hook_edges.json").read_text())["hook"]
    assert hk["edge"][0] <= 4.6 and hk["edge"][1] >= 5.6


def test_cleanup_disabled_keeps_plain_snapped_segments(tmp_path):
    work = _project(tmp_path, {"cleanup": {"enabled": False}})
    _run(work, "build_keep_list.py")
    keep = json.loads((work / "keep_list.json").read_text())
    assert keep[0]["keep"] == [[keep[0]["t0"], keep[0]["t1"]]]
    assert not (work / "cleanup_review.ep1.md").exists()


def test_timeline_uses_kept_pieces_with_fades_at_real_cuts(tmp_path):
    work = _project(tmp_path, {"speeds": {"lecture": 1.0, "hook": 1.0}})
    _run(work, "build_keep_list.py")
    keep = json.loads((work / "keep_list.json").read_text())
    (work / "zoom_windows.json").write_text(json.dumps([]))
    _run(work, "build_timeline.py")
    tl = json.loads((work / "timeline.json").read_text())
    hook = tl[0]
    hk = json.loads((work / "hook_edges.json").read_text())["hook"]
    assert hook.get("hook") and [hook["t0"], hook["t1"]] == hk["edge"]
    body = [it for it in tl if it["kind"] == "clip" and not it.get("hook")]
    assert [[it["t0"], it["t1"]] for it in body] == [p for s in keep for p in s["keep"]]
    assert not any(it["cont_in"] or it["cont_out"] for it in body)   # every join is a real cut -> afade
