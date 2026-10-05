"""Vertical (3:4 / 9:16) layouts for lecture slices cut from a horizontal screen-share recording.

Used by make_vertical.py. Everything is drawn from explicit source rectangles, so nothing outside the
configured screen region (geometry crop spans = shared page without browser chrome / bookmark bar) or
the configured speaker region can ever reach the frame; ``vertical.exclude`` rects are painted out of the
source before any crop as a second guard (participant tiles, name tags).

Layouts (per timeline item; content area = safe-box top .. caption-box top of the target canvas):
  split     speaker band on top (face-tracked crop of the speaker cam tile, vstudio.reframe face mode) and
            the screen below. No speaker region / no face found -> a title band (series + current chapter)
            instead: a camera-less screen share never shows the participant tiles.
  screen    the whole content area is a crop of the screen that follows the content: frame-difference
            activity (typing, highlights, newly revealed blocks; cursor-sized changes ignored), code-zoom
            windows (zoom_windows.json) and the first text block of a new page; camera = vstudio.reframe.follow
            (vstudio.filters.OneEuro + dead zone + eased, speed-limited pan; page switches cut, never pan).
  speaker   the whole content area is the speaker crop.
  pad-blur  the whole screen region fitted to the width over a blurred, dimmed copy.
"""
import math
import os
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw

import _lfc
from vstudio import draw, media
from vstudio import platform as PF
from vstudio import reframe as R

MODES = ("split", "screen", "speaker", "pad-blur")
SCREEN_DEFAULTS = dict(min_scale=1.6, max_scale=3.0, sample_hz=4.0, change_luma=24, min_change_px=60,
                       analysis_w=480, page_change=0.45, follow="content", ink=40, headroom=0.12,
                       min_text_px=28)
# split / screen layout: a slim title band and the screen running down to the frame bottom (under the caption
# box and the platform UI, dimmed there by a scrim) instead of stopping above the captions; screen_to="caption"
# restores the pre-demo-round layout (screen box ends above the caption box, band 24 %).
SPLIT_DEFAULTS = dict(speaker_frac=0.40, band_frac=0.16, gap=10, screen_to="frame", scrim=0.5)
CAMERA = dict(R.DEFAULTS, dead_zone=0.10, settle=0.02, gain=2.5, max_speed=0.55, max_accel=1.0,
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


def boxes(L, mode, band, speaker_frac=0.40, band_frac=0.16, screen_to="frame"):
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
    lo = min(max(o["min_scale"], need_scale or 0.0), o["max_scale"])
    want = (content_w * 1.08) if content_w else rw
    want = min(max(want, bw / o["max_scale"]), bw / lo)
    cw = min(want, rw, rh * a)
    if cw >= min(bw / o["max_scale"], rw) - 1e-6:
        return cw, cw / a, bh
    cw = min(bw / o["max_scale"], rw)             # region too short for this box: cap the zoom, shorten
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


def analyse_screen(src, t0, t1, speed, fps, n, region, box, zoom_center=None, still=None, o=SCREEN_DEFAULTS,
                   vis_h=None):
    """Per-frame crop rects [x, y, cw, ch] (source px) for the screen box of one timeline item, plus stats
    (stats["draw_h"]: canvas height the crop is drawn at, from the box top). vis_h: height of the box part
    above the captions; reading start / activity are kept inside that part of the crop.
    The zoom is chosen so a text line is >= o["min_text_px"] tall on the canvas (line height measured on a
    full-resolution frame), within min_scale..max_scale."""
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

    pts, cuts = {}, []
    tx, ty = x_for(bx0), reading_start(ink[0])
    if zoom_center is not None:
        tx, ty = zoom_center
    step = fps / hz
    a0, a1 = int(cx0), max(int(cx0) + 1, int(cx1))
    for j in range(len(smp)):
        if j > 0:
            d = np.abs(stack[j] - stack[j - 1]) > o["change_luma"]
            frac = float(d.mean())
            if frac > o["page_change"]:
                cuts.append(int(round(j * step)))
                ty, tx = reading_start(ink[j]), x_for(bx0)
            elif zoom_center is None:
                dm = d[:, a0:a1]                       # activity inside the main block only
                if dm.sum() >= o["min_change_px"]:
                    ys, xs = np.nonzero(dm)
                    ty = ys.mean() / k + ry0
                    tx = x_for(rx0 + (xs.mean() + a0) / k)
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
    stats = dict(scale=round((box[2] - box[0]) / cw, 3), content_w=round(content_w, 1), cuts=len(bounds) - 2,
                 fixed_x=bool(fixed_x), draw_h=int(draw_h), line_px=line_px and round(line_px, 1),
                 text_px=line_px and round(line_px * (box[2] - box[0]) / cw, 1),
                 **R.path_stats(rects, fps, bounds[1:-1]))
    return rects, stats


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
def warp(fr, rect, size):
    """Crop rect [x, y, w, h] (sub-pixel) of fr scaled to size (w, h)."""
    x, y, cw, ch = rect
    tw, th = size
    s = tw / cw
    M = np.float32([[s, 0, -x * s], [0, th / ch, -y * th / ch]])
    return cv2.warpAffine(fr, M, (tw, th), flags=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA,
                          borderMode=cv2.BORDER_REPLICATE)


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
        chunks = ["".join(lines[i:i + n]) if draw.has_cjk(text) else " ".join(lines[i:i + n])
                  for i in range(0, len(lines), n)]
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
                    sep = "" if draw.has_cjk(s) else " "
                    stack[:0] = [sep.join(halves[:j]), sep.join(halves[j:])]
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
