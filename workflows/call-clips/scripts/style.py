"""Shared look for every call-clips renderer: fonts (via vstudio font roles),
colours (via the persona) and the labels drawn on frame furniture.

Every renderer imports from here so the vertical, trio and landscape layouts
stay one design and nothing points at a system font.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from functools import lru_cache

from PIL import ImageFont

from vstudio.config import font as font_path, persona


def _hex(h, default):
    try:
        h = str(h).lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, TypeError):
        return default


_P = persona()
_B = _P.get("brand") or {}
_CC = _P.get("call_clips") or {}

# frame accent: rules, node-card border, chip outline, accent title runs
TEAL = _hex(_CC.get("frame_accent", "#2DD4BF"), (45, 212, 191))
RED = _hex(_B.get("accent", "#FF2442"), (255, 36, 66))          # 记笔记 header, hook badge
YEL = _hex(_B.get("highlight", "#FFD60A"), (255, 214, 10))      # 记笔记 tag, thumb accent
DIM = (156, 163, 175)
WHITE = (255, 255, 255)

# on-frame copy; override per creator under call_clips.labels in persona.local.yaml
_L = _CC.get("labels") or {}
HOOK_BADGE = _L.get("hook_badge", "高光预告 · 完整版在下面")
HOOK_BADGE_LANDSCAPE = _L.get("hook_badge_landscape", "高光预告 · HIGHLIGHTS")
NODE_EYEBROW = _L.get("node_eyebrow", "接下来")
NOTE_TAG = _L.get("note_tag", "记笔记 ↓")
GUEST_DEFAULT = _L.get("guest", "Guest")
HOST_DEFAULT = _L.get("host", "Host")


@lru_cache(maxsize=None)
def font(size, bold=True):
    """CJK font at `size` px: role cjk-bold or cjk (Noto Sans SC by default)."""
    return ImageFont.truetype(font_path("cjk-bold" if bold else "cjk"), int(size))
