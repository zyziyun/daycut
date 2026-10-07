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

    def test_plain_work_folders_detail_and_adopt(self):
        w = os.path.join(self.root, "demos")
        th = os.path.join(w, "01-talkinghead")
        for f in ("final/xhs_3x4.mp4", "final/cover_3x4.jpg", "final/post.md", "final/contact_sheet.jpg"):
            os.makedirs(os.path.dirname(os.path.join(th, f)), exist_ok=True)
            with open(os.path.join(th, f), "w", encoding="utf-8") as fh:
                fh.write("标题\n正文 #标签" if f.endswith(".md") else "x")
        with open(os.path.join(th, "REPORT.md"), "w", encoding="utf-8") as fh:
            fh.write("# 01-talkinghead: 口播精剪\n\nbody")
        fuye = os.path.join(w, "fuye")                          # in progress: work/ scripts + a sheet, no outputs
        os.makedirs(os.path.join(fuye, "work", "clips", "A"))
        open(os.path.join(fuye, "work", "compose.py"), "w").close()
        open(os.path.join(fuye, "sheet.jpg"), "w").close()
        os.makedirs(os.path.join(w, "not-work", "misc"))
        open(os.path.join(w, "not-work", "misc", "readme.txt"), "w").close()
        make_batch(os.path.join(w, "batch-rag"), name="rag")
        self.h.set_watch([w])
        items = self.h.list()["items"]
        by = {i["name"]: i for i in items}
        self.assertEqual(sorted(by), ["01-talkinghead: 口播精剪", "fuye", "rag"])
        t = by["01-talkinghead: 口播精剪"]
        self.assertEqual((t["kind"], t["type"], t["status"], t["counts"]["total"], t["openable"]),
                         ("work", "talkinghead", "done", 1, False))
        self.assertEqual((by["fuye"]["type"], by["fuye"]["status"]), ("slices", "in-progress"))
        self.assertEqual(by["rag"]["type"], "batch")
        self.assertEqual([i["name"] for i in self.h.list(type_="talkinghead")["items"]], [t["name"]])
        det = self.h.item(t["id"])["detail"]
        self.assertEqual(det["outputs"], [os.path.join(th, "final", "xhs_3x4.mp4")])
        self.assertEqual(det["covers"], [os.path.join(th, "final", "cover_3x4.jpg")])
        self.assertIn("正文", det["posts"][0]["text"])
        self.assertEqual(det["notes"][0]["path"], os.path.join(th, "REPORT.md"))
        self.assertIn(os.path.join(th, "final"), self.h.roots())
        before = sorted(os.listdir(th))
        r = self.h.adopt(t["id"])
        self.assertEqual((r["type"], r["recipe"]), ("talkinghead", "talkinghead"))
        self.assertEqual(sorted(os.listdir(th)), sorted(before + [".vstudio"]))
        self.assertTrue(os.path.exists(os.path.join(th, ".vstudio", "work.json")))
        again = {i["name"]: i for i in self.h.list()["items"]}[t["name"]]
        self.assertEqual(again["status"], "done")          # B3: adopting never hides the real state
        self.assertTrue(again["adopted"])
        with self.assertRaises(Exception):
            self.h.adopt(by["rag"]["id"])

    def test_live_status_external_runner(self):
        """A run outside the app (terminal / Claude Code) writes heartbeats: running -> stale -> interrupted;
        a checkpoint -> needs you."""
        import socket
        import time
        w = os.path.join(self.root, "demos")
        job = os.path.join(w, "fuye")
        os.makedirs(os.path.join(job, "work"))
        open(os.path.join(job, "work", "compose.py"), "w").close()
        with open(os.path.join(job, "work", "render.log"), "w") as f:
            f.write("\n".join(f"line {i}" for i in range(100)))
        self.h.set_watch([w])
        status = os.path.join(job, ".vstudio", "status.json")
        os.makedirs(os.path.dirname(status))

        def beat(**kw):
            rec = dict(status="running", stage="render", progress=0.4, message="clip B", eta=120, started=time.time() - 60,
                       heartbeat=time.time(), pid=999999, host=socket.gethostname(), updated_by="workflow")
            rec.update(kw)
            with open(status, "w") as f:
                json.dump(rec, f)
        beat()
        r = self.h.list()
        row = r["items"][0]
        self.assertEqual(r["running"], 1)
        self.assertEqual((row["live"]["state"], row["live"]["stage"], row["live"]["progress"]), ("running", "render", 0.4))
        beat(heartbeat=time.time() - C.LIVE_STALE_S - 5)                  # the external process died
        r = self.h.list()
        self.assertEqual((r["running"], r["items"][0]["live"]["state"]), (0, "interrupted"))
        beat(heartbeat=time.time() - C.LIVE_STALE_S - 5, pid=os.getpid())  # still alive: still running
        self.assertEqual(self.h.list()["items"][0]["live"]["state"], "running")
        beat(status="waiting", needs_you=True, message="checkpoint: hooks", heartbeat=time.time() - 86400)
        live = self.h.list()["items"][0]["live"]
        self.assertEqual((live["state"], live["needs_you"]), ("waiting", True))
        det = self.h.item(self.h.list()["items"][0]["id"])
        self.assertTrue(det["log"]["text"].endswith("line 99"))
        self.assertEqual(len(det["log"]["text"].splitlines()), 40)

    def test_interrupted_clip_edit_is_not_a_project_failure(self):
        """BB-24: a stale "running" output edit (its process gone) marks that edit, not the whole project Error."""
        import socket
        import time
        w = os.path.join(self.root, "demos")
        job = os.path.join(w, "talk")
        os.makedirs(os.path.join(job, "work"))
        open(os.path.join(job, "work", "compose.py"), "w").close()
        self.h.set_watch([w])
        os.makedirs(os.path.join(job, ".vstudio"))
        with open(os.path.join(job, ".vstudio", "status.json"), "w") as f:
            json.dump(dict(status="running", stage="output-edit:render", progress=0.5, message="clip A: captions",
                           started=time.time() - 90000, heartbeat=time.time() - 86000, pid=999999,
                           host=socket.gethostname(), updated_by="output-edit"), f)
        row = self.h.list()["items"][0]
        self.assertIsNone(row["live"])
        self.assertNotEqual(row.get("status"), "failed")
        self.assertEqual((row["edit_note"]["state"], row["edit_note"]["message"]), ("interrupted", "clip A: captions"))
        with open(os.path.join(job, ".vstudio", "status.json"), "w") as f:     # a project run's own stall still shows
            json.dump(dict(status="running", stage="render", heartbeat=time.time() - C.LIVE_STALE_S - 5, pid=999999,
                           host=socket.gethostname(), updated_by="workflow"), f)
        row = self.h.list()["items"][0]
        self.assertEqual(row["live"]["state"], "interrupted")
        self.assertNotIn("edit_note", row)

    def test_readonly(self):
        b = make_batch(os.path.join(self.root, "w", "batch-ro"), name="ro")
        before = os.path.getmtime(os.path.join(b, "batch.db"))
        HI.summarize_batch(b)
        self.assertEqual(before, os.path.getmtime(os.path.join(b, "batch.db")))
        self.assertFalse(os.path.exists(os.path.join(b, "batch.db-wal")))


