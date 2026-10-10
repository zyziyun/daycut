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

import desk_mock as DM  # noqa: E402

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


class Fixture(unittest.TestCase):
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


class OutputsTest(Fixture):
    def test_show_has_words_flattened_caps_and_notes(self):
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual([w["w"] for w in doc["words"]][:2], ["你在", "副业"])
        self.assertEqual(doc["mode"], "flattened")
        self.assertFalse(doc["caps"]["caption_text"])
        self.assertIn("captions-add-only", [n["code"] for n in doc["caps_notes"]])
        self.assertEqual(doc["engine"], "desk")
        self.assertGreaterEqual(len(doc["waveform"]), 240)

    def test_edit_steps_undo_redo_render(self):
        r = self.o.edit(self.item, "A_换圈子", [dict(op="trim", start=1.0, end=3.3),
                                               dict(op="effect_add", effect="pop-words", start=2.8,
                                                    params=dict(text="底气"))])
        self.assertEqual([d["code"] for d in r["step"]["describe"]], ["op-trim", "op-effect-add"])
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual(doc["trim"], dict(start=1.0, end=3.3))
        fx = doc["effects"][0]
        self.assertEqual((fx["label"]["zh"], fx["end"]), ("弹出大字", 3.3))      # default 1.2 s, clamped to the clip
        self.assertEqual((doc["undo"], doc["redo"]), (1, 0))
        self.assertTrue(os.path.exists(WK.record_path(self.d)))               # 转成项目 on the first edit
        self.o.edit(self.item, "A_换圈子", [dict(op="effect_update", id=fx["id"], start=2.0, end=2.8)])
        self.assertEqual(self.o.show(self.item, "A_换圈子")["effects"][0]["start"], 2.0)
        rr = self.o.render(self.item, "A_换圈子")
        self.assertTrue(rr["simulated"])
        self.assertTrue(self.o.show(self.item, "A_换圈子")["renders"][0]["fresh"])
        self.o.undo(self.item, "A_换圈子")
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual(doc["effects"][0]["start"], 2.8)
        self.assertFalse(doc["renders"][0]["fresh"])
        self.o.undo(self.item, "A_换圈子", redo=True)
        self.assertEqual(self.o.show(self.item, "A_换圈子")["effects"][0]["start"], 2.0)
        self.o.undo(self.item, "A_换圈子", steps=2)
        doc = self.o.show(self.item, "A_换圈子")
        self.assertIsNone(doc["trim"])
        self.assertEqual((doc["effects"], doc["undo"], doc["redo"]), ([], 0, 2))

    def test_refusals_keep_codes_and_steps_are_all_or_nothing(self):
        for ops, code in (([dict(op="caption_text", cue="0", text="x")], "captions-not-ours"),
                          ([dict(op="effect_add", effect="nope", start=0)], "unknown-effect"),
                          ([dict(op="effect_add", effect="pop-words", start=0)], "bad-param"),
                          ([dict(op="trim", start=1, end=1.2)], "too-short")):
            with self.assertRaises(OU.EngineMessage) as cm:
                self.o.edit(self.item, "A_换圈子", ops)
            self.assertEqual(cm.exception.doc["code"], code)
        with self.assertRaises(OU.EngineMessage):
            self.o.edit(self.item, "A_换圈子", [dict(op="cut", start=0.5, end=1.0), dict(op="effect_remove", id="fx9")])
        self.assertEqual(self.o.show(self.item, "A_换圈子")["cuts"], [])
        with self.assertRaises(BadRequest):
            self.o.edit(self.item, "A_换圈子", [dict(op="rm -rf")])
        with self.assertRaises(BadRequest):
            self.o.show(self.item, "../../etc")
        with self.assertRaises(OU.EngineMessage):
            self.o.undo(self.item, "A_换圈子")

    def test_ask_proposes_valid_ops_and_explains_flattened(self):
        r = self.o.ask(self.item, "A_换圈子", "开头太慢，从「其实」开始，把「底气」弹出来，字幕大一点")
        ops = [p["op"] for p in r["proposals"]]
        self.assertEqual(ops[0], dict(op="trim", start=2.4, end=3.3))
        self.assertEqual(ops[1]["effect"], "pop-words")
        self.assertEqual(ops[1]["params"]["text"], "底气")
        self.assertIn("captions-add-only", [w["code"] for w in r["warnings"]])
        self.o.edit(self.item, "A_换圈子", [p["op"] for p in r["proposals"]])     # every proposal is accepted

    def test_effects_catalogue_has_zh_labels(self):
        effs = self.o.effects()["effects"]
        self.assertTrue(all(e["label"]["zh"] and e["label"]["en"] and e["category"] for e in effs))
        self.assertIn("pop-words", {e["id"] for e in effs})

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


