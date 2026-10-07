"""Design themes (vstudio.theme): resolution order, tokens, contrast rules, themed furniture, the output-edit
``theme`` op and the client / recipe layers."""
import os
import sys
import types

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from vstudio import draw as D  # noqa: E402
from vstudio import overlays as O  # noqa: E402
from vstudio import theme as TH  # noqa: E402
from vstudio.project import outfx as FX  # noqa: E402
from vstudio.project import outputs as OUT  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("VSTUDIO_THEME", raising=False)


# ---------------------------------------------------------------- resolution order
def test_default_is_editorial_with_the_example_persona():
    T = TH.current()
    assert T["name"] == "editorial" and T["source"] in ("persona", "default")
    assert TH.resolve(persona={})["name"] == "editorial"
    assert TH.resolve(persona={})["source"] == "default"


def test_resolution_order(monkeypatch):
    p = {"style": {"theme": "soft"}, "client": {"theme": "mono"}}
    assert TH.resolve(persona={"style": {"theme": "soft"}})["name"] == "soft"
    assert TH.resolve(persona=p)["name"] == "mono"                                   # client > persona
    assert TH.resolve(recipe={"theme": "night"}, persona=p)["name"] == "night"       # recipe > client
    monkeypatch.setenv("VSTUDIO_THEME", "xhs-pop")
    assert TH.resolve(recipe={"theme": "night"}, persona=p)["name"] == "xhs-pop"     # env > recipe
    assert TH.resolve("editorial", recipe={"theme": "night"}, persona=p)["name"] == "editorial"   # explicit > env
    assert [s for s, _ in TH.layers("editorial", {"theme": "night"}, p)] == \
        ["explicit", "env", "recipe", "client", "persona"]


def test_use_block_is_the_explicit_layer():
    with TH.use("night") as T:
        assert T["name"] == "night" and TH.current()["name"] == "night"
        with TH.use(None):
            assert TH.current()["name"] == "night"
    assert TH.current()["name"] == "editorial"


def test_legacy_brand_keeps_the_old_look():
    p = {"brand": {"accent": "#FF2442", "highlight": "#FFD60A", "panel_theme": "notes-red"}}
    T = TH.resolve(persona=p)
    assert T["name"] == "classic" and T["source"] == "legacy" and T["accent"] == "#FF2442"
    p2 = dict(p, style={"theme": "editorial"})                                       # a chosen theme wins
    assert TH.resolve(persona=p2)["name"] == "editorial"


def test_token_overrides_and_aliases():
    T = TH.resolve({"theme": "editorial", "accent": "#3E5C76"})
    assert T["name"] == "editorial" and T["accent"] == "#3E5C76" and T["paper"] == TH.PRESETS["editorial"]["paper"]
    # a persona tint survives a recipe that only names a preset
    T = TH.resolve(recipe={"theme": "mono"}, persona={"style": {"theme": "soft", "accent": "#123456"}})
    assert T["name"] == "mono" and T["accent"] == "#123456"
    assert TH.canonical("黑白灰") == "mono" and TH.canonical("夜间") == "night" and TH.canonical("XHS-POP") == "xhs-pop"
    assert TH.canonical("nope") is None
    assert TH.resolve("nope", persona={})["name"] == "editorial"                    # unknown name: ignored


def test_brand_follows_the_theme(monkeypatch):
    assert D.brand()["accent"] == D.rgb(TH.PRESETS["editorial"]["accent"])
    with TH.use("night"):
        assert D.brand()["accent"] == D.rgb(TH.PRESETS["night"]["accent"])
    assert D.brand(accent="#000000")["accent"] == (0, 0, 0)                          # explicit still wins


def test_recipe_manifest_has_a_theme_param():
    from vstudio.project import manifests as M
    m = M.get("talkinghead")
    assert set(m["params"]["properties"]["theme"]["enum"]) == set(TH.names(True))


def test_batch_run_hands_the_project_theme_to_subprocesses(tmp_path, monkeypatch):
    from vstudio.batch import clients as CL
    (tmp_path / "spec.yaml").write_text("defaults: {theme: night}\n")
    with CL.activate(str(tmp_path)):
        assert os.environ["VSTUDIO_THEME"] == "night" and TH.current()["name"] == "night"
    assert "VSTUDIO_THEME" not in os.environ


