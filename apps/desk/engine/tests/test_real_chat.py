"""Chat editing against the real engine (this monorepo's lib/): the capability probe sees the extended output
commands, and ``ask`` -> ``show`` returns the new turn (the desk must read the engine's transcript, P0-2)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402
from desk_engine.caps import CliRunner  # noqa: E402
from desk_engine.common import Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402

TESTS = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(os.path.join(TESTS, "..", "..", "..", ".."))
HAVE = os.path.isdir(os.path.join(ENGINE, "lib", "vstudio", "project")) and shutil.which("ffmpeg")


class ProbeTest(unittest.TestCase):
    def test_has_word(self):
        txt = "{list,show,edit,render,undo,redo,revert,ai,chat,effects}  [--context CONTEXT] [--chat-x]"
        for w in ("show", "chat", "--context", "revert"):
            self.assertTrue(OU._has_word(txt, w), w)
        self.assertFalse(OU._has_word("[--contexts X] chat-x", "--context"))
        self.assertFalse(OU._has_word("chat-x", "chat"))


@unittest.skipUnless(HAVE, "engine repo or ffmpeg not found")
class RealChatTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        watch = os.path.join(self.root, "demos")
        self.work = os.path.join(watch, "talk")
        os.makedirs(os.path.join(self.work, "final"))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x568:d=3:r=30",
                        "-f", "lavfi", "-i", "sine=f=220:d=3", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", os.path.join(self.work, "final", "clip.mp4")], check=True)
        with open(os.path.join(self.work, "REPORT.md"), "w") as f:
            f.write("# clip\n")
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(ENGINE, "lib"), TESTS]),
                   VSTUDIO_OUTPUT_TRANSCRIBER="_fake_asr:words", VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER="none",
                   VSTUDIO_HOME=os.path.join(self.root, "home"))
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER"):
            env.pop(k, None)
        self.patch = mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": watch, "VSTUDIO_HOME": env["VSTUDIO_HOME"]})
        self.patch.start()
        subprocess.run([sys.executable, "-c", f"from vstudio.project import works; works.adopt({self.work!r})"],
                       env=env, check=True)
        data = os.path.join(self.root, "desk")
        self.h = History(data, Registry(data))
        self.env = env
        self.o = OU.Outputs(data, self.h, CliRunner(sys.executable, env))
        self.item = next(r["id"] for r in self.h.list()["items"] if r["dir"] == self.work)

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, True)

    def test_probe_sees_the_extended_commands(self):
        self.assertTrue(self.o.real())
        self.assertTrue(self.o._ext, "the engine has revert / chat / --context: the probe must see them")

    def test_ask_then_show_returns_the_new_turn(self):
        clip = self.o.clips(self.item)["clips"][0]["id"]
        before = self.o.show(self.item, clip)
        self.assertEqual(before["engine"], "real")
        r = self.o.ask(self.item, clip, "1.1倍速")
        self.assertTrue(r.get("turn"))
        after = self.o.show(self.item, clip)
        self.assertIn(r["turn"], [t["id"] for t in after["chat"]])
        self.assertEqual(len(after["chat"]), len(before["chat"]) + 1)

    def test_model_failure_rules_turn_is_shown(self):
        """A model that fails -> the desk rules answer; that turn must land in the transcript ``show`` reads."""
        self.env.update(VSTUDIO_LLM_OUTPUT_EDIT_PROVIDER="anthropic", VSTUDIO_LLM_FALLBACK="")
        clip = self.o.clips(self.item)["clips"][0]["id"]
        before = self.o.show(self.item, clip)
        r = self.o.ask(self.item, clip, "去掉开头 1 秒")
        self.assertEqual(r.get("provider"), "rules")
        self.assertIn(r["turn"], [t["id"] for t in self.o.show(self.item, clip)["chat"]])
        self.assertEqual(len(self.o.show(self.item, clip)["chat"]), len(before["chat"]) + 1)


if __name__ == "__main__":
    unittest.main()
