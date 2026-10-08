"""First ten minutes: the built-in sample (copied out of the app, marked, deletable only when it is the sample), the
checkpoints a desk plan answers with their default, engine-checkpoint answers in the shape the engine wants, the run
carrying on after an answer, and a project's own run store not listed twice."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import inbox as IB  # noqa: E402
from desk_engine import sample as SA  # noqa: E402
from desk_engine.common import Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from desk_engine.intake import auto_checkpoints  # noqa: E402


class SampleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="desk-sample-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bundle = os.path.join(self.tmp, "bundle")
        os.makedirs(self.bundle)
        with open(os.path.join(self.bundle, SA.FILE), "wb") as f:
            f.write(b"\0" * 1000)
        with open(os.path.join(self.bundle, "script.json"), "w") as f:
            json.dump(dict(duration=112.7), f)
        self.home = os.path.join(self.tmp, "vhome")
        p = mock.patch.dict(os.environ, {"DESK_SAMPLE_DIR": self.bundle})
        p.start()
        self.addCleanup(p.stop)
        self.s = SA.Sample(os.path.join(self.tmp, "data"), lambda: self.home)

    def test_the_shipped_sample_exists(self):
        with mock.patch.dict(os.environ, {"DESK_SAMPLE_DIR": ""}):
            d = SA.bundled_dir()
        self.assertTrue(os.path.isfile(os.path.join(d, SA.FILE)), d)
        self.assertTrue(os.path.isfile(os.path.join(d, "LICENSE.txt")))
        self.assertLess(os.path.getsize(os.path.join(d, SA.FILE)), 5_000_000)      # it ships inside the app

    def test_info_copies_out_of_the_bundle_once(self):
        a = self.s.info()
        self.assertTrue(a["available"])
        self.assertEqual(a["duration"], 112.7)
        self.assertTrue(a["path"].startswith(os.path.join(self.tmp, "data")))
        m = os.path.getmtime(a["path"])
        self.s.info()
        self.assertEqual(os.path.getmtime(a["path"]), m)
        os.remove(os.path.join(self.bundle, SA.FILE))
        self.assertFalse(self.s.info()["available"])

    def test_mark_and_remove_only_the_sample(self):
        self.s.info()
        d = os.path.join(self.home, "projects", "abc", "01-sample")
        other = os.path.join(self.home, "projects", "abc", "02-mine")
        for x in (d, other):
            os.makedirs(x)
        self.assertTrue(self.s.uses_sample([self.s.path]))
        self.assertFalse(self.s.uses_sample(["/x/other.mp4"]))
        self.s.mark([d])
        self.assertTrue(SA.is_sample(d))
        with self.assertRaises(Exception):
            self.s.remove(other)                                   # not marked
        outside = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(outside, ".vstudio"))
        shutil.copy(os.path.join(d, SA.MARKER), os.path.join(outside, SA.MARKER))
        with self.assertRaises(Exception):
            self.s.remove(outside)                                 # marked, but not under VSTUDIO_HOME/projects
        self.assertEqual(self.s.remove(d)["removed"], d)
        self.assertFalse(os.path.exists(d))
        self.assertTrue(os.path.exists(other))                     # the plan folder still holds her project


class AutoCheckpointsTest(unittest.TestCase):
    def test_defaults_unless_she_asked(self):
        self.assertEqual(auto_checkpoints("Cut the pauses and add captions"), ["hook", "filler", "cover"])
        self.assertEqual(auto_checkpoints("加一个高光预告开头，去气口"), ["filler", "cover"])
        self.assertEqual(auto_checkpoints("make a nice cover and a hook"), ["filler"])
        self.assertEqual(auto_checkpoints("确认一下 filler 再剪"), ["hook", "cover"])


class EngineAnswerTest(unittest.TestCase):
    def test_shapes(self):
        ticks = lambda on, off=(): dict(approve=[str(x) for x in on], keep=[str(x) for x in off])  # noqa: E731
        self.assertEqual(IB.engine_answer("hook-pick", ticks([2], [0, 1])), dict(pick=2))
        self.assertIsNone(IB.engine_answer("hook-pick", ticks([0, 1, 2])))             # untouched: the default
        self.assertEqual(IB.engine_answer("cover-pick", ticks([1])), dict(pick=1))
        self.assertEqual(IB.engine_answer("publish", ticks([0, 1])), dict(approve=True))
        self.assertEqual(IB.engine_answer("publish", ticks([], [0])), dict(approve=False))
        self.assertEqual(IB.engine_answer("filler-confirm", ticks([0, 2], [1])), dict(approve=[0, 2], keep=[1]))
        self.assertEqual(IB.engine_answer("segment-approval", dict(x=1)), dict(x=1))
        self.assertEqual(IB.engine_answer("keywords", ticks(["亚麻", "L6"], ["风格"])),       # ids = the keywords
                         dict(approve=["亚麻", "L6"], keep=["风格"]))
        self.assertIsNone(IB.engine_answer("publish", None))

    def test_export_labels(self):
        self.assertEqual(IB._export_label("/p/exports/tiktok-vertical.mp4"), "TikTok · vertical")
        self.assertEqual(IB._export_label("/p/exports/youtube-shorts-vertical.mp4"), "YouTube Shorts · vertical")

    def test_answer_goes_to_the_engine_in_its_shape_and_resumes(self):
        ib = IB.Inbox(tempfile.mkdtemp(), history=mock.Mock(), runner=mock.Mock(), mode="real")
        item = dict(key="a" * 16, kind="publish", source="engine", project=dict(id="x"),
                    engine=dict(dir="/p/proj", id="publish", item="clip1"))
        done = threading.Event()
        with mock.patch.object(IB.Inbox, "list", return_value=dict(items=[item])), \
                mock.patch("desk_engine.pilot.resume_after_answer", side_effect=lambda *a, **k: done.set()) as res:
            ib.answer(["a" * 16], dict(approve=["0"], keep=[]))
            self.assertTrue(done.wait(5))
        args = ib.runner.sibling.return_value.json.call_args[0][0]
        self.assertEqual(args[args.index("--answer") + 1], json.dumps(dict(approve=True)))
        self.assertEqual(res.call_args[0][1], "/p/proj")

    def test_a_pilot_goes_on_past_its_review_once_every_question_is_answered(self):
        """A desk project starts as a pilot, which ends in "pilot-review", where `resume` alone stops at once: once
        she has answered every question it asked, the project goes on with `--confirm-pilot`."""
        from desk_engine import pilot
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        open(os.path.join(d, "project.yaml"), "w").write("name: p\n")
        cli = mock.Mock()
        cli.json.side_effect = lambda args, timeout=None: (
            dict(batch_state="pilot-review", items=[dict(id="c", state="done"), dict(id="d", state="planned")])
            if args[0] == "status" else dict(entries=[]))
        runner = mock.Mock(python="py", env={})
        runner.sibling.return_value = cli
        calls = []
        pilot.resume_after_answer(runner, d, spawner=lambda *a, **k: calls.append(k.get("args")) or {})
        self.assertEqual(calls, [["py", "-m", "vstudio.project", "resume", "--dir", d, "--json-events", "--confirm-pilot"]])


class HistoryTest(unittest.TestCase):
    def test_project_state_is_not_a_second_row_and_the_sample_is_flagged(self):
        root = tempfile.mkdtemp(prefix="desk-hist-")
        self.addCleanup(shutil.rmtree, root, True)
        d = os.path.join(root, "proj")
        os.makedirs(os.path.join(d, "state"))
        os.makedirs(os.path.join(d, ".vstudio"))
        with open(os.path.join(d, "project.yaml"), "w") as f:
            f.write("name: Sample\nrecipe: talkinghead\n")
        open(os.path.join(d, "state", "batch.db"), "w").close()
        with open(os.path.join(d, SA.MARKER), "w") as f:
            f.write("{}")
        data = tempfile.mkdtemp(prefix="desk-hist-data-")
        self.addCleanup(shutil.rmtree, data, True)
        h = History(data, Registry(data))
        cands = [("project", d, "engine", {}), ("batch", os.path.join(d, "state"), "engine", {})]
        with mock.patch.object(History, "_candidates", return_value=(cands, {})):
            rows = h.list()["items"]
        self.assertEqual([(r["kind"], r.get("sample")) for r in rows], [("project", True)])


if __name__ == "__main__":
    unittest.main()
