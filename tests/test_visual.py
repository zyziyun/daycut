"""Fast checks for the shared visual modules (synthetic inputs, no network, no media files).

    python3 -m pytest tests/test_visual.py -q
"""
import os
import pathlib
import sys

import numpy as np
import pytest
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))

from vstudio import cover, draw, overlays, publish, render  # noqa: E402

CHAPTERS = [(0, 10, "开场"), (10, 30, "方法"), (30, 50, "案例"), (50, 60, "总结")]


def _rgba_ok(im, size=None):
    assert isinstance(im, Image.Image) and im.mode == "RGBA"
    assert im.width > 0 and im.height > 0
    if size:
        assert im.size == tuple(size)
    assert np.asarray(im)[..., 3].max() > 0, "image is fully transparent"


# ---------------------------------------------------------------- overlays
@pytest.mark.parametrize("theme", overlays.THEMES)
def test_overlays_render_per_theme(theme):
    _rgba_ok(overlays.notes_panel("三个要点", ["先想清楚【目标】", "用 Claude Code 写脚本再渲染出来", "  续行"], theme, width=620))
    assert overlays.notes_panel("标题", ["a"], theme, width=620).width == 620
    _rgba_ok(overlays.callout("这里是【关键】的一步", theme))
    _rgba_ok(overlays.node_card("第二部分：实战", "NEXT", theme))
    _rgba_ok(overlays.chapter_card(2, 5, "方法论：三步拆解", size=(1280, 720), theme=theme), (1280, 720))
    _rgba_ok(overlays.stamp("亲测", 8, theme))
    _rgba_ok(overlays.badge("精彩预告", theme))
    for style in ("outline", "filled", "star", "tag", "ghost"):
        _rgba_ok(overlays.chip("标签", style, theme))
    for style in ("classic", "refined"):
        for t in (0, 25, 60):
            im = overlays.progress_bar(CHAPTERS, t, 60, style=style, width=1080, theme=theme)
            _rgba_ok(im)
            assert im.width == 1080


def test_progress_static_and_html():
    st = overlays.progress_static(CHAPTERS, 60, width=1920)
    _rgba_ok(st["bar"]); assert st["bar"].width == 1920
    assert len(st["active"]) == len(CHAPTERS)
    # the fill is a per-frame overlay graph (drawbox never animated); "drawbox" stays as an alias
    assert "overlay=x='" in st["fill"] and st["drawbox"] == st["fill"] and "[in]" in st["fill"]
    for orient in ("horizontal", "vertical"):
        snip = overlays.hf_progress(CHAPTERS, 3.0, 60.0, orient)
        assert {"css", "html", "js"} <= set(snip) and "#bar-fill" in snip["css"] and "barwrap" in snip["html"]
        assert ".cue em" in overlays.hf_cue_css(orient)
    assert overlays.cue_html("用【Claude】<b>") == "用<em>Claude</em>&lt;b&gt;"


# ---------------------------------------------------------------- draw
def test_wrap_keeps_latin_and_no_orphan():
    f = draw.load_font("cjk-bold", 48)
    texts = ["我今天用 Claude Code 做了一个讲解视频真的很好用啊", "学习新模式让AI给你做3b1b讲解视频，效果非常好",
             "今天天气很好我们一起去公园玩吧好不好呀啊", "先打开 Claude Code，然后输入一句话，它就会帮你写完整个脚本了"]
    for text in texts:
        for w in range(260, 900, 37):
            for bal in (False, True):
                lines = draw.wrap(text, f, w, balance=bal)
                assert "".join(lines).replace(" ", "") == text.replace(" ", "")
                if "Claude Code" in text and w >= draw.text_width("Claude Code", f):
                    assert any("Claude Code" in ln for ln in lines), lines
                if "3b1b" in text:
                    assert any("3b1b" in ln for ln in lines), lines
                if len(lines) > 1:
                    core = [c for c in lines[-1] if c not in draw.NO_LINE_START]
                    assert len(core) > 1, (w, lines)


def test_wrap_markup_balanced_and_text_layer():
    f = draw.load_font("cjk-bold", 40)
    lines = draw.wrap("这是一个【非常非常长的高亮关键词】后面还有字", f, 260)
    for ln in lines:
        assert ln.count("【") == ln.count("】")
    im = draw.text_layer("这是【重点】", f)
    _rgba_ok(im)
    _rgba_ok(draw.text_layer("自动换行的一句比较长的字幕文本", f, max_w=300))
    sh, pad = draw.shadow(draw.rounded_rect((100, 50), 12, "#FF2442"))
    assert sh.size == (100 + 2 * pad, 50 + 2 * pad)


def test_alpha_paste_clips_pil_and_numpy():
    ov = draw.rounded_rect((80, 40), 10, (255, 0, 0, 255))
    base = Image.new("RGBA", (100, 100), (0, 0, 0, 255))
    draw.alpha_paste(base, ov, (-30, 80))
    assert base.getpixel((10, 90))[0] == 255
    arr = np.zeros((100, 100, 3), np.uint8)
    draw.alpha_paste(arr, ov, (50, 50), center=True, bgr=True)
    assert arr[50, 50, 2] == 255 and arr[50, 50, 0] == 0
    fl = np.zeros((100, 100, 3), np.float32)
    draw.alpha_paste(fl, ov, (90, 90), opacity=0.5)
    assert 120 < fl[95, 95, 0] < 135


