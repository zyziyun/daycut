"""Record -> second pass -> pickup, against the real engine (this monorepo's lib/, real ffmpeg, the fake transcriber):
``record ingest --target edit`` makes the take its own clip (an adopted work in All projects, the automatic cleanup as
its first step); the desk opens it with its recording info; a pickup recorded with the recorder is spliced in with
``POST /api/outputs/<item>/<clip>/pickup`` and the clip then plays the spliced file with the pickup's words; requests
outside the recordings folder or with a bad spot are refused."""
import json
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
from desk_engine.common import BadRequest, Registry, batch_id  # noqa: E402
from desk_engine.create import CreateApi  # noqa: E402
from desk_engine.history import History  # noqa: E402

TESTS = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.environ.get("VSTUDIO_ENGINE_PATH") or os.path.abspath(os.path.join(TESTS, "..", "..", "..", ".."))
HAVE = os.path.isdir(os.path.join(ENGINE, "lib", "vstudio", "project")) and shutil.which("ffmpeg")


def session(root, name, seconds):
    d = os.path.join(root, "recordings", name)
    os.makedirs(d)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=size=180x320:rate=24:duration={seconds}",
                    "-c:v", "libvpx-vp9", "-b:v", "200k", "-deadline", "realtime", os.path.join(d, "camera.webm")], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
                    "-c:a", "libopus", os.path.join(d, "mic.webm")], check=True)
    with open(os.path.join(d, "session.json"), "w") as f:
        json.dump(dict(id=name, slug="recording", title="My take", script=[], studio=False,
                       tracks=dict(camera=dict(file="camera.webm", start_ms=0), mic=dict(file="mic.webm", start_ms=0))), f)
    with open(os.path.join(d, "takes.json"), "w") as f:
        json.dump([], f)
    return d


@unittest.skipUnless(HAVE, "engine repo or ffmpeg not found")
class PickupRealTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        home = os.path.join(self.root, "home")
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([os.path.join(ENGINE, "lib"), TESTS]),
                   VSTUDIO_OUTPUT_TRANSCRIBER="_fake_asr:words", VSTUDIO_HOME=home)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "VSTUDIO_LLM_PROVIDER"):
            env.pop(k, None)
        self.patch = mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": os.path.join(self.root, "none"), "VSTUDIO_HOME": home})
        self.patch.start()
        self.take = session(home, "20261010-140200-recording", 4)
        self.pick = session(home, "20261010-140500-pickup", 3)
        data = os.path.join(self.root, "desk")
        self.h = History(data, Registry(data))
        self.runner = CliRunner(sys.executable, env)
        self.o = OU.Outputs(data, self.h, self.runner)
        self.env = env

    def tearDown(self):
        self.patch.stop()
        shutil.rmtree(self.root, True)

    def test_take_opens_in_the_editor_and_takes_a_pickup(self):
        out = subprocess.run([sys.executable, "-m", "vstudio.create", "--json", "record", "ingest", self.take, "--target", "edit"],
                             env=self.env, capture_output=True, text=True, check=True)
        res = json.loads(out.stdout)
        res = CreateApi(self.root, None)._after_ingest(res)
        self.assertEqual(res["item"], batch_id(self.take))
        self.assertEqual(res["clip"], "recording")
        self.assertIn(res["item"], [r["id"] for r in self.h.list()["items"]])            # in All projects
        doc = self.o.show(res["item"], res["clip"])
        self.assertEqual(doc["engine"], "real")
        self.assertEqual(doc["recording"]["session"], os.path.basename(self.take))
        self.assertEqual([w["w"] for w in doc["words"]], ["hello", "world", "again"])
        self.assertEqual(doc["pickups"], [])
        # refused: a folder outside the recordings, no spot, two spots, a bad range
        for kw in (dict(session_dir="/etc", at_word=1), dict(session_dir=self.pick),
                   dict(session_dir=self.pick, at_word=1, replace=[0, 1]), dict(session_dir=self.pick, replace=[2, 1])):
            with self.assertRaises(BadRequest):
                self.o.pickup(res["item"], res["clip"], kw.pop("session_dir"), **kw)
        r = self.o.pickup(res["item"], res["clip"], self.pick, at_word=1, sig=doc["words_sig"])
        self.assertEqual(r["step"]["ops"][0]["op"], "pickup")
        d2 = r["doc"]
        self.assertEqual(len(d2["pickups"]), 1)
        self.assertNotEqual(os.path.realpath(d2["file"]), os.path.realpath(doc["file"]))
        self.assertTrue(os.path.isfile(d2["file"]))
        self.assertGreater(d2["duration"], doc["duration"] + 1.0)
        self.assertEqual([w["w"] for w in d2["words"]], ["hello", "hello", "world", "again", "world", "again"])
        p = d2["pickups"][0]
        inside = [w["w"] for w in d2["words"] if p["start"] - 1e-3 <= (w["t"] + w["te"]) / 2 <= p["end"] + 1e-3]
        self.assertEqual(inside, ["hello", "world", "again"])
        # undo: the clip is back on the take itself
        self.o.undo(res["item"], res["clip"])
        d3 = self.o.show(res["item"], res["clip"])
        self.assertEqual(os.path.realpath(d3["file"]), os.path.realpath(doc["file"]))
        self.assertEqual(d3["pickups"], [])


if __name__ == "__main__":
    unittest.main()
