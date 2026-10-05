"""Spec loading + the render context (canvas geometry, fonts, palette, media lookup, shared arrays).

Everything that render_fx.py / fx_more.py kept as module globals (W, H, HDR, BOX_W, BOX_H, GOLD,
fonts, VCROP/VEQ/FOCUS tables, GRAIN/VIG/LEAK/INK/JAG arrays ...) lives on one `Ctx` object that
is passed explicitly to every shot, overlay and transition.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4] / "lib"))

import glob
import importlib.util
import math
import os
from collections import OrderedDict
from functools import cached_property, lru_cache

import numpy as np
from PIL import Image, ImageFont, ImageOps

from vstudio.config import MissingAsset, font as vfont, persona

from .util import has_cjk, hex_rgb

# name -> (W, H).  Reference design was 1620x2160 (3:4 hi-res).
PRESETS = {
    "3:4": (1080, 1440),
    "3:4-hd": (1620, 2160),
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}
REF_W, REF_H, REF_BOX_H = 1620, 2160, 1500   # geometry the original pixel constants were tuned on

# Font roles. The original used macOS system fonts; they map onto vstudio roles:
#   Songti (CJK serif titles)      -> "cjk-serif"   (optional persona fonts.cjk-serif, falls back to cjk-bold)
#   Hiragino Sans GB (CJK body)    -> "cjk" / "cjk-bold"
#   Avenir Next (latin UI/subs)    -> "sans" / "sans-bold" (optional persona keys, fall back to cjk / cjk-bold)
#   Georgia Italic (latin display) -> "serif-italic"
FALLBACK = {"cjk-serif": "cjk-bold", "sans": "cjk", "sans-bold": "cjk-bold", "serif-italic": "serif"}

DEFAULT_PALETTE = dict(
    accent=(222, 184, 112),      # gold: highlights, progress, frames, labels
    mark=(232, 86, 56),          # red pen circles
    route=(180, 60, 40),         # route line
    ground=(22, 18, 15),         # canvas background
    paper=(226, 214, 192),       # collage / map paper
    ink=(246, 240, 228),         # title text
    sub_en=(250, 250, 250),
    sub_zh=(238, 228, 210),
)


def platform_profile(name):
    """vstudio.platform Profile for a spec PLATFORM value ("xiaohongshu:vertical", "douyin", ...), or None."""
    if not name:
        return None
    from vstudio import platform as vplat
    return vplat.profile(str(name))


def check_profile(C):
    """The profile used for length / copy checks: spec PLATFORM, else persona platforms.default in the
    orientation that matches the canvas (None if that platform has no such orientation)."""
    if C.prof is not None:
        return C.prof
    from vstudio import platform as vplat
    name = (persona().get("platforms") or {}).get("default") or "xiaohongshu"
    o = "horizontal" if C.W > C.H else "full" if C.H / C.W > 1.6 else "vertical"
    try:
        return vplat.profile(name, o)
    except KeyError:
        return None


def load_spec(path):
    path = os.path.abspath(path)
    sp = importlib.util.spec_from_file_location("photostory_spec", path)
    mod = importlib.util.module_from_spec(sp)
    sys.path.insert(0, os.path.dirname(path))
    sp.loader.exec_module(mod)
    mod.__file__ = path
    return mod


def parse_canvas(v):
    if v is None:
        return PRESETS["3:4"]
    if isinstance(v, (tuple, list)):
        return int(v[0]), int(v[1])
    v = str(v).strip()
    if v in PRESETS:
        return PRESETS[v]
    w, h = v.lower().split("x")
    return int(w), int(h)


@lru_cache(maxsize=None)
def _font_path(role):
    try:
        return vfont(role)
    except MissingAsset:
        if role in FALLBACK:
            return _font_path(FALLBACK[role])
        raise


@lru_cache(maxsize=256)
def font(role, size):
    return ImageFont.truetype(_font_path(role), max(8, int(round(size))))


def font_for(text, size, latin="sans", cjk="cjk"):
    """Pick a CJK-capable role when the text contains CJK (serif/italic latin fonts have no CJK)."""
    return font(cjk if has_cjk(text) else latin, size)


class Ctx:
    def __init__(self, spec):
        self.spec = spec
        self.root = os.path.dirname(os.path.abspath(spec.__file__))
        g = lambda k, d=None: getattr(spec, k, d)
        P = persona()
        self.prof = platform_profile(g("PLATFORM"))       # None = legacy CANVAS-only layout
        if self.prof is not None:
            self.W, self.H = self.prof.size
            if g("CANVAS") is not None and parse_canvas(g("CANVAS")) != (self.W, self.H):
                print(f"note: PLATFORM {self.prof.key} sets the canvas {self.W}x{self.H} (CANVAS {g('CANVAS')} ignored)")
        else:
            self.W, self.H = parse_canvas(g("CANVAS"))
        self.FPS = int(g("FPS", (P.get("export") or {}).get("fps", 30)))
        lay = dict(g("LAYOUT", {}) or {})
        portrait = self.H >= self.W
        self.portrait = portrait
        px = lambda v: int(round(v * self.H)) if isinstance(v, float) and v <= 1 else int(v)
        self.overlay_subs = bool(lay.get("overlay_subs", not portrait))
        self.S = math.sqrt(self.W * self.H / (REF_W * REF_H))          # global text scale
        if self.prof is None:
            # legacy layout: header at the very top, subtitle band at the very bottom
            self.HDR = px(lay.get("header", 300 / 2160 if portrait else 0.15))
            self.SUB_H = px(lay.get("sub", 360 / 2160 if portrait else 0.22))
            self.HDR_Y0 = 0
            self.HS = self.HDR / 300                                     # header scale
            self.BOX_H = self.H - self.HDR - (0 if self.overlay_subs else self.SUB_H)
            self.BOX_H -= self.BOX_H % 2
            self.SUB_Y0 = self.H - self.SUB_H
            self.SAFE = (0, 0, self.W, self.H)
            self.CAP = (self.t(70), self.SUB_Y0, self.W - self.t(70), self.H)
        else:
            # platform layout: header content starts at the safe top, subtitles sit in the caption box,
            # picture box between them (portrait) or under overlaid subtitles (landscape)
            from vstudio import platform as vplat
            self.SAFE = vplat.safe_box(self.prof)
            self.CAP = vplat.caption_box(self.prof)
            hc = px(lay.get("header", 300 / 2160 if portrait else 0.15))
            self.HS = hc / 300
            self.HDR_Y0 = max(0, self.SAFE[1] - int(40 * self.HS))
            self.HDR = self.HDR_Y0 + hc
            self.SUB_Y0, self.SUB_H = self.CAP[1], self.CAP[3] - self.CAP[1]
            if "sub" in lay:                                             # taller band, bottom-anchored
                self.SUB_H = px(lay["sub"])
                self.SUB_Y0 = self.CAP[3] - self.SUB_H
            self.BOX_H = (self.H if self.overlay_subs else self.SUB_Y0) - self.HDR
            self.BOX_H -= self.BOX_H % 2
        self.BOX_W = self.W
        # lowest box row (box coords) that is not covered by overlaid subtitles / below the safe area
        self.LAB_BOT = self.BOX_H - (self.SUB_H if self.overlay_subs and self.prof is None else 0)
        if self.prof is not None:
            self.LAB_BOT = min(self.BOX_H, self.SAFE[3] - self.HDR, (self.SUB_Y0 - self.HDR) if self.overlay_subs
                               else self.BOX_H)
        self.ZH_SIZE = self.t(66)                                        # 中文 subtitle size (EN = 56/66 of it)
        if self.prof is not None:
            lo, hi = (int(v) for v in self.prof.caption.get("size", (self.ZH_SIZE, self.ZH_SIZE)))
            self.ZH_SIZE = min(max(self.ZH_SIZE, lo), hi)
        self.REF = min(self.BOX_W, self.BOX_H * REF_W / REF_BOX_H)       # box reference size
        self.bs = self.REF / REF_W                                       # box scale
        loud = self.prof.loudness if self.prof is not None else {}
        self.LUFS = float(loud.get("lufs", (P.get("audio") or {}).get("loudness_lufs", -14)))
        self.TP = float(loud.get("tp", -1.5))
        self.MODE = str(g("MODE", "narration")).lower()

        pal = dict(DEFAULT_PALETTE)
        pal.update({k: hex_rgb(v) for k, v in (g("PALETTE", {}) or {}).items()})
        self.pal = pal
        self.GOLD = pal["accent"]

        self.TITLE_ZH, self.TITLE_EN = g("TITLE_ZH", ""), g("TITLE_EN", "")
        self.SECTIONS = list(g("SECTIONS", ["Story"]))
        self.SECTIONS_EN = list(g("SECTIONS_EN", [""] * len(self.SECTIONS)))
        self.FILM_SECTIONS = set(g("FILM_SECTIONS", set()))
        self.VCROP = dict(g("VCROP", {}) or {})
        self.VEQ = set(g("VEQ", set()) or set())
        self.VEQ_FILTER = g("VEQ_FILTER", "eq=contrast=1.22:brightness=-0.07:saturation=1.3")
        self.FOCUS = dict(g("FOCUS", {}) or {})
        self.ROUTE = dict(g("ROUTE", {}) or {})
        self.TIMELINE = dict(g("TIMELINE", {}) or {})
        self.FILM_CAPTION = g("FILM_CAPTION", "{n:02d}  ▸  " + (self.TITLE_EN or "").upper()[:40])
        media = dict(g("MEDIA", {}) or {})
        self.img_dirs = [self.path(p) for p in _aslist(media.get("images", "my_photos"))]
        self.vid_dirs = [self.path(p) for p in _aslist(media.get("videos", media.get("images", "my_clips")))]
        self.img_ext = _aslist(media.get("image_ext", [".jpg", ".jpeg", ".png", ".webp", ".heic", ".JPG", ".JPEG",
                                                       ".PNG", ".HEIC"]))
        self.vid_ext = _aslist(media.get("video_ext", [".mov", ".mp4", ".m4v", ".MOV", ".MP4"]))
        self.cache_dir = self.path(g("CACHE", "cache"))
        os.makedirs(self.cache_dir, exist_ok=True)
        self._imgs = OrderedDict()

        yy, xx = np.mgrid[0:self.BOX_H, 0:self.BOX_W].astype(np.float32)
        self.XX, self.YY = xx, yy
        self.DIST = np.sqrt((xx - self.BOX_W / 2) ** 2 + (yy - self.BOX_H / 2) ** 2)
        self.VIG_BOX = (1 - 0.55 * (self.DIST / self.DIST.max()) ** 2)[..., None]
        self.DIAG = xx / self.BOX_W * 0.75 + yy / self.BOX_H * 0.25

    # ---------------------------------------------------------------- paths / media
    def path(self, p):
        if p is None:
            return None
        p = os.path.expanduser(str(p))
        return p if os.path.isabs(p) else os.path.join(self.root, p)

    def find_image(self, name):
        p = self.path(name)
        if os.path.splitext(name)[1] and os.path.exists(p):
            return p
        for d in self.img_dirs:
            for ext in self.img_ext:
                q = os.path.join(d, name + ext)
                if os.path.exists(q):
                    return q
            hits = [h for h in sorted(glob.glob(os.path.join(d, f"*_{name}.*")))     # IMG_1234.HEIC given "1234"
                    if os.path.splitext(h)[1] in self.img_ext]
            if hits:
                return hits[0]
        raise FileNotFoundError(f"image '{name}' not found in {self.img_dirs}")

    def _readable(self, p):
        """iPhone HEIC -> a cached JPEG (pillow-heif when installed, else macOS ``sips``); others as is."""
        if os.path.splitext(p)[1].lower() not in (".heic", ".heif"):
            return p
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
            return p
        except ImportError:
            pass
        import hashlib, shutil, subprocess
        out = os.path.join(self.cache_dir, "heic", hashlib.sha1(os.path.abspath(p).encode()).hexdigest()[:12] + ".jpg")
        if not os.path.exists(out) or os.path.getmtime(out) < os.path.getmtime(p):
            if not shutil.which("sips"):
                raise RuntimeError(f"{p}: HEIC needs `pip install pillow-heif` (or macOS sips)")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", p, "--out", out],
                           check=True, capture_output=True)
        return out

    def find_video(self, name):
        p = self.path(name)
        if os.path.splitext(name)[1] and os.path.exists(p):
            return p
        for d in self.vid_dirs:
            for ext in self.vid_ext:
                q = os.path.join(d, name + ext)
                if os.path.exists(q):
                    return q
            hits = sorted(glob.glob(os.path.join(d, f"*_{name}.*")))    # IMG_1234.MOV given "1234"
            hits = [h for h in hits if os.path.splitext(h)[1] in self.vid_ext]
            if hits:
                return hits[0]
        return None

    def open_img(self, name):
        """EXIF-rotated RGB PIL image, small LRU cache (photos are big)."""
        if name in self._imgs:
            self._imgs.move_to_end(name)
            return self._imgs[name]
        im = ImageOps.exif_transpose(Image.open(self._readable(self.find_image(name)))).convert("RGB")
        self._imgs[name] = im
        if len(self._imgs) > 8:
            self._imgs.popitem(last=False)
        return im

    def focus_of(self, n):
        v = self.FOCUS.get(n, ((0.5, 0.5), 1.0))
        return tuple(v[0]), float(v[1])

    # ---------------------------------------------------------------- scale helpers
    def b(self, v):
        """Box-relative pixel constant (tuned on a 1620x1500 picture box)."""
        return max(1, int(round(v * self.bs)))

    def t(self, v):
        """Canvas-relative text size (tuned on 1620x2160)."""
        return max(8, int(round(v * self.S)))

    # ---------------------------------------------------------------- lazily built arrays
    @cached_property
    def GRAIN(self):
        from .looks import make_grain
        return make_grain(self)

    @cached_property
    def LEAK(self):
        from .looks import make_leak
        return make_leak(self)

    @cached_property
    def INK(self):
        from .looks import make_ink
        return make_ink(self)

    @cached_property
    def JAG(self):
        from .looks import make_jag
        return make_jag(self)

    @cached_property
    def BG(self):
        from .looks import make_bg
        return make_bg(self)


def _aslist(v):
    return list(v) if isinstance(v, (list, tuple)) else [v]
