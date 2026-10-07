"""P0-3: a pilot that fails (e.g. an expired Claude Code login in segment planning) is visible: the project row is
failed with a plain reason code, the inbox has an item, and a retry with another provider can be started."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import pilot as PI  # noqa: E402
from desk_engine.common import Registry, write_json  # noqa: E402
from desk_engine.history import History  # noqa: E402
from desk_engine.inbox import Inbox  # noqa: E402

ERR = "plan-segments failed (exit 5): claude CLI: Failed to authenticate. API Error: 401 /Users/her/.claude/x.log"  # check-skill: allow


def project(root, name="p1"):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, "state"))
    with open(os.path.join(d, "project.yaml"), "w") as f:
        f.write(f"name: {name}\nrecipe: talkinghead\n")
    return d


def log(d, *lines, rec=None):
    with open(os.path.join(d, PI.LOG), "a") as f:
        for ln in lines:
            f.write((json.dumps(ln) if isinstance(ln, dict) else ln) + "\n")
    if rec is not None:
        write_json(os.path.join(d, PI.REC), rec)


class ClassifyTest(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(PI.classify(ERR), "ai-login")
        self.assertEqual(PI.classify("codex: 429 rate limit"), "ai-quota")
        self.assertEqual(PI.classify("claude CLI timed out after 180 s"), "ai-timeout")
        self.assertEqual(PI.classify("ModuleNotFoundError: No module named 'vstudio.llm'"), "engine")
        self.assertEqual(PI.classify("something odd"), "unknown")
        self.assertEqual(PI.provider_of(ERR), "claude-code")
        # the engine's all-attempts error (vstudio.llm.AllProvidersFailed): the first attempt's cause wins
        allf = "every AI provider failed - claude-code [auth-expired]: login expired; codex [failed]: bad schema"
        self.assertEqual((PI.classify(allf), PI.provider_of(allf)), ("ai-login", "claude-code"))

    def test_scrub_drops_paths(self):
        self.assertNotIn("/Users/", PI.scrub(ERR))


class FailureTest(unittest.TestCase):
    def setUp(self):
        self.d = project(tempfile.mkdtemp())

    def test_nothing_ran(self):
        self.assertIsNone(PI.failure(self.d))

    def test_ok_false_line(self):
        log(self.d, {"event": "stage", "stage": "plan"}, "Traceback noise", {"ok": False, "error": ERR},
            rec=dict(pid=None, started=time.time(), offset=0, exit=5))
        f = PI.failure(self.d)
        self.assertEqual((f["state"], f["code"], f["provider"]), ("failed", "ai-login", "claude-code"))
        self.assertNotIn("/Users/", f["error"])

    def test_pilot_review_is_not_a_failure(self):
        log(self.d, {"event": "project-end", "status": "pilot-review", "exit_code": 4},
            rec=dict(pid=None, started=time.time(), offset=0, exit=4))
        self.assertIsNone(PI.failure(self.d))

    def test_running_child_is_not_a_failure(self):
        log(self.d, {"ok": False, "error": ERR}, rec=dict(pid=os.getpid(), started=time.time(), offset=0, exit=None))
        self.assertIsNone(PI.failure(self.d))

    def test_only_the_last_run_counts(self):
        log(self.d, {"ok": False, "error": ERR})
        off = os.path.getsize(os.path.join(self.d, PI.LOG))
        log(self.d, {"event": "project-end", "status": "pilot-review", "exit_code": 4},
            rec=dict(pid=None, started=time.time(), offset=off, exit=None))
        self.assertIsNone(PI.failure(self.d))

    def test_retry_env_pins_every_task(self):
        env = PI.retry_env({"VSTUDIO_LLM_SEGMENT_PLAN_MODEL": "x"}, "codex")
        self.assertEqual(env["VSTUDIO_LLM_SEGMENT_PLAN_PROVIDER"], "codex")
        self.assertNotIn("VSTUDIO_LLM_SEGMENT_PLAN_MODEL", env)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "lib"))
        try:
            from vstudio import llm
        except ImportError:
            return
        self.assertEqual(set(PI.TASKS), {t.upper() for t in llm.TASKS if t != "test"})


class SurfaceTest(unittest.TestCase):
    def test_history_row_and_inbox_item(self):
        root = tempfile.mkdtemp()
        d = project(root)
        log(d, {"ok": False, "error": ERR}, rec=dict(pid=None, started=time.time(), offset=0, exit=5,
                                                      finished=time.time()))
        with mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": root}):
            data = os.path.join(root, "desk")
            h = History(data, Registry(data))
            row = next(r for r in h.list()["items"] if r["dir"] == d)
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["failure"]["code"], "ai-login")
            ib = Inbox(data, h)
            items = [i for i in ib.list()["items"] if i["kind"] == "failed"]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["code"], "inbox.failed.ai-login")
            self.assertEqual(ib.list()["items"][0]["kind"], "failed")       # failures come first
            ib.answer([items[0]["key"]])                                    # dismissed
            self.assertFalse([i for i in ib.list()["items"] if i["kind"] == "failed"])


if __name__ == "__main__":
    unittest.main()
