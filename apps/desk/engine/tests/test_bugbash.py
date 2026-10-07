"""Regressions found in the 2026-10 bug bash (qa/BUGS.md)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402


class EffectsCatalogueCached(unittest.TestCase):
    """BB-04: every editor open asked the engine CLI for the effects catalogue (~3 s Python start each time)."""

    def test_real_catalogue_is_fetched_once(self):
        o = OU.Outputs(tempfile.mkdtemp(), history=None)
        calls = []

        def cli(args, timeout=600):
            calls.append(args)
            return dict(effects=[dict(id="pop-words")])

        with mock.patch.object(o, "real", return_value=True), mock.patch.object(o, "_cli", side_effect=cli):
            a = o.effects()
            b = o.effects()
        self.assertEqual(a, b)
        self.assertEqual(a["engine"], "real")
        self.assertEqual(len(calls), 1)

    def test_a_failure_is_not_cached(self):
        o = OU.Outputs(tempfile.mkdtemp(), history=None)
        with mock.patch.object(o, "real", return_value=True), mock.patch.object(o, "_cli", side_effect=RuntimeError("x")):
            self.assertEqual(o.effects()["engine"], "desk")
        with mock.patch.object(o, "real", return_value=True), \
                mock.patch.object(o, "_cli", return_value=dict(effects=[dict(id="a")])):
            self.assertEqual(o.effects()["engine"], "real")


class NoFakeEngineFallback(unittest.TestCase):
    """Mock-in-product: a vstudio that does not import used to start the in-memory demo engine silently."""

    def test_import_error_is_not_turned_into_a_mock_engine(self):
        import server
        from desk_engine.common import EventBus
        env = {k: v for k, v in os.environ.items() if k != "DESK_ENGINE_MOCK"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(sys.modules, {"desk_engine.real": None}):
            with self.assertRaises(ImportError):
                server.make_engine(tempfile.mkdtemp(), EventBus())

    def test_mock_engine_only_when_asked(self):
        import server
        from desk_engine.common import EventBus
        with mock.patch.dict(os.environ, {"DESK_ENGINE_MOCK": "1", "DESK_MOCK_STEP": "0.01"}):
            eng, _ = server.make_engine(tempfile.mkdtemp(), EventBus())
        self.assertEqual(eng.mode, "mock")
        eng.shutdown()

    def test_the_test_engine_lives_in_tests_only(self):
        """M8: the fake engine is a test fixture (engine/tests/fixtures/desk_mock), not product code."""
        import server
        from desk_engine.common import EventBus
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertFalse(os.path.exists(os.path.join(here, "desk_engine", "mock.py")))
        with mock.patch.dict(os.environ, {"DESK_ENGINE_MOCK": "1", "DESK_MOCK_STEP": "0.01"}):
            eng, _ = server.make_engine(tempfile.mkdtemp(), EventBus())
        self.assertEqual(type(eng).__module__, "desk_mock.engine")
        eng.shutdown()
        for f in os.listdir(os.path.join(here, "desk_engine")):
            if f.endswith(".py"):
                with open(os.path.join(here, "desk_engine", f), encoding="utf-8") as fh:
                    src = fh.read()
                self.assertNotIn("DESK_MOCK", src, f)
                self.assertNotIn("_mock_", src, f)

    def test_a_packaged_layout_cannot_start_the_test_engine(self):
        """The packaged app ships engine/ without tests/: DESK_ENGINE_MOCK=1 fails the start, nothing fake runs."""
        import shutil
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pkg = tempfile.mkdtemp()
        shutil.copy(os.path.join(here, "server.py"), pkg)
        shutil.copytree(os.path.join(here, "desk_engine"), os.path.join(pkg, "desk_engine"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        env = dict(os.environ, DESK_TOKEN="t" * 40, DESK_DATA_DIR=tempfile.mkdtemp(), DESK_ENGINE_MOCK="1")
        p = subprocess.run([sys.executable, os.path.join(pkg, "server.py")], env=env, capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL)
        first = p.stdout.strip().splitlines()[0]
        import json
        doc = json.loads(first)
        self.assertFalse(doc["ready"])
        self.assertIn("test engine is not part of this build", doc["error"])


class DefaultWatchOnlyWhenPresent(unittest.TestCase):
    def test_missing_default_folder_is_not_listed(self):
        from desk_engine import history as H
        env = {k: v for k, v in os.environ.items() if k != "DESK_HISTORY_WATCH"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(H, "DEFAULT_WATCH", ["/nonexistent/reelfold-demos", tempfile.gettempdir()]):
            got = H.History(tempfile.mkdtemp(), registry=None).default_watch()
        self.assertEqual(got, [tempfile.gettempdir()])


class ResumeAfterInboxAnswer(unittest.TestCase):
    """Answering a project's last open question in the Inbox continues its run (it only did in the week plan)."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        open(os.path.join(self.d, "project.yaml"), "w").write("name: p\nrecipe: talkinghead\n")

    def runner(self, entries, items):
        class Cli:
            def json(self_, args, timeout=None):
                return dict(entries=entries) if args[0] == "inbox" else dict(items=items)

        class R:
            python, env = "py", {}

            def sibling(self_, mod):
                return Cli()
        return R()

    def resume(self, entries, items):
        from desk_engine import pilot
        calls = []
        r = pilot.resume_after_answer(self.runner(entries, items), self.d, spawner=lambda *a, **k: calls.append(k["args"]) or {})
        return r, calls

    def test_last_answer_resumes_the_run(self):
        _, calls = self.resume([], [dict(id="a", state="done"), dict(id="b", state="waiting", waiting=["publish"])])
        self.assertEqual(calls, [["py", "-m", "vstudio.project", "resume", "--dir", self.d, "--json-events"]])

    def test_nothing_runs_while_she_still_has_a_question(self):
        _, calls = self.resume([dict(project=self.d, id="publish", item="b")], [dict(id="b", state="waiting")])
        self.assertEqual(calls, [])

    def test_nothing_runs_when_finished_or_already_running(self):
        self.assertEqual(self.resume([], [dict(id="a", state="done"), dict(id="b", state="failed")])[1], [])
        self.assertEqual(self.resume([], [dict(id="a", state="running"), dict(id="b", state="planned")])[1], [])

    def test_only_projects(self):
        from desk_engine import pilot
        self.assertIsNone(pilot.resume_after_answer(self.runner([], [dict(state="planned")]), tempfile.mkdtemp()))


