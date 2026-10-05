#!/usr/bin/env python3
"""Turn a two-tile call recording (Zoom / Meet / Teams gallery view) into a vertical short.

One pass: paste the sticker over the guest's tracked face, blur the call app's name labels, stack
the two tiles on a black + accent frame, and burn the subtitles. Many ffmpeg builds have neither
drawtext nor libass, so every glyph is drawn with PIL here.

Geometry comes from a platform profile (``--platform``, default persona ``platforms.default`` at its
9:16 canvas, e.g. 小红书 1080x1920): headline at the top of the safe box, tiles between the headline
and the caption box (cropped in height around the face when the space is short), chips / badge /
panels inside the safe box, captions fitted into the caption box. ``--platform legacy`` restores the
old full-bleed 1080x1920 layout (title at 150, tiles 330..1560, subs at 1654), which ignored the
phone UI.

Usage:
  render_vertical.py CLIP.mp4 --track t.json --sticker cat.png \
      --subs subs.json --title-json title.json --out out.mp4 [--platform douyin]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import (TEAL, DIM, WHITE, RED, font, alpha_paste, FRAME_THEME, HOOK_BADGE, NODE_EYEBROW,
                   NOTE_TAG, GUEST_DEFAULT, HOST_DEFAULT)
import layout
from vstudio import overlays
from vstudio.draw import text_layer, text_width

W, H = 1080, 1920

TILE_H = 608
TOP_Y = 330
GAP = 14
BOT_Y = TOP_Y + TILE_H + GAP          # 952
TILES_BOTTOM = BOT_Y + TILE_H         # 1560

def render_chip(label):
    """Name tag that sits flush to the left edge so the call app's name badge
    underneath is fully hidden -- hence the small corner radius, not a pill."""
    return overlays.chip(label, style="tag", color=TEAL, size=30)


def render_hook_badge():
    """Marks the montage up front as a preview, so the jump cuts read as
    intentional rather than as a broken edit."""
    return overlays.badge(HOOK_BADGE, color=RED, size=32)


NODE_FADE = 0.35


def render_node_card(title, max_w=960):
    """Shown over each internal edit. The viewer needs to know the jump was
    deliberate, so the card names the section we are jumping into."""
    return overlays.node_card(title, eyebrow=NODE_EYEBROW, theme=FRAME_THEME, max_w=max_w)


def build_frame_png(title_lines, accent):
    """Static furniture: background, headline, rule. No corner index -- the
    top row is left clear for the hook badge."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)

    n = len(title_lines)
    size, lh = (64, 84) if n <= 2 else (54, 70)
    f_t = font(size)
    y = 150 if n <= 2 else 140
    for line in title_lines:
        x = 72
        # a line is a list of (text, is_accent) runs
        runs = line if isinstance(line, list) else [[line, False]]
        for txt, is_acc in runs:
            d.text((x, y), txt, font=f_t, fill=TEAL if is_acc else WHITE)
            x += text_width(txt, f_t)
        y += lh

    d.rectangle([72, TILES_BOTTOM + 36, 72 + 96, TILES_BOTTOM + 41], fill=TEAL)
    if accent:
        d.text((72 + 128, TILES_BOTTOM + 22), accent, font=font(28), fill=DIM)
    return img


SUB_MAX_W = 980


def render_sub(line):
    """Subtitle as its own RGBA strip (balanced CJK-aware wrap at SUB_MAX_W, latin
    runs never split) so it can be cached and alpha-pasted."""
    return text_layer(line, font(48), max_w=SUB_MAX_W, stroke=6, stroke_fill=(0, 0, 0, 235),
                      shadow_alpha=0, pad=14, line_gap=1.0)


PW = 940
PANEL_FADE = 0.30


def render_panel(title, bullets, pw=PW, max_h=None):
    """记笔记 card (vstudio.overlays.notes_panel, persona panel theme: dark card,
    brand-accent header, highlight 记笔记 tag, accent-dot bullets), pw wide with
    40px bullets for a 1080-wide vertical frame; scaled down to fit max_h."""
    s = 4 / 3 * pw / PW
    im = overlays.notes_panel(title, bullets, width=pw / s, scale=s, tag=NOTE_TAG)
    if max_h and im.height > max_h:
        k = max(0.6, max_h / im.height)
        im = overlays.notes_panel(title, bullets, width=pw / s, scale=s * k, tag=NOTE_TAG)
    return im