class ChatEditTest(Fixture):
    """The chat-first editor: selective revert of one card, the chat transcript per clip, context, compare."""
    C = "A_换圈子"

    def test_revert_one_older_step_keeps_the_later_ones(self):
        s1 = self.o.edit(self.item, self.C, [dict(op="speed", value=1.1)])["step"]["id"]
        r2 = self.o.edit(self.item, self.C, [dict(op="effect_add", effect="pop-words", start=2.8, params=dict(text="底气"))])
        fx = self.o.show(self.item, self.C)["effects"][0]["id"]
        self.o.edit(self.item, self.C, [dict(op="export_add", target="9:16")])
        r = self.o.revert(self.item, self.C, s1)
        self.assertEqual(r["reverted"], s1)
        doc = self.o.show(self.item, self.C)
        self.assertEqual(doc["speed"], 1.0)
        self.assertEqual([e["id"] for e in doc["effects"]], [fx])            # the later card is untouched
        self.assertEqual(doc["exports"][0]["target"], "9:16")
        self.assertTrue(doc["steps"][0]["reverted"])
        self.assertEqual(doc["steps"][-1]["revert_of"], s1)
        with self.assertRaises(OU.EngineMessage) as cm:
            self.o.revert(self.item, self.C, s1)
        self.assertEqual(cm.exception.doc["code"], "already-reverted")
        self.o.undo(self.item, self.C)                                         # the revert is one undo step
        self.assertEqual(self.o.show(self.item, self.C)["speed"], 1.1)
        self.o.undo(self.item, self.C, redo=True)
        self.assertEqual(self.o.show(self.item, self.C)["speed"], 1.0)
        self.o.edit(self.item, self.C, [dict(op="effect_update", id=fx, params=dict(text="必看"))])
        with self.assertRaises(OU.EngineMessage) as cm:                        # a later step builds on it
            self.o.revert(self.item, self.C, r2["step"]["id"])
        self.assertEqual((cm.exception.doc["code"], cm.exception.doc["params"]["n"]), ("revert-conflict", 1))
        with self.assertRaises(OU.EngineMessage) as cm:
            self.o.revert(self.item, self.C, "s99-x")
        self.assertEqual(cm.exception.doc["code"], "unknown-step")

    def test_chat_history_persists_with_the_clip(self):
        r = self.o.ask(self.item, self.C, "再紧凑一点")
        self.assertTrue(r["turn"])
        self.assertEqual(r["provider"], "rules")
        self.o.edit(self.item, self.C, [p["op"] for p in r["proposals"]] or [dict(op="speed", value=1.1)], turn=r["turn"])
        u = self.o.chat_add(self.item, self.C, dict(role="user", text="/trim", card="trim", junk=1))["turn"]
        self.assertNotIn("junk", u)
        # a fresh Outputs (an app restart) rebuilds the same conversation from the clip's edit doc
        o2 = OU.Outputs(os.path.join(self.root, "desk"), self.h)
        chat = o2.show(self.item, self.C)["chat"]
        self.assertEqual([t["id"] for t in chat], [r["turn"], u["id"]])
        self.assertEqual(chat[0]["status"], "applied")
        self.assertEqual(chat[0]["text"], "再紧凑一点")
        self.assertEqual(chat[0]["applied_step"], o2.show(self.item, self.C)["steps"][0]["id"])
        o2.revert(self.item, self.C, chat[0]["applied_step"])
        self.assertEqual(o2.show(self.item, self.C)["chat"][0]["status"], "reverted")
        self.assertEqual(o2.chat_update(self.item, self.C, u["id"], dict(status="discarded"))["turn"]["status"], "discarded")
        self.assertEqual(self.o.show(self.item, "B_自媒体")["chat"], [])          # per clip
        with self.assertRaises(BadRequest):
            o2.chat_update(self.item, self.C, u["id"], dict(status="bogus"))
        with self.assertRaises(OU.EngineMessage):
            o2.chat_update(self.item, self.C, "t9-ffff", dict(status="note"))

    def test_context_selection_and_open_effect(self):
        r = self.o.ask(self.item, self.C, "剪掉这段", context=dict(range=[2.4, 2.8]))
        self.assertEqual(r["context"], dict(range=[2.4, 2.8]))
        self.assertEqual([p["op"] for p in r["proposals"]], [dict(op="cut", start=2.4, end=2.8)])
        self.o.edit(self.item, self.C, [dict(op="effect_add", effect="pop-words", start=2.8, params=dict(text="底气"))])
        fx = self.o.show(self.item, self.C)["effects"][0]
        r = self.o.ask(self.item, self.C, "大一点，晚一点", context=dict(effect=fx["id"]))
        op = r["proposals"][0]["op"]
        self.assertEqual((op["op"], op["id"], op["start"]), ("effect_update", fx["id"], 3.1))
        self.assertGreater(op["params"]["size"], 0.11)
        for bad in (dict(range=[3, 1]), dict(range="x"), dict(cues="c1"), "x"):
            with self.assertRaises(BadRequest):
                self.o.ask(self.item, self.C, "x", context=bad)

    def test_export_job_reports_progress_and_can_stop(self):
        from desk_engine.common import EventBus
        bus = EventBus()
        q = bus.subscribe()
        o = OU.Outputs(os.path.join(self.root, "desk"), self.h, bus=bus)
        with mock.patch.dict(os.environ, {"DESK_EXPORT_STEP": "0.01"}):
            job = o.export(self.item, self.C, ["primary", "douyin:vertical"])["job"]
            evs, t0 = [], time.time()
            while time.time() - t0 < 10 and not any(x.get("event") == "render-done" for x in evs):
                try:
                    evs.append(q.get(timeout=1))
                except Exception:  # noqa: BLE001
                    pass
        mine = [x for x in evs if x.get("type") == "output-render" and x.get("job") == job]
        self.assertEqual([x["target"] for x in mine if x["event"] == "target-done"], ["primary", "douyin:vertical"])
        self.assertEqual([x["stage"] for x in mine if x["event"] == "stage-done"][:4], ["canvas", "timeline", "audio", "final"])
        self.assertTrue(o.show(self.item, self.C)["renders"])
        with mock.patch.dict(os.environ, {"DESK_EXPORT_STEP": "2"}):
            job = o.export(self.item, self.C, ["primary"])["job"]
            o.export_stop(job)
            t0 = time.time()
            got = []
            while time.time() - t0 < 5 and not got:
                try:
                    x = q.get(timeout=1)
                    if x.get("job") == job and x.get("event") == "stopped":
                        got.append(x)
                except Exception:  # noqa: BLE001
                    pass
        self.assertTrue(got)
        with self.assertRaises(BadRequest):
            o.export(self.item, self.C, ["../x"])

    def test_compare_render_applies_nothing(self):
        r = self.o.render(self.item, self.C, with_ops=[dict(op="speed", value=1.5)])
        self.assertTrue(r["compare"] and r["simulated"])
        doc = self.o.show(self.item, self.C)
        self.assertEqual((doc["undo"], doc["renders"]), (0, []))
        with self.assertRaises(OU.EngineMessage):
            self.o.render(self.item, self.C, with_ops=[dict(op="trim", start=1, end=1.1)])


