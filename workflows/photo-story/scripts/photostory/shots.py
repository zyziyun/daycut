"""Shot renderers. Each shot object has .frame(lt) -> float32 (BOX_H, BOX_W, 3), lt = seconds into the shot.

Source strings (first element of a shot tuple in the spec):
    "<img>"                      single photo (name in MEDIA.images, extension optional)
    "v<clip>" / "video:<clip>"   short video clip (name in MEDIA.videos; "1234" also matches IMG_1234.MOV)
    "collage:a,b,c"              taped polaroid cards drop onto paper one by one
    "film:a,b,c"                 film strip scrolling sideways (sprocket holes + FILM_CAPTION)
    "split:a|b"                  before/after wipe with a handle (labels=("Draft 草稿","Final 成品"))
    "grid:a,b,c,d"               2x2 grid popping in
    "tilt:a"                     photo as a physical card turning in 3D (yaw=(from,to))
    "deck:a,b,c"                 stack of cards, top ones fly away
    "quote:a"                    blurred photo + typewriter quote (q=(en, zh, attribution))
    "route:<leg>"                schematic route map from ROUTE (leg key, or "A>B>C" city chain)
    "medal:a"                    round portrait medal with rotating ring text (ring="...")
    "rows:a,b,c"                 three wide strips sliding in from alternating sides
Motions for single photos: in out panL panR up down still flip. Options: c=(cx,cy) z=zoom fx=(...).
"""
import math
import os
import random
import re
import shutil
import subprocess

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from vstudio import media as vmedia

from .ctx import font, font_for
from .looks import paper_bg
from .util import cover, crop_focus, ease, layer, paste_rgba, to_arr

KINDS = ("collage", "film", "split", "grid", "tilt", "deck", "quote", "route", "medal", "rows", "video", "img")


def parse_src(C, src):
    """-> (kind, arg)."""
    if ":" in src:
        k, a = src.split(":", 1)
        if k in KINDS:
            return k, a
    if src.startswith("v") and C.find_video(src[1:]):
        return "video", src[1:]
    return "img", src


def items(arg):
    return [x.strip() for x in arg.split(",") if x.strip()]


# ------------------------------------------------------------------ helpers
def pencil(img):
    """Colour photo -> warm graphite sketch (dodge blend)."""
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    blur = cv2.GaussianBlur(255 - g, (0, 0), 7)
    sk = np.clip(g * 255 / (256 - blur), 0, 255) / 255
    sk = sk ** 2.4
    return (sk[..., None] * np.array([240, 232, 216], np.float32)).astype(np.uint8)