class SymlinkedPathsTest(unittest.TestCase):
    """A project run reached through a symlink (macOS /var -> /private/var) registered its state/ twice; the board's
    id came from one spelling, the registry's from the other, so the board found no batch."""

    def setUp(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="hist-link-"))
        self.home = os.path.join(self.root, "home")
        os.makedirs(self.home)
        self.env = mock.patch.dict(os.environ, {"VSTUDIO_HOME": self.home, "DESK_HISTORY_WATCH": ""})
        self.env.start()
        self.reg = Registry(os.path.join(self.root, "desk"))
        self.h = HI.History(os.path.join(self.root, "desk"), self.reg)

    def tearDown(self):
        self.env.stop()

    def test_one_row_one_id_whatever_the_spelling(self):
        from vstudio.batch import clients as CL
        from vstudio.project import home as PH
        real = os.path.join(self.root, "real")
        proj = os.path.join(real, "p")
        make_batch(os.path.join(proj, "state"), name="p")
        with open(os.path.join(proj, "project.yaml"), "w") as f:
            f.write("name: P\nrecipe: talkinghead\n")
        link = os.path.join(self.root, "link")
        os.symlink(real, link)
        for root in (real, link):                    # two runs, two spellings of the same folder
            CL.register_batch(os.path.join(root, "p", "state"), "p")
            PH.register(os.path.join(root, "p"), "P", "talkinghead")
        self.assertEqual(len(CL.batches()), 1)
        ent = self.reg.add(os.path.join(link, "p", "state"), "p")
        self.assertEqual(ent["id"], C.batch_id(os.path.join(proj, "state")))
        rows = self.h.list()["items"]
        self.assertEqual([(r["kind"], r["id"], r["opened"]) for r in rows], [("project", ent["id"], True)])
        self.assertEqual(self.reg.get(rows[0]["id"])["dir"], os.path.join(link, "p", "state"))  # the board finds it


class HygieneTest(unittest.TestCase):
    def test_is_temp_path(self):
        self.assertTrue(C.is_temp_path(os.path.join(tempfile.gettempdir(), "tmpdgrjlyfq", "batch-fake")))
        self.assertTrue(C.is_temp_path(os.path.join(tempfile.gettempdir().upper(), "x")) or os.name != "nt")
        if os.name != "nt":                         # macOS / Linux temp roots
            self.assertTrue(C.is_temp_path("/var/folders/1s/q5/T/tmpdgrjlyfq/batch-fake"))
            self.assertTrue(C.is_temp_path("/tmp/x/batch"))
        self.assertFalse(C.is_temp_path(os.path.join(os.path.expanduser("~"), "Desktop", "video-studio-demos", "batch-rag")))

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