class RenameTest(Fixture):
    def test_rename_and_unhide_one(self):
        self.h.rename(self.d, "副业复盘 · 4 条切片")
        row = next(r for r in self.h.list()["items"] if r["dir"] == self.d)
        self.assertEqual(row["name"], "副业复盘 · 4 条切片")
        self.h.hide(self.d)
        self.assertFalse(any(r["dir"] == self.d for r in self.h.list()["items"]))
        self.h.unhide(self.d)
        self.assertTrue(any(r["dir"] == self.d for r in self.h.list()["items"]))
        self.assertTrue(os.path.exists(os.path.join(self.d, "PICKS.md")))


class CalendarTest(Fixture):
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


class RebaseTest(unittest.TestCase):
    def test_cloned_batch_paths_map_back_into_the_folder(self):          # B11
        from desk_engine.common import rebase
        b = tempfile.mkdtemp()
        os.makedirs(os.path.join(b, "jobs", "ep01", "preview"))
        open(os.path.join(b, "jobs", "ep01", "preview", "sheet.jpg"), "wb").close()
        old = "/Users/me/Desktop/old-place/batch-rag/jobs/ep01/preview/sheet.jpg"
        self.assertEqual(rebase(old, b), os.path.join(b, "jobs", "ep01", "preview", "sheet.jpg"))
        made_on_windows = "D:\\素材\\old place\\batch-rag\\jobs\\ep01\\preview\\sheet.jpg"   # a Windows path, any OS
        self.assertEqual(rebase(made_on_windows, b), os.path.join(b, "jobs", "ep01", "preview", "sheet.jpg"))
        self.assertEqual(rebase("/elsewhere/x.jpg", b), "/elsewhere/x.jpg")
        self.assertEqual(rebase("rel/x.jpg", b), "rel/x.jpg")