# ---------------------------------------------------------------- covers
def _synthetic_photo(w=1600, h=1200):
    """Face-less test image: gradient + shapes (no detectable face)."""
    a = np.zeros((h, w, 3), np.uint8)
    a[..., 0] = np.linspace(40, 200, w)[None]; a[..., 1] = np.linspace(60, 140, h)[:, None]; a[..., 2] = 90
    im = Image.fromarray(a); d = ImageDraw.Draw(im)
    d.ellipse([w * .35, h * .2, w * .6, h * .6], fill=(220, 180, 160)); d.rectangle([w * .3, h * .62, w * .65, h], fill=(30, 30, 60))
    return im


@pytest.mark.parametrize("aspect,size", [("4:3", (1440, 1080)), ("16:9", (1920, 1080)), ("3:4", (1080, 1440))])
def test_split_cover_aspects(aspect, size, tmp_path):
    cfg = dict(photo=_synthetic_photo(), face_x=0.5, aspect=aspect,
               quote={"text": "A quote that sets the tone", "by": "Someone"},
               title={"lines": ["学习新模式", "让AI做【讲解】视频"], "highlight": ["AI"]},
               thumbnail={"image": _synthetic_photo(800, 450), "crop": [0, 0, 1, 1]},
               chips=["Claude Code", "3 步", {"text": "亲测", "style": "accent"}],
               stamp={"text": "亲测", "rotate": 8}, corner_tag="记笔记 ↓")
    out = tmp_path / f"c_{aspect.replace(':', 'x')}.jpg"
    im = cover.split_cover(cfg, out=str(out))
    assert im.size == size and out.exists()


def test_split_cover_faceless_auto_falls_back(tmp_path):
    """face_x='auto' + retouch on a face-less image (or without the model) must still render."""
    im = cover.split_cover(dict(photo=np.asarray(_synthetic_photo()), aspect="16:9", face_x="auto", retouch=True,
                                title=["标题"]))
    assert im.size == (1920, 1080)


def test_other_covers():
    frame = _synthetic_photo(1920, 1080)
    c, c43 = cover.notes_cover(frame, panels=[("要点一", "先做这个"), ("要点二", "再做那个")],
                               fun=("彩蛋", ["第一行", "重点行"], "重点行"), kicker="一句话讲清楚")
    assert c.size == (1920, 1080) and c43.size == (1440, 1080)
    assert cover.framed_cover(frame, {"eyebrow": "E", "big1": "大字", "big2": "强调", "sub": ["副标题"], "chips": ["a", "b"]}).size == (1920, 1080)
    assert cover.framed_cover(frame, {"big1": "大字", "chips": ["a"]}, size=(1080, 1440)).size == (1080, 1440)
    _rgba_ok(cover.polaroid(frame, (400, 300), rot=-4, cap="caption"))
    sheet = cover.contact_sheet([frame] * 7, labels=[f"{i}s" for i in range(7)], cols=3, tile_w=200)
    assert sheet.width == 600 and sheet.height > 0
    assert cover.score_blend({"mouthSmileLeft": 1, "mouthSmileRight": 1}, 0.5) == 1.0


# ---------------------------------------------------------------- publish
def test_check_title_counts():
    ok, n, hints = publish.check_title("学习新模式｜让AI给你做3b1b讲解视频", "xiaohongshu")
    assert n == 17 and ok and hints == []
    ok, n, hints = publish.check_title("这是一个非常非常非常非常非常非常长的小红书标题（附教程）", "xiaohongshu")
    assert not ok and hints
    ok, n, hints = publish.check_title("x" * 50, "xiaohongshu", suggest=lambda *a: ["custom"])
    assert not ok and hints == ["custom"]
    assert publish.check_title("short", "youtube")[1] == 5


def test_timestamps_and_post():
    assert publish.srt_ts(59.9996) == "00:01:00,000"
    assert publish.srt_ts(3661.5) == "01:01:01,500"
    assert publish.mmss(59.99) == "00:59" and publish.mmss(3700) == "1:01:40"
    lines = publish.chapter_lines([(12.4, "方法"), (75, "案例")], warn=None)
    assert lines == ["00:00 开场", "00:12 方法", "01:15 案例"]
    assert publish.chapter_lines([(0, 5, "A"), (30, 40, "B")], offset=30, warn=None)[0] == "00:00 B"
    for pl in ("xiaohongshu", "youtube", "bilibili"):
        txt = publish.post_body("钩子一句", ["正文"], chapters=[(0, "开场"), (20, "方法")],
                                links=[("链接", "https://example.com")], tags=["AI", "#教程"], platform=pl, warn=None)
        assert "钩子一句" in txt and "00:20 方法" in txt and "example.com" in txt
        assert ("标签：" in txt) if pl == "bilibili" else ("#AI" in txt)


# ---------------------------------------------------------------- render
def test_find_chrome_never_raises():
    p = render.find_chrome()
    assert p is None or os.path.exists(p)


def test_persona_css_and_fonts(tmp_path):
    css = render.persona_css()
    assert css.startswith(":root{") and "--accent:" in css
    staged = render.stage_fonts(tmp_path / "fonts", ["cjk-bold"])
    if staged:
        assert (tmp_path / "fonts" / staged["cjk-bold"]).exists()
        out = render.subset_font(str(tmp_path / "fonts" / staged["cjk-bold"]), "学习新模式", tmp_path / "s.woff2")
        assert os.path.getsize(out) < os.path.getsize(tmp_path / "fonts" / staged["cjk-bold"])
    assert "@font-face" in render.font_face_css({"CJK": "cjk-700.woff2"})
