#!/usr/bin/env python3
"""Three-person gallery-view call -> 1080x1920 short, two guests masked.

Layout: the two masked guests side by side on the top row, the host full width
below. The guests' faces are stickers, so their row is also where the 记笔记
panels go; the host, who is shown, is never covered.

Each guest gets their own track and sticker. The sticker is pasted into a copy
of that guest's tile, clipped to it, so an ear can never bleed into a
neighbouring tile. The guest crop is a fixed window per clip, centred on the
median tracked face, so the face stays in frame without the crop wandering.

Reuses the furniture (title, chips, badge, node cards, panels, subtitles) from
render_vertical.py so both layouts stay one design.

Usage:
  render_trio.py CLIP.mp4 --guests-json g.json --subs subs.json \
      --title-json title.json --host-region 640,0,640,360 --out out.mp4
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_vertical as rv
from render_vertical import _wrap
from style import TEAL, GUEST_DEFAULT, HOST_DEFAULT
from render_vertical import (W, H, font, render_chip, render_hook_badge, render_node_card,
                             render_panel, render_sub, alpha_paste, NODE_FADE, PANEL_FADE)

# Platform safe zone (小红书 / Douyin / Reels on iPhone): the top ~230px sit
# under the status bar and top nav, the bottom ~270px under title, caption and
# buttons. Everything that matters lives in y 240..1660.
TITLE_Y = 240
TOP_Y = 440
GAP = 12
G_H = 500                         # guest row height
G_W = (W - GAP) // 2              # 534
HOST_Y = TOP_Y + G_H + GAP        # 952
HOST_H = 540                      # host tile, cropped slightly top and bottom
HOST_CROP = 20                    # source px trimmed off the host tile's top
TILES_BOTTOM = HOST_Y + HOST_H    # 1492
SUB_Y = 1500


def render_quote(who, text, width=980):
    """Quote card for a 金句 compilation: big type, balanced lines, the
    speaker in teal. No 记笔记 tag -- a quote is not a note."""
    f_q, f_who, f_mark = font(58), font(34), font(120)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad = 56
    if "\n" in text:
        # hand-set breaks: a quote is short enough to break by meaning
        lines = text.split("\n")
    else:
        maxw = width - pad * 2
        lines = _wrap(text, f_q, maxw, tmp)
        n, lo, hi = len(lines), maxw // 2, maxw
        while hi - lo > 8:
            mid = (lo + hi) // 2
            if len(_wrap(text, f_q, mid, tmp)) <= n:
                hi = mid
            else:
                lo = mid
        lines = _wrap(text, f_q, hi, tmp)
    # the card hugs its text instead of leaving a dead right margin
    tw = max(tmp.textbbox((0, 0), ln, font=f_q)[2] for ln in lines)
    size = 58
    while tw > width - pad * 2 and size > 40:   # never spill past the card
        size -= 2
        f_q = font(size)
        tw = max(tmp.textbbox((0, 0), ln, font=f_q)[2] for ln in lines)
    width = min(width, max(560, tw + pad * 2))
    lh = 80
    h = 86 + len(lines) * lh + 30 + 44 + 40
    im = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, width - 1, h - 1], radius=26, fill=(12, 14, 18, 240),
                        outline=TEAL + (230,), width=3)
    d.text((pad - 6, -8), "“", font=f_mark, fill=TEAL + (255,))
    y = 86
    for ln in lines:
        d.text((pad, y), ln, font=f_q, fill=(255, 255, 255, 255))
        y += lh
    y += 30
    d.rectangle([pad, y + 18, pad + 44, y + 22], fill=TEAL + (255,))
    d.text((pad + 60, y), who, font=f_who, fill=TEAL + (255,))
    return im


def build_frame(title_lines, accent):
    """Headline and accent line, both inside the top safe edge."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    f_t = font(58)
    y = TITLE_Y
    for line in title_lines:
        x = 64
        runs = line if isinstance(line, list) else [[line, False]]
        for txt, is_acc in runs:
            d.text((x, y), txt, font=f_t, fill=TEAL if is_acc else (255, 255, 255))
            x += d.textbbox((0, 0), txt, font=f_t)[2]
        y += 74
    if accent:
        d.rectangle([64, y + 22, 64 + 72, y + 26], fill=TEAL)
        d.text((64 + 92, y + 8), accent, font=font(26), fill=(156, 163, 175))
    return img