class IntakeTest(unittest.TestCase):
    def test_rule_plan_shape_and_question(self):
        p = DM.rule_plan("把这条副业复盘剪成 4 条小红书切片，每条一分钟左右", ["/x/多元副业复盘_final.mp4"],
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
        p = DM.rule_plan("剪成 4 条小红书切片", ["/x/a.mp4"], probe=lambda _p: dict(duration=600.0))
        r = DM.rule_revise(p, "只要 3 条，不要 9:16")
        proj = r["projects"][0]
        self.assertEqual(proj["items"]["count"], 3)
        self.assertEqual(proj["params"]["aspects"], ["3:4"])
        self.assertEqual(r["revisions"][-1]["prompt"], "只要 3 条，不要 9:16")
        same = DM.rule_revise(p, "嗯？")
        self.assertTrue(same["warnings"])

    def test_async_plan_and_mock_apply(self):
        root = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"VSTUDIO_HOME": os.path.join(root, "home"), "DESK_MOCK_STEP": "0.01"}):
            it = DM.MockIntake(os.path.join(root, "desk"), None)
            pid = it.start("做一期讲解视频", [])["id"]          # words only: planned (a cut with no footage waits)
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
            self.assertEqual(it.recent()[0]["prompt"], "做一期讲解视频")


class IntakeEngineHiccupTest(unittest.TestCase):
    """No mock in the product: a failed ``vstudio.intake`` probe used to make "Make a plan" write fake projects and
    fake pilot results. Now the plan card says why and offers Try again; nothing is written."""

    class Runner:
        python, env = "python3", {}

        def __init__(self, help_text):
            self.help, self.calls = help_text, []

        def sibling(self, mod):
            r = self

            class S:
                def text(self, args, **kw):
                    r.calls.append(args)
                    if isinstance(r.help, Exception):
                        raise r.help
                    return r.help

                def json(self, args, **kw):
                    r.calls.append(args)
                    if args[0] == "plan":
                        return dict(kind="vstudio.intake.plan", version=1, projects=[], prompt="p")
                    raise AssertionError(f"unexpected {args}")
            return S()

    def wait(self, it, pid):
        for _ in range(300):
            if it.get(pid)["state"] != "running":
                return it.get(pid)
            time.sleep(0.01)
        self.fail("plan never finished")

    def test_probe_hiccup_is_an_error_with_retry_and_writes_nothing(self):
        root = tempfile.mkdtemp()
        home = os.path.join(root, "home")
        with mock.patch.dict(os.environ, {"VSTUDIO_HOME": home}):
            runner = self.Runner(RuntimeError("vstudio.intake: exit 1: database is locked"))
            it = IN.Intake(os.path.join(root, "desk"), None, runner, "real")
            pid = it.start("剪一条口播", [])["id"]
            j = self.wait(it, pid)
            self.assertEqual((j["state"], j["error_code"]), ("error", "intake"))
            self.assertIn("did not answer", j["error"])
            self.assertIsNone(j.get("plan"))
            with self.assertRaises(BadRequest):
                it.apply(pid, plan=dict(kind="vstudio.intake.plan", projects=[dict(name="x")]), run=True)
            self.assertFalse(os.path.exists(os.path.join(home, "projects.json")))
            self.assertFalse(os.path.exists(os.path.join(home, "projects")))
            with self.assertRaises(BadRequest):
                it.retry_pilot(root)
            runner.help = "usage: python -m vstudio.intake {plan,revise,apply}"     # the hiccup passed: Try again
            it.retry(pid)
            j = self.wait(it, pid)
            self.assertEqual(j["state"], "done")
            self.assertGreaterEqual(runner.calls.count(["--help"]), 2)            # probed again on retry

    def test_no_engine_at_all(self):
        it = IN.Intake(tempfile.mkdtemp(), None, None, "real")
        pid = it.start("x", [])["id"]
        j = self.wait(it, pid)
        self.assertEqual((j["state"], j["error_code"]), ("error", "intake"))

    def test_no_rule_planner_or_simulated_pilot_in_the_product(self):
        for name in ("rule_plan", "rule_revise", "_mock_apply", "_mock_pilot"):
            self.assertFalse(hasattr(IN, name) or hasattr(IN.Intake, name), name)
        from desk_engine import pilot
        self.assertFalse(hasattr(pilot, "record_mock"))


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


