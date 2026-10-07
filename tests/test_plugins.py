"""vstudio.plugins: the registry (built-ins, folder plugins, entry points, on / off, broken manifests), the providers
registering through it (incl. a paid third-party provider priced by its own rates -> spend gate), the HyperFrames
importer + renderer (fixture project, fake CLI), generic shot lists / EDL / OTIO / XML, boards -> series /
episodes, and agent runners with fake CLIs in parallel lanes (concurrency, heartbeat, QC, timeout, stop, resume,
paid refused). Nothing real is called: fake CLIs only, temp VSTUDIO_HOME."""
import json
import os
import shutil
import stat
import subprocess
import textwrap
import time

import pytest

from _create_helpers import ROOT, home, needs_ffmpeg  # noqa: F401

from vstudio.create import costs, jobs, providers as PR, routing, store, views
from vstudio.create.i18n import CreateError
from vstudio.plugins import board as B, importing as IM, jobfolder as JF, lanes as L, registry as R
from vstudio.plugins.builtin import hyperframes as HF, shotlist as SL, timeline as TL

FIX = ROOT / "tests" / "fixtures" / "plugins" / "hyperframes-tiny"


@pytest.fixture
def plugdir(tmp_path, monkeypatch):
    d = tmp_path / "plugs"
    d.mkdir()
    monkeypatch.setenv("VSTUDIO_PLUGINS_PATH", str(d))
    R.discover(refresh=True)
    yield d
    R.discover(refresh=True)


def _exe(path, body):
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body).lstrip())
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def _plugin(plugdir, name, manifest, files=None):
    d = plugdir / name
    d.mkdir()
    (d / "plugin.yaml").write_text(manifest)
    for fn, body in (files or {}).items():
        _exe(d / fn, body)
    R.discover(refresh=True)
    return d


# ------------------------------------------------------------------------------------------------- registry
def test_builtins_listed_valid_and_on(home, plugdir):
    rows = R.discover(refresh=True)
    keys = {r["key"] for r in rows}
    for k in ("shot-provider:kling-mcp", "shot-provider:minimax", "shot-provider:veo", "shot-provider:jimeng",
              "shot-provider:seedance-ark", "shot-provider:hyperframes", "importer:hyperframes", "importer:shotlist",
              "importer:timeline", "agent-runner:claude-code", "agent-runner:codex", "agent-runner:shell"):
        assert k in keys, k
    assert not [r for r in rows if r["error"]]
    assert all(R.is_enabled(r) for r in rows if r["origin"] == "builtin")
    paid = {r["id"] for r in rows if r["cost"]["kind"] == "paid"}
    assert {"kling-mcp", "minimax", "veo", "seedance-ark"} <= paid
    assert all("spend" in r["permissions"] for r in rows if r["cost"]["kind"] == "paid")
    lst = R.listing()
    assert lst["api"] == 1 and all("_m" not in p for p in lst["plugins"])


def test_folder_plugin_starts_off_then_on(home, plugdir):
    _plugin(plugdir, "mine", "id: mine\nkind: agent-runner\nname: Mine\nversion: 0.1.0\napi: 1\n"
                             "command: [./run, '{job_dir}']\npermissions: [write-job, 'exec:run']\n",
            {"run": "exit 0\n"})
    row = R.find("agent-runner:mine")
    assert row["origin"] == "folder" and not R.is_enabled(row)
    with pytest.raises(R.PluginError) as ei:
        R.instance("agent-runner:mine")
    assert ei.value.code == "create.plugin.disabled"
    R.set_enabled("agent-runner:mine", True)
    assert R.is_enabled(R.find("agent-runner:mine"))
    assert R.instance("agent-runner:mine").status()["ready"]
    assert json.load(open(R.state_path()))["enabled"]["agent-runner:mine"] is True


