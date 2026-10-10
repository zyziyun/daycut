"""Found making a real promo in Reelfold 0.2.1 (fix/aigc-session-bugs):

  * an ``author`` checkpoint (promo-recut "Keep spans", "Cards, highlights, montage") read "Write your part" with one
    row "☑ 1 0", then (0.2.3) showed the raw promo.config.yaml - even the SYNTHETIC example it was seeded with. It now
    carries the engine's draft in plain words (``review``: the transcript with kept / cut parts), never the file's
    text; a file that is still the template is "template" (nothing drafted: "Draft it for me"); it is answered with
    the default or {done, spans}; "ask in plain words" redrafts it in the background;
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


REVIEW = dict(kind="keep-spans", by="ai", provider="claude-code",
              summary=dict(code="draft.keep", params=dict(kept=580.0, total=764.0, cuts=["没讲完的开场"], n=1)),
              segments=[dict(i=1, t=0.4, te=2.0, text="大家好嗯。", keep=False, label="没讲完的开场"),
                        dict(i=2, t=2.4, te=6.0, text="今天讲可灵。", keep=True, label=None)], kept_s=580.0, total_s=764.0)


def _author_project(drafted=True):
    d = tempfile.mkdtemp()
    item_dir = os.path.join(d, "items", "AIGC")
    os.makedirs(item_dir)
    cfg = os.path.join(item_dir, "promo.config.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("# promo-recut config - drafted by Reelfold\ncut:\n  body: [[2.35, 6.05]]\n" if drafted else
                "# promo-recut project config (SYNTHETIC example: invented content, plausible numbers).\ncut:\n"
                "  body:\n    - [1.0, 6.2]\n")
    cp_dir = os.path.join(d, "state", "checkpoints", "AIGC")
    os.makedirs(cp_dir)
    pay = dict(file=cfg, exists=drafted, template="/x/promo.config.example.yaml", doc="/x/WORKFLOW.md",
               format="promo-recut config (YAML)", options=[dict(file=cfg, sha="68ef")], digest="68ef",
               default=dict(done=True) if drafted else None, previews=[dict(kind="text", path=cfg)], id="keep",
               kind="author", item="AIGC", recipe="promo-recut", labels=dict(zh="确认保留内容", en="Check what's kept"),
               help=dict(zh="AI 按你的要求剪好了", en="The AI cut your recording"))
    if drafted:
        pay.update(draft_state="drafted", draft_by="ai", review=REVIEW)
    else:                                        # a 0.2.3 payload: no draft fields, the SYNTHETIC example as the file
        with open(cfg, encoding="utf-8") as f:
            pay["content"] = f.read()
    with open(os.path.join(cp_dir, "keep.json"), "w", encoding="utf-8") as f:
        json.dump(pay, f)
    # what vstudio.project.inbox lists for it (no template / doc there)
    entry = dict(project=d, id="keep", item="AIGC", kind="author", labels=pay["labels"], help=pay["help"],
                 options=pay["options"], previews=pay["previews"], default=pay["default"], file=cfg,
                 exists=drafted, content=pay.get("content"), digest="68ef")
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

    def test_the_draft_in_plain_words_not_the_file(self):
        (it,) = self.items()
        self.assertEqual(it["kind"], "author")
        self.assertEqual(it["options"], [], "never a bare '1 0' checkbox")
        self.assertEqual(it["previews"], [], "the file is never previewed")
        a = it["author"]
        self.assertEqual((a["state"], a["recipe"], a["checkpoint"], a["can_draft"]), ("drafted", "promo-recut", "keep",
                                                                                     True))
        self.assertEqual(a["review"], REVIEW)
        self.assertTrue(a["exists"])
        self.assertEqual(a["file"], self.cfg)                 # only for "Advanced: open the file"
        for gone in ("preview", "template", "help", "format"):
            self.assertNotIn(gone, a)
        blob = json.dumps({k: v for k, v in it.items() if k != "engine"}, ensure_ascii=False)
        for raw in ("cut:", "body:", "SYNTHETIC", "KEEP spans"):
            self.assertNotIn(raw, blob)

    def test_an_older_payload_still_holding_the_example_is_not_a_draft(self):
        """Her 0.2.3 project: the item was seeded with the SYNTHETIC example and the Inbox showed it as YAML."""
        self.d, self.cfg, self.entry = _author_project(drafted=False)
        self.hist.items = [dict(id="p1", dir=self.d, name="AIGC 评测", kind="project")]
        (it,) = self.items()
        a = it["author"]
        self.assertEqual((a["state"], a["review"], a["exists"], a["can_draft"]), ("template", None, False, True))
        blob = json.dumps({k: v for k, v in it.items() if k != "engine"}, ensure_ascii=False)
        self.assertNotIn("SYNTHETIC", blob)
        self.assertNotIn("cut:", blob)

    def test_accept_and_her_selection(self):
        self.assertEqual(IB.engine_answer("author", dict(done=True)), dict(done=True))
        self.assertEqual(IB.engine_answer("author", dict(approve=["0"], keep=[])), dict(done=True))  # an older desk
        self.assertEqual(IB.engine_answer("author", None), dict(done=True))
        self.assertEqual(IB.engine_answer("author", dict(done=True, spans=[[2.35, 6.05]])),
                         dict(done=True, spans=[[2.35, 6.05]]))
        (it,) = self.items()
        with mock.patch.object(self.PI, "inbox", return_value=dict(entries=[self.entry])), \
                mock.patch.object(self.ib, "resume"):
            self.ib._forget_engine()
            self.ib.answer([it["key"]], dict(done=True, spans=[[2.35, 6.05]]))
            self.ib._forget_engine()
            self.ib.answer([it["key"]])                       # "Looks good": the draft as it is
        a1 = self.runner.calls[-2][1]
        self.assertEqual(json.loads(a1[a1.index("--answer") + 1]), dict(done=True, spans=[[2.35, 6.05]]))
        a2 = self.runner.calls[-1][1]
        self.assertEqual(json.loads(a2[a2.index("--answer") + 1]), dict(done=True))

    def test_ask_in_plain_words_redrafts_in_the_background(self):
        (it,) = self.items()
        seen, done = [], __import__("threading").Event()

        def fake_redraft(project, cp, item, instruction=None, complete=None):
            seen.append((project.dir, cp, item, instruction))
            done.set()
            return dict(ok=True)
        with mock.patch.object(self.PI, "inbox", return_value=dict(entries=[self.entry])), \
                mock.patch("vstudio.project.drafts.redraft", fake_redraft), \
                mock.patch("vstudio.project.core.Project", lambda d: type("P", (), dict(dir=d))()):
            self.ib._forget_engine()
            r = self.ib.redraft(it["key"], "  Hedra 那段留着 ")
            self.assertEqual(r, dict(ok=True, drafting=True))
            self.assertTrue(done.wait(5))
        self.assertEqual(seen, [(os.path.realpath(self.d), "keep", "AIGC", "Hedra 那段留着")])

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
