"""Create page routes (/api/create/*) in mock mode: validation (bad ids / sources / money -> 400), the sample
series, plan -> series, 409 create.confirm-required for a finals run without a code, the full fake run ->
takes -> hand-off into the history + calendar, roots, inbox items. Fake services only."""
import http.client
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "lib"))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import _isolate  # noqa: E402,F401

from desk_engine.app import Api, serve  # noqa: E402
from desk_engine.common import EventBus, Registry  # noqa: E402
from desk_mock import MockEngine, make_api  # noqa: E402

TOKEN = "c" * 48
ORIGIN = "app://desk"


class CreateRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        bus = EventBus()
        cls.engine = MockEngine(cls.tmp, Registry(cls.tmp), bus, step=0.01)
        cls.api = make_api(cls.engine, bus, TOKEN, [ORIGIN])
        cls.httpd = serve(cls.api)

    @classmethod
    def tearDownClass(cls):
        cls.engine.shutdown()
        cls.httpd.shutdown()

    def req(self, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", self.api.port, timeout=60)
        h = {"Host": f"127.0.0.1:{self.api.port}", "Authorization": f"Bearer {TOKEN}", "Origin": ORIGIN}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        return r.status, json.loads(r.read() or b"null")

    def wait(self, jid, limit=120):
        t0 = time.time()
        while time.time() - t0 < limit:
            st, j = self.req("GET", f"/api/create/jobs/{jid}")
            self.assertEqual(st, 200)
            if j["state"] != "running":
                return j
            time.sleep(0.1)
        self.fail("job did not finish")

    def sample(self):
        st, r = self.req("POST", "/api/create/sample", {"lang": "en"})
        self.assertEqual(st, 200, r)
        return r["series"], r["episode"]

    def test_01_idle_until_called(self):
        self.assertEqual(self.api.create.roots(), [])
        self.assertEqual(self.api.create.inbox_items(), [])

    def test_formats_and_providers(self):
        st, r = self.req("GET", "/api/create/formats")
        self.assertEqual(st, 200)
        self.assertEqual(len(r["formats"]), 6)
        st, r = self.req("GET", "/api/create/providers")
        self.assertEqual(st, 200)
        ids = [p["id"] for p in r["providers"]]
        self.assertIn("kling-mcp", ids)
        self.assertIn("jimeng", ids)

    def test_validation(self):
        for path, body in [("/api/create/episodes/BAD!/shots/07", {"source": "record"}),
                           ("/api/create/episodes/x-e01/shots/7a", {"source": "record"}),
                           ("/api/create/episodes/x-e01/shots/07", {"source": "https://evil.example/x"}),
                           ("/api/create/episodes/x-e01/shots/07", {"source": "cloud:kling mcp"}),
                           ("/api/create/spend/cap", {"cap_cny": -1}),
                           ("/api/create/spend/cap", {"cap_cny": 10 ** 9}),
                           ("/api/create/plan", {}),
                           ("/api/create/plan", {"prompt": "x", "format": "anime-drama"}),
                           ("/api/create/series/../ideas", {"n": 2}),
                           ("/api/create/record/ingest", {"session_dir": "/etc"})]:
            st, r = self.req("POST", path, body)
            self.assertEqual(st, 400, (path, body, r))

    def test_finals_without_code_is_409(self):
        sid, eid = self.sample()
        st, r = self.req("POST", f"/api/create/episodes/{eid}/run", {"stage": "finals"})
        self.assertEqual(st, 409)
        self.assertEqual(r["code"], "create.confirm-required")
        st, r = self.req("POST", f"/api/create/episodes/{eid}/run",
                         {"stage": "finals", "estimate_id": "est-0123456789", "confirm_code": "deadbeef",
                          "max_cny": 50})
        self.assertEqual(st, 409)
        self.assertEqual(r["code"], "create.confirm-required")

    def test_plan_to_series(self):
        st, r = self.req("POST", "/api/create/plan", {"prompt": "3-episode comedy sketch about a robot barista",
                                                      "budget_cny": 60, "lang": "en"})
        self.assertEqual(st, 200)
        j = self.wait(r["job"])
        self.assertEqual(j["state"], "done", j)
        draft = j["result"]["draft"]
        self.assertEqual(draft["format"], "sketch")
        st, r = self.req("POST", "/api/create/series", {"draft": draft})
        self.assertEqual(st, 200, r)
        sid = r["series"]
        st, v = self.req("GET", f"/api/create/series/{sid}")
        self.assertEqual(v["format"]["id"], "sketch")
        st, r = self.req("POST", f"/api/create/series/{sid}/episodes", {"idea_ids": ["i1", "i2"]})
        j = self.wait(r["job"])
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(len(j["result"]["episodes"]), 2)

    def test_full_fake_run_to_handoff(self):
        sid, eid = self.sample()
        st, v = self.req("GET", f"/api/create/episodes/{eid}")
        self.assertEqual(st, 200)
        self.assertEqual(len(v["shots"]), 18)
        st, v = self.req("POST", f"/api/create/episodes/{eid}/shots/07", {"source": "cloud:minimax/MiniMax-Hailuo-02"})
        self.assertEqual(st, 200)
        self.assertTrue(any(w["code"] == "create.route.character-split" for w in v["warnings"]))
        self.req("POST", f"/api/create/episodes/{eid}/shots/07", {"source": "cloud:kling-mcp/kling-video-v3_0_omni"})
        st, est = self.req("GET", f"/api/create/episodes/{eid}/estimate?stage=finals")
        self.assertEqual(st, 200)
        st, r = self.req("POST", f"/api/create/episodes/{eid}/run",
                         {"stage": "finals", "estimate_id": est["id"], "confirm_code": est["confirm_code"],
                          "max_cny": est["max_cny"]})
        self.assertEqual(st, 200, r)
        j = self.wait(r["job"])
        self.assertEqual(j["state"], "done", j)
        st, m = self.req("GET", f"/api/create/runs?series={sid}")
        row = m["rows"][0]
        self.assertTrue(row["pick"] > 0)
        self.assertTrue(any(i["code"] == "create.pick-takes" for i in self.api.create.inbox_items()))
        st, v = self.req("GET", f"/api/create/episodes/{eid}")
        for s in v["shots"]:
            if len(s["takes"]) > 1:
                st, r = self.req("POST", f"/api/create/episodes/{eid}/takes/{s['no']}", {"take": s["takes"][0]["file"]})
                self.assertEqual(st, 200, r)
        st, r = self.req("POST", f"/api/create/episodes/{eid}/handoff", {"languages": ["en", "zh"], "schedule": True})
        j = self.wait(r["job"], limit=300)
        self.assertEqual(j["state"], "done", j)
        res = j["result"]
        self.assertTrue(res["project_id"])
        st, clips = self.req("GET", f"/api/outputs/{res['project_id']}")
        self.assertEqual(st, 200, clips)
        self.assertTrue(any(c["id"] == res["clip"] for c in clips["clips"]))
        self.assertTrue(res["calendar"] and all("error" not in p for p in res["calendar"]), res["calendar"])
        roots = self.api.roots()
        self.assertTrue(any(r.startswith(self.api.create.mock_home()) for r in roots))
        st, sp = self.req("GET", f"/api/create/spend?series={sid}")
        self.assertGreater(sp["series"]["spent"], 0)
        self.assertLessEqual(sp["series"]["spent"], est["max_cny"])


if __name__ == "__main__":
    unittest.main()


class CreateRealModeTest(unittest.TestCase):
    """Real mode = the engine CLI (python -m vstudio.create --json) in a subprocess, like the packaged app. No keys
    are set, so a paid run must be refused (service not connected) - nothing can be spent."""

    def setUp(self):
        from desk_engine.caps import CliRunner, runner_env
        from desk_engine.create import CreateApi
        self.home = tempfile.mkdtemp()
        env = runner_env(os.path.abspath(os.path.join(LIB, "..")))
        env.update(VSTUDIO_HOME=self.home, VSTUDIO_CREATE_NO_LLM="1")
        for k in ("KLING_MCP_TOKEN", "MINIMAX_API_KEY", "GEMINI_API_KEY", "ARK_API_KEY", "VSTUDIO_CREATE_FAKE"):
            env.pop(k, None)
        self.api = CreateApi(tempfile.mkdtemp(), EventBus(), CliRunner(sys.executable, env), "real")

    def test_cli_path_and_refusal(self):
        r = self.api.route("POST", ["sample"], {}, {"lang": "en"})
        eid = r["episode"]
        v = self.api.route("GET", ["episodes", eid], {}, None)
        self.assertEqual(len(v["shots"]), 18)
        self.assertEqual(v["connected"], [])
        est = self.api.route("GET", ["episodes", eid, "estimate"], {"stage": ["finals"]}, None)
        from desk_engine.create import Refused
        with self.assertRaises(Refused) as e:
            self.api.route("POST", ["episodes", eid, "run"], {}, {"stage": "finals", "estimate_id": est["id"],
                                                                  "confirm_code": est["confirm_code"],
                                                                  "max_cny": est["max_cny"]})
        self.assertEqual(e.exception.status, 409)
        self.assertEqual(e.exception.doc["code"], "create.provider-not-ready")
        led = os.path.join(self.home, "series", r["series"], "spend.jsonl")
        self.assertFalse(os.path.exists(led))           # nothing submitted, nothing in the ledger
        j = self.api.route("POST", ["episodes", eid, "run"], {}, {"stage": "animatic"})
        t0 = time.time()
        while self.api.get_job(j["job"])["state"] == "running" and time.time() - t0 < 120:
            time.sleep(0.2)
        self.assertEqual(self.api.get_job(j["job"])["state"], "done", self.api.get_job(j["job"]))
