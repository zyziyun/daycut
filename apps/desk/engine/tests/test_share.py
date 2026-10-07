"""Share for review (desk side): the dialog options (clips, versions, privacy warnings incl. desk-side privacy
stickers), the build job (folder + zip, no local paths in the page), the privacy ack gate, feedback import ->
Inbox items (approve / change), answering (approve -> the clip shows approved), Undo, and the routes."""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "lib"))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from desk_engine.inbox import Inbox  # noqa: E402
from desk_engine.share import Share  # noqa: E402

HAVE = bool(shutil.which("ffmpeg")) and os.path.isdir(os.path.join(LIB, "vstudio", "project"))
POST = "# 发布文案\n\n## A_one.mp4\n\nOne title\n\nBody one.\n\n#tag\n\n## B_two.mp4\n\nTwo title\n\nBody two.\n"


def _clip(path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=180x240:rate=25:duration=1",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", path], check=True)


def code_of(share, rows, who="Mia"):
    raw = json.dumps(dict(k="rf", v=1, s=share, n=who, t="2026-10-07T10:00:00Z", c=rows), ensure_ascii=False)
    return "RFB1." + base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


@unittest.skipUnless(HAVE, "ffmpeg + the engine lib are needed")
class ShareTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.watch = os.path.join(self.root, "demos")
        self.d = os.path.join(self.watch, "week12")
        os.makedirs(os.path.join(self.d, "final"))
        for n in ("A_one", "B_two"):
            _clip(os.path.join(self.d, "final", f"{n}.mp4"))
        with open(os.path.join(self.d, "final", "post.md"), "w", encoding="utf-8") as f:
            f.write(POST)
        self.env = mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": self.watch,
                                                "VSTUDIO_HOME": os.path.join(self.root, "home")})
        self.env.start()
        data = os.path.join(self.root, "desk")
        self.bus = EventBus()
        self.h = History(data, Registry(data))
        self.o = OU.Outputs(data, self.h)
        self.inbox = Inbox(data, self.h)
        self.s = Share(data, self.h, self.o, self.inbox, self.bus)
        self.item = next(r["id"] for r in self.h.list()["items"] if r["dir"] == self.d)

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.root, ignore_errors=True)

    def _build(self, **b):
        j = self.s.start(self.item, dict(dict(quality="small"), **b))
        for _ in range(300):
            st = self.s.job(j["job"])
            if st["state"] != "running":
                return st
            time.sleep(0.05)
        self.fail("share job did not finish")

    def test_options_build_and_ack_gate(self):
        opt = self.s.options(self.item)
        self.assertEqual([c["id"] for c in opt["clips"]], ["A_one", "B_two"])
        self.assertEqual(opt["privacy"]["warnings"], [])
        st = self._build(clips=["B_two"], footer=False, expiry_note="Reply by Friday")
        self.assertEqual(st["state"], "done", st)
        r = st["result"]
        self.assertTrue(os.path.isfile(r["index"]) and os.path.isfile(r["zip"]))
        self.assertTrue(r["dir"].startswith(os.path.join(self.d, "review-links")))
        with open(r["json"], encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual([c["id"] for c in data["clips"]], ["B_two"])
        self.assertIn("Two title", data["clips"][0]["caption"])
        self.assertFalse(data["footer"])
        self.assertEqual(data["expiry_note"], "Reply by Friday")
        with open(r["index"], encoding="utf-8") as f:
            self.assertNotIn(self.root, f.read())
        # a privacy sticker on a clip (the engine's output edit document) needs an ack before anything is shared
        from vstudio.project import outputs as EO
        from vstudio.project import works
        works.adopt(self.d)
        row = next(r for r in EO.list_outputs(self.d)["outputs"] if r["id"].endswith("A_one.mp4"))
        os.makedirs(row["edit_dir"], exist_ok=True)
        with open(os.path.join(row["edit_dir"], "edit.json"), "w") as f:
            json.dump(dict(state=dict(effects=[dict(effect="privacy-sticker", start=0)])), f)
        opt = self.s.options(self.item)
        self.assertTrue(opt["privacy"]["needs_ack"])
        self.assertEqual(opt["privacy"]["warnings"][0]["code"], "masked-people")
        with self.assertRaises(Exception):
            self.s.start(self.item, dict(quality="small"))
        self.assertEqual(self._build(ack=True)["state"], "done")
        with self.assertRaises(Exception):
            self.s.start(self.item, dict(quality="8k"))

    def test_feedback_import_inbox_answer_and_undo(self):
        r = self._build()["result"]
        code = code_of(r["share"], [["A_one", "a", ""], ["B_two", "c", "0:01 too loud"]])
        imp = self.s.import_feedback(dict(text="Thanks!\n" + code))
        self.assertEqual((imp["items"], imp["duplicates"], imp["project"]), (2, 0, self.item))
        again = self.s.import_feedback(dict(text=code))
        self.assertEqual((again["items"], again["duplicates"]), (0, 2))
        items = {i["kind"]: i for i in self.inbox.list()["items"] if i["source"] == "feedback"}
        self.assertEqual(set(items), {"feedback-approve", "feedback-change"})
        ch = items["feedback-change"]
        self.assertEqual(ch["options"][0]["clip_id"], "B_two")
        self.assertEqual(ch["params"]["who"], "Mia")
        self.assertEqual(ch["text"], "0:01 too loud")
        chat = self.o.show(self.item, "B_two")["chat"]
        self.assertEqual((chat[-1]["status"], chat[-1]["text"]), ("note", "Mia: 0:01 too loud"))
        ap = items["feedback-approve"]
        self.inbox.answer([ap["key"]])
        a = next(c for c in self.o.clips(self.item)["clips"] if c["id"] == "A_one")
        self.assertEqual(a["state"], "approved")
        self.assertNotIn(ap["key"], [i["key"] for i in self.inbox.list()["items"]])
        self.inbox.undo([ap["key"]])
        a = next(c for c in self.o.clips(self.item)["clips"] if c["id"] == "A_one")
        self.assertEqual(a["state"], "done")
        self.assertIn(ap["key"], [i["key"] for i in self.inbox.list()["items"]])
        with self.assertRaises(OU.EngineMessage) as cm:
            self.s.import_feedback(dict(text="hello"))
        self.assertEqual(cm.exception.doc["code"], "bad-feedback")
        with self.assertRaises(OU.EngineMessage) as cm:
            self.s.import_feedback(dict(text=code_of("c" * 20, [["A_one", "a", ""]])))
        self.assertEqual(cm.exception.doc["code"], "unknown-share")

    def test_routes(self):
        from desk_engine.app import Api
        from desk_mock import MockEngine, make_api
        data = os.path.join(self.root, "desk2")
        api = make_api(MockEngine(data, Registry(data), self.bus, step=0.01), self.bus, "t" * 40, [])
        item = next(r["id"] for r in api.history.list()["items"] if r["dir"] == self.d)
        opt = api.route("GET", f"/api/share/{item}", {}, None)
        self.assertEqual(len(opt["clips"]), 2)
        j = api.route("POST", f"/api/share/{item}", {}, dict(quality="small", zip=False))
        for _ in range(300):
            st = api.route("GET", f"/api/share-jobs/{j['job']}", {}, None)
            if st["state"] != "running":
                break
            time.sleep(0.05)
        self.assertEqual(st["state"], "done", st)
        self.assertIsNone(st["result"]["zip"])
        r = api.route("POST", "/api/feedback/import", {}, dict(text=code_of(st["result"]["share"], [["B_two", "c", "x"]])))
        self.assertEqual(r["items"], 1)
        self.assertTrue(any(i["kind"] == "feedback-change" for i in api.route("GET", "/api/inbox", {}, None)["items"]))


if __name__ == "__main__":
    unittest.main()
