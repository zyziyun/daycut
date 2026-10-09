"""Project archive: archive / restore round trip (single + bulk), the Archived list, the running-job guard, the desk
list row coming back on restore, the HTTP routes, and older desks' ``hidden`` entries read as archived."""
import json
import os
import socket
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import common as C  # noqa: E402
from desk_engine import history as HI  # noqa: E402
from desk_engine.common import BadRequest, Registry  # noqa: E402
from test_history import make_batch  # noqa: E402


def make_project(d, name, with_state=True):
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "project.yaml"), "w", encoding="utf-8") as f:
        f.write(f"name: {name}\nrecipe: talkinghead\n")
    if with_state:
        make_batch(os.path.join(d, "state"), name=name)
    return d


def set_running(d):
    os.makedirs(os.path.join(d, ".vstudio"), exist_ok=True)
    with open(os.path.join(d, ".vstudio", "status.json"), "w") as f:
        json.dump(dict(status="running", stage="render", message="Rendering", heartbeat=time.time(),
                       pid=os.getpid(), host=socket.gethostname()), f)


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="arch-")
        self.data = os.path.join(self.root, "desk")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.env = mock.patch.dict(os.environ, {"VSTUDIO_HOME": self.home, "DESK_HISTORY_WATCH": ""})
        self.env.start()
        self.reg = Registry(self.data)
        self.h = HI.History(self.data, self.reg)
        self.w = os.path.join(self.root, "demos")
        self.a = make_batch(os.path.join(self.w, "batch-a"), name="a")
        self.b = make_batch(os.path.join(self.w, "batch-b"), name="b")
        self.p = make_project(os.path.join(self.root, "work", "proj"), "P")
        with open(os.path.join(self.home, "projects.json"), "w") as f:
            json.dump([dict(dir=self.p, name="P", recipe="talkinghead")], f)
        self.h.set_watch([self.w])

    def tearDown(self):
        self.env.stop()

    def names(self, **kw):
        return sorted(i["name"] for i in self.h.list(**kw)["items"])

    def test_round_trip_keeps_files_and_rows(self):
        before = {i["name"]: i for i in self.h.list()["items"]}
        self.assertEqual(sorted(before), ["P", "a", "b"])
        r = self.h.archive([self.a])
        self.assertEqual(r["archived"], [os.path.realpath(self.a)])
        self.assertFalse(r["deleted"])
        doc = self.h.list()
        self.assertEqual(sorted(i["name"] for i in doc["items"]), ["P", "b"])
        self.assertEqual(doc["archived"], 1)
        arch = self.h.list(archived=True)["items"]
        self.assertEqual([i["name"] for i in arch], ["a"])
        self.assertTrue(arch[0]["archived"])
        self.assertAlmostEqual(arch[0]["archived_at"], r["at"], places=3)
        self.assertEqual(arch[0]["id"], before["a"]["id"])           # same row shape / id
        self.assertTrue(os.path.exists(os.path.join(self.a, "batch.db")))
        self.h.restore([self.a])
        after = {i["name"]: i for i in self.h.list()["items"]}
        self.assertEqual(sorted(after), ["P", "a", "b"])
        self.assertNotIn("archived", after["a"])
        for k in ("id", "dir", "status", "counts", "openable", "opened", "kind"):
            self.assertEqual(after["a"][k], before["a"][k], k)
        self.assertEqual(self.h.list(archived=True)["items"], [])
        cfg = json.load(open(os.path.join(self.data, "history.json")))
        self.assertEqual((cfg["hidden"], cfg["archived_at"]), ([], {}))

    def test_bulk_and_search_in_archived(self):
        self.h.archive([self.a, self.b, self.p])
        self.assertEqual(self.h.list()["items"], [])
        self.assertEqual(self.h.list()["archived"], 3)
        self.assertEqual(self.names(archived=True), ["P", "a", "b"])
        self.assertEqual(self.names(archived=True, q="batch-b"), ["b"])
        self.assertEqual(self.names(archived=True, kind="project"), ["P"])
        self.h.restore([self.a, self.p])
        self.assertEqual(self.names(), ["P", "a"])
        self.assertEqual(self.names(archived=True), ["b"])

    def test_restore_puts_the_desk_list_row_back(self):
        opened = self.h.open(self.p)                 # the project's run store on the desk list (the board / page)
        self.assertEqual(opened["dir"], os.path.join(self.p, "state"))
        bid = opened["id"]
        row = next(i for i in self.h.list()["items"] if i["name"] == "P")
        self.assertTrue(row["opened"])
        self.h.archive([self.p])
        self.assertIsNone(self.reg.get(bid))
        # an archived project still opens: find() reaches it
        self.assertEqual(self.h.find(row["id"])["name"], "P")
        self.assertTrue(self.h.find(row["id"])["archived"])
        self.h.restore([self.p])
        self.assertTrue(self.reg.get(bid))           # the board finds its batch again
        back = next(i for i in self.h.list()["items"] if i["name"] == "P")
        self.assertTrue(back["opened"])
        self.assertEqual(back["id"], row["id"])

    def test_desk_only_batch_listed_while_archived(self):
        d = make_batch(os.path.join(self.root, "elsewhere", "batch-d"), name="desk-only")
        self.reg.add(d, "desk-only")
        self.h.archive([d])
        self.assertIsNone(self.reg.get(C.batch_id(d)))
        self.assertIn("desk-only", self.names(archived=True))          # only the parked row still knows it
        self.assertNotIn("desk-only", self.names())
        self.h.restore([d])
        self.assertTrue(self.reg.get(C.batch_id(d)))
        self.assertIn("desk-only", self.names())

    def test_open_keeps_it_archived(self):
        self.h.archive([self.p])
        self.h.open(self.p)
        self.assertEqual(self.names(archived=True), ["P"])
        self.assertNotIn("P", self.names())
        self.h.restore([self.p])
        self.assertIn("P", self.names())

    def test_running_job_refused_nothing_archived(self):
        set_running(self.a)
        with self.assertRaises(BadRequest) as cm:
            self.h.archive([self.b, self.a])
        self.assertIn("still running", str(cm.exception))
        self.assertIn("batch-a", str(cm.exception))
        self.assertEqual(self.names(), ["P", "a", "b"])                 # all or nothing
        self.assertEqual(self.h.list()["archived"], 0)
        with self.assertRaises(BadRequest):
            self.h.hide(self.a)                                          # the old route too
        set_running(os.path.join(self.p, "state"))                       # a project's run store
        with self.assertRaises(BadRequest):
            self.h.archive([self.p])

    def test_engine_run_refused(self):
        eng = mock.Mock()
        eng.running.side_effect = lambda bid: bid == C.batch_id(self.b)
        h = HI.History(self.data, self.reg, eng)
        with self.assertRaises(BadRequest):
            h.archive([self.b])
        h.archive([self.a])
        self.assertEqual(self.names(archived=True), ["a"])

    def test_old_hidden_entries_read_as_archived(self):
        with open(os.path.join(self.data, "history.json"), "w") as f:   # written by an older desk
            json.dump(dict(watch=[self.w], hidden=[os.path.realpath(self.b)]), f)
        self.assertEqual(self.names(), ["P", "a"])
        arch = self.h.list(archived=True)["items"]
        self.assertEqual([i["name"] for i in arch], ["b"])
        self.assertTrue(arch[0]["archived"])
        self.assertIsNone(arch[0]["archived_at"])                       # unknown date, still listed
        self.h.unhide(self.b)                                           # the old route alias
        self.assertEqual(self.names(), ["P", "a", "b"])
        self.h.hide(self.a)
        cfg = json.load(open(os.path.join(self.data, "history.json")))
        self.assertEqual(cfg["hidden"], [os.path.realpath(self.a)])     # still the ``hidden`` key
        self.assertIn(os.path.realpath(self.a), cfg["archived_at"])
        self.h.unhide_all()
        self.assertEqual(self.names(), ["P", "a", "b"])

    def test_routes(self):
        from desk_engine.common import EventBus
        from desk_mock import MockEngine, make_api
        bus = EventBus()
        tmp = tempfile.mkdtemp(prefix="arch-api-")
        eng = MockEngine(tmp, Registry(tmp), bus, step=0.005)
        api = make_api(eng, bus, "t" * 48, [])

        def R(m, path, body=None, q=None):
            return api.route(m, path, {k: [v] for k, v in (q or {}).items()}, body)
        R("POST", "/api/history/config", dict(watch=[self.w]))
        mine = lambda q=None: sorted(i["name"] for i in R("GET", "/api/history", q=q)["items"] if i["dir"].startswith(self.w))  # noqa: E731
        self.assertEqual(mine(), ["a", "b"])
        R("POST", "/api/history/archive", dict(dirs=[self.a, self.b]))
        self.assertEqual(mine(), [])
        self.assertEqual(R("GET", "/api/history")["archived"], 2)
        self.assertEqual(mine(dict(archived="1")), ["a", "b"])
        R("POST", "/api/history/restore", dict(dir=self.a))
        self.assertEqual(mine(), ["a"])
        R("POST", "/api/history/unhide-one", dict(dir=self.b))           # old alias
        R("POST", "/api/history/hide", dict(dir=self.b))                 # old alias
        self.assertEqual(mine(dict(archived="1")), ["b"])
        R("POST", "/api/history/restore", dict(dirs=[self.b]))
        self.assertEqual(mine(), ["a", "b"])
        with self.assertRaises(BadRequest):
            R("POST", "/api/history/archive", dict(dirs=[]))
        with self.assertRaises(BadRequest):
            R("POST", "/api/history/archive", dict(dir="relative/path"))
        with self.assertRaises(BadRequest):
            R("GET", "/api/history", q=dict(archived="yes"))
        set_running(self.a)
        with self.assertRaisesRegex(BadRequest, "still running"):
            R("POST", "/api/history/archive", dict(dir=self.a))

if __name__ == "__main__":
    unittest.main()
