"""Captions stay inside the platform's caption box at every shape: an over-long cue (a whole spoken sentence) is never
drawn as max_lines lines wider than the frame (3:4 cropped "…ut it into many short clips. Then you post tl…")."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio import draw, export as X, platform as P  # noqa: E402
from vstudio.subs import Cue  # noqa: E402

LONG = "You cut it into many short clips. Then you post them on every platform, in the right shape."


def test_fallback_wraps_inside_the_box():
    for name in ("xiaohongshu:vertical", "tiktok:vertical", "youtube-shorts:vertical"):
        p = P.profile(name, use_persona=False)
        x0, _y0, x1, _y1 = P.caption_box(p)
        r = P.fit_text_size(p, LONG)
        f = draw.load_font("cjk-bold", r["size"])
        assert all(draw.text_width(ln, f) <= x1 - x0 for ln in r["lines"]), (name, r)


def test_long_cues_are_shown_in_turns():
    p = P.profile("xiaohongshu:vertical", use_persona=False)
    cs = X.fit_cues(p, [Cue(10.0, 16.0, LONG), Cue(16.0, 18.0, "Short one.")])
    assert len(cs) >= 3 and cs[-1].text == "Short one."
    assert all(P.fit_text_size(p, c.text)["fits"] for c in cs)
    assert cs[0].start == 10.0 and abs(cs[-2].end - 16.0) < 1e-6
    assert all(a.end <= b.start + 1e-6 for a, b in zip(cs, cs[1:]))
    assert " ".join(c.text for c in cs[:-1]) == LONG


def test_keywords_light_up_whole_words_only():
    assert draw.runs("Don't stop the recording.", ["to", "it", "recording"]) == \
        [("Don't stop the ", False), ("recording", True), (".", False)]          # never "s【to】p"
    assert draw.runs("The editor keeps it", ["editor"]) == [("The ", False), ("editor", True), (" keeps it", False)]
    assert draw.runs("我们用前端组件库", ["组件"]) == [("我们用前端", False), ("组件", True), ("库", False)]
