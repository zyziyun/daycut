"""Requests from Home that used to trap her (0.2.3: "Couldn't make a plan · Something went wrong", Start over led back
to the same failure):

* a request with no files is planned from its words (real ``vstudio.intake``, no model: the rule planner) - never
  "PlanError: no inputs";
* one that cuts footage but has none, or names her Notion with nothing to read, waits for her (state ``needs``: All
  projects + an Inbox item, nothing applied or run); ``add`` (files / links) plans it again, ``go_on`` plans it
  without;
* a failure keeps its own reason code (``plan-empty``, ``ai-timeout`` ...) instead of "exited 1";
* a request that was planning when the app quit is a failure she can try again after the restart (Home stays free:
  it never shows requests)."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _isolate  # noqa: E402,F401

from desk_engine import intake as IN  # noqa: E402
from desk_engine import pilot as P  # noqa: E402
from desk_engine.caps import CliRunner  # noqa: E402

ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def wait_for(fn, limit=120, step=0.1):
    t0 = time.time()
    while time.time() - t0 < limit:
        v = fn()
        if v:
            return v
        time.sleep(step)
    raise AssertionError("timed out")


class TextOnlyAndNeedsRealEngineTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="hneeds-")
        self.video = os.path.join(tmp, "talk.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=3",
                        "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", self.video], check=True)
        self.vhome = os.path.join(tmp, "vhome")
        self.env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=self.vhome,
                        VSTUDIO_CACHE=os.path.join(tmp, "cache"), VSTUDIO_CLI_EXTRA_DIRS="",
                        VSTUDIO_DEFAULT_PERSONA="1", VSTUDIO_LLM_PROVIDER="none", VSTUDIO_LLM_INTAKE_PROVIDER="none")
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            self.env.pop(k, None)
        self.data = os.path.join(tmp, "desk")
        self.spawned = []
        self._spawn = P.spawn
        P.spawn = lambda python, env, d, provider=None, bus=None, args=None: self.spawned.append((d, args)) or {}
        os.environ["VSTUDIO_HOME"], self._home = self.vhome, os.environ.get("VSTUDIO_HOME")

    def tearDown(self):
        P.spawn = self._spawn
        if self._home is None:
            os.environ.pop("VSTUDIO_HOME", None)
        else:
            os.environ["VSTUDIO_HOME"] = self._home

    def intake(self):
        return IN.Intake(self.data, None, CliRunner(sys.executable, self.env), "real")

    def settled(self, it, pid):
        return wait_for(lambda: (lambda j: j if j["state"] != "running" else None)(it.get(pid)), 180)

    def test_words_only_is_planned_not_failed(self):
        it = self.intake()
        pid = it.start("做一期时间管理的科普视频", [], mode="ask")["id"]
        j = self.settled(it, pid)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertEqual([p["recipe"] for p in j["plan"]["projects"]], ["explainer"])
        self.assertFalse(j["plan"].get("needs"))

    def test_footage_request_waits_for_the_recordings_then_runs(self):
        it = self.intake()
        pid = it.start("把这条口播剪干净，去气口", [], mode="autopilot")["id"]
        j = self.settled(it, pid)
        self.assertEqual(j["state"], "needs", j.get("error"))
        self.assertEqual([n["code"] for n in j["needs"]], ["intake.need.footage"])
        self.assertFalse(j.get("applied"))
        self.assertEqual(self.spawned, [])                                  # nothing made, nothing run
        row, = it.open()["items"]
        self.assertEqual((row["state"], row["needs"][0]["code"]), ("needs", "intake.need.footage"))
        item, = it.inbox_items()
        self.assertEqual((item["kind"], item["code"], item["need"]["code"], item["href"]),
                         ("needs", "inbox.planNeeds", "intake.need.footage", f"#/projects?sel={pid}"))
        again = self.intake()                                               # it waits across a restart too
        self.assertEqual(again.get(pid)["state"], "needs")
        again.add(pid, [self.video])
        j = self.settled(again, pid)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertTrue(j["applied"])
        self.assertEqual(j["inputs"], [self.video])
        self.assertEqual(len(self.spawned), 1)
        self.assertEqual(again.open()["items"], [])

    def test_her_notion_waits_for_the_pages_and_can_go_on_without(self):
        it = self.intake()
        pid = it.start("阅读我的notion，尝试做一下有丰富交互的科普经验类视频，做ip", [], mode="ask")["id"]
        j = self.settled(it, pid)
        self.assertEqual((j["state"], j["needs"][0]["code"]), ("needs", "intake.need.notion"))
        self.assertEqual([p["recipe"] for p in j["plan"]["projects"]], ["explainer"])   # what it would make
        notes = os.path.join(os.path.dirname(self.video), "Notion export")
        os.makedirs(notes)
        with open(os.path.join(notes, "IP 计划.md"), "w", encoding="utf-8") as f:
            f.write("# IP 计划\n\n## 第一期：提示词\n\n提示词就是合同。\n\n## 第二期：三个误区\n\n别把模型当搜索引擎。\n")
        it.add(pid, [notes])
        j = self.settled(it, pid)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertFalse(j["plan"].get("needs"))
        self.assertEqual(j["plan"]["materials"][0]["kind"], "text")
        pid2 = it.start("读我的 Notion 做科普", [], mode="ask")["id"]
        self.assertEqual(self.settled(it, pid2)["state"], "needs")
        it.go_on(pid2)
        j = self.settled(it, pid2)
        self.assertEqual(j["state"], "done", j.get("error"))
        self.assertFalse(j["plan"].get("needs"))

    def test_a_failure_keeps_its_reason_code(self):
        it = self.intake()
        pid = it.start(" ", [], mode="autopilot")["id"]
        j = self.settled(it, pid)
        self.assertEqual((j["state"], j["error_code"]), ("error", "plan-empty"))
        self.assertIn("nothing to plan", j["error"])
        item, = it.inbox_items()
        self.assertEqual((item["kind"], item["error_code"]), ("failed", "plan-empty"))


class StaleRequestAfterRestartTest(unittest.TestCase):
    def test_a_plan_that_was_running_when_the_app_quit_is_a_failure_to_try_again(self):
        from desk_mock.intake import MockIntake
        tmp = tempfile.mkdtemp(prefix="stale-")
        env0 = dict(os.environ)
        os.environ.update(DESK_MOCK_STEP="0.05", VSTUDIO_HOME=os.path.join(tmp, "vh"))
        try:
            data = os.path.join(tmp, "desk")
            os.makedirs(os.path.join(data, "intake"))
            pid = "7d25b0d015f4"
            with open(os.path.join(data, "intake", f"{pid}.job.json"), "w", encoding="utf-8") as f:
                json.dump(dict(id=pid, state="running", step="plan", prompt="做一期时间管理科普", inputs=[],
                               started=time.time() - 60, mode="ask"), f)
            it = MockIntake(data, None, None, "mock")
            row, = it.open()["items"]
            self.assertEqual((row["state"], row["error_code"]), ("error", "stopped"))
            it.retry(pid)
            j = wait_for(lambda: (lambda x: x if x["state"] != "running" else None)(it.get(pid)), 30)
            self.assertEqual(j["state"], "done", j.get("error"))
            it.discard(pid)                                       # Start over: it is gone, nothing was made
            self.assertEqual(it.open()["items"], [])
        finally:
            os.environ.clear()
            os.environ.update(env0)

    def test_the_test_engines_planner_timeout_is_a_coded_failure(self):
        from desk_mock.intake import MockIntake
        tmp = tempfile.mkdtemp(prefix="mockfail-")
        env0 = dict(os.environ)
        os.environ.update(DESK_MOCK_STEP="0.05", DESK_MOCK_PLAN_FAIL="1", VSTUDIO_HOME=os.path.join(tmp, "vh"))
        MockIntake._plan_fails = 0
        try:
            it = MockIntake(os.path.join(tmp, "desk"), None, None, "mock")
            pid = it.start("做一期时间管理科普", [], mode="ask")["id"]
            j = wait_for(lambda: (lambda x: x if x["state"] != "running" else None)(it.get(pid)), 30)
            self.assertEqual((j["state"], j["error_code"], j["error_provider"]), ("error", "ai-timeout", "claude-code"))
            it.retry(pid)
            j = wait_for(lambda: (lambda x: x if x["state"] not in ("running", "error") else None)(it.get(pid)), 30)
            self.assertEqual(j["state"], "done")
        finally:
            MockIntake._plan_fails = 0
            os.environ.clear()
            os.environ.update(env0)


if __name__ == "__main__":
    unittest.main()
