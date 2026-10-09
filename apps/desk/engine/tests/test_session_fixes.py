"""Found making a real promo in Reelfold 0.2.1 (fix/aigc-session-bugs):

  * an ``author`` checkpoint (promo-recut "Keep spans", "Cards, highlights, montage") read "Write your part" with one
    row "☑ 1 0": it now carries the label, the help, the file, a preview of its first lines, and is answered
    {done: true};
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import inbox as IB  # noqa: E402


class _Hist:
    def __init__(self, items=()):
        self.items = list(items)
        self.allowed = []

    def list(self):
        return dict(items=self.items)

    def allow_media(self, paths):
        self.allowed += list(paths)


class _Runner:
    def __init__(self):
        self.calls = []

    def sibling(self, mod):
        runner = self

        class S:
            def json(self, args, timeout=None, **kw):
                runner.calls.append((mod, args))
                return {}

            def text(self, args, timeout=None, **kw):
                return ""
        return S()


def _author_project():
    d = tempfile.mkdtemp()
    item_dir = os.path.join(d, "items", "AIGC")
    os.makedirs(item_dir)
    cfg = os.path.join(item_dir, "promo.config.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("\n".join(f"line {k}" for k in range(60)))
    cp_dir = os.path.join(d, "state", "checkpoints", "AIGC")
    os.makedirs(cp_dir)
    pay = dict(file=cfg, exists=True, template="/x/promo.config.example.yaml", doc="/x/WORKFLOW.md",
               format="promo-recut config (YAML)", options=[dict(file=cfg, sha="68ef")], digest="68ef",
               default=dict(done=True), previews=[dict(kind="text", path=cfg)], id="keep", kind="author",
               item="AIGC", labels=dict(zh="保留片段", en="Keep spans"),
               help=dict(zh="在 promo.config.yaml 写 cut.body", en="Write cut.body KEEP spans"))
    with open(os.path.join(cp_dir, "keep.json"), "w", encoding="utf-8") as f:
        json.dump(pay, f)
    # what vstudio.project.inbox lists for it (no template / doc there)
    entry = dict(project=d, id="keep", item="AIGC", kind="author", labels=pay["labels"], help=pay["help"],
                 options=pay["options"], previews=pay["previews"], default=pay["default"], file=cfg, exists=True,
                 content="line 0\n...", digest="68ef")
    return d, cfg, entry


class AuthorCheckpointInInbox(unittest.TestCase):
    def setUp(self):
        from vstudio.project import inbox as PI
        self.PI = PI
        self.d, self.cfg, self.entry = _author_project()
        self.hist = _Hist([dict(id="p1", dir=self.d, name="AIGC 评测", kind="project")])
        self.runner = _Runner()
        self.ib = IB.Inbox(tempfile.mkdtemp(), self.hist, self.runner, "real")

    def items(self):
        with mock.patch.object(self.PI, "inbox", return_value=dict(entries=[self.entry])):
            self.ib._forget_engine()
            return self.ib.list()["items"]

    def test_the_file_is_the_decision_not_an_option_row(self):
        (it,) = self.items()
        self.assertEqual(it["kind"], "author")
        self.assertEqual(it["options"], [], "never a bare '1 0' checkbox")
        a = it["author"]
        self.assertEqual((a["file"], a["exists"], a["preview_of"]), (self.cfg, True, "file"))
        self.assertEqual(a["help"]["en"], "Write cut.body KEEP spans")
        self.assertEqual(a["labels"]["en"], "Keep spans")
        self.assertEqual((a["template"], a["doc"]), ("/x/promo.config.example.yaml", "/x/WORKFLOW.md"))  # payload file
        self.assertEqual(a["preview"].splitlines()[:2], ["line 0", "line 1"])
        self.assertEqual(len(a["preview"].splitlines()), IB.PREVIEW_LINES)
        self.assertTrue(a["more"])

    def test_a_missing_file_previews_nothing_it_cannot_read(self):
        os.remove(self.cfg)
        self.entry["exists"] = False
        (it,) = self.items()
        self.assertFalse(it["author"]["exists"])
        self.assertIsNone(it["author"]["preview"])

    def test_continue_answers_done(self):
        self.assertEqual(IB.engine_answer("author", dict(done=True)), dict(done=True))
        self.assertEqual(IB.engine_answer("author", dict(approve=["0"], keep=[])), dict(done=True))  # an older desk
        self.assertEqual(IB.engine_answer("author", None), dict(done=True))
        (it,) = self.items()
        with mock.patch.object(self.PI, "inbox", return_value=dict(entries=[self.entry])), \
                mock.patch.object(self.ib, "resume"):
            self.ib._forget_engine()
            self.ib.answer([it["key"]], dict(done=True))
        args = self.runner.calls[-1][1]
        self.assertEqual(json.loads(args[args.index("--answer") + 1]), dict(done=True))

    def test_open_in_editor_opens_only_listed_files(self):
        (it,) = self.items()
        opened = []
        self.ib.opener = opened.append
        with mock.patch.object(self.PI, "inbox", return_value=dict(entries=[self.entry])):
            self.ib._forget_engine()
            self.assertEqual(self.ib.open_file(it["key"])["path"], self.cfg)
            from desk_engine.common import BadRequest
            with self.assertRaises(BadRequest):
                self.ib.open_file(it["key"], "doc")            # /x/WORKFLOW.md does not exist here
            with self.assertRaises(BadRequest):
                self.ib.open_file("0" * 16)
        self.assertEqual(opened, [self.cfg])


class RegistryStamp(unittest.TestCase):
    """All projects only showed a re-registered project after navigating away and back: the desk polls a stamp."""

    def test_the_stamp_moves_when_a_registry_changes(self):
        from desk_engine import history as HI
        from desk_engine.common import Registry
        data, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        with mock.patch.object(HI, "vstudio_home", return_value=home):
            h = HI.History(data, Registry(data))
            a = h.stamp()["stamp"]
            self.assertEqual(h.stamp()["stamp"], a)
            with open(os.path.join(home, "projects.json"), "w", encoding="utf-8") as f:
                json.dump([dict(dir="/x/p", name="p", recipe="promo-recut")], f)
            self.assertNotEqual(h.stamp()["stamp"], a)


if __name__ == "__main__":
    unittest.main()
