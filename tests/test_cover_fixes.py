"""Cover fixes: CJK quote / attribution never drawn with a Latin-only face (tofu), and the cover retouch makes no
geometric warps (face slim / eye enlarge / body slim) unless the config opts in."""
import importlib.util
import pathlib
import sys

import numpy as np
import pytest
from PIL import Image

from vstudio import config, cover

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _has(role):
    try:
        config.font(role)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- font picker
@pytest.mark.parametrize("text,role,want", [
    ("一句金句", "serif-italic", "cjk-serif"),
    ("— 千剪 Reelfold", "serif-italic", "cjk-serif"),
    ("周末，", "serif", "cjk-serif"),
    ("标签", "mono-bold", "cjk-bold"),
    ("标签", "mono", "cjk"),
    ("ひらがな", "serif-italic", "cjk-serif"),
    ("한국어", "serif-italic", "cjk-serif"),
    ("Ship it fast", "serif-italic", "serif-italic"),
    ("", "serif-italic", "serif-italic"),
    ("中文", "cjk-bold", "cjk-bold"),
])
def test_font_role_for_cjk(text, role, want):
    assert cover.font_role_for(text, role) == want


def test_font_role_for_missing_glyph(monkeypatch):
    monkeypatch.setattr(cover, "_codepoints", lambda role: frozenset(map(ord, "abc ")))
    assert cover.font_role_for("abc", "serif-italic") == "serif-italic"
    assert cover.font_role_for("abc ✓", "serif-italic") == "cjk-serif"


@pytest.mark.skipif(not (_has("serif-italic") and _has("cjk")), reason="fonts not installed (./install.sh)")
def test_font_role_for_real_cmap():
    assert cover.font_role_for("Quote, by Ada", "serif-italic") == "serif-italic"
    assert cover._codepoints("serif-italic") is not None
    assert ord("中") not in cover._codepoints("serif-italic")       # the bug: STIX has no CJK
    f = cover.text_font("中文金句", "serif-italic", 30)
    assert "STIX" not in (f.getname()[0] or "")


def test_split_cover_quote_uses_cjk_face(monkeypatch):
    roles = []
    real_fit, real_text_font = cover.fit_font, cover.text_font
    monkeypatch.setattr(cover, "fit_font", lambda text, role, *a, **k: roles.append((text, role)) or
                        real_fit(text, role, *a, **k))
    monkeypatch.setattr(cover, "text_font", lambda text, role, size: roles.append((text, cover.font_role_for(text, role)))
                        or real_text_font(text, role, size))
    photo = Image.new("RGB", (640, 480), (120, 110, 100))
    cover.split_cover(dict(photo=photo, aspect="16:9", face_x=0.5, retouch=None,
                           quote={"text": "把复杂的事讲简单", "by": "— 子芸"}, title={"lines": ["标题"]}))
    got = dict(roles)
    assert got["把复杂的事讲简单"].startswith("cjk")
    assert got["— 子芸"].startswith("cjk")


# ---------------------------------------------------------------- retouch defaults
def test_cover_retouch_has_no_warps():
    for k in ("slim", "eye", "eye_extra", "body"):
        assert cover.COVER_RETOUCH[k] == 0
    assert cover.COVER_RETOUCH["makeup"] > 0


def test_split_cover_retouch_true_passes_no_warps(monkeypatch):
    from vstudio import face as F
    from vstudio import retouch as R
    seen = {}

    class LM:
        def close(self):
            pass

    monkeypatch.setattr(F, "landmarker", lambda *a, **k: LM())
    monkeypatch.setattr(F, "detect", lambda lm, bgr: [])
    monkeypatch.setattr(F, "main_face", lambda faces: {"pts": np.array([[320.0, 240.0]])})
    monkeypatch.setattr(R, "retouch", lambda bgr, f=None, lm=None, **kw: seen.update(kw) or bgr)
    cover.prepare_photo(Image.new("RGB", (640, 480), (120, 110, 100)), retouch=True)
    assert seen and seen["slim"] == 0 and seen["eye"] == 0 and seen["body"] == 0
    seen.clear()
    cover.prepare_photo(Image.new("RGB", (640, 480), (120, 110, 100)), retouch={"slim": 0.05})
    assert seen["slim"] == 0.05 and seen["eye"] == 0                 # explicit opt-in only


def _load_make_cover():
    scripts = ROOT / "workflows" / "promo-recut" / "scripts"
    saved = sys.modules.pop("common", None)                          # other workflows ship a ``common`` too
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("promo_make_cover", scripts / "make_cover.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(scripts))
        sys.modules.pop("common", None)
        if saved is not None:
            sys.modules["common"] = saved


def test_make_cover_default_retouch_no_warps():
    mc = _load_make_cover()
    rt = mc.split_cfg({}, "photo.png", None, False)["retouch"]
    assert rt["slim"] == 0 and rt["eye"] == 0 and rt["body"] == 0 and rt["makeup"] > 0
    rt = mc.split_cfg({"retouch": {"slim": 0.05, "eye": 0.04}}, "photo.png", None, False)["retouch"]
    assert rt["slim"] == 0.05 and rt["eye"] == 0.04 and rt["body"] == 0
    assert mc.split_cfg({"retouch": False}, "photo.png", None, False)["retouch"] is None
    assert mc.split_cfg({}, "photo.png", None, True)["retouch"] is None
