"""Storyboard stills. MVP backends: ``placeholder`` (a calm card with the shot text, made here with Pillow -
free, instant, no model) and, when detected, a local image model (phase 2 wiring). Kling image is a paid source
and goes through the spend gate like any final."""
import os
import textwrap

BG = (240, 235, 226)
INK = (46, 42, 38)
MUTED = (126, 118, 108)
SWATCH = {"kling-mcp": (15, 122, 108), "minimax": (194, 96, 58), "veo": (47, 106, 166), "jimeng": (61, 143, 176),
          "seedance-ark": (61, 143, 176), "local": (124, 107, 176), "record": (194, 59, 59), "reuse": (140, 131, 121),
          "card": (176, 138, 46)}


def _font_paths():
    """The engine's own CJK font (downloaded on first run), then system CJK fonts (macOS, Windows, Linux)."""
    from ..config import FONT_DIR, FONTS
    out = [os.path.join(FONT_DIR, n) for n in FONTS.get("cjk", [])]
    win = os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows", "Fonts")
    return out + ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc",
                  "/System/Library/Fonts/STHeiti Medium.ttc", "/Library/Fonts/Arial Unicode.ttf",
                  os.path.join(win, "msyh.ttc"), os.path.join(win, "simhei.ttf"), os.path.join(win, "arial.ttf"),
                  "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _font(size):
    from PIL import ImageFont
    for p in _font_paths():
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


CAST = [(15, 122, 108), (194, 96, 58), (47, 106, 166), (124, 107, 176), (176, 138, 46), (140, 131, 121)]
CAMERA_WORDS = [("aerial", "aerial"), ("drone", "aerial"), ("wide", "wide"), ("全景", "wide"), ("low", "low"),
                ("仰拍", "low"), ("close", "close"), ("近景", "close"), ("insert", "insert"), ("product", "insert")]


def _shot_kind(shot):
    cam = f"{shot.get('camera') or ''} {shot.get('action') or ''}".lower()
    return next((k for w, k in CAMERA_WORDS if w in cam), "medium")


def placeholder(shot, path, size=(540, 960), kind="local", cast=()):
    """A quiet storyboard sketch (no text, no faces): a horizon, the cast as coloured figures (A teal, B rust... like
    the bible), framed by the shot size (wide / medium / close / low / aerial / insert). The shot number, length and
    action are shown by the desk around it. Deterministic: the same shot gives the same file."""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", size, (236, 231, 222))
    d = ImageDraw.Draw(im)
    acc = SWATCH.get(kind, SWATCH["local"])
    sk = _shot_kind(shot)
    # sky -> ground, tinted very lightly by the source colour
    horizon = int(h * (0.35 if sk == "low" else 0.62 if sk == "aerial" else 0.55))
    for y in range(h):
        t = y / h
        base = (232, 226, 216) if y < horizon else (214, 205, 192)
        mix = 0.10 if y < horizon else 0.16
        d.line([(0, y), (w, y)], fill=tuple(int(b * (1 - mix) + a * mix - 12 * t) for b, a in zip(base, acc)))
    d.line([(0, horizon), (w, horizon)], fill=tuple(max(0, c - 40) for c in (214, 205, 192)), width=3)
    faces = list(shot.get("faces") or [])
    order = {c: i for i, c in enumerate(cast or faces)}
    scale = {"wide": 0.45, "aerial": 0.22, "medium": 0.75, "low": 0.95, "close": 1.35, "insert": 0.6}[sk]
    if not faces:
        # an object on a plinth (insert / product) or a quiet landscape mark
        r = int(w * 0.16 * (1.3 if sk == "insert" else 1))
        cx, cy = w // 2, horizon - r // 2
        d.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=r // 3, fill=(250, 248, 244), outline=acc, width=4)
        d.ellipse([cx - r // 3, cy - r // 3, cx + r // 3, cy + r // 3], fill=acc)
    else:
        n = len(faces)
        for i, c in enumerate(faces):
            col = CAST[order.get(c, i) % len(CAST)]
            cx = int(w * (i + 1) / (n + 1))
            head = int(w * 0.11 * scale)
            body_w, body_h = int(head * 2.2), int(head * 3.2)
            top = horizon - int(head * 1.2) if sk != "close" else int(h * 0.30)
            d.rounded_rectangle([cx - body_w // 2, top + head, cx + body_w // 2, top + head + body_h], radius=head,
                                fill=col)
            d.ellipse([cx - head // 2 * 2 // 2 - head // 2, top - head // 2, cx + head // 2 + head // 2 - head // 2,
                       top + head + head // 2 - head // 2], fill=tuple(min(255, int(v * 0.6 + 255 * 0.4)) for v in col))
    # frame corners (a storyboard panel)
    m, L = 26, 46
    for (x, y, dx, dy) in ((m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
        d.line([(x, y), (x + dx * L, y)], fill=(120, 112, 102), width=3)
        d.line([(x, y), (x, y + dy * L)], fill=(120, 112, 102), width=3)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im.save(path, "JPEG", quality=86)
    return path


def card_png(text, path, size=(1080, 1920)):
    """A text card made in post (never generated): warm dark ground, large centred text."""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", size, (35, 31, 28))
    d = ImageDraw.Draw(im)
    f = _font(int(w * 0.08))
    cjk = any(ord(c) > 0x2e80 for c in str(text))
    rows = textwrap.wrap(str(text or ""), 10 if cjk else 18)[:5] or [""]
    lh = int(w * 0.11)
    y = (h - lh * len(rows)) // 2
    for r in rows:
        try:
            tw = d.textlength(r, font=f)
        except AttributeError:
            tw = len(r) * w * 0.05
        d.text(((w - tw) / 2, y), r, fill=(232, 196, 92), font=f)
        y += lh
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    im.save(path, "PNG")
    return path
