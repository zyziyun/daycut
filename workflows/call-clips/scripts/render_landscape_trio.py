#!/usr/bin/env python3
"""1920x1080 YouTube cut of a three-person gallery-view call, two guests masked.

Three 640x720 tiles side by side: the two masked guests on the left, the host
on the right. Each tile is a 320x360 window out of its 640x360 call tile that
follows a heavily smoothed face track, so a speaker who drifts over an hour
stays framed without the crop visibly chasing them. Bilingual subtitles sit
under the tiles; 记笔记 panels sit over the two guests, whose faces are
stickers already.

Furniture (panel, subtitle strip, chips, cards, badge) is shared with
render_landscape.py so the two long-form layouts stay one design; so is ``--platform``
(safe-box headline/badge/chips, tiles above the caption box, captions in the caption box).

Usage:
  render_landscape_trio.py RAW.mp4 --guests-json g.json --host-track h.json \
      --subs subs.json --title-json title.json --host-region 640,0,640,360 --out out.mp4
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess
import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_landscape import (W, H, render_chip, render_node_card, render_hook_badge,
                              build_frame_png, render_panel, render_sub, NODE_FADE, PANEL_FADE, geometry)
from style import GUEST_DEFAULT, HOST_DEFAULT, alpha_paste
import layout

TILE_W, TILE_H = 640, 720
TILE_Y = 96
TILES_BOTTOM = TILE_Y + TILE_H          # 816
SUB_TOP = 832
CROP_W, CROP_H = 320, 360               # source window, scaled 2x
REFRAME_S = 6.0                         # seconds of smoothing on the crop centre


def smooth_centres(cx, fps, region_x, region_w):
    """Crop x0 per frame: face centre, smoothed over REFRAME_S so the frame
    drifts slowly rather than following every head turn."""
    a = np.asarray(cx, dtype=float) - region_x
    k = max(1, int(REFRAME_S * fps))
    pad = np.pad(a, (k, k), mode="edge")
    c = np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode="same")[k:-k]
    x0 = np.clip(np.round(c - CROP_W / 2), 0, region_w - CROP_W).astype(int)
    return x0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--guests-json", required=True)
    ap.add_argument("--host-track", required=True)
    ap.add_argument("--subs", required=True)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--host-region", required=True)
    ap.add_argument("--out", required=True)
    # accepted for build_clips.py compatibility
    ap.add_argument("--track", default=None)
    ap.add_argument("--sticker", default=None)
    ap.add_argument("--guest-region", default=None)
    ap.add_argument("--scale", type=float, default=2.40)
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preview", default=None, help="comma list of seconds to dump as JPGs")
    layout.add_args(ap)
    args = ap.parse_args()
    prof = layout.resolve(args.platform, "horizontal")
    nmask = layout.name_mask_from_args(args)

    meta = json.load(open(args.title_json))
    subs = json.load(open(args.subs))
    guests = json.load(open(args.guests_json))
    hx, hy, hw, hh = (int(v) for v in args.host_region.split(","))

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    tiles = []
    for g in guests:
        x, y, w, h = (int(v) for v in g["region"].split(","))
        tr = json.load(open(g["track"]))
        tiles.append({"reg": (x, y, w, h), "tr": tr, "label": g.get("label") or GUEST_DEFAULT,
                      "x0": smooth_centres(tr["cx"], fps, x, w),
                      "st": np.array(Image.open(g["sticker"]).convert("RGBA")), "cache": {}})
    htr = json.load(open(args.host_track))
    tiles.append({"reg": (hx, hy, hw, hh), "tr": None, "label": meta.get("host_label") or HOST_DEFAULT,
                  "x0": smooth_centres(htr["cx"], fps, hx, hw)})

    G = geometry(prof, meta.get("yt_title", ""), meta.get("accent", ""), TILE_H, TILE_Y)
    CW, CH, TY, TH = G["W"], G["H"], G["tile_y"], G["tile_h"]
    TB = TY + TH
    crop_h = CROP_H if TH == TILE_H else int(round(CROP_W * TH / TILE_W))
    sx0 = G["safe"][0]
    base_bgr = np.array(G["base"])[:, :, ::-1].copy()
    chips = [(np.array(render_chip(t["label"])), max(k * TILE_W, sx0)) for k, t in enumerate(tiles)]
    name_rects = layout.name_rects(nmask, [t["reg"] for t in tiles[:-1]], [tiles[-1]["reg"]])
    cap_ov = layout.caption_overlay(prof, subs, bilingual=True) if (prof is not None and not args.no_subs) else None

    hook_end = float(meta.get("hook_end", 0.0))
    badge = np.array(render_hook_badge()) if hook_end > 0 else None
    nodes = [{"im": np.array(render_node_card(t)), "s": a - 1.0, "e": a + 1.0}
             for a, t in meta.get("node_cards", [])]
    panels = []
    for anchor, dur, title, bullets in meta.get("panels", []):
        im = np.array(render_panel(title, bullets))
        if im.shape[0] > TH - 24:
            print(f"WARN panel taller than the tile ({im.shape[0]}px): {title}")
        panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                       "y": TY + (TH - im.shape[0]) / 2})

    previews = sorted(float(v) for v in args.preview.split(",")) if args.preview else None
    proc = None
    if not previews:
        proc = subprocess.Popen([
            "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{CW}x{CH}", "-r", str(fps), "-i", "-",
            "-i", args.video, "-map", "0:v", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
            "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", args.out,
        ], stdin=subprocess.PIPE)

    sub_cache = {}
    i = 0
    while True:
        ok, src = cap.read()
        if not ok:
            break
        t = i / fps
        if previews is not None:
            if not previews:
                break
            if t + 1e-6 < previews[0]:
                i += 1
                continue
        canvas = base_bgr.copy()
        layout.mask_names(src, name_rects, nmask["mode"])

        for k, tl in enumerate(tiles):
            x, y, w, h = tl["reg"]
            tile = src[y:y + h, x:x + w].copy()
            j = min(i, len(tl["x0"]) - 1)
            if tl["tr"] is not None:
                tr = tl["tr"]
                tw = max(24, int(round(tr["w"][j] * args.scale)))
                if tw not in tl["cache"]:
                    th = int(round(tw * tl["st"].shape[0] / tl["st"].shape[1]))
                    tl["cache"][tw] = np.array(Image.fromarray(tl["st"]).resize((tw, th), Image.LANCZOS))
                st = tl["cache"][tw]
                # pasted into this tile only, before the crop, so it can never
                # bleed into a neighbour and never misses the reframed window
                alpha_paste(tile, st, tr["cx"][j] - x, tr["cy"][j] - y + args.y_offset * st.shape[0])
            x0 = tl["x0"][j]
            cy0 = 0 if crop_h == CROP_H else int(round((min(h, CROP_H) - crop_h) * 0.46))
            canvas[TY:TB, k * TILE_W:(k + 1) * TILE_W] = cv2.resize(
                tile[cy0:cy0 + crop_h, x0:x0 + CROP_W], (TILE_W, TH), interpolation=cv2.INTER_CUBIC)

        cur_node = next((n for n in nodes if n["s"] - NODE_FADE <= t <= n["e"] + NODE_FADE), None)
        if cur_node is not None:
            if t < cur_node["s"]:
                kk = (t - (cur_node["s"] - NODE_FADE)) / NODE_FADE
            elif t > cur_node["e"]:
                kk = 1 - (t - cur_node["e"]) / NODE_FADE
            else:
                kk = 1.0
            band = canvas[TY:TB]
            canvas[TY:TB] = (band * (1 - 0.68 * kk)).astype(np.uint8)
            alpha_paste(canvas, cur_node["im"], CW / 2, TY + TH / 2, opacity=kk)

        if badge is not None and t < hook_end:
            op = min(1.0, (hook_end - t) / 0.5)
            bx, by = G["badge"]
            alpha_paste(canvas, badge, bx - badge.shape[1] / 2,
                        by if G["legacy"] else by + badge.shape[0] / 2 - 20, opacity=op)

        for p in panels:
            if not (p["s"] - PANEL_FADE <= t <= p["e"] + PANEL_FADE):
                continue
            if t < p["s"]:
                kk = (t - (p["s"] - PANEL_FADE)) / PANEL_FADE
                op, dy = kk, (1 - kk) * 22
            elif t > p["e"]:
                op, dy = 1 - (t - p["e"]) / PANEL_FADE, 0.0
            else:
                op, dy = 1.0, 0.0
            # centred over the two guest tiles
            alpha_paste(canvas, p["im"], TILE_W, p["y"] + p["im"].shape[0] / 2 + dy, opacity=op)

        # flush to each tile's bottom-left, where the call app stamps the real name
        for img, ox in chips:
            alpha_paste(canvas, img, ox + img.shape[1] / 2, TB - img.shape[0] / 2)

        cur = None if (args.no_subs or cap_ov) else next((s for s in subs if s["start"] <= t < s["end"]), None)
        if cap_ov:
            cap_ov(t, canvas)
        if cur:
            key = (cur.get("zh") or cur.get("text", ""), cur.get("en", ""))
            if key not in sub_cache:
                sub_cache[key] = np.array(render_sub(*key))
            sub = sub_cache[key]
            alpha_paste(canvas, sub, W // 2, SUB_TOP + sub.shape[0] / 2)

        if args.show_safe:
            layout.draw_safe(canvas, prof)
        if previews is not None:
            stem = args.out[:-4] if args.out.endswith(".jpg") else args.out
            cv2.imwrite(f"{stem}_{previews[0]:.0f}.jpg", canvas)
            print(f"preview t={t:.2f}")
            previews.pop(0)
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
