#!/usr/bin/env python3
"""Scrapbook torn-paper cover, full-bleed (default 1920x1080, any size works).

Several large photo fragments are layered with ragged torn-paper edges so they
overlap and fill the whole frame. The LAST piece is the hero (biggest, centered).
A darkened backing photo sits underneath so any gap between torn edges reveals
scenery, never a black seam. No text by default; --title adds an optional
scrapbook label using the vstudio font roles.

    python3 make_cover.py --out cover.png --hero hero.jpg \\
        --frames a.jpg b.jpg c.jpg d.jpg e.jpg --base wide.jpg
    python3 make_cover.py --out cover_v.png --size 1080x1920 --hero h.jpg --frames a.jpg b.jpg c.jpg d.jpg
    python3 make_cover.py --out cover.png --config cover.json     # explicit layout

--config schema (pixel coords in the given size; last piece drawn on top):
{"size":[1920,1080], "bg":"#34301f", "base":"wide.jpg", "title":"optional",
 "pieces":[{"img":"a.jpg","left":-90,"top":40,"w":900,"h":760,"rot":2,
            "bgsize":130,"bgpos":"center 55%","seed":11}, ...]}
bgsize = zoom % (>=100) applied after cover-fit; bgpos = focus point (CSS position). The auto layout sets
bgpos on each piece's largest face (vstudio.face, else OpenCV Haar; --no-faces keeps the fixed points).
Output is exactly --size px (--scale 2 for a 2x render; the log prints the real pixel size).

Renderer: vstudio.render.html_to_png - the first working Chrome/Chromium/Edge ($CHROME,
PATH, common macOS/Linux/Windows paths), else Playwright.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, base64, html, json, math, mimetypes, os

from vstudio import render
from vstudio.config import persona

# Hand-tuned full-bleed layouts on a 1920x1080 canvas (rescaled for other sizes).
# (left, top, w, h, rot, zoom%, focus, seed). LAST entry = hero. Each photo is
# object-fit:cover inside its piece, then zoomed by zoom% around the focus point
# (CSS position, e.g. "center 55%"), so any frame aspect fills any slot.
LAYOUTS = {
    6: [
        (-90, 40, 900, 760, 2, 110, "center 55%", 11),
        (1060, -90, 980, 740, -2, 112, "center 50%", 22),
        (-40, 520, 960, 660, -3, 106, "center 60%", 33),
        (980, 500, 1040, 700, 2, 104, "center 55%", 44),
        (500, -100, 860, 580, 4, 115, "center 55%", 55),
        (470, 210, 1000, 700, -2, 110, "48% 58%", 66),
    ],
    5: [
        (-90, 40, 980, 820, 2, 110, "center 55%", 11),
        (1040, -90, 1000, 800, -2, 112, "center 50%", 22),
        (-40, 540, 1000, 700, -3, 106, "center 60%", 33),
        (1000, 520, 1060, 720, 2, 104, "center 55%", 44),
        (430, 180, 1060, 740, -2, 110, "48% 58%", 55),
    ],
}


def data_uri(path):
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as f:
        return f"data:{mime};base64," + base64.b64encode(f.read()).decode()


def face_focus(path):
    """CSS object-position ("x% y%") on the largest face in an image, or None. vstudio.face (MediaPipe) when
    installed, else OpenCV's bundled Haar cascade. object-position p% puts the image's p% point at the
    piece's p% point, so the face stays inside the piece whatever its aspect, and the zoom (transform-origin
    = the same point) grows around it."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        im.thumbnail((1280, 1280))
        bgr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
    except Exception:                                         # noqa: BLE001 - unreadable: keep the default
        return None
    h, w = bgr.shape[:2]
    box = None
    try:
        from vstudio import face as F
        lm = F.landmarker(num_faces=4)
        f = F.main_face(F.detect(lm, bgr), min_area_frac=0.002, shape=bgr.shape)
        if f is not None:
            p = f["pts"]
            box = (float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max()))
    except Exception:                                         # noqa: BLE001 - no mediapipe / model
        try:
            casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            fs = casc.detectMultiScale(g, 1.1, 5, minSize=(max(24, w // 40), max(24, w // 40)))
            if len(fs):
                x, y, fw, fh = max(fs, key=lambda r: r[2] * r[3])
                box = (float(x), float(y), float(x + fw), float(y + fh))
        except Exception:                                     # noqa: BLE001
            box = None
    if box is None:
        return None
    cx, cy = (box[0] + box[2]) / 2 / w, (box[1] + box[3]) / 2 / h
    return f"{100 * min(max(cx, 0.0), 1.0):.0f}% {100 * min(max(cy, 0.0), 1.0):.0f}%"


def auto_pieces(frames, hero, W, H, faces=True):
    imgs = frames + [hero]
    n = len(imgs)
    portrait = H > W
    slots = None if portrait else LAYOUTS.get(n)
    if slots:
        sx, sy = W / 1920, H / 1080
        slots = [(int(l * sx), int(t * sy), int(w * sx), int(h * sy), r, b, p, s)
                 for l, t, w, h, r, b, p, s in slots]
    else:
        # generic grid with generous overlap; hero enlarged and centered on top
        rest = n - 1
        cols = (2 if portrait else 3) if rest > 4 else (1 if portrait and rest <= 2 else 2)
        rows = max(1, math.ceil(rest / cols))
        cw, ch = W / cols, H / rows
        slots = []
        for k in range(rest):
            r, c = divmod(k, cols)
            slots.append((int(-60 + c * cw), int(-40 + r * ch), int(cw + 180), int(ch + 200),
                          [-3, 2, -2, 3][k % 4], 110, "center 55%", 11 * (k + 1)))
        hw, hh = (int(W * 0.8), int(H * 0.42)) if portrait else (int(W * 0.52), int(H * 0.65))
        slots.append(((W - hw) // 2, (H - hh) // 2, hw, hh, -2, 110, "48% 58%", 99))
    out = []
    for img, (l, t, w, h, rot, bgs, bgp, seed) in zip(imgs, slots):
        ff = face_focus(img) if faces else None
        out.append({"img": img, "left": l, "top": t, "w": w, "h": h, "rot": rot,
                    "bgsize": bgs, "bgpos": ff or bgp, "seed": seed, "focus": "face" if ff else "default"})
    return out


def title_html(cfg, fonts, W, H):
    t = cfg.get("title")
    if not t:
        return "", ""
    is_cjk = any(ord(c) >= 0x2E80 for c in t)
    role = "cjk-bold" if is_cjk else "serif-italic"
    face = ""
    if role in fonts:
        face = render.font_face_css({"CoverTitle": fonts[role]})
    tape = (persona().get("vlog") or {}).get("cover_tape", "#c9b98f")
    size = int(min(W, H) * 0.075)
    css = (face + f".title{{position:absolute;left:50%;bottom:{int(H * 0.07)}px;transform:translateX(-50%) rotate(-2deg);"
           f"background:#f7f3ea;padding:{size // 4}px {size // 2}px;font:{size}px CoverTitle,serif;"
           f"color:#1c1a17;box-shadow:0 10px 18px rgba(0,0,0,.4);white-space:nowrap;"
           f"border-bottom:6px solid {tape};"
           f"filter:url(#tornT)}}")
    return css, f'<div class="title">{html.escape(t)}</div>'


def build_html(cfg, fonts):
    W, H = cfg.get("size", [1920, 1080])
    bg = cfg.get("bg", "#34301f")
    base_src = data_uri(cfg["base"]) if cfg.get("base") else data_uri(cfg["pieces"][-1]["img"])
    rough = cfg.get("roughness", 13)
    seeds = [p["seed"] for p in cfg["pieces"]]
    filters = "".join(f'''
      <filter id="torn{s}" x="-8%" y="-8%" width="116%" height="116%">
        <feTurbulence type="fractalNoise" baseFrequency="0.011 0.013" numOctaves="3" seed="{s}" result="n"/>
        <feDisplacementMap in="SourceGraphic" in2="n" scale="{rough}" xChannelSelector="R" yChannelSelector="G"/>
      </filter>''' for s in seeds)
    filters += f'''
      <filter id="tornT" x="-8%" y="-30%" width="116%" height="160%">
        <feTurbulence type="fractalNoise" baseFrequency="0.03" numOctaves="2" seed="7" result="n"/>
        <feDisplacementMap in="SourceGraphic" in2="n" scale="6" xChannelSelector="R" yChannelSelector="G"/>
      </filter>'''
    pieces = "".join(f'''
      <div class="piece" style="left:{p['left']}px;top:{p['top']}px;width:{p['w']}px;height:{p['h']}px;
          transform:rotate({p['rot']}deg);filter:url(#torn{p['seed']}) drop-shadow(0 12px 18px rgba(0,0,0,.45));">
        <div class="mat"><div class="ph"><img src="{data_uri(p['img'])}" style="object-position:{p['bgpos']};
          transform-origin:{p['bgpos']};transform:scale({max(p['bgsize'], 100) / 100:.3f});"></div></div>
      </div>''' for p in cfg["pieces"])
    tcss, tdiv = title_html(cfg, fonts, W, H)
    return f'''<!doctype html><html><head><meta charset="utf-8"><style>
      *{{margin:0;padding:0;box-sizing:border-box}}
      html,body{{width:{W}px;height:{H}px;overflow:hidden;background:{bg}}}
      .base{{position:absolute;inset:0;background-size:cover;background-position:center;
        filter:brightness(.72) saturate(1.05)}}
      .piece{{position:absolute}}
      .mat{{width:100%;height:100%;background:#f7f3ea;padding:12px}}
      .ph{{width:100%;height:100%;overflow:hidden}}
      .ph img{{display:block;width:100%;height:100%;object-fit:cover}}
      {tcss}
    </style></head><body>
      <svg width="0" height="0">{filters}</svg>
      <div class="base" style="background-image:url('{base_src}')"></div>
      {pieces}
      {tdiv}
    </body></html>'''


def main():
    ap = argparse.ArgumentParser(description="Scrapbook torn-paper full-bleed cover.")
    ap.add_argument("--out", required=True, help="output PNG")
    ap.add_argument("--hero", help="clearest / most expressive frame (big, centered, on top)")
    ap.add_argument("--frames", nargs="*", default=[], help="other frames (4-5 recommended)")
    ap.add_argument("--base", help="wide frame for the darkened backing (default: hero)")
    ap.add_argument("--config", help="explicit layout JSON (see docstring)")
    ap.add_argument("--size", default=None, help="WxH canvas, e.g. 1080x1920 for vertical (default 1920x1080)")
    ap.add_argument("--platform", help="size from vstudio.platform.cover_size, e.g. xiaohongshu:full -> 1080x1440")
    ap.add_argument("--title", help="optional scrapbook label (default: no text)")
    ap.add_argument("--scale", type=int, default=1, help="device scale (default 1 = exactly --size px; 2 => 2x px)")
    ap.add_argument("--no-faces", action="store_true", help="auto layout: keep the fixed focus points instead of "
                                                          "centring each piece on its largest face")
    a = ap.parse_args()
    if a.platform and not a.size:
        from vstudio import platform as P
        prof = P.profile(a.platform)
        cw, ch = P.cover_size(prof)
        a.size = f"{cw}x{ch}"
        print(f"{prof.key}: cover {a.size}; keep any title inside {P.cover_title_safe(prof)}")
    a.size = a.size or "1920x1080"

    if a.config:
        with open(a.config) as f:
            cfg = json.load(f)
        cdir = os.path.dirname(os.path.abspath(a.config))
        fix = lambda p: p if os.path.isabs(p) else os.path.join(cdir, p)
        for p in cfg["pieces"]:
            p["img"] = fix(p["img"])
        if cfg.get("base"):
            cfg["base"] = fix(cfg["base"])
        if a.base:
            cfg["base"] = a.base
    else:
        if not a.hero or not a.frames:
            sys.exit("provide --hero and --frames, or a --config")
        W, H = (int(v) for v in a.size.lower().split("x"))
        cfg = {"size": [W, H], "base": a.base, "pieces": auto_pieces(a.frames, a.hero, W, H, faces=not a.no_faces)}
        nf = sum(p["focus"] == "face" for p in cfg["pieces"])
        print(f"auto layout: {nf}/{len(cfg['pieces'])} pieces centred on a face (bgpos in the --config schema)")
    if a.title:
        cfg["title"] = a.title

    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.out))[0]
    fonts = {}
    if cfg.get("title"):   # {role: filename} in <out>/assets/fonts/ (missing roles warn, title falls back to serif)
        fonts = render.stage_fonts(os.path.join(out_dir, "assets", "fonts"), ["cjk-bold", "serif-italic"])
    html_path = os.path.join(out_dir, stem + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(cfg, fonts))
    W, H = cfg.get("size", [1920, 1080])
    chrome = render.find_chrome()
    render.html_to_png(html_path, a.out, size=(W, H), scale=a.scale, use_persona=False, fonts=False)
    how = os.path.basename(chrome) if chrome else "playwright"
    try:
        from PIL import Image
        with Image.open(a.out) as im:
            pw, ph = im.size
    except Exception:                                         # noqa: BLE001
        pw, ph = W * a.scale, H * a.scale
    print(f"cover -> {a.out}  ({pw}x{ph} px = {W}x{H} layout @{a.scale}x via {how}; html: {html_path})")


if __name__ == "__main__":
    main()