def guest_crop(region, track):
    """Fixed crop inside the guest's tile with the output tile's aspect,
    centred on the median face so a lean does not push the head out."""
    x, y, w, h = region
    ch = h
    cw = int(round(ch * G_W / G_H))
    cx = float(np.median(track["cx"])) - x
    x0 = int(round(min(max(cx - cw / 2, 0), w - cw)))
    return x0, 0, cw, ch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--guests-json", required=True)
    ap.add_argument("--subs", required=True)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host-region", required=True)
    # accepted for build_clips.py compatibility, unused here
    ap.add_argument("--track", default=None)
    ap.add_argument("--sticker", default=None)
    ap.add_argument("--guest-region", default=None)
    ap.add_argument("--scale", type=float, default=2.40)
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preview", default=None, help="dump one JPG at this second and exit")
    args = ap.parse_args()

    meta = json.load(open(args.title_json))
    subs = json.load(open(args.subs))
    guests = json.load(open(args.guests_json))
    hx, hy, hw, hh = (int(v) for v in args.host_region.split(","))

    for g in guests:
        g["reg"] = [int(v) for v in g["region"].split(",")]
        g["tr"] = json.load(open(g["track"]))
        g["crop"] = guest_crop(g["reg"], g["tr"])
        g["st"] = np.array(Image.open(g["sticker"]).convert("RGBA"))
        g["cache"] = {}

    base_bgr = np.array(build_frame(meta["title"], meta.get("accent", "")))[:, :, ::-1].copy()

    f_chip = font(30)
    chips = []
    for k, g in enumerate(guests):
        chips.append((np.array(render_chip(g.get("label") or GUEST_DEFAULT, f_chip)),
                      k * (G_W + GAP), TOP_Y + G_H - 44))
    chips.append((np.array(render_chip(meta.get("host_label") or HOST_DEFAULT, f_chip)),
                  0, HOST_Y + HOST_H - 44))

    panels = []
    for anchor, dur, title, bullets in meta.get("panels", []):
        im = np.array(render_quote(title, bullets[0]) if meta.get("quote_cards")
                      else render_panel(title, bullets))
        if im.shape[0] > G_H - 24:
            print(f"WARN panel taller than the guest row ({im.shape[0]}px): {title}")
        panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                       "y": TOP_Y + (G_H - im.shape[0]) / 2})

    hook_end = float(meta.get("hook_end", 0.0))
    badge = np.array(render_hook_badge()) if hook_end > 0 else None
    nodes = [{"im": np.array(render_node_card(t)), "s": float(at) - 0.95, "e": float(at) + 0.95}
             for at, t in meta.get("node_cards", [])]

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    proc = None
    if not args.preview:
        proc = subprocess.Popen([
            "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
            "-i", args.video, "-map", "0:v", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
            "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", args.out,
        ], stdin=subprocess.PIPE)

    sub_cache = {}
    i = 0
    while True:
        ok, src = cap.read()
        if not ok:
            break
        t = i / fps
        if args.preview and abs(t - float(args.preview)) >= 1 / fps:
            i += 1
            continue
        canvas = base_bgr.copy()

        for k, g in enumerate(guests):
            x, y, w, h = g["reg"]
            tile = src[y:y + h, x:x + w].copy()
            tr = g["tr"]
            j = min(i, len(tr["cx"]) - 1)
            tw = max(24, int(round(tr["w"][j] * args.scale)))
            if tw not in g["cache"]:
                th = int(round(tw * g["st"].shape[0] / g["st"].shape[1]))
                g["cache"][tw] = np.array(Image.fromarray(g["st"]).resize((tw, th), Image.LANCZOS))
            st = g["cache"][tw]
            alpha_paste(tile, st, tr["cx"][j] - x, tr["cy"][j] - y + args.y_offset * st.shape[0])
            cx0, cy0, cw, ch = g["crop"]
            out = cv2.resize(tile[cy0:cy0 + ch, cx0:cx0 + cw], (G_W, G_H), interpolation=cv2.INTER_CUBIC)
            ox = k * (G_W + GAP)
            canvas[TOP_Y:TOP_Y + G_H, ox:ox + G_W] = out

        ch = int(round(hw * HOST_H / W))           # keep aspect: 640 wide -> 320 tall
        y0 = hy + min(HOST_CROP, hh - ch)
        host = cv2.resize(src[y0:y0 + ch, hx:hx + hw], (W, HOST_H), interpolation=cv2.INTER_CUBIC)
        canvas[HOST_Y:HOST_Y + HOST_H] = host

        cur_node = next((n for n in nodes if n["s"] - NODE_FADE <= t <= n["e"] + NODE_FADE), None)
        if cur_node is not None:
            if t < cur_node["s"]:
                kk = (t - (cur_node["s"] - NODE_FADE)) / NODE_FADE
            elif t > cur_node["e"]:
                kk = 1 - (t - cur_node["e"]) / NODE_FADE
            else:
                kk = 1.0
            band = canvas[TOP_Y:TILES_BOTTOM]
            canvas[TOP_Y:TILES_BOTTOM] = (band * (1 - 0.68 * kk)).astype(np.uint8)
            alpha_paste(canvas, cur_node["im"], W / 2, TOP_Y + (TILES_BOTTOM - TOP_Y) / 2, opacity=kk)

        if badge is not None and t < hook_end:
            op = min(1.0, (hook_end - t) / 0.4)
            # on the guest row's top-right, not the screen's top edge, which
            # the platform's nav bar covers
            alpha_paste(canvas, badge, W - 24 - badge.shape[1] / 2,
                        TOP_Y + 20 + badge.shape[0] / 2, opacity=op)

        for p in panels:
            if not (p["s"] - PANEL_FADE <= t <= p["e"] + PANEL_FADE):
                continue
            if t < p["s"]:
                kk = (t - (p["s"] - PANEL_FADE)) / PANEL_FADE
                op, dy = kk, (1 - kk) * 26
            elif t > p["e"]:
                op, dy = 1 - (t - p["e"]) / PANEL_FADE, 0.0
            else:
                op, dy = 1.0, 0.0
            alpha_paste(canvas, p["im"], W / 2, p["y"] + p["im"].shape[0] / 2 + dy, opacity=op)

        # chips flush to each tile's bottom-left, over the call app's name badges
        for img, ox, oy in chips:
            alpha_paste(canvas, img, ox + img.shape[1] / 2, oy + img.shape[0] / 2)

        cur = next((s for s in subs if s["start"] <= t < s["end"]), None)
        if cur:
            key = cur["text"]
            if key not in sub_cache:
                sub_cache[key] = np.array(render_sub(key))
            sub = sub_cache[key]
            alpha_paste(canvas, sub, W // 2, SUB_Y + sub.shape[0] / 2)

        if args.preview:
            cv2.imwrite(args.out, canvas)
            print(f"preview t={t:.2f} -> {args.out}")
            return
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