def test_broken_manifests_are_listed_not_loaded(home, plugdir):
    _plugin(plugdir, "future", "id: future\nkind: importer\nversion: 1\napi: 99\ncommand: [x]\n")
    _plugin(plugdir, "greedy", "id: greedy\nkind: agent-runner\nversion: 1\napi: 1\ncommand: [x]\ncost: {kind: paid}\n")
    _plugin(plugdir, "dupe", "id: shotlist\nkind: importer\nversion: 1\napi: 1\ncommand: [x]\n")
    (plugdir / "junk").mkdir()
    (plugdir / "junk" / "plugin.yaml").write_text("id: [unclosed\n")
    rows = {(r["id"], r["origin"]): r for r in R.discover(refresh=True)}
    assert "api" in rows[("future", "folder")]["error"]
    assert "spend" in rows[("greedy", "folder")]["error"]
    assert "duplicate" in rows[("shotlist", "folder")]["error"]
    assert "plugin.yaml" in rows[("junk", "folder")]["error"]
    assert rows[("shotlist", "builtin")]["error"] is None                     # the built-in still wins
    with pytest.raises(R.PluginError):
        R.set_enabled("importer:future", True)


def test_entry_point_plugins(home, plugdir, monkeypatch):
    import importlib.metadata as md

    class EP:
        name, value, dist = "acme", "acme_plugins:manifests", None

        def load(self):
            return lambda: [dict(id="acme-board", kind="importer", version="2.0", api=1,
                                 entry="vstudio.plugins.builtin.shotlist:ShotListImporter")]
    monkeypatch.setattr(md, "entry_points", lambda group=None: [EP()] if group == R.GROUP else [])
    R.discover(refresh=True)
    row = R.find("importer:acme-board")
    assert row["origin"] == "package" and not R.is_enabled(row) and row["error"] is None


def test_providers_register_through_the_registry(home, plugdir):
    ids = [p["id"] for p in PR.list_info()]
    assert ids[:5] == ["kling-mcp", "minimax", "jimeng", "veo", "seedance-ark"]
    assert "hyperframes" not in ids                                             # render providers go to `make`
    R.set_enabled("shot-provider:minimax", False)
    assert "minimax" not in [p["id"] for p in PR.list_info()]
    R.set_enabled("shot-provider:minimax", True)


def test_paid_third_party_provider_goes_through_the_spend_gate(home, plugdir, monkeypatch):
    d = _plugin(plugdir, "acme", textwrap.dedent("""\
        id: acme-video
        kind: shot-provider
        version: 1.0.0
        api: 1
        entry: acme_provider:Acme
        permissions: [network, spend]
        cost: {kind: paid}
        rates:
          acme-1: {label: Acme 1, unit: second, cny_per_s: 2.0, min_clip_s: 2, max_clip_s: 10, step_s: 1}
        """))
    (d / "acme_provider.py").write_text(textwrap.dedent("""\
        from vstudio.create.providers.base import Provider
        class Acme(Provider):
            info = dict(id="acme-video", label={"en": "Acme"}, kind="cloud", needs=["ACME_KEY"], models=["acme-1"],
                        concurrency=2)
        """))
    R.set_enabled("shot-provider:acme-video", True)
    assert "acme-video" in [p["id"] for p in PR.list_info()]
    assert costs.entry("acme-video", "acme-1")["cny_per_s"] == 2.0
    assert costs.price_job("acme-video", "acme-1", 3)["cny"] == 6.0
    from _create_helpers import sample_episode
    sid, eid = sample_episode()
    jobs.set_source(eid, "02", "cloud:acme-video/acme-1")
    est = jobs.estimate(eid, "finals")
    line = next(ln for ln in est["lines"] if ln["provider"] == "acme-video")
    assert line["cny"] > 0 and "02" in line["shots"] and est["confirm_code"]
    with pytest.raises(CreateError):                                            # no confirm code -> nothing runs
        jobs.run(eid, "finals")


