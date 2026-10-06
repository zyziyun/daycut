"""Static overlay QC: persistent UI chrome (an editor's block / selection menu, a toolbar) left open inside the
screen crop over whole items - the V02 field test's Notion menu that the popup scan reported "clean"
(_vertical.find_cards / static_overlays / scan_static_overlays, lfsplit.screen_checks, api._screen_scans)."""
import numpy as np
import pytest

import test_demo_grade as TDG

ffmpeg = TDG.ffmpeg
BG = 252


def _page(H=600, W=800, scroll=0, seed=5):
    """A light document page: rows of dark word blocks, shifted up by ``scroll`` px."""
    g = np.full((H, W), BG, np.uint8)
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(80):
        words, x = [], 40
        while x < W - 80:
            w = int(rng.integers(12, 46))
            words.append((x, w))
            x += w + 8
        rows.append(words)
    for k, words in enumerate(rows):
        y = 30 + 22 * k - scroll
        if y < 0 or y + 9 > H:
            continue
        for x, w in words:
            g[y:y + 9, x:x + w] = 45
    return g


def _menu(g, x0=470, y0=140, w=200, h=300, shadow=True, border=12):
    """A floating menu: page-coloured card, faint 1 px border, a soft drop shadow outside (left / right /
    bottom), a few item rows inside."""
    P = max(w, h) + 16                                       # drawn on a padded copy: may run off the crop
    H, W = g.shape
    g = np.pad(g, P, mode="edge")
    x0, y0 = x0 + P, y0 + P
    x1, y1 = x0 + w, y0 + h
    if shadow:
        for k in range(1, 9):
            v = BG - max(1, int(round(7 - 0.7 * k)))
            g[y0 + 6:y1 + k, x0 - k] = np.minimum(g[y0 + 6:y1 + k, x0 - k], v)
            g[y0 + 6:y1 + k, x1 - 1 + k] = np.minimum(g[y0 + 6:y1 + k, x1 - 1 + k], v)
            g[y1 - 1 + k, x0 - k:x1 + k] = np.minimum(g[y1 - 1 + k, x0 - k:x1 + k], v)
    g[y0:y1, x0:x1] = BG
    g[y0, x0:x1] = g[y1 - 1, x0:x1] = BG - border
    g[y0:y1, x0] = g[y0:y1, x1 - 1] = BG - border
    for r in range(6):
        yy = y0 + 22 + 44 * r
        g[yy:yy + 9, x0 + 18:x0 + 18 + 60 + 15 * (r % 3)] = 60
    return np.ascontiguousarray(g[P:P + H, P:P + W])


def _slide_box(g, x0=470, y0=140, w=200, h=300):
    """Page content with a crisp border and nothing outside it (an input field / table / callout box)."""
    g = g.copy()
    g[y0:y0 + h, x0:x0 + w] = BG
    g[y0:y0 + 2, x0:x0 + w] = g[y0 + h - 2:y0 + h, x0:x0 + w] = 210
    g[y0:y0 + h, x0:x0 + 2] = g[y0:y0 + h, x0 + w - 2:x0 + w] = 210
    for r in range(5):
        g[y0 + 30 + 50 * r:y0 + 39 + 50 * r, x0 + 20:x0 + 120] = 60
    return g


def _samples(frames, hz=2.0):
    return [dict(t=i / hz, key="screen", g=f, item=0) for i, f in enumerate(frames)]


def test_find_cards_sees_a_floating_menu_and_its_shadow():
    V = TDG._V()
    cards = V.find_cards(_menu(_page()))
    assert len(cards) == 1, cards
    c = cards[0]
    assert abs(c["box"][0] - 470) <= 3 and abs(c["box"][2] - 670) <= 3 and abs(c["box"][1] - 140) <= 3
    assert c["halo"] >= 1.5 and c["fill"] >= 0.7 and c["hug"] is None
    flat = V.find_cards(_slide_box(_page()))                 # a crisp page box: a card, but no drop shadow
    assert flat and all(x["halo"] < 1.0 for x in flat), flat
    assert V.find_cards(_page()) == []
    cut = V.find_cards(_menu(_page(), x0=690))               # cut by the crop's right edge
    assert cut and cut[0]["hug"] == "right" and cut[0]["halo"] >= 1.5, cut


