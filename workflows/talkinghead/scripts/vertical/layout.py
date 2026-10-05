"""Canvas geometry for the V-track compositor, derived from a vstudio.platform profile.

    from layout import resolve_profile, Layout
    prof = resolve_profile("xiaohongshu:vertical")      # None -> persona platforms.default, 9:16 ("full")
    L = Layout(prof)                                      # every overlay position compose.py needs

Positions are functions of ``platform.safe_box`` / ``caption_box`` / ``keepouts``. On the measured
小红书 9:16 profile (1080x1920, safe y 240..1660, captions ~1525) they reproduce the original constants
exactly, so the default output is unchanged. Other canvases:
  * 3:4 (1080x1440) and other vertical sizes: the same stack (bar, title, face, panel, captions) re-spaced
    into that safe box;
  * landscape (1920x1080): side layouts - the 记笔记 panel / callouts / PiP sit on the side away from the
    face, circle and card scenes put the picture left and the text column right.
Effect coordinates written in configs (POPS x/y, STAMPS x_left/y_top) are in the 1080x1920 authoring frame;
``Layout.map_point`` moves them relative to the face onto other canvases and clamps them out of the
caption band and button column.
"""
import sys, pathlib; sys.path[:0] = [str(pathlib.Path(__file__).resolve().parents[4] / "lib")]
import numpy as np
from vstudio import platform as P

AUTHOR_W, AUTHOR_H = 1080, 1920                   # config pixel coordinates are authored on this frame
AUTHOR_FACE = (540.0, 860.0, 480.0)               # face (cx, cy, width) the example coordinates assume


def resolve_profile(spec=None, natural="full"):
    """Profile for a config/CLI value like 'xiaohongshu:vertical', 'douyin', 'youtube'. None -> persona
    platforms.default in the workflow's natural orientation ('full' = 9:16 for the V track, falls back to
    the platform's own default orientation when it has no 9:16 canvas)."""
    if spec:
        return P.profile(spec)
    try:
        from vstudio.config import persona
        name = (persona().get("platforms") or {}).get("default") or "xiaohongshu"
    except Exception:
        name = "xiaohongshu"
    try:
        return P.profile(name, natural)
    except KeyError:
        return P.profile(name)