def test_client_theme_validated_and_overlaid():
    from vstudio.batch import clients as CL
    assert CL.validate({"theme": "黑白灰"})["theme"] == "mono"
    with pytest.raises(CL.ClientError):
        CL.validate({"theme": "rainbow"})
    ov = CL.persona_overlay(CL.effective({"name": "x", "theme": "soft"}))
    assert TH.resolve(persona=ov)["name"] == "soft"


# ---------------------------------------------------------------- the rules (references/STYLE_RULES.md)
@pytest.mark.parametrize("name", TH.names(True))
def test_contrast(name):
    T = TH.PRESETS[name]
    c = lambda k: D.rgb(T[k])
    assert TH.contrast(c("ink"), c("paper")) >= 7.0
    assert TH.contrast(c("ink2"), c("paper")) >= 4.5
    assert TH.contrast(c("card_ink"), c("card")) >= 7.0
    if T["emphasis"] == "color" and name != "classic":               # accent-coloured keyword text (classic = legacy)
        assert TH.contrast(c("accent"), c("paper")) >= 4.5
    if T["emphasis"] == "marker" and T["marker_alpha"] >= 1:        # ink on the marker band
        assert TH.contrast(c("ink"), c("marker")) >= 4.5


@pytest.mark.parametrize("name", [n for n in TH.names() if n != "xhs-pop"])
def test_no_saturated_red_by_default(name):
    import colorsys
    T = TH.PRESETS[name]
    for k in ("accent", "marker", "over_emph"):
        r, g, b = (v / 255 for v in D.rgb(T[k]))
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        red = (h < 0.03 or h > 0.95) and s > 0.75 and 0.3 < l < 0.7
        assert not red, f"{name}.{k} is a saturated red"
    assert T["motion"]["in_s"] <= 0.35 and not T["motion"]["overshoot"]
    assert T["stamp"]["angle"] == 0 and T["stamp"]["anim"] != "slam"
    assert T["notes"] == "paper" and T["quote"] == "type"


def _has(img, col, tol=6):
    a = np.asarray(img.convert("RGBA")).astype(int)
    m = (np.abs(a[..., :3] - np.array(col)).max(-1) <= tol) & (a[..., 3] > 200)
    return int(m.sum())


def test_emphasis_one_keyword_per_line_marker_behind_ink():
    T = TH.resolve("editorial")
    f = D.load_font("cjk-bold", 60)
    one = D.emph_layer("看更大的【世界】", f, T)
    two = D.emph_layer("先做【减法】再做【加法】", f, T)
    mk = D.rgb(T["marker"])
    assert _has(one, mk) > 200
    w1 = _has(two, mk)
    plain = D.emph_layer("先做减法再做加法", f, T)
    assert _has(plain, mk) == 0
    assert w1 < 2 * _has(one, mk) * 1.2                # the second keyword is not marked (S2)
    assert D.limit_runs([("a", True), ("b", False), ("c", True)], 1) == [("a", True), ("b", False), ("c", False)]
    assert _has(D.emph_layer("【世界】", f, T, sweep=0.0), mk) == 0                  # marker-sweep start
    acc = D.rgb(TH.PRESETS["night"]["accent"])
    assert _has(D.emph_layer("【世界】", f, TH.resolve("night")), acc, tol=30) > 50    # colour emphasis


