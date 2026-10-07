"""Create Plan against the REAL engine (python -m vstudio.create in a subprocess, like the packaged app), in a fresh
temp profile: the bug where "Series ad, ¥60, Douyin/XHS +2 -> Plan" sat on "Planning…" forever.

AI set up the way hers is (Claude Code subscription, Codex fallback) with fake CLIs: claude hangs (an expired
login drags on), codex fails -> the job ends on its own with create.ai-failed and visible steps (Retry); "Start from
the template" (mode=template, labelled, no AI) -> a saved series; no AI set up -> a clear create.ai-failed
not-set-up at once (never a silent swap); a stuck engine process -> the sidecar's watchdog."""
import os
import stat
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _isolate  # noqa: E402,F401

ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

from desk_engine.caps import CliRunner  # noqa: E402
from desk_engine.common import EventBus  # noqa: E402
from desk_engine.create import CreateApi  # noqa: E402

HER_BODY = {"format": "series-ad", "budget_cny": 60, "lang": "zh",
            "platforms": ["douyin", "xiaohongshu:full", "tiktok", "youtube-shorts"]}


def _exe(path, body):
    with open(path, "w") as f:
        f.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


class PlanRealEngineTest(unittest.TestCase):
    def make(self, ai=True, timeout="1", deadline="3"):
        tmp = tempfile.mkdtemp(prefix="cplan-")
        bindir = os.path.join(tmp, "bin")
        os.makedirs(bindir)
        _exe(os.path.join(bindir, "claude"), "sleep 30")                     # an expired login that never answers
        _exe(os.path.join(bindir, "codex"), "echo 'stream error: 503 upstream' >&2; exit 1")
        env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=os.path.join(tmp, "vhome"),
                   PATH=bindir + os.pathsep + "/usr/bin:/bin", VSTUDIO_CLI_EXTRA_DIRS="",
                   VSTUDIO_CREATE_AI_TIMEOUT=timeout, VSTUDIO_CREATE_AI_DEADLINE=deadline)
        for k in ("VSTUDIO_CREATE_NO_LLM", "VSTUDIO_CREATE_FAKE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                  "VSTUDIO_LLM_PROVIDER", "VSTUDIO_LLM_SCRIPT_PROVIDER"):
            env.pop(k, None)
        routes = os.path.join(tmp, "llm-routes.json")
        if ai:
            with open(routes, "w") as f:
                f.write('{"default": {"provider": "claude-code", "fallback": ["codex"]}, "tasks": {"script": '
                        '{"provider": "claude-code", "fallback": ["codex"]}}}')
        env["VSTUDIO_LLM_ROUTES_FILE"] = routes
        self.bus = EventBus()
        api = CreateApi(os.path.join(tmp, "desk"), self.bus, CliRunner(sys.executable, env), "real")
        return api

    def wait(self, api, jid, limit=60):
        t0 = time.time()
        while time.time() - t0 < limit:
            j = api.get_job(jid)
            if j["state"] != "running":
                return j
            time.sleep(0.1)
        self.fail("the plan job never finished (the 'Planning…' forever bug)")

    def steps(self, j):
        return [e.get("step") for e in j["events"] if e.get("event") == "create.step"]

    def test_hanging_claude_then_failing_codex_is_a_clear_error(self):
        api = self.make()
        t0 = time.time()
        j = self.wait(api, api.route("POST", ["plan"], {}, HER_BODY)["job"])
        self.assertLess(time.time() - t0, 30)
        self.assertEqual(j["state"], "error", j)
        self.assertEqual(j["error"]["code"], "create.ai-failed")
        self.assertIn(j["error"]["params"]["reason"], ("timeout", "failed"))
        self.assertEqual(j["error"]["params"]["provider"], "claude-code")
        st = self.steps(j)
        self.assertEqual(st[:2], ["read", "bible"])
        self.assertIn("fallback", st)

    def test_start_from_template_gives_a_usable_series(self):
        api = self.make()
        j = self.wait(api, api.route("POST", ["plan"], {}, dict(HER_BODY, mode="template"))["job"])
        self.assertEqual(j["state"], "done", j)
        d = j["result"]["draft"]
        self.assertEqual((d["format"], d["source"], d["budget_cny"]), ("series-ad", "template", 60.0))
        self.assertEqual(len(d["platforms"]), 4)
        self.assertEqual(len(d["ideas"]), 4)
        self.assertTrue(all(c["look"] for c in d["bible"]["cast"]))
        self.assertEqual(self.steps(j), ["read", "template"])
        sid = api.route("POST", ["series"], {}, {"draft": d})["series"]          # and it saves as a series
        self.assertEqual(api.route("GET", ["series", sid], {}, {})["format"]["id"], "series-ad")

    def test_no_ai_set_up_is_a_clear_error_at_once(self):
        api = self.make(ai=False)
        t0 = time.time()
        j = self.wait(api, api.route("POST", ["plan"], {}, HER_BODY)["job"])
        self.assertEqual(j["state"], "error", j)
        self.assertEqual((j["error"]["code"], j["error"]["params"]["reason"]), ("create.ai-failed", "not-set-up"))
        self.assertLess(time.time() - t0, 20)

    def test_watchdog_stops_a_stuck_engine(self):
        api = self.make(timeout="60", deadline="60")
        jid = api.job("plan", ["plan", "--format", "series-ad", "--lang", "zh"], limit=1.5)["job"]
        j = self.wait(api, jid)
        self.assertEqual(j["state"], "error")
        self.assertEqual(j["error"]["code"], "create.job-timeout")

    def test_bad_mode_is_400(self):
        from desk_engine.common import BadRequest
        api = self.make(ai=False)
        with self.assertRaises(BadRequest):
            api.route("POST", ["plan"], {}, dict(HER_BODY, mode="magic"))


if __name__ == "__main__":
    unittest.main()
