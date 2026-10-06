"""History: discovery of past work (desk + engine registries, projects, watched folders), read-only summaries,
hide (never deletes), open, and registry hygiene (missing / temp-dir entries pruned)."""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import common as C  # noqa: E402
from desk_engine import history as HI  # noqa: E402
from desk_engine.common import Registry  # noqa: E402


def make_batch(d, name="b", recipe="longform-split", jobs=(("ep01", "done", "green"), ("ep02", "failed", "red")),
               client=None, delivered=False, sheet=True):
    os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(os.path.join(d, "batch.db"))
    con.executescript("""CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE jobs (id TEXT PRIMARY KEY, ord INTEGER, recipe TEXT, item TEXT, variant TEXT, params TEXT,
          state TEXT, qc TEXT, qc_reasons TEXT, sample INTEGER, review TEXT, review_reason TEXT, pilot INTEGER,
          cost REAL, created REAL, updated REAL);
        CREATE TABLE deliveries (n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, client TEXT, dir TEXT, zip TEXT,
          code TEXT, items INTEGER, jobs INTEGER, duration REAL, cleanup_due REAL, cleaned REAL, sources TEXT);""")
    spec = dict(name=name, recipe=recipe)
    if client:
        spec["client"] = f"/x/clients/{client}"
    con.execute("INSERT INTO meta VALUES ('spec', ?)", (json.dumps(spec),))
    for i, (jid, st, qc) in enumerate(jobs):
        con.execute("INSERT INTO jobs(id, ord, state, qc, created, updated) VALUES (?,?,?,?,?,?)",
                    (jid, i, st, qc, 1000.0 + i, 2000.0 + i))
        if sheet:
            os.makedirs(os.path.join(d, "jobs", jid, "preview"), exist_ok=True)
            open(os.path.join(d, "jobs", jid, "preview", "sheet.jpg"), "wb").close()
    if delivered:
        con.execute("INSERT INTO deliveries(ts, client) VALUES (1, 'self')")
    con.commit()
    con.close()
    return d


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hist-")
        self.data = os.path.join(self.root, "desk")
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.env = mock.patch.dict(os.environ, {"VSTUDIO_HOME": self.home, "DESK_HISTORY_WATCH": ""})
        self.env.start()
        self.reg = Registry(self.data)
        self.h = HI.History(self.data, self.reg)

    def tearDown(self):
        self.env.stop()

    def test_watch_folder_scan_depth_and_summary(self):
        w = os.path.join(self.root, "demos")
        make_batch(os.path.join(w, "batch-rag"), name="rag", client="self", delivered=True)
        make_batch(os.path.join(w, "client-a", "batch-x"), name="x")          # level 2
        make_batch(os.path.join(w, "a", "b", "batch-deep"), name="deep")       # level 3: not scanned
        os.makedirs(os.path.join(w, "proj"))
        with open(os.path.join(w, "proj", "project.yaml"), "w") as f:
            f.write("name: 我的项目\nrecipe: promo\nclient: acme\n")
        self.h.set_watch([w])
        r = self.h.list()
        names = sorted(i["name"] for i in r["items"])
        self.assertEqual(names, ["rag", "x", "我的项目"])
        rag = next(i for i in r["items"] if i["name"] == "rag")
        self.assertEqual(rag["status"], "delivered")
        self.assertEqual(rag["client"], "self")
        self.assertEqual(rag["recipe"], "longform-split")
        self.assertEqual(rag["counts"]["total"], 2)
        self.assertEqual(rag["counts"]["red"], 1)
        self.assertTrue(rag["thumb"].endswith(os.path.join("ep01", "preview", "sheet.jpg")))
        self.assertEqual(rag["sources"], ["watch"])
        proj = next(i for i in r["items"] if i["kind"] == "project")
        self.assertEqual((proj["recipe"], proj["client"], proj["openable"]), ("promo", "acme", False))
        self.assertIn(os.path.join(w, "batch-rag", "jobs"), self.h.roots())
        # search / filter
        self.assertEqual([i["name"] for i in self.h.list(q="RAG")["items"]], ["rag"])
        self.assertEqual([i["name"] for i in self.h.list(status="delivered")["items"]], ["rag"])
        self.assertEqual([i["name"] for i in self.h.list(kind="project")["items"]], ["我的项目"])

    def test_engine_registries_and_dedupe(self):
        b = make_batch(os.path.join(self.root, "work", "batch-a"), name="a")
        p = os.path.join(self.root, "work", "proj")
        make_batch(os.path.join(p, "state"), name="p-state")
        with open(os.path.join(p, "project.yaml"), "w") as f:
            f.write("name: P\nrecipe: talkinghead\n")
        with open(os.path.join(self.home, "batches.json"), "w") as f:
            json.dump([dict(dir=b, name="a"), dict(dir=os.path.join(self.root, "gone"), name="gone")], f)
        with open(os.path.join(self.home, "projects.json"), "w") as f:
            json.dump([dict(dir=p, name="P", recipe="talkinghead")], f)
        self.reg.add(b, "a")
        items = self.h.list()["items"]
        self.assertEqual(sorted(i["name"] for i in items), ["P", "a"])
        a = next(i for i in items if i["name"] == "a")
        self.assertEqual(sorted(a["sources"]), ["desk", "engine"])
        self.assertTrue(a["opened"])
        pr = next(i for i in items if i["name"] == "P")
        self.assertTrue(pr["openable"])
        self.assertEqual(pr["counts"]["total"], 2)

    def test_hide_never_deletes_and_open(self):
        w = os.path.join(self.root, "demos")
        b = make_batch(os.path.join(w, "batch-1"), name="one")
        self.h.set_watch([w])
        opened = self.h.open(b)
        self.assertEqual(opened["id"], C.batch_id(b))
        self.assertTrue(self.reg.get(opened["id"]))
        self.h.hide(b)
        self.assertEqual(self.h.list()["items"], [])
        self.assertTrue(os.path.exists(os.path.join(b, "batch.db")))       # files untouched
        self.assertIsNone(self.reg.get(opened["id"]))
        self.h.unhide_all()
        self.assertEqual(len(self.h.list()["items"]), 1)

    def test_readonly(self):
        b = make_batch(os.path.join(self.root, "w", "batch-ro"), name="ro")
        before = os.path.getmtime(os.path.join(b, "batch.db"))
        HI.summarize_batch(b)
        self.assertEqual(before, os.path.getmtime(os.path.join(b, "batch.db")))
        self.assertFalse(os.path.exists(os.path.join(b, "batch.db-wal")))


