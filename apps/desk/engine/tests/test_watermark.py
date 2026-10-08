"""Settings › Watermark routes (desk_engine/watermark.py over vstudio.watermark) and the export's watermark choice
reaching the engine command (run: npm run test:engine)."""
import http.client
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401  (VSTUDIO_HOME / DESK_DATA_DIR -> a temp folder, first)

from desk_engine import outputs as OU  # noqa: E402
from desk_engine.app import serve  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402
from desk_mock import MockEngine, make_api  # noqa: E402

TOKEN = "w" * 48
ORIGIN = "app://desk"


class WatermarkApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.wm_file = os.path.join(cls.tmp, "wm", "watermark.json")
        cls.env = mock.patch.dict(os.environ, VSTUDIO_WATERMARK_FILE=cls.wm_file)
        cls.env.start()
        bus = EventBus()
        cls.engine = MockEngine(cls.tmp, Registry(cls.tmp), bus, step=0.01)
        cls.api = make_api(cls.engine, bus, TOKEN, [ORIGIN])
        cls.httpd = serve(cls.api)

    @classmethod
    def tearDownClass(cls):
        cls.engine.shutdown()
        cls.httpd.shutdown()
        cls.env.stop()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=30)
        h = {"Host": f"127.0.0.1:{self.api.port}", "Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None)

    def test_a_not_set_up_then_set_and_previewed(self):
        st, d = self.req("GET", "/api/watermark")
        self.assertEqual(st, 200, d)
        self.assertFalse(d["configured"])
        self.assertFalse(d["default_on"])
        self.assertEqual(set(d["previews"]), {"9:16", "16:9"})
        blank = d["previews"]["9:16"]
        self.assertTrue(blank.startswith("data:image/jpeg;base64,"))
        st, d = self.req("POST", "/api/watermark", dict(patch=dict(text="@me", default=True, position="top-left")))
        self.assertEqual(st, 200, d)
        self.assertTrue(d["configured"] and d["default_on"])
        self.assertEqual(d["settings"]["position"], "top-left")
        self.assertNotEqual(d["previews"]["9:16"], blank)            # the mark is drawn into the sample frame
        with open(self.wm_file, encoding="utf-8") as f:
            self.assertEqual(json.load(f), dict(text="@me", default=True, position="top-left"))
        st, d = self.req("GET", "/api/watermark?previews=0")
        self.assertNotIn("previews", d)
        self.assertEqual(d["settings"]["text"], "@me")

    def test_b_bad_patches_are_refused(self):
        for patch in (dict(position="middle"), dict(size=5), dict(nope=1), dict(image="/etc/passwd")):
            st, d = self.req("POST", "/api/watermark", dict(patch=patch))
            self.assertEqual(st, 400, (patch, d))
        st, _ = self.req("POST", "/api/watermark", dict(text="x"))
        self.assertEqual(st, 400)

    def test_c_logo(self):
        from PIL import Image
        p = os.path.join(self.tmp, "logo.png")
        Image.new("RGBA", (120, 60), (255, 0, 0, 200)).save(p)
        st, d = self.req("POST", "/api/watermark/logo", dict(path=p))
        self.assertEqual(st, 200, d)
        self.assertEqual(d["settings"]["kind"], "image")
        self.assertTrue(d["configured"] and d["logo"].startswith("logo-"))
        self.assertNotIn("image", d["settings"])                     # no raw paths back to the UI
        for bad in ("relative.png", os.path.join(self.tmp, "missing.png"), os.path.join(self.tmp, "x.txt")):
            st, _ = self.req("POST", "/api/watermark/logo", dict(path=bad))
            self.assertEqual(st, 400, bad)

    def test_d_export_choice_is_validated(self):
        st, d = self.req("POST", "/api/outputs/0123456789ab/clip/export", dict(targets=["primary"], watermark="yes"))
        self.assertEqual(st, 400, d)


class ExportCommandTest(unittest.TestCase):
    """The export's on / off reaches ``vstudio.project output render`` as --watermark; absent = her default."""

    def run_export(self, watermark):
        o = OU.Outputs.__new__(OU.Outputs)
        o.bus, o.history, o._jobs = None, mock.Mock(), {"j": {}}
        o.runner = mock.Mock()
        o.runner.sibling.return_value = mock.Mock(python="python3", env={})
        o._output_id = lambda e, c: "out1"
        o._publish = lambda *a: None
        seen = {}

        class P:
            stdout = iter(())
            returncode = 0

            def __init__(self, cmd, **kw):
                seen["cmd"] = cmd

            def wait(self):
                return 0
        import threading
        with mock.patch.object(OU.subprocess, "Popen", P):
            o._export_run("j", dict(dir="/p"), {}, "item", "clip", ["primary"], threading.Event(), watermark)
        return seen["cmd"]

    def test_flag(self):
        self.assertEqual(self.run_export(True)[-2:], ["--watermark", "on"])
        self.assertEqual(self.run_export(False)[-2:], ["--watermark", "off"])
        self.assertNotIn("--watermark", self.run_export(None))


if __name__ == "__main__":
    unittest.main()
