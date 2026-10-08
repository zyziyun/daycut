"""A render that fails on a missing / broken external tool (Node.js for HyperFrames, ffmpeg) gets its own failure
code + fix key instead of "Part of Reelfold didn't start"; the capabilities document reports tool health."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import caps as CP  # noqa: E402
from desk_engine import pilot as PI  # noqa: E402
from desk_engine.common import write_json  # noqa: E402

DYLD = ("RuntimeError: export.py exit 1: dyld[8123]: Library not loaded: /opt/homebrew/opt/simdjson/lib/"
        "libsimdjson.29.dylib  Referenced from: <0A1B> /opt/homebrew/Cellar/node/25.6.1/bin/node")
NODE_ERR = ("RuntimeError: export.py exit 1:\nerror: node unavailable: the Node.js at /opt/homebrew/bin/node is "
            "broken (dyld[1]: Library not loaded: libsimdjson.29.dylib). Run `brew reinstall node` in Terminal")
OLD_NODE = "error: node unavailable: the Node.js at /usr/local/bin/node is v16.20.2; HyperFrames needs 18+"
NO_NODE = "RuntimeError: npx (Node) not found: HyperFrames needs Node 18+"
FF_MISSING = "FFmpegError: VSTUDIO_FFMPEG=/Applications/Reelfold.app/Contents/Resources/runtime/ffmpeg/bin/ffmpeg does not exist"
FF_BSF = "export.py exit 1: [vost#0:0] Unknown bitstream filter h264_metadata"
FF_DYLD = "dyld: Library not loaded: libx264.164.dylib\n  Referenced from: /opt/homebrew/bin/ffmpeg"
B_TRACEBACK = ("RuntimeError: export.py exit 1: Traceback (most recent call last):\n  File \"export.py\"\n"
               "vstudio.media.FFmpegError: command failed (254): ffmpeg -nostdin ...\n"
               "Error opening output /x/out/promo.loud.mp4: No such file or directory")


class ClassifyTools(unittest.TestCase):
    def test_node(self):
        for t in (DYLD, NODE_ERR, OLD_NODE, NO_NODE):
            self.assertEqual(PI.classify(t), "tool-node", t)
        self.assertEqual(PI.tool_fix("tool-node", DYLD), dict(tool="node", fix="brew-reinstall-node"))
        self.assertEqual(PI.tool_fix("tool-node", OLD_NODE)["fix"], "install-node")
        self.assertEqual(PI.tool_fix("tool-node", NO_NODE)["fix"], "install-node")

    def test_ffmpeg(self):
        for t in (FF_MISSING, FF_BSF, FF_DYLD):
            self.assertEqual(PI.classify(t), "tool-ffmpeg", t)
        self.assertEqual(PI.tool_fix("tool-ffmpeg", FF_MISSING), dict(tool="ffmpeg", fix="reinstall-app"))
        self.assertEqual(PI.tool_fix("tool-ffmpeg", FF_DYLD)["fix"], "install-ffmpeg")

    def test_existing_codes_unchanged_and_traceback_is_not_engine_when_it_says_more(self):
        self.assertEqual(PI.classify("codex: 429 rate limit"), "ai-quota")
        self.assertEqual(PI.classify("ModuleNotFoundError: No module named 'vstudio.llm'"), "engine")
        self.assertEqual(PI.classify("Traceback (most recent call last):\n  ValueError: x"), "engine")
        self.assertEqual(PI.classify(B_TRACEBACK), "media")
        self.assertEqual(PI.tool_fix("media", B_TRACEBACK), {})

    def test_failure_document_carries_tool_and_fix(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, PI.LOG), "w") as f:
            f.write(json.dumps(dict(event="stage-fail", job="AIGC", stage="render", error=DYLD)) + "\n")
            f.write(json.dumps(dict(event="project-end", exit_code=5, status="failed")) + "\n")
        write_json(os.path.join(d, PI.REC), dict(pid=None, started=1, offset=0, exit=5, finished=2))
        f = PI.failure(d)
        self.assertEqual((f["code"], f["tool"], f["fix"]), ("tool-node", "node", "brew-reinstall-node"))
        self.assertNotIn("/opt/homebrew", f["error"])


class ToolHealth(unittest.TestCase):
    def test_tools_in_capabilities_info_real_mode_only(self):
        class R:
            def json(self, *a, **k):
                return {"recipes": [], "capabilities": ["deliver"]}

        c = CP.Capabilities(R())
        c._tools = dict(node=dict(ok=False, error="node unavailable: ...", fix="brew reinstall node"),
                        ffmpeg=dict(ok=True))
        info = c.info()
        self.assertFalse(info["tools"]["node"]["ok"])
        self.assertNotIn("tools", CP.Capabilities(fixed=set()).info())

    def test_health_shapes(self):
        n = CP.node_health()
        self.assertTrue({"ok", "version", "path", "error", "fix", "checked"} <= set(n))
        f = CP.ffmpeg_health()
        self.assertTrue({"ok", "path", "ffprobe", "version", "error"} <= set(f))


if __name__ == "__main__":
    unittest.main()
