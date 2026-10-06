"""v0.4: clips per output (work folders incl. in-progress work/clips, batches), the output editor (desk
implementation of ``vstudio.project output``), the intake rule planner / revise / apply, and the inbox."""
import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import inbox as IB  # noqa: E402
from desk_engine import intake as IN  # noqa: E402
from desk_engine import outputs as OU  # noqa: E402
from desk_engine import works as WK  # noqa: E402
from desk_engine.common import BadRequest, Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from test_history import make_batch  # noqa: E402

POST = """# 发布文案 (小红书)

## A_换圈子.mp4  ·  封面 A_换圈子_cover.jpg

同一个行业待越久，思路越窄

正文第一段。

#副业 #程序员

## B_自媒体.mp4  ·  封面 B_自媒体_cover.jpg

再小的博主，也是博主

正文。

#自媒体
"""

PICKS = """# PICKS

| # | Source span | Len | Title (小红书 units) | Why | Opening line (hook) |
|---|---|---|---|---|---|
| A 换圈子 | 7:30 | 1:24 | 同一个行业待越久，思路越窄 (13) | x | y |
| C 底气 | 5:01 | 0:50 | 副业给我的不是钱，是底气 (12) | x | y |

## Edits inside the spans (creator should confirm)
- **A** starts at 你在副业当中, skipping 「这也是挺丰富人生的一个事情」.
- **C** drops the hedge 「或者说也可能是」.
- Skipped: 摄影 (3:00–3:21).
"""


def asr(words):
    return dict(segments=[dict(start=words[0][1], end=words[-1][2],
                               words=[dict(word=w, start=a, end=z) for w, a, z in words])])


def make_fuye(root):
    d = os.path.join(root, "fuye")
    os.makedirs(os.path.join(d, "final"))
    os.makedirs(os.path.join(d, "work", "clips", "A"))
    os.makedirs(os.path.join(d, "work", "clips", "C"))
    for n in ("A_换圈子.mp4", "A_换圈子_9x16.mp4", "B_自媒体.mp4", "B_band.mp4", "A_换圈子_cover.jpg"):
        open(os.path.join(d, "final", n), "wb").close()
    with open(os.path.join(d, "final", "post.md"), "w", encoding="utf-8") as f:
        f.write(POST)
    with open(os.path.join(d, "PICKS.md"), "w", encoding="utf-8") as f:
        f.write(PICKS)
    with open(os.path.join(d, "final", "A_换圈子.mp4.asr.json"), "w", encoding="utf-8") as f:
        json.dump(asr([("你在", 0.0, 0.5), ("副业", 0.5, 1.0), ("当中", 1.0, 1.4), ("其实", 2.4, 2.8),
                       ("底气", 2.8, 3.3)]), f)
    with open(os.path.join(d, "work", "clips", "C", "compose.log"), "w") as f:
        f.write("frame 10")
    return d


class ClipsTest(unittest.TestCase):
    def test_work_folder_clips_group_versions_posts_and_in_progress(self):
        d = make_fuye(tempfile.mkdtemp())
        cl = WK.clips(d)
        ids = [c["id"] for c in cl]
        self.assertEqual(ids[:2], ["A_换圈子", "B_自媒体"])
        a = cl[0]
        self.assertEqual(a["title"], "同一个行业待越久，思路越窄")
        self.assertEqual(sorted(f["aspect"] for f in a["files"]), ["9:16", "原尺寸"])
        self.assertTrue(a["cover"].endswith("A_换圈子_cover.jpg"))
        self.assertEqual(a["post"]["tags"], ["副业", "程序员"])
        c = next(x for x in cl if x["id"] == "C")
        self.assertEqual(c["state"], "running")                  # B2: work/clips/C is rendering
        self.assertEqual(c["title"], "副业给我的不是钱，是底气")      # from the PICKS table
        self.assertNotIn("A", ids)                               # A is finished in final/
        self.assertTrue(next(x for x in cl if x["id"] == "B_band")["extra"])

    def test_confirmations_from_picks(self):
        d = make_fuye(tempfile.mkdtemp())
        conf = WK.confirmations(d)
        self.assertEqual([c["clip"] for c in conf], ["A", "C"])

    def test_status_is_never_adopted(self):                      # B3
        d = make_fuye(tempfile.mkdtemp())
        WK.adopt(d)
        self.assertEqual(WK.summarize(d)["status"], "done")
        self.assertTrue(WK.summarize(d)["adopted"])

    def test_clip_key_and_aspect(self):
        self.assertEqual(WK.clip_key("final/A_换圈子_9x16.mp4"), "A_换圈子")
        self.assertEqual(WK.clip_key("final/A_换圈子_cover.jpg"), "A_换圈子")
        self.assertEqual(WK.aspect_of(1080, 1440), "3:4")
        self.assertEqual(WK.aspect_of(1080, 1920), "9:16")


class OutputsTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.watch = os.path.join(self.root, "demos")
        self.d = make_fuye(self.watch)
        self.env = mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": self.watch,
                                                "VSTUDIO_HOME": os.path.join(self.root, "home")})
        self.env.start()
        data = os.path.join(self.root, "desk")
        self.h = History(data, Registry(data))
        self.o = OU.Outputs(data, self.h)
        self.item = next(r["id"] for r in self.h.list()["items"] if r["dir"] == self.d)

    def tearDown(self):
        self.env.stop()

    def test_show_has_words_flattened_captions_and_caps(self):
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual([w["w"] for w in doc["words"]][:2], ["你在", "副业"])
        self.assertEqual(doc["caps"]["captions"], "flattened")
        self.assertIn("烧进画面", doc["notes"]["captions"])
        self.assertEqual(doc["engine"], "desk")
        self.assertTrue(doc["waveform"] == [] or len(doc["waveform"]) == 240)

    def test_edit_trim_effect_undo_render(self):
        r = self.o.edit(self.item, "A_换圈子", [dict(op="trim", start=1.0, end=3.3),
                                               dict(op="effect_add", effect="pop-word", start=2.8, end=3.6,
                                                    params=dict(text="底气"))])
        self.assertTrue(r["ok"])
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual(doc["trim"], dict(start=1.0, end=3.3))
        self.assertEqual(doc["effects"][0]["label"], "弹字")
        self.assertTrue(doc["dirty"])
        self.assertEqual([o["label"][:2] for o in doc["ops"]], ["保留", "加弹"])
        self.assertTrue(os.path.exists(WK.record_path(self.d)))           # 转成项目 happened on the first edit
        eid = doc["effects"][0]["id"]
        self.o.edit(self.item, "A_换圈子", [dict(op="effect_move", id=eid, start=2.0, end=2.8)])
        self.assertEqual(self.o.show(self.item, "A_换圈子")["effects"][0]["start"], 2.0)
        rr = self.o.render(self.item, "A_换圈子")
        self.assertTrue(rr["simulated"])
        self.assertFalse(self.o.show(self.item, "A_换圈子")["dirty"])
        self.o.undo(self.item, "A_换圈子")
        self.assertEqual(self.o.show(self.item, "A_换圈子")["effects"][0]["start"], 2.8)
        self.o.undo(self.item, "A_换圈子", n=1)
        doc = self.o.show(self.item, "A_换圈子")
        self.assertIsNone(doc["trim"])
        self.assertEqual(doc["effects"], [])

    def test_flattened_captions_refuse_caption_edits_and_bad_ops(self):
        with self.assertRaises(BadRequest):
            self.o.edit(self.item, "A_换圈子", [dict(op="caption_style", size=1.2)])
        with self.assertRaises(BadRequest):
            self.o.edit(self.item, "A_换圈子", [dict(op="effect_add", effect="nope", start=0, end=1)])
        with self.assertRaises(BadRequest):
            self.o.edit(self.item, "A_换圈子", [dict(op="trim", start=2, end=1)])
        with self.assertRaises(BadRequest):
            self.o.show(self.item, "../../etc")

    def test_ask_proposes_trim_pop_word_and_explains_flattened(self):
        r = self.o.ask(self.item, "A_换圈子", "开头太慢，从「其实」开始，把「底气」弹出来，字幕大一点")
        labels = [p["label"] for p in r["proposals"]]
        self.assertTrue(any("开头前移 2.4" in x for x in labels), labels)
        pop = next(p for p in r["proposals"] if p["ops"][0]["op"] == "effect_add")
        self.assertEqual(pop["ops"][0]["params"]["text"], "底气")
        self.assertIn("烧进画面", r["summary_zh"])
        for p in r["proposals"]:                               # every proposal is a valid op list
            for op in p["ops"]:
                OU.validate_op(op)

    def test_effects_catalogue_has_zh_labels(self):
        effs = self.o.effects()["effects"]
        self.assertTrue(all(e["label"] and e["category"] for e in effs))
        self.assertIn("pop-word", {e["id"] for e in effs})

    def test_batch_clips_from_export_manifest(self):
        b = make_batch(os.path.join(self.watch, "batch-x"))
        out = os.path.join(b, "jobs", "ep01", "export", "out", "v")
        os.makedirs(out)
        open(os.path.join(out, "xiaohongshu-vertical.mp4"), "wb").close()
        with open(os.path.join(b, "jobs", "ep01", "export", "manifest.json"), "w") as f:
            json.dump(dict(exports=[dict(platform="xiaohongshu", orientation="vertical", file="xiaohongshu-vertical.mp4",
                                         w=1080, h=1440, fps=24, duration=80.0)]), f)
        cl = OU.list_clips(dict(kind="batch", dir=b))
        self.assertEqual(cl[0]["files"][0]["aspect"], "3:4")
        self.assertEqual(cl[0]["duration"], 80.0)


