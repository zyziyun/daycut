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


if __name__ == "__main__":
    unittest.main()
