"""Projects from Home and the autopilot, on the desk's side:

* a request is a project the moment it is sent: ``Intake.open()`` lists it while it plans, its job record survives a
  restart, a dropped one is discarded;
* autopilot (the default from Home): the plan is applied at once with ``vstudio.intake apply --autopilot`` and each
  project's run is ``vstudio.project run --autopilot`` (no pilot) - real engine for the apply, a fake ``claude`` CLI
  for the plan; "ask me first" keeps the plan waiting for her Start;
* the run queue: no more than ``DESK_MAX_RUNS`` runs at once, the next one waits in line and starts when one ends;
* ``Autopilot`` (decisions / take one back / switch the mode) over the real ``vstudio.project`` CLI;
* the test engine's simulated autopilot run makes every clip with no question and records its decisions."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _isolate  # noqa: E402,F401

from desk_engine import intake as IN  # noqa: E402
from desk_engine import pilot as P  # noqa: E402
from desk_engine.autopilot import Autopilot  # noqa: E402
from desk_engine.caps import CliRunner  # noqa: E402

ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

FAKE_CLAUDE = r'''#!{python}
import json, sys
sys.stdin.read()
plan = dict(projects=[dict(recipe="talkinghead", name="talk", materials=["f1"], inputs=dict(video=["f1"]),
                           items=dict(method="per-file"))], questions=[], risks=[], summary_zh="ok")
print(json.dumps(dict(type="result", is_error=False, result="", structured_output=plan)))
'''


def rj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def status_of(d):
    p = os.path.join(d, ".vstudio", "status.json")
    return rj(p).get("status") if os.path.exists(p) else None


def wait_for(fn, limit=120, step=0.1):
    t0 = time.time()
    while time.time() - t0 < limit:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timed out")


class RunQueueTest(unittest.TestCase):
    def test_runs_wait_in_line_and_start_when_one_ends(self):
        os.environ["DESK_MAX_RUNS"] = "2"
        try:
            q = P.RunQueue()
            ends, started = {}, []

            def run(name):
                def start(done):
                    started.append(name)
                    ends[name] = done
                return start
            self.assertTrue(q.submit("/tmp/a", run("a")))
            self.assertTrue(q.submit("/tmp/b", run("b")))
            self.assertFalse(q.submit("/tmp/c", run("c")))
            self.assertFalse(q.submit("/tmp/d", run("d")))
            self.assertEqual((q.position("/tmp/c"), q.position("/tmp/d")), (1, 2))
            self.assertFalse(q.submit("/tmp/c", run("c")))          # asked twice: still one place in line
            ends["a"]()
            self.assertEqual(started, ["a", "b", "c"])
            self.assertEqual((q.position("/tmp/c"), q.position("/tmp/d")), (None, 1))
            self.assertTrue(q.cancel("/tmp/d"))
            ends["b"]()
            ends["c"]()
            self.assertEqual(started, ["a", "b", "c"])
            self.assertEqual(q.active, set())
        finally:
            os.environ.pop("DESK_MAX_RUNS", None)

    def test_a_queued_spawn_says_so_and_requeue_puts_it_back(self):
        os.environ["DESK_MAX_RUNS"] = "1"
        tmp = tempfile.mkdtemp(prefix="rq-")
        dirs = [os.path.join(tmp, n) for n in ("one", "two")]
        for d in dirs:
            os.makedirs(d)
        saved = P.QUEUE
        P.QUEUE = P.RunQueue()
        try:
            sleep = [sys.executable, "-c", "import time; time.sleep(0.6)"]
            P.spawn(sys.executable, dict(os.environ), dirs[0], args=sleep)
            rec = P.spawn(sys.executable, dict(os.environ), dirs[1], args=sleep)
            self.assertTrue(rec["queued"])
            self.assertEqual(P.queued(dirs[1]), 1)
            self.assertIsNone(P.failure(dirs[1]))
            wait_for(lambda: P.running(dirs[1]), 10)                 # the first ended: the second started
            self.assertIsNone(P.queued(dirs[1]))
            # the app quit while a run waited in line: at start it goes back in line
            P.QUEUE = P.RunQueue()
            with open(os.path.join(dirs[0], P.REC), "w", encoding="utf-8") as f:
                json.dump(dict(pid=None, queued=True, exit=None, args=sleep[1:]), f)
            self.assertEqual(P.requeue(sys.executable, dict(os.environ), dirs), [dirs[0]])
            wait_for(lambda: P.running(dirs[0]), 10)
        finally:
            P.QUEUE = saved
            os.environ.pop("DESK_MAX_RUNS", None)


@unittest.skipIf(os.name == "nt" or not shutil.which("ffmpeg"), "fake CLI is a script; needs ffmpeg for the video")
class HomeRequestRealEngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="hreq-")
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        exe = os.path.join(bindir, "claude")
        with open(exe, "w", encoding="utf-8") as f:
            f.write(FAKE_CLAUDE.format(python=sys.executable))
        os.chmod(exe, 0o755)
        self.video = os.path.join(tmp, "talk.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=3",
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", self.video], check=True)
        routes = os.path.join(tmp, "llm-routes.json")
        with open(routes, "w", encoding="utf-8") as f:
            json.dump({"default": {"provider": "claude-code"}, "tasks": {"intake": {"provider": "claude-code"}}}, f)
        self.vhome = os.path.join(tmp, "vhome")
        self.env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=self.vhome,
                        VSTUDIO_CACHE=os.path.join(tmp, "cache"), PATH=bindir + os.pathsep + os.environ.get("PATH", ""),
                        VSTUDIO_CLI_EXTRA_DIRS="", VSTUDIO_DEFAULT_PERSONA="1", VSTUDIO_LLM_ROUTES_FILE=routes)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_INTAKE_PROVIDER"):
            self.env.pop(k, None)
        self.data = os.path.join(tmp, "desk")
        self.spawned = []
        self._spawn = P.spawn
        P.spawn = lambda python, env, d, provider=None, bus=None, args=None: self.spawned.append((d, args)) or {}
        os.environ["VSTUDIO_HOME"], self._home = self.vhome, os.environ.get("VSTUDIO_HOME")

    def tearDown(self):
        P.spawn = self._spawn
        os.environ["VSTUDIO_HOME"] = self._home

    def intake(self):
        return IN.Intake(self.data, None, CliRunner(sys.executable, self.env), "real")

    def test_autopilot_request_plans_applies_and_runs_without_a_confirm(self):
        it = self.intake()
        pid = it.start("cut this talk", [self.video], lang="en", mode="autopilot")["id"]
        self.assertEqual([x["id"] for x in it.open()["items"]], [pid])        # listed at once, while it plans
        j = wait_for(lambda: (lambda x: x if x["state"] != "running" else None)(it.get(pid)), 180)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertTrue(j["applied"])
        self.assertEqual(it.open()["items"], [])
        d = j["applied"][0]["dir"]
        import yaml
        with open(os.path.join(d, "project.yaml"), encoding="utf-8") as f:
            self.assertTrue(yaml.safe_load(f)["autopilot"]["on"])
        (sd, args), = self.spawned
        self.assertEqual(sd, d)
        self.assertIn("--autopilot", args)
        self.assertNotIn("--pilot", args)
        self.assertEqual(args[args.index("--lang") + 1], "en")

    def test_ask_first_keeps_the_plan_waiting_and_a_restart_keeps_the_request(self):
        it = self.intake()
        pid = it.start("cut this talk", [self.video], mode="ask")["id"]
        wait_for(lambda: it.get(pid)["state"] == "done", 180)
        self.assertEqual(self.spawned, [])
        row, = it.open()["items"]
        self.assertEqual((row["id"], row["state"], row["mode"], row["name"]), (pid, "done", "ask", "talk"))
        ask, = it.inbox_items()                                                 # the Inbox: "plan ready, start it?"
        self.assertEqual((ask["code"], ask["href"]), ("inbox.planReady", f"#/projects?sel={pid}"))
        again = self.intake()                                                   # the desk restarted
        self.assertEqual([x["id"] for x in again.open()["items"]], [pid])
        self.assertTrue(again.get(pid)["plan"]["projects"])                     # the plan is read back for Start
        again.apply(pid, run=True)
        (_d, args), = self.spawned
        self.assertIn("--pilot", args)
        self.assertNotIn("--autopilot", args)
        self.assertEqual(again.open()["items"], [])
        pid2 = again.start("another", [self.video], mode="ask")["id"]
        wait_for(lambda: again.get(pid2)["state"] == "done", 180)
        again.discard(pid2)
        self.assertEqual(again.open()["items"], [])


class FakeHistory:
    def __init__(self, d):
        self.d = d

    def find(self, item):
        return dict(id=item, dir=self.d, kind="project")


SCRIPT = ("# 第二次更快\n\n## HOOK\n    你把同一个问题问两遍，第二次快了整整十倍。\n\n## INSIGHT\n"
          "    说到底，快只是因为被记住了。\n")


class AutopilotDecisionsRealEngineTest(unittest.TestCase):
    """The desk's decisions / take back / mode over the real ``vstudio.project`` CLI (a script project: cheap)."""

    def test_decisions_reopen_and_mode(self):
        tmp = tempfile.mkdtemp(prefix="apd-")
        env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=os.path.join(tmp, "vhome"),
                   VSTUDIO_LLM_PROVIDER="none")
        d = os.path.join(tmp, "pp")
        cli = [sys.executable, "-m", "vstudio.project"]
        subprocess.run(cli + ["new", "--recipe", "preproduction", "--dir", d, "--episodes", "1", "--json"], env=env,
                       check=True, capture_output=True)
        with open(os.path.join(d, "items", "ep01", "SCRIPT.md"), "w", encoding="utf-8") as f:
            f.write(SCRIPT)
        r = subprocess.run(cli + ["run", "--dir", d, "--autopilot", "--json"], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        spawned = []
        saved = P.spawn
        P.spawn = lambda python, env_, dd, provider=None, bus=None, args=None: spawned.append(args) or {}
        try:
            ap = Autopilot(FakeHistory(d), CliRunner(sys.executable, env))
            doc = ap.get("abcdefabcdef")
            self.assertTrue(doc["supported"] and doc["autopilot"]["on"])
            dec, = doc["decisions"]
            self.assertEqual((dec["checkpoint"], dec["item"], dec["by"], dec["reason_code"]),
                             ("lock", "ep01", "rules", "drafted"))
            out = ap.reopen("abcdefabcdef", "lock", "ep01")
            self.assertTrue(out["ok"] and out["resumed"])
            self.assertIn("resume", spawned[-1])
            self.assertTrue(any(x.get("asked") for x in ap.get("abcdefabcdef")["decisions"]))
            m = ap.mode("abcdefabcdef", False)
            self.assertFalse(m["autopilot"]["on"])
            self.assertFalse(m["resumed"])
            self.assertTrue(ap.mode("abcdefabcdef", True)["autopilot"]["on"])
        finally:
            P.spawn = saved


class MockAutopilotRunTest(unittest.TestCase):
    """The test engine (DESK_ENGINE_MOCK): two requests back to back both become projects and finish every clip with
    no question; the decisions are listed; a third waits in line while two run."""

    def test_two_requests_run_to_done_and_the_third_waits(self):
        from desk_mock.intake import MockIntake, mock_autopilot
        tmp = tempfile.mkdtemp(prefix="mockap-")
        env0 = dict(os.environ)
        os.environ.update(DESK_MOCK_STEP="0.01", DESK_MAX_RUNS="2", VSTUDIO_HOME=os.path.join(tmp, "vh"))
        saved = P.QUEUE
        P.QUEUE = P.RunQueue()
        try:
            video = os.path.join(tmp, "live.mp4")
            with open(video, "w", encoding="utf-8") as f:
                f.write("x")
            it = MockIntake(os.path.join(tmp, "desk"), None, None, "mock")
            ids = [it.start(f"把这条剪成 {n} 条小红书切片", [video], mode="autopilot")["id"] for n in (2, 3, 2)]
            jobs = [wait_for(lambda i=i: (lambda j: j if j.get("applied") else None)(it.get(i)), 30) for i in ids]
            dirs = [j["applied"][0]["dir"] for j in jobs]
            self.assertTrue(any(P.queued(d) for d in dirs))            # two run, the third waits in line
            for d in dirs:
                wait_for(lambda d=d: status_of(d) == "done", 60)
                self.assertFalse(rj(os.path.join(d, ".vstudio", "status.json")).get("needs_you"))
            self.assertEqual(len([f for f in os.listdir(os.path.join(dirs[1], "final")) if f.endswith(".mp4")]), 3)
            self.assertEqual({x["by"] for x in mock_autopilot(dirs[0])["decisions"]}, {"ai", "rules"})
        finally:
            P.QUEUE = saved
            os.environ.clear()
            os.environ.update(env0)


class StopRequestTest(unittest.TestCase):
    def test_a_request_stopped_while_it_plans_makes_nothing(self):
        """Stop in the control room while an autopilot request plans: the late plan never applies (no project, no
        run), and the request leaves the list."""
        from desk_mock.intake import MockIntake
        tmp = tempfile.mkdtemp(prefix="mockstop-")
        env0 = dict(os.environ)
        os.environ.update(DESK_MOCK_STEP="0.2", VSTUDIO_HOME=os.path.join(tmp, "vh"))
        try:
            video = os.path.join(tmp, "live.mp4")
            with open(video, "w", encoding="utf-8") as f:
                f.write("x")
            it = MockIntake(os.path.join(tmp, "desk"), None, None, "mock")
            pid = it.start("剪 2 条切片", [video], mode="autopilot")["id"]
            time.sleep(0.1)
            it.stop(pid)
            time.sleep(2.5)                                       # the simulated plan would have been ready by now
            j = it.get(pid)
            self.assertEqual(j["state"], "stopped")
            self.assertFalse(j.get("applied"))
            self.assertEqual(it.open()["items"], [])
            self.assertFalse(os.path.exists(os.path.join(tmp, "vh", "projects")))
        finally:
            os.environ.clear()
            os.environ.update(env0)


if __name__ == "__main__":
    unittest.main()
