"""Home / Inbox / transcript editing (ux-core): plain-language inbox options (no file paths or raw numbers), quickest
first + done today, and the desk implementation of transcript cuts (cut by word index, stale words, pause tightening,
one Apply = one step with effect / caption re-timing, preview-edl parity with the applied edit, filler / pause marks)."""
import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _isolate  # noqa: E402,F401

from desk_engine import inbox as IB  # noqa: E402
from desk_engine import inbox_labels as L  # noqa: E402
from desk_engine import outputs as OU  # noqa: E402
from desk_engine import works as WK  # noqa: E402
from desk_engine.common import Registry  # noqa: E402
from desk_engine.history import History  # noqa: E402
from test_v04 import Fixture, asr  # noqa: E402

PICKS_FULL = """# PICKS: 多元副业复盘_final.mp4 → 4 条小红书切片

| # | Source span | Len | Title (小红书 units) | Why | Opening line (hook) |
|---|---|---|---|---|---|
| A 换圈子 | 7:30.6 – 8:55.5 | 1:24 | 同一个行业待越久，思路越窄 (13) | x | y |
| B 自媒体 | 8:56.3 – 10:10.8 | 1:13 | 再小的博主，也是博主 (10) | x | y |
| C 底气 | 5:01.4–5:05.3 + 5:10.9–5:16.3 + 10:11.4 – 10:53 | 0:50 | 副业给我的不是钱，是底气 (12) | x | y |
| D 反哺主业 | 5:19.3 – 6:03.2 | 0:43 | 带学员求职，反而帮我面试不挂 (14) | x | y |

## Edits inside the spans (creator should confirm)
- **A** starts at 你在副业当中, skipping 「这也是挺丰富人生的一个事情」, which only makes sense after the previous segment.
- **B** drops 「还有一个点就是」 before 我做自媒体.
- **C** drops the hedge 「或者说也可能是因为程序员这个工作确实在近十年还是OK的」 (5:05.6–5:10.9) and 「另外的话就是」 before 10:11.
- **D** starts at 年初面试 instead of 「比如说做career coach，我能够了解到非常多的东西」. That gives a stronger opening, but the clip is 43 s, 2 s under the 45 s floor. To restore the softer opener, change the D start to 316.72 in `work/make_src.py`.
- Skipped: 摄影 「熟练工 vs 摄影师」 (3:00–3:21).
"""


def _no_engine_noise(s):
    """A label the creator reads: no file paths, code spans or raw decimals like 316.72."""
    return not re.search(r"\.py\b|`|/|\b\d+\.\d{2,}\b", s or "")


class LabelsTest(unittest.TestCase):
    def test_real_picks_become_plain_choices(self):
        spans = L.picks_spans(PICKS_FULL)
        self.assertEqual(spans["C"], [[301.4, 305.3], [310.9, 316.3], [611.4, 653.0]])
        conf = WK.parse_picks(PICKS_FULL)["confirm"]
        self.assertEqual(len(conf), 4)
        words = {"B": [dict(w="我做", t=0.0, te=0.4), dict(w="自媒体", t=0.4, te=1.0)]}
        opts = [L.humanize(c, spans, None, lambda k: words.get(k, []), "/src.mp4", i) for i, c in enumerate(conf)]
        kinds = [o["kind"] for o in opts]
        self.assertEqual(kinds, ["aside", "filler", "hedge", "opener"])
        for o in opts:
            for m in (o["label"], o.get("detail")) + tuple(c["label"] for c in o.get("choices") or []):
                if m:
                    self.assertTrue(_no_engine_noise(m["message"]), m)
                    self.assertTrue(m["code"].startswith("inbox."))
                    self.assertTrue(m["message_zh"])
        d = opts[3]
        self.assertEqual([c["id"] for c in d["choices"]], ["softer", "stronger"])
        self.assertTrue(d["choices"][0]["recommended"])                  # 43 s is under the 45 s floor
        self.assertEqual((d["choices"][0]["secs"], d["choices"][1]["secs"]), (45.6, 43.0))
        self.assertEqual(d["choice"], "softer")
        self.assertEqual(d["detail"]["params"], dict(secs=43.0, floor=45.0))
        self.assertEqual(d["at"], 0.0)
        self.assertEqual(d["before"], dict(file="/src.mp4", at=316.72))
        c = opts[2]
        self.assertEqual(c["at"], 3.9)                                   # the join of the first two spans
        self.assertLess(c["secs"], -5.0)
        self.assertEqual(opts[1]["at"], 0.0)                             # found 我做自媒体 in the clip's words
        self.assertEqual(opts[0]["quote"], "这也是挺丰富人生的一个事情")

    def test_fallback_label_strips_paths_and_numbers(self):
        o = L.humanize(dict(clip="E", text="Raise the gain to 3.25 dB in `work/mix.py` (1:00–1:02)."), {}, idx=0)
        self.assertEqual(o["kind"], "check")
        self.assertTrue(_no_engine_noise(o["detail"]["message"]), o["detail"])

    def test_spend_params(self):
        p = L.spend_params(dict(aggregate=dict(cost_cny=18.0), estimate=dict(shots=12)))
        self.assertEqual(p, dict(amount=18.0, currency="CNY", n=12))