def pop_platform_arg(argv):
    """Remove '--platform X' / '--platform=X' (and '--clean-master') from argv; returns (spec, clean)."""
    spec, clean, out, i = None, False, [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--platform" and i + 1 < len(argv):
            spec = argv[i + 1]; i += 2; continue
        if a.startswith("--platform="):
            spec = a.split("=", 1)[1]; i += 1; continue
        if a == "--clean-master":
            clean = True; i += 1; continue
        out.append(a); i += 1
    argv[:] = out
    return spec, clean


def overlap(a, b):
    """Intersection area of two (x0, y0, x1, y1) rects."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def face_core(box):
    """The part of a face box that must never be covered: brows down to the chin (the forehead may be)."""
    x0, y0, x1, y1 = box
    h = y1 - y0
    return (x0 + 0.08 * (x1 - x0), y0 + 0.18 * h, x1 - 0.08 * (x1 - x0), y1)


def pick(cands, boxes, keep=()):
    """First candidate rect that covers no face core (and no keep-out); else the one covering least.
    cands: [(x0, y0, x1, y1)], boxes: face boxes it must avoid."""
    best, score = None, None
    for c in cands:
        s = sum(overlap(c, face_core(b)) for b in boxes) + sum(overlap(c, k) for k in keep)
        if s <= 0:
            return c
        if score is None or s < score:
            best, score = c, s
    return best


class Layout:
    def __init__(self, prof):
        self.prof = prof
        W, H = self.W, self.H = prof.w, prof.h
        self.portrait = H > W
        self.safe = sx0, sy0, sx1, sy1 = P.safe_box(prof)
        self.cap = P.caption_box(prof)
        self.keep = P.keepouts(prof)
        cx0, cy0, cx1, cy1 = self.cap
        self.legacy = (W, H) == (AUTHOR_W, AUTHOR_H) and (sy0, sy1) == (240, 1660)
        self.k = min(W, H) / 1080.0
        top = sy0
        # progress bars: refined bar centre ~ top + 13, classic track at top + 22
        self.pb_y = top + 10
        self.bar_s = 1.0 if self.portrait else 1.25    # progress-bar scale (a 1080-scaled bar is lost on 16:9)
        self.ui_top = int(self.pb_y + 84 * self.bar_s + 10)   # below the bar + chapter pill
        self.classic_y = top + 22 - 14
        self.classic_x = (sx0 + 10, sx1 - 10) if not self.legacy else (70, 1010)
        # hook title / badge
        self.badge_y = top + 60
        self.title_y = top + 90                    # first line centre (no badge); +60 with a badge
        # subtitles
        self.sub_y = int(round((cy0 + cy1) / 2 - 5))
        self.sub_max_w = cx1 - cx0
        # callouts
        self.callout_xy = (sx0, top + 110)
        self.callout_max_w = min(880, (sx1 - sx0) - 80) if self.portrait else min(760, int((sx1 - sx0) * 0.42))
        # 记笔记 panel
        self.panel_w = min(940, (sx1 - sx0) - 20) if self.portrait else min(760, int((sx1 - sx0) * 0.42))
        # circle-inset list scene
        if self.portrait:
            self.circ_title = (W / 2, top + 132)
            self.tok_x, self.tok_y0, self.tok_dx = W / 2, top + 260, 210
            self.circ_c = (W / 2, cy0 - 320)
            self.circ_R = 290 if H >= 1900 else None   # None: sized per scene from the free height
        else:
            colx = sx0 + (sx1 - sx0) * 0.70
            self.circ_title = (colx, top + 90)
            self.tok_x, self.tok_y0, self.tok_dx = colx, top + 210, 200
            R = int(min(290, (cy0 - top) / 2 - 30))
            self.circ_c = (sx0 + (sx1 - sx0) * 0.27, top + (cy0 - top) / 2)
            self.circ_R = R
        # shrink-to-card scene
        self.card_s = 0.55
        if self.portrait:
            self.card_xy = ((W - int(W * 0.55)) // 2, top + 360)
            self.card_title = (W / 2, top + 112)
            self.card_lines = (W / 2, top + 192)
            self.card_col_w = sx1 - sx0
        else:
            cw, ch = int(W * 0.55), int(H * 0.55)
            self.card_xy = (sx0 + 20, max(top, (cy0 + top) // 2 - ch // 2))
            colx = (sx0 + 20 + cw + sx1) / 2
            self.card_title = (colx, self.card_xy[1] + 70)
            self.card_lines = (colx, self.card_xy[1] + 160)
            self.card_col_w = sx1 - (sx0 + 40 + cw)

    # ------------------------------------------------------------------ circle radius on short canvases
    def circle_R(self, n_rows):
        if self.circ_R:
            return self.circ_R
        free = self.cap[1] - 30 - (self.tok_y0 + max(1, n_rows) * 108 - 54) - 20
        return int(np.clip(free / 2, 160, 290))

    def circle_center(self, R):
        if not self.portrait or self.circ_R:
            return self.circ_c
        return (self.W / 2, self.cap[1] - 30 - R)

    # ------------------------------------------------------------------ allowed area for on-picture elements
    def content_box(self):
        """Safe box minus the caption band (elements on the picture must end above the captions)."""
        sx0, sy0, sx1, sy1 = self.safe
        return (sx0, max(sy0 + 60, self.ui_top), sx1, min(sy1, self.cap[1] - 10))

    def clamp_rect(self, x, y, w, h):
        """Top-left (x, y) moved so a w x h rect sits inside content_box and left of any button column."""
        bx0, by0, bx1, by1 = self.content_box()
        for kx0, ky0, kx1, ky1 in self.keep:
            if y + h > ky0:
                bx1 = min(bx1, kx0)
        x = min(max(x, bx0), max(bx0, bx1 - w))
        y = min(max(y, by0), max(by0, by1 - h))
        return x, y

    def map_point(self, x, y, face):
        """Authoring-frame (1080x1920) point -> this canvas, relative to the face (cx, cy, w)."""
        if self.legacy:
            return x, y
        fx, fy, fw = face
        k = float(np.clip(fw / AUTHOR_FACE[2], 0.6, 1.4))
        return fx + (x - AUTHOR_FACE[0]) * k, fy + (y - AUTHOR_FACE[1]) * k

    # ------------------------------------------------------------------ face-aware candidates
    def block_cands(self, rect):
        """Hook-title block (x0, y0, x1, y1) at its default top position, then the same block moved to sit
        just above the captions (used when the default would cover the eyes)."""
        x0, y0, x1, y1 = rect
        dy = (self.cap[1] - 20 - y1)
        return [rect, (x0, y0 + dy, x1, y1 + dy)]

    def side_cands(self, w, h, top=None):
        """Rects of w x h for callouts / PiP / panels: corners and sides of the content box."""
        bx0, by0, bx1, by1 = self.content_box()
        t = by0 + 40 if top is None else top
        rx = bx1 - w
        for kx0, ky0, kx1, ky1 in self.keep:
            rx = min(rx, kx0 - w) if by1 > ky0 else rx
        ys = [t, (t + by1 - h) / 2, by1 - h]
        out = []
        for y in ys:
            out += [(bx0, y, bx0 + w, y + h), (max(bx0, rx), y, max(bx0, rx) + w, y + h)]
        return out


def h_track_geo(prof):
    """Overlay geometry of the H track (1920x1080 剪映 export, notes-board) from a horizontal profile.
    小红书 horizontal (the default) reproduces the original constants: bar strip at y 1000, x 80..1840,
    badge (70, 44), callouts (70, 70), panels (66, 86). The 4:3 feed crop only matters for the cover
    (make_cover.py judges cover43.png); the video itself plays full-frame."""
    if prof.h > prof.w:
        raise SystemExit(f"{prof.key} is vertical: the H track renders 16:9. Render it, then "
                         f"`python -m vstudio.export OUT.mp4 --platforms {prof.key}` (face-tracked reframe).")
    sx0, sy0, sx1, sy1 = P.safe_box(prof)
    m = min(sx0, 96) - 26
    return dict(W=prof.w, H=prof.h, bar_y=sy1 - 20, bar_x=m + 10, bar_w=prof.w - 2 * (m + 10),
                badge=(m, max(44, sy0 - 16)), callout=(m, sy0 + 10), panel=(m - 4, sy0 + 26))