def geometry(prof, title_lines, accent):
    """Layout for a platform profile: dict with canvas, rows, positions and the static frame image.
    None profile -> the legacy fixed layout (unchanged)."""
    if prof is None:
        return dict(W=W, H=H, top_y=TOP_Y, row_h=TILE_H, bot_y=BOT_Y, tiles_bottom=TILES_BOTTOM,
                    chip_x=0, cx=W / 2, pw=PW, node_max_w=960, legacy=True,
                    base=build_frame_png(title_lines, accent))
    b = layout.boxes(prof)
    cw, ch = b["W"], b["H"]
    sx0, sy0, sx1, sy1 = b["safe"]
    img = Image.new("RGB", (cw, ch), (0, 0, 0))
    d = ImageDraw.Draw(img)
    n = len(title_lines)
    size, lh = (64, 84) if n <= 2 else (54, 70)
    x_l, x_r = sx0 + 12, sx1 - 12

    def line_w(line, f):
        runs = line if isinstance(line, list) else [[line, False]]
        return sum(text_width(t, f) for t, _ in runs)
    while size > 36 and max([line_w(ln, font(size)) for ln in title_lines] or [0]) > x_r - x_l:
        size -= 2
        lh = int(size * 1.3)
    f_t = font(size)
    y = sy0
    for line in title_lines:
        x = x_l
        for txt, is_acc in (line if isinstance(line, list) else [[line, False]]):
            d.text((x, y), txt, font=f_t, fill=TEAL if is_acc else WHITE)
            x += text_width(txt, f_t)
        y += lh
    if accent:
        d.rectangle([x_l, y + 22, x_l + 72, y + 26], fill=TEAL)
        d.text((x_l + 92, y + 8), accent, font=font(28), fill=DIM)
        y += 56
    tiles_top = y + 16
    tiles_bottom = b["caption"][1] - 16
    avail = tiles_bottom - tiles_top
    row_h = int(min(TILE_H, (avail - GAP) // 2))
    if row_h < 240:
        print(f"WARN only {avail}px between the headline and the caption box: tiles {row_h}px tall")
    top_y = tiles_top + (avail - (2 * row_h + GAP)) // 2
    bot_y = top_y + row_h + GAP
    return dict(W=cw, H=ch, top_y=top_y, row_h=row_h, bot_y=bot_y, tiles_bottom=bot_y + row_h,
                chip_x=sx0, cx=(sx0 + sx1) / 2, pw=min(PW, sx1 - sx0 - 24), node_max_w=min(960, (sx1 - sx0) * 0.75),
                safe=b["safe"], legacy=False, base=img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--track", default=None, help="guest face track (required unless --no-mask)")
    ap.add_argument("--sticker", default=None)
    ap.add_argument("--no-mask", action="store_true",
                    help="nobody needs hiding: render both tiles as recorded")
    ap.add_argument("--subs", required=True)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--guest-region", default="0,180,640,360")
    ap.add_argument("--host-region", default="640,180,640,360")
    ap.add_argument("--scale", type=float, default=2.40)
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preview", default=None, help="dump one JPG at this second and exit")
    layout.add_args(ap, platform_default="default")
    args = ap.parse_args()
    prof = layout.resolve(args.platform, "vertical")
    nmask = layout.name_mask_from_args(args)

    meta = json.load(open(args.title_json, encoding="utf-8"))
    subs = json.load(open(args.subs, encoding="utf-8"))
    if not args.no_mask and not (args.track and args.sticker):
        sys.exit("--track and --sticker are required unless --no-mask")
    if not args.no_mask:
        tr = json.load(open(args.track))
        cxs, cys, ws = tr["cx"], tr["cy"], tr["w"]

    gx, gy, gw, gh = (int(v) for v in args.guest_region.split(","))
    hx, hy, hw, hh = (int(v) for v in args.host_region.split(","))

    G = geometry(prof, meta["title"], meta.get("accent", ""))
    CW, CH = G["W"], G["H"]
    top_y, row_h, bot_y, tiles_bottom = G["top_y"], G["row_h"], G["bot_y"], G["tiles_bottom"]
    base_bgr = np.array(G["base"])[:, :, ::-1].copy()
    chips = [
        (np.array(render_chip(meta.get("guest_label") or GUEST_DEFAULT)), top_y + row_h - 44),
        (np.array(render_chip(meta.get("host_label") or HOST_DEFAULT)), bot_y + row_h - 44),
    ]
    # each tile: full source width, height cut to the row's aspect around the face
    gcy = float(np.median(cys)) if not args.no_mask else None
    if G["legacy"]:
        crops = [(gx, gy, gw, gh), (hx, hy, hw, hh)]
    else:
        crops = [layout.vcrop((gx, gy, gw, gh), CW, row_h, gcy), layout.vcrop((hx, hy, hw, hh), CW, row_h)]
    name_rects = layout.name_rects(nmask, [(gx, gy, gw, gh)], [(hx, hy, hw, hh)])
    cap_ov = layout.caption_overlay(prof, subs) if (prof is not None and not args.no_subs) else None

    # 记笔记 panels sit over the guest's tile: the face there is a sticker
    # already, so nothing is lost, and the speaker stays visible below.
    panels = []
    for anchor, dur, title, bullets in meta.get("panels", []):
        im = np.array(render_panel(title, bullets, G["pw"], None if G["legacy"] else row_h - 24))
        if im.shape[0] > row_h - 24:
            print(f"WARN panel taller than the tile ({im.shape[0]}px): {title}")
        panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                       "title": title,
                       "y": top_y + (row_h - im.shape[0]) / 2})
    # two live panels would stack on the same spot, so catch it at build time
    for a, b in zip(panels, panels[1:]):
        if b["s"] < a["e"] + PANEL_FADE:
            print(f"WARN panels overlap: '{a['title']}' ends {a['e']:.1f}s, "
                  f"'{b['title']}' starts {b['s']:.1f}s")

    hook_end = float(meta.get("hook_end", 0.0))
    badge = np.array(render_hook_badge()) if hook_end > 0 else None

    nodes = []
    nd = meta.get("node_cards", [])
    for at, title in nd:
        nodes.append({"im": np.array(render_node_card(title, G["node_max_w"])),
                      "s": float(at) - 0.95, "e": float(at) + 0.95})

    if not args.no_mask:
        sticker = np.array(Image.open(args.sticker).convert("RGBA"))
        s_h0, s_w0 = sticker.shape[:2]

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

    proc = None
    if not args.preview:
        proc = subprocess.Popen([
            "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{CW}x{CH}", "-r", str(fps), "-i", "-",
            "-i", args.video, "-map", "0:v", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", args.out,
        ], stdin=subprocess.PIPE)

    st_cache, sub_cache = {}, {}
    i = 0
    while True:
        ok, src = cap.read()
        if not ok:
            break
        t = i / fps
        layout.mask_names(src, name_rects, nmask["mode"])

        if not args.no_mask:
            j = min(i, len(cxs) - 1)
            tw = max(24, int(round(ws[j] * args.scale)))
            if tw not in st_cache:
                th = int(round(tw * s_h0 / s_w0))
                st_cache[tw] = np.array(Image.fromarray(sticker).resize((tw, th), Image.LANCZOS))
            st = st_cache[tw]
            alpha_paste(src, st, cxs[j], cys[j] + args.y_offset * st.shape[0])

        canvas = base_bgr.copy()
        for (rx, ry, rw, rh), oy in zip(crops, (top_y, bot_y)):
            tile = cv2.resize(src[ry:ry + rh, rx:rx + rw], (CW, row_h), interpolation=cv2.INTER_AREA)
            canvas[oy:oy + row_h, 0:CW] = tile
        cur_node = next((n for n in nodes
                         if n["s"] - NODE_FADE <= t <= n["e"] + NODE_FADE), None)
        if cur_node is not None:
            if t < cur_node["s"]:
                k = (t - (cur_node["s"] - NODE_FADE)) / NODE_FADE
            elif t > cur_node["e"]:
                k = 1 - (t - cur_node["e"]) / NODE_FADE
            else:
                k = 1.0
            # dim the footage so the card reads, and so the jump itself lands
            band = canvas[top_y:tiles_bottom]
            canvas[top_y:tiles_bottom] = (band * (1 - 0.68 * k)).astype(np.uint8)
            alpha_paste(canvas, cur_node["im"], G["cx"],
                        top_y + (tiles_bottom - top_y) / 2, opacity=k)

        if badge is not None and t < hook_end:
            op = min(1.0, (hook_end - t) / 0.4)
            if G["legacy"]:
                # right-aligned on the eyebrow row: the only band with free space
                alpha_paste(canvas, badge, W - 72 - badge.shape[1] / 2,
                            107 + badge.shape[0] / 2 - 30, opacity=op)
            else:
                # top-right of the guest row, inside the safe box (the top bar covers the edge)
                alpha_paste(canvas, badge, G["safe"][2] - 12 - badge.shape[1] / 2,
                            top_y + 20 + badge.shape[0] / 2, opacity=op)

        for p in panels:
            if not (p["s"] - PANEL_FADE <= t <= p["e"] + PANEL_FADE):
                continue
            if t < p["s"]:                       # fade in, sliding up
                k = (t - (p["s"] - PANEL_FADE)) / PANEL_FADE
                op, dy = k, (1 - k) * 26
            elif t > p["e"]:                     # fade out in place
                op, dy = 1 - (t - p["e"]) / PANEL_FADE, 0.0
            else:
                op, dy = 1.0, 0.0
            alpha_paste(canvas, p["im"], G["cx"],
                        p["y"] + p["im"].shape[0] / 2 + dy, opacity=op)

        # chips go on after the tiles (legacy: flush left, over the call app's name badge;
        # platform: at the safe-box edge, the badge itself is blurred by mask_names)
        for img, oy in chips:
            alpha_paste(canvas, img, G["chip_x"] + img.shape[1] / 2, oy + img.shape[0] / 2)

        cur = None if (args.no_subs or cap_ov) else next((s for s in subs if s["start"] <= t < s["end"]), None)
        if cap_ov:
            cap_ov(t, canvas)
        if cur:
            key = cur["text"]
            if key not in sub_cache:
                sub_cache[key] = np.array(render_sub(key))
            sub = sub_cache[key]
            # anchored at the top so a two-line subtitle grows downward
            alpha_paste(canvas, sub, W // 2, 1654 + sub.shape[0] / 2)

        if args.show_safe:
            layout.draw_safe(canvas, prof)
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