def test_static_toolbar_over_changing_content_is_flagged():
    """The page scrolls under a menu that stays open for 5 s: flagged with its time and box, evidence shadow +
    pinned; the same menu WITHOUT a shadow is still flagged (pinned: the page moves, it does not)."""
    V = TDG._V()
    frames = [_page(scroll=0)] * 2 + [_menu(_page(scroll=14 * i)) for i in range(10)] + [_page(scroll=140)] * 2
    out = V.static_overlays(_samples(frames))
    assert len(out) == 1, out
    x = out[0]
    assert x["t"] == 1.0 and x["dur"] == 5.0 and "shadow" in x["evidence"] and "pinned" in x["evidence"]
    assert abs(x["box"][0] - 470) <= 3 and 438 <= x["box"][3] <= 450       # the bottom may take the shadow in
    flat = [_page(scroll=0)] * 2 + [_menu(_page(scroll=14 * i), shadow=False) for i in range(10)]
    got = V.static_overlays(_samples(flat))
    assert len(got) == 1 and "pinned" in got[0]["evidence"] and "shadow" not in got[0]["evidence"], got


def test_menu_open_over_an_unchanged_page_is_flagged_even_across_cuts():
    """A menu already open when an item starts and still open when it ends (the Notion block menu of ep02 /
    ep06): no appear / vanish inside the item, the page static - the drop shadow alone flags it; one that comes
    and stays over an unchanged page also carries ``appeared``."""
    V = TDG._V()
    page = _page()
    held = [_menu(page)] * 8
    out = V.static_overlays(_samples(held))
    assert len(out) == 1 and out[0]["evidence"] == ["shadow"] and out[0]["dur"] == 4.0, out
    came = [page] * 3 + [_menu(page)] * 6
    got = V.static_overlays(_samples(came))
    assert len(got) == 1 and got[0]["t"] == 1.5 and "appeared" in got[0]["evidence"], got


def test_static_full_slide_is_not_flagged():
    """A static slide / page with a bordered box that is always there (no shadow, nothing around it changes)
    is page content: nothing to report; neither is a plain static page, nor a page that only scrolls."""
    V = TDG._V()
    slide = _slide_box(_page())
    assert V.static_overlays(_samples([slide] * 12)) == []
    assert V.static_overlays(_samples([_page()] * 12)) == []
    assert V.static_overlays(_samples([_page(scroll=10 * i) for i in range(12)])) == []
    short = [_page()] * 3 + [_menu(_page())] + [_page()] * 3          # 0.5 s: the popup scan's business
    assert V.static_overlays(_samples(short)) == []


def test_transient_popup_is_still_the_popup_scans_and_not_reported_twice():
    """A menu that opens and closes inside one item stays with the old path (detect_popups finds it); when
    both scans see the same box at the same time, QC warns once (screen-popup-visible)."""
    V = TDG._V()
    page = _page()
    frames = [page] * 4 + [_menu(page)] * 6 + [page] * 4
    st = np.stack([f[::2, ::2] for f in frames]).astype(np.int16)
    pops = V.detect_popups(st, dict(V.SCREEN_DEFAULTS, popup_min_frac=0.01), 2.0)
    assert len(pops) == 1 and pops[0]["j0"] == 4 and pops[0]["j1"] == 10, pops
    from vstudio.batch import lfsplit as LS
    vis = [dict(t=2.0, dur=3.0, cover=0.12, box=[470, 140, 670, 440])]
    sto = [dict(t=2.0, dur=3.0, box=[468, 139, 671, 441], cover=0.12, evidence=["shadow"], hug=None, items=[0])]
    plan = dict(items=[], visible_popups=vis, static_overlays=sto)
    sc = LS.screen_summary(plan, [], 24)
    out = LS.screen_checks({}, {}, dict(privacy=dict(plans={"1080x1920": dict(screen=sc)})))
    by = {c["name"]: c for c in out}
    assert not by["screen-popup-visible"]["ok"] and by["screen-overlay-static"]["ok"]


