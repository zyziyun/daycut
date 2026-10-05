#!/usr/bin/env python3
"""Turn a two-tile call recording (Zoom / Meet / Teams gallery view) into a 1080x1920 short.

One pass: paste the sticker over the guest's tracked face, stack the two
tiles on a black + accent frame, and burn the subtitles. Many ffmpeg builds have
neither drawtext nor libass, so every glyph is drawn with PIL here.

Usage:
  render_vertical.py CLIP.mp4 --track t.json --sticker cat.png \
      --subs subs.json --title-json title.json --out out.mp4
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, json, os, re, subprocess
import cv2
import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from style import (TEAL, DIM, WHITE, RED, YEL, font, HOOK_BADGE, NODE_EYEBROW, NOTE_TAG,
                   GUEST_DEFAULT, HOST_DEFAULT)

W, H = 1080, 1920

TILE_H = 608
TOP_Y = 330
GAP = 14
BOT_Y = TOP_Y + TILE_H + GAP          # 952
TILES_BOTTOM = BOT_Y + TILE_H         # 1560

def text_w(draw, s, f):
    return draw.textbbox((0, 0), s, font=f)[2]


def render_chip(label, fnt):
    """Name tag that sits flush to the left edge so the call app's name badge
    underneath is fully hidden -- hence the small corner radius, not a pill."""
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad_x, pad_y = 24, 12
    w = max(text_w(tmp, label, fnt) + pad_x * 2, 230)
    h = fnt.size + pad_y * 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=10,
                        fill=(0, 0, 0, 255), outline=TEAL + (220,), width=2)
    d.text(((w - text_w(tmp, label, fnt)) // 2, pad_y - 3), label, font=fnt, fill=WHITE)
    return im


def render_hook_badge():
    """Marks the montage up front as a preview, so the jump cuts read as
    intentional rather than as a broken edit."""
    f = font(32)
    txt = HOOK_BADGE
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    w, h = text_w(tmp, txt, f) + 56, f.size + 28
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=RED + (242,))
    d.text((28, 12), txt, font=f, fill=WHITE)
    return im


NODE_FADE = 0.35


def render_node_card(title):
    """Shown over each internal edit. The viewer needs to know the jump was
    deliberate, so the card names the section we are jumping into."""
    f_eye, f_t = font(30), font(56)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    eyebrow = NODE_EYEBROW
    w = max(text_w(tmp, title, f_t), text_w(tmp, eyebrow, f_eye)) + 120
    w = min(max(w, 620), 960)
    h = 216
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=24, fill=(10, 12, 16, 247),
                        outline=TEAL + (235,), width=3)
    d.rectangle([48, 60, 48 + 72, 65], fill=TEAL)
    d.text((48, 86), eyebrow, font=f_eye, fill=TEAL)
    d.text((48, 128), title, font=f_t, fill=WHITE)
    return im


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
            x += text_w(d, txt, f_t)
        y += lh

    d.rectangle([72, TILES_BOTTOM + 36, 72 + 96, TILES_BOTTOM + 41], fill=TEAL)
    if accent:
        d.text((72 + 128, TILES_BOTTOM + 22), accent, font=font(28), fill=DIM)
    return img


SUB_MAX_W = 980


def _nudge_off_word(line, cut):
    """Never split inside a run of latin/digits."""
    if 0 < cut < len(line) and line[cut - 1].isascii() and line[cut].isascii():
        back = cut
        while back > 1 and line[back - 1].isascii():
            back -= 1
        if back > 4:
            return back
    return cut


def wrap_sub(line, f, tmp):
    """Split a long subtitle. Two lines get balanced around the middle rather
    than a full first line and an orphan second one."""
    if text_w(tmp, line, f) <= SUB_MAX_W:
        return [line]
    hard = len(line)
    while hard > 1 and text_w(tmp, line[:hard], f) > SUB_MAX_W:
        hard -= 1
    if text_w(tmp, line[hard:], f) <= SUB_MAX_W:
        cut = _nudge_off_word(line, len(line) // 2)
        if text_w(tmp, line[:cut], f) <= SUB_MAX_W and text_w(tmp, line[cut:], f) <= SUB_MAX_W:
            return [line[:cut], line[cut:]]
    cut = _nudge_off_word(line, hard)
    return [line[:cut]] + wrap_sub(line[cut:], f, tmp)


def render_sub(line):
    """Subtitle as its own RGBA strip so it can be cached and alpha-pasted."""
    f = font(48)
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows = wrap_sub(line, f, tmp)
    pad, lh = 20, 64
    w = max(text_w(tmp, r, f) for r in rows) + pad * 2
    im = Image.new("RGBA", (w, lh * len(rows) + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, r in enumerate(rows):
        d.text(((w - text_w(tmp, r, f)) // 2, pad + i * lh), r, font=f, fill=WHITE,
               stroke_width=6, stroke_fill=(0, 0, 0, 235))
    return im


PW = 940
PANEL_FADE = 0.30


def _toks(s):
    """Split for wrapping, keeping latin/number runs whole."""
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
    """记笔记 card, same design language as the talking-head workflow's notes
    panels (dark card, brand-accent header, highlight 记笔记 tag, accent-dot
    bullets), scaled up for a 1080-wide vertical frame."""
    ft, fbu, ftag = font(46, False), font(40, False), font(32, False)
    PX, PY, HEAD, BG, DOT = 30, 26, 88, 20, 11
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    wr = [_wrap(b, fbu, PW - PX * 2 - 26, tmp) for b in bullets]
    a, dsc = fbu.getmetrics()
    blh = a + dsc
    n = sum(len(w) for w in wr)
    Hh = HEAD + PY * 2 + n * blh + (len(bullets) - 1) * BG

    im = Image.new("RGBA", (PW, Hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, PW - 1, Hh - 1], radius=22, fill=(16, 18, 24, 242))
    d.rounded_rectangle([0, 0, PW - 1, HEAD + 22], radius=22, fill=RED + (255,))
    d.rectangle([0, HEAD - 2, PW - 1, HEAD + 22], fill=(16, 18, 24, 242))

    tb = d.textbbox((0, 0), title, font=ft)
    d.text((28, (HEAD - (tb[3] - tb[1])) // 2 - tb[1]), title, font=ft, fill=WHITE)

    tag = NOTE_TAG
    tt = text_w(d, tag, ftag)
    px = PW - tt - 28 - 26
    if 28 + text_w(d, title, ft) > px - 12:
        print(f"WARN panel title runs under the 记笔记 tag -> {title}")
    d.rounded_rectangle([px, 20, px + tt + 26, 20 + 46], radius=13, fill=YEL + (255,))
    d.text((px + 13, 20 + 6), tag, font=ftag, fill=(20, 20, 20, 255))

    y = HEAD + PY
    for w in wr:
        cy = y + blh // 2
        d.ellipse([28, cy - DOT // 2, 28 + DOT, cy + DOT // 2], fill=RED + (255,))
        for ln in w:
            d.text((28 + DOT + 16, y), ln, font=fbu, fill=(245, 246, 250, 255))
            y += blh
        y += BG
    return im


def alpha_paste(dst_bgr, rgba, cx, cy, opacity=1.0):
    sh, sw = rgba.shape[:2]
    x0, y0 = int(round(cx - sw / 2)), int(round(cy - sh / 2))
    Hh, Ww = dst_bgr.shape[:2]
    sx0, sy0 = max(0, -x0), max(0, -y0)
    sx1, sy1 = sw - max(0, x0 + sw - Ww), sh - max(0, y0 + sh - Hh)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    patch = rgba[sy0:sy1, sx0:sx1]
    dx0, dy0 = max(0, x0), max(0, y0)
    a = patch[:, :, 3:4].astype(np.float32) / 255.0 * opacity
    rgb = patch[:, :, :3][:, :, ::-1].astype(np.float32)
    roi = dst_bgr[dy0:dy0 + patch.shape[0], dx0:dx0 + patch.shape[1]].astype(np.float32)
    dst_bgr[dy0:dy0 + patch.shape[0], dx0:dx0 + patch.shape[1]] = \
        (rgb * a + roi * (1 - a)).astype(np.uint8)


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
    args = ap.parse_args()

    meta = json.load(open(args.title_json, encoding="utf-8"))
    subs = json.load(open(args.subs, encoding="utf-8"))
    if not args.no_mask and not (args.track and args.sticker):
        sys.exit("--track and --sticker are required unless --no-mask")
    if not args.no_mask:
        tr = json.load(open(args.track))
        cxs, cys, ws = tr["cx"], tr["cy"], tr["w"]

    gx, gy, gw, gh = (int(v) for v in args.guest_region.split(","))
    hx, hy, hw, hh = (int(v) for v in args.host_region.split(","))

    base = build_frame_png(meta["title"], meta.get("accent", ""))
    base_bgr = np.array(base)[:, :, ::-1].copy()
    f_chip = font(30)
    chips = [
        (np.array(render_chip(meta.get("guest_label") or GUEST_DEFAULT, f_chip)), TOP_Y + TILE_H - 44),
        (np.array(render_chip(meta.get("host_label") or HOST_DEFAULT, f_chip)), BOT_Y + TILE_H - 44),
    ]

    # 记笔记 panels sit over the guest's tile: the face there is a sticker
    # already, so nothing is lost, and the speaker stays visible below.
    panels = []
    for anchor, dur, title, bullets in meta.get("panels", []):
        im = np.array(render_panel(title, bullets))
        if im.shape[0] > TILE_H - 24:
            print(f"WARN panel taller than the tile ({im.shape[0]}px): {title}")
        panels.append({"im": im, "s": float(anchor), "e": float(anchor) + float(dur),
                       "title": title,
                       "y": TOP_Y + (TILE_H - im.shape[0]) / 2})
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
        nodes.append({"im": np.array(render_node_card(title)),
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
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
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

        if not args.no_mask:
            j = min(i, len(cxs) - 1)
            tw = max(24, int(round(ws[j] * args.scale)))
            if tw not in st_cache:
                th = int(round(tw * s_h0 / s_w0))
                st_cache[tw] = np.array(Image.fromarray(sticker).resize((tw, th), Image.LANCZOS))
            st = st_cache[tw]
            alpha_paste(src, st, cxs[j], cys[j] + args.y_offset * st.shape[0])

        canvas = base_bgr.copy()
        for (rx, ry, rw, rh), oy in ((( gx, gy, gw, gh), TOP_Y), ((hx, hy, hw, hh), BOT_Y)):
            tile = cv2.resize(src[ry:ry + rh, rx:rx + rw], (W, TILE_H), interpolation=cv2.INTER_AREA)
            canvas[oy:oy + TILE_H, 0:W] = tile
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
            band = canvas[TOP_Y:TILES_BOTTOM]
            canvas[TOP_Y:TILES_BOTTOM] = (band * (1 - 0.68 * k)).astype(np.uint8)
            alpha_paste(canvas, cur_node["im"], W / 2,
                        TOP_Y + (TILES_BOTTOM - TOP_Y) / 2, opacity=k)

        if badge is not None and t < hook_end:
            op = min(1.0, (hook_end - t) / 0.4)
            # right-aligned on the eyebrow row: the only band with free space
            alpha_paste(canvas, badge, W - 72 - badge.shape[1] / 2,
                        107 + badge.shape[0] / 2 - 30, opacity=op)

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
            alpha_paste(canvas, p["im"], W / 2,
                        p["y"] + p["im"].shape[0] / 2 + dy, opacity=op)

        # chips go on after the tiles so the call app's name badges stay covered
        for img, oy in chips:
            alpha_paste(canvas, img, img.shape[1] / 2, oy + img.shape[0] / 2)

        cur = next((s for s in subs if s["start"] <= t < s["end"]), None)
        if cur:
            key = cur["text"]
            if key not in sub_cache:
                sub_cache[key] = np.array(render_sub(key))
            sub = sub_cache[key]
            # anchored at the top so a two-line subtitle grows downward
            alpha_paste(canvas, sub, W // 2, 1654 + sub.shape[0] / 2)

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
