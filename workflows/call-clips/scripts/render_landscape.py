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
import argparse, json, os, subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import (TEAL, DIM, WHITE, RED, font, alpha_paste, FRAME_THEME, HOOK_BADGE_LANDSCAPE,
                   NODE_EYEBROW, NOTE_TAG, GUEST_DEFAULT, HOST_DEFAULT)
from vstudio import overlays
from vstudio.draw import text_layer, text_width

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


def render_chip(label):
    """Flush to the tile's left edge so the call app's name badge under it is hidden."""
    return overlays.chip(label, style="tag", color=TEAL, size=30, scale=28 / 30)


_NK = 52 / 56          # node card: 52px title on a 1920 frame


def render_node_card(title):
    return overlays.node_card(title, eyebrow=NODE_EYEBROW, theme=FRAME_THEME, scale=_NK,
                              min_w=560 / _NK, max_w=1200 / _NK)


def render_hook_badge():
    """Tells the viewer the opening montage is a preview, so the jump cuts read
    as intentional."""
    return overlays.badge(HOOK_BADGE_LANDSCAPE, color=RED, size=28)


def build_frame_png(title, accent):
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([64, 26, 64 + 84, 31], fill=TEAL)
    if title:
        d.text((64, 44), title, font=font(36), fill=WHITE)
    if accent:
        d.text((64 + 26 + text_width(title, font(36)), 51), accent,
               font=font(26), fill=DIM)
    return img


PW = 880
PANEL_FADE = 0.30


def render_panel(title, bullets):
    """记笔记 card, same design as the vertical cuts (vstudio.overlays.notes_panel),
    PW wide with 36px bullets for a 960px tile."""
    return overlays.notes_panel(title, bullets, width=PW / 1.2, scale=1.2, tag=NOTE_TAG)


SUB_MAX_W = 1680


def render_sub(zh, en):
    """Chinese above, English below, as one cached RGBA strip (each balanced-wrapped
    at SUB_MAX_W, latin runs never split)."""
    rows = [text_layer(zh, font(50), max_w=SUB_MAX_W, stroke=5, stroke_fill=(0, 0, 0, 235),
                       shadow_alpha=0, pad=13, line_gap=1.2)]
    if en:
        rows.append(text_layer(en, font(38, False), fill=(203, 213, 225), max_w=SUB_MAX_W, stroke=5,
                               stroke_fill=(0, 0, 0, 235), shadow_alpha=0, pad=13, line_gap=1.2))
    w = max(r.width for r in rows)
    im = Image.new("RGBA", (w, sum(r.height for r in rows) - 26 * (len(rows) - 1)), (0, 0, 0, 0))
    y = 0
    for r in rows:
        im.alpha_composite(r, ((w - r.width) // 2, y))
        y += r.height - 26
    return im


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

    chips = [(np.array(render_chip(meta.get("guest_label") or GUEST_DEFAULT)), 0),
             (np.array(render_chip(meta.get("host_label") or HOST_DEFAULT)), TILE_W)]

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