class PlanTimingTest(unittest.TestCase):
    def test_the_card_gets_the_real_planning_time(self):
        """The card said "read 1 file in 1 s" (the planner's own number) while planning took 20-40 s."""
        root = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"VSTUDIO_HOME": os.path.join(root, "home"), "DESK_MOCK_STEP": "0.3"}):
            it = DM.MockIntake(os.path.join(root, "desk"), None)
            pid = it.start("做一期讲解视频", [])["id"]
            for _ in range(300):
                if it.get(pid)["state"] != "running":
                    break
                time.sleep(0.02)
            j = it.get(pid)
            self.assertEqual(j["state"], "done")
            self.assertGreaterEqual(j["seconds"], 0.3)
            self.assertLess(j["plan"]["planner"]["seconds"], 0.3)             # the planner's own number is not it


class IntakeProgressTest(unittest.TestCase):
    """While a plan runs, the engine's ``--json-events`` become the job's ``progress`` (the card's stage, bar and
    steps); an engine without the flag still plans (no progress)."""

    def wait(self, it, pid):
        for _ in range(500):
            if it.get(pid)["state"] != "running":
                return it.get(pid)
            time.sleep(0.01)
        self.fail("plan never finished")

    def test_events_become_the_jobs_progress(self):
        import threading
        mid = threading.Event()
        go = threading.Event()
        seen_args = []

        class Runner:
            python, env = "python3", {}

            def sibling(self, mod):
                class S:
                    def text(self, args, **kw):
                        return "usage: python -m vstudio.intake plan [--json-events]" if args[:1] == ["plan"] \
                            else "usage: python -m vstudio.intake {plan,revise,apply}"

                    def events(self, args, on_event, **kw):
                        seen_args.append(args)
                        for ev in (dict(event="stage", stage="scan", inputs=2),
                                   dict(event="stage", stage="scan", inputs=2, files=27),
                                   dict(event="stage", stage="probe", file="talk.mp4", i=3, n=27, kind="video"),
                                   dict(event="stage", stage="transcribe", file="talk.mp4", total_s=764.0, done_s=0),
                                   dict(event="progress", stage="transcribe", file="talk.mp4", done_s=250.0,
                                        total_s=764.0),
                                   dict(event="progress", stage="faces", done_s=1.0)):     # not the current stage
                            on_event(ev)
                        mid.set()
                        go.wait(5)
                        on_event(dict(event="stage", stage="model", provider="claude-code"))
                        return dict(event="done", plan=dict(kind="vstudio.intake.plan", version=1, projects=[]))

                    def json(self, args, **kw):
                        raise AssertionError("an engine with --json-events streams")
                return S()

        it = IN.Intake(tempfile.mkdtemp(), None, Runner(), "real")
        pid = it.start("把讲方法的部分剪出来", ["/x/talk.mp4", "/x/folder"])["id"]
        self.assertTrue(mid.wait(5))
        p = it.get(pid)["progress"]
        self.assertEqual((p["stage"], p["file"], p["done_s"], p["total_s"]), ("transcribe", "talk.mp4", 250.0, 764.0))
        self.assertEqual(p["seen"], ["scan", "probe", "transcribe"])
        self.assertEqual(p["files"], 27)                                       # the scan's count stays
        self.assertNotIn("i", p)                                               # the probe's counter went with it
        go.set()
        j = self.wait(it, pid)
        self.assertEqual(j["state"], "done")
        self.assertEqual(j["progress"]["stage"], "model")
        self.assertEqual(j["progress"]["provider"], "claude-code")
        self.assertIn("--json-events", seen_args[0])

    def test_reused_transcript_is_remembered(self):
        it = IN.Intake(tempfile.mkdtemp(), None, None, "real")
        it.jobs["a" * 12] = dict(id="a" * 12, state="running")
        for ev in (dict(event="stage", stage="transcribe", file="t.mp4", cached="shared"),
                   dict(event="stage", stage="model", provider="codex")):
            it._progress("a" * 12, ev)
        p = it.get("a" * 12)["progress"]
        self.assertEqual((p["stage"], p.get("reused"), p["seen"]), ("model", True, ["transcribe", "model"]))

    def test_older_engine_plans_without_progress(self):
        class Runner:
            python, env = "python3", {}

            def sibling(self, mod):
                class S:
                    def text(self, args, **kw):
                        return "usage: python -m vstudio.intake {plan,revise,apply}"

                    def json(self, args, **kw):
                        assert "--json-events" not in args
                        return dict(kind="vstudio.intake.plan", version=1, projects=[], prompt="p")
                return S()

        it = IN.Intake(tempfile.mkdtemp(), None, Runner(), "real")
        j = self.wait(it, it.start("x", [])["id"])
        self.assertEqual(j["state"], "done")
        self.assertIsNone(j["progress"])

    def test_mock_engine_simulates_progress(self):
        root = tempfile.mkdtemp()
        with mock.patch.dict(os.environ, {"VSTUDIO_HOME": os.path.join(root, "home"), "DESK_MOCK_STEP": "0.01"}):
            it = DM.MockIntake(os.path.join(root, "desk"), None, probe=lambda _p: dict(duration=764.0))
            j = self.wait(it, it.start("剪一条口播", ["/x/talk.mp4"])["id"])
            self.assertEqual(j["progress"]["seen"], ["scan", "probe", "transcribe", "model", "write"])