# ------------------------------------------------------------------------------------------------- HyperFrames
def test_hyperframes_storyboard_parse_and_import(home, plugdir):
    imp = HF.HyperFramesImporter()
    assert imp.sniff(str(FIX)) > 0.9 and imp.sniff(str(FIX / "STORYBOARD.md")) > 0.9
    assert imp.sniff(str(ROOT / "tests")) == 0
    b = B.normalize(imp.load(str(FIX)), importer="hyperframes")
    assert b["title"] == "Matcha teaser" and b["aspect"] == "9:16"
    assert b["message"].startswith("Matcha in three beats")
    assert [s["dur"] for s in b["shots"]] == [3.1, 4.1, 3.0]                 # built clips win over the plan
    assert [s.get("source") for s in b["shots"]] == ["plugin:hyperframes", "plugin:hyperframes", None]
    s1 = b["shots"][0]
    assert s1["voiceover"] == "Whisk it fast." and s1["transition"] == "cut"
    assert s1["ref"]["src"] == "compositions/f01-whisk.html" and "motion: kinetic-type-beats" in s1["notes"]
    assert "Open on motion" in s1["notes"]


def test_hyperframes_index_only_project(home, plugdir, tmp_path):
    p = tmp_path / "hf"
    shutil.copytree(FIX, p)
    os.remove(p / "STORYBOARD.md")
    b = B.normalize(HF.HyperFramesImporter().load(str(p)))
    assert [s["dur"] for s in b["shots"]] == [3.1, 4.1] and b["shots"][1]["ref"]["src"] == "compositions/f02-pour.html"


def test_import_board_into_new_series_then_make_with_render(home, plugdir, tmp_path):
    proj = tmp_path / "hf"
    shutil.copytree(FIX, proj)
    r = IM.into_new_series(str(proj))
    assert r["n"] == 3 and r["importer"] == "hyperframes"
    v = views.episode_view(r["episode"])
    assert [s["route"]["kind"] for s in v["shots"]][:2] == ["plugin", "plugin"]
    assert v["next"] == dict(step="make", n=2) and all(s.get("still") for s in v["shots"])
    assert v["estimate"]["free"].get("plugin") == 2
    assert any(o["source"] == "plugin:hyperframes" for o in v["shots"][0]["options"])
    # no HyperFrames CLI in the project: the shots wait for a file you render yourself
    m = L.make(r["episode"])
    assert {u["state"] for u in m["units"].values()} == {"manual-waiting"}
    assert m["units"]["01"]["code"] == "create.plugin.external"
    row = next(x for x in views.making()["rows"] if x["id"] == r["episode"])
    assert len(row["make"]["waiting"]) == 2 and [c["state"] for c in row["cells"]][:2] == ["you", "you"]


@needs_ffmpeg
def test_hyperframes_render_with_the_projects_cli_and_resume(home, plugdir, tmp_path):
    proj = tmp_path / "hf"
    shutil.copytree(FIX, proj)
    bin_ = proj / "node_modules" / ".bin"
    bin_.mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    _exe(bin_ / "hyperframes", f"""\
        echo "$@" >> {calls}
        out=""; while [ $# -gt 0 ]; do [ "$1" = "--output" ] && out="$2"; shift; done
        ffmpeg -v error -y -f lavfi -i color=c=green:s=108x192:d=0.4 -pix_fmt yuv420p "$out"
        """)
    r = IM.into_new_series(str(proj))
    m = L.make(r["episode"])
    assert m["units"]["01"]["state"] == "done" and m["units"]["02"]["state"] == "done", m
    ep = store.load_episode(r["episode"])
    assert len(ep["takes"]["01"]) == 1 and ep["picks"]["01"].endswith("takes/u01_v1.mp4")
    assert "--composition compositions/f01-whisk.html" in calls.read_text()
    st = JF.status(m["units"]["01"]["dir"])
    assert st["state"] == "done" and st["progress"] == 1
    n = len(calls.read_text().splitlines())
    L.make(r["episode"])                                                        # resume: done shots are not redone
    assert len(calls.read_text().splitlines()) == n
    assert views.episode_view(r["episode"])["next"]["step"] != "make"


