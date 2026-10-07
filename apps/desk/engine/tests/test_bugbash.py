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
