"""`project touch` on a recipe project folder only reports its live status: the registry row stays a project and no
.vstudio/work.json is created (a `work` row made the desk drop the project). home.register keeps name / recipe /
kind when called with None. Registry under a temp VSTUDIO_HOME."""
import json
import os
import subprocess
import sys

import pytest

LIB = os.path.join(os.path.dirname(__file__), "..", "lib")

from vstudio.project import home as H  # noqa: E402
from vstudio.project import works as W  # noqa: E402


@pytest.fixture
def vhome(tmp_path, monkeypatch):
    h = tmp_path / "home"
    monkeypatch.setenv("VSTUDIO_HOME", str(h))
    return h


def _project(tmp_path, name="ai-skit", recipe="talkinghead"):
    d = tmp_path / name
    (d / "final").mkdir(parents=True)
    (d / "final" / "a.mp4").write_bytes(b"x")
    (d / "project.yaml").write_text(f"name: {name}\nrecipe: {recipe}\n", encoding="utf-8")
    H.register(str(d), name, recipe, None, None)
    return d


def _row(d):
    real = os.path.realpath(d)
    return next(p for p in H.projects() if os.path.realpath(p["dir"]) == real)


def test_touch_project_writes_only_status(vhome, tmp_path):
    d = _project(tmp_path)
    before = dict(_row(d))
    r = W.touch(str(d), status="running", stage="render", progress=0.4)
    assert r["kind"] == "project" and r["record"] is None
    assert r["status"]["status"] == "running"
    assert os.path.exists(d / ".vstudio" / "status.json")
    assert not os.path.exists(d / ".vstudio" / "work.json")
    assert _row(d) == before and "kind" not in _row(d)
    assert [p["dir"] for p in H.live_projects()] == [str(d)]
    assert H.live_works() == []
    W.touch(str(d), status="done", recipe="guess", title="x")          # recipe / title never rewrite the row
    assert _row(d) == before and not os.path.exists(d / ".vstudio" / "work.json")


def test_touch_registered_project_without_yaml_is_left_alone(vhome, tmp_path):
    d = tmp_path / "02-aigc"
    d.mkdir()
    H.register(str(d), "AIGC", "ai-video", None, None, kind="project")
    W.touch(str(d), status="running")
    assert _row(d)["kind"] == "project" and _row(d)["name"] == "AIGC"
    assert not os.path.exists(d / ".vstudio" / "work.json")
    with pytest.raises(ValueError):
        W.adopt(str(d))


def test_touch_cli_on_project(vhome, tmp_path):
    d = _project(tmp_path, "03-skit", "talkinghead")
    env = dict(os.environ, PYTHONPATH=LIB, VSTUDIO_HOME=str(vhome))
    out = subprocess.run([sys.executable, "-m", "vstudio.project", "touch", str(d), "--status", "running", "--json"],
                         env=env, capture_output=True, text=True, check=True).stdout
    assert json.loads(out)["kind"] == "project"
    rows = json.loads((vhome / "projects.json").read_text(encoding="utf-8"))
    assert len(rows) == 1 and rows[0].get("kind") is None and rows[0]["recipe"] == "talkinghead"
    assert not os.path.exists(d / ".vstudio" / "work.json")


def test_touch_plain_folder_still_makes_work(vhome, tmp_path):
    d = tmp_path / "04-vlog"
    (d / "final").mkdir(parents=True)
    (d / "final" / "v.mp4").write_bytes(b"x")
    r = W.touch(str(d), status="running", recipe="vlog")
    assert r["kind"] == "work" and os.path.exists(d / ".vstudio" / "work.json")
    assert _row(d)["kind"] == "work"


def test_register_keeps_fields_given_none(vhome, tmp_path):
    d = tmp_path / "p"
    d.mkdir()
    H.register(str(d), "Name", "ai-video", "s1", "c1", kind="project")
    created = _row(d)["created"]
    H.register(str(d))
    r = _row(d)
    assert (r["name"], r["recipe"], r["kind"], r["created"]) == ("Name", "ai-video", "project", created)
    H.register(str(d), "New", None, None, None)
    assert (_row(d)["name"], _row(d)["recipe"], _row(d)["kind"]) == ("New", "ai-video", "project")


def test_register_work_row_becomes_project_when_project_yaml_appears(vhome, tmp_path):
    d = tmp_path / "w"
    d.mkdir()
    H.register(str(d), "W", "vlog", None, None, kind="work")
    H.register(str(d), "W", "vlog", None, None)                         # still a work folder: kind kept
    assert _row(d)["kind"] == "work"
    (d / "project.yaml").write_text("name: W\nrecipe: vlog\n", encoding="utf-8")
    H.register(str(d), "W", "vlog", None, None)                         # vstudio.project.core after `project new`
    assert "kind" not in _row(d)
