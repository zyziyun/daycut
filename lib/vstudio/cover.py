"""Cover compositors (PIL) and cover-frame helpers.

    from vstudio import cover as C
    C.score_frames("talk.mp4", top_n=6)            # smile / eyes open / centred face picks (vstudio.face)
    C.split_cover({...}, out="cover-4x3.jpg")     # premium split cover: 4:3, 16:9 side-by-side, 3:4 stacked
    C.notes_cover(frame, panels=[...], fun=..., kicker=...)   # notes-board 16:9 cover (+ 4:3 centre crop)
    C.framed_cover(shot, {...}, size=(1920, 1080))           # dark plate + big text + tilted framed screenshot
    C.polaroid(img, (600, 450), rot=-4, cap="caption")
    C.contact_sheet(frames, labels=[...])

All colours default to persona.brand, fonts to vstudio roles. Face detection / retouch are optional:
without a model, mediapipe or a detectable face, layouts fall back to a centred crop.
"""
import os
import random
import re
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import overlays as O
from .draw import (alpha_paste, brand, draw_runs, fit_font, hgradient_mask, load_font, rgb, rounded_rect,
                   shadow, text_width, to_pil, vgradient_mask)

# Cover retouch: skin / de-shine / light / light makeup only - NO geometric warps. Face slim + eye enlarge on a
# still deformed her face (人都变形了); a config opts in explicitly, e.g. retouch: {slim: 0.05, eye: 0.04}.
COVER_RETOUCH = {"slim": 0.0, "eye": 0.0, "eye_extra": 0.0, "body": 0.0, "makeup": 0.5}

ASPECTS = {  # name -> (W, H, photo extent: width for side-by-side, band height for stacked)
    "4:3": (1440, 1080, 760),
    "16:9": (1920, 1080, 900),
    "3:4": (1080, 1440, 640),
}


# ---------------------------------------------------------------- fonts for user text
# Latin-only faces (STIX serif / italic, JetBrains Mono) have no CJK glyphs: Chinese drawn with them is tofu (□□□).
_CJK = re.compile(r"[\u2e80-\u2fff\u3000-\u303f\u3040-\u30ff\u3100-\u31ff\u3400-\u4dbf\u4e00-\u9fff"
                  r"\uac00-\ud7af\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]")


def _cjk_fallback(role):
    r = str(role).lower()
    if "bold" in r:
        return "cjk-serif-bold" if "serif" in r else "cjk-bold"
    return "cjk-serif" if "serif" in r else "cjk"    # load_font falls back to cjk when cjk-serif is missing


@lru_cache(maxsize=32)
def _codepoints(role):
    """Code points a role's font maps (None when the font or fontTools is unavailable)."""
    try:
        from fontTools.ttLib import TTFont

        from .config import font
        path = role if os.path.exists(str(role)) else font(role)
        with TTFont(path, fontNumber=0, lazy=True) as tt:
            return frozenset(tt.getBestCmap() or ())
    except Exception:  # noqa: BLE001
        return None


def font_role_for(text, role):
    """The font role to draw ``text`` with: ``role``, unless it is a non-CJK face and the text has CJK or any
    character the face lacks -> the matching CJK family (serif -> cjk-serif, bold -> cjk-bold, else cjk)."""
    if not text or str(role).startswith("cjk"):
        return role
    text = str(text)
    if _CJK.search(text):
        return _cjk_fallback(role)
    cps = _codepoints(role)
    if cps is not None and any(ord(c) not in cps for c in text if not c.isspace()):
        return _cjk_fallback(role)
    return role


def text_font(text, role, size):
    """``load_font`` with ``font_role_for``: a face that can draw ``text``."""
    return load_font(font_role_for(text, role), size)


# ---------------------------------------------------------------- frame picking
def score_blend(blend: dict, cx_frac: float) -> float:
    """mouthSmile - 1.5 * eyeBlink - |cx - 0.5| (higher is a better cover frame)."""
    sm = (blend.get("mouthSmileLeft", 0) + blend.get("mouthSmileRight", 0)) / 2
    bl = (blend.get("eyeBlinkLeft", 0) + blend.get("eyeBlinkRight", 0)) / 2
    return float(sm - 1.5 * bl - abs(cx_frac - 0.5))