class CliRunnerEventsTest(unittest.TestCase):
    """``CliRunner.events``: JSON lines from a real child, as they come; the done line; a failure's reason."""

    def runner(self, body):
        from desk_engine.caps import CliRunner
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "fake_engine.py"), "w", encoding="utf-8") as f:
            f.write(body)
        env = dict(os.environ, PYTHONPATH=d)
        return CliRunner(sys.executable, env, timeout=20, module="fake_engine")

    def test_streams_events_and_returns_done(self):
        r = self.runner(
            "import json, sys, time\n"
            "print('a log line', file=sys.stderr)\n"
            "for k in range(3):\n"
            "    print(json.dumps(dict(event='progress', stage='transcribe', done_s=k)), flush=True)\n"
            "print('not json')\n"
            "print(json.dumps(dict(event='done', plan=dict(id='p1'))), flush=True)\n")
        got, track = [], []
        done = r.events(["plan"], got.append, track=track)
        self.assertEqual(done["plan"]["id"], "p1")
        self.assertEqual([e["done_s"] for e in got], [0, 1, 2])
        self.assertEqual(track, [])

    def test_error_event_is_the_reason(self):
        from desk_engine.caps import CliError
        r = self.runner(
            "import json, sys\n"
            "print(json.dumps(dict(event='error', error='PlanError: no inputs')), flush=True)\n"
            "print('Traceback ...', file=sys.stderr)\n"
            "sys.exit(1)\n")
        with self.assertRaises(CliError) as cm:
            r.events(["plan"], lambda ev: None)
        self.assertIn("PlanError: no inputs", str(cm.exception))

    def test_timeout_kills_the_child(self):
        from desk_engine.caps import CliError
        r = self.runner("import time\ntime.sleep(30)\n")
        t0 = time.time()
        with self.assertRaises(CliError) as cm:
            r.events(["plan"], lambda ev: None, timeout=0.5, track=[])
        self.assertIn("timed out", str(cm.exception))
        self.assertLess(time.time() - t0, 10)


