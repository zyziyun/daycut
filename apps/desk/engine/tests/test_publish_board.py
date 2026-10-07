"""发布 board (publish redesign A): scheduleMany / removeMany + restore (unschedule with undo), updatePost (caption,
platform, on / off, stats, filled), per-post status + warnings (caption too long, no caption, slot clash),
fillWeek in the engine, and the one-sentence planner (parse + preview that never writes)."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402
from desk_engine import schedule_text as ST  # noqa: E402
from desk_engine import works as WK  # noqa: E402
from desk_engine.calendar import Calendar, post_text, shorten_rules, text_limit  # noqa: E402
from desk_engine.common import BadRequest, Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from test_v04 import make_fuye  # noqa: E402

A, B = "A_换圈子", "B_自媒体"
MON = "2026-10-05"   # a Monday


class Board(unittest.TestCase):
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
        WK.adopt(self.d)
        self.cal = Calendar(data, self.h, self.o)

    def tearDown(self):
        self.env.stop()

    def posts(self):
        return self.cal.list()["posts"]

    def test_schedule_many_is_one_step_and_decorated(self):
        r = self.cal.add_many([dict(item=self.item, clip=A, platform=p, at="2026-10-07T20:00") for p in ("xiaohongshu", "douyin", "x")])
        self.assertEqual(len(r["ids"]), 3)
        ps = self.posts()
        self.assertEqual({p["platform"] for p in ps}, {"xiaohongshu", "douyin", "x"})
        p = next(x for x in ps if x["platform"] == "xiaohongshu")
        self.assertEqual(p["status"], "draft")
        self.assertTrue(p["enabled"])
        self.assertIn("同一个行业待越久，思路越窄", p["caption"])          # the clip's post copy
        self.assertIn("#副业", p["caption"])
        self.assertFalse(p["caption_custom"])
        self.assertEqual(p["limit"], 1000)
        self.assertEqual(p["project"], "fuye")
        self.assertNotIn(A, [q["clip"] for q in self.cal.list()["queue"]])
        # all or nothing: one bad row -> nothing written
        with self.assertRaises(BadRequest):
            self.cal.add_many([dict(item=self.item, clip=B, platform="xiaohongshu", at="2026-10-08T20:00"),
                               dict(item=self.item, clip=B, platform="xiaohongshu", at="tomorrow")])
        self.assertEqual(len(self.posts()), 3)

    def test_unschedule_and_undo_restores_the_same_rows(self):
        ids = self.cal.add_many([dict(item=self.item, clip=A, platform=p, at="2026-10-07T20:00") for p in ("xiaohongshu", "x")])["ids"]
        self.cal.update(ids[1], dict(caption="my own X text"))
        files = sorted(os.listdir(os.path.join(self.d, "final")))
        gone = self.cal.remove_many(ids)["removed"]
        self.assertEqual(self.posts(), [])
        self.assertIn(A, [q["clip"] for q in self.cal.list()["queue"]])     # back in the queue
        self.assertEqual(sorted(os.listdir(os.path.join(self.d, "final"))), files)  # never deletes files
        self.cal.restore(gone)
        back = {p["id"]: p for p in self.posts()}
        self.assertEqual(set(back), set(ids))
        self.assertEqual(back[ids[1]]["caption"], "my own X text")
        self.assertTrue(back[ids[1]]["caption_custom"])
        self.cal.restore(gone)                                             # idempotent
        self.assertEqual(len(self.posts()), 2)

    def test_update_caption_platform_onoff_state_stats(self):
        pid = self.cal.add(dict(item=self.item, clip=A, platform="xiaohongshu", at="2026-10-07T20:00"))["id"]
        self.cal.update(pid, dict(caption="短文案"))
        self.assertEqual(self.posts()[0]["caption"], "短文案")
        self.cal.update(pid, dict(caption=None))                           # back to the clip's copy
        self.assertFalse(self.posts()[0]["caption_custom"])
        self.cal.update(pid, dict(platform="douyin"))
        self.assertEqual(self.posts()[0]["platform"], "douyin")
        self.cal.update(pid, dict(enabled=False))
        self.assertFalse(self.posts()[0]["enabled"])
        self.assertEqual(self.cal.confirm_week(MON)["ready"], 0)          # switched off: not confirmed
        self.cal.update(pid, dict(enabled=True))
        self.assertEqual(self.cal.confirm_week(MON)["ready"], 1)
        self.cal.update(pid, dict(state="filled"))
        self.assertEqual(self.posts()[0]["status"], "filled")
        self.cal.update(pid, dict(state="posted", stats=dict(views=1204, likes=96)))
        p = self.posts()[0]
        self.assertEqual((p["status"], p["stats"]["views"]), ("posted", 1204))
        for bad in (dict(state="published"), dict(enabled="no"), dict(platform="X!"), dict(stats=dict(views=-1)),
                    dict(caption=1)):
            with self.assertRaises(BadRequest):
                self.cal.update(pid, bad)

    def test_warnings_caption_too_long_no_caption_slot_clash(self):
        ids = self.cal.add_many([dict(item=self.item, clip=A, platform="x", at="2026-10-09T20:00"),
                                 dict(item=self.item, clip=B, platform="x", at="2026-10-09T20:00"),
                                 dict(item=self.item, clip=B, platform="xiaohongshu", at="2026-10-09T21:00")])["ids"]
        self.cal.update(ids[0], dict(caption="再小的博主也是博主" * 20))       # 180 CJK = 360 weighted on X
        self.cal.update(ids[2], dict(caption=""))
        ps = {p["id"]: p for p in self.posts()}
        kinds = lambda i: sorted(w["kind"] for w in ps[i]["warnings"])   # noqa: E731
        self.assertEqual(kinds(ids[0]), ["caption_too_long", "slot_clash"])
        w = next(w for w in ps[ids[0]]["warnings"] if w["kind"] == "caption_too_long")
        self.assertEqual((w["n"], w["max"]), (360, 280))                   # X weighs CJK as 2
        self.assertEqual(kinds(ids[1]), ["slot_clash"])
        self.assertEqual(kinds(ids[2]), ["no_caption"])
        self.cal.update(ids[1], dict(at="2026-10-09T21:30"))
        self.assertEqual(sorted(w["kind"] for w in next(p for p in self.posts() if p["id"] == ids[0])["warnings"]), ["caption_too_long"])

    def test_fill_week_one_undo(self):
        self.cal.add(dict(item=self.item, clip=A, platform="xiaohongshu", at="2026-10-06T12:00"))
        r = self.cal.fill_week(dict(start=MON, today=MON, platforms=["xiaohongshu", "douyin"],
                                    times=dict(xiaohongshu="20:00", douyin="12:30")))
        # the queue has one clip left (B): the first free day (Mon) gets it on both platforms
        self.assertEqual(len(r["ids"]), 2)
        ats = sorted((p["platform"], p["at"]) for p in r["posts"])
        self.assertEqual(ats, [("douyin", "2026-10-05T12:30"), ("xiaohongshu", "2026-10-05T20:00")])
        self.cal.remove_many(r["ids"])
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.cal.fill_week(dict(start=MON, today="2026-10-12", platforms=["x"]))["reason"], "no_free_days")
        with self.assertRaises(BadRequest):
            self.cal.fill_week(dict(start=MON, platforms=[]))

    def test_plan_preview_never_writes_and_moves_clashes(self):
        self.cal.add(dict(item=self.item, clip=A, platform="xiaohongshu", at="2026-10-07T20:00"))
        before = self.cal._rows()
        p = self.cal.plan(dict(text="每天晚上8点发一条小红书，周末不发", start=MON, today=MON, platforms=["douyin"],
                               times={}))
        self.assertTrue(p["ok"])
        self.assertEqual(self.cal._rows(), before)                         # preview only
        self.assertEqual(p["platforms"], ["xiaohongshu"])
        self.assertEqual(p["time"], "20:00")
        self.assertEqual(p["days"], [0, 1, 2, 3, 4])
        self.assertEqual(len(p["drafts"]), 1)                              # one clip left in the queue
        self.assertEqual(p["drafts"][0]["at"], "2026-10-06T20:00")         # from tomorrow (Tue)
        # selection: the same clip twice in a row lands on Tue and Wed; Wed 20:00 is taken -> 21:00
        sel = [dict(item=self.item, clip=B), dict(item=self.item, clip=A)]
        p = self.cal.plan(dict(text="every weekday at 8pm on RedNote", start=MON, today=MON, clips=sel))
        self.assertEqual([d["at"] for d in p["drafts"]], ["2026-10-06T20:00", "2026-10-07T21:00"])
        self.assertEqual(p["adjustments"], [dict(kind="moved", platform="xiaohongshu", frm="2026-10-07T20:00", to="2026-10-07T21:00")])
        self.assertTrue(p["from_selection"])
        applied = self.cal.add_many([{k: d[k] for k in ("item", "clip", "platform", "at")} for d in p["drafts"]])
        self.assertEqual(len(applied["ids"]), 2)
        nope = self.cal.plan(dict(text="hmm, whatever", start=MON, today=MON))
        self.assertEqual((nope["ok"], nope["reason"]), (False, "not_understood"))
        nxt = self.cal.plan(dict(text="下周每天中午12点发抖音", start=MON, today=MON, clips=sel))
        self.assertEqual(nxt["start"], "2026-10-12")
        self.assertEqual(nxt["drafts"][0]["at"], "2026-10-12T12:00")


class TitleAndPostedTest(Board):
    def test_title_edit_per_row_limit_and_reset(self):
        r = self.cal.add_many([dict(item=self.item, clip=A, platform=p, at="2026-10-07T20:00") for p in ("xiaohongshu", "youtube")])
        xhs, yt = r["ids"]
        p = next(x for x in self.posts() if x["id"] == xhs)
        original = p["title"]
        self.assertEqual(p["title_limit"], 20)
        self.assertFalse(p["title_custom"])
        self.cal.update(xhs, dict(title="再小的博主，也是博主"))
        self.cal.update(yt, dict(platform_title="Even a small creator is a creator"))
        ps = {x["id"]: x for x in self.posts()}
        self.assertEqual(ps[xhs]["title"], "再小的博主，也是博主")
        self.assertEqual(ps[xhs]["title_length"], 10)
        self.assertTrue(ps[yt]["title_custom"])
        self.assertEqual(ps[yt]["platform_title"], "Even a small creator is a creator")
        self.assertEqual(ps[yt]["title"], original)              # the card's title is untouched
        self.assertEqual(ps[yt]["title_limit"], 100)
        # 小红书 counts CJK as 1, latin as 0.5: 21 CJK characters are over, 30 latin letters are not
        self.cal.update(xhs, dict(platform_title="一" * 21))
        self.assertIn("title_too_long", [w["kind"] for w in next(x for x in self.posts() if x["id"] == xhs)["warnings"]])
        self.cal.update(xhs, dict(platform_title="a" * 30))
        self.assertNotIn("title_too_long", [w["kind"] for w in next(x for x in self.posts() if x["id"] == xhs)["warnings"]])
        with self.assertRaises(BadRequest):
            self.cal.update(xhs, dict(title="two\nlines"))
        with self.assertRaises(BadRequest):
            self.cal.update(xhs, dict(title="   "))
        self.cal.update(yt, dict(platform_title=None))
        p = next(x for x in self.posts() if x["id"] == yt)
        self.assertNotIn("platform_title", p)
        self.assertFalse(p["title_custom"])
        self.cal.update(xhs, dict(title=None))
        self.assertEqual(next(x for x in self.posts() if x["id"] == xhs)["title"], original)

    def test_posts_only_skips_the_queue_scan(self):
        self.cal.add_many([dict(item=self.item, clip=A, platform="xiaohongshu", at="2026-10-07T20:00")])
        full, lean = self.cal.list(), self.cal.list(queue=False)
        self.assertTrue(full["queue"])
        self.assertEqual(lean["queue"], [])
        self.assertEqual([p["id"] for p in lean["posts"]], [p["id"] for p in full["posts"]])

    def test_posted_keeps_url_and_via_and_unposting_clears_them(self):
        pid = self.cal.add_many([dict(item=self.item, clip=A, platform="xiaohongshu", at="2026-10-07T20:00")])["ids"][0]
        self.cal.update(pid, dict(state="posted", url="https://www.xiaohongshu.com/explore/abc", via="assisted"))
        p = next(x for x in self.posts() if x["id"] == pid)
        self.assertEqual((p["state"], p["url"], p["via"]), ("posted", "https://www.xiaohongshu.com/explore/abc", "assisted"))
        self.assertTrue(p["posted_at"])
        with self.assertRaises(BadRequest):
            self.cal.update(pid, dict(url="javascript:alert(1)"))
        self.cal.update(pid, dict(state="ready"))
        p = next(x for x in self.posts() if x["id"] == pid)
        self.assertNotIn("url", p)
        self.assertNotIn("posted_at", p)


class ShortenTest(Board):
    def test_rules_make_it_fit_and_keep_tags(self):
        long = ("Small creators are still creators. I posted for 8 months to 300 followers before one video changed "
                "how I think about side projects. Here is what I wish I knew on day one, and why consistency beat "
                "talent every single time. Start before you feel ready, post the rough version, keep going.\n\n#creator #sidehustle")
        r = self.cal.shorten(dict(text=long, platform="x"))
        self.assertEqual(r["provider"], "rules")                          # mock engine: no model
        self.assertLessEqual(r["length"], 280)
        self.assertEqual(r["limit"], 280)
        self.assertTrue(r["text"].startswith("Small creators are still creators."))
        self.assertIn("#creator", r["text"])
        zh = "再小的博主也是博主。" * 40
        out = shorten_rules("x", zh, 280)
        self.assertLessEqual(text_limit("x", out)[0], 280)
        self.assertEqual(self.cal.shorten(dict(text="short", platform="x"))["text"], "short")
        with self.assertRaises(BadRequest):
            self.cal.shorten(dict(text="", platform="x"))


class ParseTest(unittest.TestCase):
    def test_sentences(self):
        cases = {
            "每天晚上8点发一条小红书，周末不发": ("20:00", [0, 1, 2, 3, 4], ["xiaohongshu"], 1),
            "工作日中午12点发抖音和X": ("12:00", [0, 1, 2, 3, 4], ["douyin", "x"], 1),
            "每周一三五 19:30 小红书": ("19:30", [0, 2, 4], ["xiaohongshu"], 1),
            "每天两条抖音，早上9点": ("09:00", list(range(7)), ["douyin"], 2),
            "post on TikTok every day at 6pm, no weekends": ("18:00", [0, 1, 2, 3, 4], ["tiktok"], 1),
            "Instagram on Mondays and Thursdays at 7:15 pm": ("19:15", [0, 3], ["instagram"], 1),
            "tous les soirs à 20h sur Instagram, pas le week-end": ("20:00", [0, 1, 2, 3, 4], ["instagram"], 1),
            "YouTube Shorts weekends only at 10:00": ("10:00", [5, 6], ["youtube-shorts"], 1),
            "晚上八点半发视频号": ("20:30", None, ["wechat-channels"], 1),
        }
        for text, (tm, days, pfs, n) in cases.items():
            r = ST.parse(text)
            self.assertTrue(r["understood"], text)
            self.assertEqual((r["time"], r["days"], r["platforms"], r["per_day"]), (tm, days, pfs, n), text)
        self.assertFalse(ST.parse("hello there")["understood"])
        self.assertTrue(ST.parse("下周每天发")["next_week"])

    def test_post_text_and_limits(self):
        self.assertEqual(post_text(dict(title="标题", body="正文", tags=["a", "b"])), "标题\n\n正文\n\n#a #b")
        self.assertEqual(post_text(dict(title="标题", body="正文 #a", tags=["a"])), "标题\n\n正文 #a")
        self.assertEqual(post_text(None), "")
        n, lim = text_limit("x", "中文ab")
        self.assertEqual((n, lim), (6, 280))
        self.assertEqual(text_limit("xiaohongshu:vertical", "abc")[1], 1000)


if __name__ == "__main__":
    unittest.main()
