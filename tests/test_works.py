"""Work records: plain skill folders (final/, REPORT.md, post.md, work/) are adopted / touched into a lightweight
record + the projects registry, so the desk and `project list` see every job."""
import json
import os
import subprocess
import sys

LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, LIB)

from vstudio.project import home as H  # noqa: E402
from vstudio.project import works as W  # noqa: E402


def _folder(root, name, files):
    d = root / name
    for f in files:
        p = d / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return d


def test_detect_and_guess(tmp_path):
    th = _folder(tmp_path, "01-talkinghead", ["REPORT.md", "final/xhs_3x4.mp4", "final/cover_3x4.jpg", "final/post.md"])
    (th / "REPORT.md").write_text("# 01-talkinghead: 口播精剪\n", encoding="utf-8")
    fuye = _folder(tmp_path, "fuye", ["sheet.jpg", "work/compose.py", "work/clips/A/parts.json"])
    pod = _folder(tmp_path, "05-x", ["clips.json", "final/a.mp4"])
    empty = _folder(tmp_path, "random", ["notes.txt"])
    assert W.looks_like_work(str(th)) and W.looks_like_work(str(fuye)) and W.looks_like_work(str(pod))
    assert not W.looks_like_work(str(empty))
    assert W.guess_type(str(th)) == "talkinghead"
    assert W.guess_type(str(fuye)) == "slices"
    assert W.guess_type(str(pod)) == "podcast"
    s = W.scan(str(th))
    assert s["outputs"] == ["final/xhs_3x4.mp4"]
    assert s["covers"] == ["final/cover_3x4.jpg"]
    assert s["posts"] == ["final/post.md"]


def test_adopt_registers_and_lists(monkeypatch, tmp_path):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))
    d = _folder(tmp_path, "03-raphael-story", ["final/story.mp4", "final/cover.png", "post.md", "src/a.jpg"])
    before = sorted(str(p) for p in d.rglob("*"))
    r = W.adopt(str(d))
    assert r["type"] == "photo-story" and r["recipe"] == "photo-story"
    assert r["outputs"] == ["final/story.mp4"]
    assert r["sources"] == [str(d / "src" / "a.jpg")]
    after = sorted(str(p) for p in d.rglob("*"))
    assert set(after) - set(before) == {str(d / ".vstudio"), str(d / ".vstudio" / "work.json")}   # only the record
    assert [p["dir"] for p in H.live_works()] == [str(d)]
    assert H.live_projects() == []
    env = dict(os.environ, PYTHONPATH=LIB)
    out = subprocess.run([sys.executable, "-m", "vstudio.project", "list", "--json"], env=env, capture_output=True,
                         text=True, check=True).stdout
    rows = json.loads(out)["projects"]
    assert rows[0]["kind"] == "work" and rows[0]["type"] == "photo-story" and rows[0]["items"] == 1
    # re-touch keeps created, explicit recipe wins
    r2 = W.touch(str(d), recipe="vlog", title="T")
    assert (r2["created"], r2["type"], r2["title"]) == (r["created"], "vlog", "T")
    # prune keeps a work folder; drops it once the record is gone
    assert H.prune() == []
    os.remove(d / ".vstudio" / "work.json")
    assert len(H.prune()) == 1


def test_adopt_cli(monkeypatch, tmp_path):
    d = _folder(tmp_path, "06-cuda-explainer", ["final/a.mp4", "project/hyperframes.json"])
    env = dict(os.environ, PYTHONPATH=LIB, VSTUDIO_HOME=str(tmp_path / "home"))
    out = subprocess.run([sys.executable, "-m", "vstudio.project", "adopt", str(d), "--json"], env=env,
                         capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    assert r["ok"] and r["type"] == "explainer" and r["recipe"] == "explainer"
