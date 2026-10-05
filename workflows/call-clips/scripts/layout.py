"""Platform geometry and name-label masking shared by the call-clips renderers.

Platform (wave B): every renderer takes ``--platform`` (``xiaohongshu``, ``douyin:vertical``,
``youtube``, ``bilibili:horizontal`` ...; see ``vstudio.platform``). The canvas, the UI-free safe box
and the caption box come from that profile, so the title, chips, badge, panels and captions stay
clear of the app's top bar, bottom description and button column.

  ``--platform legacy`` (or no flag on render_trio / render_landscape / render_landscape_trio)
  keeps the pre-wave-B fixed geometry, unchanged. ``render_vertical`` defaults to the persona's
  ``platforms.default`` instead: its old full-bleed layout ignored the phone safe zone.

A vertical renderer given a bare platform name picks that platform's 9:16 canvas (``full`` for
小红书, ``vertical`` elsewhere); ask for ``xiaohongshu:vertical`` to get the 3:4 feed canvas.

Name labels: call apps stamp each participant's real name at a tile's bottom-left, and real-media
QA found it visible beside the label chip. ``mask_names`` blurs (or covers) that region of each tile
in SOURCE pixels before any crop, so it is gone whatever the layout does with the tile.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import cv2
import numpy as np

from vstudio import platform as P
from vstudio.config import persona

LEGACY = ("", "legacy", "none", "off")


def _default_name():
    d = (persona().get("platforms") or {}).get("default") or "xiaohongshu"
    return str(d[0] if isinstance(d, (list, tuple)) else d).split(",")[0].strip()


def resolve(spec, family):
    """Profile for a renderer family ("vertical" | "horizontal"), or None for the legacy geometry.
    spec None/"legacy" -> None; "default" -> persona platforms.default; "name[:orientation]"."""
    if spec is None or str(spec).strip().lower() in LEGACY:
        return None
    spec = str(spec).strip()
    if spec.lower() == "default":
        spec = _default_name()
    name, _, orient = spec.partition(":")
    name = P.canonical(name)
    if name not in P.PLATFORMS:
        sys.exit(f"--platform {spec}: unknown platform; one of {sorted(P.PLATFORMS)}")
    ors = P.PLATFORMS[name]["orientations"]
    if not orient:
        if family == "vertical":
            orient = "full" if "full" in ors else "vertical" if "vertical" in ors else None
        else:
            orient = "horizontal" if "horizontal" in ors else None
        if orient is None:
            sys.exit(f"--platform {spec}: {name} has no {family} canvas "
                     f"({', '.join(sorted(ors))}); pick another platform or renderer")
    prof = P.profile(name, orient)
    if (family == "vertical") != (prof.h > prof.w):
        sys.exit(f"--platform {prof.key} is {prof.w}x{prof.h}: not a {family} canvas for this renderer")
    return prof


def boxes(prof):
    """dict(W, H, safe, caption, keepouts) for a profile."""
    return dict(W=prof.w, H=prof.h, safe=P.safe_box(prof), caption=P.caption_box(prof),
                keepouts=P.keepouts(prof))


def vcrop(region, out_w, out_h, cy_hint=None):
    """(x0, y0, w, h) inside region (x, y, w, h): full region width, height cut to out_w:out_h, centred
    on cy_hint (source y of the face; default the upper-middle of the tile, where faces sit)."""
    x, y, w, h = region
    ch = min(h, int(round(w * out_h / out_w)))
    cy = cy_hint if cy_hint is not None else y + h * 0.46
    y0 = int(round(min(max(cy - ch * 0.46, y), y + h - ch)))
    return x, y0, w, ch


def caption_overlay(prof, subs, bilingual=False):
    """overlay(t, canvas_bgr) burning the active line inside the profile's caption box: size from
    platform.fit_text_size (the vstudio.export look), then shrunk until the whole block (incl. an
    English line) fits the box HEIGHT too, so a two-line caption never climbs onto the tiles."""
    from vstudio import draw
    from vstudio.export import _lines_layer
    from PIL import Image
    x0, y0, x1, y1 = P.caption_box(prof)
    lo = int(prof.caption["size"][0])
    stroke_k = float(prof.caption.get("stroke", 0.08))
    cache = {}

    def layer(text, alt):
        fit = P.fit_text_size(prof, text.replace("\n", " "))
        size, lines = fit["size"], fit["lines"]
        while True:
            f = draw.load_font("cjk-bold", size)
            stroke = max(2, int(size * stroke_k))
            im = _lines_layer(lines, f, (255, 255, 255, 255), stroke)
            if alt:
                fa = draw.load_font("cjk", max(16, int(size * 0.66)))
                al = draw.wrap(alt.strip(), fa, x1 - x0, balance=True, max_lines=2)
                sec = _lines_layer(al, fa, (226, 232, 240, 255), max(2, stroke * 2 // 3))
                w = max(im.width, sec.width)
                both = Image.new("RGBA", (w, im.height + sec.height - 8), (0, 0, 0, 0))
                both.alpha_composite(im, ((w - im.width) // 2, 0))
                both.alpha_composite(sec, ((w - sec.width) // 2, im.height - 8))
                im = both
            if im.height <= (y1 - y0) or size <= max(28, lo - 16):
                return np.asarray(im)
            size -= 2
            lines = P._wrap(text, draw.load_font("cjk-bold", size),
                            (x1 - x0) - 2 * int(size * stroke_k) - 8, int(prof.caption.get("max_lines", 2)))

    spans = [(float(s["start"]), float(s["end"]), s.get("zh") or s.get("text", ""),
              (s.get("en") or "") if bilingual else "") for s in subs]

    def overlay(t, img):
        for a, b, text, alt in spans:
            if a <= t < b and text.strip():
                key = (text, alt)
                if key not in cache:
                    cache[key] = layer(text, alt)
                L = cache[key]
                h, w = L.shape[:2]
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                draw.alpha_paste(img, L, (cx - w / 2, max(y0, min(cy - h / 2, y1 - h))), bgr=True)
                break
        return img
    return overlay


# ----------------------------------------------------------------------------------- name labels
DEFAULT_BOX = (0.0, 0.90, 0.40, 0.10)     # x, y, w, h as fractions of the tile: the bottom-left label


def parse_name_mask(spec):
    """'blur' | 'cover' | 'off' | dict(mode, box=[fx, fy, fw, fh], tiles='all'|'guests', extra=[[x,y,w,h]])
    -> normalised dict. Default: blur every tile's bottom-left name label."""
    if spec is None:
        spec = (persona().get("call_clips") or {}).get("name_mask", "blur")
    if isinstance(spec, str):
        spec = {"mode": spec}
    m = dict(mode="blur", box=list(DEFAULT_BOX), tiles="all", extra=[])
    m.update({k: v for k, v in spec.items() if v is not None})
    if isinstance(m["box"], str):
        m["box"] = [float(v) for v in m["box"].split(",")]
    if m["mode"] not in ("blur", "cover", "off"):
        sys.exit(f"name mask mode {m['mode']!r}: blur | cover | off")
    return m


