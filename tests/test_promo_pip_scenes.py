"""promo-recut PiP / scene cards / hooks / montage robustness / privacy crop / speeds (unit level).

    python3 -m pytest tests/test_promo_pip_scenes.py -q
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

import numpy as np
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
S = ROOT / "workflows" / "promo-recut" / "scripts"
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(S))

from vstudio import hf  # noqa: E402
from vstudio import platform as PF  # noqa: E402
from vstudio.cut import TimeMap  # noqa: E402
import build_promo as BP  # noqa: E402
import common  # noqa: E402
import screen_crop as SC  # noqa: E402
import tight_cut as TC  # noqa: E402


# ---------------------------------------------------------------- window validation
def test_pip_windows_must_not_overlap_cards_or_each_other():
    cards = [{"start": 10.0, "end": 20.0}]
    assert BP.validate_windows([{"start": 21.0, "end": 30.0}], cards) == []
    with pytest.raises(ValueError, match=r"overlaps card\[0\]"):
        BP.validate_windows([{"start": 19.0, "end": 25.0}], cards)
    with pytest.raises(ValueError, match=r"overlaps pip\[1\]"):
        BP.validate_windows([{"start": 30.0, "end": 40.0}, {"start": 39.0, "end": 45.0}])
    with pytest.raises(ValueError, match="split"):
        BP.validate_windows([{"start": 30.0, "end": 40.0}], splits=[[35, 50]])
    with pytest.raises(ValueError, match="freeze hold"):
        BP.validate_windows([{"start": 30.0, "end": 40.0}], hold_at=33.0)
    with pytest.raises(ValueError, match="shorter than 1 s"):
        BP.validate_windows([{"start": 30.0, "end": 30.5}])
    with pytest.raises(ValueError, match="outside the body"):
        BP.validate_windows([{"start": 90.0, "end": 95.0}], body=[(0, 60)])
    w = BP.validate_windows([{"start": 30.0, "end": 40.0}], punches=[[35, 37]])
    assert w and "punch" in w[0]


# ---------------------------------------------------------------- raw -> final with the hook offset
def test_final_time_shifts_by_hook_length_and_hold():
    tm = TimeMap.from_segments([(0, 10), (12, 20)])          # raw 10..12 cut out
    assert BP.final_time(tm, 5.0, 1.0) == pytest.approx(5.0)
    assert BP.final_time(tm, 5.0, 1.25, offset=6.0) == pytest.approx(6.0 + 4.0)
    assert BP.final_time(tm, 14.0, 1.0, offset=6.0) == pytest.approx(6.0 + 12.0)
    assert BP.final_time(tm, 11.0, 1.0, offset=6.0) == pytest.approx(6.0 + 10.0)   # inside a cut -> next span
    assert BP.final_time(tm, 14.0, 1.0, 6.0, hold_at=13.0, hold=2.0) == pytest.approx(20.0)
    assert BP.final_time(tm, 12.5, 1.0, 6.0, hold_at=13.0, hold=2.0) == pytest.approx(16.5)


# ---------------------------------------------------------------- scenes
SPECS = {
    "tiles": {"title": "4 个平台", "items": [["Seedance", "字节"], ["可灵", "快手"], ["MiniMax", "海螺"], ["Muse", "token"]]},
    "flow": {"title": "MCP", "items": [["Claude Code", "脚本"], ["MCP", "", True], ["可灵", "生成"]], "foot": "同一个 session"},
    "bars": {"title": "分辨率", "items": [["768P", 0.42, "低"], ["1080P", 0.62, "合适", True], ["2K", 1.0, "浪费"]]},
    "stat": {"title": "废片率", "items": [[1, "分钟成片"], ["2.5–3", "分钟生成", True]], "bars": [["成片", 36], ["生成", 100, True]]},
    "toast": {"title": "参考素材上限", "items": ["REF 1", "REF 2", "REF 3"], "alert": "生成失败", "detail": "（没说原因）"},
    "ranking": {"title": "推荐", "items": [["MiniMax", "性价比"], ["Seedance", "可控"], ["可灵", "偏贵"]]},
    "columns": {"title": "成本", "items": [["可灵", 200], ["Seedance", 100], ["MiniMax", 25, "20–30", "每条", True]]},
    "checklist": {"title": "补课", "items": ["构思 idea", "写脚本", "学分镜"]},
    "swatch": {"title": "Higgsfield", "colors": ["#d9d3c7", "#b9c4c9"], "pros": ["调色清淡"], "cons": ["效果一般"]},
}
EXPECT = {"tiles": "sc-tile", "flow": "sc-pipe", "bars": "sc-bar", "stat": "sc-eq", "toast": "sc-toast",
          "ranking": "sc-rank hi", "columns": "sc-colbar", "checklist": "sc-chk", "swatch": "sc-swatch"}


@pytest.mark.parametrize("kind", hf.SCENE_KINDS)
def test_scene_generator_elements(kind):
    sc = hf.scene_card("c4x", dict(SPECS[kind], kind=kind), 10.0, 20.0, 760, 740)
    h, js = sc["html"], sc["js"]
    assert h.startswith('<div class="scene" id="c4x" style="width:760px;height:740px">')
    assert EXPECT[kind] in h and "sc-h" in h
    assert js.count("#c4x ") == js.count('"#') and "tl." in js     # every selector scoped to the scene
    times = [float(t) for t in re.findall(r"\}, ([\d.]+)\);", js)]
    assert times and all(10.0 <= t < 20.0 for t in times)


def test_scene_scales_to_card_and_escapes():
    sc = hf.scene_card("x", {"kind": "checklist", "title": "<b>【重点】</b>", "items": ["a"]}, 0, 5, 380, 740)
    assert "&lt;b&gt;<em>重点</em>&lt;/b&gt;" in sc["html"] and "scale(0.5)" in sc["html"]
    with pytest.raises(ValueError):
        hf.scene_card("x", {"kind": "pie"}, 0, 5)
    css = hf.scene_css(hf.scene_palette(gold="#123456"))
    assert "#123456" in css and ".sc-in" in css


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_scene_and_pip_js_parse(tmp_path):
    body = "".join(hf.scene_card(f"s{k}", dict(SPECS[k], kind=k), 1, 9)["js"] for k in hf.SCENE_KINDS)
    body += _pip()["js"] + hf.flash(5.0)["js"]
    src = "const gsap = { timeline: () => null };\nfunction f() {\n" + hf.prelude() + body + "}\n"
    p = tmp_path / "s.js"
    p.write_text(src, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ---------------------------------------------------------------- PiP
def _pip(wins=None):
    g = BP.pip_layout(BP.GEO["horizontal"])
    wins = wins or [dict(id="pip0", s=10.0, e=20.0, video="assets/extras/a.mp4", media_start=3.0, tag="A"),
                    dict(id="pip1", s=20.2, e=30.0, images=["assets/extras/1.png", "assets/extras/2.png"], tag="B"),
                    dict(id="pip2", s=40.0, e=50.0, video="assets/extras/a.mp4")]
    return hf.pip_windows(wins, g["clip"], g["scale"], g["x"], g["y"], g["tile"], g["frame"])


def test_pip_html_times_only_the_video():
    p = _pip()
    assert '<div id="pip0" class="full pipscr">' in p["html"]                       # plain wrapper
    assert re.search(r'<video id="pip0v"[^>]*muted[^>]*data-start="10.0"[^>]*data-media-start="3.0"', p["html"])
    assert '<div id="pip1" class="full clip pipscr" data-start="20.2"' in p["html"]  # image window: wrapper timed
    assert p["overlay"].count("pipring clip") == 2                                   # runs: [pip0+pip1], [pip2]
    assert 'data-duration="10.7"' in p["html"]                                       # pip0 lives into pip1 (cross-fade)
    assert re.search(r'data-track-index="1"', p["html"]) and re.search(r'data-track-index="12"', p["html"])
    assert 'tl.set("#pip0", { opacity: 0 }, 20.7)' in p["js"]
    assert p["js"].count('tl.to("#face", { clipPath: "inset(0px') == 2


def _inside(box, W, H):
    l, t, w, h = box
    return l >= 0 and t >= 0 and l + w <= W + 0.5 and t + h <= H + 0.5


def test_pip_geometry_horizontal_inside_canvas():
    g = BP.GEO["horizontal"]
    p = BP.pip_layout(g)
    assert _inside(p["tile"], 1920, 1080) and _inside(p["frame"], 1920, 1080)
    ct, cr, cb, cl = g["pip_clip"]
    # the clipped region's top-left lands exactly on the tile
    assert p["x"] + cl * p["scale"] == pytest.approx(p["tile"][0], abs=0.2)
    assert p["y"] + ct * p["scale"] == pytest.approx(p["tile"][1], abs=0.2)
    assert _inside(BP.pip_layout(BP.GEO["vertical"])["tile"], 1080, 1920)


@pytest.mark.parametrize("spec", ["xiaohongshu:full", "douyin", "youtube-shorts", "xiaohongshu:vertical"])
def test_pip_geometry_vertical_clear_of_captions_and_buttons(spec):
    prof, _ = BP.resolve_platform(spec, "vertical")
    for face in (None, (0.3, 0.35, 0.2), (0.7, 0.5, 0.15)):
        g = BP.vertical_geo(prof, (1920, 1080), face)
        p = BP.pip_layout(g)
        W, H = g["W"], g["H"]
        assert _inside(p["tile"], W, H) and _inside(p["frame"], W, H)
        l, t, w, h = p["tile"]
        cx0, cy0, cx1, cy1 = PF.caption_box(prof)
        assert t + h <= cy0                                         # above the caption band
        for kx0, ky0, kx1, ky1 in PF.keepouts(prof):
            assert not (l < kx1 and l + w > kx0 and t < ky1 and t + h > ky0), (spec, p["tile"])
        fl, ft, fw, fh = p["frame"]
        assert ft + fh <= t                                         # frame above the tile
        ct, cr, cb, cl = g["pip_clip"]
        assert min(ct, cr, cb, cl) >= 0


# ---------------------------------------------------------------- hooks
def test_hook_plan_and_times():
    items = [{"spans": [(10.0, 12.0)], "lines": ["a", "b"]}, {"spans": [(20.0, 21.0), (22.0, 24.0)], "lines": ["c"]}]
    pieces, owner = TC.hook_plan(items, 2.0)
    assert owner == [0, 1, 1] and all(p["speed"] == 2.0 for p in pieces)
    assert "afade=t=out:st=0.970" in pieces[0]["af"]
    from vstudio import cut
    asm = cut.xfade_assemble(pieces, xfade=0.0, mute_pad=False, fps=30)
    t = TC.hook_times(asm, owner, items)
    assert t[0] == {"s": 0.0, "e": 1.0, "lines": ["a", "b"]}
    assert t[1]["s"] == pytest.approx(1.0) and t[1]["e"] == pytest.approx(2.5)


class _Prj:
    def __init__(self, cfg):
        self.cfg = cfg

    def get(self, dotted, default=None):
        cur = self.cfg
        for k in dotted.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur


def test_hook_items_come_only_from_config():
    assert TC.hook_items(_Prj({})) == []
    with pytest.raises(SystemExit, match="spans"):
        TC.hook_items(_Prj({"hooks": {"items": [{"lines": ["x"]}]}}))


def test_speeds_precedence_no_clamp(monkeypatch):
    from vstudio import formats
    monkeypatch.setattr(formats, "_persona_formats", lambda: {"promo": {"hooks_speed": 2.0, "speed": {"body": 1.5}}})
    assert common.hook_speed(_Prj({})) == 2.0 and common.body_rate(_Prj({})) == 1.5
    assert common.hook_speed(_Prj({"hooks": {"speed": 1.7}})) == 1.7
    assert common.body_rate(_Prj({"rates": {"body": 1.6}})) == 1.6
    monkeypatch.setattr(formats, "_persona_formats", lambda: {})
    monkeypatch.setattr(common, "P", lambda k, d=None: None)
    assert common.hook_speed(_Prj({})) == formats.FORMATS["promo"]["speed"]["hook"]
    assert common.body_rate(_Prj({})) == formats.FORMATS["promo"]["speed"]["body"]


# ---------------------------------------------------------------- montage duration check
def test_montage_short_render_retries_with_clean_source(monkeypatch, tmp_path):
    from vstudio import cut
    asm = cut.xfade_assemble([(0, 5), (10, 15)], xfade=0.3, mute_pad=False, fps=30)
    calls, durs = [], iter([7.0, asm.total])
    monkeypatch.setattr(cut, "render_assembly", lambda a, inputs, out, args=None: calls.append(inputs[0]))
    monkeypatch.setattr(TC.media, "duration", lambda p: next(durs))
    monkeypatch.setattr(TC, "clean_cfr", lambda src, wd, fps=30: str(tmp_path / "clean.mp4"))
    used = TC.render_checked(asm, "src.mp4", str(tmp_path / "o.mp4"), str(tmp_path), args=[])
    assert calls == ["src.mp4", str(tmp_path / "clean.mp4")] and used.endswith("clean.mp4")


def test_montage_still_short_is_a_clear_error(monkeypatch, tmp_path):
    from vstudio import cut
    asm = cut.xfade_assemble([(0, 5), (10, 15)], xfade=0.3, mute_pad=False, fps=30)
    monkeypatch.setattr(cut, "render_assembly", lambda *a, **k: None)
    monkeypatch.setattr(TC.media, "duration", lambda p: 6.0)
    monkeypatch.setattr(TC, "clean_cfr", lambda src, wd, fps=30: "clean.mp4")
    with pytest.raises(SystemExit, match="planned 9.70s"):
        TC.render_checked(asm, "src.mp4", str(tmp_path / "o.mp4"), str(tmp_path), args=[])


def test_montage_on_time_renders_once(monkeypatch, tmp_path):
    from vstudio import cut
    asm = cut.xfade_assemble([(0, 5)], xfade=0.3, mute_pad=False, fps=30)
    calls = []
    monkeypatch.setattr(cut, "render_assembly", lambda *a, **k: calls.append(1))
    monkeypatch.setattr(TC.media, "duration", lambda p: asm.total + 0.3)
    assert TC.render_checked(asm, "src.mp4", str(tmp_path / "o.mp4"), str(tmp_path), args=[]) == "src.mp4"
    assert calls == [1]


def test_new_encodes_use_media_encoder_selection():
    for f in ("tight_cut.py", "screen_crop.py", "build_promo.py"):
        assert '"libx264"' not in (S / f).read_text(encoding="utf-8"), f


# ---------------------------------------------------------------- privacy crop detector
def _noise(h, w, mean, rng, amp=8):
    return np.clip(rng.normal(mean, amp, (h, w)), 0, 255)


def test_detect_chrome_header_over_dark_page():
    rng = np.random.default_rng(0)
    f = np.zeros((1080, 1920))
    f[:122] = _noise(122, 1920, 230, rng, 30)     # tabs + url bar + bookmarks: light, with text
    f[121] = 221
    f[122:] = _noise(958, 1920, 15, rng, 3)
    assert SC.detect_top_bar([f]) == 124


def test_detect_bookmarks_border_over_light_page():
    rng = np.random.default_rng(1)
    f = _noise(1080, 1920, 250, rng, 3)
    f[:110] = _noise(110, 1920, 232, rng, 25)
    f[110:121] = 248
    f[121] = 221                                  # the bookmarks bar's bottom border
    f[300:340, 100:1800] = 40                     # page text further down
    assert SC.detect_top_bar([f, f]) == 124


def test_detect_native_black_band_and_nothing():
    rng = np.random.default_rng(2)
    f = _noise(1112, 1920, 120, rng, 30)
    f[:32] = 0
    assert SC.detect_top_bar([f]) == 32
    assert SC.detect_top_bar([_noise(1080, 1920, 120, rng, 30)]) == 0


def test_crop_spec_defaults():
    assert SC.resolve_spec(None, "inputs/Screen Recording 2026-01-02 at 10.mov") == "auto"
    assert SC.resolve_spec(None, "inputs/rec1.mov") == "auto"
    assert SC.resolve_spec(None, "inputs/recipe.mp4") is None
    assert SC.resolve_spec(None, "inputs/shot.png") is None
    assert SC.resolve_spec(False, "rec1.mov") is None
    assert SC.resolve_spec([0, 124, 1920, 956], "a.mp4") == [0, 124, 1920, 956]
    with pytest.raises(ValueError):
        SC.resolve_spec([0, 1], "a.mp4")


def test_clean_image_crop(tmp_path):
    from PIL import Image
    a = np.full((400, 600, 3), 20, np.uint8)
    a[:50] = 230
    p = tmp_path / "Screen Recording shot.png"
    Image.fromarray(a).save(p)
    out, c = SC.clean(str(p), "auto", str(tmp_path / "work"), log=lambda *_: None)
    assert c == [0, 52, 600, 348] and Image.open(out).size == (600, 348)
    assert SC.clean(str(p), False, str(tmp_path / "work"))[1] is None


# ---------------------------------------------------------------- caption overlap
def test_cues_never_overlap_after_the_tail():
    tm = TimeMap.from_segments([(0, 30)])
    subs = [[24.32 - 24.0, 25.12 - 24.0, "Hello大家好"], [25.12 - 24.0, 30.12 - 24.0, "下一句"], [6.4, 6.5, "短"],
            [6.55, 8.0, "再下一句"], [9.0, 10.0, "隔开的"]]
    cues = [{"s": BP.r(BP.final_time(tm, a, 1.5)), "e": BP.r(BP.final_time(tm, b, 1.5) + 0.15), "t": t} for a, b, t in subs]
    assert cues[0]["e"] > cues[1]["s"]                       # the bug: the tail runs into the next cue
    BP.clip_cues(cues)
    for x, y in zip(cues, cues[1:]):
        assert x["e"] <= y["s"] - 0.02 + 1e-9 or x["e"] - x["s"] == pytest.approx(0.2)
    assert cues[0]["e"] == pytest.approx(cues[1]["s"] - 0.02)
    short = next(c for c in cues if c["t"] == "短")
    assert short["e"] - short["s"] == pytest.approx(0.2)     # minimum kept
    assert next(c for c in cues if c["t"] == "再下一句")["e"] == pytest.approx(8.0 / 1.5 + 0.15, abs=1e-3)   # gap kept
    gap = next(c for c in cues if c["t"] == "隔开的")
    assert gap["e"] == pytest.approx(10.0 / 1.5 + 0.15, abs=1e-3)   # last cue untouched


# ---------------------------------------------------------------- footage map
def test_footage_about_matches_the_cards_own_text(capsys):
    """about "平台" on a tiles card titled "4 个平台" while she lists the platform names is not a mismatch;
    a pip tag counts too; an about found nowhere is still flagged."""
    scene = SPECS["tiles"]
    own = BP.own_text(scene, None)
    assert "4 个平台" in own and "Seedance" in own and "tiles" not in own
    said = [(10.0, 14.0, "可灵 Seedance MiniMax 还有 Muse")]
    rows = [("card", 10, 14, 10.0, 14.0, "scene:tiles 4 个平台", "平台", own),
            ("pip", 20, 24, 20.0, 24.0, "video:a.mp4", "价格", BP.own_text("价格对比")),
            ("pip", 30, 34, 30.0, 34.0, "video:b.mp4", "分镜", BP.own_text("录屏")),
            ("card", 40, 44, 40.0, 44.0, "img:x.png", "Muse", "")]           # legacy 7-item rows still work
    BP.print_footage(rows, [[0.0, 100.0, "横评"]], said + [(40.0, 44.0, "Muse 的 token 计费")])
    out = capsys.readouterr().out.splitlines()[1:]
    assert [ln[1] for ln in out] == [" ", " ", "!", " "]
    assert not BP.about_mismatch("平台", "可灵 Seedance", "横评", own)
    assert BP.about_mismatch("平台", "可灵 Seedance", "横评", "")


# ---------------------------------------------------------------- montage from b-roll sources
def test_montage_clip_forms():
    assert common.parse_clip([0.0, 8.0, "可灵"]) == dict(src=None, start=0.0, end=8.0, label="可灵")
    assert common.parse_clip([16.0, 22.0, None])["src"] is None
    assert common.parse_clip([2.0, 9.0]) == dict(src=None, start=2.0, end=9.0, label=None)
    assert common.parse_clip([1, 3.0, 9.0, "Seedance"]) == dict(src=1, start=3.0, end=9.0, label="Seedance")
    assert common.parse_clip([0, 0.0, 6.0]) == dict(src=0, start=0.0, end=6.0, label=None)     # index, no label
    assert common.parse_clip(["a.mp4", 1.0, 4.0])["src"] == "a.mp4"
    d = common.parse_clip({"src": 2, "start": 1, "end": 5, "crop": "auto", "fit": "blur"})
    assert d["src"] == 2 and d["crop"] == "auto" and d["fit"] == "blur" and d["label"] is None
    with pytest.raises(SystemExit, match="shorter"):
        common.parse_clip([0, 4.0, 4.2, "x"])
    with pytest.raises(SystemExit, match="want"):
        common.parse_clip([1.0])


def test_montage_source_resolution(tmp_path):
    rec, cutf = tmp_path / "Screen Recording 1.mov", tmp_path / "out" / "FinePrint_v4-zh.mp4"
    cutf.parent.mkdir()
    for f in (rec, cutf, tmp_path / "hl.mp4", tmp_path / "local.mp4"):
        f.write_bytes(b"x")
    prj = _Prj({"highlights": "hl.mp4", "broll": [str(rec), str(cutf)]})
    prj.p = lambda r: r if os.path.isabs(r) else str(tmp_path / r)
    assert common.resolve_source(prj, None) == str(tmp_path / "hl.mp4")
    assert common.resolve_source(prj, "highlights") == str(tmp_path / "hl.mp4")
    assert common.resolve_source(prj, 1) == str(cutf)
    assert common.resolve_source(prj, "FinePrint_v4-zh.mp4") == str(cutf)
    assert common.resolve_source(prj, "FinePrint_v4-zh") == str(cutf)
    assert common.resolve_source(prj, "local.mp4") == str(tmp_path / "local.mp4")
    with pytest.raises(SystemExit, match="out of range"):
        common.resolve_source(prj, 5)
    with pytest.raises(SystemExit, match="0: Screen Recording 1.mov"):
        common.resolve_source(prj, "nope.mp4")


def test_canvas_fit_vertical_is_pillarboxed_169_is_cover():
    assert TC.canvas_fit((1080, 1920), (1920, 1080)) == "blur"
    assert TC.canvas_fit((1920, 1080), (1920, 1080)) == "crop"
    assert TC.canvas_fit((1920, 956), (1920, 1080)) == "crop"            # a browser-cropped recording: cover
    assert TC.canvas_fit((1920, 1080), (1920, 1080), rotation=90) == "blur"   # phone clip stored landscape + rotated
    assert TC.canvas_fit((1440, 1080), (1920, 1080)) == "blur"           # 4:3 is past the 1.25x tolerance


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_montage_multi_from_broll_sources(tmp_path):
    """A vertical silent clip + a 16:9 clip with sound -> one 640x360 montage, duration = clips - crossfades."""
    v = tmp_path / "phone.mp4"
    h = tmp_path / "cut.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=4",
                    "-pix_fmt", "yuv420p", str(v)], check=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=5",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=5", "-pix_fmt", "yuv420p", "-shortest", str(h)],
                   check=True)
    work = tmp_path / "work"
    work.mkdir()
    prj = _Prj({"broll": [str(v), str(h)]})
    prj.p = lambda r: r if os.path.isabs(r) else str(tmp_path / r)
    prj.work = str(work)
    prj.w = lambda n: str(work / n)
    clips = [common.parse_clip(c) for c in ([0, 0.5, 2.5, "竖屏"], ["cut.mp4", 1.0, 3.0, None])]
    out = str(work / "montage.mp4")
    TC.montage_multi(prj, clips, out, 0.3, "640:360", 30, -17)
    from vstudio import media
    info = media.probe(out)
    assert (info["w"], info["h"]) == (640, 360) and info["has_audio"]
    assert info["duration"] == pytest.approx(2.0 + 2.0 - 0.3, abs=0.1)
    parts = sorted(os.listdir(work / "montage_parts"))
    assert len(parts) == 2 and all(p.endswith(".mp4") for p in parts)
    with pytest.raises(SystemExit, match="ends past"):
        TC.montage_multi(prj, [common.parse_clip([0, 3.0, 9.0])], out, 0.3, "640:360", 30, -17)


def test_montage_crop_is_per_source(monkeypatch):
    """montage.crop: false (meant for the highlights file) keeps auto on b-roll recordings; a clip crop wins."""
    seen = []
    monkeypatch.setattr(TC.screen_crop, "clean", lambda path, spec, wd: (seen.append((os.path.basename(path), spec)),
                                                                          (path, None))[1])
    prj = _Prj({"highlights": "/x/hl.mp4", "broll": ["/x/Screen Recording 1.mov", "/x/cut.mp4"]})
    prj.p = lambda r: r
    prj.work = "/x/work"
    clips = [common.parse_clip(c) for c in ([0.0, 4.0, "hl"], [0, 1.0, 5.0, None], [1, 1.0, 5.0, None],
                                            {"src": 0, "start": 6, "end": 9, "crop": [0, 10, 100, 50]})]
    TC.montage_sources(prj, clips, highlights_crop=False)
    assert seen == [("hl.mp4", False), ("Screen Recording 1.mov", None), ("cut.mp4", None),
                    ("Screen Recording 1.mov", [0, 10, 100, 50])]


# ---------------------------------------------------------------- delivery bitrate (export.py)
def test_export_reencodes_only_an_oversized_render(monkeypatch, tmp_path):
    import export as EX
    runs = []
    monkeypatch.setattr(EX.media, "run", lambda cmd: runs.append(cmd))
    info = dict(w=1920, h=1080, fps=30.0, duration=480.0, vbitrate=14_800_000)
    monkeypatch.setattr(EX.media, "probe", lambda p: info)
    out, target, have = EX.fit_bitrate("raw.mp4", str(tmp_path / "r.mp4"), PF.profile("youtube", use_persona=False))
    assert out.endswith("r.mp4") and target == 8_000_000 and have == 14_800_000 and len(runs) == 1
    assert "-c:a" in runs[0] and runs[0][runs[0].index("-c:a") + 1] == "copy"
    info["vbitrate"] = 7_500_000
    assert EX.fit_bitrate("raw.mp4", str(tmp_path / "r.mp4"))[0] == "raw.mp4" and len(runs) == 1