def test_qc_warns_on_static_overlays_with_times_and_boxes():
    from vstudio.batch import lfsplit as LS
    from vstudio.batch import api
    sto = [dict(t=18.5, dur=5.5, box=[466, 681, 659, 1028], cover=0.075, evidence=["shadow"], hug=None, items=[5]),
           dict(t=40.0, dur=0.5, box=[1, 2, 3, 4], cover=0.01, evidence=["shadow"], hug=None, items=[9]),
           dict(t=26.0, dur=8.0, box=[913, 685, 1080, 1032], cover=0.06, evidence=["shadow", "appeared"],
                hug="right", items=[2])]
    sc = LS.screen_summary(dict(items=[], visible_popups=[], static_overlays=sto), [], 24)
    assert len(sc["static"]) == 3
    ex = dict(privacy=dict(plans={"1080x1920": dict(screen=sc)}))
    out = LS.screen_checks({}, {}, ex)
    chk = [c for c in out if c["name"] == "screen-overlay-static"][0]
    assert not chk["ok"] and chk["severity"] == "warn" and chk["target"] == "1080x1920"
    assert "18.5-24.0s at [466, 681, 659, 1028]" in chk["reason"] and "40.0" not in chk["reason"]
    assert "cut by the right edge" in chk["reason"]
    assert [v["t"] for v in chk["value"]] == [18.5, 26.0] and chk["value"][0]["evidence"] == ["shadow"]
    quiet = LS.screen_checks({}, {"qc": {"overlay_s": 10}}, ex)
    assert [c for c in quiet if c["name"] == "screen-overlay-static"][0]["ok"]
    old = LS.screen_summary(dict(items=[], visible_popups=[]), [], 24)       # a master from before the scan
    assert old["static"] is None
    assert not [c for c in LS.screen_checks({}, {}, dict(privacy=dict(plans={"x": dict(screen=old)})))
                if c["name"] == "screen-overlay-static"]
    js = api._screen_scans(ex)
    assert js["1080x1920"]["static_overlays"][0]["box"] == [466, 681, 659, 1028]
    assert js["1080x1920"]["visible_popups"] == [] and api._screen_scans({}) == {}


@ffmpeg
def test_output_scan_finds_a_menu_left_open_in_a_rendered_master(tmp_path):
    """End to end on an encoded vertical video: the screen box shows a page; a menu is open from 1 s to the end
    of the item and a dark notes panel (an overlay rect) shows from 3 s. The static scan reports the menu with
    output times + canvas box, never the panel; the clean render reports nothing."""
    import cv2
    V = TDG._V()
    from vstudio import platform as PF
    L = V.layout([PF.parse_targets(["xiaohongshu:vertical"])[0]])
    bx = V.boxes(L, "split", "title")["screen"]
    W, H = L["W"], L["H"]
    fps, n = 24, 24 * 5
    bw, bh = bx[2] - bx[0], bx[3] - bx[1]
    page = _page(bh, bw)
    panel = [W - 420, bx[1] + 16, W - 40, bx[1] + 260]

    def render(menu):
        out = []
        for i in range(n):
            g = _menu(page, x0=300, y0=300) if menu and i / fps >= 1.0 else page
            f = np.zeros((H, W, 3), np.uint8)
            f[bx[1]:bx[3], bx[0]:bx[2]] = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
            if i / fps >= 3.0:
                f[panel[1]:panel[3], panel[0]:panel[2]] = 30
            out.append(f)
        return TDG._video(tmp_path, out, fps, f"s{int(menu)}.mp4")
    segs = [(0.0, n / fps, list(bx), 0)]
    ov = [dict(a=3.0, b=5.0, rect=panel)]
    found = V.scan_static_overlays(render(True), segs, ov)
    assert len(found) == 1, found
    x = found[0]
    assert abs(x["t"] - 1.0) <= 0.5 and x["dur"] >= 3.0 and "shadow" in x["evidence"]
    assert abs(x["box"][0] - (bx[0] + 300)) <= 6 and abs(x["box"][1] - (bx[1] + 300)) <= 6
    assert V.scan_static_overlays(render(False), segs, ov) == []


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