# ------------------------------------------------------------------------------------------------- shot lists
def test_shotlist_json_csv_markdown(home, plugdir, tmp_path):
    j = tmp_path / "s.json"
    j.write_text(json.dumps({"title": "Spot", "aspect": "1080x1920", "shots": [
        {"Duration": "2.5s", "Description": "Cup on table", "VO": "Morning.", "Camera": "close"},
        {"seconds": 3, "visual": "Pour", "source": "agent:codex"}]}))
    b = IM.read(str(j))
    assert b["title"] == "Spot" and b["shots"][0] == dict(dur=2.5, action="Cup on table", voiceover="Morning.",
                                                          camera="close")
    assert b["shots"][1]["source"] == "agent:codex" and b["source"]["importer"] == "shotlist"
    c = tmp_path / "s.csv"
    c.write_text("镜头,时长,画面,台词\n1,2,手持杯子,早上好\n2,4,倒茶,\n")
    b = IM.read(str(c))
    assert [s["dur"] for s in b["shots"]] == [2.0, 4.0] and b["shots"][0]["voiceover"] == "早上好"
    md = tmp_path / "s.md"
    md.write_text("# Teaser\n\n| Shot | Duration | Action | Dialogue |\n|---|---|---|---|\n| 1 | 2s | Door opens | Hi |\n"
                  "| 2 | 3s | Walk in | |\n")
    b = IM.read(str(md))
    assert b["title"] == "Teaser" and [s["action"] for s in b["shots"]] == ["Door opens", "Walk in"]
    md2 = tmp_path / "list.md"
    md2.write_text("1. (3s) Close-up of the cup — \"Morning.\"\n2. (2s) Steam rises\n")
    b = IM.read(str(md2))
    assert b["shots"][0] == dict(dur=3.0, action="Close-up of the cup", voiceover="Morning.")


def test_timelines_edl_otio_xml(home, plugdir, tmp_path):
    e = tmp_path / "cut.edl"
    e.write_text("TITLE: Promo cut\nFCM: NON-DROP FRAME\n\n"
                 "001  AX       V     C        00:00:10:00 00:00:12:12 01:00:00:00 01:00:02:12\n"
                 "* FROM CLIP NAME: wide_shot.mov\n* COMMENT: hero\n"
                 "002  AX       V     C        00:00:00:00 00:00:03:00 01:00:02:12 01:00:05:12\n"
                 "* FROM CLIP NAME: close.mov\n")
    b = IM.read(str(e))
    assert b["title"] == "Promo cut" and [s["dur"] for s in b["shots"]] == [2.48, 3.0]
    assert b["shots"][0]["action"] == "wide_shot.mov" and b["shots"][0]["notes"] == "hero"
    o = tmp_path / "t.otio"
    rt = lambda v: {"OTIO_SCHEMA": "RationalTime.1", "value": v, "rate": 24}  # noqa: E731
    o.write_text(json.dumps({"OTIO_SCHEMA": "Timeline.1", "name": "OT", "tracks": {"OTIO_SCHEMA": "Stack.1", "children": [
        {"OTIO_SCHEMA": "Track.1", "kind": "Video", "children": [
            {"OTIO_SCHEMA": "Clip.2", "name": "a", "source_range": {"start_time": rt(0), "duration": rt(48)}},
            {"OTIO_SCHEMA": "Gap.1", "source_range": {"start_time": rt(0), "duration": rt(12)}},
            {"OTIO_SCHEMA": "Clip.2", "name": "b", "source_range": {"start_time": rt(0), "duration": rt(36)},
             "markers": [{"name": "beat", "comment": "drop"}]}]}]}}))
    b = IM.read(str(o))
    assert [(s["action"], s["dur"]) for s in b["shots"]] == [("a", 2.0), ("b", 1.5)] and "drop" in b["shots"][1]["notes"]
    x = tmp_path / "prem.xml"
    x.write_text('<?xml version="1.0"?><xmeml version="4"><sequence><name>Seq</name><rate><timebase>25</timebase></rate>'
                 '<media><video><track><clipitem><name>one</name><start>0</start><end>50</end></clipitem>'
                 '<clipitem><name>two</name><start>50</start><end>125</end></clipitem></track></video></media>'
                 '</sequence></xmeml>')
    assert [(s["action"], s["dur"]) for s in IM.read(str(x))["shots"]] == [("one", 2.0), ("two", 3.0)]
    f = tmp_path / "p.fcpxml"
    f.write_text('<?xml version="1.0"?><fcpxml version="1.10"><library><event><project name="FX"><sequence><spine>'
                 '<asset-clip name="c1" duration="2002/1000s"/><gap duration="1s"/><asset-clip name="c2" duration="3s"/>'
                 '</spine></sequence></project></event></library></fcpxml>')
    b = IM.read(str(f))
    assert b["title"] == "FX" and [(s["action"], s["dur"]) for s in b["shots"]] == [("c1", 2.0), ("c2", 3.0)]


