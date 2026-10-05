#!/usr/bin/env python3
"""Premium split cover from the project config: retouched speaker on one side, dark panel with a quote,
a two-line title with one highlighted term, a framed thumbnail of the highlights video, outline chips,
a rotated red tag and a "记笔记" note tag. Landscape sizes use the side-by-side split; portrait sizes
(e.g. 3:4) stack the photo over the panel.

  python3 $VSTUDIO/workflows/promo-recut/scripts/make_cover.py promo.config.json [--no-retouch]

Retouch runs through vstudio.retouch (face slim, eye, de-shine, skin, light makeup, optional body slim).
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import os
import subprocess

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project, P  # noqa: E402
from vstudio.config import font  # noqa: E402
from PIL import Image, ImageDraw, ImageFont, ImageFilter  # noqa: E402


def hex2rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def grab(src, t, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", out], check=True)
    return out


def get_photo(prj, cv, no_retouch):
    ph = cv.get("photo") or {}
    if ph.get("image"):
        src = prj.p(ph["image"])
    else:
        talk = prj.w("raw_graded.mp4") if os.path.exists(prj.w("raw_graded.mp4")) else prj.p(prj.cfg["talk"])
        src = grab(talk, ph.get("talk_at", 1.0), prj.w("cover_frame.png"))
    rt = cv.get("retouch", {})
    face_x = None
    import cv2
    img = cv2.imread(src)
    try:
        from vstudio import face as F
        lm = F.landmarker(1)
        f = F.main_face(F.detect(lm, img))
        if f is not None:
            face_x = float(f["pts"][:, 0].mean()) / img.shape[1]
            if rt is not False and not no_retouch:
                from vstudio.retouch import retouch
                opts = {"slim": 0.05, "eye": 0.04, "makeup": 0.5, "body": 0.07}
                opts.update(rt or {})
                img = retouch(img, f=f, lm=lm, **opts)
                f2 = F.main_face(F.detect(lm, img))
                if f2 is not None:
                    face_x = float(f2["pts"][:, 0].mean()) / img.shape[1]
    except Exception as e:  # missing model / mediapipe: still produce a cover
        print("  face/retouch skipped:", e)
    out = prj.w("cover_photo.png"); cv2.imwrite(out, img)
    k = cv.get("brighten", 1.03)
    return Image.open(out).convert("RGB").point(lambda v: min(255, int(v * k))), face_x if face_x is not None else 0.5


def get_thumb(prj, cv):
    th = cv.get("thumb") or {}
    if th.get("image"):
        im = Image.open(prj.p(th["image"])).convert("RGB")
    elif prj.cfg.get("highlights") and th.get("highlights_at") is not None:
        im = Image.open(grab(prj.p(prj.cfg["highlights"]), th["highlights_at"], prj.w("cover_thumb.png"))).convert("RGB")
    else:
        return None
    return im.crop(tuple(th["crop"])) if th.get("crop") else im


def fit(d, text, fnt_fn, size, max_w, min_size=24):
    while size > min_size and d.textbbox((0, 0), text, font=fnt_fn(size))[2] > max_w:
        size -= 2
    return fnt_fn(size), size


def build(prj, cv, photo, face_x, thumb, W, H, photo_w, out):
    brand = P("brand", {}) or {}
    NAVY, YEL = hex2rgb(brand.get("ground", "#0B1020")), hex2rgb(brand.get("highlight_alt", "#F4D35E"))
    RED, INK, DIM = hex2rgb(brand.get("accent", "#FF2442")), hex2rgb(brand.get("ink", "#ECEEF2")), hex2rgb(brand.get("dim", "#969EB2"))
    cjk = lambda s, b=True: ImageFont.truetype(font("cjk-bold" if b else "cjk"), s)
    serif = lambda s: ImageFont.truetype(font("serif-italic"), s)
    img = Image.new("RGB", (W, H), NAVY)
    portrait = H > W

    if not portrait:  # side-by-side: photo left, panel right
        ph = photo.resize((int(photo.width * H / photo.height), H), Image.LANCZOS)
        cx = int(face_x * ph.width)
        x0 = max(0, min(ph.width - photo_w, cx - photo_w // 2 - 40))
        img.paste(ph.crop((x0, 0, x0 + photo_w, H)), (0, 0))
        g = Image.new("L", (220, H)); gd = ImageDraw.Draw(g)
        for i in range(220):
            gd.line([(i, 0), (i, H)], fill=int(255 * (i / 220) ** 1.6))
        img.paste(Image.new("RGB", (220, H), NAVY), (photo_w - 220, 0), g)
        px, py = photo_w - 40, 96
    else:  # stacked: photo top, panel below
        ph_h = photo_w  # for portrait sizes photo_w means the photo band height
        ph = photo.resize((int(photo.width * ph_h / photo.height), ph_h), Image.LANCZOS)
        cx = int(face_x * ph.width)
        x0 = max(0, min(ph.width - W, cx - W // 2))
        img.paste(ph.crop((x0, 0, x0 + W, ph_h)), (0, 0))
        g = Image.new("L", (W, 220)); gd = ImageDraw.Draw(g)
        for i in range(220):
            gd.line([(0, i), (W, i)], fill=int(255 * (i / 220) ** 1.6))
        img.paste(Image.new("RGB", (W, 220), NAVY), (0, ph_h - 220), g)
        px, py = 60, ph_h - 80
    pw = W - px - 60
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([px - 100, py + 80, W + 150, H - 80], fill=(40, 60, 120, 70))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(120)))
    d = ImageDraw.Draw(img)

    y = py
    if cv.get("quote"):
        f, _ = fit(d, cv["quote"], serif, 34 if W < 1600 else 38, pw)
        d.text((px, y), cv["quote"], font=f, fill=YEL); y += 46
        if cv.get("attribution"):
            d.text((px, y), cv["attribution"], font=serif(28), fill=DIM); y += 80
        else:
            y += 34
    hl = cv.get("title_highlight", "")
    lines = cv.get("title", [])
    tf, ts = None, 94
    for ln in lines:
        _, s = fit(d, ln, cjk, 94, pw); ts = min(ts, s)
    tf = cjk(ts)
    for ln in lines:
        d.text((px, y), ln, font=tf, fill=INK)
        if hl and hl in ln:
            pre = ln[:ln.index(hl)]
            d.text((px + d.textlength(pre, font=tf), y), hl, font=tf, fill=YEL)
        y += int(ts * 1.28)
    y += 20
    if thumb is not None:
        tw = pw; thh = int(thumb.height * tw / thumb.width)
        max_h = H - y - (190 if cv.get("chips") else 110)
        if thh > max_h:
            thh = max(0, max_h); tw = int(thumb.width * thh / thumb.height)
        if thh > 40:
            th = thumb.resize((tw, thh), Image.LANCZOS)
            m = Image.new("L", (tw, thh), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, tw - 1, thh - 1], 18, fill=255)
            sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle([px + 6, y + 14, px + tw + 6, y + thh + 14], 18, fill=(0, 0, 0, 170))
            img = Image.alpha_composite(img, sh.filter(ImageFilter.GaussianBlur(16))); img.paste(th, (px, y), m)
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([px, y, px + tw - 1, y + thh - 1], 18, outline=(255, 255, 255, 60), width=2)
            y += thh + 34
    x = px
    for i, txt in enumerate(cv.get("chips", [])):
        colr = INK if i == 0 else DIM
        f = cjk(30, False); w = d.textbbox((0, 0), txt, font=f)[2]
        if x + w + 36 > W - 40:
            x = px; y += 66
        d.rounded_rectangle([x, y, x + w + 36, y + 52], 26, outline=colr, width=2); d.text((x + 18, y + 9), txt, font=f, fill=colr)
        x += w + 52
    if cv.get("tag"):
        f = cjk(54); tw = int(d.textlength(cv["tag"], font=f)) + 60
        tag = Image.new("RGBA", (tw, 84), (0, 0, 0, 0)); td = ImageDraw.Draw(tag)
        td.rounded_rectangle([0, 0, tw - 1, 83], 16, fill=RED); td.text((30, 6), cv["tag"], font=f, fill=(255, 255, 255))
        img.alpha_composite(tag.rotate(8, expand=True, resample=Image.BICUBIC), (60, 60))
    if cv.get("note"):
        f = cjk(32); nw = int(d.textlength(cv["note"], font=f)) + 40
        nt = Image.new("RGBA", (nw, 58), (0, 0, 0, 0)); nd = ImageDraw.Draw(nt)
        nd.rounded_rectangle([0, 0, nw - 1, 57], 14, fill=YEL); nd.text((20, 6), cv["note"], font=f, fill=(20, 20, 20))
        img.alpha_composite(nt, (W - 60 - nw, H - 100))
    img.convert("RGB").save(out, quality=94)
    print("cover ->", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("config")
    ap.add_argument("--no-retouch", action="store_true")
    a = ap.parse_args()
    prj = Project(a.config)
    cv = prj.cfg.get("cover") or {}
    photo, face_x = get_photo(prj, cv, a.no_retouch)
    thumb = get_thumb(prj, cv)
    sizes = cv.get("sizes") or [{"w": 1440, "h": 1080, "photo_w": 760, "out": "cover-4x3.jpg"},
                                {"w": 1920, "h": 1080, "photo_w": 900, "out": "cover-16x9.jpg"}]
    for s in sizes:
        build(prj, cv, photo, face_x, thumb, s["w"], s["h"], s.get("photo_w", int(s["w"] * 0.5)), prj.p(s["out"]))


if __name__ == "__main__":
    main()
