"""Engine API tests against the mock engine (stdlib unittest; run: npm run test:engine)."""
import http.client
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401  (VSTUDIO_HOME / DESK_DATA_DIR -> a temp folder, first)

from desk_engine.app import Api, serve, validate_create, validate_decisions  # noqa: E402
from desk_engine.common import BadRequest, EventBus, Registry  # noqa: E402
from desk_engine.mock import MockEngine  # noqa: E402
from desk_engine.real import _parse_reply_local, verify_manifest  # noqa: E402

TOKEN = "t" * 48
ORIGIN = "app://desk"


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        bus = EventBus()
        cls.engine = MockEngine(cls.tmp, Registry(cls.tmp), bus, step=0.01)
        cls.api = Api(cls.engine, bus, TOKEN, [ORIGIN])
        cls.httpd = serve(cls.api)

    @classmethod
    def tearDownClass(cls):
        cls.engine.shutdown()
        cls.httpd.shutdown()

    def req(self, method, path, body=None, token=TOKEN, origin=ORIGIN, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.api.port}"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        if origin:
            h["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        return r.status, (json.loads(raw) if raw else None), dict(r.getheaders())

    def test_auth_required(self):
        self.assertEqual(self.req("GET", "/api/health", token=None)[0], 401)
        self.assertEqual(self.req("GET", "/api/health", token="x" * 48)[0], 401)
        st, body, hdr = self.req("GET", "/api/health")
        self.assertEqual(st, 200)
        self.assertEqual(body["mode"], "mock")
        self.assertEqual(hdr.get("Access-Control-Allow-Origin"), ORIGIN)

    def test_origin_and_host_guard(self):
        self.assertEqual(self.req("GET", "/api/health", origin="https://evil.example")[0], 403)
        self.assertEqual(self.req("GET", "/api/health", host="evil.example:80")[0], 421)

    def test_validation(self):
        st, body, _ = self.req("POST", "/api/batches", dict(name="../x", recipe="longform-slices"))
        self.assertEqual(st, 400)
        with self.assertRaises(BadRequest):
            validate_create(dict(name="ok", recipe="talkinghead-clips", folder="relative/path", platforms=["tiktok"]))
        with self.assertRaises(BadRequest):
            validate_decisions(dict(decisions={"s001": dict(decision="publish")}))
        st, _, _ = self.req("GET", "/api/batches/notanid")
        self.assertEqual(st, 400)

    def test_pilot_review_package_flow(self):
        folder = tempfile.mkdtemp()
        st, b, _ = self.req("POST", "/api/batches", dict(name="t1", recipe="talkinghead-clips", folder=folder,
                                                          platforms=["tiktok:vertical"], budget=dict(max_hours=5)))
        self.assertEqual(st, 200, b)
        bid = b["id"]
        st, est, _ = self.req("GET", f"/api/batches/{bid}/estimate")
        self.assertTrue(est["budget"]["ok"])
        st, r, _ = self.req("POST", f"/api/batches/{bid}/run", dict(pilot=2))
        self.assertTrue(r["started"])
        for _ in range(200):
            _, s, _ = self.req("GET", f"/api/batches/{bid}")
            if s["meta"]["state"] == "pilot-review":
                break
            time.sleep(0.05)
        self.assertEqual(s["meta"]["state"], "pilot-review")
        _, r, _ = self.req("POST", f"/api/batches/{bid}/run", {})
        self.assertEqual(r["status"], "pilot-waits")                    # full run needs confirm_pilot
        _, items, _ = self.req("GET", f"/api/batches/{bid}/review")
        self.assertEqual(len(items), 2)
        st, r, _ = self.req("POST", f"/api/batches/{bid}/review/apply",
                            dict(decisions={"s001": dict(decision="approve"), "s002": dict(decision="reject",
                                                                                         reason="hook too slow")}))
        self.assertEqual(r["approved"], ["s001"])
        self.assertEqual(r["rejected"], ["s002"])
        st, p, _ = self.req("POST", f"/api/batches/{bid}/package", dict(per_day=1))
        self.assertEqual(st, 200, p)
        _, m, _ = self.req("GET", f"/api/batches/{bid}/package")
        self.assertTrue(m["verify"]["ok"])
        self.assertEqual(m["verify"]["code"], p["code"])
        # tamper -> code mismatch
        man = dict(m["manifest"])
        man["items"] = [dict(man["items"][0], title="changed")]
        self.assertFalse(verify_manifest(man)["ok"])

    def test_job_detail_cleanup_state(self):
        bid = next(b["id"] for b in self.engine.list_batches() if b["name"] == "demo-course")
        _, j, _ = self.req("GET", f"/api/batches/{bid}/jobs/s003")
        edits = {e["id"]: e for e in j["cleanup"]["parts"][0]["edits"]}
        self.assertTrue(edits[1]["cut"])           # auto
        self.assertFalse(edits[2]["cut"])          # confirm, not approved yet

    def test_parse_reply(self):
        r = _parse_reply_local("确认 2,3 / 保留 1")
        self.assertEqual(r["approve"], {2, 3})
        self.assertEqual(r["keep"], {1})
        self.assertTrue(_parse_reply_local("全部确认")["all_confirm"])


if __name__ == "__main__":
    unittest.main()
