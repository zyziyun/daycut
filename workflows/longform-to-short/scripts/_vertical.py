"""Vertical (3:4 / 9:16) layouts for lecture slices cut from a horizontal screen-share recording.

Used by make_vertical.py. Everything is drawn from explicit source rectangles, so nothing outside the
configured screen region (geometry crop spans = shared page without browser chrome / bookmark bar) or
the configured speaker region can ever reach the frame; ``vertical.exclude`` rects are painted out of the
source before any crop as a second guard (participant tiles, name tags).

Layouts (per timeline item; content area = safe-box top .. caption-box top of the target canvas; by default
the screen stops above the caption box, so captions sit in their own lower band and never over the page text -
``vertical.split.screen_to: frame`` restores the screen running under the captions behind a scrim):
  split     speaker band on top (face-tracked crop of the speaker cam tile, vstudio.reframe face mode) and
            the screen below. No speaker region / no face found -> a title band (series + current chapter)
            instead: a camera-less screen share never shows the participant tiles.
  screen    the whole content area is a crop of the screen that follows the content: frame-difference
            activity (pointer moves, selections, typing, newly revealed blocks; the largest change inside the main
            text block wins), code-zoom windows (zoom_windows.json) and the first text block of a new page;
            scrolls (phase correlation) and transient editor popups / context menus (a box that appears and then
            vanishes, the page under it unchanged) hold the camera, and popups are masked with the page as it was
            just before (``popups: mask | hold | off``); camera = vstudio.reframe.follow (One Euro + a small dead
            zone + eased, speed-limited pan; page switches cut, never pan). The zoom never upscales the source
            beyond ``max_upscale`` (2.0: more only blurs a 720p share) - a smaller text line shows a tighter
            region at that scale instead; the upscale is Lanczos + a light unsharp mask (``sharpen``).
  speaker   the whole content area is the speaker crop.
  pad-blur  the whole screen region fitted to the width over a blurred, dimmed copy.
"""
import math
import os
import re
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw

import _lfc
from vstudio import draw, media
from vstudio import platform as PF
from vstudio import reframe as R

MODES = ("split", "screen", "speaker", "pad-blur")
SCREEN_DEFAULTS = dict(min_scale=1.6, max_scale=3.0, sample_hz=4.0, change_luma=24, min_change_px=12,
                       analysis_w=480, page_change=0.45, follow="content", ink=40, headroom=0.12,
                       min_text_px=28, max_upscale=2.0, sharpen=0.6, popups="mask", popup_min_frac=0.02,
                       popup_max_s=20.0, scroll_min_px=2.0)
# split / screen layout: a slim title band on top, the screen in all the space down to the caption box, the
# captions in their own lower band (no dark fade over the page). screen_to="frame" runs the screen on under the
# captions and the platform UI, dimmed there by a scrim (the first demo round's layout).
SPLIT_DEFAULTS = dict(speaker_frac=0.40, band_frac=0.16, gap=10, screen_to="caption", scrim=0.5)
CAMERA = dict(R.DEFAULTS, dead_zone=0.04, settle=0.01, gain=2.5, max_speed=0.55, max_accel=1.0,
              min_cutoff=0.4, beta=0.4)


def even(v):
    return int(v) // 2 * 2


# ----------------------------------------------------------------------------------- layout
def layout(profiles, gap=10):
    """Shared layout for targets on the same canvas: the most conservative safe / caption boxes."""
    W, H = profiles[0].w, profiles[0].h
    safes = [PF.safe_box(p) for p in profiles]
    caps = [PF.caption_box(p) for p in profiles]
    safe = (max(s[0] for s in safes), max(s[1] for s in safes), min(s[2] for s in safes), min(s[3] for s in safes))
    cap = (max(c[0] for c in caps), min(c[1] for c in caps), min(c[2] for c in caps), max(c[3] for c in caps))
    content = (0, even(safe[1]), W, even(cap[1] - gap))
    return dict(W=W, H=H, safe=safe, caption=cap, content=content, gap=gap)


def boxes(L, mode, band, speaker_frac=0.40, band_frac=0.16, screen_to="caption"):
    """{'screen': box, 'speaker': box, 'band': box} (x0, y0, x1, y1) for one item.
    screen_to "frame": the screen box of split / screen layouts runs to the canvas bottom (the part under the
    caption box is scrimmed, see ``visible_h``); "caption": it stops at the content bottom (above the captions)."""
    x0, y0, x1, y1 = L["content"]
    sy1 = L["H"] if screen_to == "frame" else y1
    if mode == "pad-blur":
        return {"screen": (x0, y0, x1, y1)}
    if mode == "screen":
        return {"screen": (x0, y0, x1, sy1)}
    if mode == "speaker":
        return {"speaker": (x0, y0, x1, y1)} if band == "speaker" else {"band": (x0, y0, x1, y1)}
    frac = speaker_frac if band == "speaker" else band_frac
    yb = y0 + even((y1 - y0) * frac)
    top = {"speaker": (x0, y0, x1, yb)} if band == "speaker" else {"band": (x0, y0, x1, yb)}
    return dict(top, screen=(x0, yb + 6, x1, sy1))


def visible_h(L, box):
    """Height of the part of a screen box above the caption box (what the crop must keep readable)."""
    return max(2, min(box[3], L["content"][3]) - box[1])


