"""A failed step keeps the engine's own code (tool-missing / tool-broken {tool, path, fix}) and its stage; a Python
crash inside a step is "stage", never "engine" ("Part of Reelfold didn't start" is only for the engine not starting).
Found when a Homebrew node whose dylib was upgraded away crashed the render of a real promo."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401


class ToolFailureKeepsItsCode(unittest.TestCase):
    """The render's node crashed (a Homebrew dylib upgraded away): "Part of Reelfold didn't start" was wrong."""

    def test_a_stage_fail_with_an_engine_code_wins(self):
        from desk_engine import pilot
        d = tempfile.mkdtemp()
        ev = dict(event="stage-fail", job="AIGC", stage="render", code="tool-broken",
                  params=dict(tool="node", path="/opt/homebrew/bin/node", fix="brew reinstall node"),
                  error="RuntimeError: export.py exit 1: dyld: Library not loaded\nTraceback (most recent call last):")
        with open(os.path.join(d, pilot.LOG), "w", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n" + json.dumps(dict(event="project-end", exit_code=1)) + "\n")
        with open(os.path.join(d, pilot.REC), "w", encoding="utf-8") as f:
            json.dump(dict(pid=None, started=1.0, offset=0, exit=1, finished=2.0), f)
        fail = pilot.failure(d)
        self.assertEqual(fail["code"], "tool-broken")
        self.assertEqual(fail["params"], dict(tool="node", path="/opt/homebrew/bin/node", fix="brew reinstall node"))
        self.assertEqual(fail["stage"], "render")

    def test_a_python_crash_in_a_stage_is_not_an_engine_start_failure(self):
        from desk_engine import pilot
        d = tempfile.mkdtemp()
        ev = dict(event="stage-fail", job="A", stage="build", error="Traceback (most recent call last):\nKeyError: 'x'")
        with open(os.path.join(d, pilot.LOG), "w", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")
        with open(os.path.join(d, pilot.REC), "w", encoding="utf-8") as f:
            json.dump(dict(pid=None, started=1.0, offset=0, exit=1, finished=2.0), f)
        fail = pilot.failure(d)
        self.assertNotEqual(fail["code"], "engine")
        self.assertEqual(fail["stage"], "build")
        self.assertEqual(pilot.classify("ModuleNotFoundError: No module named 'vstudio'"), "engine")


if __name__ == "__main__":
    unittest.main()
