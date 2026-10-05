"""Checks for vstudio.hf (HyperFrames effect generators): well-formed css/html/js, every transition type
emits GSAP, overlays start hidden.

    python3 -m pytest tests/test_hf.py -q
"""
import html.parser
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import hf  # noqa: E402

CARDS = [dict(id="c1", img="assets/img/shot.png", w=1200, h=2400, s=3.0, e=9.5,
              scroll=[[3.0, 0], [6.0, 400]], hl=[[4.0, 120, 170, 0.6]], box=[5.0, 300, 420])]
LABELS = [{"s": 20.0, "e": 24.0, "n": 1, "t": "第一步"}, {"s": 24.0, "e": 30.0, "n": 2, "t": "第二步"}]


def snippets():
    return {
        "subtitles": hf.subtitles([{"s": 1.0, "e": 2.5, "t": "hello <em>world</em>"}]),
        "split_screen": hf.split_screen([[3.0, 9.5], [10.0, 14.0]], "inset(40px 520px 120px 500px round 28px)", x=-440),
        "punch_in": hf.punch_in([[2.0, 4.0]]),
        "punch_at": hf.punch_at("#ow", 12.0),
        "enter_zoom": hf.enter_zoom("#ow", 11.0),
        "screenshot_cards": hf.screenshot_cards(CARDS),
        "chips": hf.chips([[3.0, "Writing", 0], [4.0, "Video ★", 1]], 9.0),
        "badge": hf.badge("精选", 20.0, 10.0, 20.6),
        "tag": hf.tag("完整版", 20.0, 10.0, 20.8),
        "title_card": hf.title_card("成片精选", 20.0, 20.0, sub="节选"),
        "stamp": hf.stamp("好用", 30.0, 5.0, 32.0),
        "end_card": hf.end_card(35.0, 3.2, "kicker", "main", "sub"),
        "freeze_hold": hf.freeze_hold(15.0, 2.6, (380, -150), "prompt", "assets/img/p.png"),
        "framed_screen": hf.framed_screen("assets/video/m.mp4", 19.5, 10.5, 30.0, 1.1),
        "zoom_through": hf.zoom_through(19.5, 30.0),
        "step_labels": hf.step_labels(LABELS, 20.0, 10.0),
        "scene_transitions": hf.scene_transitions([hf.transition(t, "w-a", "w-b", 10.0 + k, 0.8)
                                                   for k, t in enumerate(hf.TRANSITIONS)]),
    }


def _strip_strings(js):
    return re.sub(r'"(?:\\.|[^"\\])*"|`(?:\\.|[^`\\])*`', '""', js)


def _balanced(s):
    pairs, stack = {")": "(", "]": "[", "}": "{"}, []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack


class _Tags(html.parser.HTMLParser):
    VOID = {"img", "br", "meta", "source", "input", "hr"}

    def __init__(self):
        super().__init__(); self.stack = []; self.ok = True

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack or self.stack.pop() != tag:
            self.ok = False


@pytest.mark.parametrize("name", list(snippets()))
def test_snippet_well_formed(name):
    s = snippets()[name]
    assert set(s) == {"css", "html", "js"}
    assert all(isinstance(v, str) for v in s.values())
    assert s["css"] or s["html"] or s["js"]
    if s["css"]:
        assert _balanced(s["css"]) and s["css"].endswith("\n")
    if s["js"]:
        assert _balanced(_strip_strings(s["js"])), name
        assert "tl." in s["js"]
    if s["html"]:
        p = _Tags(); p.feed(s["html"]); p.close()
        assert p.ok and not p.stack, name
        assert "../" not in s["html"], "asset paths must be project-root-relative"


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_js_parses_with_node(tmp_path):
    body = "".join(s["js"] for s in snippets().values())
    src = ("const gsap = { timeline: () => null };\nfunction f() {\n" + hf.prelude() + body + "}\n")
    p = tmp_path / "s.js"; p.write_text(src, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_transitions_emit_gsap_for_every_type():
    tr = [hf.transition(t, "w-a", "w-b", 10.0, 0.8) for t in hf.TRANSITIONS]
    js = hf.scene_transitions(tr)["js"]
    assert len(hf.TRANSITIONS) == 11
    for t in hf.TRANSITIONS:
        m = re.search(r'case "%s":(.*?)(?=case "|\n  }\n)' % t, js, re.S)
        assert m, t
        block = m.group(1) if t != "blur" else js.split('case "fade":')[1].split("case ")[0]
        assert re.search(r"tl\.(to|fromTo|set)\(", block), t
    assert js.count("immediateRender") == 1 and js.count("...IR") >= 10
    assert 'tl.set(w, ID, 0)' in js       # identity baseline at t=0
    with pytest.raises(ValueError):
        hf.transition("wipe", "a", "b", 0, 1)


def test_overlays_start_hidden():
    s = snippets()
    hidden = {"screenshot_cards": [".card", ".box"], "chips": [".chip"], "badge": ["#mbadge"], "tag": ["#mtag"],
              "title_card": ["#mtitle"], "stamp": ["#stamp"], "end_card": ["#end-k", "#end-m", "#end-s"],
              "freeze_hold": ["#pz-dim", "#pz-box", "#pz-label"], "framed_screen": ["#screen"],
              "step_labels": [".ml"], "enter_zoom": ["#ow"]}
    for name, sels in hidden.items():
        css = s[name]["css"]
        for sel in sels:
            m = re.search(re.escape(sel) + r" \{([^}]*)\}", css)
            assert m and "opacity: 0" in m.group(1), f"{name}: {sel} must start at opacity 0"


def test_js_expressions_are_referenced_not_inlined():
    s = hf.split_screen(hf.JS("D.SPLITS"), hf.JS("D.SPLIT"), hf.JS("D.SPLIT_X"))
    assert "D.SPLITS.forEach" in s["js"] and "clipPath: D.SPLIT," in s["js"]
    c = hf.screenshot_cards(CARDS, card_w=900, cards_js=hf.JS("D.CARDS"), card_w_js=hf.JS("D.CW"))
    assert "D.CARDS.forEach" in c["js"] and "D.CW / c.w" in c["js"] and "width: 900px" in c["css"]
    f = hf.freeze_hold(hf.JS("D.T"), hf.JS("D.H"), hf.JS("D.FLY"), clip=(1.0, 2.0))
    assert "D.T + D.H - 0.38" in f["js"] and "x: D.FLY[0]" in f["js"] and 'data-start="1.0"' in f["html"]


def test_one_fromto_per_target():
    """No snippet fromTo's the same literal selector twice (later moves must use to())."""
    for name, s in snippets().items():
        if name == "scene_transitions":
            continue  # per-transition targets are runtime ids; incoming tweens use immediateRender: false
        sels = re.findall(r'tl\.fromTo\("([^"]+)"', s["js"])
        assert len(sels) == len(set(sels)), name


def test_freeze_clips_resume_with_media_start():
    h = hf.freeze_clips("assets/video/body.mp4", "assets/img/freeze.jpg", 0.0, 13.0, 2.6, 30.0, 1.3)
    assert h.count("<video") == 2 and 'data-media-start="13.0"' in h and 'data-start="10.0"' in h
    assert 'data-start="12.6"' in h