def blurred_bg(C, im, dark=0.4, sig=24):
    small = cover(im, C.BOX_W // 4, C.BOX_H // 4)
    small = small.filter(ImageFilter.GaussianBlur(sig / 4))
    return cv2.resize(np.asarray(small).astype(np.float32), (C.BOX_W, C.BOX_H)) * dark


def make_card(C, n, maxside, rot, seed):
    """Polaroid-style card with tape and drop shadow, rotated; float32 RGBA."""
    c, z = C.focus_of(n)
    im = crop_focus(C.open_img(n), c, z).copy()
    im.thumbnail((int(maxside), int(maxside)), Image.LANCZOS)
    b, bb = C.b(26), C.b(90)
    card = Image.new("RGBA", (im.width + 2 * b, im.height + b + bb), (250, 247, 240, 255))
    card.paste(im, (b, b))
    r = random.Random(seed)
    tape = Image.new("RGBA", (C.b(200), C.b(56)), (236, 222, 180, 165)).rotate(r.uniform(-12, 12), expand=True)
    pad = C.b(60)
    big = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rectangle((pad + C.b(14), pad + C.b(20), pad + card.width + C.b(14), pad + card.height + C.b(20)),
                                 fill=(0, 0, 0, 120))
    big = Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(C.b(16))), big)
    big.paste(card, (pad, pad), card)
    big.alpha_composite(tape, (pad + card.width // 2 - tape.width // 2, pad - tape.height // 2 + C.b(6)))
    return to_arr(big.rotate(rot, resample=Image.BICUBIC, expand=True))


def ffprobe_size(src):
    w, h = map(int, re.findall(r"\d+", subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", src]).decode())[:2])
    rot = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream_side_data=rotation:stream_tags=rotate", "-of", "csv=p=0", src]).decode()
    if re.search(r"-?(90|270)", rot):
        w, h = h, w
    return w, h


def prep_video(C, sh, name):
    """Trim / speed / crop (VCROP or c=, z=) / optional grade (VEQ) a clip to the box size, cached."""
    speed = sh.get("speed", 1.0)
    off = sh.get("off", 0.0)
    need = (sh["end"] - sh["start"] + sh["tail"] + 0.6) * speed
    tag = re.sub(r"[^\w.-]", "_", name)
    out = os.path.join(C.cache_dir, f"v_{tag}_{C.BOX_W}x{C.BOX_H}_{off}_{speed}_{need:.1f}_sdr.mp4")
    if not os.path.exists(out):
        src = C.find_video(name)
        if not src:
            raise FileNotFoundError(f"video '{name}' not found in {C.vid_dirs}")
        hdr = ""
        info = vmedia.probe(src)
        if info["hdr"]:                              # iPhone HLG / PQ clip -> SDR bt709 first (avconvert on macOS)
            if shutil.which("avconvert"):
                sdr = os.path.join(C.cache_dir, f"sdr_{tag}.mov")
                if not os.path.exists(sdr):
                    vmedia.to_sdr(src, sdr, backend="avconvert")
                src = sdr
            else:
                hdr = vmedia.hdr_to_sdr_args(src, info["transfer"]) + ","
        w, h = ffprobe_size(src)
        if name in C.VCROP:
            cx, cy, fr = C.VCROP[name]
        else:
            (cx, cy), fr = sh.get("c", (0.5, 0.5)), 1.0 / sh.get("z", 1.0)
        cw = min(w * fr, h * C.BOX_W / C.BOX_H)
        ch = cw * C.BOX_H / C.BOX_W
        x = int(min(max(cx * w - cw / 2, 0), w - cw))
        y = int(min(max(cy * h - ch / 2, 0), h - ch))
        vf = hdr + f"setpts=PTS/{speed},crop={int(cw)}:{int(ch)}:{x}:{y},scale={C.BOX_W}:{C.BOX_H}:flags=lanczos,fps={C.FPS}"
        if name in C.VEQ or sh.get("grade"):
            vf += "," + (sh.get("grade") if isinstance(sh.get("grade"), str) else C.VEQ_FILTER)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(off), "-t", f"{need:.2f}", "-i", src,
                        "-vf", vf, "-an", "-c:v", "libx264", "-crf", "12", "-preset", "fast", out], check=True)
    return out


class VideoShot:
    def __init__(self, C, sh, name):
        self.C = C
        self.cap = cv2.VideoCapture(prep_video(C, sh, name))
        self.idx, self.last = -1, np.zeros((C.BOX_H, C.BOX_W, 3), np.float32)

    def frame(self, lt):
        want = max(0, int(round(lt * self.C.FPS)))
        while self.idx < want:
            ok, f = self.cap.read()
            if not ok:
                break
            self.idx += 1
            self.last = cv2.cvtColor(f, cv2.COLOR_BGR2RGB).astype(np.float32)
        return self.last      # shared buffer: caller copies before drawing overlays


# ------------------------------------------------------------------ single photo
class ImageShot:
    """Ken-Burns style moves: in / out / panL / panR / up / down / still / flip; fx sketch."""

    def __init__(self, C, sh, name):
        self.C, self.sh = C, sh
        z = sh.get("z", 1.0)
        im = C.open_img(name)
        cov = max(C.BOX_W / im.width, C.BOX_H / im.height)
        s = min(1.0, cov * z * 1.14 * 1.08)
        if s < 1:
            im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        self.img = np.asarray(im)
        self.sk = pencil(self.img) if "sketch" in sh.get("fx", ()) else None

    def frame(self, lt):
        C, sh, img = self.C, self.sh, self.img
        BW, BH = C.BOX_W, C.BOX_H
        ih, iw = img.shape[:2]
        dur = sh["end"] - sh["start"] + sh["tail"]
        u = ease(lt / dur)
        z = sh.get("z", 1.0)
        mo = sh["motion"]
        Z = {"in": z * (1 + 0.12 * u), "out": z * (1.12 - 0.12 * u)}.get(mo, z * 1.04)
        scale = max(BW / iw, BH / ih) * Z
        ww, wh = BW / scale, BH / scale
        cx, cy = sh.get("c", (0.5, 0.5))
        cx, cy = cx * iw, cy * ih
        lo_x, hi_x, lo_y, hi_y = ww / 2, iw - ww / 2, wh / 2, ih - wh / 2
        if mo in ("panR", "panL"):
            a, b = (lo_x, hi_x) if mo == "panR" else (hi_x, lo_x)
            cx = a + (b - a) * (0.15 + 0.7 * u)
        if mo in ("up", "down"):
            a, b = (hi_y, lo_y) if mo == "up" else (lo_y, hi_y)
            cy = a + (b - a) * (0.15 + 0.7 * u)
        cx = min(max(cx, lo_x), hi_x) if hi_x > lo_x else iw / 2
        cy = min(max(cy, lo_y), hi_y) if hi_y > lo_y else ih / 2
        M = np.float32([[scale, 0, BW / 2 - scale * cx], [0, scale, BH / 2 - scale * cy]])
        f = cv2.warpAffine(img, M, (BW, BH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT).astype(np.float32)
        if self.sk is not None:      # pencil sketch grows into the colour photo along the ink-noise field
            s = cv2.warpAffine(self.sk, M, (BW, BH), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            q = ease((lt - 0.2 * dur) / (0.5 * dur))
            m = np.clip((q * 1.3 - C.INK) / 0.1, 0, 1)[..., None]
            f = s.astype(np.float32) * (1 - m) + f * m
        if mo == "flip":             # turn around the vertical axis; mirrored after half-way
            p = ease((lt - dur * 0.25) / (dur * 0.4))
            sx = abs(math.cos(math.pi * p))
            src = f[:, ::-1] if p > 0.5 else f
            out = np.full_like(f, 14)
            nw = max(2, int(BW * sx))
            out[:, (BW - nw) // 2:(BW - nw) // 2 + nw] = cv2.resize(src, (nw, BH)) * (0.7 + 0.3 * sx)
            f = out
        return f


# ------------------------------------------------------------------ multi-photo layouts
class CollageShot:
    POS = [(0.29, 0.28), (0.72, 0.3), (0.3, 0.72), (0.71, 0.7), (0.5, 0.5), (0.5, 0.26)]

    def __init__(self, C, sh, k, arg):
        self.C, self.sh = C, sh
        ids = items(arg)
        r = random.Random(k)
        self.bg = paper_bg(C, k)
        self.cards = []
        for j, n in enumerate(ids):
            card = make_card(C, n, int(C.REF * (0.39 if j < 4 else 0.46)), r.uniform(-9, 9), k * 10 + j)
            px, py = self.POS[j % len(self.POS)]
            self.cards.append((card, px * C.BOX_W + C.b(r.uniform(-30, 30)), py * C.BOX_H + C.b(r.uniform(-30, 30))))
        dur = sh["end"] - sh["start"]
        self.t0 = [0.1 + j * dur * 0.72 / len(ids) for j in range(len(ids))]

    def frame(self, lt):
        f = self.bg.copy()
        for (card, cx, cy), t0 in zip(self.cards, self.t0):
            p = (lt - t0) / 0.38
            if p <= 0:
                continue
            e = ease(p)
            s = 1.22 - 0.22 * e
            c = cv2.resize(card, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR) if s != 1 else card
            paste_rgba(f, c, int(cx - c.shape[1] / 2), int(cy - c.shape[0] / 2 - self.C.b(40) * (1 - e)), min(1, p * 1.6))
        return f


class FilmShot:
    def __init__(self, C, sh, arg):
        self.C, self.sh = C, sh
        ids = items(arg)
        ch = int(C.BOX_H * 0.5)
        cw = int(ch * 4 / 3)
        k = ch / 750
        q = lambda v: max(1, int(round(v * k)))
        g, band = q(40), q(120)
        L = len(ids) * (cw + g) + g
        strip = Image.new("RGB", (L, ch + 2 * band), (16, 14, 12))
        d = ImageDraw.Draw(strip)
        for x in range(q(20), L, q(84)):   # sprocket holes
            for y in (band // 2 - q(24), ch + band + band // 2 - q(24)):
                d.rounded_rectangle((x, y, x + q(40), y + q(48)), q(8), fill=(222, 214, 196))
        for j, n in enumerate(ids):
            c, z = C.focus_of(n)
            x = g + j * (cw + g)
            strip.paste(cover(C.open_img(n), cw, ch, c, z), (x, band))
            cap = C.FILM_CAPTION.format(n=j + 1, name=n)
            d.text((x + q(8), ch + band + q(8)), cap, font=font_for(cap, q(26), "sans-bold", "cjk"), fill=(232, 140, 50))
        self.strip = to_arr(strip)
        self.L = L
        self.bg = np.full((C.BOX_H, C.BOX_W, 3), 18, np.float32)
        self.y = (C.BOX_H - self.strip.shape[0]) // 2

    def frame(self, lt):
        C = self.C
        dur = self.sh["end"] - self.sh["start"] + self.sh["tail"]
        u = min(max(lt / dur, 0), 1)
        x = -int((self.L - C.BOX_W) * (0.05 + 0.9 * u))
        f = self.bg.copy()
        sw = self.strip.shape[1]
        x0, x1 = max(0, -x), min(sw, C.BOX_W - x)
        if x1 > x0:
            f[self.y:self.y + self.strip.shape[0], x0 + x:x1 + x] = self.strip[:, x0:x1]
        return f


class SplitShot:
    """A|B wipe (draft vs final, before vs after) with a draggable-looking handle."""

    def __init__(self, C, sh, arg):
        from .subtitles import make_label
        self.C, self.sh = C, sh
        a, b = arg.split("|")
        self.A = to_arr(cover(C.open_img(a), C.BOX_W, C.BOX_H, *C.focus_of(a)))
        self.B = to_arr(cover(C.open_img(b), C.BOX_W, C.BOX_H, *C.focus_of(b)))
        la, lb = sh.get("labels", ("Draft 草稿", "Final 成品"))
        self.la, self.lb = make_label(C, la), make_label(C, lb)

    def frame(self, lt):
        C = self.C
        dur = self.sh["end"] - self.sh["start"]
        p = ease((lt - dur * 0.18) / (dur * 0.5))
        xline = int(C.BOX_W * (0.97 - 0.47 * p))
        f = self.A.copy()
        f[:, xline:] = self.B[:, xline:]
        f[:, max(0, xline - C.b(3)):xline + C.b(3)] = C.GOLD
        cv2.circle(f, (xline, C.BOX_H // 2), C.b(26), C.GOLD, -1)
        cv2.circle(f, (xline, C.BOX_H // 2), C.b(12), (30, 24, 18), -1)
        m = C.b(40)
        paste_rgba(f, self.la, m, m)
        if p > 0.15:
            paste_rgba(f, self.lb, C.BOX_W - m - self.lb.shape[1], m, min(1, (p - 0.15) * 4))
        return f


class GridShot:
    def __init__(self, C, sh, arg):
        self.C, self.sh = C, sh
        ids = items(arg)[:4]
        g = C.b(16)
        self.cw, self.ch = (C.BOX_W - 3 * g) // 2, (C.BOX_H - 3 * g) // 2
        self.cells = [(to_arr(cover(C.open_img(n), self.cw, self.ch, *C.focus_of(n))),
                       g + (j % 2) * (self.cw + g), g + (j // 2) * (self.ch + g)) for j, n in enumerate(ids)]

    def frame(self, lt):
        f = np.full((self.C.BOX_H, self.C.BOX_W, 3), 16, np.float32)
        for j, (img, x, y) in enumerate(self.cells):
            p = (lt - 0.05 - j * 0.22) / 0.3
            if p <= 0:
                continue
            s = 0.86 + 0.14 * ease(p)
            c = cv2.resize(img, None, fx=s, fy=s) if s < 1 else img
            ox, oy = x + (self.cw - c.shape[1]) // 2, y + (self.ch - c.shape[0]) // 2
            rgba = np.dstack([c, np.full(c.shape[:2], 255 * min(1, p * 1.5), np.float32)])
            paste_rgba(f, rgba, ox, oy)
        return f


class RowsShot:
    def __init__(self, C, sh, arg):
        self.C, self.sh = C, sh
        ids = items(arg)[:3]
        self.g = g = C.b(18)
        self.rh = (C.BOX_H - 4 * g) // 3
        self.rw = C.BOX_W - 2 * g
        self.drift = C.b(160)
        self.rows = [to_arr(cover(C.open_img(n), self.rw + self.drift, self.rh, *C.focus_of(n))) for n in ids]

    def frame(self, lt):
        C = self.C
        f = np.full((C.BOX_H, C.BOX_W, 3), 16, np.float32)
        dur = self.sh["end"] - self.sh["start"] + self.sh["tail"]
        for j, img in enumerate(self.rows):
            p = ease((lt - 0.1 - j * 0.3) / 0.45)
            if p <= 0:
                continue
            u = min(1, max(0, lt / dur))
            drift = int(self.drift * (u if j % 2 == 0 else 1 - u))
            crop = img[:, drift:drift + self.rw]
            sgn = -1 if j % 2 == 0 else 1
            rgba = np.dstack([crop, np.full(crop.shape[:2], 255, np.float32)])
            paste_rgba(f, rgba, self.g + int(sgn * (1 - p) * C.BOX_W), self.g + j * (self.rh + self.g))
        return f


# ------------------------------------------------------------------ object-like shots
class TiltShot:
    """Photo as a physical card turning in 3D over a blurred copy of itself."""

    def __init__(self, C, sh, arg):
        self.C, self.sh = C, sh
        im = crop_focus(C.open_img(arg), sh.get("c", (0.5, 0.5)), sh.get("z", 1.0)).copy()
        self.bg = blurred_bg(C, im, 0.38)
        im.thumbnail((int(C.BOX_W * 0.74), int(C.BOX_H * 0.74)), Image.LANCZOS)
        e = C.b(8)
        card = Image.new("RGB", (im.width + 2 * e, im.height + 2 * e), C.GOLD)
        card.paste(im, (e, e))
        self.card = to_arr(card)
        self.yaw = sh.get("yaw", (-22, 14))

    def frame(self, lt):
        C = self.C
        dur = self.sh["end"] - self.sh["start"] + self.sh["tail"]
        u = ease(lt / dur)
        yaw = math.radians(self.yaw[0] + (self.yaw[1] - self.yaw[0]) * u)
        pitch = math.radians(6 * math.sin(math.pi * u))
        h, w = self.card.shape[:2]
        fl = 2200.0 * C.bs
        cx, cy = C.BOX_W / 2, C.BOX_H / 2
        dst = []
        for x, y in [(0, 0), (w, 0), (w, h), (0, h)]:
            X, Y = x - w / 2, y - h / 2
            X2, Z = X * math.cos(yaw), X * math.sin(yaw)
            Y2, Z = Y * math.cos(pitch) - Z * math.sin(pitch), Z * math.cos(pitch) + Y * math.sin(pitch)
            s = fl / (fl + Z)
            dst.append((cx + X2 * s, cy + Y2 * s))
        M = cv2.getPerspectiveTransform(np.float32([(0, 0), (w, 0), (w, h), (0, h)]), np.float32(dst))
        out = self.bg.copy()
        mask = cv2.warpPerspective(np.ones((h, w), np.float32), M, (C.BOX_W, C.BOX_H))
        sh_mask = cv2.GaussianBlur(np.roll(np.roll(mask, C.b(28), 0), C.b(22), 1), (0, 0), C.b(22))[..., None]
        out *= 1 - 0.55 * sh_mask
        warped = cv2.warpPerspective(self.card, M, (C.BOX_W, C.BOX_H), flags=cv2.INTER_CUBIC)
        m = mask[..., None]
        return out * (1 - m) + warped * m


class DeckShot:
    """A stack of cards; the top ones fly off left/right in turn."""

    def __init__(self, C, sh, k, arg):
        self.C, self.sh = C, sh
        ids = items(arg)
        r = random.Random(k)
        self.bg = paper_bg(C, k + 99) * 0.92
        self.cards = [make_card(C, n, int(C.REF * 0.6), r.uniform(-7, 7), k * 7 + j) for j, n in enumerate(ids)]
        self.off = [(C.b(r.uniform(-25, 25)), C.b(r.uniform(-20, 20))) for _ in ids]
        dur = sh["end"] - sh["start"]
        n = len(ids)
        self.t_fly = [0.35 + (j + 1) * (dur - 0.6) / n for j in range(n - 1)]

    def frame(self, lt):
        C = self.C
        f = self.bg.copy()
        for j in range(len(self.cards) - 1, -1, -1):
            card = self.cards[j]
            ox, oy = self.off[j]
            dx = dy = 0.0
            if j < len(self.t_fly):
                p = (lt - self.t_fly[j]) / 0.45
                if p >= 1:
                    continue
                if p > 0:
                    e = ease(p)
                    dx, dy = -1.3 * C.BOX_W * e * (1 if j % 2 == 0 else -1), -C.b(160) * e
            paste_rgba(f, card, int(C.BOX_W / 2 - card.shape[1] / 2 + ox + dx), int(C.BOX_H / 2 - card.shape[0] / 2 + oy + dy))
        return f


class QuoteShot:
    """Dimmed blurred photo + typewriter quote, translation fades in, then attribution."""

    def __init__(self, C, sh, arg):
        self.C, self.sh = C, sh
        self.bg = blurred_bg(C, C.open_img(arg), 0.32, 30)
        self.en, self.zh, self.who = (tuple(sh["q"]) + ("", "", ""))[:3]
        self.cache = {}
        self.fe = font_for(self.en, C.b(76), "serif-italic", "cjk-serif")
        self.fz = font("cjk-serif", C.b(62))
        self.fw = font_for(self.who, C.b(40), "sans", "cjk")
        d = ImageDraw.Draw(layer(1, 1))
        self.lines = self._wrap(d, self.en, self.fe, C.BOX_W * 0.8)
        self.zlines = self._wrap(d, self.zh, self.fz, C.BOX_W * 0.8, cjk=True) if self.zh else []

    @staticmethod
    def _wrap(d, text, f, maxw, cjk=False):
        toks = list(text) if cjk else text.split(" ")
        lines, cur = [], ""
        for tk in toks:
            test = cur + tk if cjk else (cur + " " + tk).strip()
            if d.textlength(test, font=f) > maxw and cur:
                lines.append(cur)
                cur = tk
            else:
                cur = test
        return lines + ([cur] if cur else [])

    def _layer(self, nchar, zh_a):
        key = (nchar, round(zh_a, 2))
        if key in self.cache:
            return self.cache[key]
        C = self.C
        lay = layer(C.BOX_W, C.BOX_H)
        d = ImageDraw.Draw(lay)
        d.text((C.b(110), C.b(120)), "“", font=font("serif-italic", C.b(300)), fill=C.GOLD + (150,))
        LE, LZ = C.b(104), C.b(84)
        total = LE * len(self.lines) + C.b(40) + LZ * len(self.zlines) + C.b(90)
        y = (C.BOX_H - total) // 2
        left = nchar
        for ln in self.lines:
            show = ln[:max(0, left)]
            left -= len(ln) + 1
            d.text(((C.BOX_W - d.textlength(ln, font=self.fe)) / 2, y), show, font=self.fe, fill=(250, 244, 230, 255))
            y += LE
        y += C.b(40)
        for ln in self.zlines:
            d.text(((C.BOX_W - d.textlength(ln, font=self.fz)) / 2, y), ln, font=self.fz,
                   fill=(236, 220, 190, int(255 * zh_a)))
            y += LZ
        y += C.b(30)
        if self.who:
            d.text(((C.BOX_W - d.textlength(self.who, font=self.fw)) / 2, y), self.who, font=self.fw,
                   fill=C.GOLD + (int(255 * zh_a),))
        arr = to_arr(lay)
        self.cache[key] = arr
        return arr

    def frame(self, lt):
        dur = self.sh["end"] - self.sh["start"]
        total = sum(len(l) + 1 for l in self.lines)
        q = min(1, max(0, (lt - 0.2) / max(0.6, dur * 0.55)))
        zh_a = min(1, max(0, (lt - 0.2 - dur * 0.55) / 0.5))
        f = self.bg.copy()
        paste_rgba(f, self._layer(int(total * q), zh_a), 0, 0)
        return f


class RouteShot:
    """Schematic route map on paper (not to scale). Cities/legs come from spec ROUTE:
        ROUTE = dict(title=..., note=..., cities={"A": dict(lon=, lat=, zh="", year="", side="right")},
                     legs={"key": [("A", "B"), ...]})
    "route:key" draws that leg list; "route:A>B>C" draws a chain; a leg ("A","A") just pulses at A."""

    def __init__(self, C, sh, k, arg):
        self.C, self.sh = C, sh
        R = C.ROUTE
        self.cities = {n: dict(v) if isinstance(v, dict) else dict(zip(("lon", "lat", "zh", "year", "side"), v))
                       for n, v in (R.get("cities") or {}).items()}
        legs = R.get("legs") or {}
        if arg in legs:
            self.legs = [tuple(x) for x in legs[arg]]
        else:
            chain = [x.strip() for x in arg.split(">") if x.strip()]
            self.legs = list(zip(chain[:-1], chain[1:])) if len(chain) > 1 else [(chain[0], chain[0])]
        for a, b in self.legs:
            for n in (a, b):
                if n not in self.cities:
                    raise KeyError(f"route city '{n}' missing from ROUTE['cities']")
        self._project()
        bg = paper_bg(C, k + 5)
        lay = layer(C.BOX_W, C.BOX_H)
        d = ImageDraw.Draw(lay)
        step = C.b(120)
        for gx in range(0, C.BOX_W, step):
            d.line((gx, 0, gx, C.BOX_H), fill=(120, 100, 70, 28), width=1)
        for gy in range(0, C.BOX_H, step):
            d.line((0, gy, C.BOX_W, gy), fill=(120, 100, 70, 28), width=1)
        title = R.get("title", "")
        if title:
            d.text((C.b(80), C.b(60)), title, font=font_for(title, C.b(64), "serif-italic", "cjk-serif"), fill=(70, 52, 36, 255))
        note = R.get("note", "示意图，非精确比例 · schematic, not to scale")
        if note:
            d.text((C.b(80), C.BOX_H - C.b(80)), note, font=font_for(note, C.b(30), "sans", "cjk"), fill=(110, 92, 70, 255))
        cx, cy = C.BOX_W - C.b(170), C.BOX_H - C.b(230)   # north arrow
        d.polygon([(cx, cy - C.b(80)), (cx - C.b(22), cy), (cx + C.b(22), cy)], fill=(140, 40, 30, 230))
        d.polygon([(cx, cy + C.b(80)), (cx - C.b(22), cy), (cx + C.b(22), cy)], fill=(90, 70, 50, 160))
        d.text((cx, cy - C.b(110)), "N", font=font("serif-italic", C.b(46)), fill=(70, 52, 36, 255), anchor="mm")
        fz = font("cjk-serif", C.b(56))
        for name, v in self.cities.items():
            x, y = self.xy(name)
            r = C.b(14)
            d.ellipse((x - r, y - r, x + r, y + r), fill=(70, 52, 36, 255))
            top = v.get("zh") or name
            low = f"{name} {v.get('year', '')}".strip() if v.get("zh") else str(v.get("year", ""))
            ft = fz if v.get("zh") else font_for(top, C.b(56), "serif-italic", "cjk-serif")
            fe = font_for(low, C.b(40), "serif-italic", "cjk")
            left = v.get("side", "right") == "left"
            tx = (lambda t, f: x - C.b(30) - d.textlength(t, font=f)) if left else (lambda t, f: x + C.b(30))
            d.text((tx(top, ft), y - C.b(64)), top, font=ft, fill=(60, 44, 30, 255))
            if low:
                d.text((tx(low, fe), y + C.b(2)), low, font=fe, fill=(120, 92, 60, 255))
        self.bg = bg.copy()
        paste_rgba(self.bg, to_arr(lay), 0, 0)

    def _project(self):
        C = self.C
        pts = {n: (v["lon"] * math.cos(math.radians(v["lat"])), -v["lat"]) for n, v in self.cities.items()}
        xs, ys = [p[0] for p in pts.values()], [p[1] for p in pts.values()]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        L, Rr, T, B = C.BOX_W * 0.2, C.BOX_W * 0.8, C.BOX_H * 0.2, C.BOX_H * 0.8
        sx = (Rr - L) / (x1 - x0) if x1 > x0 else 1e9
        sy = (B - T) / (y1 - y0) if y1 > y0 else 1e9
        s = min(sx, sy) if min(sx, sy) < 1e9 else 1.0
        ox = (L + Rr) / 2 - s * (x0 + x1) / 2
        oy = (T + B) / 2 - s * (y0 + y1) / 2
        self._xy = {n: (ox + s * p[0], oy + s * p[1]) for n, p in pts.items()}

    def xy(self, name):
        return self._xy[name]

    def frame(self, lt):
        C = self.C
        f = self.bg.copy()
        dur = self.sh["end"] - self.sh["start"]
        p = ease((lt - 0.25) / max(0.8, dur * 0.6))
        col = C.pal["route"]
        for a, b in self.legs:
            (x0, y0), (x1, y1) = self.xy(a), self.xy(b)
            if a != b:     # dashed line drawing itself
                n = max(2, int(math.hypot(x1 - x0, y1 - y0) / C.b(26)))
                for i in range(int(n * p)):
                    if i % 2 == 0:
                        s0, s1 = i / n, (i + 1) / n
                        cv2.line(f, (int(x0 + (x1 - x0) * s0), int(y0 + (y1 - y0) * s0)),
                                 (int(x0 + (x1 - x0) * s1), int(y0 + (y1 - y0) * s1)), col, C.b(8), cv2.LINE_AA)
            tx, ty = x0 + (x1 - x0) * p, y0 + (y1 - y0) * p
            pulse = (lt * 1.3) % 1
            cv2.circle(f, (int(tx), int(ty)), C.b(24 + 50 * pulse), col, C.b(4), cv2.LINE_AA)
            cv2.circle(f, (int(tx), int(ty)), C.b(20), tuple(min(255, c + 20) for c in col), -1, cv2.LINE_AA)
        return f


class MedalShot:
    """Round portrait medal over blurred background, ring text slowly rotating."""

    def __init__(self, C, sh, arg):
        self.C, self.sh = C, sh
        im = C.open_img(arg)
        c, z = sh.get("c", (0.5, 0.5)), sh.get("z", 1.0)
        self.bg = blurred_bg(C, im, 0.3, 30)
        # keep the whole ring above overlaid subtitles: centre it in the visible part of the box, shrink if needed
        self.cy = C.BOX_H // 2 if C.LAB_BOT >= C.BOX_H else C.LAB_BOT // 2
        k = min(1.0, (2 * self.cy - C.b(40)) / (2 * C.b(700)))
        b = C.b if k >= 1 else (lambda v: max(1, int(round(v * C.bs * k))))
        self.R = R = b(520)
        self.face = to_arr(cover(im, 2 * R + b(120), 2 * R + b(120), c, z))
        self.RC = RC = b(1500)
        h = RC // 2
        ring = layer(RC, RC)
        text = sh.get("ring", (C.TITLE_EN or "PHOTO STORY").upper() + " · ")
        fr = font_for(text, b(52), "serif-italic", "cjk")
        cs = b(80)
        for i, ch in enumerate(text):
            ang = 360 * i / len(text)
            ci = layer(cs, cs)
            ImageDraw.Draw(ci).text((cs / 2, cs / 2), ch, font=fr, fill=C.GOLD + (255,), anchor="mm")
            ci = ci.rotate(-ang, resample=Image.BICUBIC)
            r = b(650)
            ring.alpha_composite(ci, (int(h + r * math.sin(math.radians(ang)) - cs / 2),
                                      int(h - r * math.cos(math.radians(ang)) - cs / 2)))
        dr = ImageDraw.Draw(ring)
        r1, r2 = b(548), b(590)
        dr.ellipse((h - r1, h - r1, h + r1, h + r1), outline=C.GOLD + (255,), width=b(14))
        dr.ellipse((h - r2, h - r2, h + r2, h + r2), outline=C.GOLD + (120,), width=b(3))
        self.ring = to_arr(ring)
        yy, xx = np.mgrid[0:2 * R, 0:2 * R]
        self.mask = np.clip(R - np.sqrt((xx - R) ** 2 + (yy - R) ** 2), 0, 1)[..., None].astype(np.float32)

    def frame(self, lt):
        C, R = self.C, self.R
        dur = self.sh["end"] - self.sh["start"] + self.sh["tail"]
        f = self.bg.copy()
        s = 1 + 0.08 * ease(lt / dur)
        fh = self.face.shape[0]
        M = np.float32([[s, 0, R - s * fh / 2], [0, s, R - s * fh / 2]])
        face = cv2.warpAffine(self.face, M, (2 * R, 2 * R), flags=cv2.INTER_CUBIC)
        cx, cy = C.BOX_W // 2, self.cy
        reg = f[cy - R:cy + R, cx - R:cx + R]
        reg[:] = reg * (1 - self.mask) + face * self.mask
        h = self.RC / 2
        rot = cv2.warpAffine(self.ring, cv2.getRotationMatrix2D((h, h), -lt * 9, 1.0), (self.RC, self.RC),
                             flags=cv2.INTER_LINEAR)
        paste_rgba(f, rot, cx - int(h), cy - int(h))
        return f


def build(C, sh, k):
    kind, arg = parse_src(C, sh["src"])
    return {
        "video": lambda: VideoShot(C, sh, arg),
        "img": lambda: ImageShot(C, sh, arg),
        "collage": lambda: CollageShot(C, sh, k, arg),
        "film": lambda: FilmShot(C, sh, arg),
        "split": lambda: SplitShot(C, sh, arg),
        "grid": lambda: GridShot(C, sh, arg),
        "rows": lambda: RowsShot(C, sh, arg),
        "tilt": lambda: TiltShot(C, sh, arg),
        "deck": lambda: DeckShot(C, sh, k, arg),
        "quote": lambda: QuoteShot(C, sh, arg),
        "route": lambda: RouteShot(C, sh, k, arg),
        "medal": lambda: MedalShot(C, sh, arg),
    }[kind]()