def name_rects(m, guest_regions, host_regions):
    """Source-pixel rects to hide for the configured tiles."""
    if m["mode"] == "off":
        return []
    regs = list(guest_regions) + (list(host_regions) if m["tiles"] == "all" else [])
    fx, fy, fw, fh = m["box"]
    out = [(int(x + fx * w), int(y + fy * h), max(1, int(round(fw * w))), max(1, int(round(fh * h))))
           for x, y, w, h in regs]
    return out + [tuple(int(v) for v in r) for r in m.get("extra") or []]


def mask_names(frame, rects, mode="blur"):
    """Hide each rect of a BGR frame in place: 'blur' smears it (1/16 downscale, then blur: no glyph
    survives), 'cover' fills it with the region's median colour."""
    H, W = frame.shape[:2]
    for x, y, w, h in rects:
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        reg = frame[y0:y1, x0:x1]
        if mode == "cover":
            reg[:] = np.median(reg.reshape(-1, 3), axis=0).astype(np.uint8)
        else:
            small = cv2.resize(reg, (max(1, (x1 - x0) // 16), max(1, (y1 - y0) // 16)), interpolation=cv2.INTER_AREA)
            reg[:] = cv2.GaussianBlur(cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR), (0, 0), 3)
    return frame


def add_args(ap, platform_default=None):
    """--platform / --name-mask / --name-box / --name-tiles / --no-subs / --show-safe for a renderer."""
    ap.add_argument("--platform", default=platform_default,
                    help="platform profile for canvas + safe/caption boxes, e.g. xiaohongshu, douyin, "
                         "youtube, bilibili:horizontal; 'legacy' = the fixed pre-platform geometry "
                         f"(default: {platform_default or 'legacy'})")
    ap.add_argument("--name-mask", default=None, choices=["blur", "cover", "off"],
                    help="hide the call app's name label in each tile (default persona call_clips.name_mask, else blur)")
    ap.add_argument("--name-box", default=None, help="label rect as tile fractions fx,fy,fw,fh (default 0,0.90,0.40,0.10)")
    ap.add_argument("--name-tiles", default=None, choices=["all", "guests"], help="which tiles (default all)")
    ap.add_argument("--name-extra", default=None,
                    help="more source-pixel rects to hide, 'x,y,w,h;x,y,w,h' (e.g. a label in another corner)")
    ap.add_argument("--no-subs", action="store_true", help="caption-free render (clean master for vstudio.export)")
    ap.add_argument("--show-safe", action="store_true", help="draw the safe (green) and caption (yellow) boxes (QA)")


def name_mask_from_args(args):
    m = parse_name_mask({"mode": args.name_mask, "box": args.name_box, "tiles": args.name_tiles}
                        if (args.name_mask or args.name_box or args.name_tiles) else None)
    if getattr(args, "name_extra", None):
        m["extra"] = list(m.get("extra") or []) + [[int(v) for v in r.split(",")] for r in args.name_extra.split(";") if r]
    return m


def draw_safe(canvas, prof):
    if prof is None:
        return
    x0, y0, x1, y1 = P.safe_box(prof)
    cv2.rectangle(canvas, (x0, y0), (x1 - 1, y1 - 1), (0, 255, 0), 2)
    cx0, cy0, cx1, cy1 = P.caption_box(prof)
    cv2.rectangle(canvas, (cx0, cy0), (cx1 - 1, cy1 - 1), (0, 255, 255), 2)
    for kx0, ky0, kx1, ky1 in P.keepouts(prof):
        cv2.rectangle(canvas, (kx0, ky0), (kx1 - 1, ky1 - 1), (0, 0, 255), 2)


# ----------------------------------------------------------------------------------- covers
def cover_profile(spec, family):
    """Profile whose cover size a cover/thumbnail should use, or None (keep the script's own size)."""
    return resolve(spec, family) if spec else None


def fit_saved_cover(path, prof):
    """Re-fit a written cover/thumbnail to the profile's cover size (cover-crop, centre); max_bytes kept."""
    if prof is None:
        return
    from PIL import Image
    from vstudio.export import fit_cover
    W, H = P.cover_size(prof)
    im = Image.open(path)
    if im.size == (W, H):
        return
    if abs(np.log((im.width / im.height) / (W / H))) > 0.05:
        print(f"note: {im.width}x{im.height} cover-cropped to {prof.key} {W}x{H}: check the headline still fits")
    fit_cover(im, (W, H)).save(path, quality=95)
    mb = prof.cover.get("max_bytes")
    if mb and pathlib.Path(path).stat().st_size > mb:
        Image.open(path).save(path, quality=82)
