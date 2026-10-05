#!/usr/bin/env python3
"""1920x1080 long-form cut for YouTube: two tiles side by side, bilingual
subtitles burned in, and a sticker tracking the guest's face.

Both participants stay on screen with their gestures; only the guest's face is
covered. Coverage is proved geometrically by verify_coverage.py, not by eye.

Usage:
  render_landscape.py CLIP.mp4 --track t.json --sticker cat.png --subs subs.json \
      --title-json title.json --out out.mp4
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re, subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import (TEAL, DIM, WHITE, RED, YEL, font, HOOK_BADGE_LANDSCAPE, NODE_EYEBROW,
                   NOTE_TAG, GUEST_DEFAULT, HOST_DEFAULT)

W, H = 1920, 1080

TILE_W, TILE_H = 960, 675
TILE_Y = 96
TILES_BOTTOM = TILE_Y + TILE_H          # 771
# Default horizontal crop of each 640px source tile. Measure per recording
# (track the guest, sample-detect the host) and keep a real margin beyond both
# speakers' extremes; e.g. faces measured at 174..483 and 144..464 -> 512 is
# safe with ~80px spare each side. Override with --crop-w.
CROP_W = 512
SUB_TOP = 795

NODE_FADE = 0.35


def text_w(d, s, f):
    return d.textbbox((0, 0), s, font=f)[2]


def render_chip(label, fnt):
    """Flush to the tile's left edge so the call app's name badge under it is hidden."""
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad_x, pad_y = 22, 10
    w = max(text_w(tmp, label, fnt) + pad_x * 2, 210)
    h = fnt.size + pad_y * 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=9,
                        fill=(0, 0, 0, 255), outline=TEAL + (220,), width=2)
    d.text(((w - text_w(tmp, label, fnt)) // 2, pad_y - 3), label, font=fnt, fill=WHITE)
    return im


def render_node_card(title):
    f_eye, f_t = font(28), font(52)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    eyebrow = NODE_EYEBROW
    w = min(max(max(text_w(tmp, title, f_t), text_w(tmp, eyebrow, f_eye)) + 110, 560), 1200)
    h = 196
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=22, fill=(10, 12, 16, 247),
                        outline=TEAL + (235,), width=3)
    d.rectangle([44, 52, 44 + 64, 57], fill=TEAL)
    d.text((44, 76), eyebrow, font=f_eye, fill=TEAL)
    d.text((44, 114), title, font=f_t, fill=WHITE)
    return im


def render_hook_badge():
    """Tells the viewer the opening montage is a preview, so the jump cuts read
    as intentional."""
    f = font(28)
    txt = HOOK_BADGE_LANDSCAPE
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w, h = text_w(tmp, txt, f) + 52, f.size + 26
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=RED + (242,))
    d.text((26, 11), txt, font=f, fill=WHITE)
    return im


def build_frame_png(title, accent):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([64, 26, 64 + 84, 31], fill=TEAL)
    if title:
        d.text((64, 44), title, font=font(36), fill=WHITE)
    if accent:
        d.text((64 + 26 + text_w(d, title, font(36)), 51), accent,
               font=font(26), fill=DIM)
    return img


PW = 880
PANEL_FADE = 0.30


def _toks(s):
    out, i = [], 0
    while i < len(s):
        m = re.match(r"[A-Za-z0-9%/+.\-']+", s[i:])
        if m:
            out.append(m.group()); i += m.end()
        else:
            out.append(s[i]); i += 1
    return out


def _wrap(text, f, maxw, dr):
    lines, cur = [], ""
    for t in _toks(text):
        if dr.textbbox((0, 0), cur + t, font=f)[2] > maxw and cur:
            lines.append(cur.rstrip()); cur = t if t.strip() else ""
        else:
            cur += t
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def render_panel(title, bullets):
    """记笔记 card, same design as the vertical cuts, narrowed for a 960px tile."""
    ft, fbu, ftag = font(42, False), font(36, False), font(29, False)
    PX, PY, HEAD, BG, DOT = 28, 24, 80, 18, 10
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    wr = [_wrap(b, fbu, PW - PX * 2 - 24, tmp) for b in bullets]
    a, dsc = fbu.getmetrics()
    blh = a + dsc
    Hh = HEAD + PY * 2 + sum(len(x) for x in wr) * blh + (len(bullets) - 1) * BG
    im = Image.new("RGBA", (PW, Hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, PW - 1, Hh - 1], radius=20, fill=(16, 18, 24, 242))
    d.rounded_rectangle([0, 0, PW - 1, HEAD + 20], radius=20, fill=RED + (255,))
    d.rectangle([0, HEAD - 2, PW - 1, HEAD + 20], fill=(16, 18, 24, 242))
    tb = d.textbbox((0, 0), title, font=ft)
    d.text((26, (HEAD - (tb[3] - tb[1])) // 2 - tb[1]), title, font=ft, fill=WHITE)
    tag = NOTE_TAG
    tt = text_w(d, tag, ftag)
    px = PW - tt - 26 - 24
    if 26 + text_w(d, title, ft) > px - 12:
        print(f"WARN panel title runs under the tag -> {title}")
    d.rounded_rectangle([px, 18, px + tt + 24, 18 + 42], radius=12, fill=YEL + (255,))
    d.text((px + 12, 18 + 5), tag, font=ftag, fill=(20, 20, 20, 255))
    y = HEAD + PY
    for x in wr:
        cy = y + blh // 2
        d.ellipse([26, cy - DOT // 2, 26 + DOT, cy + DOT // 2], fill=RED + (255,))
        for ln in x:
            d.text((26 + DOT + 14, y), ln, font=fbu, fill=(245, 246, 250, 255))
            y += blh
        y += BG
    return im


SUB_MAX_W = 1680


def wrap(line, f, tmp):
    """Balance two lines rather than orphaning a few characters."""
    if text_w(tmp, line, f) <= SUB_MAX_W:
        return [line]
    hard = len(line)
    while hard > 1 and text_w(tmp, line[:hard], f) > SUB_MAX_W:
        hard -= 1
    for cut in (len(line) // 2, hard):
        c = cut
        if 0 < c < len(line) and line[c - 1].isascii() and line[c].isascii():
            while c > 1 and line[c - 1].isascii():
                c -= 1
            if c <= 4:
                c = cut
        if text_w(tmp, line[:c], f) <= SUB_MAX_W and text_w(tmp, line[c:], f) <= SUB_MAX_W:
            return [line[:c], line[c:]]
    return [line[:hard]] + wrap(line[hard:], f, tmp)


def render_sub(zh, en):
    """Chinese above, English below, as one cached RGBA strip."""
    f_zh, f_en = font(50), font(38, False)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows = [(r, f_zh, WHITE) for r in wrap(zh, f_zh, tmp)]
    if en:
        rows += [(r, f_en, (203, 213, 225)) for r in wrap(en, f_en, tmp)]
    pad = 18
    w = max(text_w(tmp, r, f) for r, f, _ in rows) + pad * 2
    hs = [int(f.size * 1.34) for _, f, _ in rows]
    im = Image.new("RGBA", (w, sum(hs) + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = pad
    for (r, f, col), lh in zip(rows, hs):
        d.text(((w - text_w(tmp, r, f)) // 2, y), r, font=f, fill=col,
               stroke_width=5, stroke_fill=(0, 0, 0, 235))
        y += lh
    return im


def alpha_paste(dst, rgba, cx, cy, opacity=1.0):
    sh, sw = rgba.shape[:2]
    x0, y0 = int(round(cx - sw / 2)), int(round(cy - sh / 2))
    Hh, Ww = dst.shape[:2]
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = sw - max(0, x0 + sw - Ww), sh - max(0, y0 + sh - Hh)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    patch = rgba[sy0:sy1, sx0:sx1]
    dx0, dy0 = max(0, x0), max(0, y0)
    a = patch[:, :, 3:4].astype(np.float32) / 255.0 * opacity
    rgb = patch[:, :, :3][:, :, ::-1].astype(np.float32)
    roi = dst[dy0:dy0 + patch.shape[0], dx0:dx0 + patch.shape[1]].astype(np.float32)
    dst[dy0:dy0 + patch.shape[0], dx0:dx0 + patch.shape[1]] = \
        (rgb * a + roi * (1 - a)).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--avatar", default=None, help="unused; kept for the driver")
    ap.add_argument("--subs", required=True)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--guest-region", default="0,180,640,360")
    ap.add_argument("--host-region", default="640,180,640,360")
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--track", default=None, help="guest face track (required unless --no-mask)")
    ap.add_argument("--sticker", default=None)
    ap.add_argument("--no-mask", action="store_true",
                    help="nobody needs hiding: render both tiles as recorded")
    ap.add_argument("--scale", type=float, default=2.40)
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--hook-badge", action="store_true", default=True)
    ap.add_argument("--crop-w", type=int, default=CROP_W,
                    help="source px kept from the centre of each tile (measure first)")
    ap.add_argument("--preview", default=None)
    args = ap.parse_args()

    meta = json.load(open(args.title_json, encoding="utf-8"))
    subs = json.load(open(args.subs, encoding="utf-8"))
    if not args.no_mask and not (args.track and args.sticker):
        sys.exit("--track and --sticker are required unless --no-mask")
    gx, gy, gw, gh = (int(v) for v in args.guest_region.split(","))
    hx, hy, hw, hh = (int(v) for v in args.host_region.split(","))

    base = build_frame_png(meta.get("yt_title", ""), meta.get("accent", ""))
    base_bgr = np.array(base)[:, :, ::-1].copy()

    if not args.no_mask:
        tr = json.load(open(args.track))
        cxs, cys, ws = tr["cx"], tr["cy"], tr["w"]
        sticker = np.array(Image.open(args.sticker).convert("RGBA"))
        s_h0, s_w0 = sticker.shape[:2]
    st_cache = {}

    f_chip = font(28)
    chips = [(np.array(render_chip(meta.get("guest_label") or GUEST_DEFAULT, f_chip)), 0),
             (np.array(render_chip(meta.get("host_label") or HOST_DEFAULT, f_chip)), TILE_W)]

    hook_end = float(meta.get("hook_end", 0.0))
    badge = np.array(render_hook_badge()) if hook_end > 0 else None

    nodes = [{"im": np.array(render_node_card(t)), "s": a - 1.0, "e": a + 1.0}
             for a, t in meta.get("node_cards", [])]

    # note cards sit over the guest's tile: that face is a sticker already, so
    # the card costs nothing there, and the speaker stays visible on the right.
    panels = []
    for anchor, dur, title, bullets in meta.get("panels", []):
        im = np.array(render_panel(title, bullets))
        if im.shape[0] > TILE_H - 24:
            print(f"WARN panel taller than the tile ({im.shape[0]}px): {title}")
        panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                       "y": TILE_Y + (TILE_H - im.shape[0]) / 2})

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    proc = None
    if not args.preview:
        proc = subprocess.Popen([
            "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
            "-i", args.video, "-map", "0:v", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", args.out,
        ], stdin=subprocess.PIPE)

    sub_cache = {}
    i = 0
    while True:
        ok, src = cap.read()
        if not ok:
            break
        t = i / fps

        # the sticker goes on at source resolution, so the tile scale-up below
        # carries it along and the track never needs rescaling
        if not args.no_mask:
            j = min(i, len(cxs) - 1)
            tw_ = max(24, int(round(ws[j] * args.scale)))
            if tw_ not in st_cache:
                th = int(round(tw_ * s_h0 / s_w0))
                st_cache[tw_] = np.array(
                    Image.fromarray(sticker).resize((tw_, th), Image.LANCZOS))
            st = st_cache[tw_]
            alpha_paste(src, st, cxs[j], cys[j] + args.y_offset * st.shape[0])

        canvas = base_bgr.copy()
        for (rx, ry, rw, rh), ox in (((gx, gy, gw, gh), 0), ((hx, hy, hw, hh), TILE_W)):
            cw = min(args.crop_w, rw)
            cx0 = rx + (rw - cw) // 2
            canvas[TILE_Y:TILES_BOTTOM, ox:ox + TILE_W] = cv2.resize(
                src[ry:ry + rh, cx0:cx0 + cw], (TILE_W, TILE_H),
                interpolation=cv2.INTER_CUBIC)

        cur_node = next((n for n in nodes if n["s"] - NODE_FADE <= t <= n["e"] + NODE_FADE), None)
        if cur_node is not None:
            if t < cur_node["s"]:
                k = (t - (cur_node["s"] - NODE_FADE)) / NODE_FADE
            elif t > cur_node["e"]:
                k = 1 - (t - cur_node["e"]) / NODE_FADE
            else:
                k = 1.0
            band = canvas[TILE_Y:TILES_BOTTOM]
            canvas[TILE_Y:TILES_BOTTOM] = (band * (1 - 0.68 * k)).astype(np.uint8)
            alpha_paste(canvas, cur_node["im"], W / 2, TILE_Y + TILE_H / 2, opacity=k)

        if badge is not None and t < hook_end:
            op = min(1.0, (hook_end - t) / 0.5)
            alpha_paste(canvas, badge, W - 64 - badge.shape[1] / 2, 62, opacity=op)

        for p in panels:
            if not (p["s"] - PANEL_FADE <= t <= p["e"] + PANEL_FADE):
                continue
            if t < p["s"]:
                k = (t - (p["s"] - PANEL_FADE)) / PANEL_FADE
                op, dy = k, (1 - k) * 22
            elif t > p["e"]:
                op, dy = 1 - (t - p["e"]) / PANEL_FADE, 0.0
            else:
                op, dy = 1.0, 0.0
            alpha_paste(canvas, p["im"], TILE_W / 2,
                        p["y"] + p["im"].shape[0] / 2 + dy, opacity=op)

        # flush to each tile's bottom-left corner, because that is exactly
        # where the call app stamps the participant's real name
        for img, ox in chips:
            alpha_paste(canvas, img, ox + img.shape[1] / 2,
                        TILES_BOTTOM - img.shape[0] / 2)

        cur = next((s for s in subs if s["start"] <= t < s["end"]), None)
        if cur:
            key = (cur.get("zh") or cur.get("text", ""), cur.get("en", ""))
            if key not in sub_cache:
                sub_cache[key] = np.array(render_sub(*key))
            sub = sub_cache[key]
            alpha_paste(canvas, sub, W // 2, SUB_TOP + sub.shape[0] / 2)

        if args.preview:
            if abs(t - float(args.preview)) < 1 / fps:
                cv2.imwrite(args.out, canvas)
                print(f"preview t={t:.2f} -> {args.out}")
                return
            i += 1
            continue

        proc.stdin.write(canvas.tobytes())
        i += 1

    cap.release()
    if proc:
        proc.stdin.close()
        if proc.wait() != 0:
            sys.exit("ffmpeg failed")
        print(f"rendered {i} frames -> {args.out}")


if __name__ == "__main__":
    main()