def test_unknown_and_empty_boards(home, plugdir, tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"\0\1")
    with pytest.raises(CreateError) as ei:
        IM.read(str(p))
    assert ei.value.code == "create.import.unknown-format"
    e = tmp_path / "e.json"
    e.write_text("[]")
    with pytest.raises(CreateError) as ei:
        IM.read(str(e))
    assert ei.value.code == "create.import.empty"


def test_import_into_existing_episode_replaces_board_keeps_old_takes(home, plugdir, tmp_path):
    from _create_helpers import sample_episode
    sid, eid = sample_episode()
    ep = store.load_episode(eid)
    ep["takes"] = {"01": [dict(file="/x/u01_v1.mp4")]}
    store.save_episode(ep)
    j = tmp_path / "b.json"
    j.write_text(json.dumps([{"dur": 2, "action": "A"}, {"dur": 3, "action": "B", "source": "agent:shell"}]))
    r = IM.into_episode(eid, str(j))
    ep = store.load_episode(eid)
    assert r["n"] == 2 and [s["no"] for s in ep["shots"]] == ["01", "02"] and ep["takes"] == {}
    assert ep["takes_archive"][0]["takes"]["01"][0]["file"] == "/x/u01_v1.mp4"
    assert ep["shots"][1]["source"] == "agent:shell"


# ------------------------------------------------------------------------------------------------- agent runners
AGENT = """\
    # fake agent CLI: record start / end, write an output (or not) depending on the mode file
    d="$1"; mode=$(cat "{mode}" 2>/dev/null || echo ok)
    now() {{ python3 -c 'import time; print("%.3f" % time.time())'; }}
    echo "start $(now) $REELFOLD_SHOT" >> "{log}"
    case "$mode" in
      fail) echo "boom on purpose" >&2; exit 3 ;;
      empty) exit 0 ;;
      hang) sleep 30 ;;
    esac
    printf '{{"progress": 0.5, "message": "drawing"}}' > "$d/status.json"
    sleep 0.6
    ffmpeg -v error -y -f lavfi -i color=c=red:s=64x112:d=0.3 -pix_fmt yuv420p "$d/outputs/take.mp4"
    echo "end $(now) $REELFOLD_SHOT" >> "{log}"
"""


