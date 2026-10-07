"""「这周的素材 → 一周的帖子」 (weekplan.py): drop footage -> intake plan -> every clip made -> laid out over the week
(calendar.plan with each platform's default rule + the account's usual time) -> one confirm (scheduleMany). Also the
per-platform default rules and the words that override them."""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402
from desk_engine import pilot  # noqa: E402
from desk_engine import schedule_text as ST  # noqa: E402
from desk_engine.calendar import Calendar  # noqa: E402
from desk_engine.common import BadRequest, Registry, read_json, write_json  # noqa: E402
from desk_engine.history import History  # noqa: E402
from desk_engine.intake import Intake  # noqa: E402
from desk_engine.weekplan import WeekPlans, _want  # noqa: E402

MON = "2026-10-05"   # a Monday; "today" is that Sunday before, so the whole week is free
SUN = "2026-10-04"


class Defaults(unittest.TestCase):
    def test_each_platform_has_a_rule_and_unknown_ones_fall_back(self):
        self.assertEqual(ST.default_rule("xiaohongshu:vertical"), dict(days=list(range(7)), time="20:00"))
        self.assertEqual(ST.default_rule("x")["days"], [0, 1, 2, 3, 4])
        self.assertEqual(ST.default_rule("nope"), dict(days=list(range(7)), time="19:00"))
        r = ST.default_rule("x")
        r["days"].append(6)
        self.assertEqual(ST.default_rule("x")["days"], [0, 1, 2, 3, 4])      # a copy

    def test_how_many_clips_a_week_needs(self):
        self.assertEqual(_want(None, ["xiaohongshu"]), 7)
        self.assertEqual(_want(None, ["x", "wechat-channels"]), 5)
        self.assertEqual(_want(ST.parse("weekdays 8pm, Xiaohongshu and Shorts"), []), 5)
        self.assertEqual(_want(ST.parse("每天两条小红书"), []), 14)


