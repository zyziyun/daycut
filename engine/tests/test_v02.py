"""v0.2 adapter tests: capability probing, real-command dispatch (fake runner), and the mock end-to-end flow
(client -> plan -> segments -> batch -> edits/undo/rerun -> timing -> deliver -> metrics)."""
import csv
import io
import json
import os
import sys
import tempfile
import time
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401  (VSTUDIO_HOME / DESK_DATA_DIR -> a temp folder, first)

from desk_engine import metrics as M  # noqa: E402
from desk_engine import planning as P  # noqa: E402
from desk_engine.app import Api, validate_deliver, validate_edit, validate_plan_batch  # noqa: E402
from desk_engine.caps import Capabilities, parse_help, parse_recipes_doc  # noqa: E402
from desk_engine.common import BadRequest, EventBus, Registry  # noqa: E402
from desk_engine.mock import MockEngine  # noqa: E402
from desk_engine.studio import Studio, downstream  # noqa: E402

GTM_CSV = os.path.join(os.path.dirname(__file__), "..", "..", "..", "video-studio-app", "gtm", "05_weekly_metrics.csv")

TOP_HELP = """usage: python -m vstudio.batch [-h]
  {plan,estimate,run,status,review,job,package,verify-manifest,clean,du,bench,recipes,plan-segments,client,deliver,metrics,timing} ...
"""
JOB_HELP = "usage: python -m vstudio.batch job [-h] {show,edit,rerun} ..."
CLIENT_HELP = "usage: python -m vstudio.batch client [-h] {init,show,update} ..."


class FakeRunner:
    def __init__(self, docs=None):
        self.calls = []
        self.docs = docs or {}

    def json(self, args, timeout=None, cwd=None):
        self.calls.append(list(args))
        key = args[0] if args[0] not in ("job", "client") else f"{args[0]} {args[1]}"
        d = self.docs.get(key, {"ok": True})
        return d(args) if callable(d) else d

    def text(self, args, timeout=30):
        self.calls.append(list(args))
        return {"--help": TOP_HELP, "job": JOB_HELP, "client": CLIENT_HELP}.get(args[0], "")