def _agent_series(home, plugdir, tmp_path, n=4, timeout=60, cost="local", conc=2):
    log = tmp_path / "agent.log"
    _plugin(plugdir, "fake-agent", textwrap.dedent(f"""\
        id: fake-agent
        kind: agent-runner
        name: Fake agent
        version: 0.1.0
        api: 1
        command: [./agent, "{{job_dir}}"]
        permissions: [write-job, "exec:agent"{', spend' if cost == 'paid' else ''}]
        cost: {{kind: {cost}}}
        concurrency: {conc}
        timeout_s: {timeout}
        """), {"agent": AGENT.format(log=log, mode=tmp_path / "mode")})
    R.set_enabled("agent-runner:fake-agent", True)
    j = tmp_path / "board.json"
    j.write_text(json.dumps([{"dur": 2, "action": f"shot {i}", "source": "agent:fake-agent"} for i in range(n)]))
    r = IM.into_new_series(str(j))
    return r["episode"], log


def _set_mode(tmp_path, mode):
    (tmp_path / "mode").write_text(mode)


@needs_ffmpeg
def test_agent_runner_parallel_lanes_takes_heartbeat(home, plugdir, tmp_path):
    eid, log = _agent_series(home, plugdir, tmp_path, n=4, conc=2)
    seen = []
    m = L.make(eid, on_event=seen.append)
    assert m["lanes"] == {"fake-agent": 2}
    assert {u["state"] for u in m["units"].values()} == {"done"}, m
    ev = []
    for ln in log.read_text().splitlines():
        kind, ts, _ = ln.split()
        ev.append((float(ts), 1 if kind == "start" else -1))
    live = peak = 0
    for _, d in sorted(ev):
        live += d
        peak = max(peak, live)
    assert peak == 2                                                            # 2 lanes, never more
    ep = store.load_episode(eid)
    assert all(len(ep["takes"][no]) == 1 and ep["picks"][no] for no in ("01", "02", "03", "04"))
    d = m["units"]["01"]["dir"]
    assert os.path.exists(os.path.join(d, "brief.md")) and json.load(open(os.path.join(d, "job.json")))["schema"] == JF.SCHEMA
    st = JF.status(d)
    assert st["state"] == "done" and st["heartbeat"] >= st["started"] and st["exit_code"] == 0
    assert any(e.get("stage") == "make" and e.get("state") == "done" for e in seen)
    assert views.episode_view(eid)["next"]["step"] != "make"


@needs_ffmpeg
def test_agent_failures_qc_and_retry(home, plugdir, tmp_path):
    eid, _ = _agent_series(home, plugdir, tmp_path, n=2)
    _set_mode(tmp_path, "fail")
    m = L.make(eid, lanes=1)
    assert m["units"]["01"]["state"] == "failed" and m["units"]["01"]["code"] == "create.agent.failed"
    assert "boom" in m["units"]["01"]["params"]["error"]
    _set_mode(tmp_path, "empty")
    m = L.make(eid)
    assert m["units"]["01"]["code"] == "create.agent.qc-no-output"
    row = next(x for x in views.making()["rows"] if x["id"] == eid)
    assert [f["code"] for f in row["make"]["failed"]] == ["create.agent.qc-no-output"] * 2
    _set_mode(tmp_path, "ok")                                                       # a plain re-run retries them
    m = L.make(eid)
    assert {u["state"] for u in m["units"].values()} == {"done"}


def test_agent_timeout_and_stop(home, plugdir, tmp_path):
    eid, _ = _agent_series(home, plugdir, tmp_path, n=1, timeout=1)
    _set_mode(tmp_path, "hang")
    t0 = time.time()
    m = L.make(eid)
    assert time.time() - t0 < 10
    assert m["units"]["01"]["code"] == "create.agent.timeout"
    R.set_settings("agent-runner:fake-agent", {"timeout_s": 60})
    import threading
    res = {}
    th = threading.Thread(target=lambda: res.update(L.make(eid)))
    th.start()
    time.sleep(1.5)
    jobs.stop(eid)
    th.join(15)
    assert not th.is_alive() and res["units"]["01"]["state"] == "stopped" and res["state"] == "stopped"