class MappedWordsTest(unittest.TestCase):
    """A batch clip opens with its words: the pipeline's transcript mapped through the job's cuts, not 「听一遍」."""

    def test_batch_clip_has_words_from_the_apply_sidecar(self):
        from vstudio import cleanup
        root = tempfile.mkdtemp()
        b = make_batch(os.path.join(root, "b"), jobs=(("ep01", "done", "green"),))
        jd = os.path.join(b, "jobs", "ep01")
        for sub in ("apply", os.path.join("export", "exports")):
            os.makedirs(os.path.join(jd, sub), exist_ok=True)
        with open(os.path.join(jd, "job.json"), "w", encoding="utf-8") as f:
            json.dump(dict(id="ep01", params=dict(title="Plan first")), f)
        words = [dict(w=w, t=t, te=t + 0.3) for w, t in (("plan", 0.5), ("um", 1.0), ("first", 1.6))]
        cleanup.write_sidecar(os.path.join(jd, "apply", "body.mp4"), "src.mp4", [(0.4, 0.9), (1.5, 2.0)], words)
        open(os.path.join(jd, "export", "exports", "youtube-vertical.mp4"), "wb").close()
        with open(os.path.join(jd, "export", "exports", "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(dict(exports=[dict(file="youtube-vertical.mp4", platform="youtube", orientation="vertical",
                                         w=1080, h=1920, duration=1.0)]), f)
        data = os.path.join(root, "desk")
        with mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": ""}):
            h = History(data, Registry(data))
            item = h.open(b)["id"]
            doc = OU.Outputs(data, h).show(item, "ep01")
        self.assertEqual([w["w"] for w in doc["words"]], ["plan", "first"])
        self.assertAlmostEqual(doc["words"][1]["t"], 0.6, places=2)
        self.assertTrue(doc["words_sig"])


class PublishedTest(Fixture):
    """An edited clip is listed (for publishing, the calendar, the queue) with its fresh final renders; the editor
    keeps editing the original."""

    def test_fresh_final_renders_stand_in_for_the_original(self):
        orig = self.o.clips(self.item)["clips"][0]
        f0 = orig["files"][0]["path"]
        oid = "final/A_换圈子.mp4"
        rdir = tempfile.mkdtemp()
        prim, vert, cov = (os.path.join(rdir, n) for n in ("primary.final.mp4", "douyin-vertical.final.mp4", "c.jpg"))
        for p in (prim, vert, cov):
            open(p, "wb").close()
        fin = dict(primary=dict(file=prim, cover=cov, w=1080, h=1440, duration=20.0),
                   **{"douyin:vertical": dict(file=vert, cover=None, w=1080, h=1920, duration=20.0)})
        self.o._engine_list = lambda e: {os.path.realpath(f0): oid}
        self.o._edited[os.path.realpath(self.d)] = {oid}
        with mock.patch("vstudio.project.outrender.fresh_finals", return_value=fin):
            c = self.o.clips(self.item)["clips"][0]
        self.assertTrue(c["edited"])
        self.assertEqual(c["files"][0]["path"], prim)
        self.assertEqual(c["cover"], cov)
        self.assertEqual(next(f for f in c["files"] if f["aspect"] == "9:16")["path"], vert)
        with mock.patch("vstudio.project.outrender.fresh_finals", return_value={}):
            c = self.o.clips(self.item)["clips"][0]
        self.assertEqual(c["files"][0]["path"], f0)
        self.assertTrue(c["edited_stale"])
        self.assertEqual(self.o._clip(self.item, c["id"])[1]["files"][0]["path"], f0)   # the editor's own file


class RenderQueueTest(Fixture):
    def test_renders_of_one_clip_run_one_after_the_other(self):
        """A background render and her Export never write the same stage files at once: the second waits."""
        events = []

        class Bus:
            def publish(self, kind, **kw):
                if kind == "output-render":
                    events.append((kw.get("job"), kw.get("event")))
        self.o.bus = Bus()
        with mock.patch.dict(os.environ, {"DESK_EXPORT_STEP": "0.05"}):
            a = self.o.export(self.item, "A_换圈子", ["primary"])["job"]
            b = self.o.export(self.item, "A_换圈子", ["primary"])["job"]
            t0 = time.time()
            while sum(1 for _, ev in events if ev == "render-done") < 2 and time.time() - t0 < 20:
                time.sleep(0.05)
        order = [j for j, ev in events if ev in ("target-start", "render-done")]
        self.assertEqual(len(order), 4)
        first = order[0]
        self.assertEqual(order[:2], [first, first])               # one starts and finishes before the other starts
        self.assertEqual(set(order), {a, b})