def test_themed_blocks_render():
    for name in TH.names(True):
        with TH.use(name):
            for im in (O.title_band("小步快跑，【每天复盘】", 1080, 160),
                       O.quote_block([("把复杂的事，【讲简单】", "main"), ("而是知道每一步为什么", "sub")], 900),
                       O.notes_chip("本段", "把复杂的事讲简单", 370),
                       O.notes_panel("三个要点", ["先定目标", "再拆步骤", "【每天复盘】"], width=620),
                       O.marker_line("先做【减法】", 64, sweep=0.5),
                       O.chapter_rule("第二部分", "先进去", index=2, progress=0.5),
                       O.counter(7, 0.3, label="粉丝", suffix="万"),
                       O.lower_third("Speaker A", "Career coach"),
                       O.stamp("亲测"),
                       O.progress_bar([(0, 5, "a"), (5, 10, "b")], 6, 10, style=None)):
                assert im.mode == "RGBA" and im.width > 10 and im.height > 2
    with TH.use("editorial"):
        band = np.asarray(O.title_band("标题", 400, 100))
        assert tuple(band[2, 2, :3]) == D.rgb(TH.PRESETS["editorial"]["paper"])
        st = O.stamp("亲测")
        assert abs(st.width - st.height) > 10                      # upright label, not a rotated square-ish plate
    assert O.counter_text(7, 0) == "0" and O.counter_text(7, 5) == "7" and O.counter_text(70000, 0.45).count(",") == 1
    assert O.get_theme()["layout"] == "paper"
    with TH.use("classic"):
        assert O.get_theme()["layout"] == "header"


def test_new_output_effects_draw():
    img = np.zeros((640, 360, 3), np.uint8) + 90
    for eid, p in (("marker-sweep", {"text": "先做【减法】"}), ("chapter-rule", {"label": "第二部分", "index": 2}),
                   ("number-counter", {"value": 7, "suffix": "万", "label": "粉丝"}),
                   ("lower-third", {"name": "Speaker A", "role": "coach"})):
        params, _ = FX.validate(eid, p)
        L = FX.make_layer(dict(effect=eid, params=params, start=0, end=3), 360, 640)
        a = img.copy()
        L.draw(a, 1.0, 3.0)
        assert (a != img).any(), eid
    assert FX.resolve("划重点") == "marker-sweep" and FX.resolve("数字滚动") == "number-counter"
    s, op, dy = FX.anim_state("rise", 0.0, 2.0)
    assert op == 0 and dy > 0
    s, op, dy = FX.anim_state("rise", 0.5, 2.0)
    assert op == 1 and dy == 0 and s == 1.0


# ---------------------------------------------------------------- output edit `theme` op
def _fake_doc():
    rec = dict(mode="pipeline", info=dict(duration=60.0, w=1080, h=1440, has_audio=True))
    return types.SimpleNamespace(rec=rec, d={})


def test_theme_op_normalize_and_fold():
    st = OUT.empty_state()
    st["captions"]["style"] = dict(color="#1A1A1E", highlight="#FF2442", stroke=0, size=0.8, y=0.65)
    st["title"] = dict(text="小步快跑，每天复盘", color="#1A1A1E", band_color="#FAF7F2", y=0.04)
    st["effects"] = [dict(id="fx1", effect="stacking-stamps", start=1, end=2,
                          params=dict(text="亲测有效", angle=8.0, anim="slam", x=0.8, y=0.3, scale=1.0))]
    n, _v, _w = OUT.normalize(_fake_doc(), st, {"op": "theme", "theme": "编辑感"})
    assert n["theme"] == "editorial" and n["restyle"] is True
    st2 = OUT.fold(st, n)
    assert st2["theme"] == "editorial"
    assert st2["captions"]["style"] == dict(size=0.8, y=0.65)              # look keys handed to the theme
    assert "color" not in st2["title"] and st2["title"]["text"].startswith("小步")
    assert st2["effects"][0]["params"]["angle"] is None and st2["effects"][0]["params"]["anim"] is None
    assert st2["effects"][0]["params"]["x"] == 0.8
    n, _v, _w = OUT.normalize(_fake_doc(), st, {"op": "theme", "theme": "mono", "keep_colors": True})
    assert OUT.fold(st, n)["captions"]["style"]["highlight"] == "#FF2442"
    n, _v, _w = OUT.normalize(_fake_doc(), st, {"op": "theme", "theme": "editorial", "accent": "#3E5C76"})
    assert n["theme"] == {"theme": "editorial", "accent": "#3E5C76"}
    with pytest.raises(OUT.OutputError) as e:
        OUT.normalize(_fake_doc(), st, {"op": "theme", "theme": "rainbow"})
    assert e.value.info["code"] == "unknown-theme"
    assert OUT.describe(dict(op="theme", theme="night"))["code"] == "op-theme"


