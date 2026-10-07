"""vstudio.batch: spec / plan / scheduler / review / package / hygiene on a fake recipe (no media, fast)."""
import json
import os
import pathlib
import sqlite3
import subprocess
import sys

import pytest
import yaml

import _batch_helpers as H
from vstudio.batch import estimate as EST
from vstudio.batch import hygiene, planner, review
from vstudio.batch import spec as S
from vstudio.batch.package import package
from vstudio.batch.plan import plan_batch
from vstudio.batch.run import is_transient, run_batch, TransientError, default_limits, limit_for, parse_limits
from vstudio.batch.store import Store

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("VSTUDIO_BATCH_BENCH", str(tmp_path / "machine_bench.json"))
    H.STATE.update(active={}, peak={}, calls=[])


def mkspec(tmp, jobs, **kw):
    spec = dict(name="t", recipe="test-fake", plugins=["_batch_helpers"], jobs=jobs, retry={"backoff": 0})
    spec.update(kw)
    p = tmp / "batch.yaml"
    p.write_text(yaml.safe_dump(spec, allow_unicode=True))
    return str(p)


def plan_run(tmp, jobs, run=True, **kw):
    r = plan_batch(mkspec(tmp, jobs, **kw), echo=False)
    if run:
        return r["batch_dir"], run_batch(r["batch_dir"], echo=False)
    return r["batch_dir"], None


def jobs_n(n, **extra):
    return [dict(id=f"j{i + 1:03d}", x=i, **extra) for i in range(n)]


# --------------------------------------------------------------------------- spec / plan
def test_spec_expand_variants_yaml_and_csv(tmp_path):
    seg = tmp_path / "segments.yaml"
    seg.write_text(yaml.safe_dump({"segments": [
        dict(id="s1", range="0:10-1:05", title="A", hooks=[dict(src=[20, 24], lines=["L1"]), dict(src="30-33")]),
        dict(id="s2", start=70, end=130, title="B", hook=dict(src=[80, 84], lines=["H"]))]}))
    p = tmp_path / "spec.yaml"
    p.write_text(yaml.safe_dump(dict(recipe="test-fake", segments="segments.yaml",
                                     defaults=dict(platforms=["xiaohongshu:full", "douyin"]),
                                     variants=dict(by=["hook", "platform"]))))
    spec = S.load_spec(str(p))
    rows = planner.FilePlanner().rows(spec)
    assert rows[0]["range"] == [10.0, 65.0] and rows[1]["range"] == [70.0, 130.0]
    jobs = S.apply_variants(spec, [dict(item=r["id"], params=S.with_defaults(spec, r)) for r in rows])
    ids = [j["id"] for j in jobs]
    assert ids == ["s1.h1.xiaohongshu-full", "s1.h1.douyin", "s1.h2.xiaohongshu-full", "s1.h2.douyin",
                   "s2.xiaohongshu-full", "s2.douyin"]
    j = jobs[2]
    assert j["params"]["hook"] == dict(src=[30.0, 33.0], lines=[]) and j["params"]["platforms"] == ["xiaohongshu:full"]
    assert "hooks" not in j["params"] and jobs[4]["params"]["hook"]["lines"] == ["H"]
    # CSV job rows
    csvp = tmp_path / "rows.csv"
    csvp.write_text("id,start,end,title,hook_start,hook_end,hook_lines,tags,platforms\n"
                    "c1,1:00,1:45,标题,62,65,第一句|第二句,a|b,\"douyin,tiktok\"\n,5,9,无id,,,,,\n", encoding="utf-8")
    rows = S.read_rows(str(csvp))
    assert rows[0] == dict(id="c1", range=[60.0, 105.0], title="标题", hook=dict(src=[62.0, 65.0], lines=["第一句", "第二句"]),
                           tags=["a", "b"], platforms=["douyin", "tiktok"])
    assert rows[1]["id"] == "s002" and rows[1]["range"] == [5.0, 9.0]


