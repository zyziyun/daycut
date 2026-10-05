#!/usr/bin/env python3
"""Three-person gallery-view call -> 1080x1920 short, two guests masked.

Two layouts (``--trio-layout``):

``stage`` (default with a ``--platform``): the person TALKING gets the big full-width tile under the
headline; the other two sit side by side below it, down to the bottom of the platform safe box, and
the captions are burned over the lower part of that row inside the platform caption box (a soft
dark gradient keeps them legible). The talker comes from ``--speakers`` (build_clips.py maps
speaker_timeline.py into final time and smooths it so the big tile only changes on a real turn,
with a 0.3 s cross-dissolve); without it the host keeps the big tile. 记笔记 panels sit in the
small row, above the captions, so they never cover whoever is speaking. Stickers and name-label
masks are applied to the SOURCE tile before it is cropped and scaled, so a masked guest stays
masked in whichever slot and at whatever size the tile is shown.

``rows`` (the pre-2026-10 layout; the only one without a platform): the two masked guests side by
side on the top row, the host full width below; panels over the guest row.

Each guest gets their own track and sticker. The sticker is pasted into a copy
of that guest's tile, clipped to it, so an ear can never bleed into a
neighbouring tile. The guest crop is a fixed window per clip, centred on the
median tracked face, so the face stays in frame without the crop wandering.

Reuses the furniture (title, chips, badge, node cards, panels, subtitles) from
render_vertical.py so both layouts stay one design.

``--platform`` (e.g. xiaohongshu, douyin, youtube-shorts) derives the canvas, the headline position
(top of the safe box), the two rows (between the headline and the caption box, 500:540 as before)
and the caption box from the platform profile. Without it the fixed layout below is used unchanged
(it was hand-fitted to the 小红书 9:16 safe zone).

Usage:
  render_trio.py CLIP.mp4 --platform xiaohongshu --speakers work/<id>.speakers.json ...
  render_trio.py CLIP.mp4 --guests-json g.json --subs subs.json \
      --title-json title.json --host-region 640,0,640,360 --out out.mp4
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import TEAL, GUEST_DEFAULT, HOST_DEFAULT, font, alpha_paste
import layout
from vstudio.config import persona
from render_vertical import (W, H, render_chip, render_hook_badge, render_node_card,
                             render_panel, render_sub, NODE_FADE, PANEL_FADE)
from vstudio.draw import text_width, wrap

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
    pad = 56
    if "\n" in text:
        # hand-set breaks: a quote is short enough to break by meaning
        lines = text.split("\n")
    else:
        # fewest lines that fit, then evened out (no orphan last line)
        lines = wrap(text, f_q, width - pad * 2, balance=True)
    # the card hugs its text instead of leaving a dead right margin
    tw = max(text_width(ln, f_q) for ln in lines)
    size = 58
    while tw > width - pad * 2 and size > 40:   # never spill past the card
        size -= 2
        f_q = font(size)
        tw = max(text_width(ln, f_q) for ln in lines)
    tw = int(tw)
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


def build_frame(title_lines, accent, size=(W, H), title_y=TITLE_Y, x_l=64, x_r=None):
    """Headline and accent line, both inside the top safe edge. Returns (image, y below the text)."""
    img = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(img)
    fs = 58
    if x_r:
        def lw(line, f):
            return sum(text_width(t, f) for t, _ in (line if isinstance(line, list) else [[line, False]]))
        while fs > 36 and max([lw(ln, font(fs)) for ln in title_lines] or [0]) > x_r - x_l:
            fs -= 2
    f_t = font(fs)
    lh = 74 if fs == 58 else int(fs * 1.28)
    y = title_y
    for line in title_lines:
        x = x_l
        runs = line if isinstance(line, list) else [[line, False]]
        for txt, is_acc in runs:
            d.text((x, y), txt, font=f_t, fill=TEAL if is_acc else (255, 255, 255))
            x += text_width(txt, f_t)
        y += lh
    if accent:
        d.rectangle([x_l, y + 22, x_l + 72, y + 26], fill=TEAL)
        d.text((x_l + 92, y + 8), accent, font=font(26), fill=(156, 163, 175))
        y += 40
    return img, y


def geometry(prof, title_lines, accent):
    """Rows and positions: the fixed layout for prof None, else derived from the profile."""
    if prof is None:
        img, _ = build_frame(title_lines, accent)
        return dict(W=W, H=H, top_y=TOP_Y, g_w=G_W, g_h=G_H, host_y=HOST_Y, host_h=HOST_H,
                    tiles_bottom=TILES_BOTTOM, sub_y=SUB_Y, cx=W / 2, chip_x0=0, badge_x=W - 24,
                    pw=None, quote_w=980, node_max_w=960, base=img, legacy=True)
    b = layout.boxes(prof)
    cw, chh = b["W"], b["H"]
    sx0, sy0, sx1, sy1 = b["safe"]
    img, y = build_frame(title_lines, accent, (cw, chh), sy0, sx0 + 4, sx1 - 12)
    tiles_top = y + 12
    tiles_bottom = b["caption"][1] - 12
    avail = tiles_bottom - tiles_top - GAP
    total = min(avail, G_H + HOST_H)
    g_h = int(round(total * G_H / (G_H + HOST_H)))
    host_h = total - g_h
    if g_h < 300:
        print(f"WARN only {avail}px for the tiles: guest row {g_h}px, host row {host_h}px")
    top_y = tiles_top + (avail - total) // 2
    host_y = top_y + g_h + GAP
    return dict(W=cw, H=chh, top_y=top_y, g_w=(cw - GAP) // 2, g_h=g_h, host_y=host_y, host_h=host_h,
                tiles_bottom=host_y + host_h, sub_y=None, cx=(sx0 + sx1) / 2, chip_x0=sx0, badge_x=sx1 - 12,
                pw=min(940, sx1 - sx0 - 24), quote_w=min(980, sx1 - sx0 - 24),
                node_max_w=min(960, (sx1 - sx0) * 0.75), base=img, legacy=False)


def fit_crop(region, out_w, out_h, cx=None, cy=None):
    """(x0, y0, w, h) RELATIVE to the tile region (x, y, w, h): the largest window with the output's
    aspect, centred on the face (source cx, cy; default the tile's upper middle) and clamped inside."""
    x, y, w, h = region
    ch = h
    cw = int(round(ch * out_w / out_h))
    if cw > w:
        cw, ch = w, int(round(w * out_h / out_w))
    fx = (cx - x) if cx is not None else w / 2
    fy = (cy - y) if cy is not None else h * 0.46
    x0 = int(round(min(max(fx - cw / 2, 0), w - cw)))
    y0 = int(round(min(max(fy - ch * 0.46, 0), h - ch)))
    return x0, y0, cw, ch


def guest_crop(region, track, g_w=G_W, g_h=G_H):
    """Fixed crop inside the guest's tile with the output tile's aspect,
    centred on the median face so a lean does not push the head out."""
    x, y, w, h = region
    ch = h
    cw = int(round(ch * g_w / g_h))
    if cw > w:                           # a short, wide row: keep the full width, trim the height
        cw, ch = w, int(round(w * g_h / g_w))
        cy = float(np.median(track["cy"])) - y
        y0 = int(round(min(max(cy - ch * 0.46, 0), h - ch)))
        return 0, y0, cw, ch
    cx = float(np.median(track["cx"])) - x
    x0 = int(round(min(max(cx - cw / 2, 0), w - cw)))
    return x0, 0, cw, ch


def fit_panel(title, bullets, pw, max_h, quote=False, quote_w=980):
    """记笔记 panel (or quote card) no taller than max_h: scaled down (to 0.6), then the last bullets
    dropped. Prints a WARN whenever the authored panel does not fit as written."""
    if quote:
        im = render_quote(title, bullets[0], quote_w)
        if im.height > max_h:
            k = max_h / im.height
            print(f"WARN quote card {im.height}px > {max_h}px room: scaled to {k:.2f}")
            im = im.resize((max(1, int(im.width * k)), max_h), Image.LANCZOS)
        return np.array(im)
    full = render_panel(title, bullets, pw)
    if full.height <= max_h:
        return np.array(full)
    keep = list(bullets)
    im = render_panel(title, keep, pw, max_h)
    while im.height > max_h and len(keep) > 1:
        keep.pop()
        im = render_panel(title, keep, pw, max_h)
    msg = f"WARN panel '{title}' is {full.height}px, room {max_h}px: "
    msg += f"scaled to {im.height}px" if len(keep) == len(bullets) else \
        f"dropped {len(bullets) - len(keep)} bullet(s) ({'; '.join(bullets[len(keep):])})"
    if im.height > max_h:
        msg += f", STILL {im.height}px: shorten it"
    print(msg)
    return np.array(im)


MIN_SMALL = 360    # stage layout: the small row never gets shorter than this (a face + the captions)


def stage_geometry(prof, title_lines, accent, tile_aspect):
    """The active-speaker layout for a platform profile: big tile, small row, panel and caption bands."""
    b = layout.boxes(prof)
    cw, chh = b["W"], b["H"]
    sx0, sy0, sx1, sy1 = b["safe"]
    cx0, cy0, cx1, cy1 = b["caption"]
    img, y = build_frame(title_lines, accent, (cw, chh), sy0, sx0 + 4, sx1 - 12)
    big_y = y + 12
    small_bottom = sy1
    # the big tile keeps the source tile's aspect (no crop, sharpest) unless the small row would
    # get too short; the small row needs room for a face above the caption box
    big_h = int(round(cw / tile_aspect))
    big_h = max(320, min(big_h, small_bottom - big_y - GAP - MIN_SMALL))
    small_y = big_y + big_h + GAP
    small_h = small_bottom - small_y
    sw = (cw - GAP) // 2
    if small_h < 260:
        print(f"WARN only {small_h}px for the small row")
    cap_top = cy0 if cy0 < small_bottom else small_bottom
    panel_top, panel_bottom = small_y + 14, cap_top - 12
    if panel_bottom - panel_top < 200:            # caption box too high: let panels use the whole row
        panel_bottom = small_bottom - 12
    # a gradient under the caption box so white captions read over the small tiles
    grad = None
    g0 = max(small_y, cap_top - 90)
    if g0 < small_bottom:
        a = np.clip((np.arange(small_bottom - g0) / max(1, cap_top - g0)), 0, 1) * 0.55
        grad = (g0, 1.0 - a[:, None, None])
    return dict(W=cw, H=chh, big=(0, big_y, cw, big_h), small=[(0, small_y, sw, small_h),
                                                               (cw - sw, small_y, sw, small_h)],
                top_y=big_y, tiles_bottom=small_bottom, panel=(panel_top, panel_bottom),
                cx=(sx0 + sx1) / 2, chip_x0=sx0, badge_x=sx1 - 12, safe=b["safe"],
                pw=min(940, sx1 - sx0 - 24), quote_w=min(980, sx1 - sx0 - 24),
                node_max_w=min(960, (sx1 - sx0) * 0.75), base=img, grad=grad)


def load_speakers(path):
    if not path:
        return None, 0.1
    d = json.load(open(path))
    return d["labels"], float(d.get("step", 0.1))


SWITCH = 0.3       # cross-dissolve when the big tile changes speaker


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--guests-json", required=True)
    ap.add_argument("--subs", required=True)
    ap.add_argument("--title-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--host-region", required=True)
    ap.add_argument("--host-track", default=None, help="face track of the host (crop centre only)")
    ap.add_argument("--speakers", default=None,
                    help="final-time active speaker JSON {step, labels} from build_clips.py "
                         "(labels = guest names | host); stage layout: the talker gets the big tile")
    ap.add_argument("--trio-layout", default=None, choices=["stage", "rows"],
                    help="stage = active speaker large, full canvas (default with --platform; persona "
                         "call_clips.trio_layout); rows = the old two-masked-guests-on-top layout")
    # accepted for build_clips.py compatibility, unused here
    ap.add_argument("--track", default=None)
    ap.add_argument("--sticker", default=None)
    ap.add_argument("--guest-region", default=None)
    ap.add_argument("--scale", type=float, default=2.40)
    ap.add_argument("--y-offset", type=float, default=-0.031)
    ap.add_argument("--crf", type=int, default=18)
    ap.add_argument("--preview", default=None, help="dump one JPG at this second and exit")
    layout.add_args(ap)
    args = ap.parse_args()
    prof = layout.resolve(args.platform, "vertical")
    nmask = layout.name_mask_from_args(args)
    mode = args.trio_layout or (persona().get("call_clips") or {}).get("trio_layout") or "stage"
    if prof is None and mode == "stage":
        if args.trio_layout == "stage":
            print("note: the stage layout needs --platform; using rows")
        mode = "rows"

    meta = json.load(open(args.title_json))
    subs = json.load(open(args.subs))
    guests = json.load(open(args.guests_json))
    hx, hy, hw, hh = (int(v) for v in args.host_region.split(","))
    host_tr = json.load(open(args.host_track)) if args.host_track else None

    if mode == "stage":
        G = stage_geometry(prof, meta["title"], meta.get("accent", ""), hw / hh)
    else:
        G = geometry(prof, meta["title"], meta.get("accent", ""))
    CW, CH = G["W"], G["H"]
    for g in guests:
        g["reg"] = [int(v) for v in g["region"].split(",")]
        g["tr"] = json.load(open(g["track"]))
        g["st"] = np.array(Image.open(g["sticker"]).convert("RGBA"))
        g["cache"] = {}
    name_rects = layout.name_rects(nmask, [tuple(g["reg"]) for g in guests], [(hx, hy, hw, hh)])
    cap_ov = layout.caption_overlay(prof, subs) if (prof is not None and not args.no_subs) else None
    base_bgr = np.array(G["base"])[:, :, ::-1].copy()
    chip_h = render_chip("Ag").height

    hook_end = float(meta.get("hook_end", 0.0))
    badge = np.array(render_hook_badge()) if hook_end > 0 else None
    nodes = [{"im": np.array(render_node_card(t, G["node_max_w"])), "s": float(at) - 0.95, "e": float(at) + 0.95}
             for at, t in meta.get("node_cards", [])]

    # ------------------------------------------------------------------ per-layout set-up
    panels = []
    if mode == "rows":
        TOP_Y_, G_W_, G_H_, HOST_Y_, HOST_H_ = G["top_y"], G["g_w"], G["g_h"], G["host_y"], G["host_h"]
        for g in guests:
            g["crop"] = guest_crop(g["reg"], g["tr"], G_W_, G_H_)
        chips = []
        for k, g in enumerate(guests):
            chips.append((np.array(render_chip(g.get("label") or GUEST_DEFAULT)),
                          max(k * (G_W_ + GAP), G["chip_x0"]), TOP_Y_ + G_H_ - 44))
        chips.append((np.array(render_chip(meta.get("host_label") or HOST_DEFAULT)),
                      G["chip_x0"], HOST_Y_ + HOST_H_ - 44))
        # panels live over the guest row, ABOVE the label chips at its bottom edge
        p_top, p_bot = TOP_Y_ + 12, TOP_Y_ + G_H_ - 44 - 8
        for anchor, dur, title, bullets in meta.get("panels", []):
            im = fit_panel(title, bullets, G["pw"] or 940, p_bot - p_top, bool(meta.get("quote_cards")),
                           G["quote_w"])
            panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                           "y": p_top + (p_bot - p_top - im.shape[0]) / 2})
        badge_y = TOP_Y_ + 20
    else:
        people = [dict(id=g["name"], kind="guest", g=g, reg=tuple(g["reg"]),
                       label=g.get("label") or GUEST_DEFAULT) for g in guests]
        people.append(dict(id="host", kind="host", g=None, reg=(hx, hy, hw, hh),
                           label=meta.get("host_label") or HOST_DEFAULT))
        ids = [p["id"] for p in people]
        for p in people:
            tr = p["g"]["tr"] if p["g"] else host_tr
            fcx = float(np.median(tr["cx"])) if tr else None
            fcy = float(np.median(tr["cy"])) if tr else None
            bx, by, bw, bh = G["big"]
            sx_, sy_, sw_, sh_ = G["small"][0]
            p["crop_big"] = fit_crop(p["reg"], bw, bh, fcx, fcy)
            p["crop_small"] = fit_crop(p["reg"], sw_, sh_, fcx, fcy)
            p["chip"] = np.array(render_chip(p["label"]))
        p_top, p_bot = G["panel"]
        for anchor, dur, title, bullets in meta.get("panels", []):
            im = fit_panel(title, bullets, G["pw"], p_bot - p_top, bool(meta.get("quote_cards")), G["quote_w"])
            panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                           "y": p_top + (p_bot - p_top - im.shape[0]) / 2})
        badge_y = G["big"][1] + 20
        spk, spk_step = load_speakers(args.speakers)
        if spk is not None:
            bad = sorted({x for x in spk if x not in ids})
            if bad:
                print(f"WARN speaker labels {bad} match no tile ({ids}); they keep the host large")

        def active_at(t):
            if not spk:
                return "host"
            x = spk[min(len(spk) - 1, max(0, int(t / spk_step + 1e-6)))]
            return x if x in ids else "host"

        def switch_info(t):
            """(current, previous, blend 0..1): blend < 1 inside the dissolve after a change."""
            cur = active_at(t)
            if not spk:
                return cur, cur, 1.0
            k = int(t / spk_step + 1e-6)
            back = int(SWITCH / spk_step + 0.5)
            for j in range(1, back + 1):
                if k - j < 0:
                    break
                prev = active_at((k - j) * spk_step)
                if prev != cur:
                    ts = (k - j + 1) * spk_step
                    return cur, prev, min(1.0, max(0.0, (t - ts) / SWITCH))
            return cur, cur, 1.0

    def sticker_tile(g, src, i):
        """The guest's source tile with the sticker pasted over the tracked face (clipped to it)."""
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
        return tile

    def stage_tiles(canvas, tiles, big_id):
        """Paste every person's (already masked) tile into its slot for big_id talking."""
        smalls = [p for p in people if p["id"] != big_id]
        slots = [(p, G["big"], p["crop_big"], True) for p in people if p["id"] == big_id]
        slots += [(p, G["small"][k], p["crop_small"], False) for k, p in enumerate(smalls[:2])]
        for p, (ox, oy, ow, oh), (cx0, cy0, cw, ch), big in slots:
            t = tiles[p["id"]]
            canvas[oy:oy + oh, ox:ox + ow] = cv2.resize(t[cy0:cy0 + ch, cx0:cx0 + cw], (ow, oh),
                                                        interpolation=cv2.INTER_CUBIC)
        return slots

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    proc = None
    if not args.preview:
        proc = subprocess.Popen([
            "ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{CW}x{CH}", "-r", str(fps), "-i", "-",
            "-i", args.video, "-map", "0:v", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf),
            "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-color_range", "tv",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", args.out,
        ], stdin=subprocess.PIPE)

    TOP_Y_, TILES_BOTTOM_ = G["top_y"], G["tiles_bottom"]
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
        # names and faces are hidden on SOURCE pixels, before any crop or scale
        layout.mask_names(src, name_rects, nmask["mode"])

        if mode == "rows":
            for k, g in enumerate(guests):
                tile = sticker_tile(g, src, i)
                cx0, cy0, cw, ch = g["crop"]
                out = cv2.resize(tile[cy0:cy0 + ch, cx0:cx0 + cw], (G_W_, G_H_), interpolation=cv2.INTER_CUBIC)
                ox = k * (G_W_ + GAP)
                canvas[TOP_Y_:TOP_Y_ + G_H_, ox:ox + G_W_] = out
            if G["legacy"]:
                ch = int(round(hw * HOST_H / W))           # keep aspect: 640 wide -> 320 tall
                y0 = hy + min(HOST_CROP, hh - ch)
            else:
                _, y0, _, ch = layout.vcrop((hx, hy, hw, hh), CW, HOST_H_)
            host = cv2.resize(src[y0:y0 + ch, hx:hx + hw], (CW, HOST_H_), interpolation=cv2.INTER_CUBIC)
            canvas[HOST_Y_:HOST_Y_ + HOST_H_] = host
        else:
            tiles = {p["id"]: (sticker_tile(p["g"], src, i) if p["g"] else src[hy:hy + hh, hx:hx + hw])
                     for p in people}
            cur, prev, kk = switch_info(t)
            slots = stage_tiles(canvas, tiles, cur)
            if kk < 1.0:
                other = base_bgr.copy()
                stage_tiles(other, tiles, prev)
                canvas = cv2.addWeighted(canvas, kk, other, 1.0 - kk, 0)
            if G["grad"] is not None:
                g0, a = G["grad"]
                band = canvas[g0:g0 + a.shape[0]]
                canvas[g0:g0 + a.shape[0]] = (band * a).astype(np.uint8)
            chips = []
            for p, (ox, oy, ow, oh), _, big in slots:
                cx_ = max(ox + 16, G["chip_x0"])
                cy_ = (oy + oh - chip_h - 16) if big else (oy + 16)
                chips.append((p["chip"], cx_, cy_))

        cur_node = next((n for n in nodes if n["s"] - NODE_FADE <= t <= n["e"] + NODE_FADE), None)
        if cur_node is not None:
            if t < cur_node["s"]:
                kk = (t - (cur_node["s"] - NODE_FADE)) / NODE_FADE
            elif t > cur_node["e"]:
                kk = 1 - (t - cur_node["e"]) / NODE_FADE
            else:
                kk = 1.0
            band = canvas[TOP_Y_:TILES_BOTTOM_]
            canvas[TOP_Y_:TILES_BOTTOM_] = (band * (1 - 0.68 * kk)).astype(np.uint8)
            alpha_paste(canvas, cur_node["im"], G["cx"], TOP_Y_ + (TILES_BOTTOM_ - TOP_Y_) / 2, opacity=kk)

        if badge is not None and t < hook_end:
            op = min(1.0, (hook_end - t) / 0.4)
            # on the guest row's top-right, not the screen's top edge, which
            # the platform's nav bar covers
            alpha_paste(canvas, badge, G["badge_x"] - badge.shape[1] / 2,
                        badge_y + badge.shape[0] / 2, opacity=op)

        # rows: chips flush to each tile's bottom-left, over the call app's name badges;
        # stage: the big tile's bottom-left, the small tiles' top-left (captions sit at their bottom);
        # drawn BEFORE the 记笔记 panels so a panel is never cut by a chip
        for img, ox, oy in chips:
            alpha_paste(canvas, img, ox + img.shape[1] / 2, oy + img.shape[0] / 2)

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
            alpha_paste(canvas, p["im"], G["cx"], p["y"] + p["im"].shape[0] / 2 + dy, opacity=op)

        cur = None if (args.no_subs or cap_ov) else next((s for s in subs if s["start"] <= t < s["end"]), None)
        if cap_ov:
            cap_ov(t, canvas)
        if cur:
            key = cur["text"]
            if key not in sub_cache:
                sub_cache[key] = np.array(render_sub(key))
            sub = sub_cache[key]
            alpha_paste(canvas, sub, W // 2, SUB_Y + sub.shape[0] / 2)

        if args.show_safe:
            layout.draw_safe(canvas, prof)
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
