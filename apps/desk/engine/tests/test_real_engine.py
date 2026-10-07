"""Real-engine adapter test against the engine repo's fake recipe (no media). Skipped without the repo.

Uses video-studio/tests/_batch_helpers.py (recipe ``test-fake``) through the spec's ``plugins`` /
``plugin_paths`` keys, so the `run` subprocess loads it too. Nothing in the engine repo is modified.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401  (VSTUDIO_HOME / DESK_DATA_DIR -> a temp folder, first)

ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(       # monorepo root: apps/desk/engine/tests -> ../../../..
    os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
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
            self.assertIn(r["batch_dir"], [e.get("dir") for e in json.load(f)])
        after = open(real, "rb").read() if os.path.exists(real) else None
        self.assertEqual(before, after)


@unittest.skipUnless(HAVE and shutil.which("ffmpeg"), "engine repo or ffmpeg not found")
class FocusReviewOfAProjectTest(unittest.TestCase):
    """Found while capturing the launch video: #/p/<project>/focus was empty for a project waiting at its publish
    check (its clips are exported but ``waiting``, and the review listed only ``done`` jobs)."""

    def test_clips_at_the_publish_check_are_reviewed_and_answered_there(self):
        sys.path[:0] = [os.path.join(ENGINE, "lib"), os.path.join(ENGINE, "tests")]
        os.environ["VSTUDIO_BATCH_BENCH"] = os.path.join(tempfile.mkdtemp(), "bench.json")
        import _batch_helpers as H
        from vstudio.batch.store import Store
        from vstudio.project.core import Project
        from desk_engine.common import EventBus, Registry
        from desk_engine.real import RealEngine
        tmp = tempfile.mkdtemp()
        x, truth, dur = H.synth_speech([("大家", .4), ("好", .3), ("今天", .4), ("我们", .35), ("讲", .3), ("一个", .35),
                                        ("方法", .4), ("这个", .3), ("方法", .4), ("很", .25), ("好用", .4)])
        src = H.make_video(os.path.join(tmp, "talk.mp4"), x, 48000, dur)
        tp = os.path.join(tmp, "truth.json")
        with open(tp, "w") as f:
            json.dump([{k: w[k] for k in ("w", "t", "te")} for w in truth], f, ensure_ascii=False)
        os.environ["VSTUDIO_TEST_TRUTH"] = tp
        p = Project.create(os.path.join(tmp, "th"), recipe="talkinghead", inputs=dict(video=[src]),
                           params=dict(pipeline="fast", preset="ultrafast", speed=1.0), auto=["hook", "filler", "cover"],
                           spec=dict(plugins=["vstudio.project.registry", "_batch_helpers"],
                                     asr=dict(transcriber="_batch_helpers:fake_transcriber"), proofread=dict(enabled=False)))
        self.assertEqual([x["id"] for x in p.run()["pending"]], ["publish"])
        eng = RealEngine(tmp, Registry(tmp), EventBus(), engine_path=ENGINE)
        bid = eng.reg.add(p.state_dir, "th")["id"]                  # what History.open does for a project
        items = eng.review_items(bid)
        self.assertEqual([(i["id"], i["state"]) for i in items], [("talk", "waiting")])
        self.assertTrue(items[0]["files"] and all(os.path.exists(f) for f in items[0]["files"]))
        r = eng.apply_review(bid, dict(decisions=dict(talk=dict(decision="approve", reason="")), cleanup={}))
        self.assertEqual((r["approved"], r["skipped"], r["resume"]), (["talk"], [], [p.dir]))
        self.assertEqual(Project(p.dir).data["answers"]["publish"]["talk"]["value"], dict(approve=True))
        st = Store(p.state_dir)
        self.assertEqual(st.job("talk")["review"], "approved")
        st.close()


if __name__ == "__main__":
    unittest.main()
