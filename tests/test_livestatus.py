"""Live status (.vstudio/status.json): writers (touch / heartbeat / batch runner / project run), stale ->
interrupted, needs-you at a checkpoint."""
import json
import os
import subprocess
import sys
import time

LIB = os.path.join(os.path.dirname(__file__), "..", "lib")
sys.path.insert(0, LIB)

from vstudio.batch import livestatus as LS  # noqa: E402
from vstudio.project import works as W  # noqa: E402


def test_write_read_and_stale(tmp_path):
    d = str(tmp_path / "job")
    rec = LS.write(d, "running", stage="asr", progress=0.2, message="a.mp4", eta=30)
    assert rec["started"] and rec["pid"] == os.getpid()
    r = LS.read(d)
    assert (r["state"], r["stage"], r["progress"], r["stale"]) == ("running", "asr", 0.2, False)
    # our own pid is alive: an old heartbeat is still running until HARD_S
    assert LS.read(d, now=time.time() + LS.STALE_S + 5)["state"] == "running"
    assert LS.read(d, now=time.time() + LS.HARD_S + 5)["state"] == "interrupted"
    # an external writer whose process is gone: stale after STALE_S
    raw = json.loads(open(LS.status_path(d)).read())
    raw.update(pid=999999)
    open(LS.status_path(d), "w").write(json.dumps(raw))
    assert LS.read(d)["state"] == "running"
    later = LS.read(d, now=time.time() + LS.STALE_S + 5)
    assert (later["state"], later["stale"]) == ("interrupted", True)
    LS.write(d, "waiting", needs_you=True, message="checkpoint: hooks")
    w = LS.read(d, now=time.time() + LS.HARD_S * 10)
    assert (w["state"], w["needs_you"]) == ("waiting", True)              # waiting on the creator never goes stale
    LS.write(d, "done")
    assert (LS.read(d)["state"], LS.read(d)["progress"], LS.read(d)["needs_you"]) == ("done", 1.0, False)


def test_heartbeat_only_in_registered_folders(tmp_path, monkeypatch):
    monkeypatch.delenv("VSTUDIO_WORK_DIR", raising=False)
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert LS.heartbeat("asr", force=True) is None
    assert not (plain / ".vstudio").exists()
    job = tmp_path / "job"
    W.touch(str(job), recipe="talkinghead", status="running", stage="plan", register=False)
    (job / "work").mkdir()
    monkeypatch.chdir(job / "work")
    assert LS.heartbeat("export", progress=0.5, force=True)["stage"] == "export"
    assert LS.read(str(job))["progress"] == 0.5
    assert LS.heartbeat("export", progress=0.6) is None                  # throttled


def test_touch_cli_and_external_runner(tmp_path):
    job = tmp_path / "fuye"
    env = dict(os.environ, PYTHONPATH=LIB, VSTUDIO_HOME=str(tmp_path / "home"))
    run = lambda *a: json.loads(subprocess.run([sys.executable, "-m", "vstudio.project", "touch", str(job), *a,  # noqa: E731
                                                "--json"], env=env, capture_output=True, text=True, check=True).stdout)
    r = run("--status", "running", "--stage", "cut", "--progress", "0.3", "--message", "clip A")
    assert r["status"]["status"] == "running" and r["kind"] == "work"
    st = LS.read(str(job))
    assert (st["state"], st["stage"]) == ("running", "cut")
    assert st["pid"] != os.getpid()                                      # the CLI process is gone ...
    assert LS.read(str(job), now=time.time() + LS.STALE_S + 1)["state"] == "interrupted"   # ... -> interrupted
    run("--status", "waiting", "--needs-you", "--message", "pick hooks")
    assert LS.read(str(job))["needs_you"] is True


def test_batch_runner_writes_status(tmp_path, monkeypatch):
    import yaml
    sys.path.insert(0, os.path.dirname(__file__))
    import _batch_helpers as BH  # noqa: F401  (registers the test-fake recipe)
    from vstudio.batch.plan import plan_batch
    from vstudio.batch.run import run_batch
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "bench.json"))
    BH.STATE.update(active={}, peak={}, calls=[])
    spec = dict(name="t", recipe="test-fake", plugins=["_batch_helpers"], retry={"backoff": 0},
                jobs=[dict(id=f"j{i}", x=i) for i in range(3)])
    (tmp_path / "batch.yaml").write_text(yaml.safe_dump(spec))
    bdir = plan_batch(str(tmp_path / "batch.yaml"), echo=False)["batch_dir"]
    res = run_batch(bdir, echo=False)
    st = LS.read(bdir)
    assert st["updated_by"] == "batch" and st["state"] == ("done" if res["status"] == "done" else "failed")
    assert st["progress"] == 1.0 and st["started"] <= st["heartbeat"]
    # the line as a code the desk words (never only "3/3 jobs"), the clip count, and no time left once it is over
    assert st["jobs_total"] == 3 and st["jobs_done"] == 3 and "eta" not in st
    assert st["message"].endswith("jobs") and "live_code" not in st          # the final line is free text again


def test_runner_fields_eta_and_codes(tmp_path):
    from vstudio.batch.run import Runner
    r = Runner.__new__(Runner)
    r.inflight, r.finished, r.n_done, r.n_total, r.jobs_total = {}, [], 0, 0, 0
    assert r._live_fields()["live_code"] is None and r._eta(None) is None
    r.jobs_total, r.n_total, r.n_done, r.finished = 3, 30, 3, [dict(id="s001")]
    r._t_run, r._est_wall = time.time() - 5, 120.0
    f = r._live_fields()
    assert (f["live_code"], f["live_params"], f["jobs_done"], f["jobs_total"]) == ("jobs", dict(done=1, total=3), 1, 3)
    assert f["eta"] == round(120 * 0.9)                    # little done yet: the benchmark's estimate
    r._t_run, r.n_done = time.time() - 60, 15                # half done in a minute: the run's own pace counts
    assert 40 <= r._eta(0.5) <= 70


def test_codes_follow_the_message(tmp_path):
    d = str(tmp_path / "p")
    LS.write(d, "running", message="0/2 jobs", live_code="jobs", live_params=dict(done=0, total=2), eta=40)
    LS.write(d, "waiting", needs_you=True, message="waits for you")
    rec = json.loads(open(LS.status_path(d)).read())
    assert "live_code" not in rec and "eta" not in rec         # a new free-text line: the old code and time left go