class HygieneTest(unittest.TestCase):
    def test_is_temp_path(self):
        self.assertTrue(C.is_temp_path("/var/folders/1s/q5/T/tmpdgrjlyfq/batch-fake"))
        self.assertTrue(C.is_temp_path("/tmp/x/batch"))
        self.assertFalse(C.is_temp_path("/Users/me/Desktop/video-studio-demos/batch-rag"))

    def test_prune_real_registry(self):
        root = tempfile.mkdtemp(prefix="hyg-")
        real = make_batch(os.path.join(root, "real", "batch-a"))
        junk = make_batch(os.path.join(root, "junk", "batch-fake"))
        reg = os.path.join(root, "registry", "batches.json")
        os.makedirs(os.path.dirname(reg))
        with open(reg, "w") as f:
            json.dump([dict(dir=real), dict(dir=junk), dict(dir=os.path.join(root, "missing"))], f)
        fake_temp = lambda p: os.path.abspath(p or "").startswith(os.path.join(root, "junk"))  # noqa: E731
        with mock.patch.object(C, "is_temp_path", fake_temp):
            gone = C.prune_json_registry(reg)
        self.assertEqual(len(gone), 2)
        with open(reg) as f:
            self.assertEqual([r["dir"] for r in json.load(f)], [real])

    def test_temp_registry_keeps_temp_entries(self):
        root = tempfile.mkdtemp(prefix="hyg-")
        reg = Registry(os.path.join(root, "desk"))
        b = make_batch(os.path.join(root, "batch-t"))
        reg.add(b, "t")
        reg.add(os.path.join(root, "missing"), "m")
        self.assertEqual(reg.prune(), 1)
        self.assertEqual([x["dir"] for x in reg.all()], [b])


if __name__ == "__main__":
    unittest.main()
