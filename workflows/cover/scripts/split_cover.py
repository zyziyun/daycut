#!/usr/bin/env python3
"""Premium split cover: face photo left, dark panel right (quote, title, thumbnail, chips, stamps).

Driven by a JSON config (see ../examples/split_cover.example.json). Renders one or more sizes
(e.g. 4:3 for 小红书 horizontal posts, 16:9 for YouTube/B站) from the same config.

  python3 split_cover.py work/split_cover.json

Paths in the config are relative to the config file. Colours default to persona.brand
(ground / highlight / accent / ink); fonts come from vstudio.config.font().
Optional "retouch": {...} runs vstudio.retouch on the photo first (cached next to the photo).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import json

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from vstudio.config import font, persona


def rgb(c):
    if isinstance(c, (list, tuple)):
        return tuple(int(v) for v in c[:3])
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def F(role, size):
    return ImageFont.truetype(font(role), size)


def tw(d, text, f):
    return d.textbbox((0, 0), text, font=f)[2]


def load_photo(cfg, base):
    src = base / cfg["photo"]
    rt = cfg.get("retouch")
    if rt:
        cached = src.with_name(src.stem + ".retouched.png")
        if not cached.exists() or cfg.get("retouch_force"):
            import cv2
            from vstudio import face as FA
            from vstudio.retouch import retouch
            img = cv2.imread(str(src))
            cv2.imwrite(str(cached), retouch(img, lm=FA.landmarker(1), **(rt if isinstance(rt, dict) else {})))
            print("retouched ->", cached)
        src = cached
    im = Image.open(src).convert("RGB")
    lift = float(cfg.get("photo_lift", 1.0))
    return im.point(lambda v: min(255, int(v * lift))) if lift != 1.0 else im


def face_center_x(photo):
    """Fraction of the photo width at the main face centre (0.5 if no face / no model)."""
    try:
        import cv2
        import numpy as np
        from vstudio import face as FA
        bgr = cv2.cvtColor(np.asarray(photo), cv2.COLOR_RGB2BGR)
        f = FA.main_face(FA.detect(FA.landmarker(1), bgr))
        return float(f["pts"][:, 0].mean() / photo.width) if f is not None else 0.5
    except Exception as e:  # noqa: BLE001 - layout must still render without the model
        print("face detection skipped:", e)
        return 0.5


def draw_title(d, lines, highlights, x, y, panel_w, size, ink, hl, line_gap):
    f = F("cjk-bold", size)
    while size > 40 and max(tw(d, ln, f) for ln in lines) > panel_w:
        size -= 4; f = F("cjk-bold", size)
    for i, ln in enumerate(lines):
        yy = y + i * int(size * line_gap)
        d.text((x, yy), ln, font=f, fill=ink)
        for h in highlights:                       # overdraw highlighted substrings in place
            start = ln.find(h)
            while start >= 0:
                d.text((x + tw(d, ln[:start], f), yy), h, font=f, fill=hl)
                start = ln.find(h, start + len(h))
    return y + len(lines) * int(size * line_gap)


def build(cfg, base, photo, cx_frac, out):
    br = persona().get("brand", {}) or {}
    col = cfg.get("colors", {})
    GROUND = rgb(col.get("ground", br.get("ground", "#0B1020")))
    HL = rgb(col.get("highlight", br.get("highlight", "#F4D35E")))
    ACC = rgb(col.get("accent", br.get("accent", "#FF2442")))
    INK = rgb(col.get("ink", br.get("ink", "#ECEEF2")))
    DIM = rgb(col.get("dim", "#969EB2"))
    W, H = out["size"]; pw = int(out.get("photo_w", W * 0.5)); fade = int(out.get("fade", 220))

    img = Image.new("RGB", (W, H), GROUND)
    s = H / photo.height
    ph = photo.resize((max(1, int(photo.width * s)), H), Image.LANCZOS)
    x0 = int(cx_frac * ph.width - pw / 2 + out.get("photo_shift", cfg.get("photo_shift", 0)))
    x0 = max(0, min(ph.width - pw, x0))
    img.paste(ph.crop((x0, 0, x0 + min(pw, ph.width), H)), (0, 0))
    g = Image.new("L", (fade, H)); gd = ImageDraw.Draw(g)
    for i in range(fade):
        gd.line([(i, 0), (i, H)], fill=int(255 * (i / fade) ** 1.6))
    img.paste(Image.new("RGB", (fade, H), GROUND), (pw - fade, 0), g)

    px = pw - int(out.get("overlap", 40)); pwid = W - px - 60
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow_c = rgb(cfg.get("glow", [40, 60, 120]))
    ImageDraw.Draw(glow).ellipse([px - 100, int(H * .17), W + 150, H - 80], fill=(*glow_c, 70))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)

    k = H / 1080
    y = int(96 * k)
    q = cfg.get("quote")
    if q:
        qs = int(q.get("size", 34 if W < 1600 else 38) * k)
        while qs > 18 and tw(d, q["text"], F("serif-italic", qs)) > pwid:
            qs -= 2
        d.text((px, y), q["text"], font=F("serif-italic", qs), fill=HL)
        if q.get("by"):
            d.text((px, y + int(qs * 1.35)), q["by"], font=F("serif-italic", int(qs * .82)), fill=DIM)
        y = int(222 * k)
    t = cfg.get("title", {})
    y = draw_title(d, t.get("lines", []), t.get("highlight", []), px, y, pwid,
                   int(t.get("size", 94) * k), INK, HL, t.get("line_gap", 1.28))

    th_cfg = cfg.get("thumbnail")
    if th_cfg:
        th = Image.open(base / th_cfg["path"]).convert("RGB")
        c = th_cfg.get("crop")                      # fractions x0,y0,x1,y1
        if c:
            th = th.crop((int(c[0] * th.width), int(c[1] * th.height), int(c[2] * th.width), int(c[3] * th.height)))
        tw_ = pwid; thh = int(th.height * tw_ / th.width)
        thh = min(thh, H - y - int(200 * k)); tw_ = int(th.width * thh / th.height)
        th = th.resize((tw_, thh), Image.LANCZOS)
        r = int(18 * k); cy = y + int(28 * k)
        m = Image.new("L", (tw_, thh), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, tw_ - 1, thh - 1], r, fill=255)
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([px + 6, cy + 14, px + tw_ + 6, cy + thh + 14], r, fill=(0, 0, 0, 170))
        img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(16)))
        img.paste(th, (px, cy), m); d = ImageDraw.Draw(img)
        d.rounded_rectangle([px, cy, px + tw_ - 1, cy + thh - 1], r, outline=(255, 255, 255, 60), width=2)
        y = cy + thh

    yy, x = y + int(34 * k), px
    cf = F("cjk", int(30 * k)); chh = int(52 * k)
    for chip in cfg.get("chips", []):
        txt = chip["text"] if isinstance(chip, dict) else chip
        cc = {"ink": INK, "dim": DIM, "highlight": HL, "accent": ACC}.get(
            chip.get("style", "ink") if isinstance(chip, dict) else "ink", INK)
        w = tw(d, txt, cf)
        if x + w + 36 > W - 40:
            x = px; yy += chh + 14
        d.rounded_rectangle([x, yy, x + w + 36, yy + chh], chh // 2, outline=cc, width=2)
        d.text((x + 18, yy + int(9 * k)), txt, font=cf, fill=cc); x += w + 52

    st = cfg.get("stamp")                           # rotated accent tag, top-left over the photo
    if st:
        sf = F("cjk-bold", int(st.get("size", 54) * k)); sw = tw(d, st["text"], sf) + int(60 * k); shh = int(84 * k)
        tag = Image.new("RGBA", (sw, shh), (0, 0, 0, 0)); td = ImageDraw.Draw(tag)
        td.rounded_rectangle([0, 0, sw - 1, shh - 1], int(16 * k), fill=ACC)
        td.text((int(30 * k), int(10 * k)), st["text"], font=sf, fill=(255, 255, 255))
        img.alpha_composite(tag.rotate(st.get("rotate", 8), expand=True, resample=Image.BICUBIC), (int(60 * k), int(60 * k)))

    ct = cfg.get("corner_tag")                      # highlight tag, bottom-right
    if ct:
        nf = F("cjk-bold", int(32 * k)); nw = tw(d, ct["text"], nf) + int(40 * k); nh = int(58 * k)
        nt = Image.new("RGBA", (nw, nh), (0, 0, 0, 0)); nd = ImageDraw.Draw(nt)
        nd.rounded_rectangle([0, 0, nw - 1, nh - 1], int(14 * k), fill=HL)
        nd.text((int(20 * k), int(9 * k)), ct["text"], font=nf, fill=(20, 20, 20))
        img.alpha_composite(nt, (W - 60 - nw, H - int(100 * k)))

    p = base / out["path"]; p.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(p, quality=int(out.get("quality", 94)))
    print("wrote", p, f"{W}x{H}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="split cover JSON")
    a = ap.parse_args()
    cfgp = pathlib.Path(a.config).resolve()
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    base = cfgp.parent
    photo = load_photo(cfg, base)
    cx = cfg.get("face_x", "auto")
    cx = face_center_x(photo) if cx == "auto" else float(cx)
    for out in cfg.get("outputs", [{"path": "cover-16x9.jpg", "size": [1920, 1080], "photo_w": 900}]):
        build(cfg, base, photo, cx, out)


if __name__ == "__main__":
    main()
