#!/usr/bin/env python3
"""Render a Pattern A / B cover template (HTML) at each platform's cover size, in the cover accent.

    python3 render_cover.py work/cover.html -o work/cover.png                      # 1080x1920 (as before)
    python3 render_cover.py work/cover.html -o work/cover.png --platform xiaohongshu --platform douyin

Per platform (vstudio.platform.cover_size): the page is laid out at a design size of the same aspect whose
short side is >= 1080 (3:4 -> 1080x1440, 9:16 -> 1080x1920, 16:9 -> 1920x1080, 16:10 -> 1728x1080), then
scaled to the exact cover size (YouTube 1280x720, B站 1146x717). The templates read --W / --H / --fs
(type scale) and --cover-accent, all injected here. Covers shown as a centre crop in the feed (小红书 16:9
-> 4:3, 抖音 grid -> 3:4) also get a <out>.feed.jpg preview.

Accent: persona ``cover.accent`` (default teal #2dd4bf, the original collage / face-quadrant look; the
brand red stays for on-video graphics). ``--accent '#ff2442'`` overrides it for one render.
Without --platform the output is the old 1080x1920 cover at -o. With several platforms each file is
<out stem>.<platform>-<orientation>.<ext>.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import os

from vstudio import platform as P
from vstudio.config import persona
from vstudio.render import html_to_png, inject_css

DEFAULT_ACCENT = "#2dd4bf"


def cover_accent():
    return ((persona().get("cover") or {}).get("accent")) or DEFAULT_ACCENT


def design_size(w, h):
    """Same aspect, short side >= 1080 (templates are drawn at 1080 px wide)."""
    k = 1080 / min(w, h)
    return (int(round(w * k / 2)) * 2, int(round(h * k / 2)) * 2) if k > 1 else (w, h)


def type_scale(w, h):
    """Font / face scale relative to the 1080x1920 design: shorter canvases get smaller type."""
    return round(min(1.0, (h / 1920) * 1.15) if h > w else 0.72, 3)


def render(html, out, size, accent, wait=2000):
    W, H = design_size(*size)
    css = f":root{{--W:{W}px;--H:{H}px;--fs:{type_scale(W, H)};--cover-accent:{accent};}}"
    src = pathlib.Path(html).resolve()
    page = src.with_name(src.stem + f".{W}x{H}.html")
    page.write_text(inject_css(src.read_text(encoding="utf-8"), css, style_id="cover-size"), encoding="utf-8")
    try:
        for attempt in range(3):          # headless Chrome occasionally exits 2 under heavy load: retry
            try:
                html_to_png(str(page), out, size=(W, H), wait=wait); break
            except Exception:
                if attempt == 2: raise
    finally:
        page.unlink(missing_ok=True)
    if (W, H) != tuple(size):
        from PIL import Image
        Image.open(out).convert("RGB").resize(tuple(size), Image.LANCZOS).save(out)
    return out


def feed_preview(prof, out):
    fc = prof.cover.get("feed_crop")
    if not fc:
        return None
    from PIL import Image
    im = Image.open(out); W, H = im.size
    aw, ah = (float(v) for v in fc.split(":"))
    cw, ch = (H * aw / ah, H) if W / H > aw / ah else (W, W * ah / aw)
    x0, y0 = (W - cw) / 2, (H - ch) / 2
    p = os.path.splitext(out)[0] + ".feed.jpg"
    im.convert("RGB").crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).save(p, quality=90)
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html"); ap.add_argument("-o", "--out", default="cover.png")
    ap.add_argument("--platform", action="append", default=[], help="e.g. xiaohongshu, douyin, youtube-shorts, youtube")
    ap.add_argument("--size", help="WxH instead of a platform (default 1080x1920)")
    ap.add_argument("--accent", help="override persona cover.accent for this render")
    ap.add_argument("--wait", type=int, default=2000)
    a = ap.parse_args()
    accent = a.accent or cover_accent()
    if not a.platform:
        size = tuple(int(v) for v in (a.size or "1080x1920").lower().split("x"))
        print(render(a.html, a.out, size, accent, a.wait)); return
    stem, ext = os.path.splitext(a.out)
    for sp in a.platform:
        prof = P.profile(sp)
        out = a.out if len(a.platform) == 1 else f"{stem}.{prof.name}-{prof.orientation}{ext}"
        render(a.html, out, P.cover_size(prof), accent, a.wait)
        fp = feed_preview(prof, out)
        print(f"{prof.key}: {P.cover_size(prof)} -> {out}" + (f"  (feed preview {fp})" if fp else ""))


if __name__ == "__main__":
    main()
