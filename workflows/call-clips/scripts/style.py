"""Shared look for every call-clips renderer: fonts (via vstudio font roles),
colours (via the persona), the labels drawn on frame furniture, and the one
compositing call they all use.

Every renderer imports from here so the vertical, trio and landscape layouts
stay one design and nothing points at a system font. The furniture itself
(chips, badges, node cards, 记笔记 panels, subtitle strips) is drawn by
vstudio.overlays / vstudio.draw.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio import draw
from vstudio.config import persona


def _hex(h, default):
    try:
        return draw.rgb(h)
    except (ValueError, TypeError):
        return default


_P = persona()
_B = _P.get("brand") or {}
_CC = _P.get("call_clips") or {}

# frame accent: rules, node-card border, chip outline, accent title runs
TEAL = _hex(_CC.get("frame_accent", "#2DD4BF"), (45, 212, 191))
try:                                                             # accent / highlight follow vstudio.theme
    from vstudio.draw import brand as _brand
    _BR = _brand()
except Exception:  # noqa: BLE001
    _BR = {}
RED = tuple(_BR.get("accent") or _hex(_B.get("accent", "#FF2442"), (255, 36, 66)))       # 记笔记 header, hook badge
YEL = tuple(_BR.get("highlight") or _hex(_B.get("highlight", "#FFD60A"), (255, 214, 10)))  # 记笔记 tag, thumb accent
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


# overlays theme for the teal frame furniture (node cards use only "accent")
FRAME_THEME = {"accent": TEAL}


def font(size, bold=True):
    """CJK font at `size` px: role cjk-bold or cjk (Noto Sans SC by default), cached."""
    return draw.load_font("cjk-bold" if bold else "cjk", int(size))


def alpha_paste(dst_bgr, rgba, cx, cy, opacity=1.0):
    """Composite an RGBA overlay (numpy or PIL) onto a BGR frame, CENTRED at (cx, cy), clipped."""
    draw.alpha_paste(dst_bgr, rgba, (cx, cy), opacity=opacity, center=True, bgr=True)


def frame_at(video, t):
    """BGR frame of `video` at second t, frame-accurate (vstudio.media.grab_frame
    pre-rolls and decodes forward; a plain seek on a sparse-keyframe call
    recording lands seconds off). Exits if the still cannot be read."""
    import os, tempfile
    import cv2
    from vstudio import media
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "f.png")
        try:
            media.grab_frame(video, max(0.0, float(t)), p)
        except media.FFmpegError as e:
            raise SystemExit(f"could not read a still at {t}s: {e}")
        fr = cv2.imread(p)
    if fr is None:
        raise SystemExit(f"could not read a still at {t}s")
    return fr