def test_theme_chat_fallback():
    assert OUT._rule_ops("换成更高级的配色", 60) == [dict(op="theme", theme="editorial")]
    assert OUT._rule_ops("用黑白灰的风格", 60) == [dict(op="theme", theme="mono")]
    assert OUT._rule_ops("导出小红书版本", 60) == [dict(op="export_add", target="xiaohongshu:vertical")]
    assert OUT._rule_ops("换回小红书红", 60) == [dict(op="theme", theme="xhs-pop")]
    assert OUT._rule_ops("红色的字有点丑", 60) == [dict(op="theme", theme="editorial")]


def test_caption_surface_paper_vs_video():
    from vstudio.project import outrender as R
    vis = dict(captions=[[0.0, 2.0, "这一步其实最【关键】"]], style={"y": 0.65, "position": "custom"},
               caption_box=[54, 1000, 1026, 1300])
    c = R.Captions(vis, 1080, 1440, None)
    paper = np.zeros((1440, 1080, 3), np.uint8)
    paper[:] = D.rgb(TH.PRESETS["editorial"]["paper"])[::-1]
    assert c._surface(paper, 540, 936) == "paper"
    noisy = np.random.default_rng(0).integers(0, 255, (1440, 1080, 3), dtype=np.uint8)
    assert c._surface(noisy, 540, 936) == "video"
    out = paper.copy()
    c.draw(out, 1.0)
    ink = np.array(D.rgb(TH.PRESETS["editorial"]["ink"])[::-1])
    assert (np.abs(out.astype(int) - ink).max(-1) < 30).sum() > 500           # ink text on the paper
    legacy = R.Captions(dict(vis, style={"color": "#FFFFFF", "y": 0.65, "position": "custom"}), 1080, 1440, None)
    assert legacy._surface(paper, 540, 936) == "legacy"
    hair = paper.copy()                                                          # a hairline / a video edge in the
    hair[900:904] = (60, 80, 160)                                                # probe is still a paper band
    hair[960:990, :200] = 30
    assert c._surface(hair, 540, 936) == "paper"


def test_title_band_text_only_over_flat_paper():
    from vstudio.project import outrender as R
    paper = np.zeros((300, 400, 3), np.uint8) + 200
    assert R._flat(paper, 10, 100)
    vid = np.random.default_rng(1).integers(0, 255, (300, 400, 3), dtype=np.uint8)
    assert not R._flat(vid, 10, 100)
    a = R._title_layer(dict(text="标题"), 400, 100, alpha=0)
    assert a[2, 2, 3] == 0 and a[:, :, 3].max() == 255                          # no band, opaque text


def test_render_key_follows_the_resolved_theme(monkeypatch):
    from vstudio.project import outrender as R
    rec = dict(mode="pipeline", info=dict(duration=10.0, w=1080, h=1440), cues=[])
    st = OUT.empty_state()
    tl = OUT.Timeline(st, 10.0)
    tg = dict(target="primary", w=1080, h=1440, profile=None, layout="auto")
    a = R.visual_spec(rec, st, tl, tg, False)["look"]
    monkeypatch.setenv("VSTUDIO_THEME", "night")
    b = R.visual_spec(rec, st, tl, tg, False)["look"]
    assert a != b                                                                # a persona / env theme re-renders


def test_stamp_styles():
    with TH.use("editorial"):
        lab = np.asarray(O.stamp("亲测有效"))
        assert TH.current()["stamp"]["style"] == "label" and lab[lab.shape[0] // 2, 2, 3] > 200   # card label
    with TH.use("classic"):
        assert TH.current()["stamp"]["angle"] == 8.0                             # the old slam stays in classic


def test_paper_caption_shrinks_before_it_wraps():
    from vstudio.project import outrender as R
    text = "你会有其他的稻草可以去揪着"
    vis = dict(captions=[[0.0, 2.0, text]], style={"y": 0.65, "position": "custom"}, caption_box=[200, 1000, 880, 1300])
    c = R.Captions(vis, 1080, 1440, None)
    size = c._size(text)
    w = D.text_width(text, D.load_font(TH.current()["font_caption"], size))
    c.box = (540 - w * 0.53, 1000, 540 + w * 0.53, 1300)                       # ~6 % too narrow for one line
    one = c.layer(0, text, "paper")
    assert one.shape[0] < size * 2.5                                               # one line, a little smaller