def score_frames(video, top_n=6, step=5, min_gap=2.0, analysis_width=540, landmarker=None):
    """Rank frames of `video` for a cover. Returns [{"t", "frame", "score", "image" (BGR)}] best first,
    picks at least min_gap seconds apart. Returns [] (with a message) when no face model is available."""
    import cv2
    from . import face as F
    try:
        lm = landmarker or F.landmarker(1)
    except Exception as e:  # noqa: BLE001
        print("score_frames: face model unavailable:", e)
        return []
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    res, i = [], 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        if i % step == 0:
            h, w = img.shape[:2]; s = analysis_width / w
            small = cv2.resize(img, (analysis_width, int(h * s)))
            f = F.main_face(F.detect(lm, small))
            if f is not None and f["blend"]:
                res.append((score_blend(f["blend"], f["pts"][:, 0].mean() / analysis_width), i, i / fps))
        i += 1
    res.sort(reverse=True)
    picks = []
    for sc, fi, t in res:
        if all(abs(t - p["t"]) > min_gap for p in picks):
            picks.append({"t": t, "frame": fi, "score": sc})
        if len(picks) == top_n:
            break
    for p in picks:  # frame-index seek: exact frame, unlike -ss
        cap.set(cv2.CAP_PROP_POS_FRAMES, p["frame"]); ok, img = cap.read()
        p["image"] = img if ok else None
    cap.release()
    if landmarker is None:      # ours: close it now (one garbage-collected on a worker thread deadlocks mediapipe)
        lm.close()
    return picks