class CalendarTest(OutputsTest):
    def test_schedule_move_confirm_remove(self):
        from desk_engine.calendar import Calendar
        WK.adopt(self.d)                                    # a finished work folder (status done)
        cal = Calendar(os.path.join(self.root, "desk"), self.h, self.o)
        q = cal.list()["queue"]
        self.assertIn("A_换圈子", [x["clip"] for x in q])
        post = cal.add(dict(item=self.item, clip="A_换圈子", platform="xiaohongshu", at="2026-10-07T19:00"))
        self.assertNotIn("A_换圈子", [x["clip"] for x in cal.list()["queue"]])
        cal.update(post["id"], dict(at="2026-10-08T21:00"))
        self.assertEqual(cal.list(start="2026-10-05")["posts"][0]["at"], "2026-10-08T21:00")
        self.assertEqual(cal.confirm_week("2026-10-05")["ready"], 1)
        cal.update(post["id"], dict(remove=True))
        self.assertEqual(cal.list()["posts"], [])
        with self.assertRaises(BadRequest):
            cal.add(dict(item=self.item, clip="A_换圈子", at="tomorrow"))


class IntakeTest(unittest.TestCase):
    def test_rule_plan_shape_and_question(self):
        p = IN.rule_plan("把这条副业复盘剪成 4 条小红书切片，每条一分钟左右", ["/x/多元副业复盘_final.mp4"],
                         probe=lambda _p: dict(duration=653.0))
        self.assertEqual(p["kind"], "vstudio.intake.plan")
        proj = p["projects"][0]
        self.assertEqual(proj["recipe"], "longform-to-short")
        self.assertEqual(proj["items"]["count"], 4)
        self.assertEqual(proj["params"]["platforms"], ["xiaohongshu:vertical"])
        self.assertEqual(proj["params"]["aspects"], ["3:4", "9:16"])
        self.assertTrue(p["questions"])
        self.assertIn("4 条", p["summary_zh"])

    def test_revise_rules(self):
        p = IN.rule_plan("剪成 4 条小红书切片", ["/x/a.mp4"], probe=lambda _p: dict(duration=600.0))
        r = IN.rule_revise(p, "只要 3 条，不要 9:16")
        proj = r["projects"][0]
        self.assertEqual(proj["items"]["count"], 3)
        self.assertEqual(proj["params"]["aspects"], ["3:4"])
        self.assertEqual(r["revisions"][-1]["prompt"], "只要 3 条，不要 9:16")
        same = IN.rule_revise(p, "嗯？")
        self.assertTrue(same["warnings"])

    def test_async_plan_and_mock_apply(self):
        root = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"VSTUDIO_HOME": os.path.join(root, "home"), "DESK_MOCK_STEP": "0.01"}):
            it = IN.Intake(os.path.join(root, "desk"), None)
            pid = it.start("剪一条口播", [])["id"]
            for _ in range(200):
                if it.get(pid)["state"] != "running":
                    break
                time.sleep(0.01)
            self.assertEqual(it.get(pid)["state"], "done")
            r = it.apply(pid, run=False)
            d = r["projects"][0]["dir"]
            self.assertTrue(os.path.exists(os.path.join(d, ".vstudio", "work.json")))
            with open(os.path.join(root, "home", "projects.json"), encoding="utf-8") as f:
                reg = json.load(f)
            self.assertEqual(reg[0]["dir"], d)
            self.assertEqual(it.recent()[0]["prompt"], "剪一条口播")