if __name__ == "__main__":
    unittest.main()


class InboxPollIsCheap(unittest.TestCase):
    """BB-19: every /api/inbox poll started a `vstudio.project inbox` CLI (1.5-4.5 s of CPU while idle)."""

    class Hist:
        def list(self):
            return dict(items=[])

        def allow_media(self, paths):
            pass

    class Runner:
        def __init__(self):
            self.calls = []

        def sibling(self, mod):
            runner = self

            class S:
                def json(self, args, timeout=None, **kw):
                    runner.calls.append((mod, args))
                    return {}

                def text(self, args, timeout=None, **kw):
                    runner.calls.append((mod, args))
                    return ""
            return S()

    def test_engine_inbox_is_read_in_process_and_cached(self):
        from desk_engine import inbox as IB
        from vstudio.project import inbox as PI
        runner = self.Runner()
        ib = IB.Inbox(tempfile.mkdtemp(), self.Hist(), runner, "real")
        reads = []

        def fake_inbox(projects=None):
            reads.append(1)
            return dict(entries=[], groups=[], counts={}, total=0, errors=[])
        with mock.patch.object(PI, "inbox", side_effect=fake_inbox):
            self.assertTrue(ib.real())
            for _ in range(5):
                ib.list()
            self.assertEqual(len(reads), 1)
            ib.undo(["0" * 16])                       # an answer / undo reads it again
            ib.list()
            self.assertEqual(len(reads), 2)
        self.assertEqual(runner.calls, [], "no CLI is started to list or probe the inbox")


class EditorOpenWithoutCli(unittest.TestCase):
    """BB-18: opening a clip started `output list` + `output show` CLIs (6-8 s cold); now read in process."""

    def test_list_and_show_are_read_in_process(self):
        from vstudio.project import outputs as O
        o = OU.Outputs(tempfile.mkdtemp(), history=None)
        with mock.patch.object(o, "_cli", side_effect=AssertionError("no CLI")), \
                mock.patch.object(O, "list_outputs", return_value=dict(outputs=[dict(id="final/a.mp4", file="/x/a.mp4")])), \
                mock.patch.object(O, "show", return_value=dict(output=dict(id="final/a.mp4"), state={})):
            self.assertEqual(o._read("list", "/x")["outputs"][0]["id"], "final/a.mp4")
            self.assertEqual(o._read("show", "/x", "final/a.mp4")["output"]["id"], "final/a.mp4")

    def test_a_refusal_is_the_same_engine_message(self):
        from vstudio.project import outputs as O
        o = OU.Outputs(tempfile.mkdtemp(), history=None)
        with mock.patch.object(O, "show", side_effect=O.OutputError("no-output", "no output x", "没有 x", id="x")):
            with self.assertRaises(OU.EngineMessage) as cm:
                o._read("show", "/x", "x")
        self.assertEqual((cm.exception.doc["code"], cm.exception.doc["params"]), ("no-output", {"id": "x"}))
