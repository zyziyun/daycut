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


if __name__ == "__main__":
    unittest.main()