class InboxTest(unittest.TestCase):
    def test_confirm_and_review_items_answer_and_undo(self):
        root = tempfile.mkdtemp()
        watch = os.path.join(root, "demos")
        d = make_fuye(watch)
        make_batch(os.path.join(watch, "batch-rag"), jobs=(("ep01", "done", "green"), ("ep02", "done", "red")))
        with mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": watch, "VSTUDIO_HOME": os.path.join(root, "home")}):
            data = os.path.join(root, "desk")
            h = History(data, Registry(data))
            ib = IB.Inbox(data, h)
            items = ib.list()["items"]
            kinds = sorted(i["kind"] for i in items)
            self.assertEqual(kinds, ["confirm", "review"])
            conf = next(i for i in items if i["kind"] == "confirm")
            self.assertEqual(conf["params"]["n"], 2)
            self.assertEqual(conf["project"]["id"], next(r["id"] for r in h.list()["items"] if r["dir"] == d))
            rv = next(i for i in items if i["kind"] == "review")
            self.assertEqual(rv["code"], "inbox.reviewClips")
            ib.answer([conf["key"]], dict(approve=["o0"]))
            self.assertEqual([i["kind"] for i in ib.list()["items"]], ["review"])
            self.assertFalse(os.path.exists(os.path.join(d, ".vstudio")))     # nothing written in the folder
            ib.undo([conf["key"]])
            self.assertEqual(len(ib.list()["items"]), 2)
            with self.assertRaises(BadRequest):
                ib.answer(["zz"])

    def test_qc_issue_codes(self):
        jd = tempfile.mkdtemp()
        os.makedirs(os.path.join(jd, "qc"))
        with open(os.path.join(jd, "qc", "qc.json"), "w") as f:
            json.dump(dict(checks=[dict(name="lost-words", ok=False, value=1, reason="lost: '我们' @19.01s"),
                                   dict(name="frozen-frames", ok=False, reason="frozen 0.0s for 5.4s"),
                                   dict(name="loudness", ok=True)]), f)
        iss = IB.qc_issues(jd)
        self.assertEqual([i["code"] for i in iss], ["lost-words", "frozen-frames"])
        self.assertEqual(iss[0]["at"], 19.01)
        self.assertEqual(iss[0]["quote"], "我们")
        self.assertEqual(iss[1]["seconds"], 5.4)


if __name__ == "__main__":
    unittest.main()
