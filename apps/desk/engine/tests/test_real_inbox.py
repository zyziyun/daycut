"""The inbox and the review screen against the real engine (this monorepo's lib/): a talkinghead project on a tiny
synthetic talk (tests/e2e/fixture/real_project.py: tone-burst words + the engine tests' fake transcriber, the only
fakes) parks at a filler question. Found while recording the real app:

  * the answer reached the engine with option ids as strings ("'6' is not of type 'integer'");
  * the filler card showed a bare word: it reads as a cut with the words around it;
  * answering never continued the run (an answered question stayed "pending" until its gate ran again);
  * a clip waiting at its publish review was "Nothing to review here" on the review screen;
  * a run's stale "needs you" status added a second "A decision is waiting" item.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine.caps import CliRunner  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from desk_engine.inbox import Inbox  # noqa: E402

TESTS = os.path.dirname(os.path.abspath(__file__))
DESK = os.path.abspath(os.path.join(TESTS, "..", ".."))
ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(os.path.join(DESK, "..", ".."))
FIXTURE = os.path.join(DESK, "tests", "e2e", "fixture", "real_project.py")
# no AI account in tests: every model task the engine routes answers "none" (ahead of any desk / persona route)
NO_AI = dict({f"VSTUDIO_LLM_{t}_PROVIDER": "none" for t in ("SEGMENT_PLAN", "PROOFREAD", "GLOSSARY", "COPY", "SCRIPT",
                                                             "PLANNER", "INTAKE", "OUTPUT_EDIT")},
             VSTUDIO_LLM_PROVIDER="none")
HAVE = os.path.isdir(os.path.join(ENGINE, "lib", "vstudio", "project")) and shutil.which("ffmpeg")


def wait(fn, timeout=240, what="condition"):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(1)
    raise AssertionError(f"timed out waiting for {what}")


@unittest.skipUnless(HAVE, "engine repo or ffmpeg not found")
class RealInboxTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="desk-real-inbox-")
        self.addCleanup(shutil.rmtree, self.root, True)
        env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=os.path.join(self.root, "home"),
                   VSTUDIO_BATCH_BENCH=os.path.join(self.root, "bench.json"), VSTUDIO_DEFAULT_PERSONA="1",
                   VSTUDIO_TEST_TRUTH=os.path.join(self.root, "truth.json"), PYTHONUNBUFFERED="1")
        env.update(NO_AI)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_PERSONA"):
            env.pop(k, None)
        patch = mock.patch.dict(os.environ, {k: env[k] for k in ("VSTUDIO_HOME", "VSTUDIO_DEFAULT_PERSONA",
                                                                   "VSTUDIO_TEST_TRUTH", "VSTUDIO_BATCH_BENCH")})
        patch.start()
        self.addCleanup(patch.stop)
        sys.path.insert(0, os.path.join(ENGINE, "lib"))
        out = subprocess.run([sys.executable, FIXTURE, self.root], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr[-3000:])
        self.fx = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(self.fx["pending"], [["talk", "filler"]], "the fixture parks at the filler question")
        data = os.path.join(self.root, "desk")
        self.reg = Registry(data)
        self.h = History(data, self.reg)
        self.runner = CliRunner(sys.executable, env)
        self.ib = Inbox(data, self.h, self.runner, "real", EventBus())

    def status(self):
        return self.runner.sibling("vstudio.project").json(["status", "--dir", self.fx["dir"], "--json"])

    def test_answer_continue_review_and_publish(self):
        items = self.ib.list()["items"]
        self.assertEqual([(i["source"], i["kind"]) for i in items], [("engine", "filler-confirm")])   # listed once
        opt = items[0]["options"][0]
        self.assertEqual(opt["label"]["code"], "inbox.opt.cutWord")
        self.assertEqual(opt["label"]["params"]["word"], "然后")
        self.assertIn("方法⟨然后⟩来看", opt["quote"])                          # the words around the cut

        # her tick, as the desk sends it: option ids as strings
        self.ib.answer([items[0]["key"]], dict(approve=[opt["id"]], keep=[]))
        self.assertEqual(self.ib.list()["items"], [], "an answered question is not asked again")
        # the run goes on by itself and stops at the review before publishing
        pub = wait(lambda: [i for i in self.ib.list()["items"] if i["kind"] == "publish"], what="the publish review")
        self.assertEqual(len(self.ib.list()["items"]), 1)
        labels = [o["label"]["params"]["text"] for o in pub[0]["options"]]
        self.assertTrue(labels and not any(re.fullmatch(r"\d+", x) for x in labels), labels)
        self.assertIn("Xiaohongshu", labels[0])
        wait(lambda: self.status()["state"] == "needs-you" and not self.status()["running"], what="the run to stop")

        # the review screen lists the clip waiting at its publish review; approving answers the checkpoint
        from desk_engine.real import RealEngine
        eng = RealEngine(os.path.join(self.root, "desk"), self.reg, EventBus(), engine_path=ENGINE)
        self.addCleanup(eng.shutdown)
        bid = self.h.open(self.fx["dir"])["id"]
        rows = eng.review_items(bid)
        self.assertEqual([(r["id"], r["state"]) for r in rows], [("talk", "waiting")])
        r = eng.apply_review(bid, dict(decisions=dict(talk=dict(decision="approve", reason=""))))
        self.assertEqual((r["approved"], [os.path.realpath(x) for x in r["resume"]]),
                         (["talk"], [os.path.realpath(self.fx["dir"])]))
        self.ib.resume(r["resume"])
        self.assertEqual(self.ib.list()["items"], [])
        wait(lambda: self.status()["state"] == "done", what="the project to finish")


@unittest.skipUnless(HAVE, "engine repo or ffmpeg not found")
class RealPilotTest(unittest.TestCase):
    """A desk project starts as a pilot of one clip: answering its question confirms the pilot and the rest is
    made too (``resume --confirm-pilot``), each clip still stopping at its own questions."""

    def test_answering_the_pilot_makes_the_other_clips(self):
        root = tempfile.mkdtemp(prefix="desk-real-pilot-")
        self.addCleanup(shutil.rmtree, root, True)
        env = dict(os.environ, PYTHONPATH=os.path.join(ENGINE, "lib"), VSTUDIO_HOME=os.path.join(root, "home"),
                   VSTUDIO_BATCH_BENCH=os.path.join(root, "bench.json"), VSTUDIO_DEFAULT_PERSONA="1",
                   VSTUDIO_TEST_TRUTH=os.path.join(root, "truth.json"), PYTHONUNBUFFERED="1")
        env.update(NO_AI)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_PERSONA"):
            env.pop(k, None)
        patch = mock.patch.dict(os.environ, {k: env[k] for k in ("VSTUDIO_HOME", "VSTUDIO_DEFAULT_PERSONA",
                                                                   "VSTUDIO_TEST_TRUTH", "VSTUDIO_BATCH_BENCH")})
        patch.start()
        self.addCleanup(patch.stop)
        out = subprocess.run([sys.executable, FIXTURE, root, "--pilot"], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr[-3000:])
        fx = json.loads(out.stdout.strip().splitlines()[-1])
        data = os.path.join(root, "desk")
        runner = CliRunner(sys.executable, env)
        st = runner.sibling("vstudio.project").json(["status", "--dir", fx["dir"], "--json"])
        self.assertEqual((st["batch_state"], [i["state"] for i in st["items"]]), ("pilot-review", ["waiting", "planned"]))
        ib = Inbox(data, History(data, Registry(data)), runner, "real", EventBus())
        it = ib.list()["items"]
        self.assertEqual([i["kind"] for i in it], ["filler-confirm"])
        ib.answer([it[0]["key"]], dict(approve=[it[0]["options"][0]["id"]], keep=[]))

        def asked():
            s = runner.sibling("vstudio.project").json(["status", "--dir", fx["dir"], "--json"])
            return not s["running"] and {i["id"]: i["waiting"] for i in s["items"]}
        self.assertEqual(wait(lambda: asked() == {"talk": ["publish"], "talk2": ["filler"]} and asked(),
                              what="both clips at their next question"),
                         {"talk": ["publish"], "talk2": ["filler"]})


if __name__ == "__main__":
    unittest.main()
