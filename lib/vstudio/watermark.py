"""Watermark: your handle, your logo or a generated badge on every export (off until you set one up).

    python -m vstudio.watermark show [--json]
    python -m vstudio.watermark set --text @me [--kind text|image|generate] [--image logo.png] [--style badge]
                                    [--position bottom-right] [--size 0.2] [--opacity 0.8] [--margin 0.02]
                                    [--default on|off] [--platform douyin=off ...]
    python -m vstudio.watermark generate --text @me --out logo.png [--style badge|monogram|plain] [--color #FFFFFF]
    python -m vstudio.watermark preview --aspect 9:16 --out preview.jpg
    python -m vstudio.watermark apply in.mp4 out.mp4 [--platform tiktok:vertical]

Settings = ``DEFAULTS`` <- persona ``watermark:`` <- ``$VSTUDIO_WATERMARK_FILE`` (default
``$VSTUDIO_HOME/watermark.json``; the desk's Settings › Watermark and ``set`` write it). Keys:

    kind      text (the handle as clean type) | image (your PNG logo, alpha kept) | generate (a logo-style badge
              drawn from the handle, locally with Pillow; style badge | monogram | plain)
    text      the handle / name ("@yourname")       image   path of the logo (kind image)
    color     text / badge colour                   position  top-left | top-right | bottom-left | bottom-right
    size      the mark fits in a square of size x the frame's short side (0.05 .. 0.5)
    opacity   0.1 .. 1                              margin  extra inset inside the platform safe area (x short side)
    default   true = every export gets it unless a job / clip says ``watermark: false``
    platforms {name: false} = never on that platform (unless a job asks for it explicitly)

Placement is safe-area aware: the corner is taken inside the platform's UI-free box (``platform.safe_box``: no
like / comment column, no caption bar of the app), and a bottom corner moves above the caption band
(``platform.caption_box``) so the mark never sits on the captions. A canvas without a profile uses the closest
known one (9:16 -> TikTok, 3:4 -> 小红书, 16:9 -> YouTube).

Where it is applied: ``vstudio.export.export_one`` (every batch recipe, make_vertical, clipkit, polish, vlog) and the
desk's output render (``project.outrender``, final quality). An export manifest entry says ``watermark`` so a
finished file is never marked twice when it is re-rendered.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import sys
import threading

from vstudio import oscompat

DEFAULTS = dict(kind="text", text="", image="", style="badge", color="#FFFFFF", position="bottom-right",
                size=0.24, opacity=0.8, margin=0.02, default=False, platforms={})
KINDS = ("text", "image", "generate")
STYLES = ("badge", "monogram", "plain")
POSITIONS = ("top-left", "top-right", "bottom-left", "bottom-right")
RANGES = dict(size=(0.05, 0.5), opacity=(0.1, 1.0), margin=(0.0, 0.1))
MAX_TEXT = 40
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


# ----------------------------------------------------------------------------------- settings
def home():
    return os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"))


def settings_path():
    return os.path.expanduser(os.environ.get("VSTUDIO_WATERMARK_FILE") or os.path.join(home(), "watermark.json"))


def asset_dir(create=True):
    d = os.path.join(os.path.dirname(settings_path()), "watermark")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _color(v):
    s = str(v or "").strip()
    if len(s) in (4, 7) and s.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in s[1:]):
        return s.upper()
    raise ValueError(f"color must be #RGB or #RRGGBB, not {v!r}")


def validate(patch):
    """A settings patch -> the same patch checked and normalised (ValueError says what is wrong)."""
    if not isinstance(patch, dict):
        raise ValueError("watermark settings must be an object")
    out = {}
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise ValueError(f"unknown watermark setting {k!r} (known: {', '.join(DEFAULTS)})")
        if k == "kind":
            if v not in KINDS:
                raise ValueError(f"kind: {' | '.join(KINDS)}")
        elif k == "style":
            if v not in STYLES:
                raise ValueError(f"style: {' | '.join(STYLES)}")
        elif k == "position":
            if v not in POSITIONS:
                raise ValueError(f"position: {' | '.join(POSITIONS)}")
        elif k == "text":
            v = " ".join(str(v or "").split())
            if len(v) > MAX_TEXT:
                raise ValueError(f"text: at most {MAX_TEXT} characters")
        elif k == "image":
            v = os.path.expanduser(str(v or ""))
            if v and not v.lower().endswith(IMAGE_EXT):
                raise ValueError("image: a .png / .jpg / .webp file")
        elif k == "color":
            v = _color(v)
        elif k in RANGES:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"{k} must be a number")
            lo, hi = RANGES[k]
            if not lo <= float(v) <= hi:
                raise ValueError(f"{k} must be {lo}..{hi}")
            v = round(float(v), 4)
        elif k == "default":
            if not isinstance(v, bool):
                raise ValueError("default must be true or false")
        elif k == "platforms":
            if not isinstance(v, dict) or not all(isinstance(n, str) and isinstance(b, bool) for n, b in v.items()):
                raise ValueError("platforms: {platform: true | false}")
            v = {n.split(":")[0]: b for n, b in v.items()}
        out[k] = v
    return out


def _lenient(d):
    """Settings read from a file: drop (never fail on) a bad value, so an old / hand-edited file cannot stop an export."""
    out = {}
    for k, v in (d or {}).items():
        try:
            out.update(validate({k: v}))
        except ValueError as e:
            print(f"!! vstudio.watermark: ignoring {k}: {e}", file=sys.stderr)
    return out


def _read_file():
    p = settings_path()
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        print(f"!! vstudio.watermark: cannot read {p}: {e}", file=sys.stderr)
        return {}


def load():
    """The effective settings: defaults <- persona ``watermark:`` <- the settings file. Read fresh on every call (the
    desk edits the file while the engine runs)."""
    from .config import persona
    cfg = dict(DEFAULTS, platforms={})
    for layer in ((persona() or {}).get("watermark") or {}, _read_file()):
        d = _lenient(layer)
        if "platforms" in d:
            d["platforms"] = dict(cfg["platforms"], **d["platforms"])
        cfg.update(d)
    return cfg


def save(patch):
    """Merge a (validated) patch into the settings file -> the effective settings."""
    d = validate(patch)
    cur = _read_file()
    if "platforms" in d:
        d["platforms"] = dict(cur.get("platforms") or {}, **d["platforms"])
    cur.update(d)
    p = settings_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.%d.%d.tmp" % (p, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False, indent=1)
    oscompat.replace(tmp, p)
    return load()


def import_logo(path):
    """Copy a logo the creator picked into the watermark folder as a PNG (alpha kept) -> the stored path."""
    from PIL import Image
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise ValueError("logo: file not found")
    try:
        im = Image.open(path)
        im.load()
    except Exception as e:  # noqa: BLE001 - any decoder error = not an image
        raise ValueError(f"logo: not an image ({type(e).__name__})") from None
    im = im.convert("RGBA")
    if max(im.size) > 2048:
        im.thumbnail((2048, 2048), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    data = buf.getvalue()
    out = os.path.join(asset_dir(), f"logo-{hashlib.sha1(data).hexdigest()[:10]}.png")
    if not os.path.exists(out):
        tmp = "%s.%d.%d.part" % (out, os.getpid(), threading.get_ident())
        with open(tmp, "wb") as f:
            f.write(data)
        oscompat.replace(tmp, out)
    return out


# ----------------------------------------------------------------------------------- when
def configured(cfg):
    """Something to draw: a handle (text / generate) or an existing logo file (image)."""
    if not cfg:
        return False
    if cfg.get("kind") == "image":
        return bool(cfg.get("image")) and os.path.isfile(cfg["image"])
    return bool((cfg.get("text") or "").strip())


def _override(v):
    if v is None or isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("", "auto", "default", "none"):
        return None
    if s in ("on", "true", "yes", "1"):
        return True
    if s in ("off", "false", "no", "0"):
        return False
    raise ValueError(f"watermark: on | off | auto, not {v!r}")


def wants(cfg, platform=None, override=None):
    """Should this export carry the watermark? Never without one set up. ``override`` (a job / clip / CLI choice:
    True / False / None) wins; otherwise ``default`` and the per-platform switch decide."""
    if not configured(cfg):
        return False
    ov = _override(override)
    if ov is not None:
        return ov
    name = (platform or "").split(":")[0]
    if name and (cfg.get("platforms") or {}).get(name) is False:
        return False
    return bool(cfg.get("default"))


def resolve(platform=None, override=None, cfg=None):
    """The settings when this export gets the watermark, else None."""
    cfg = load() if cfg is None else cfg
    return cfg if wants(cfg, platform, override) else None


# ----------------------------------------------------------------------------------- drawing
def _rgba(c, a=255):
    from . import draw
    return draw.rgba(c, a)


def _font(px, role="cjk-bold"):
    from . import draw
    return draw.load_font(role, px)


def _text_size(text, f):
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    return x0, y0, x1, y1


def _soft_shadow(im, blur, alpha):
    from PIL import Image, ImageFilter
    pad = blur * 3
    big = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(im.split()[3].point(lambda v: v * alpha // 255))
    big.paste(sh, (pad, pad + max(1, blur // 3)), sh)
    big = big.filter(ImageFilter.GaussianBlur(blur))
    big.alpha_composite(im, (pad, pad))
    return big


def _initial(text):
    s = (text or "").strip().lstrip("@#").strip()
    return (s[:1] or "R").upper()


def text_image(text, color="#FFFFFF", px=160):
    """The handle as clean type: the colour, a thin dark edge and a soft shadow (reads on any picture)."""
    from PIL import Image, ImageDraw
    f = _font(px)
    x0, y0, x1, y1 = _text_size(text, f)
    stroke = max(2, px // 28)
    pad = stroke + 2
    im = Image.new("RGBA", (x1 - x0 + 2 * pad, y1 - y0 + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((pad - x0, pad - y0), text, font=f, fill=_rgba(color), stroke_width=stroke,
                            stroke_fill=(0, 0, 0, 110))
    return _soft_shadow(im, max(4, px // 16), 120)


def badge_image(text, style="badge", color="#FFFFFF", px=160):
    """A logo-style mark drawn from the handle (no network, no paid API):

    badge     the handle on a dark rounded pill
    monogram  a filled circle with the first letter, the handle beside it
    plain     the handle in clean type (= ``text_image``)"""
    from PIL import Image, ImageDraw
    if style == "plain":
        return text_image(text, color, px)
    f = _font(px)
    x0, y0, x1, y1 = _text_size(text, f)
    tw, th = x1 - x0, y1 - y0
    fill = _rgba(color)
    if style == "monogram":
        d = int(px * 1.5)
        gap = int(px * 0.4)
        W, H = d + gap + tw + 8, max(d, th) + 8
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dr = ImageDraw.Draw(im)
        cy = H // 2
        dr.ellipse([4, cy - d // 2, 4 + d, cy + d // 2], fill=fill)
        ini = _initial(text)
        fi = _font(int(px * 0.9))
        a0, b0, a1, b1 = _text_size(ini, fi)
        lum = 0.299 * fill[0] + 0.587 * fill[1] + 0.114 * fill[2]
        ink = (17, 17, 17, 255) if lum > 140 else (255, 255, 255, 255)
        dr.text((4 + d / 2 - (a0 + a1) / 2, cy - (b0 + b1) / 2), ini, font=fi, fill=ink)
        dr.text((4 + d + gap - x0, cy - (y0 + y1) / 2), text, font=f, fill=fill, stroke_width=max(2, px // 28),
                stroke_fill=(0, 0, 0, 110))
        return _soft_shadow(im, max(4, px // 16), 110)
    # badge
    padx, pady = int(px * 0.55), int(px * 0.32)
    W, H = tw + 2 * padx, th + 2 * pady
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([0, 0, W - 1, H - 1], radius=H // 2, fill=(12, 14, 20, 150),
                         outline=fill[:3] + (90,), width=max(2, px // 40))
    dr.text((padx - x0, pady - y0), text, font=f, fill=fill)
    return _soft_shadow(im, max(4, px // 16), 90)


def generate(text, style="badge", color="#FFFFFF", out=None):
    """Draw a logo-style watermark PNG from the handle -> its path (cached by content under the watermark folder)."""
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("generate: type your handle or name first")
    validate(dict(text=text, style=style, color=color))
    im = badge_image(text, style, color)
    if out is None:
        key = hashlib.sha1(json.dumps([text, style, _color(color), 2]).encode()).hexdigest()[:10]
        out = os.path.join(asset_dir(), f"generated-{key}.png")
        if os.path.exists(out):
            return out
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = "%s.%d.%d.part" % (out, os.getpid(), threading.get_ident())   # atomic: a parallel preview never reads half
    im.save(tmp, "PNG")
    oscompat.replace(tmp, out)
    return out


_SRC = {}


def source_image(cfg):
    """The full-size mark (PIL RGBA) before scaling / opacity, cached per settings."""
    from PIL import Image
    kind = cfg.get("kind") or "text"
    if kind == "image":
        st = os.stat(cfg["image"])
        key = ("image", cfg["image"], st.st_size, int(st.st_mtime))
    else:
        key = (kind, cfg.get("text"), cfg.get("style"), cfg.get("color"))
    if key not in _SRC:
        if kind == "image":
            im = Image.open(cfg["image"]).convert("RGBA")
            bb = im.getbbox()                      # a logo with a wide transparent margin: placed by what shows
            if bb:
                im = im.crop(bb)
        elif kind == "generate":
            im = Image.open(generate(cfg["text"], cfg.get("style") or "badge", cfg.get("color") or "#FFFFFF"))
            im = im.convert("RGBA")
        else:
            im = text_image(cfg["text"], cfg.get("color") or "#FFFFFF")
        if len(_SRC) > 16:
            _SRC.clear()
        _SRC[key] = im
    return _SRC[key]


# ----------------------------------------------------------------------------------- placement
def _generic_profile(W, H):
    from . import platform as P
    r = W / float(H)
    name = "tiktok:vertical" if r < 0.66 else "xiaohongshu:vertical" if r < 0.9 else \
        "youtube:horizontal" if r > 1.3 else None
    if not name:
        return None
    n, o = name.split(":")
    return P.profile(n, o, use_persona=False)


def areas(W, H, prof=None):
    """(safe box, caption keep-out or None) in this canvas' pixels. A horizontal canvas keeps only the centre 70 % of
    its caption band out (lines are centred and rarely span the width); a vertical one keeps the whole band out."""
    from . import platform as P
    p = prof if prof is not None else _generic_profile(W, H)
    if p is None:
        m = 0.04 * min(W, H)
        return (m, m, W - m, H - m), None
    sx, sy = W / float(p.w), H / float(p.h)
    s = P.safe_box(p)
    c = P.caption_box(p)
    safe = (s[0] * sx, s[1] * sy, s[2] * sx, s[3] * sy)
    cap = [c[0] * sx, c[1] * sy, c[2] * sx, c[3] * sy]
    if W > H:
        cw = cap[2] - cap[0]
        cap[0], cap[2] = cap[0] + cw * 0.15, cap[2] - cw * 0.15
    return safe, tuple(cap)


def _hits(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


def box(cfg, W, H, prof=None, src_size=None):
    """Where the mark goes: (x, y, w, h) in px. It fits a square of ``size`` x the short side, sits in the chosen
    corner of the safe box (+ ``margin``) and steps over the caption band when the corner would cover it."""
    sw, sh = src_size or source_image(cfg).size
    short = min(W, H)
    side = float(cfg.get("size") or DEFAULTS["size"]) * short
    k = min(side / sw, side / sh)
    w, h = max(1, int(round(sw * k))), max(1, int(round(sh * k)))
    safe, cap = areas(W, H, prof)
    m = float(cfg.get("margin") or 0.0) * short
    pos = cfg.get("position") or DEFAULTS["position"]
    x = safe[0] + m if pos.endswith("left") else safe[2] - m - w
    y = safe[1] + m if pos.startswith("top") else safe[3] - m - h
    if cap and _hits((x, y, x + w, y + h), cap):
        gap = max(m, 0.015 * short)
        y = cap[1] - gap - h if pos.startswith("bottom") else cap[3] + gap
    x = min(max(0, x), W - w)
    y = min(max(0, y), H - h)
    return int(round(x)), int(round(y)), w, h


def layer(cfg, W, H, prof=None):
    """(RGBA numpy array with the opacity applied, (x, y)) for one canvas."""
    import numpy as np
    from PIL import Image
    src = source_image(cfg)
    x, y, w, h = box(cfg, W, H, prof, src.size)
    im = src.resize((w, h), Image.LANCZOS)
    a = np.asarray(im).copy()
    a[..., 3] = (a[..., 3].astype(np.float32) * float(cfg.get("opacity") or 1.0) + 0.5).astype(np.uint8)
    return a, (x, y)


def overlay(cfg, W, H, prof=None):
    """img_bgr -> img_bgr with the mark drawn (for frame pipelines: reframe.render, the output frame pass)."""
    from . import draw
    arr, xy = layer(cfg, W, H, prof)

    def f(img):
        draw.alpha_paste(img, arr, xy, bgr=True)
        return img
    return f


def write_png(cfg, W, H, prof, path):
    """The scaled mark as a PNG for an ffmpeg ``overlay`` -> (path, x, y)."""
    from PIL import Image
    arr, (x, y) = layer(cfg, W, H, prof)
    Image.fromarray(arr, "RGBA").save(path)
    return path, x, y


def ffmpeg_overlay(vin, png_index, x, y, vout="[v]"):
    """filter_complex chain: the PNG input ``png_index`` over the video label ``vin`` (e.g. "[b]")."""
    return f"{vin}[{png_index}:v]overlay={x}:{y}:format=auto{vout}"


def spec(cfg, W, H, prof=None):
    """JSON description of what is drawn (render cache keys): the settings that change the picture + the box."""
    keep = {k: cfg.get(k) for k in ("kind", "text", "style", "color", "position", "size", "opacity", "margin")}
    if cfg.get("kind") == "image":
        st = os.stat(cfg["image"])
        keep.update(image=cfg["image"], image_sig=[st.st_size, int(st.st_mtime)])
    return dict(cfg=keep, box=list(box(cfg, W, H, prof)), canvas=[W, H])


def from_spec(s):
    """The settings a ``spec`` was made from (for drawing it later in a render stage)."""
    return dict(DEFAULTS, **{k: v for k, v in (s.get("cfg") or {}).items() if k != "image_sig"})


def summary(cfg):
    """Short manifest note of what was applied."""
    return dict(kind=cfg.get("kind"), position=cfg.get("position"),
                text=cfg.get("text") if cfg.get("kind") != "image" else None,
                image=os.path.basename(cfg.get("image") or "") or None)


def already_marked(path):
    """True when ``path`` is an export this engine already watermarked (its export manifest says so)."""
    d, name = os.path.split(os.path.abspath(path))
    try:
        with open(os.path.join(d, "manifest.json"), encoding="utf-8") as f:
            man = json.load(f)
    except (OSError, ValueError):
        return False
    rows = man.get("exports") if isinstance(man, dict) else man
    for e in rows or []:
        if isinstance(e, dict) and os.path.basename(str(e.get("file") or "")) == name:
            return bool(e.get("watermark"))
    return False


# ----------------------------------------------------------------------------------- apply / preview
def apply_file(src, dst, cfg, prof=None, encode_args=None):
    """Re-encode ``src`` with the mark (audio stream-copied) -> dst. For a finished file outside the export path."""
    import tempfile

    from . import media
    info = media.probe(src)
    W, H = int(info.get("display_w") or info["w"]), int(info.get("display_h") or info["h"])
    with tempfile.TemporaryDirectory(prefix="vwm-") as td:
        png, x, y = write_png(cfg, W, H, prof, os.path.join(td, "wm.png"))
        cmd = [media.ffmpeg_bin(), "-y", "-v", "error", "-i", src, "-i", png, "-filter_complex",
               ffmpeg_overlay("[0:v]", 1, x, y), "-map", "[v]"]
        if info.get("has_audio"):
            cmd += ["-map", "0:a:0", "-c:a", "copy"]
        args = list(encode_args) if encode_args is not None else media.delivery_args(audio=None)
        media.run(cmd + [a for a in args if a != "-an"] + [dst])
    return dst


SAMPLES = {"9:16": "tiktok:vertical", "16:9": "youtube:horizontal", "3:4": "xiaohongshu:vertical"}


def sample_frame(W, H, prof=None):
    """A neutral stand-in picture: a soft gradient, a sample caption in the caption band, the safe area outlined."""
    import numpy as np
    from PIL import Image, ImageDraw
    yy = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    xx = np.linspace(0, 1, W, dtype=np.float32)[None, :]
    r = 46 + 60 * xx + 20 * yy
    g = 58 + 40 * yy + 22 * xx
    b = 74 + 70 * (1 - yy) + 10 * xx
    im = Image.fromarray(np.dstack([r, g, b]).clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    safe, cap = areas(W, H, prof)
    dr = ImageDraw.Draw(im)
    lw = max(2, min(W, H) // 360)
    dr.rounded_rectangle([int(v) for v in safe], radius=min(W, H) // 40, outline=(255, 255, 255, 70), width=lw)
    if cap:
        cx, cy = (cap[0] + cap[2]) / 2, (cap[1] + cap[3]) / 2
        f = _font(int(min(W, H) * 0.05))
        line = "Captions · 字幕"
        x0, y0, x1, y1 = _text_size(line, f)
        dr.text((cx - (x0 + x1) / 2, cy - (y0 + y1) / 2), line, font=f, fill=(255, 255, 255, 235),
                stroke_width=max(2, lw), stroke_fill=(0, 0, 0, 200))
    return im


def preview(cfg, aspect="9:16", height=640):
    """The mark over a sample frame of ``aspect`` (9:16 / 16:9 / 3:4), as the export would place it -> PIL RGB,
    ``height`` px tall."""
    from PIL import Image

    from . import platform as P
    n, o = SAMPLES.get(aspect, SAMPLES["9:16"]).split(":")
    p = P.profile(n, o, use_persona=False)
    im = sample_frame(p.w, p.h, p)
    if configured(cfg):
        arr, (x, y) = layer(cfg, p.w, p.h, p)
        im.alpha_composite(Image.fromarray(arr, "RGBA"), (x, y))
    im = im.convert("RGB")
    k = height / float(p.h)
    return im.resize((max(1, int(p.w * k)), height), Image.LANCZOS)


def preview_data_url(cfg, aspect="9:16", height=640):
    buf = io.BytesIO()
    preview(cfg, aspect, height).save(buf, "JPEG", quality=86)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ----------------------------------------------------------------------------------- CLI
def _bool(s):
    v = _override(s)
    if v is None:
        raise argparse.ArgumentTypeError("on | off")
    return v


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.watermark", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="the effective settings and whether exports get the mark")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("set", help="change the settings (written to $VSTUDIO_HOME/watermark.json)")
    s.add_argument("--kind", choices=KINDS)
    s.add_argument("--text")
    s.add_argument("--image", help="a PNG / JPG logo (copied into the watermark folder)")
    s.add_argument("--style", choices=STYLES)
    s.add_argument("--color")
    s.add_argument("--position", choices=POSITIONS)
    s.add_argument("--size", type=float)
    s.add_argument("--opacity", type=float)
    s.add_argument("--margin", type=float)
    s.add_argument("--default", type=_bool, help="on = every export gets it unless a job says watermark: false")
    s.add_argument("--platform", action="append", default=[], help="name=off (never there) or name=on")
    s = sub.add_parser("generate", help="draw a logo-style watermark PNG from a handle")
    s.add_argument("--text", required=True)
    s.add_argument("--style", choices=STYLES, default="badge")
    s.add_argument("--color", default="#FFFFFF")
    s.add_argument("--out", required=True)
    s = sub.add_parser("preview", help="the mark over a sample frame")
    s.add_argument("--aspect", choices=sorted(SAMPLES), default="9:16")
    s.add_argument("--out", required=True)
    s = sub.add_parser("apply", help="re-encode a finished video with the mark")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("--platform", help="platform[:orientation] whose safe area to use")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "show":
            cfg = load()
            res = dict(settings=cfg, configured=configured(cfg), default_on=wants(cfg), file=settings_path())
            print(json.dumps(res, ensure_ascii=False, indent=1) if a.json else
                  f"{'on by default' if res['default_on'] else 'set up, off by default' if res['configured'] else 'not set up'}"
                  f" · {cfg['kind']} {cfg['text'] or os.path.basename(cfg['image'] or '')} · {cfg['position']}")
            return 0
        if a.cmd == "set":
            patch = {k: getattr(a, k) for k in ("kind", "text", "style", "color", "position", "size", "opacity",
                                                 "margin", "default") if getattr(a, k) is not None}
            if a.image:
                patch["image"] = import_logo(a.image)
                patch.setdefault("kind", "image")
            if a.platform:
                patch["platforms"] = {}
                for x in a.platform:
                    n, _, v = x.partition("=")
                    patch["platforms"][n.strip()] = _bool(v)
            cfg = save(patch)
            print(json.dumps(cfg, ensure_ascii=False))
            return 0
        if a.cmd == "generate":
            print(generate(a.text, a.style, a.color, out=a.out))
            return 0
        if a.cmd == "preview":
            preview(load(), a.aspect, height=1280).save(a.out, quality=90)
            print(a.out)
            return 0
        if a.cmd == "apply":
            cfg = load()
            if not configured(cfg):
                print("no watermark set up: python -m vstudio.watermark set --text @you", file=sys.stderr)
                return 2
            prof = None
            if a.platform:
                from . import platform as P
                n, _, o = a.platform.partition(":")
                prof = P.profile(n, o or None)
            print(apply_file(a.src, a.dst, cfg, prof))
            return 0
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
