"""Registry hygiene: batches.json / projects.json never keep missing folders or temp-dir test junk (in the real,
non-temp registry), and scratch batches never enter it."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio.batch import clients as CL  # noqa: E402
from vstudio.project import home as H  # noqa: E402


def test_is_temp_path():
    import tempfile
    assert CL.is_temp_path(os.path.join(tempfile.gettempdir(), "tmpx", "batch-fake"))
    if os.name == "nt":                                    # any case, the long and the 8.3 form
        assert CL.is_temp_path(os.path.join(tempfile.gettempdir().upper(), "x"))
        assert not CL.is_temp_path(r"D:\work\videos\batch-rag")
        return
    assert CL.is_temp_path("/var/folders/1s/abc/T/tmpx/batch-fake")
    assert CL.is_temp_path("/private/var/folders/1s/abc/T/x")
    assert CL.is_temp_path("/tmp/x")
    assert not CL.is_temp_path("/Volumes/work/videos/batch-rag")


def _real_home(monkeypatch, tmp_path):
    """A registry that is not in a temp dir: patch is_temp_path so only the junk paths count as temp."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("VSTUDIO_HOME", str(home))
    junk = str(tmp_path / "junk")
    monkeypatch.setattr(CL, "is_temp_path", lambda p: os.path.abspath(p or "").startswith(junk))
    return home, junk


def test_prune_batches(monkeypatch, tmp_path):
    home, junk = _real_home(monkeypatch, tmp_path)
    real = tmp_path / "work" / "batch-a"
    real.mkdir(parents=True)
    (real / "batch.db").write_bytes(b"")
    os.makedirs(os.path.join(junk, "batch-fake"))
    open(os.path.join(junk, "batch-fake", "batch.db"), "w").close()
    rows = [dict(dir=str(real), name="a"), dict(dir=os.path.join(junk, "batch-fake"), name="fake"),
            dict(dir=str(tmp_path / "gone"), name="gone")]
    (home / "batches.json").write_text(json.dumps(rows))
    assert [r["dir"] for r in CL.batches()] == [str(real)]
    gone = CL.prune_batches()
    assert {r["name"] for r in gone} == {"fake", "gone"}
    assert [r["dir"] for r in json.loads((home / "batches.json").read_text())] == [str(real)]
    CL.register_batch(os.path.join(junk, "batch-fake"), "fake")          # scratch batches stay out
    assert [r["dir"] for r in json.loads((home / "batches.json").read_text())] == [str(real)]


def test_temp_registry_keeps_temp_batches(monkeypatch, tmp_path):
    monkeypatch.setenv("VSTUDIO_HOME", str(tmp_path / "home"))           # tests: registry itself in temp
    b = tmp_path / "batch-x"
    b.mkdir()
    (b / "batch.db").write_bytes(b"")
    CL.register_batch(str(b), "x")
    assert [r["dir"] for r in CL.batches()] == [str(b)]


def test_prune_projects(monkeypatch, tmp_path):
    home, junk = _real_home(monkeypatch, tmp_path)
    real = tmp_path / "work" / "proj"
    real.mkdir(parents=True)
    (real / "project.yaml").write_text("name: p\n")
    os.makedirs(os.path.join(junk, "p2"))
    open(os.path.join(junk, "p2", "project.yaml"), "w").close()
    (home / "projects.json").write_text(json.dumps([dict(dir=str(real)), dict(dir=os.path.join(junk, "p2")),
                                                    dict(dir=str(tmp_path / "missing"))]))
    assert len(H.prune()) == 2
    assert [p["dir"] for p in H.projects()] == [str(real)]
    r = H.register(os.path.join(junk, "p3"), "p3")
    assert r.get("registered") is False and len(H.projects()) == 1