def scrim(L, box, draw_h, strength=0.5, ramp=72):
    """Per-row multipliers (draw_h,) dimming the screen under the caption box so captions stay readable
    (1.0 above the content bottom, easing to 1 - strength over ``ramp`` px)."""
    y = np.arange(draw_h) + box[1]
    t = np.clip((y - (L["content"][3] - ramp // 2)) / float(ramp), 0.0, 1.0)
    return (1.0 - strength * (t * t * (3 - 2 * t))).astype(np.float32)


# ----------------------------------------------------------------------------------- decoding
def decode_cmd(src, t0, t1, speed, fps, vf_extra="", pix="bgr24"):
    vf = f"setpts=PTS/{speed},fps={fps}" + (f",{vf_extra}" if vf_extra else "")
    return [media.ffmpeg_bin(), "-v", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", os.fspath(src),
            "-map", "0:v:0", "-vf", vf, "-f", "rawvideo", "-pix_fmt", pix, "-"]


def frames(cmd, w, h, ch=3):
    """Iterate decoded raw frames (h, w, ch) from an ffmpeg command."""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = w * h * ch
    try:
        while True:
            buf = p.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape((h, w, ch) if ch > 1 else (h, w))
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def paint_out(fr, excludes, color=(20, 20, 20)):
    """Copy of fr with every exclude rect filled (privacy guard)."""
    if not excludes:
        return fr
    fr = fr.copy()
    H, W = fr.shape[:2]
    for x0, y0, x1, y1 in excludes:
        fr[max(0, int(y0)):min(H, int(y1)), max(0, int(x0)):min(W, int(x1))] = color
    return fr


def overlaps(rect, excludes):
    x, y, w, h = rect
    return any(x < ex1 and x + w > ex0 and y < ey1 and y + h > ey0 for ex0, ey0, ex1, ey1 in excludes)


# ----------------------------------------------------------------------------------- screen tracking
def main_block(ink, o=SCREEN_DEFAULTS):
    """(x0, x1) in analysis px of the dominant text block: columns of ink (border / separator lines, i.e.
    near-solid columns, removed), runs merged across small gaps, the run with the most ink wins."""
    col = ink.mean(axis=(0, 1)).astype(np.float64)
    if col.sum() <= 0:
        return None
    col[col > 0.85] = 0.0                                    # 1-px panel borders / scrollbars
    on = col > max(0.004, 0.03 * col.max())
    w = len(col)
    gap = max(3, int(w * 0.02))
    runs, i = [], 0
    while i < w:
        if on[i]:
            j = i
            while j < w and (on[j] or (j + gap < w and on[j:j + gap + 1].any())):
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    if not runs:
        return None
    a, b = max(runs, key=lambda r: col[r[0]:r[1]].sum())
    return float(a), float(b)


def max_zoom(o=SCREEN_DEFAULTS):
    """The largest source -> canvas scale: max_scale, never above max_upscale (upscaling a screen recording
    further only blurs it; a tighter region at this scale reads better)."""
    up = o.get("max_upscale")
    return min(o["max_scale"], float(up)) if up else o["max_scale"]


def screen_size(region, box, content_w=None, o=SCREEN_DEFAULTS, need_scale=None):
    """Source crop (cw, ch, draw_h) for the screen box inside region: as tight as the content column allows,
    scale (box_w / cw) at least max(min_scale, need_scale) (the readable-text scale) and at most max_scale,
    never larger than the region. draw_h = the box height normally; when the region is too short to fill a tall
    box at max_scale the crop takes the whole region height and draw_h < box height (the screen is drawn at the
    top of the box: the leftover is at the bottom, under the captions / platform UI)."""
    rx0, ry0, rx1, ry1 = region
    rw, rh = rx1 - rx0, ry1 - ry0
    bw, bh = box[2] - box[0], box[3] - box[1]
    a = bw / bh
    top = max_zoom(o)
    lo = min(max(o["min_scale"], need_scale or 0.0), top)
    want = (content_w * 1.08) if content_w else rw
    want = min(max(want, bw / top), bw / lo)
    cw = min(want, rw, rh * a)
    if cw >= min(bw / top, rw) - 1e-6:
        return cw, cw / a, bh
    cw = min(bw / top, rw)                        # region too short for this box: cap the zoom, shorten
    ch = min(rh, cw / a)
    return cw, ch, min(bh, even(ch * bw / cw))


def text_line_px(gray, x0=0, x1=None, ink=40):
    """Median ink height (px) of the text lines in a full-resolution grey frame (columns x0..x1), or None."""
    g = gray[:, int(x0):int(x1) if x1 else None].astype(np.int16)
    if g.size == 0:
        return None
    on = (np.abs(g - np.median(g)) > ink).mean(axis=1) > 0.004
    runs, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and on[j]:
                j += 1
            runs.append(j - i)
            i = j
        else:
            i += 1
    runs = [r for r in runs if 3 <= r <= 80]
    return float(np.median(runs)) if len(runs) >= 3 else None


def detect_popups(stack, o=SCREEN_DEFAULTS, hz=4.0):
    """Transient editor popups / context menus in analysis frames ``stack`` (T, h, w int16 grey): a box that
    appears (possibly fading in over two samples), hides the page text under it (not a selection tint: the text
    edges under a highlight stay) and shows items of its own, and vanishes within ``popup_max_s`` with the page
    under it back as it was. One still showing when the window ends is reported ``open`` (never masked).
    -> [dict(j0 first sample showing it, j1 first sample without it, box (x0, y0, x1, y1) analysis px, frac
    [, open])]; the clean page is sample j0 - 1."""
    T = len(stack)
    if T < 3:
        return []
    ah, aw = stack.shape[1:]
    thr, ink = o["change_luma"], o["ink"]
    horizon = max(1, int(round(o["popup_max_s"] * hz)))

    def differs(a_, b_, x, y, w, h):
        return float(np.mean(np.abs(stack[a_, y:y + h, x:x + w] - stack[b_, y:y + h, x:x + w]) > thr))

    def extent(r, j1, x, y, w, h):
        """Full box: everything that differs from the clean page r while it shows (it grows / animates in), the
        components touching the first box."""
        um = (np.abs(stack[r + 1:j1] - stack[r][None]) > thr).any(axis=0).astype(np.uint8)
        um = cv2.dilate(um, np.ones((9, 9), np.uint8))
        nu, _, su, _ = cv2.connectedComponentsWithStats(um, connectivity=8)
        X0, Y0, X1, Y1 = x, y, x + w, y + h
        for q in range(1, nu):
            qx, qy, qw, qh = (int(v) for v in su[q, :4])
            if qx < x + w and x < qx + qw and qy < y + h and y < qy + qh:
                X0, Y0, X1, Y1 = min(X0, qx), min(Y0, qy), max(X1, qx + qw), max(Y1, qy + qh)
        return (X0, Y0, X1, Y1)

    def inside(bx, j):
        return any(p["box"][0] <= bx[0] + bx[2] / 2 <= p["box"][2] and p["box"][1] <= bx[1] + bx[3] / 2 <= p["box"][3]
                   and p["j0"] <= j < p["j1"] for p in out)
    out, j = [], 1
    while j < T - 1:
        d = np.abs(stack[j] - stack[j - 1]) > thr
        frac = float(d.mean())
        if frac < o["popup_min_frac"] * 0.25 or frac > o["page_change"]:
            j += 1
            continue
        m = cv2.dilate(d.astype(np.uint8), np.ones((7, 7), np.uint8))
        n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        nxt = j + 1
        for i in range(1, n):
            x, y, w, h = (int(v) for v in st[i, :4])
            if w * h < o["popup_min_frac"] * aw * ah or w < 0.04 * aw or h < 0.04 * ah or w * h > 0.8 * aw * ah:
                continue
            if inside((x, y, w, h), j):
                continue                                   # the popup already found, still animating
            r = j - 1                                      # the clean page: one more sample back when it faded in
            if j >= 2 and differs(j - 1, j - 2, x, y, w, h) > 0.01:
                r = j - 2
            ref, cur = stack[r, y:y + h, x:x + w], stack[j, y:y + h, x:x + w]
            if float(np.mean(np.abs(cur - ref) > thr)) < 0.08:
                continue
            ir = np.abs(ref - np.median(ref)) > ink           # page text under the box
            ic = np.abs(cur - np.median(cur)) > ink
            if ir.sum() > 0 and (ir & ic).sum() / ir.sum() > 0.6:
                continue                                   # the text is still there: a highlight, not a popup
            gone = next((j2 for j2 in range(j + 1, min(T, j + horizon + 1))
                         if min(differs(j2, r, x, y, w, h), differs(j2, j - 1, x, y, w, h)) < 0.03), None)
            if gone is None:
                # still there at the end: a popup only if it hid page text AND shows items of its own (typing
                # into empty space hides nothing). Cut off by the end of the clip within popup_max_s -> masked
                # to the end like any transient one; open longer than popup_max_s -> ``open``: left visible
                # (it may be what is being shown) and reported for QC
                if float(ir.mean()) > 0.02 and float(ic.mean()) > 0.02:
                    ends = j + horizon >= T
                    j1 = T if ends else j + horizon + 1
                    bx_ = extent(r, j1, x, y, w, h) if ends else (x, y, x + w, y + h)
                    out.append(dict(j0=r + 1, j1=j1, box=bx_, open=not ends, to_end=ends,
                                    frac=round((bx_[2] - bx_[0]) * (bx_[3] - bx_[1]) / float(aw * ah), 4)))
                continue
            bx_ = extent(r, gone, x, y, w, h)
            out.append(dict(j0=r + 1, j1=gone, box=bx_,
                            frac=round((bx_[2] - bx_[0]) * (bx_[3] - bx_[1]) / float(aw * ah), 4)))
            nxt = max(nxt, gone + 1)
        j = nxt
    return out


def _box_overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def find_popups(stack, o=SCREEN_DEFAULTS, hz=4.0):
    """``detect_popups`` forward, plus a popup already open when the clip starts (it opened before the cut) and
    closing inside it: found running backwards, its clean page is the first sample after it closes
    (``clean_after``). The closing of such a popup looks like an opening to the forward pass (a box changes,
    the page under it "differs" from the popup frame before): that detection would use a popup frame as its
    clean page and paint the popup back over the rest of the clip, so it is dropped."""
    popups = detect_popups(stack, o, hz)
    Tn = len(stack)
    for pp in detect_popups(stack[::-1].copy(), o, hz):
        if not pp.get("to_end"):
            continue
        c = Tn - pp["j0"]                              # forward index of the clean sample after it closes
        popups = [q for q in popups if not (q["j0"] <= c + 1 and _box_overlap(q["box"], pp["box"]))]
        if c <= 0 or any(q["j0"] < c for q in popups):
            continue                                   # only when it closes before anything else opens
        popups.append(dict(j0=0, j1=c, box=pp["box"], frac=pp["frac"], clean_after=c))
    return popups


def analyse_screen(src, t0, t1, speed, fps, n, region, box, zoom_center=None, still=None, o=SCREEN_DEFAULTS,
                   vis_h=None):
    """Per-frame crop rects [x, y, cw, ch] (source px) for the screen box of one timeline item, plus stats
    (stats["draw_h"]: canvas height the crop is drawn at, stats["draw_y"]: its offset below the box top - a region
    too short for the box at the zoom cap is centred in it; stats["popups"]: masked / held
    transient popups with the source rect and frame range ``make_vertical`` paints the clean page into).
    vis_h: height of the box part above the captions; reading start / activity are kept inside that part.
    The zoom is chosen so a text line is >= o["min_text_px"] tall on the canvas (line height measured on a
    full-resolution frame), within min_scale..max_zoom (max_scale capped by max_upscale): text that would need
    more is shown at the cap (stats["text_small"])."""
    rx0, ry0, rx1, ry1 = [int(v) for v in region]
    rw, rh = rx1 - rx0, ry1 - ry0
    k = min(1.0, o["analysis_w"] / rw)
    aw, ah = max(8, int(rw * k) // 2 * 2), max(8, int(rh * k) // 2 * 2)
    hz = min(o["sample_hz"], fps)
    if still is not None:
        g = cv2.cvtColor(cv2.resize(still[ry0:ry1, rx0:rx1], (aw, ah), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        smp = [g]
    else:
        vf = f"crop={rw}:{rh}:{rx0}:{ry0},fps={hz},scale={aw}:{ah}:flags=area"
        smp = list(frames(decode_cmd(src, t0, t1, speed, fps, vf, "gray"), aw, ah, 1))
    if not smp:
        smp = [np.full((ah, aw), 255, np.uint8)]
    stack = np.stack(smp).astype(np.int16)
    bg = np.median(stack.reshape(len(smp), -1), axis=1)[:, None, None]
    ink = np.abs(stack - bg) > o["ink"]
    blk = main_block(ink, o)
    cx0, cx1 = blk if blk else (0.0, float(aw))
    content_w = (cx1 - cx0) / k
    if still is not None:
        full = cv2.cvtColor(still[ry0:ry1, rx0:rx1], cv2.COLOR_BGR2GRAY)
    else:
        tm_ = t0 + (t1 - t0) * 0.5
        vf1 = f"crop={rw}:{rh}:{rx0}:{ry0}"
        g1 = frames(decode_cmd(src, tm_, min(t1, tm_ + 1.0), 1.0, fps, vf1, "gray"), rw, rh, 1)
        full = next(g1, None)
        g1.close()
    line_px = text_line_px(full, cx0 / k, cx1 / k, o["ink"]) if full is not None else None
    need = (o["min_text_px"] / line_px) if (line_px and o.get("min_text_px")) else None
    cw, ch, draw_h = screen_size(region, box, content_w if o["follow"] == "content" else None, o, need)
    f = min(1.0, (vis_h or draw_h) / draw_h)          # visible fraction of the crop (above the captions)
    bx0, bx1 = rx0 + cx0 / k, rx0 + cx1 / k            # main text block (source px)
    margin = 0.04 * cw
    fixed_x = content_w <= cw * 1.02

    def reading_start(m):
        rows = np.where(m[:, int(cx0):max(int(cx0) + 1, int(cx1))].mean(axis=1) > 0.01)[0]
        y = (rows[0] / k + ry0) if len(rows) else ry0
        return y + ch * f * (0.5 - o["headroom"])

    def x_for(ax):
        """Crop centre x: the main block centred if it fits, else line starts kept visible near the activity."""
        if fixed_x:
            return (bx0 + bx1) / 2
        left = min(max(bx0 - margin, ax - 0.9 * cw), ax - 0.1 * cw)
        return left + cw / 2

    step = fps / hz
    popups = []
    if (o.get("popups") or "off") != "off" and still is None:
        popups = find_popups(stack, o, hz)
    held = set()
    for pp in popups:                                  # the popup and its vanishing: never a camera target
        if not pp.get("open"):                         # (one that stays open may be what is shown: follow)
            held |= set(range(pp["j0"], pp["j1"] + 1))
    pts, cuts, n_scroll, n_act = {}, [], 0, 0
    tx, ty = x_for(bx0), reading_start(ink[0])
    if zoom_center is not None:
        tx, ty = zoom_center
    a0, a1 = int(cx0), max(int(cx0) + 1, int(cx1))
    win = cv2.createHanningWindow((aw, ah), cv2.CV_32F)
    for j in range(len(smp)):
        if j > 0:
            d = np.abs(stack[j] - stack[j - 1]) > o["change_luma"]
            frac = float(d.mean())
            if frac > o["page_change"]:
                cuts.append(int(round(j * step)))
                ty, tx = reading_start(ink[j]), x_for(bx0)
            elif zoom_center is None and j not in held:
                (sx, sy), resp = cv2.phaseCorrelate(stack[j - 1].astype(np.float32), stack[j].astype(np.float32), win)
                if frac > 0.02 and resp > 0.25 and abs(sy) >= o["scroll_min_px"] and abs(sx) < 1.0:
                    ty -= sy / k                       # scroll: stay on the text that was being read
                    n_scroll += 1
                else:
                    dm = d[:, a0:a1].astype(np.uint8)  # activity inside the main block: pointer, selection, typing
                    nc, lab, st, cen = cv2.connectedComponentsWithStats(dm, connectivity=8)
                    keep = [i for i in range(1, nc) if st[i, cv2.CC_STAT_AREA] >= o["min_change_px"]]
                    # where something NEW is marked (a highlight / text / the pointer arriving: darker on a light
                    # page), not where the old mark went away
                    sd = (stack[j] - stack[j - 1])[:, a0:a1]
                    pol = -1.0 if float(bg[j].item()) > 128 else 1.0
                    new = [i for i in keep if pol * float(sd[lab == i].mean()) > 0]
                    keep = new or keep
                    if keep:
                        wts = np.array([st[i, cv2.CC_STAT_AREA] for i in keep], float)
                        cy = float(np.average([cen[i][1] for i in keep], weights=wts))
                        cxx = float(np.average([cen[i][0] for i in keep], weights=wts))
                        ty = cy / k + ry0
                        tx = x_for(rx0 + (cxx + a0) / k)
                        n_act += 1
        pts[int(round(j * step))] = (tx, ty)
    # per-frame targets -> crop top-left, followed per shot by the virtual camera
    idx = sorted(pts)
    xs = np.interp(np.arange(n), idx, [pts[i][0] for i in idx]) - cw / 2
    ys = np.interp(np.arange(n), idx, [pts[i][1] for i in idx]) - ch * f / 2   # target -> centre of visible part
    bounds = [0] + [c for c in sorted(set(cuts)) if 0 < c < n] + [n]
    px, py = [], []
    for a, b in zip(bounds, bounds[1:]):
        px += R.follow(list(xs[a:b]), fps, cw, CAMERA)
        py += R.follow(list(ys[a:b]), fps, ch, CAMERA)
    rects = [[min(max(x, rx0), rx1 - cw), min(max(y, ry0), ry1 - ch), cw, ch] for x, y in zip(px, py)]
    pop = []
    for pp in popups:
        x0, y0, x1, y1 = pp["box"]
        if pp.get("clean_after") is not None:          # open from the clip start: the clean page comes after it
            pad = 10
            sr = [max(rx0, int(rx0 + x0 / k) - pad), max(ry0, int(ry0 + y0 / k) - pad),
                  min(rx1, int(np.ceil(rx0 + x1 / k)) + pad), min(ry1, int(np.ceil(ry0 + y1 / k)) + pad)]
            cf = min(n - 1, int(round((pp["clean_after"] + 1) * step)))   # one sample on: past any fade-out
            pop.append(dict(clean=cf, f0=0, f1=cf, rect=sr, future=True, open=False,
                            cover=round(min(1.0, (sr[2] - sr[0]) * (sr[3] - sr[1]) / float(cw * ch)), 3),
                            dur=round(cf / fps, 2), masked=o.get("popups") == "mask"))
            continue
        pad = 10                                       # popup shadows reach past the detected box
        sr = [max(rx0, int(rx0 + x0 / k) - pad), max(ry0, int(ry0 + y0 / k) - pad),
              min(rx1, int(np.ceil(rx0 + x1 / k)) + pad), min(ry1, int(np.ceil(ry0 + y1 / k)) + pad)]
        f0, f1 = max(0, int(round((pp["j0"] - 1) * step))), min(n, int(round(pp["j1"] * step)))
        cover = (sr[2] - sr[0]) * (sr[3] - sr[1]) / float(cw * ch)
        pop.append(dict(clean=f0, f0=f0 + 1, f1=f1, rect=sr, cover=round(min(1.0, cover), 3),
                        dur=round((f1 - f0) / fps, 2), open=bool(pp.get("open")),
                        masked=o.get("popups") == "mask" and not pp.get("open")))
    text_px = line_px and line_px * (box[2] - box[0]) / cw
    stats = dict(scale=round((box[2] - box[0]) / cw, 3), content_w=round(content_w, 1), cuts=len(bounds) - 2,
                 fixed_x=bool(fixed_x), draw_h=int(draw_h), draw_y=even(max(0, (box[3] - box[1]) - int(draw_h)) // 2), line_px=line_px and round(line_px, 1),
                 text_px=text_px and round(text_px, 1),
                 text_small=bool(text_px and o.get("min_text_px") and text_px < o["min_text_px"] - 0.5),
                 max_zoom=round(max_zoom(o), 3), popups=pop, scrolls=n_scroll, activity=n_act,
                 **R.path_stats(rects, fps, bounds[1:-1]))
    return rects, stats


def mask_popups(fr, i, popups, clean):
    """Paint the clean page (``clean[p["clean"]]``: the frame just before the popup, or for one open from the clip
    start (``future``) the first frame after it closes, decoded ahead by the caller) over every popup showing at
    frame ``i``. ``clean``: {frame index: frame} kept by the caller."""
    for p in popups or ():
        if p.get("masked") and p["f0"] <= i < p["f1"] and p["clean"] in clean:
            x0, y0, x1, y1 = p["rect"]
            fr = fr.copy() if not fr.flags.writeable else fr
            fr[y0:y1, x0:x1] = clean[p["clean"]][y0:y1, x0:x1]
    return fr


# ----------------------------------------------------------------------------------- output popup scan
SCAN_DEFAULTS = dict(hz=2.0, analysis_w=360, edge_s=0.25, min_frac=0.01)


def _stabilise(stack):
    """Align every sample of a (T, h, w) int16 stack to the first one: the screen crop pans (one zoom per item,
    so a pan is a translation; phase correlation between neighbours, accumulated). Page cuts (low response)
    restart the chain."""
    if len(stack) < 2:
        return stack
    out = [stack[0]]
    h, w = stack.shape[1:]
    win = cv2.createHanningWindow((w, h), cv2.CV_32F)
    cx = cy = 0.0
    for j in range(1, len(stack)):
        (sx, sy), resp = cv2.phaseCorrelate(stack[j - 1].astype(np.float32), stack[j].astype(np.float32), win)
        if resp > 0.3 and (abs(sx) > 0.5 or abs(sy) > 0.5) and abs(sx) < w / 4 and abs(sy) < h / 4:
            cx, cy = cx + sx, cy + sy
        if abs(cx) < 0.5 and abs(cy) < 0.5:
            out.append(stack[j])
            continue
        M = np.float32([[1, 0, -cx], [0, 1, -cy]])
        out.append(cv2.warpAffine(stack[j].astype(np.float32), M, (w, h), borderMode=cv2.BORDER_REPLICATE)
                   .astype(np.int16))
    return np.stack(out)


def _moved_content(st, p, min_resp=0.35, min_shift=1.5):
    """True when the box of a found 'popup' holds the page content of the frame next to it, only shifted (a
    scroll or a re-flow, e.g. a stale mask pasted over a page that moved): phase correlation of the box between
    the sample just outside the popup and the first one inside finds a clear translation."""
    x0, y0, x1, y1 = [int(v) for v in p["box"]]
    if x1 - x0 < 8 or y1 - y0 < 8:
        return False
    T = len(st)
    a, b = (p["j0"] - 1, p["j0"]) if p["j0"] > 0 else (min(T - 1, p["j1"]), min(T - 1, p["j1"]) - 1)
    if a < 0 or b < 0 or a == b:
        return False
    pa, pb = st[a, y0:y1, x0:x1].astype(np.float32), st[b, y0:y1, x0:x1].astype(np.float32)
    win = cv2.createHanningWindow((x1 - x0, y1 - y0), cv2.CV_32F)
    (sx, sy), resp = cv2.phaseCorrelate(pa, pb, win)
    return resp >= min_resp and math.hypot(sx, sy) >= min_shift


def output_segments(plan, timeline, fps, split=None):
    """Screen boxes of a rendered vertical master in OUTPUT time: [(t0, t1, box (x0, y0, x1, y1) canvas px, item)]
    from plan.json (layout + per-item mode / band) and the timeline (final_t0, source span, speed)."""
    sp = dict(SPLIT_DEFAULTS, **(split or {}))
    L = plan.get("layout") or {}
    out = []
    for rec in plan.get("items") or []:
        k = rec.get("item")
        if rec.get("kind") == "card" or k is None or k >= len(timeline) or not rec.get("screen"):
            continue
        it = timeline[k]
        bx = rec.get("box") or boxes(L, rec.get("mode") or "split", rec.get("band") or "title", sp["speaker_frac"],
                                     sp["band_frac"], sp["screen_to"]).get("screen")
        if not bx:
            continue
        t0 = float(it["final_t0"])
        dur = (rec.get("frames") / float(fps)) if rec.get("frames") else (it["t1"] - it["t0"]) / it.get("speed", 1.0)
        out.append((t0, t0 + dur, [int(v) for v in bx], k))
    return out


def legacy_overlays(cfg_panels, plan, timeline, split=None):
    """Overlay rects [{a, b, rect}] for a plan.json written before make_vertical recorded them: the 记笔记 panels
    of the config (source spans mapped through the timeline), each as the widest box ``vertical_panels`` can
    draw (<= 62 % of the safe width, right-aligned, from the screen top + 16 down to the caption box)."""
    L = plan.get("layout") or {}
    if not L or not cfg_panels:
        return []
    sp = dict(SPLIT_DEFAULTS, **(split or {}))
    sx0, _, sx1, _ = L["safe"]
    top = boxes(L, "split", plan.get("band") or "title", sp["speaker_frac"], sp["band_frac"], sp["screen_to"])["screen"][1]
    pw = int(min(620, (sx1 - sx0) * 0.62))
    rect = [sx1 - pw, top + 16, sx1, L["caption"][1] - 20]
    out = []
    for p in cfg_panels:
        a, b = (float(x) for x in p.get("src") or (0, 0))
        for it in timeline:
            if it.get("kind") == "card" or it.get("t0") is None:
                continue
            lo, hi = max(a, it["t0"]), min(b, it["t1"])
            if hi > lo:
                sp_ = it.get("speed") or 1.0
                out.append(dict(a=it["final_t0"] + (lo - it["t0"]) / sp_, b=it["final_t0"] + (hi - it["t0"]) / sp_,
                                rect=rect))
    return out


def scan_popups(video, segments, overlays=(), caption_top=None, o=SCREEN_DEFAULTS, scan=None):
    """Editor popups / context menus still VISIBLE in a rendered video (the master or an export): the whole
    video is sampled at ``scan.hz`` (2 fps), every screen segment [(t0, t1, box, item)] is cut out of those
    samples (overlay rects [{a, b, rect}] - 记笔记 panels, hook boxes - and the caption band painted flat over
    the whole segment so they never read as a popup), pans are stabilised, and ``detect_popups`` runs forward and
    backward (a popup already open when the segment starts). -> [dict(t, dur, item, box canvas px, cover)] in
    output seconds; QC warns on any longer than ``qc.popup_s`` (1 s)."""
    sc = dict(SCAN_DEFAULTS, **(scan or {}))
    hz = float(sc["hz"])
    info = media.probe(video)
    W, H = int(info["w"]), int(info["h"])
    k = sc["analysis_w"] / float(W)
    aw, ah = even(W * k), even(H * k)
    cmd = [media.ffmpeg_bin(), "-v", "error", "-i", os.fspath(video), "-map", "0:v:0",
           "-vf", f"fps={hz},scale={aw}:{ah}:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    allf = np.stack(list(frames(cmd, aw, ah, 1)) or [np.zeros((ah, aw), np.uint8)]).astype(np.int16)
    oo = dict(o, popup_max_s=1e6, popup_min_frac=sc["min_frac"])
    out = []
    for t0, t1, box, item in segments:
        j0 = int(np.ceil((t0 + sc["edge_s"]) * hz))
        j1 = min(len(allf), int(np.floor((t1 - sc["edge_s"]) * hz)) + 1)
        if j1 - j0 < 3:
            continue
        x0, y0, x1, y1 = [int(round(v * k)) for v in box]
        if caption_top is not None:
            y1 = min(y1, int(caption_top * k))
        if x1 - x0 < 16 or y1 - y0 < 16:
            continue
        st = allf[j0:j1, y0:y1, x0:x1].copy()
        for ov in overlays or ():
            if ov["a"] < t1 and t0 < ov["b"]:
                rx0, ry0, rx1, ry1 = [int(round(v * k)) for v in ov["rect"]]
                st[:, max(0, ry0 - y0):max(0, ry1 - y0), max(0, rx0 - x0):max(0, rx1 - x0)] = 128
        st = _stabilise(st)
        found = [dict(p, j0=p["j0"], j1=p["j1"]) for p in detect_popups(st, oo, hz)]
        T = len(st)
        for p in detect_popups(st[::-1].copy(), oo, hz):
            if p.get("to_end"):
                c = T - p["j0"]
                found = [q for q in found if not (q["j0"] <= c + 1 and _box_overlap(q["box"], p["box"]))]
                found.append(dict(p, j0=0, j1=c))
        for p in found:
            bx0, by0, bx1, by1 = p["box"]
            if (bx1 - bx0) > 0.8 * st.shape[2] or (by1 - by0) < 0.25 * (bx1 - bx0):
                continue                               # page-wide (a pan / page change) or a text strip (typing)
            if _moved_content(st, p):
                continue                               # the page moved / re-flowed under a mask edge: not a popup
            out.append(dict(t=round((j0 + p["j0"]) / hz, 2), item=item,
                            dur=round((min(p["j1"], T) - p["j0"]) / hz, 2), cover=p["frac"],
                            box=[int(x0 / k + bx0 / k), int(y0 / k + by0 / k), int(x0 / k + bx1 / k),
                                 int(y0 / k + by1 / k)], open_end=bool(p.get("to_end"))))
    return sorted(out, key=lambda x: x["t"])


# ----------------------------------------------------------------------------------- static overlay scan
# Persistent UI chrome inside the screen crop - an editor's selection / block menu, a formatting toolbar, a
# floating panel - that stays open over whole items: ``detect_popups`` only sees a box that APPEARS (and vanishes)
# inside one screen segment, so a menu already open when an item starts and still open when it ends reads as page.
# This scan looks for the panel itself in every sample: a card (four thin, faint border lines, a near-uniform
# page-coloured fill, not touching the crop edge - or cut by exactly one side edge), tracked over time, and kept
# when there is evidence that it floats above the page rather than being part of it:
#   shadow   a drop-shadow halo just outside its left / right borders (menus, popovers, toolbars; page boxes such
#            as an input field, a table cell or a code block have a crisp border and nothing outside it)
#   pinned   the page around it changes (scroll, page switch) while the card itself stays pixel-stable
#   appeared / vanished   the card comes / goes between two samples while the page around it stays the same
# A static slide (a bordered box that is always there, no shadow, the page around it unchanged) is never flagged.
OVERLAY_DEFAULTS = dict(hz=2.0, edge_s=0.25, max_w=1080, lo=2.5, hi=60.0, tol=12, min_w=0.12, min_h=0.04,
                        min_cov=0.75, min_fill=0.7,
                        min_halo=1.5, max_area=0.35, min_s=1.0, change_luma=12, ring=24, max_segs=600)


def find_cards(gray, o=None):
    """Card-shaped panels in one grey frame (h, w) of the screen crop. -> [dict(box (x0, y0, x1, y1) px,
    cov (top, bottom, left, right) border coverage, fill (share of page-coloured pixels inside), halo (outer
    shadow on the free vertical sides, luma), hug None | 'left' | 'right' (cut by that crop edge))], nested
    cards folded into the outermost one."""
    o = dict(OVERLAY_DEFAULTS, **(o or {}))
    g = np.asarray(gray, np.float32)
    H, W = g.shape
    if H < 16 or W < 16:
        return []
    bg = float(np.median(g))
    d = (bg - g) if bg >= 128 else (g - bg)          # light page: borders are darker; dark page: lighter
    on = (d >= o["lo"]) & (d <= o["hi"])               # faint (a panel border, a shadow), not a text stroke
    clean = np.abs(d) < o["lo"]
    up, dn, lf, rt = (np.zeros_like(clean) for _ in range(4))
    up[2:], dn[:-2], lf[:, 2:], rt[:, :-2] = clean[:-2], clean[2:], clean[:, :-2], clean[:, 2:]
    k5h, k5v = np.ones((1, 5), np.uint8), np.ones((5, 1), np.uint8)
    th = cv2.morphologyEx((on & (up | dn)).astype(np.uint8), cv2.MORPH_CLOSE, k5h)      # thin horizontal lines
    tv = cv2.morphologyEx((on & (lf | rt)).astype(np.uint8), cv2.MORPH_CLOSE, k5v)      # thin vertical lines
    hcs = np.zeros((H, W + 1), np.int32)
    hcs[:, 1:] = np.cumsum(cv2.dilate(th, np.ones((3, 1), np.uint8)), axis=1)
    vcs = np.zeros((H + 1, W), np.int32)
    vcs[1:] = np.cumsum(cv2.dilate(tv, np.ones((1, 3), np.uint8)), axis=0)
    min_w, min_h = max(48, int(o["min_w"] * W)), max(24, int(o["min_h"] * H))
    pad = np.zeros((H, W + 2), np.int8)
    pad[:, 1:-1] = th
    dd = np.diff(pad, axis=1)
    sy, sx = np.nonzero(dd == 1)
    _, ex = np.nonzero(dd == -1)
    keep = (ex - sx) >= min_w // 2
    sy, sx, ex = sy[keep], sx[keep], ex[keep]
    if len(sy) > o["max_segs"]:                        # a page full of rules / tables: the longest lines only
        top = np.argsort(sx - ex)[:o["max_segs"]]
        top.sort()
        sy, sx, ex = sy[top], sx[top], ex[top]
    tol = int(o["tol"])

    def covh(y, a, b):
        return float(hcs[y, b] - hcs[y, a]) / (b - a) if b > a else 0.0

    def best_v(xc, y0, y1):
        xs = np.arange(max(0, xc - tol), min(W, xc + tol + 1))
        if y1 <= y0 or not len(xs):
            return 0.0, xc
        c = (vcs[y1, xs] - vcs[y0, xs]) / float(y1 - y0)
        i = int(np.argmax(c))
        return float(c[i]), int(xs[i])

    cands = []
    for i in range(len(sy)):
        yt, ta, tb = int(sy[i]), int(sx[i]), int(ex[i])
        m = (sy > yt + min_h) & (np.minimum(ex, tb) - np.maximum(sx, ta) >= 0.5 * np.maximum(ex - sx, tb - ta))
        for j in np.nonzero(m)[0]:
            yb, x0, x1 = int(sy[j]), min(ta, int(sx[j])), max(tb, int(ex[j]))
            if x1 - x0 < min_w or (x1 - x0) * (yb - yt) > o["max_area"] * W * H:
                continue
            r = max(3, int(0.08 * min(x1 - x0, yb - yt)))  # rounded corners: sides measured off the corners
            cl, xl = best_v(x0, yt + r, yb - r)
            cr, xr = best_v(x1 - 1, yt + r, yb - r)
            hug = "left" if x0 <= 2 else ("right" if x1 >= W - 2 else None)
            if hug == "left":
                xl, cl = 0, 1.0
            elif hug == "right":
                xr, cr = W - 1, 1.0
            ct, cb = covh(yt, xl + r, xr - r), covh(yb, xl + r, xr - r)
            if min(ct, cb, cl, cr) < o["min_cov"]:
                continue
            cands.append(dict(box=(xl, yt, xr + 1, yb + 1), cov=(round(ct, 2), round(cb, 2), round(cl, 2),
                                                                 round(cr, 2)), hug=hug, r=r))
    out = []
    for c in sorted(cands, key=lambda c: -(c["box"][2] - c["box"][0]) * (c["box"][3] - c["box"][1])):
        x0, y0, x1, y1 = c["box"]
        if any(k["box"][0] - 4 <= x0 and k["box"][1] - 4 <= y0 and x1 <= k["box"][2] + 4 and y1 <= k["box"][3] + 4
               for k in out):
            continue                                   # a row / field inside a card already kept
        inner = clean[y0 + 4:y1 - 4, x0 + 4:x1 - 4]
        fill = float(inner.mean()) if inner.size else 0.0
        if fill < o["min_fill"]:
            continue                                   # a filled block (code, highlight), not a panel
        ys = slice(y0 + c["r"], y1 - c["r"])
        halos = []
        for side, x, step in (("left", x0, -1), ("right", x1 - 1, 1)):
            if c["hug"] == side:
                continue
            offs = np.arange(-6, 15)
            cols = np.clip(x + step * offs, 0, W - 1)
            prof = np.median(d[ys][:, cols], axis=0)
            pk = int(np.argmax(prof[:13]))             # the border itself: within 6 px of the found side
            band = prof[pk + 2:pk + 9]
            ok = (x + step * (offs[pk] + 8) >= 0) and (x + step * (offs[pk] + 8) < W)
            halos.append(float(np.clip(band, 0, 12).mean()) if ok and len(band) else 0.0)
        out.append(dict(box=c["box"], cov=c["cov"], fill=round(fill, 2), hug=c["hug"],
                        halo=round(min(halos), 2) if halos else 0.0))
    return out


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / float(u) if u > 0 else 0.0


def _ring_diff(a, b, box, s, ring, thr):
    """(inside, around) shares of changed pixels between two small samples for a full-scale box: the card
    (inset 4 px) and a ring ``ring`` px wide around it (from 4 px out: its shadow is not page)."""
    h, w = a.shape
    x0, y0, x1, y1 = [v * s for v in box]
    ch = np.abs(a.astype(np.int16) - b.astype(np.int16)) > thr
    ix0, iy0, ix1, iy1 = int(x0 + 4 * s), int(y0 + 4 * s), int(x1 - 4 * s), int(y1 - 4 * s)
    inner = ch[max(0, iy0):max(0, iy1), max(0, ix0):max(0, ix1)]
    ox0, oy0 = max(0, int(x0 - ring * s)), max(0, int(y0 - ring * s))
    ox1, oy1 = min(w, int(x1 + ring * s)), min(h, int(y1 + ring * s))
    gx0, gy0, gx1, gy1 = int(x0 - 4 * s), int(y0 - 4 * s), int(x1 + 4 * s), int(y1 + 4 * s)
    m = np.zeros_like(ch)
    m[oy0:oy1, ox0:ox1] = True
    m[max(0, gy0):max(0, gy1), max(0, gx0):max(0, gx1)] = False
    return (float(inner.mean()) if inner.size else 0.0), (float(ch[m].mean()) if m.any() else 0.0)


def static_overlays(samples, hz=2.0, o=None):
    """Persistent floating panels in a sequence of screen-crop samples ``[dict(t, key, g)]`` (g: grey crop at
    analysis scale; key: the crop geometry - a card is only followed between samples of the same key).
    -> [dict(t, dur, box crop px, idx (first, last), halo, hug, evidence [shadow | pinned | appeared |
    vanished], items)] for the cards seen >= ``min_s`` with at least one piece of evidence."""
    o = dict(OVERLAY_DEFAULTS, **(o or {}))
    s = 0.25                                           # temporal checks on quarter-size copies
    small, cards, prev = [], [], None
    for smp in samples:
        g = np.asarray(smp["g"])
        sm = cv2.resize(g, (max(4, int(g.shape[1] * s)), max(4, int(g.shape[0] * s))), interpolation=cv2.INTER_AREA)
        if prev is not None and prev[0] == smp["key"] and prev[1].shape == sm.shape and \
                not (np.abs(sm.astype(np.int16) - prev[1].astype(np.int16)) > 6).any():
            cs = prev[2]                               # nothing moved: same cards (static pages are the norm)
        else:
            cs = find_cards(g, o)
        small.append(sm)
        cards.append(cs)
        prev = (smp["key"], sm, cs)
    tracks = []
    for i, cs in enumerate(cards):
        for c in cs:
            best = None
            for tr in tracks:
                j = tr["idx"][-1]
                if i - j > 2 or j == i or samples[j]["key"] != samples[i]["key"]:
                    continue
                v = _iou(tr["boxes"][-1], c["box"])
                if v >= 0.6 and (best is None or v > best[0]):
                    best = (v, tr)
            if best:
                tr = best[1]
                tr["idx"].append(i)
                tr["boxes"].append(c["box"])
                tr["halo"].append(c["halo"])
                tr["hug"].append(c["hug"])
            else:
                tracks.append(dict(idx=[i], boxes=[c["box"]], halo=[c["halo"]], hug=[c["hug"]]))
    thr, ring, step = o["change_luma"], o["ring"], 1.5 / hz
    out = []
    for tr in tracks:
        a, b = tr["idx"][0], tr["idx"][-1]
        dur = samples[b]["t"] - samples[a]["t"] + 1.0 / hz
        if dur < o["min_s"] - 1e-6:
            continue
        box = tuple(int(np.median([bx[k] for bx in tr["boxes"]])) for k in range(4))
        halo = float(np.median(tr["halo"]))
        ev = []
        if halo >= o["min_halo"]:
            ev.append("shadow")
        for i in tr["idx"][1:]:
            inside, around = _ring_diff(small[a], small[i], box, s, ring, thr)
            if inside <= 0.03 and around >= 0.05:
                ev.append("pinned")
                break
        for edge, nb in (("appeared", a - 1), ("vanished", b + 1)):
            if 0 <= nb < len(samples) and samples[nb]["key"] == samples[a]["key"] and \
                    abs(samples[nb]["t"] - samples[a if edge == "appeared" else b]["t"]) <= step:
                inside, around = _ring_diff(small[nb], small[a if edge == "appeared" else b], box, s, ring, thr)
                if inside >= 0.1 and around <= 0.02:
                    ev.append(edge)
        if not ev:
            continue
        hugs = [h for h in tr["hug"] if h]
        out.append(dict(t=round(samples[a]["t"], 2), dur=round(dur, 2), box=box, idx=(a, b), halo=round(halo, 2),
                        hug=max(set(hugs), key=hugs.count) if hugs else None, evidence=ev,
                        items=sorted({samples[i].get("item") for i in tr["idx"]} - {None})))
    merged = []                                        # one panel, several tracks (its outline found differently
    for p in sorted(out, key=lambda x: -x["dur"]):     # frame to frame, a field inside it): fold them together
        x0, y0, x1, y1 = p["box"]
        area = max(1, (x1 - x0) * (y1 - y0))
        for q in merged:
            qx0, qy0, qx1, qy1 = q["box"]
            ix = max(0, min(x1, qx1) - max(x0, qx0)) * max(0, min(y1, qy1) - max(y0, qy0))
            if samples[p["idx"][0]]["key"] == samples[q["idx"][0]]["key"] and ix >= 0.6 * area and \
                    p["t"] <= q["t"] + q["dur"] + 1.0 / hz and q["t"] <= p["t"] + p["dur"] + 1.0 / hz:
                end = max(q["t"] + q["dur"], p["t"] + p["dur"])
                q["t"] = min(q["t"], p["t"])
                q["dur"] = round(end - q["t"], 2)
                q["idx"] = (min(q["idx"][0], p["idx"][0]), max(q["idx"][1], p["idx"][1]))
                q["evidence"] += [e for e in p["evidence"] if e not in q["evidence"]]
                q["items"] = sorted(set(q["items"]) | set(p["items"]))
                break
        else:
            merged.append(dict(p))
    return sorted(merged, key=lambda x: x["t"])


def scan_static_overlays(video, segments, overlays=(), caption_top=None, scan=None):
    """Persistent UI panels (an editor's block / selection menu, a toolbar) still VISIBLE in a rendered video:
    sampled at ``scan.hz`` (2 fps) at up to ``max_w`` px wide (their borders are faint: full scale), every screen
    segment [(t0, t1, box, item)] cut out (overlay rects - 记笔记 panels, hook boxes - and the caption band painted
    with the page colour), then ``static_overlays``. Segments with the same box are followed across cuts (a menu
    left open spans items). -> [dict(t, dur, item, items, box canvas px, cover, evidence, halo, hug)] in output
    seconds; QC warns on each (``screen-overlay-static``)."""
    o = dict(OVERLAY_DEFAULTS, **(scan or {}))
    hz = float(o["hz"])
    info = media.probe(video)
    W, H = int(info["w"]), int(info["h"])
    k = min(1.0, o["max_w"] / float(W))
    aw, ah = even(W * k), even(H * k)
    cmd = [media.ffmpeg_bin(), "-v", "error", "-i", os.fspath(video), "-map", "0:v:0",
           "-vf", f"fps={hz},scale={aw}:{ah}:flags=area", "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    segs = sorted(segments, key=lambda x: x[0])
    samples = []
    for j, fr in enumerate(frames(cmd, aw, ah, 1)):
        t = j / hz
        seg = next((sg for sg in segs if sg[0] + o["edge_s"] <= t <= sg[1] - o["edge_s"]), None)
        if seg is None:
            continue
        t0, t1, box, item = seg
        x0, y0, x1, y1 = [int(round(v * k)) for v in box]
        if caption_top is not None:
            y1 = min(y1, int(caption_top * k))
        if x1 - x0 < 32 or y1 - y0 < 32:
            continue
        g = fr[y0:y1, x0:x1].copy()
        bgv = int(np.median(g))
        for ov in overlays or ():
            if ov["a"] <= t < ov["b"]:
                rx0, ry0, rx1, ry1 = [int(round(v * k)) for v in ov["rect"]]
                g[max(0, ry0 - y0):max(0, ry1 - y0), max(0, rx0 - x0):max(0, rx1 - x0)] = bgv
        samples.append(dict(t=t, key=(x0, y0, x1, y1), g=g, item=item))
    out = []
    for p in static_overlays(samples, hz, o):
        x0, y0, x1, y1 = samples[p["idx"][0]]["key"]
        bx0, by0, bx1, by1 = p["box"]
        out.append(dict(t=p["t"], dur=p["dur"], item=samples[p["idx"][0]]["item"], items=p["items"],
                        box=[int((x0 + bx0) / k), int((y0 + by0) / k), int((x0 + bx1) / k), int((y0 + by1) / k)],
                        cover=round((bx1 - bx0) * (by1 - by0) / float((x1 - x0) * (y1 - y0)), 4),
                        evidence=p["evidence"], halo=p["halo"], hug=p["hug"]))
    return out


# ----------------------------------------------------------------------------------- speaker tracking
def make_detector(kind="mediapipe", color=None, upscale_to=640):
    """reframe-compatible detector(bgr) -> [(x0, y0, x1, y1, talk)]. 'mediapipe' upscales small cam tiles
    (faces in a 260 px tile are too small for the detector otherwise); 'color' tracks a solid marker colour
    (synthetic tests / debugging)."""
    if kind == "color":
        r, g, b = color or (255, 160, 0)

        def det(bgr):
            m = (np.abs(bgr[..., 2].astype(int) - r) < 40) & (np.abs(bgr[..., 1].astype(int) - g) < 40) & \
                (np.abs(bgr[..., 0].astype(int) - b) < 40)
            ys, xs = np.nonzero(m)
            return [] if len(xs) < 20 else [(float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max()), None)]
        det.close = lambda: None
        return det
    from vstudio import face
    lm = face.landmarker(2)

    def det(bgr):
        h, w = bgr.shape[:2]
        s = max(1.0, upscale_to / w)
        img = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC) if s > 1 else bgr
        out = []
        for f in face.detect(lm, np.ascontiguousarray(img)):
            p = f["pts"] / s
            out.append((float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()),
                        face.mouth_gap(f["pts"])))
        return out
    det.close = lm.close
    return det


def plan_speaker(src, t0, t1, speed, fps, region, box, tmp, detector, zoom=1.0, min_hit=0.3):
    """vstudio.reframe face plan of the speaker region (cut to the item's timing) for the speaker box.
    Returns (rects in SOURCE px or None, info)."""
    rx0, ry0, rx1, ry1 = [int(v) for v in region]
    rw, rh = even(rx1 - rx0), even(ry1 - ry0)
    media.run([media.ffmpeg_bin(), "-y", "-v", "error", "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}", "-i", os.fspath(src),
               "-map", "0:v:0", "-vf", f"crop={rw}:{rh}:{rx0}:{ry0},setpts=PTS/{speed},fps={fps}", "-an",
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16", tmp])
    bw, bh = box[2] - box[0], box[3] - box[1]
    safe = (bw * 0.18, bh * 0.08, bw * 0.82, bh * 0.96)
    pl = R.plan(tmp, bw, bh, mode="face", safe=safe, detector=detector, every=max(1, round(fps / 6)),
                zoom=zoom, min_hit=min_hit, fallback="center")
    info = dict(hit_rate=pl.get("hit_rate"), mode_used=pl["mode_used"], stats=pl.get("stats"))
    if pl["mode_used"] != "face":
        return None, info
    return [[x + rx0, y + ry0, w, h] for x, y, w, h in pl["rects"]], info


# ----------------------------------------------------------------------------------- drawing
def warp(fr, rect, size, sharpen=0.0):
    """Crop rect [x, y, w, h] (sub-pixel) of fr scaled to size (w, h). Upscales use Lanczos and, with
    ``sharpen`` > 0, a light unsharp mask (text edges of an upscaled screen recording stay crisp)."""
    x, y, cw, ch = rect
    tw, th = size
    s = tw / cw
    M = np.float32([[s, 0, -x * s], [0, th / ch, -y * th / ch]])
    out = cv2.warpAffine(fr, M, (tw, th), flags=cv2.INTER_LANCZOS4 if s > 1 else cv2.INTER_AREA,
                         borderMode=cv2.BORDER_REPLICATE)
    if sharpen and s > 1.2:
        blur = cv2.GaussianBlur(out, (0, 0), 0.6 * s)
        out = cv2.addWeighted(out, 1.0 + sharpen, blur, -sharpen, 0)
    return out


def pad_blur(fr, region, size, dim=0.6):
    rx0, ry0, rx1, ry1 = [int(v) for v in region]
    crop = fr[ry0:ry1, rx0:rx1]
    tw, th = size
    s = min(tw / crop.shape[1], th / crop.shape[0])
    fw, fh = max(2, int(crop.shape[1] * s)), max(2, int(crop.shape[0] * s))
    small = cv2.resize(crop, (max(8, tw // 12), max(8, th // 12)), interpolation=cv2.INTER_AREA)
    bgi = (cv2.resize(cv2.GaussianBlur(small, (0, 0), 2.2), (tw, th)).astype(np.float32) * dim).astype(np.uint8)
    fg = cv2.resize(crop, (fw, fh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    ox, oy = (tw - fw) // 2, (th - fh) // 2
    bgi[oy:oy + fh, ox:ox + fw] = fg
    return bgi


def pil_bgr(im):
    return cv2.cvtColor(np.asarray(im.convert("RGB")), cv2.COLOR_RGB2BGR)


def title_band(size, eyebrow, title, P, margin, hook=None):
    """Band image (BGR): accent eyebrow + big wrapped title (or the hook lines), left-aligned in the safe width."""
    W, H = size
    im = Image.new("RGB", (W, H), P["bg"])
    d = ImageDraw.Draw(im)
    maxw = W - 2 * margin
    if hook:
        l1, l2 = (list(hook) + [""])[:2]
        f1 = draw.fit_font(l1, "cjk-bold", int(H * 0.30), maxw, min_size=28)
        f2 = draw.fit_font(l2, "cjk-bold", int(H * 0.19), maxw, min_size=22) if l2 else None
        h1 = sum(f1.getmetrics())
        h2 = sum(f2.getmetrics()) if f2 else 0
        y = (H - h1 - h2 - (int(H * 0.06) if f2 else 0)) // 2
        d.text(((W - draw.text_width(l1, f1)) / 2, y), l1, font=f1, fill=P["ink"])
        if f2:
            d.text(((W - draw.text_width(l2, f2)) / 2, y + h1 + int(H * 0.06)), l2, font=f2, fill=P["accent"])
        return pil_bgr(im)
    fe = draw.load_font("cjk-bold", max(18, min(40, int(H * 0.13))))
    size_t = max(26, min(84, int(H * 0.27)))
    while True:
        ft = draw.load_font("cjk-bold", size_t)
        lines = draw.wrap(title or "", ft, maxw, balance=True)
        lh = int(sum(ft.getmetrics()) * 1.08)
        he = sum(fe.getmetrics()) if eyebrow else 0
        if (len(lines) <= 2 and he + int(H * 0.05) + lh * len(lines) <= H * 0.86) or size_t <= 26:
            break
        size_t -= 4
    block = he + (int(H * 0.05) if eyebrow else 0) + lh * len(lines)
    y = (H - block) // 2
    if eyebrow:
        d.text((margin, y), eyebrow, font=fe, fill=P["accent"])
        y += he + int(H * 0.05)
    for ln in lines:
        draw.draw_runs(d, (margin, y), ln, ft, P["ink"] + (255,), P["accent"] + (255,))
        y += lh
    d.rectangle([margin, H - 4, margin + int(maxw * 0.18), H - 1], fill=P["accent"])
    return pil_bgr(im)


def hook_box(lines, width, P):
    """Rounded dark box with the hook lines (RGBA PIL), for layouts without a title band."""
    l1, l2 = (list(lines) + [""])[:2]
    f1 = draw.fit_font(l1, "cjk-bold", 64, width - 80, min_size=30)
    f2 = draw.fit_font(l2, "cjk-bold", 42, width - 80, min_size=22) if l2 else None
    h1, h2 = sum(f1.getmetrics()), (sum(f2.getmetrics()) + 14 if f2 else 0)
    im = draw.rounded_rect((width, h1 + h2 + 56), 26, P["bg"] + (222,))
    d = ImageDraw.Draw(im)
    d.text(((width - draw.text_width(l1, f1)) / 2, 26), l1, font=f1, fill=P["ink"])
    if f2:
        d.text(((width - draw.text_width(l2, f2)) / 2, 26 + h1 + 14), l2, font=f2, fill=P["accent"])
    return im


# ----------------------------------------------------------------------------------- captions
def _join_lines(lines):
    """Wrapped lines back into one caption: CJK lines meet directly, but a latin word on both sides of a break
    keeps its space (用 Claude / Code 来做 -> 用 Claude Code 来做, never ClaudeCode)."""
    out = ""
    for ln in lines:
        ln = ln.strip()
        if out and ln and ord(out[-1]) < 0x2E80 and ord(ln[0]) < 0x2E80 and ln[0] not in ",.!?;:)]%…":
            out += " "
        out += ln
    return out


def relayout_cues(cues, prof, role="cjk-bold"):
    """Split cues so every one fits the profile's caption box in <= max_lines at a size inside its range
    (vstudio.platform.fit_text_size); time is shared in proportion to text length."""
    from vstudio.subs import Cue, balanced_wrap, text_width
    out = []
    cap = prof.caption
    for c in cues:
        text = " ".join(c.text.split("\n")).strip()
        if not text:
            continue
        if PF.fit_text_size(prof, text, role)["fits"]:
            out.append(Cue(c.start, c.end, text, c.alt, c.meta))
            continue
        per = cap["max_chars_zh"] if draw.has_cjk(text) else cap["max_chars_en"]
        lines = balanced_wrap(text, per)
        n = int(cap.get("max_lines", 2))
        chunks = [_join_lines(lines[i:i + n]) for i in range(0, len(lines), n)]
        final = []
        for ch in chunks:              # rare: pixel width still too wide -> halve
            stack = [ch]
            while stack:
                s = stack.pop(0)
                if PF.fit_text_size(prof, s, role)["fits"] or len(s) < 4:
                    final.append(s)
                else:                       # two balanced halves, breaking after punctuation when possible
                    halves = balanced_wrap(s, text_width(s) / 2 + 1)
                    if len(halves) < 2:
                        halves = [s[:len(s) // 2], s[len(s) // 2:]]
                    j = len(halves) // 2
                    stack[:0] = [_join_lines(halves[:j]), _join_lines(halves[j:])]
        tot = sum(max(1.0, text_width(s)) for s in final)
        t = c.start
        for s in final:
            dt = (c.end - c.start) * max(1.0, text_width(s)) / tot
            out.append(Cue(t, t + dt, s, "", c.meta))
            t += dt
    return out


# ----------------------------------------------------------------------------------- manifests
def merge_exports(old, new):
    """Exports of one episode: entries of the targets just rendered replace older ones (same file), others kept."""
    files = {e["file"] for e in new}
    return [e for e in (old or []) if e.get("file") not in files] + list(new)


def merge_manifest(old, new):
    """A later `make_vertical --targets X` run updates X's entries and keeps the other targets' exports
    (qa.py then still sees every target, not only the last run's)."""
    if not old:
        return new
    keys = set(new["targets"])
    out = dict(new, targets=list(dict.fromkeys(list(old.get("targets", [])) + new["targets"])),
               masters={**old.get("masters", {}), **new["masters"]})
    eps = {e["n"]: dict(e) for e in old.get("episodes", [])}
    for e in new["episodes"]:
        prev = eps.get(e["n"])
        eps[e["n"]] = dict(e, exports=merge_exports(prev["exports"] if prev else [], e["exports"]))
    out["episodes"] = [eps[n] for n in sorted(eps)]
    stale = tuple(f" {k}: " for k in keys)
    redone = {f"ep{e['n']} " for e in new["episodes"]}
    out["warnings"] = [w for w in old.get("warnings", [])
                       if not (any(s in w for s in stale) and any(w.startswith(r) for r in redone))] + new["warnings"]
    return out