def test_paid_runner_refused_and_nothing_to_make(home, plugdir, tmp_path):
    eid, log = _agent_series(home, plugdir, tmp_path, n=1, cost="paid")
    m = L.make(eid)
    assert m["units"]["01"]["code"] == "create.plugin.paid-needs-gate" and not log.exists()
    from _create_helpers import sample_episode
    _, eid2 = sample_episode()
    with pytest.raises(CreateError) as ei:
        L.make(eid2)
    assert ei.value.code == "create.make.nothing"


def test_disabled_runner_is_reported(home, plugdir, tmp_path):
    eid, log = _agent_series(home, plugdir, tmp_path, n=1)
    R.set_enabled("agent-runner:fake-agent", False)
    m = L.make(eid)
    assert m["units"]["01"]["code"] == "create.plugin.disabled" and not log.exists()


def test_builtin_cli_runners_command_shape(home, plugdir, tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    _exe(bin_ / "claude", "exit 0\n")
    _exe(bin_ / "codex", "exit 0\n")
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-never-passed")
    job = dict(dir=str(tmp_path / "job"), shot="01", episode="e")
    cc = R.instance("agent-runner:claude-code")
    cmd = cc.command(job)
    assert cmd[0] == str(bin_ / "claude") and "-p" in cmd and cmd[cmd.index("--permission-mode") + 1] == "acceptEdits"
    assert "npx" not in " ".join(cmd) and "ANTHROPIC_API_KEY" not in cc.env(job)
    cx = R.instance("agent-runner:codex")
    cmd = cx.command(job)
    assert cmd[:3] == [str(bin_ / "codex"), "exec", "--sandbox"] and "workspace-write" in cmd and job["dir"] in cmd


def test_routing_accepts_plugin_and_agent_sources(home, plugdir):
    assert routing.parse("agent:claude-code") == dict(source="agent:claude-code", kind="agent", provider="claude-code",
                                                      model=None)
    assert routing.parse("plugin:hyperframes")["kind"] == "plugin"
    for bad in ("agent:", "agent:Bad", "plugin:x/y", "agent:../x"):
        with pytest.raises(CreateError):
            routing.check_source(bad)


def test_cli_plugins_and_import(home, plugdir, capsys):
    from vstudio.create import cli
    assert cli.main(["--json", "plugins"]) == 0
    d = json.loads(capsys.readouterr().out)
    assert any(p["key"] == "importer:hyperframes" for p in d["plugins"])
    assert cli.main(["--json", "import", str(FIX), "--sniff"]) == 0
    assert json.loads(capsys.readouterr().out)["importers"][0]["id"] == "hyperframes"
    assert cli.main(["--json", "plugins", "disable", "importer:hyperframes"]) == 0
    capsys.readouterr()
    assert cli.main(["--json", "import", str(FIX), "--sniff"]) == 0
    assert json.loads(capsys.readouterr().out)["importers"] == []
    assert cli.main(["--json", "plugins", "enable", "importer:nope"]) == 2
    assert "plugin.not-found" in capsys.readouterr().out


def test_job_folder_outputs_ignore_escapes(tmp_path):
    d = tmp_path / "job"
    (d / "outputs").mkdir(parents=True)
    (d / "outputs" / "a.png").write_bytes(b"png")
    (tmp_path / "secret.mp4").write_bytes(b"x")
    (d / "outputs" / "result.json").write_text(json.dumps({"files": ["../../secret.mp4", "a.png"]}))
    assert JF.outputs(str(d)) == [os.path.realpath(d / "outputs" / "a.png")]
    ok, files, code = JF.qc(str(d))
    assert ok and len(files) == 1


def test_seconds_parsing():
    assert B.seconds("~12s") == 12 and B.seconds("0:04") == 4 and B.seconds("1.5 秒") == 1.5 and B.seconds("x") is None
    assert B.aspect_of("1080x1920") == "9:16" and B.aspect_of("1920×1080") == "16:9"
