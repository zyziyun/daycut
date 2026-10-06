"""Real-engine adapter test against the engine repo's fake recipe (no media). Skipped without the repo.

Uses video-studio/tests/_batch_helpers.py (recipe ``test-fake``) through the spec's ``plugins`` /
``plugin_paths`` keys, so the `run` subprocess loads it too. Nothing in the engine repo is modified.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401  (VSTUDIO_HOME / DESK_DATA_DIR -> a temp folder, first)

ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "video-studio"))
HAVE = os.path.isdir(os.path.join(ENGINE, "lib", "vstudio", "batch"))


@unittest.skipUnless(HAVE, "video-studio engine repo not found")
class RealEngineTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, os.path.join(ENGINE, "lib"))
        os.environ["PYTHONPATH"] = os.path.join(ENGINE, "lib")
        os.environ["VSTUDIO_BATCH_BENCH"] = os.path.join(tempfile.mkdtemp(), "bench.json")
        from desk_engine.common import EventBus, Registry
        from desk_engine.real import RealEngine
        self.tmp = tempfile.mkdtemp()
        self.bus = EventBus()
        self.q = self.bus.subscribe()
        self.eng = RealEngine(self.tmp, Registry(self.tmp), self.bus, engine_path=ENGINE)

    def tearDown(self):
        self.eng.shutdown()

    def test_import_status_pilot(self):
        from vstudio.batch.plan import plan_batch
        spec = dict(name="fake", recipe="test-fake", plugins=["_batch_helpers"],
                    plugin_paths=[os.path.join(ENGINE, "tests")],
                    jobs=[dict(id="a"), dict(id="b"), dict(id="c", red=True)], budget=dict(max_hours=10))
        sp = os.path.join(self.tmp, "fake.json")
        with open(sp, "w") as f:
            json.dump(spec, f)
        r = plan_batch(sp, os.path.join(self.tmp, "batch-fake"), echo=False)
        ent = self.eng.import_batch(r["batch_dir"])
        s = self.eng.status(ent["id"])
        self.assertEqual([j["id"] for j in s["jobs"]], ["a", "b", "c"])
        est = self.eng.estimate(ent["id"])
        self.assertTrue(est["budget"]["ok"])
        self.eng.run(ent["id"], dict(pilot=1))
        code = None
        t0 = time.time()
        while time.time() - t0 < 60:
            ev = self.q.get(timeout=60)
            if ev["type"] == "run-exit":
                code = ev["code"]
                break
        self.assertEqual(code, 0)
        s = self.eng.status(ent["id"])
        self.assertEqual(s["meta"]["state"], "pilot-review")
        self.assertEqual(s["jobs"][0]["state"], "done")
        items = self.eng.review_items(ent["id"])
        self.assertEqual(items[0]["id"], "a")
        res = self.eng.apply_review(ent["id"], dict(decisions={"a": dict(decision="approve")}))
        self.assertEqual(res["approved"], ["a"])
        self.assertIn(r["batch_dir"], self.eng.roots())

    def test_registry_stays_in_the_temp_home(self):
        """plan registers the batch under $VSTUDIO_HOME (the tests' temp folder), never ~/.config/vstudio."""
        from vstudio.batch.plan import plan_batch
        real = os.path.expanduser("~/.config/vstudio/batches.json")
        before = open(real, "rb").read() if os.path.exists(real) else None
        spec = dict(name="fake", recipe="test-fake", plugins=["_batch_helpers"],
                    plugin_paths=[os.path.join(ENGINE, "tests")], jobs=[dict(id="a")])
        sp = os.path.join(self.tmp, "fake.json")
        with open(sp, "w") as f:
            json.dump(spec, f)
        r = plan_batch(sp, os.path.join(self.tmp, "batch-reg"), echo=False)
        self.assertEqual(os.environ["VSTUDIO_HOME"], _isolate.HOME)
        with open(os.path.join(_isolate.HOME, "batches.json")) as f:
            self.assertIn(r["batch_dir"], json.dumps(json.load(f)))
        after = open(real, "rb").read() if os.path.exists(real) else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