def test_plan_store_wal_isolated_dirs_and_replan(tmp_path):
    bdir, _ = plan_run(tmp_path, jobs_n(3), run=False)
    st = Store(bdir)
    assert st.journal_mode() == "wal"
    assert [j["id"] for j in st.jobs()] == ["j001", "j002", "j003"]
    assert all(os.path.exists(os.path.join(bdir, "jobs", j, "job.json")) for j in ("j001", "j002", "j003"))
    st.set_job("j002", state="done")
    st.close()
    # replan: j002 changed, j003 gone, j004 new
    js = jobs_n(2) + [dict(id="j004", x=9)]
    js[1]["x"] = 42
    r = plan_batch(mkspec(tmp_path, js), echo=False)
    assert r["created"] == ["j004"] and r["updated"] == ["j002"] and r["dropped"] == ["j003"]
    st = Store(bdir)
    assert st.job("j002")["state"] == "planned" and st.job("j002")["params"]["x"] == 42
    assert st.job("j003")["state"] == "dropped"
    st.close()


# --------------------------------------------------------------------------- scheduler
def test_shared_cache_hit_and_idempotent_rerun(tmp_path):
    bdir, res = plan_run(tmp_path, jobs_n(3))
    assert res["exit_code"] == 0
    c = H.calls(bdir)
    assert sum(1 for _, s in c if s == "probe") == 1          # one source -> one probe, one asr for 3 jobs
    assert sum(1 for _, s in c if s == "asr") == 1
    assert sum(1 for _, s in c if s == "render") == 3
    st = Store(bdir)
    cached = [(r["job"], r["stage"]) for r in st.q("SELECT * FROM stages WHERE cached=1")]
    assert len([x for x in cached if x[1] == "asr"]) == 2
    assert all(j["state"] == "done" and j["qc"] == "green" for j in st.jobs())
    st.close()
    # rerun: nothing to do; then change one job's param -> only its downstream stages re-run
    n0 = len(H.calls(bdir))
    js = jobs_n(3)
    js[1]["x"] = 99
    plan_batch(mkspec(tmp_path, js), echo=False)
    res = run_batch(bdir, echo=False)
    new = H.calls(bdir)[n0:]
    assert sorted(new) == [("j002", "big"), ("j002", "qc"), ("j002", "render")]
    assert res["exit_code"] == 0


def test_concurrency_limits_respected(tmp_path):
    js = [dict(id=f"j{i}", x=i, source=f"src{i}") for i in range(6)]
    bdir, _ = plan_run(tmp_path, js, run=False, test=dict(sleep=dict(render=0.15, asr=0.05)),
                       concurrency={"cpu-render": 2, "asr": 1, "io": 3})
    res = run_batch(bdir, echo=False)
    assert res["exit_code"] == 0
    assert H.STATE["peak"]["cpu-render"] == 2 and res["peak"]["cpu-render"] == 2
    assert H.STATE["peak"]["asr"] == 1 and res["peak"]["asr"] == 1
    assert sum(1 for _, s in H.calls(bdir) if s == "asr") == 6