def contact_sheet(frames, labels=None, cols=6, tile_w=240, bg=(0, 0, 0), bgr=False):
    """Grid of thumbnails with optional labels under each. frames: PIL / numpy (RGB, or BGR with bgr=True) / paths."""
    ims = [to_pil(f, bgr=bgr).convert("RGB") for f in frames]
    if not ims:
        return Image.new("RGB", (tile_w, tile_w), bg)
    th = max(1, int(tile_w * ims[0].height / ims[0].width))
    lab_h = 30 if labels else 0
    cols = max(1, min(cols, len(ims)))
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * (th + lab_h)), bg)
    d = ImageDraw.Draw(sheet)
    for k, im in enumerate(ims):
        x, y = (k % cols) * tile_w, (k // cols) * (th + lab_h)
        t = im.copy(); t.thumbnail((tile_w, th), Image.LANCZOS)
        sheet.paste(t, (x + (tile_w - t.width) // 2, y + (th - t.height) // 2))
        if labels and k < len(labels):
            d.text((x + 6, y + th + 4), str(labels[k]), font=text_font(str(labels[k]), "mono-bold", 20),
                   fill=(255, 255, 255))
    return sheet


# ---------------------------------------------------------------- photo prep
def _face_and_retouch(photo, retouch_opts, face_x):
    """-> (PIL photo, face centre x fraction). Graceful without model/face."""
    if face_x != "auto" and not retouch_opts:
        return photo, float(face_x if face_x is not None else 0.5)
    fx = 0.5 if face_x == "auto" or face_x is None else float(face_x)
    lm = None
    try:
        import cv2
        from . import face as F
        bgr = cv2.cvtColor(np.asarray(photo.convert("RGB")), cv2.COLOR_RGB2BGR)
        lm = F.landmarker(1)
        f = F.main_face(F.detect(lm, bgr))
        if f is None:
            print("split_cover: no face found; centred crop, no retouch")
            return photo, fx
        if face_x == "auto":
            fx = float(f["pts"][:, 0].mean() / bgr.shape[1])
        if retouch_opts:
            from .retouch import retouch
            opts = dict(COVER_RETOUCH)
            if isinstance(retouch_opts, dict):
                opts.update(retouch_opts)
            bgr = retouch(bgr, f=f, lm=lm, **opts)
            photo = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    except Exception as e:  # noqa: BLE001 - the cover must render without the model
        print("split_cover: face/retouch skipped:", e)
    finally:
        if lm is not None:      # close here: a landmarker garbage-collected later on a worker thread deadlocks
            lm.close()
    return photo, fx


def prepare_photo(photo, retouch=True, face_x="auto", base=None):
    """Load + (optionally) retouch a cover photo ONCE -> (PIL RGB, face centre x fraction), to pass to
    several ``split_cover`` sizes as {"photo": img, "retouched": True, "face_x": fx}. retouch: True (COVER_RETOUCH:
    skin + light makeup, no face slim / eye / body warps) | {slim, eye, makeup, ...} over COVER_RETOUCH | None/False."""
    return _face_and_retouch(_load(photo, base), retouch, face_x)


def redpen_ellipse(im, ellipse, color=(220, 38, 38), width=None, angle=-6, start=-100, end=282):
    """Hand-drawn red-pen circle (an open ellipse stroke whose ends overlap) around a spot.
    ellipse = (cx, cy, rx, ry) as fractions of the image size (values > 1 are pixels); width
    default max(4, W/60). Returns a new PIL image (RGB/RGBA kept). From photo-story ``cover.circled``."""
    import cv2
    pil = to_pil(im)
    mode = pil.mode if pil.mode in ("RGB", "RGBA") else "RGB"
    a = np.asarray(pil.convert(mode)).copy()
    h, w = a.shape[:2]
    cx, cy, rx, ry = ellipse
    fx = lambda v, n: int(v * n) if v <= 1 else int(v)
    col = tuple(rgb(color)) + ((255,) if mode == "RGBA" else ())
    cv2.ellipse(a, (fx(cx, w), fx(cy, h)), (fx(rx, w), fx(ry, h)), angle, start, end, col,
                int(width or max(4, w // 60)), cv2.LINE_AA)
    return Image.fromarray(a, mode)


def _load(img, base=None):
    if img is None:
        return None
    if isinstance(img, str) and base is not None:
        import os
        img = img if os.path.isabs(img) else os.path.join(base, img)
    return to_pil(img).convert("RGB")


def _title_lines(t):
    """title cfg -> (lines, highlights). Accepts {"lines": [...], "highlight": [...]}, a list, or a string."""
    if isinstance(t, str):
        return [t], []
    if isinstance(t, (list, tuple)):
        return list(t), []
    return list(t.get("lines", [])), list(t.get("highlight", []))


# ---------------------------------------------------------------- split cover
def split_cover(cfg: dict, out=None, base=None):
    """Premium split cover. cfg keys (all optional except photo):
      photo        path / PIL / numpy RGB          retouch      True (= COVER_RETOUCH: no warps) | {slim, eye, ...}
      face_x       "auto" | 0..1                   photo_lift   brightness multiplier (1.03)
      aspect       "4:3" | "16:9" | "3:4"  or size [W, H] (+ photo_w: photo width / band height)
      quote        "text" or {"text", "by"}        title        {"lines": [...], "highlight": [...]} (【】 works too)
      thumbnail    path/PIL or {"path"|"image", "crop": [x0,y0,x1,y1] fractions (values > 1: pixels),
                   "crop_px": [x0,y0,x1,y1] pixels}
      retouched    True: the photo is already retouched (``prepare_photo``) - skip retouch/detection
      face_box     [x0,y0,x1,y1] face box in photo pixels -> face_x (no detection)
      fade         photo -> panel fade width (px at 1080, default 220)
      overlap      how far the panel text reaches back over the photo (px at 1080; default 40
                   side-by-side, 70 stacked)
      chips        ["a", {"text", "style": ink|dim|highlight|accent}]   (first plain chip = ink, rest dim)
      stamp        {"text", "rotate": 8}           corner_tag   {"text"} (记笔记 ↓ bottom-right)
      colors       {ground, highlight, accent, ink, dim}   glow   [r,g,b]
    Landscape sizes put the photo left with a fade into the panel; portrait sizes stack photo over panel.
    Returns a PIL RGB image (saved to `out` if given)."""
    B = brand()
    col = cfg.get("colors", {}) or {}
    GROUND = rgb(col.get("ground", B["ground"])); HL = rgb(col.get("highlight", B.get("highlight_alt", B["highlight"])))
    ACC = rgb(col.get("accent", B["accent"])); INK = rgb(col.get("ink", B["ink"])); DIM = rgb(col.get("dim", B["dim"]))
    if cfg.get("size"):
        W, H = cfg["size"]; ext = cfg.get("photo_w", int(W * 0.5) if W >= H else int(H * 0.44))
    else:
        W, H, ext = ASPECTS[cfg.get("aspect", "16:9")]
        ext = cfg.get("photo_w", ext)
    portrait = H > W
    k = min(W, H) / 1080.0

    photo = _load(cfg.get("photo"), base)
    if photo is None:
        photo = Image.new("RGB", (W, H), tuple(min(255, c + 30) for c in GROUND))
    face_x = cfg.get("face_x", "auto")
    if cfg.get("face_box"):
        fb = cfg["face_box"]
        face_x = (fb[0] + fb[2]) / 2 / photo.width
    if cfg.get("retouched") and face_x == "auto":
        photo, fx = _face_and_retouch(photo, None, "auto")
    else:
        photo, fx = _face_and_retouch(photo, None if cfg.get("retouched") else cfg.get("retouch"), face_x)
    lift = float(cfg.get("photo_lift", 1.0))
    if lift != 1.0:
        photo = photo.point(lambda v: min(255, int(v * lift)))

    img = Image.new("RGB", (W, H), GROUND)
    fade = max(1, int(cfg.get("fade", 220) * k))
    if not portrait:
        pw = ext
        s = max(H / photo.height, pw / photo.width)
        ph = photo.resize((max(1, int(photo.width * s)), max(1, int(photo.height * s))), Image.LANCZOS)
        x0 = int(fx * ph.width - pw / 2 + cfg.get("photo_shift", 0)); x0 = max(0, min(ph.width - pw, x0))
        y0 = max(0, (ph.height - H) // 3)
        img.paste(ph.crop((x0, y0, x0 + pw, y0 + H)), (0, 0))
        img.paste(Image.new("RGB", (fade, H), GROUND), (pw - fade, 0), hgradient_mask(fade, H))
        px, py = pw - int(cfg.get("overlap", 40) * k), int(96 * k)
    else:
        bh = ext
        s = max(bh / photo.height, W / photo.width)
        ph = photo.resize((max(1, int(photo.width * s)), max(1, int(photo.height * s))), Image.LANCZOS)
        x0 = int(fx * ph.width - W / 2); x0 = max(0, min(ph.width - W, x0))
        y0 = max(0, min(ph.height - bh, int(ph.height * 0.05)))
        img.paste(ph.crop((x0, y0, x0 + W, y0 + bh)), (0, 0))
        img.paste(Image.new("RGB", (W, fade), GROUND), (0, bh - fade), vgradient_mask(W, fade))
        px, py = int(60 * k), bh - int(cfg.get("overlap", 70) * k)
    pwid = W - px - int(60 * k)

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([px - 100 * k, py + (80 * k if portrait else H * 0.07), W + 150 * k, H - 80 * k],
                                 fill=tuple(cfg.get("glow", (40, 60, 120))) + (70,))
    img = Image.alpha_composite(img.convert("RGBA"), glow.filter(ImageFilter.GaussianBlur(int(120 * k))))
    d = ImageDraw.Draw(img)

    y = py
    q = cfg.get("quote")
    if q:
        q = {"text": q} if isinstance(q, str) else q
        qf = fit_font(q["text"], font_role_for(q["text"], "serif-italic"), int(q.get("size", 34 if W < 1600 else 38) * k),
                      pwid, int(18 * k))
        d.text((px, y), q["text"], font=qf, fill=HL)
        y += int(qf.size * 1.35)
        if q.get("by"):
            d.text((px, y), q["by"], font=text_font(q["by"], "serif-italic", int(qf.size * .82)), fill=DIM)
            y += int(qf.size * 1.1)
        y += int(46 * k)
    lines, hls = _title_lines(cfg.get("title", {}))
    if lines:
        tsize = int((cfg.get("title", {}).get("size", 94) if isinstance(cfg.get("title"), dict) else 94) * k)
        tf = load_font("cjk-bold", tsize)
        while tsize > 30 and max(text_width(ln, tf) for ln in lines) > pwid:
            tsize -= 4; tf = load_font("cjk-bold", tsize)
        gap = (cfg.get("title", {}).get("line_gap", 1.28) if isinstance(cfg.get("title"), dict) else 1.28)
        for ln in lines:
            draw_runs(d, (px, y), ln, tf, INK + (255,), HL + (255,), keywords=hls)
            y += int(tsize * gap)
        y += int(20 * k)

    th_cfg = cfg.get("thumbnail")
    chips = cfg.get("chips", [])
    if th_cfg is not None:
        tsrc = th_cfg.get("image", th_cfg.get("path")) if isinstance(th_cfg, dict) else th_cfg
        th = _load(tsrc, base)
        c = th_cfg.get("crop") if isinstance(th_cfg, dict) else None
        cpx = th_cfg.get("crop_px") if isinstance(th_cfg, dict) else None
        if th is not None and cpx:
            th = th.crop(tuple(int(v) for v in cpx))
        elif th is not None and c:
            if max(c) > 1:
                th = th.crop(tuple(int(v) for v in c))
            else:
                th = th.crop((int(c[0] * th.width), int(c[1] * th.height), int(c[2] * th.width), int(c[3] * th.height)))
        if th is not None:
            tw_ = pwid; thh = int(th.height * tw_ / th.width)
            max_h = H - y - int((190 if chips else 110) * k)
            if thh > max_h:
                thh = max(0, max_h); tw_ = int(th.width * thh / max(1, th.height))
            if thh > 40 * k:
                th = th.resize((tw_, thh), Image.LANCZOS)
                r = int(18 * k)
                m = Image.new("L", (tw_, thh), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, tw_ - 1, thh - 1], r, fill=255)
                card = th.convert("RGBA"); card.putalpha(m)
                sh, pad = shadow(card, blur=int(16 * k), offset=(int(6 * k), int(14 * k)), alpha=170)
                alpha_paste(img, sh, (px - pad, y - pad))   # shadow() already holds the card
                d = ImageDraw.Draw(img)
                d.rounded_rectangle([px, y, px + tw_ - 1, y + thh - 1], r, outline=(255, 255, 255, 60), width=max(1, int(2 * k)))
                y += thh + int(34 * k)

    x = px
    cmap = {"ink": INK, "dim": DIM, "highlight": HL, "accent": ACC}
    for i, c in enumerate(chips):
        txt = c["text"] if isinstance(c, dict) else c
        style = c.get("style") if isinstance(c, dict) else ("ink" if i == 0 else "dim")
        im = O.chip(txt, "outline", color=cmap.get(style, INK), scale=k)
        if x + im.width > W - int(40 * k):
            x = px; y += im.height + int(14 * k)
        if y + im.height <= H:
            alpha_paste(img, im, (x, y))
        x += im.width + int(16 * k)

    st = cfg.get("stamp")
    if st:
        st = {"text": st} if isinstance(st, str) else st
        im = O.tag(st["text"], angle=st.get("rotate", 8), scale=k, size=int(st.get("size", 54)), fill=ACC)
        alpha_paste(img, im, (int(60 * k), int(60 * k)))
    ct = cfg.get("corner_tag")
    if ct:
        ct = {"text": ct} if isinstance(ct, str) else ct
        im = O.tag(ct["text"], scale=k, size=32, fill=HL, text_fill=(20, 20, 20))
        alpha_paste(img, im, (W - int(60 * k) - im.width, H - int(100 * k)))
    img = img.convert("RGB")
    if out:
        img.save(out, quality=int(cfg.get("quality", 94)))
    return img


# ---------------------------------------------------------------- notes-board cover
def crop_43(img):
    """Centre 4:3 crop (what 小红书 shows for a horizontal post)."""
    W, H = img.size
    cw = min(W, int(H * 4 / 3)); x0 = (W - cw) // 2
    return img.crop((x0, 0, x0 + cw, H))


def _paste_rot(img, card, cx, cy, ang, shadow_a=0.42):
    a = card.split()[3]
    blk = Image.new("RGBA", card.size, (0, 0, 0, 255)); blk.putalpha(a.point(lambda p: int(p * shadow_a)))
    blk = blk.rotate(ang, expand=True, resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(8))
    rot = card.rotate(ang, expand=True, resample=Image.BICUBIC)
    alpha_paste(img, blk, (cx - blk.width // 2 + 10, cy - blk.height // 2 + 12))
    alpha_paste(img, rot, (cx - rot.width // 2, cy - rot.height // 2))


def sticky_note(title, lines, hl_line=None, width=412, scale=1.0):
    """Highlight-yellow sticky with a dark header; hl_line drawn bigger in accent."""
    B = brand(); s = scale
    W = int(width * s); head = int(70 * s); row = int(58 * s)
    H = head + len(lines) * row + int(40 * s)
    im = rounded_rect((W, H), int(22 * s), B["highlight"] + (255,))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, head], int(22 * s), fill=(20, 20, 22, 255))
    d.rectangle([0, head - int(20 * s), W - 1, head], fill=(20, 20, 22, 255))
    d.text((W / 2, head / 2), title, font=load_font("cjk-bold", int(33 * s)), fill=B["highlight"] + (255,), anchor="mm")
    for i, ln in enumerate(lines):
        big = ln == hl_line
        d.text((int(30 * s), head + int(22 * s) + i * row), ln, font=load_font("cjk-bold", int((40 if big else 34) * s)),
               fill=(B["accent"] if big else (28, 28, 30)) + (255,))
    return im


def notes_cover(frame, panels=(), fun=None, kicker=None, mute_bottom=150, mute_top=0, spots=None, theme=None):
    """Notes-board cover on a (16:9) video frame: mini 记笔记 panels (title, one bullet) tilted around the face,
    a yellow sticky `fun=(title, lines, highlighted_line)`, an accent kicker pill at the top. Burned-in subtitle
    bands are covered SOLIDLY (a gradient lets white subtitles show through). Returns (cover, crop_43(cover))."""
    img = to_pil(frame).convert("RGBA"); W, H = img.size; s = H / 1080.0
    dark = (12, 13, 16, 255)
    if mute_bottom:
        m = Image.new("L", (W, H), 0); md = ImageDraw.Draw(m); fe = int(24 * s); mb = int(mute_bottom * s)
        md.rectangle([0, H - mb + fe, W, H], fill=255)
        for i in range(fe):
            md.line([(0, H - mb + i), (W, H - mb + i)], fill=int(255 * i / fe))
        img = Image.composite(Image.new("RGBA", (W, H), dark), img, m)
    if mute_top:
        m = Image.new("L", (W, H), 0); md = ImageDraw.Draw(m); fe = int(20 * s); mt = int(mute_top * s)
        md.rectangle([0, 0, W, mt - fe], fill=255)
        for i in range(fe):
            md.line([(0, mt - fe + i), (W, mt - fe + i)], fill=int(255 * (1 - i / fe)))
        img = Image.composite(Image.new("RGBA", (W, H), dark), img, m)
    spots = spots or [(490, 300, -4), (470, 560, 3), (1466, 250, 3), (470, 800, -3)]
    sx = W / 1920.0
    for i, p in enumerate(panels):
        title, bullet = p if isinstance(p, (list, tuple)) else (p, "")
        card = O.notes_panel(title, [bullet] if bullet else [], theme, width=int(400 * s), scale=0.85 * s, tag="记笔记↓")
        cx, cy, ang = spots[i % len(spots)]
        _paste_rot(img, card, int(cx * sx), int(cy * s), ang)
    if fun:
        ftitle, lines, hl = (list(fun) + [None])[:3]
        _paste_rot(img, sticky_note(ftitle, lines, hl, scale=s), int(1466 * sx), int(600 * s), -3)
    if kicker:
        kp = O.tag(kicker, scale=s, size=44)
        alpha_paste(img, kp, ((W - kp.width) // 2, int(34 * s)))
    img = img.convert("RGB")
    return img, crop_43(img)


# ---------------------------------------------------------------- framed / polaroid
def framed(shot, box_w, tilt=-3, accent=None):
    """Screenshot in a white rounded frame with accent outline, slightly tilted (RGBA)."""
    acc = rgb(accent) if accent else brand()["accent"]
    shot = to_pil(shot).convert("RGB")
    sh = shot.resize((int(box_w), max(1, int(box_w * shot.height / shot.width))), Image.LANCZOS)
    b = max(6, int(box_w / 85))
    fr = rounded_rect((sh.width + 2 * b, sh.height + 2 * b), int(b * 1.7), (255, 255, 255), outline=acc + (255,), width=max(2, b // 2))
    fr.paste(sh, (b, b))
    return fr.rotate(tilt, expand=True, resample=Image.BICUBIC) if tilt else fr


def framed_cover(shot, copy: dict, size=(1920, 1080), accent=None, ground=None):
    """Text-led cover: dark plate, eyebrow, big1 (ink) + big2 (accent), sub lines, chips, framed screenshot.
    Wide sizes put the shot bottom-right; tall sizes centre it under the text (longform / episode covers).
    copy keys: eyebrow, hook [..], big1, big2, sub (str or list), chips [..]."""
    B = brand(); acc = rgb(accent) if accent else B["accent"]; bg = rgb(ground) if ground else B["ground"]
    W, H = size; k = min(W, H) / 1080.0
    im = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(im)
    subs = copy.get("sub") or copy.get("sub_lines") or []
    subs = [subs] if isinstance(subs, str) else list(subs)
    if W >= H:
        if shot is not None:
            fr = framed(shot, int(W * 0.53), -3, acc)
            alpha_paste(im, fr, (W - fr.width + int(130 * k), H - fr.height + int(80 * k)))
        x = int(104 * k); maxw = int(W * 0.55)
        if copy.get("eyebrow"):
            d.text((x + 6, int(130 * k)), copy["eyebrow"], font=load_font("cjk-bold", int(44 * k)), fill=acc)
        if copy.get("big1"):
            d.text((x, int(220 * k)), copy["big1"], font=fit_font(copy["big1"], "cjk-bold", int(150 * k), maxw), fill=B["ink"])
        if copy.get("big2"):
            d.text((x, int(410 * k)), copy["big2"], font=fit_font(copy["big2"], "cjk-bold", int(190 * k), maxw), fill=acc)
        for i, ln in enumerate(subs[:2]):
            d.text((x + 6, int((700 + 100 * i) * k)), ln, font=fit_font(ln, "cjk-bold", int(60 * k), maxw), fill=(235, 235, 235))
        cx, cy = x + 6, int(930 * k)
        for c in copy.get("chips", []):
            ci = O.chip(c, "outline", color=(192, 192, 197), scale=k)
            alpha_paste(im, ci, (cx, cy)); cx += ci.width + int(18 * k)
        return im.convert("RGB")
    s = W / 1080.0
    def center(text, y, role, size, fill):
        f = fit_font(text, role, int(size * s), W - int(120 * s))
        d.text(((W - text_width(text, f)) / 2, int(y * s)), text, font=f, fill=fill)
    if copy.get("eyebrow"):
        center(copy["eyebrow"], 110, "cjk-bold", 46, acc)
    for i, ln in enumerate(copy.get("hook", [])[:2]):
        center(ln, 250 + 72 * i, "cjk", 58, (220, 220, 224))
    if copy.get("big1"):
        center(copy["big1"], 470, "cjk-bold", 96, B["ink"])
    if copy.get("big2"):
        center(copy["big2"], 600, "cjk-bold", 150, acc)
    if subs:
        center(subs[0], 800, "cjk-bold", 50, (235, 235, 235))
    chips = [O.chip(c, "outline", color=(192, 192, 197), scale=s * 34 / 30) for c in copy.get("chips", [])]
    if shot is not None:
        bottom = H - ((chips[0].height + int(40 * s)) if chips else int(20 * s))
        bw = int(860 * s)
        fr = framed(shot, bw, -2.5, acc)
        while fr.height > bottom - int(905 * s) and bw > 200:
            bw -= int(40 * s); fr = framed(shot, bw, -2.5, acc)
        alpha_paste(im, fr, ((W - fr.width) // 2, int(905 * s)))
    if chips:
        tot = sum(c.width for c in chips) + int(18 * s) * (len(chips) - 1); cx = (W - tot) // 2
        for c in chips:
            alpha_paste(im, c, (cx, H - c.height - int(20 * s))); cx += c.width + int(18 * s)
    return im.convert("RGB")


def polaroid(im, size, rot=0, cap=None, scale=1.0, seed=0, cap_role="cjk"):
    """Photo on a cream polaroid card with a tape strip and soft shadow, rotated (RGBA)."""
    q = lambda v: max(1, int(round(v * scale)))
    im = to_pil(im).convert("RGB").resize(tuple(int(v) for v in size), Image.LANCZOS)
    b, bb = q(22), (q(70) if cap else q(22))
    card = Image.new("RGBA", (im.width + 2 * b, im.height + b + bb), (250, 247, 240, 255))
    card.paste(im, (b, b))
    if cap:
        ImageDraw.Draw(card).text((card.width / 2, im.height + b + bb / 2 - 2), cap, font=text_font(cap, cap_role, q(30)),
                                  fill=(70, 56, 40), anchor="mm")
    r = random.Random(seed)
    tape = Image.new("RGBA", (q(170), q(48)), (236, 222, 180, 170)).rotate(r.uniform(-14, 14), expand=True)
    pad = q(50)
    big = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    shd = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(shd).rectangle((pad + q(12), pad + q(18), pad + card.width + q(12), pad + card.height + q(18)), fill=(0, 0, 0, 130))
    big = Image.alpha_composite(shd.filter(ImageFilter.GaussianBlur(q(14))), big)
    big.paste(card, (pad, pad), card)
    big.alpha_composite(tape, (pad + card.width // 2 - tape.width // 2, max(0, pad - tape.height // 2 + q(4))))
    return big.rotate(rot, resample=Image.BICUBIC, expand=True) if rot else big