class InboxListTest(unittest.TestCase):
    def test_options_media_order_and_done_today(self):
        root = tempfile.mkdtemp()
        watch = os.path.join(root, "demos")
        d = os.path.join(watch, "fuye")
        os.makedirs(os.path.join(d, "final"))
        for n in ("A_换圈子.mp4", "B_自媒体.mp4", "C_底气.mp4", "D_反哺主业.mp4"):
            open(os.path.join(d, "final", n), "wb").close()
        with open(os.path.join(d, "final", "B_自媒体.mp4.asr.json"), "w", encoding="utf-8") as f:
            json.dump(asr([("嗯", 0.0, 0.3), ("我做", 0.5, 0.9), ("自媒体", 0.9, 1.5)]), f)
        with open(os.path.join(d, "PICKS.md"), "w", encoding="utf-8") as f:
            f.write(PICKS_FULL)
        with mock.patch.dict(os.environ, {"DESK_HISTORY_WATCH": watch, "VSTUDIO_HOME": os.path.join(root, "home")}):
            data = os.path.join(root, "desk")
            h = History(data, Registry(data))
            ib = IB.Inbox(data, h)
            doc = ib.list()
            self.assertEqual(doc["done_today"], 0)
            it = doc["items"][0]
            self.assertEqual(it["kind"], "confirm")
            self.assertEqual(len(it["options"]), 4)
            b = it["options"][1]
            self.assertEqual((b["clip_id"], b["at"]), ("B_自媒体", 0.5))
            self.assertTrue(b["file"].endswith("B_自媒体.mp4"))
            self.assertIn(os.path.dirname(b["file"]), h._media)            # playable through the media protocol
            ib.answer([it["key"]], dict(approve=["o0", "o1"], keep=["o2"], choices=dict(o3="softer")))
            self.assertEqual(ib.list()["done_today"], 1)


class TranscriptCutTest(Fixture):
    """A_换圈子 words: 你在 0-.5, 副业 .5-1, 当中 1-1.4, (pause 1 s), 其实 2.4-2.8, 底气 2.8-3.3."""

    def test_show_has_sig_marks_and_caps(self):
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual(doc["words_sig"], OU.words_sig(doc["words"]))
        self.assertEqual([(m["kind"], m["i0"], m["i1"]) for m in doc["marks"]], [("pause", 2, 3)])
        self.assertTrue(doc["caps"]["cut_words"])
        self.assertEqual(doc["caps"]["cut_strategy"], "hard")

    def test_cut_by_words_one_step_and_undo(self):
        doc = self.o.show(self.item, "A_换圈子")
        sig = doc["words_sig"]
        fx = self.o.edit(self.item, "A_换圈子", [dict(op="effect_add", effect="pop-words", start=0.6, end=0.95,
                                                    params=dict(text="副业"))])["values"][0]["id"]
        r = self.o.edit(self.item, "A_换圈子", [dict(op="cut", words=[1, 1], sig=sig, why="transcript"),
                                               dict(op="cut", gap=2, keep=0.25, why="pause")], by="you", note="transcript")
        st = r["step"]
        self.assertEqual(st["by"], "you")
        self.assertEqual(st["note"], "transcript")
        self.assertEqual([d["code"] for d in st["describe"]], ["op-cut", "op-cut", "op-effect-remove"])
        self.assertEqual(st["describe"][0]["params"]["said"], "副业")
        self.assertEqual(st["retimed"]["effects"]["removed"][0]["id"], fx)
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual([(c["start"], c["end"]) for c in doc["cuts"]], [(0.51, 0.99), (1.525, 2.275)])
        self.assertEqual(doc["effects"], [])
        self.assertEqual(doc["steps"][-1]["retimed"]["targets"], ["primary"])
        self.o.undo(self.item, "A_换圈子")                                   # one Apply = one step
        doc = self.o.show(self.item, "A_换圈子")
        self.assertEqual((doc["cuts"], len(doc["effects"])), ([], 1))

    def test_stale_words_and_bad_indices(self):
        for op, code in ((dict(op="cut", words=[0, 0], sig="0123456789", why="transcript"), "stale-words"),
                         (dict(op="cut", words=[3, 9], why="transcript"), "bad-param"),
                         (dict(op="cut", gap=0, why="pause"), "bad-param"),
                         (dict(op="cut", words=[0, 4], why="transcript"), "too-short")):
            with self.assertRaises(OU.EngineMessage) as cm:
                self.o.edit(self.item, "A_换圈子", [op])
            self.assertEqual(cm.exception.doc["code"], code, op)

    def test_preview_edl_matches_the_applied_edit(self):
        sig = self.o.show(self.item, "A_换圈子")["words_sig"]
        ops = [dict(op="cut", words=[1, 1], sig=sig, why="transcript"), dict(op="cut", gap=2, why="pause"),
               dict(op="cut", words=[0, 9], sig=sig, why="transcript")]
        pv = self.o.preview_edl(self.item, "A_换圈子", ops)
        self.assertEqual(len(pv["dropped"]), 1)
        self.assertEqual(pv["dropped"][0]["index"], 2)
        self.o.edit(self.item, "A_换圈子", ops[:2])
        doc = self.o.show(self.item, "A_换圈子")
        st = dict(OU._new_state(), cuts=[dict(start=c["start"], end=c["end"]) for c in doc["cuts"]])
        self.assertEqual(pv["keep"], OU.segments(st, doc["duration"]))
        self.assertAlmostEqual(pv["duration"], sum(b - a for a, b in pv["keep"]), places=3)
        self.assertEqual(self.o.preview_edl(self.item, "A_换圈子", [])["keep"], pv["keep"])

    def test_marks_fillers_and_low_confidence(self):
        W = [dict(w="嗯", t=0.0, te=0.3), dict(w="那个", t=0.35, te=0.7, p=0.3), dict(w="好", t=1.6, te=1.9)]
        m = OU.marks(W)
        self.assertEqual([(x["kind"], x["i0"]) for x in m], [("filler", 0), ("filler", 1), ("lowconf", 1), ("pause", 1)])
        self.assertAlmostEqual(m[3]["save_s"], 0.65, delta=0.06)


if __name__ == "__main__":
    unittest.main()