def wait(fn, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = fn()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("timed out")


class CapsTest(unittest.TestCase):
    def test_parse_help(self):
        caps = parse_help(TOP_HELP, JOB_HELP, CLIENT_HELP)
        self.assertEqual(caps, {"plan-segments", "client", "job-edit", "job-rerun", "deliver", "metrics", "timing"})
        self.assertEqual(parse_help("{plan,estimate,run,job,recipes}", "usage: job [-h] id", ""), set())

    def test_recipes_doc_wins(self):
        self.assertIsNone(parse_recipes_doc([{"name": "x"}]))
        self.assertEqual(parse_recipes_doc({"recipes": [], "capabilities": ["deliver", "bogus"]}), {"deliver"})
        r = FakeRunner({"recipes": {"recipes": [], "capabilities": ["timing"]}})
        c = Capabilities(r)
        self.assertTrue(c.has("timing"))
        self.assertFalse(c.has("deliver"))
        self.assertEqual(c.info()["source"], "recipes --json")

    def test_help_fallback(self):
        r = FakeRunner({"recipes": [{"name": "longform-slices"}]})
        c = Capabilities(r)
        self.assertTrue(c.has("job-edit") and c.has("plan-segments"))
        self.assertEqual(c.info()["source"], "--help")


class PlanningTest(unittest.TestCase):
    def test_rule_plan_contract(self):
        words = P.fake_transcript(600)
        segs = P.rule_plan(words, count=5, min_s=20, max_s=60)
        self.assertEqual(len(segs), 5)
        for s in segs:
            for k in ("id", "start", "end", "title", "chapter", "hook", "notes", "tags", "why", "risk", "score"):
                self.assertIn(k, s)
            self.assertTrue(20 <= s["end"] - s["start"] <= 60)
            self.assertIn(s["start"], {w["t"] for w in words})          # word edges
            self.assertIn(s["end"], {w["te"] for w in words})
        self.assertEqual([s["start"] for s in segs], sorted(s["start"] for s in segs))

    def test_snap(self):
        words = [dict(w="a", t=1.0, te=1.4), dict(w="b", t=1.6, te=2.0)]
        self.assertEqual(P.snap(1.5, words, "start"), 1.6)
        self.assertEqual(P.snap(1.5, words, "end"), 1.4)

    def test_faithful(self):
        self.assertTrue(P.faithful("我们用rak检索", "我们用RAG检索")["faithful"])
        self.assertTrue(P.faithful("今天讲RAG", "今天讲 RAG。")["faithful"])
        r = P.faithful("今天讲RAG", "今天讲RAG，记得点赞关注收藏转发")
        self.assertFalse(r["faithful"])
        self.assertEqual(r["reason"], "adds-words")
        self.assertFalse(P.faithful("今天讲RAG", "明天去爬山吧")["faithful"])
        self.assertEqual(P.term_fix("我们用rak检索", "我们用RAG检索"), dict(wrong="rak", right="RAG"))
        self.assertIsNone(P.term_fix("今天讲RAG", "今天讲 RAG。"))
        self.assertEqual(P.term_fix("这是大模形的能力", "这是大模型的能力"), dict(wrong="模形的", right="模型的"))
        self.assertEqual(P.term_fix("用拉格做检索", "用RAG做检索"), dict(wrong="拉格", right="RAG"))


class RealDispatchTest(unittest.TestCase):
    """Real mode with every v0.2 command present: the adapter must call the engine, not its own fallback."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bus = EventBus()
        self.eng = MockEngine(self.tmp, Registry(self.tmp), self.bus, step=0.005)
        self.eng.mode = "real"                     # pretend: data from the mock, commands through the runner
        self.runner = FakeRunner({
            "job edit": {"ok": True, "faithful": True, "rerun": ["export", "qc", "preview"]},
            "deliver": {"dir": "/x/delivery", "zip": "/x/delivery.zip", "items": 2, "manifest": {"items": []}},
            "metrics": {"scope": "all", "summary": {"jobs": 1}},
            "plan-segments": {"duration": 10, "segments": [], "words": [], "draft": "/x/segments.draft.yaml"},
            "client init": {"ok": True}, "client show": {"effective": {"name": "C"}}, "client update": {"ok": True},
        })
        self.st = Studio(self.eng, self.tmp, self.bus, Capabilities(fixed=parse_help(TOP_HELP, JOB_HELP, CLIENT_HELP)),
                         self.runner)
        self.bid = next(b["id"] for b in self.eng.list_batches())

    def test_job_edit_calls_engine(self):
        r = self.st.edit(self.bid, "s001", "caption", dict(cue=0, text="今天我们聊一下RAG"))
        self.assertTrue(r["ok"])
        call = next(c for c in self.runner.calls if c[:2] == ["job", "edit"])
        self.assertEqual(call[:4], ["job", "edit", "--batch", self.eng.dir_of(self.bid)])
        self.assertEqual(call[4:], ["--job", "s001", "--op", "caption", "--cue", "0", "--text", "今天我们聊一下RAG",
                                    "--json"])
        self.assertEqual(r["rerun"], ["export", "qc", "preview"])
        self.st.edit(self.bid, "s001", "copy", dict(title="新标题", body="b", tags=["a", "b"]))
        call = [c for c in self.runner.calls if c[:2] == ["job", "edit"]][-1]
        self.assertEqual(call[6:], ["--op", "copy", "--title", "新标题", "--body", "b", "--tags", "a,b", "--json"])

    def test_deliver_metrics_timing_plan_client(self):
        r = self.st.deliver(self.bid, dict(zip=True, cleanup_days=30))
        self.assertEqual(r["dir"], "/x/delivery")
        call = next(c for c in self.runner.calls if c[0] == "deliver")
        self.assertIn("--zip", call)
        self.assertEqual(call[call.index("--cleanup-days") + 1], "30")
        # 0 = never delete the sources: passed through to the engine (it was dropped -> the 30-day default)
        self.assertEqual(validate_deliver(dict(cleanup_days=0))["cleanup_days"], 0)
        self.st.deliver(self.bid, dict(zip=True, cleanup_days=0))
        call = [c for c in self.runner.calls if c[0] == "deliver"][-1]
        self.assertEqual(call[call.index("--cleanup-days") + 1], "0")
        self.st.deliver(self.bid, dict(zip=True))
        self.assertNotIn("--cleanup-days", [c for c in self.runner.calls if c[0] == "deliver"][-1])
        self.assertEqual(self.st.metrics()["source"], "engine")
        self.st.timing(self.bid, dict(job="s001", event="stop", what="review", active_s=12.5))
        wait(lambda: any(c[0] == "timing" for c in self.runner.calls))
        call = next(c for c in self.runner.calls if c[0] == "timing")
        self.assertEqual(call[call.index("--seconds") + 1], "12.5")
        self.assertEqual(call[call.index("--event") + 1], "stop")
        src = os.path.join(self.tmp, "rec.mp4")
        open(src, "wb").close()
        pid = self.st.start_plan(dict(source=src, count=3, min=20.0, max=60.0, provider="none"))["id"]
        wait(lambda: self.st.get_plan(pid)["state"] != "running")
        call = next(c for c in self.runner.calls if c[0] == "plan-segments")
        self.assertEqual(call[call.index("--provider") + 1], "none")
        self.assertEqual(call[call.index("--count") + 1], "3")
        self.st.create_client(dict(slug="acme", name="ACME"))
        self.assertTrue(any(c[:2] == ["client", "init"] for c in self.runner.calls))

    def test_undo_and_engine_shapes(self):
        self.runner.docs["job edit"] = lambda args: (
            {"ok": True, "op": "undo", "undone": {"n": 1, "op": "caption"}, "rerun": ["export"], "pending": []}
            if "undo" in args else {"ok": True, "faithful": True, "rerun": ["export"], "pending": ["export"],
                                    "glossary_added": [{"wrong": "rak", "right": "RAG"}]})
        r = self.st.edit(self.bid, "s001", "caption", dict(cue=0, text="今天我们聊一下RAG"))
        self.assertEqual(r["glossary_added"], {"wrong": "rak", "right": "RAG"})
        self.assertEqual(r["pending"], ["export"])
        u = self.st.undo(self.bid, "s001")
        self.assertEqual(u["undone"]["op"], "caption")
        self.assertEqual(self.runner.calls[-1][-3:], ["--op", "undo", "--json"])
        self.runner.docs["deliver"] = {"dir": "/x", "zip": None, "items": 1, "jobs": 1, "manifest": "/x/manifest.json",
                                       "manifest_data": {"items": [{"path": "a.mp4", "sha256": "0" * 64, "bytes": 3}]}}
        self.assertEqual(self.st.deliver(self.bid, dict(zip=False))["manifest"]["items"][0]["path"], "a.mp4")
        self.runner.docs["metrics"] = {"scope": "all", "summary": {}, "clients": [],
                                       "batches": [{"batch": "demo-course", "dir": self.eng.dir_of(self.bid)}]}
        m = self.st.metrics()
        self.assertEqual(m["batches"][0]["batch"], self.bid)
        self.assertEqual(m["batches"][0]["name"], "demo-course")

    def test_real_without_commands_reports_engine_too_old(self):
        st = Studio(self.eng, tempfile.mkdtemp(), self.bus, Capabilities(fixed=set()), self.runner)
        with self.assertRaisesRegex(BadRequest, "engine lacks"):
            st.edit(self.bid, "s001", "copy", dict(title="x", body="", tags=[]))
        with self.assertRaisesRegex(BadRequest, "engine lacks plan-segments"):
            st.start_plan(dict(source=__file__, count=3, min=20.0, max=60.0, provider="none"))


class MockFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bus = EventBus()
        self.eng = MockEngine(self.tmp, Registry(self.tmp), self.bus, step=0.005)
        self.api = Api(self.eng, self.bus, "t" * 48, [])
        self.st = self.api.studio
        self.R = lambda m, path, body=None, q=None: self.api.route(m, path, q or {}, body)

    def test_full_flow(self):
        R = self.R
        # client workspace
        c = R("POST", "/api/clients", dict(slug="acme", name="ACME 讲师", platforms=["xiaohongshu:full"],
                                            cleanup_profile="strict", brand=dict(accent="#112233")))
        self.assertEqual(c["effective"]["brand"]["accent"], "#112233")
        self.assertEqual(c["effective"]["brand"]["highlight"], "#FFD60A")      # inherited default
        self.assertTrue(os.path.exists(os.path.join(c["dir"], "client.yaml")))
        with self.assertRaises(BadRequest):
            R("POST", "/api/clients/acme", dict(cleanup_profile="nuclear"))
        R("POST", "/api/clients/acme", dict(tags=["RAG"], fillers=dict(extra=["那么"], keep=[])))
        self.assertEqual(R("GET", "/api/clients/acme")["config"]["fillers"]["extra"], ["那么"])
        # plan from a raw recording
        src = os.path.join(self.tmp, "raw.mp4")
        with open(src, "wb") as f:
            f.write(b"not a real video")
        pid = R("POST", "/api/plans", dict(source=src, count=4, min=20, max=60, provider="none", client="acme"))["id"]
        plan = wait(lambda: (lambda p: p if p["state"] != "running" else None)(R("GET", f"/api/plans/{pid}")))
        self.assertEqual(plan["state"], "done", plan.get("error"))
        segs = plan["result"]["segments"]
        self.assertEqual(len(segs), 4)
        self.assertIn(os.path.dirname(src), self.api.roots())
        # accept 3, edit one title, nudge an edge (snaps to a word edge)
        acc = segs[:3]
        acc[0] = dict(acc[0], title="改过的标题", start=acc[0]["start"] + 0.07)
        b = R("POST", f"/api/plans/{pid}/batch", dict(name="from-plan", segments=acc, platforms=["xiaohongshu:full"],
                                                      budget=dict(max_hours=5)))
        bid = b["id"]
        st = R("GET", f"/api/batches/{bid}")
        self.assertEqual([j["title"] for j in st["jobs"]][0], "改过的标题")
        self.assertEqual(len(st["jobs"]), 3)
        self.assertEqual(next(x for x in R("GET", "/api/batches") if x["id"] == bid)["client"], "acme")
        # pilot then full run
        R("POST", f"/api/batches/{bid}/run", dict(pilot=1))
        wait(lambda: R("GET", f"/api/batches/{bid}")["meta"]["state"] == "pilot-review")
        R("POST", f"/api/batches/{bid}/run", dict(confirm_pilot=True))
        wait(lambda: R("GET", f"/api/batches/{bid}")["meta"]["state"] == "ran")
        # job edits
        jd = R("GET", f"/api/batches/{bid}/jobs/s001")
        e = jd["edit"]
        self.assertTrue(e["cues"] and e["words"] and len(e["hooks"]) >= 1 and e["can_edit"])
        cue = e["cues"][0]
        bad = R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="caption", cue=0, text=cue["text"] + "记得点赞关注收藏转发"))
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["reason"], "adds-words")
        fixed = cue["text"].replace("RAG", "Rag", 1) if "RAG" in cue["text"] else cue["text"][:-1] + "嘛"
        ok = R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="caption", cue=0, text=fixed))
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["rerun"], ["export", "qc", "preview"])                     # captions: re-burn only
        if ok["glossary_added"]:
            self.assertIn(ok["glossary_added"]["wrong"], [g["wrong"] for g in R("GET", "/api/clients/acme")["config"]["glossary"]])
        rng = e["range"]
        tr = R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="trim", start=rng[0] + 1.03, end=rng[1] - 0.5))
        self.assertIn("cleanup", tr["rerun"])
        jd = R("GET", f"/api/batches/{bid}/jobs/s001")
        self.assertIn(jd["edit"]["range"][0], {w["t"] for w in jd["edit"]["words"]})    # snapped
        noop = R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="caption", cue=0, text=fixed))
        self.assertTrue(noop.get("noop"))
        R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="hook", pick=1))
        R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="cover", t=1.5, text="封面字"))
        R("POST", f"/api/batches/{bid}/jobs/s001/edit", dict(op="copy", title="新标题", body="新正文", tags=["#a", "b"]))
        jd = R("GET", f"/api/batches/{bid}/jobs/s001")
        self.assertEqual(jd["edit"]["copy"]["tags"], ["a", "b"])
        self.assertEqual(jd["edit"]["hook_pick"], 1)
        self.assertEqual(len(jd["edit"]["history"]), 5)
        # undo the copy edit and the cover edit
        u = R("POST", f"/api/batches/{bid}/jobs/s001/undo")
        self.assertEqual(u["undone"]["op"], "copy")
        R("POST", f"/api/batches/{bid}/jobs/s001/undo")
        jd = R("GET", f"/api/batches/{bid}/jobs/s001")
        self.assertEqual(jd["edit"]["copy"]["title"], acc[0]["title"])
        self.assertEqual(len(jd["edit"]["history"]), 3)
        self.assertIn("compose", jd["edit"]["pending"])
        # re-render only the affected stages
        rr = R("POST", f"/api/batches/{bid}/jobs/s001/rerun")
        self.assertNotIn("asr", rr["stages"])
        wait(lambda: R("GET", f"/api/batches/{bid}/jobs/s001")["job"]["state"] == "done")
        self.assertEqual(R("GET", f"/api/batches/{bid}/jobs/s001")["edit"]["pending"], [])
        # timing
        for jid, secs in (("s001", 20.0), ("s002", 10.0), ("s003", 30.0)):
            R("POST", f"/api/batches/{bid}/timing", dict(job=jid, event="start", what="review"))
            R("POST", f"/api/batches/{bid}/timing", dict(job=jid, event="stop", what="review", active_s=secs))
        R("POST", f"/api/batches/{bid}/review/apply", dict(decisions={j: dict(decision="approve") for j in ("s001", "s002", "s003")}))
        # deliver
        d = R("POST", f"/api/batches/{bid}/deliver", dict(cleanup_days=30, zip=True))
        self.assertTrue(os.path.isdir(d["dir"]))
        names = set(os.listdir(d["dir"]))
        self.assertTrue({"文案.md", "排期表.csv", "交付说明.md", "manifest.json", "小红书"} <= names, names)
        self.assertEqual(len([f for f in os.listdir(os.path.join(d["dir"], "小红书")) if f.endswith(".mp4")]), 3)
        with open(os.path.join(d["dir"], "文案.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("AI 标识提醒", md)
        self.assertNotIn("新标题", md)                                # the copy edit was undone
        with open(os.path.join(d["dir"], "排期表.csv"), encoding="utf-8-sig") as f:
            self.assertEqual(next(csv.reader(f)), ["日期", "时间", "平台", "序号", "标题", "文件"])
        with zipfile.ZipFile(d["zip"]) as z:
            self.assertTrue(any(n.endswith("交付说明.md") for n in z.namelist()))
        with open(os.path.join(d["dir"], "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
        self.assertTrue(all(len(i["sha256"]) == 64 for i in man["items"]))
        self.assertEqual(R("GET", f"/api/batches/{bid}/deliver")["delivery"]["cleanup"]["days"], 30)
        self.assertEqual(R("GET", "/api/clients/acme")["crm"]["stage"], "delivered")
        self.assertEqual(self.st.cleanup_due(), [])
        due = self.st.cleanup_due(now=time.time() + 31 * 86400)
        self.assertEqual(due, [dict(batch=bid, paths=[src])])
        R("POST", "/api/cleanup/done", dict(batch=bid, paths=[src]))
        self.assertEqual(self.st.cleanup_due(now=time.time() + 31 * 86400), [])
        # metrics
        m = R("GET", "/api/metrics", q={"batch": [bid]})
        self.assertEqual(m["summary"]["review_s_median"], 20.0)
        self.assertEqual(m["summary"]["delivered_clips"], 3)
        self.assertEqual(next(j for j in m["jobs"] if j["id"] == "s001")["reruns"], 1)
        self.assertAlmostEqual(m["summary"]["rework_rate"], round(1 / 3, 3))
        R("POST", "/api/clients/acme/crm", dict(post=dict(platform="xiaohongshu", plays=1200, saves=80)))
        R("POST", "/api/clients/acme/crm", dict(revenue=499))
        mc = R("GET", "/api/metrics", q={"client": ["acme"]})
        self.assertEqual(mc["crm"]["stage"], "paid")
        R("POST", "/api/metrics/weekly", dict(week="W1", values={"内容号涨粉": 35}))
        w = R("GET", "/api/metrics/weekly")
        header = next(csv.reader(io.StringIO(w["csv"])))
        self.assertEqual(header, M.WEEKLY_COLUMNS)
        if os.path.exists(GTM_CSV):
            with open(GTM_CSV, encoding="utf-8-sig") as f:
                self.assertEqual(header, next(csv.reader(f)))

    def test_validators(self):
        with self.assertRaises(BadRequest):
            validate_edit(dict(op="caption", cue=True, text="x"))
        with self.assertRaises(BadRequest):
            validate_edit(dict(op="trim", start=5, end=4))
        with self.assertRaises(BadRequest):
            validate_edit(dict(op="rm -rf"))
        with self.assertRaises(BadRequest):
            validate_plan_batch(dict(name="../x", segments=[], platforms=["tiktok"]))
        with self.assertRaises(BadRequest):
            self.R("POST", "/api/clients", dict(slug="../evil", name="x"))
        with self.assertRaises(BadRequest):
            self.R("POST", "/api/clients", dict(slug="ok", name="x", shell="rm"))
        with self.assertRaises(BadRequest):
            self.R("POST", "/api/plans", dict(source="relative.mp4"))
        with self.assertRaises(BadRequest):
            self.R("POST", "/api/metrics/weekly", dict(week="W1", values={"线索数": 3}))     # computed, not manual

    def test_downstream_dag(self):
        self.assertEqual(downstream(["export"]), ["export", "qc", "preview"])
        self.assertEqual(downstream(["compose"]), ["compose", "proofread", "export", "qc", "preview"])
        self.assertEqual(downstream([]), [])

    def test_demo_seed(self):
        self.assertEqual([c["slug"] for c in self.R("GET", "/api/clients")], ["demo"])
        demo = next(b for b in self.R("GET", "/api/batches") if b["name"] == "demo-course")
        self.assertEqual(demo["client"], "demo")


if __name__ == "__main__":
    unittest.main()