def test_resume_after_crash(tmp_path):
    bdir, _ = plan_run(tmp_path, jobs_n(4), run=False, concurrency={"cpu-render": 1, "cpu": 1, "io": 1})
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT / "lib"), str(ROOT / "tests")]),
               VSTUDIO_TEST_CRASH_AT="j003:render")
    p = subprocess.run([sys.executable, "-m", "vstudio.batch", "run", "--batch", bdir], env=env,
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 9, p.stderr                         # hard crash (os._exit) mid-stage
    con = sqlite3.connect(os.path.join(bdir, "batch.db"))
    states = dict(con.execute("SELECT job || ':' || stage, state FROM stages").fetchall())
    con.close()
    recorded = {tuple(k.split(":")) for k, v in states.items() if v == "done"}
    assert ("j001", "qc") in recorded
    assert states["j003:render"] == "running"                  # left behind by the crash
    before = H.calls(bdir)
    assert ("j003", "render") not in before
    res = run_batch(bdir, echo=False)                          # restart: resumes, no redo of finished stages
    assert res["exit_code"] == 0
    after = H.calls(bdir)
    assert after[:len(before)] == before
    redo = after[len(before):]
    assert ("j003", "render") in redo
    assert not any(c in recorded for c in redo)                # nothing recorded as finished re-ran
    assert sum(1 for _, s in after if s == "asr") == 1
    st = Store(bdir)
    assert all(j["state"] == "done" for j in st.jobs())
    st.close()


def test_budget_refusal(tmp_path):
    bdir, res = plan_run(tmp_path, jobs_n(3), budget={"max_hours": 0.0001})
    assert res["status"] == "over-budget" and res["exit_code"] == 2
    assert H.calls(bdir) == []
    st = Store(bdir)
    est = EST.estimate(st, __import__("vstudio.batch.run", fromlist=["x"]).load_recipe(st.spec), st.spec,
                       default_limits())
    assert not est["budget"]["ok"] and "max_hours" in est["budget"]["over"][0]
    assert est["stages"]["asr"]["n"] == 1                      # shared stage counted once per source
    assert est["stages"]["render"]["n"] == 3
    st.close()


def test_transient_retry_then_breaker_pause_and_resume(tmp_path):
    bdir, res = plan_run(tmp_path, jobs_n(2), test=dict(fail={"j001:render": "once"}))
    assert res["exit_code"] == 0
    st = Store(bdir)
    assert st.stage("j001", "render")["attempts"] == 2 and st.job("j001")["state"] == "done"
    st.close()
    assert is_transient(TransientError("x")) and is_transient(RuntimeError("HTTP 503 overloaded"))
    assert not is_transient(ValueError("bad input"))
    # deterministic failures in most jobs -> circuit breaker pauses the batch
    t2 = tmp_path / "b2"
    t2.mkdir()
    fails = {f"j00{i}:render": "always" for i in (1, 2, 3)}
    bdir, res = plan_run(t2, jobs_n(6), test=dict(fail=fails), breaker={"min_jobs": 3, "max_fail_rate": 0.5},
                         concurrency={"cpu-render": 1, "cpu": 1})
    assert res["status"] == "paused" and res["exit_code"] == 3 and "failure rate" in res["pause_reason"]
    st = Store(bdir)
    assert st.state() == "paused"
    assert st.stage("j001", "render")["attempts"] == 1          # deterministic: no retry
    assert any(j["state"] in ("planned", "interrupted") for j in st.jobs())   # the rest did not run
    assert not any(j["state"] == "running" for j in st.jobs())          # never a stale running
    st.close()
    assert run_batch(bdir, echo=False)["exit_code"] == 3       # still paused
    res = run_batch(bdir, echo=False, resume=True)
    st = Store(bdir)
    assert all(j["state"] in ("done", "failed") for j in st.jobs())
    assert [j["id"] for j in st.jobs(("failed",))] == ["j001", "j002", "j003"]
    st.close()


def test_pilot_then_confirm_and_pilot_red_pauses(tmp_path):
    bdir, _ = plan_run(tmp_path, jobs_n(4), run=False)
    res = run_batch(bdir, echo=False, pilot=2)
    assert res["status"] == "pilot-review"
    assert {j for j, _ in H.calls(bdir) if _ == "qc"} == {"j001", "j002"}
    assert run_batch(bdir, echo=False)["exit_code"] == 4       # waits for review
    res = run_batch(bdir, echo=False, confirm_pilot=True)
    assert res["exit_code"] == 0
    assert {j for j, _ in H.calls(bdir) if _ == "qc"} == {"j001", "j002", "j003", "j004"}
    t2 = tmp_path / "b2"
    t2.mkdir()
    js = jobs_n(3)
    js[0]["red"] = True
    bdir, _ = plan_run(t2, js, run=False)
    res = run_batch(bdir, echo=False, pilot=2)
    assert res["status"] == "paused" and "pilot job j001" in res["pause_reason"]


def test_pause_drains_post_render_stages_and_never_leaves_running(tmp_path):
    """A pilot job goes red while another pilot job is still in its last render stage: that job still runs its
    cheap post-render stage (qc) instead of being left half-done; no new job starts; nothing stays 'running'."""
    js = jobs_n(3)
    js[0]["red"] = True
    bdir, _ = plan_run(tmp_path, js, run=False, concurrency={"cpu-render": 3},
                       test=dict(sleep_job={"j002:big": 0.6}))
    res = run_batch(bdir, echo=False, pilot=2)
    assert res["status"] == "paused" and "pilot job j001" in res["pause_reason"]
    done = H.calls(bdir)
    assert ("j002", "big") in done and ("j002", "qc") in done          # drained after the pause
    assert not any(j == "j003" for j, _ in done)                        # not a pilot job: never started
    st = Store(bdir)
    assert st.job("j002")["state"] == "done" and st.job("j002")["qc"] == "green"
    assert not any(j["state"] == "running" for j in st.jobs())
    st.close()


def test_pause_interrupts_half_rendered_job_then_resume(tmp_path):
    """The other job is still in an EXPENSIVE stage when the batch pauses: it finishes that stage but starts no
    further render; it ends 'interrupted' (status says so too) and the next run picks it up."""
    from vstudio.batch import cli as CLI
    js = jobs_n(2)
    js[0]["red"] = True
    bdir, _ = plan_run(tmp_path, js, run=False, concurrency={"cpu-render": 3},
                       test=dict(sleep_job={"j002:render": 0.6}))
    res = run_batch(bdir, echo=False, pilot=2)
    assert res["status"] == "paused"
    done = H.calls(bdir)
    assert ("j002", "render") in done and ("j002", "big") not in done and ("j002", "qc") not in done
    st = Store(bdir)
    assert st.job("j002")["state"] == "interrupted"
    assert {r["id"]: r["state"] for r in CLI.status_rows(st)}["j002"] == "interrupted"
    # a run killed hard leaves 'running' rows behind: status shows them as interrupted (no lock holder)
    st.set_job("j002", state="running")
    assert {r["id"]: r["state"] for r in CLI.status_rows(st)}["j002"] == "interrupted"
    st.set_job("j002", state="interrupted")
    st.close()
    res = run_batch(bdir, echo=False, pilot=2, resume=True)
    assert ("j002", "qc") in H.calls(bdir) and ("j002", "render") not in H.calls(bdir)[len(done):]
    st = Store(bdir)
    assert st.job("j002")["state"] == "done"
    st.close()


# --------------------------------------------------------------------------- review / package / hygiene
def _fake_exports(bdir, jid, plats=("xiaohongshu-full", "douyin-vertical")):
    st = Store(bdir)
    d = os.path.join(bdir, "jobs", jid, "export")
    os.makedirs(d, exist_ok=True)
    ex = []
    for p in plats:
        f = os.path.join(d, f"{p}.mp4")
        with open(f, "wb") as fh:
            fh.write(f"{jid}-{p}".encode() * 100)
        cov = os.path.join(d, f"{p}.cover.jpg")
        open(cov, "wb").write(b"jpg")
        name, orient = p.rsplit("-", 1)
        ex.append(dict(platform=name, orientation=orient, file=f, cover=cov, post=None, duration=12.0))
    st.set_stage(jid, "export", state="done", key="k", out=dict(exports=ex, files=[e["file"] for e in ex]))
    st.close()


def test_review_page_and_apply(tmp_path):
    js = jobs_n(3)
    js[2]["red"] = True
    bdir, res = plan_run(tmp_path, js)
    r = review.generate(bdir)
    page = open(r["page"], encoding="utf-8").read()
    assert all(f'"{j}"' in page for j in ("j001", "j002", "j003")) and "keydown" in page and "decisions.json" in page
    assert r["red"] == 1 and os.path.exists(r["decisions_needed"])
    dec = tmp_path / "decisions.json"
    dec.write_text(json.dumps(dict(decisions={"j001": {"decision": "approve"},
                                              "j003": {"decision": "reject", "reason": "hook too slow"}},
                                   cleanup={"j002": "确认 3 / 保留 5"})), encoding="utf-8")
    out = review.apply_decisions(bdir, str(dec))
    assert out["approved"] == ["j001"] and out["rejected"] == ["j003"] and out["replied"] == ["j002"]
    st = Store(bdir)
    assert st.job("j001")["state"] == "approved"
    j3 = st.job("j003")
    assert j3["state"] == "needs-replan" and j3["review_reason"] == "hook too slow"
    j2 = st.job("j002")
    assert j2["state"] == "planned" and j2["params"]["cleanup_reply"] == "确认 3 / 保留 5"
    st.close()


def test_package_manifest_hash(tmp_path):
    bdir, _ = plan_run(tmp_path, jobs_n(3))
    for j in ("j001", "j002", "j003"):
        _fake_exports(bdir, j)
    review.apply_decisions(bdir, {"decisions": {j: {"decision": "approve"} for j in ("j001", "j002", "j003")}})
    a = package(bdir, per_day=2, start="2026-10-10", times=["12:00", "19:00"])
    assert a["items"] == 6 and a["jobs"] == 3
    man = json.load(open(a["manifest"], encoding="utf-8"))
    assert man["confirmation_code"] == a["code"]
    days = [(it["platform"], it["date"], it["time"]) for it in man["items"]]
    assert ("douyin-vertical", "2026-10-10", "12:00") in days and ("douyin-vertical", "2026-10-11", "12:00") in days
    assert sum(1 for p, d, _ in days if p == "douyin-vertical" and d == "2026-10-10") == 2
    rows = open(os.path.join(a["dir"], "schedule.csv"), encoding="utf-8").read().splitlines()
    assert rows[0].startswith("date,time,platform") and len(rows) == 7
    assert os.path.exists(os.path.join(a["dir"], "xiaohongshu-full", "001_j001", "video.mp4"))
    b = package(bdir, per_day=2, start="2026-10-10", times=["12:00", "19:00"])
    assert b["code"] == a["code"]                              # same list -> same code
    c = package(bdir, per_day=1, start="2026-10-10")
    assert c["code"] != a["code"]                              # schedule changed -> new code
    with open(os.path.join(bdir, "jobs", "j002", "export", "douyin-vertical.mp4"), "ab") as f:
        f.write(b"x")
    d = package(bdir, per_day=2, start="2026-10-10", times=["12:00", "19:00"])
    assert d["code"] != a["code"]                              # a file changed -> new code
    st = Store(bdir)
    assert all(j["state"] == "packaged" for j in st.jobs())
    st.close()


def test_clean_purges_and_rebuilds_on_demand(tmp_path):
    bdir, _ = plan_run(tmp_path, jobs_n(2))
    big = os.path.join(bdir, "jobs", "j001", "big", "big.bin")
    assert os.path.exists(big)
    review.apply_decisions(bdir, {"decisions": {"j001": {"decision": "approve"}}})
    r = hygiene.clean(bdir)
    assert r["freed"] >= 200000 and not os.path.exists(big)
    assert os.path.exists(os.path.join(bdir, "jobs", "j002", "big", "big.bin"))   # not finished: kept
    assert os.path.exists(os.path.join(bdir, "jobs", "j001", "big", "big.txt"))   # small files kept
    assert r["usage"]["total"] > 0 and "jobs" in hygiene.format_usage(r["usage"])
    # a later change downstream of the purged stage -> the purged output is rebuilt first
    js = jobs_n(2)
    js[0]["red"] = True
    plan_batch(mkspec(tmp_path, js), echo=False)
    n0 = len(H.calls(bdir))
    assert run_batch(bdir, echo=False)["exit_code"] == 0
    assert sorted(H.calls(bdir)[n0:]) == [("j001", "big"), ("j001", "qc")]


# --------------------------------------------------------------------------- planner / misc
def test_claude_planner_stub_offline(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(planner.PlannerUnavailable):
        planner.ClaudePlanner().rows({"inputs": {}})
    words = [dict(w=f"词{i}", t=i * 2.0, te=i * 2.0 + 0.5) for i in range(1200)]
    reqs = planner.build_requests({"planner_opts": {"chunk_s": 900}}, words)
    assert len(reqs) == 3 and reqs[0]["params"]["model"] == "claude-opus-5-5"
    assert reqs[0]["custom_id"] == "chunk-000" and "Transcript 0.0" in reqs[0]["params"]["messages"][0]["content"]
    rows = planner.parse_reply('Here: {"segments": [{"range": ["1:00", 95], "title": "T", "body": "b"}]}')
    assert rows == [dict(range=[60.0, 95.0], title="T", body="b")]


def test_limits_and_bench_update(tmp_path):
    lim = default_limits(cores=10, mem_gb=32)
    assert lim["asr"] == 1 and lim["cpu-render"] == 3 and lim["cpu"] == 5 and lim["face"] == 2
    # agent runners wait on their model: their lanes do not shrink on a small machine (3 cores -> cpu 1)
    small = default_limits(cores=3, mem_gb=7)
    assert small["cpu"] == 1 and limit_for(small, "agent:fake-agent") == 4 and limit_for(small, "api:kling") == 4
    assert limit_for(small, "ffmpeg") == 1
    assert parse_limits("asr=2, cpu-render=4") == {"asr": 2, "cpu-render": 4}
    bdir, _ = plan_run(tmp_path, jobs_n(1), test=dict(sleep=dict(render=0.05)))
    st = Store(bdir)
    t = EST.bench_table(st)
    assert t["render"]["source"] == "batch" and t["render"]["n"] == 1
    st.close()
    mb = json.load(open(os.environ["VSTUDIO_BATCH_BENCH"]))
    assert mb["render"]["sec_per_unit"] > 0                    # machine table updated for the next batch