def fake_spawn(fail=False, review=False):
    """Test double for pilot.spawn: what ``vstudio.project run --auto all`` leaves in the project folder (every clip in
    final/ with its cover and post copy, status done), or a failed run's desk-pilot.* record."""
    calls = []

    def spawn(python, env, d, provider=None, bus=None, args=None):
        calls.append(args)
        if fail:
            pilot.record_mock(d, False, "plan-segments failed (exit 5): ffmpeg: moov atom not found")
            return {}
        n = int((read_json(os.path.join(d, ".vstudio", "work.json"), {}) or {}).get("count") or 1)
        fin = os.path.join(d, "final")
        os.makedirs(fin, exist_ok=True)
        md = ["# 发布文案", ""]
        for k in range(n):
            name = f"{k + 1:02d}_clip"
            out = os.path.join(fin, f"{name}.mp4")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=90x160:rate=10:duration=1",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", out], check=True)
            md += [f"## {name}.mp4", "", f"第 {k + 1} 条", "", "正文。", ""]
        with open(os.path.join(fin, "post.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(md))
        write_json(os.path.join(d, ".vstudio", "status.json"),
                   dict(status="waiting", stage="publish", progress=0.9, needs_you=True, heartbeat=time.time())
                   if review else dict(status="done", stage="完成", progress=1.0, heartbeat=time.time(),
                                       finished=time.time()))
        return {}
    spawn.calls = calls
    return spawn


class PlannerAsEngine:
    """The desk's rule planner standing in for vstudio.intake (no model in tests); says the engine is there."""

    def __init__(self, intake):
        self.i = intake

    def real(self):
        return True

    def __getattr__(self, k):
        return getattr(self.i, k)


class Runner:
    """The engine CLI as far as the week plan uses it: ``vstudio.project status --json`` (items waiting, and her
    review decision on each)."""
    python = "python3"
    env = {}

    def __init__(self):
        self.review, self.asked = None, []

    def sibling(self, module):
        runner = self

        class Cli:
            def json(self, args, timeout=None):
                runner.asked.append([module, *args])
                return dict(items=[dict(id="s01", state="waiting", waiting=["publish"], review=runner.review)])
        return Cli()


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg makes the test clips")
class Flow(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.env = mock.patch.dict(os.environ, {"VSTUDIO_HOME": os.path.join(self.root, "home"), "DESK_MOCK_STEP": "0.01",
                                                "DESK_HISTORY_WATCH": ""})
        self.env.start()
        data = os.path.join(self.root, "desk")
        self.h = History(data, Registry(data))
        self.o = OU.Outputs(data, self.h)
        self.cal = Calendar(data, self.h, self.o)
        # the planner + apply: the desk's rule planner stands in for vstudio.intake (no model in tests)
        self.intake = Intake(data, None, mode="mock")
        self.spawn = fake_spawn()
        self.w = WeekPlans(data, None, PlannerAsEngine(self.intake), self.cal, self.h, runner=Runner(), spawn=self.spawn)
        self.src = os.path.join(self.root, "this-week")
        os.makedirs(self.src)
        for n in ("mon.mp4", "tue.mp4"):
            with open(os.path.join(self.src, n), "wb") as f:
                f.write(b"\0" * 32)

    def tearDown(self):
        self.env.stop()

    def until(self, wid, states, timeout=40):
        end = time.time() + timeout
        while time.time() < end:
            r = self.w.get(wid)
            if r["state"] in states:
                return r
            time.sleep(0.1)
        self.fail(f"still {r['state']}")

    def start(self, text="", **kw):
        return self.w.start(dict(dict(inputs=[self.src], text=text, start=MON, today=SUN, platforms=["xiaohongshu", "douyin"],
                                      times={"xiaohongshu": "21:00"}, lang="en"), **kw))

    def test_drop_plan_make_preview_confirm(self):
        r = self.start()
        self.assertEqual(r["state"], "planning")
        self.assertEqual(r["words"], "Make this week's posts from these recordings")
        self.assertEqual(r["want"], 7)
        r = self.until(r["id"], ("ready",))
        self.assertEqual(r["plan"]["projects"][0]["items"]["count"], 7)          # a week's worth
        self.assertIn("xiaohongshu:vertical", r["plan"]["projects"][0]["params"]["platforms"])
        with self.assertRaises(BadRequest):
            self.w.confirm(r["id"])                                              # nothing to confirm yet
        r = self.w.run(r["id"])
        self.assertEqual(r["state"], "making")
        self.assertEqual(self.spawn.calls[0][1:5], ["-m", "vstudio.project", "run", "--dir"])
        self.assertEqual(self.spawn.calls[0][-3:], ["--auto", "all", "--json-events"])   # every clip, defaults
        r = self.until(r["id"], ("preview", "failed"))
        self.assertEqual(r["state"], "preview", r.get("error"))
        p = r["preview"]
        self.assertTrue(p["ok"])
        self.assertEqual(self.cal.list()["posts"], [])                           # a preview writes nothing
        self.assertEqual(p["clips"], 7)
        xhs = [d for d in p["drafts"] if d["platform"] == "xiaohongshu"]
        dy = [d for d in p["drafts"] if d["platform"] == "douyin"]
        self.assertEqual(len(xhs), 7)
        self.assertTrue(all(d["at"].endswith("T21:00") for d in xhs))           # the account's usual time
        self.assertTrue(all(d["at"].endswith("T18:00") for d in dy))            # douyin's default
        self.assertEqual(p["drafts"][0]["at"][:10], MON)
        self.assertEqual({x["platform"]: x["time"] for x in p["rules"]}, {"xiaohongshu": "21:00", "douyin": "18:00"})
        self.assertEqual(p["left"], 0)
        # still listed as going until she confirms
        self.assertEqual([x["id"] for x in self.w.active()["plans"]], [r["id"]])
        c = self.w.confirm(r["id"])
        self.assertEqual(c["state"], "scheduled")
        self.assertEqual(len(c["ids"]), 14)
        self.assertEqual(len(self.cal.list()["posts"]), 14)
        self.assertEqual(self.w.active()["plans"], [])
        with self.assertRaises(BadRequest):
            self.w.confirm(r["id"])                                              # once

    def test_her_words_set_platforms_days_and_time(self):
        r = self.start("weekdays 8pm, Xiaohongshu and Shorts")
        self.assertEqual(r["platforms"], ["youtube-shorts", "xiaohongshu"])
        self.assertEqual(r["want"], 5)
        r = self.until(r["id"], ("ready",))
        self.assertEqual(r["plan"]["projects"][0]["items"]["count"], 5)
        # a planner that left a platform out: the week still gets a version for each
        plan = self.intake.get(r["intake"])["plan"]
        plan["projects"][0]["params"]["platforms"] = ["youtube-shorts"]
        self.intake.jobs[r["intake"]]["plan"] = plan
        self.w.run(r["id"])
        applied = read_json(self.intake._path(r["intake"]))                       # the plan the projects came from
        self.assertEqual(applied["projects"][0]["params"]["platforms"], ["youtube-shorts", "xiaohongshu:vertical"])
        r = self.until(r["id"], ("preview", "failed"))
        p = r["preview"]
        self.assertEqual(len(p["drafts"]), 10)
        self.assertTrue(all(d["at"].endswith("T20:00") for d in p["drafts"]))
        days = sorted({d["at"][:10] for d in p["drafts"]})
        self.assertEqual(days, ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"])
        # said differently afterwards: the same clips, laid out again; nothing written
        r2 = self.w.reword(r["id"], "only Xiaohongshu, Mon Wed Fri at 7:30pm")
        self.assertTrue(r2["ok"])
        self.assertEqual({d["platform"] for d in r2["preview"]["drafts"]}, {"xiaohongshu"})
        self.assertEqual(len(r2["preview"]["drafts"]), 3)
        self.assertEqual(r2["preview"]["left"], 2)
        self.assertTrue(all(d["at"].endswith("T19:30") for d in r2["preview"]["drafts"]))
        self.assertFalse(self.w.reword(r["id"], "blah blah")["ok"])
        self.assertEqual(self.cal.list()["posts"], [])

    def test_saying_it_differently_before_making_replans_the_count(self):
        r = self.until(self.start()["id"], ("ready",))
        self.assertEqual(r["want"], 7)
        self.assertEqual([x["time"] for x in r["rules"]], ["21:00", "18:00"])   # usual time, then douyin's default
        r = self.w.reword(r["id"], "weekdays at 9am")
        self.assertEqual(r["state"], "planning")
        self.assertEqual(r["want"], 5)
        r = self.until(r["id"], ("ready",))
        self.assertEqual(r["plan"]["projects"][0]["items"]["count"], 5)
        self.assertEqual({x["time"] for x in r["rules"]}, {"09:00"})

    def test_clips_waiting_for_her_ok_park_the_week_until_approved(self):
        r = self.until(self.start()["id"], ("ready",))
        self.w._spawn = fake_spawn(review=True)
        self.w.run(r["id"])
        r = self.until(r["id"], ("review",))
        self.assertEqual(len(r["review"]), 1)
        self.assertEqual(self.cal.list()["posts"], [])
        self.assertEqual([x["id"] for x in self.w.active()["plans"]], [r["id"]])
        # not decided yet: nothing is resumed
        self.w._checked.clear()
        self.assertEqual(self.w.get(r["id"])["state"], "review")
        self.assertEqual(self.w.runner.asked[-1][:2], ["vstudio.project", "status"])
        # she approved everything in the review / Inbox: the run is started again and finishes -> the week
        self.w.runner.review = "approved"
        self.w._checked.clear()
        self.w._spawn = fake_spawn()
        r = self.w.get(r["id"])
        self.assertIn(r["state"], ("making", "preview"))
        self.assertEqual(self.w._spawn.calls[0][-3:], ["--auto", "all", "--json-events"])
        r = self.until(r["id"], ("preview",))
        self.assertTrue(r["preview"]["ok"])

    def test_without_the_engine_making_is_refused_in_words(self):
        r = self.until(self.start()["id"], ("ready",))
        self.w.runner = None
        with self.assertRaises(BadRequest) as e:
            self.w.run(r["id"])
        self.assertIn("needs the Reelfold engine", str(e.exception))
        self.assertEqual(self.w.get(r["id"])["state"], "ready")                  # nothing was half made

    def test_a_failed_run_is_failed_with_a_code_and_dismiss_hides_it(self):
        r = self.until(self.start()["id"], ("ready",))
        self.w._spawn = fake_spawn(fail=True)
        self.w.run(r["id"])
        r = self.until(r["id"], ("failed",))
        self.assertEqual(r["error_code"], "media")
        self.assertNotIn("/Users/", r.get("error") or "")
        self.assertEqual(len(self.w.active()["plans"]), 1)                       # failed stays until put away
        self.w.dismiss(r["id"])
        self.assertEqual(self.w.active()["plans"], [])

    def test_bad_input(self):
        with self.assertRaises(BadRequest):
            self.w.start(dict(inputs=[], start=MON))
        with self.assertRaises(BadRequest):
            self.start(times={"x": "25:00"})
        with self.assertRaises(BadRequest):
            self.w.get("../etc")


class ProjectClipFiles(unittest.TestCase):
    """A project made by today's engine keeps each clip's export manifest in export/exports/ (vstudio.batch stages):
    the clip has its files there, so it can be scheduled (the week's preview found no clips before)."""

    def test_export_manifest_in_exports(self):
        import sqlite3
        root = tempfile.mkdtemp()
        ex = os.path.join(root, "jobs", "s001", "export", "exports")
        os.makedirs(ex)
        with open(os.path.join(ex, "youtube-shorts-vertical.mp4"), "wb") as f:
            f.write(b"\0")
        write_json(os.path.join(ex, "manifest.json"), dict(exports=[dict(platform="youtube-shorts", orientation="vertical",
                                                                          file="youtube-shorts-vertical.mp4", w=1080, h=1920)]))
        con = sqlite3.connect(os.path.join(root, "batch.db"))
        con.execute("CREATE TABLE jobs (id TEXT, state TEXT, qc TEXT, review TEXT, ord INTEGER)")
        con.execute("INSERT INTO jobs VALUES ('s001', 'done', NULL, 'approved', 0)")
        con.commit()
        con.close()
        c = OU._batch_clips(root)[0]
        self.assertEqual([f["aspect"] for f in c["files"]], ["9:16"])
        self.assertEqual(c["state"], "done")


class CalendarDefaults(unittest.TestCase):
    """calendar.plan(platform_defaults): the existing one-sentence planner keeps its behaviour without the flag."""

    def test_without_the_flag_text_is_still_required(self):
        cal = Calendar(tempfile.mkdtemp(), mock.Mock(), mock.Mock())
        with self.assertRaises(BadRequest):
            cal.plan(dict(text="", start=MON, platforms=["xiaohongshu"]))


if __name__ == "__main__":
    unittest.main()
