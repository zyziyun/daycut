"""One title per clip: the AI-written post title is the clip's title (not the job id / file name), her own title in
the editor header wins and the publish cards follow it."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import outputs as OU  # noqa: E402


def _job(bdir, jid, params=None, post=None):
    j = os.path.join(bdir, "jobs", jid)
    ex = os.path.join(j, "export", "exports")
    os.makedirs(ex, exist_ok=True)
    with open(os.path.join(j, "job.json"), "w", encoding="utf-8") as f:
        json.dump(dict(id=jid, params=params or {}), f)
    with open(os.path.join(ex, f"{jid}.xhs.mp4"), "wb") as f:
        f.write(b"\0")
    e = dict(file=f"{jid}.xhs.mp4", platform="xiaohongshu", orientation="vertical", w=1080, h=1440, duration=31.0)
    if post is not None:
        with open(os.path.join(ex, f"{jid}.xhs.post.md"), "w", encoding="utf-8") as f:
            f.write(post)
        e["post"] = f"{jid}.xhs.post.md"
    with open(os.path.join(ex, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(dict(exports=[e]), f)


class ClipTitleOrder(unittest.TestCase):
    def test_fallback_order(self):
        self.assertEqual(OU.clip_title(dict(title="  一次录完，一周的内容 "), "Seg title", "lesson_part1"), "一次录完，一周的内容")
        self.assertEqual(OU.clip_title(dict(title=""), "Seg title", "lesson_part1"), "Seg title")
        self.assertEqual(OU.clip_title(None, None, "lesson_part1"), "lesson_part1")
        self.assertEqual(OU.clip_title(None, "   ", "lesson_part1"), "lesson_part1")

    def test_batch_clip_takes_the_post_title_not_the_job_id(self):
        bdir = tempfile.mkdtemp()
        # post.md as vstudio.publish.post_body writes it: title, blank, hook, body, tags
        _job(bdir, "lesson_part1", post="One recording, a week of posts\n\nRecord once.\n\nThen cut many.\n\n#creator\n")
        _job(bdir, "s002", params=dict(title="The second habit"))
        _job(bdir, "s003")
        by = {c["id"]: c for c in OU._batch_clips(bdir)}
        self.assertEqual(by["lesson_part1"]["title"], "One recording, a week of posts")
        self.assertNotIn("One recording", by["lesson_part1"]["post"]["body"])     # the title is not the body's line 1
        self.assertEqual(by["s002"]["title"], "The second habit")
        self.assertEqual(by["s003"]["title"], "s003")


class HerTitle(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.bdir = os.path.join(self.root, "batch")
        _job(self.bdir, "lesson_part1", post="One recording, a week of posts\n\nRecord once.\n")
        entry = dict(id="b1", kind="batch", dir=self.bdir)

        class H:
            def find(self, _id):
                return entry

            def allow_media(self, _paths):
                pass
        self.events = []

        class Bus:
            def publish(bus, kind, **kw):      # noqa: N805
                self.events.append(kind)
        self.o = OU.Outputs(os.path.join(self.root, "desk"), H(), bus=Bus())

    def clip(self):
        return self.o.clips("b1")["clips"][0]

    def test_rename_and_back_to_the_ai_title(self):
        self.assertEqual((self.clip()["title"], self.clip()["title_custom"]), ("One recording, a week of posts", False))
        r = self.o.set_title("b1", "lesson_part1", "  一条录像，一周的内容 ")
        self.assertEqual(r, dict(ok=True, title="一条录像，一周的内容", title_custom=True))
        self.assertEqual(self.clip()["title"], "一条录像，一周的内容")
        self.assertIn("output-edit", self.events)
        self.assertIn("calendar", self.events)
        # the same as the AI's title = not her own; None = back to the AI's
        self.assertFalse(self.o.set_title("b1", "lesson_part1", "One recording, a week of posts")["title_custom"])
        self.o.set_title("b1", "lesson_part1", "x")
        self.assertEqual(self.o.set_title("b1", "lesson_part1", None)["title"], "One recording, a week of posts")
        with self.assertRaises(OU.BadRequest):
            self.o.set_title("b1", "lesson_part1", "two\nlines")
        with self.assertRaises(OU.BadRequest):
            self.o.set_title("b1", "lesson_part1", "a" * 301)


if __name__ == "__main__":
    unittest.main()
