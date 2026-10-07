"""Create plugin routes (/api/create/plugins, import, import-board, make) over HTTP in mock mode (fake video services,
temp profile): list + toggle plugins, import the HyperFrames fixture as a new series, replace an episode's board
with a CSV shot list, make agent shots with a fake agent CLI plugin in 2 lanes -> takes, inbox items for failures,
validation (bad keys / paths / lanes -> 400)."""
import http.client
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIB = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "lib"))
if LIB not in sys.path:
    sys.path.insert(0, LIB)

import _isolate  # noqa: E402,F401

PLUGS = tempfile.mkdtemp(prefix="desk-plugs-")
os.environ["VSTUDIO_PLUGINS_PATH"] = PLUGS
FIX = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "tests", "fixtures", "plugins",
                                   "hyperframes-tiny"))

from desk_engine.app import Api, serve  # noqa: E402
from desk_engine.common import EventBus  # noqa: E402
from desk_engine.common import Registry  # noqa: E402
from desk_mock import MockEngine, make_api  # noqa: E402

TOKEN = "p" * 48
ORIGIN = "app://desk"
AGENT = """#!/bin/sh
d="$1"
sleep 0.3
ffmpeg -v error -y -f lavfi -i color=c=blue:s=64x112:d=0.3 -pix_fmt yuv420p "$d/outputs/take.mp4"
"""


class CreatePluginRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = os.path.join(PLUGS, "fake-agent")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "plugin.yaml"), "w") as f:
            f.write('id: fake-agent\nkind: agent-runner\nname: Fake agent\nversion: 0.1.0\napi: 1\n'
                    'command: [./agent, "{job_dir}"]\npermissions: [write-job, "exec:agent"]\ncost: {kind: local}\n'
                    'concurrency: 2\ntimeout_s: 60\n')
        with open(os.path.join(d, "agent"), "w") as f:
            f.write(AGENT)
        os.chmod(os.path.join(d, "agent"), 0o755 | stat.S_IEXEC)
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
            if j["state"] != "running":
                return j
            time.sleep(0.1)
        self.fail("job did not finish")

    def plugins(self):
        st, r = self.req("GET", "/api/create/plugins?lang=zh")
        self.assertEqual(st, 200, r)
        return {p["key"]: p for p in r["plugins"]}

    def test_a_list_and_toggle(self):
        ps = self.plugins()
        self.assertTrue(ps["importer:hyperframes"]["enabled"])
        self.assertEqual(ps["importer:hyperframes"]["label"], "HyperFrames")
        self.assertEqual(ps["shot-provider:kling-mcp"]["cost"]["kind"], "paid")
        self.assertFalse(ps["agent-runner:fake-agent"]["enabled"])               # third-party: off until turned on
        st, r = self.req("POST", "/api/create/plugins/importer:timeline", {"enabled": False})
        self.assertEqual(st, 200, r)
        self.assertFalse(self.plugins()["importer:timeline"]["enabled"])
        self.req("POST", "/api/create/plugins/importer:timeline", {"enabled": True})
        st, r = self.req("POST", "/api/create/plugins/agent-runner:shell", {"settings": {"command": ["echo", "{job_dir}"], "lanes": 3}})
        self.assertEqual(st, 200, r)

    def test_validation(self):
        for path, body in [("/api/create/plugins/nope", {"enabled": True}),
                           ("/api/create/plugins/importer:Bad", {"enabled": True}),
                           ("/api/create/plugins/importer:shotlist", {"enabled": "yes"}),
                           ("/api/create/plugins/agent-runner:shell", {"settings": {"command": "rm -rf /"}}),
                           ("/api/create/plugins/agent-runner:shell", {"settings": {"lanes": 99}}),
                           ("/api/create/import", {"path": "relative/board.csv"}),
                           ("/api/create/import", {"path": FIX, "format": "anime"}),
                           ("/api/create/episodes/x-e01/make", {"lanes": 0}),
                           ("/api/create/episodes/x-e01/make", {"only": ["7a"]})]:
            st, r = self.req("POST", path, body)
            self.assertEqual(st, 400, (path, body, r))

    def test_import_hyperframes_then_board_then_make_agents(self):
        st, r = self.req("POST", "/api/create/import/sniff", {"path": FIX})
        self.assertEqual(r["importers"][0]["id"], "hyperframes")
        st, r = self.req("POST", "/api/create/import", {"path": FIX, "lang": "en"})
        self.assertEqual(st, 200, r)
        j = self.wait(r["job"])
        self.assertEqual(j["state"], "done", j)
        eid = j["result"]["episode"]
        self.assertEqual((j["result"]["n"], j["result"]["importer"]), (3, "hyperframes"))
        st, v = self.req("GET", f"/api/create/episodes/{eid}")
        self.assertEqual([s["route"]["source"] for s in v["shots"]][:2], ["plugin:hyperframes"] * 2)
        self.assertEqual(v["next"]["step"], "make")
        # replace the board with a CSV shot list routed to the fake agent
        csv = os.path.join(self.tmp, "shots.csv")
        with open(csv, "w") as f:
            f.write("shot,duration,action,source\n1,2,Cup,agent:fake-agent\n2,2,Pour,agent:fake-agent\n"
                    "3,2,Sip,agent:fake-agent\n")
        st, r = self.req("POST", f"/api/create/episodes/{eid}/import-board", {"path": csv})
        j = self.wait(r["job"])
        self.assertEqual(j["state"], "done", j)
        st, v = self.req("GET", f"/api/create/episodes/{eid}")
        self.assertEqual(len(v["shots"]), 3)
        # the agent plugin is off: the make reports it, nothing runs
        st, r = self.req("POST", f"/api/create/episodes/{eid}/make", {})
        j = self.wait(r["job"])
        self.assertEqual(j["result"]["units"]["01"]["code"], "create.plugin.disabled")
        self.req("POST", "/api/create/plugins/agent-runner:fake-agent", {"enabled": True})
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not installed")
        if os.name == "nt":
            self.skipTest("the fake agent is a POSIX shell script")
        st, r = self.req("POST", f"/api/create/episodes/{eid}/make", {"lanes": 2})
        j = self.wait(r["job"])
        self.assertEqual(j["state"], "done", j)
        self.assertEqual(j["result"]["lanes"], {"fake-agent": 2})
        self.assertEqual({u["state"] for u in j["result"]["units"].values()}, {"done"})
        st, v = self.req("GET", f"/api/create/episodes/{eid}")
        self.assertTrue(all(len(s["takes"]) == 1 and s["pick"] for s in v["shots"]))
        self.assertTrue(any(e.get("stage") == "make" for e in j["events"]))
        st, m = self.req("GET", "/api/create/runs")
        row = next(x for x in m["rows"] if x["id"] == eid)
        self.assertEqual((row["make"]["done"], row["make"]["total"]), (3, 3))
        # a failing agent on shot 02 -> failed with the reason -> an Inbox item
        bad = os.path.join(PLUGS, "bad-agent")
        os.makedirs(bad, exist_ok=True)
        with open(os.path.join(bad, "plugin.yaml"), "w") as f:
            f.write('id: bad-agent\nkind: agent-runner\nversion: 0.1.0\napi: 1\ncommand: [./agent]\n')
        with open(os.path.join(bad, "agent"), "w") as f:
            f.write("#!/bin/sh\necho 'model refused' >&2\nexit 2\n")
        os.chmod(os.path.join(bad, "agent"), 0o755)
        self.req("POST", "/api/create/plugins/agent-runner:bad-agent", {"enabled": True})
        st, v = self.req("POST", f"/api/create/episodes/{eid}/shots/02", {"source": "agent:bad-agent"})
        self.assertEqual(st, 200, v)
        st, r = self.req("POST", f"/api/create/episodes/{eid}/make", {"only": ["02"]})
        j = self.wait(r["job"])
        self.assertEqual(j["result"]["units"]["02"]["code"], "create.agent.failed")
        self.api.create._inbox_cache = (0.0, [])
        items = [i for i in self.api.create.inbox_items() if i["code"] == "create.agent.failed"]
        self.assertEqual(len(items), 1)
        self.assertIn("model refused", items[0]["params"]["error"])


if __name__ == "__main__":
    unittest.main()
