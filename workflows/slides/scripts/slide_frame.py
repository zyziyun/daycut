"""Shared by render_slides.py / record_slides.py: slide accent, canvas size and safe-area CSS vars.

  accent  persona `slides.accent` (default teal #2dd4bf), `--accent` overrides; injected as --slides-accent
          (deliberately NOT persona brand.accent, which is the red talking-head/promo accent for many creators).
  size    --layout split (default): square, side = min(profile canvas) or 1080 without --platform.
          --layout full: the platform profile's canvas; padding/footnote kept inside platform.safe_box + keepouts.
          --size WxH always wins.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

from vstudio import platform as P
from vstudio.config import persona
from vstudio.render import inject_css

DEFAULT_ACCENT = "#2dd4bf"
BASE_PAD = 60          # template .slide padding
BASE_FOOT = 54         # template .footnote bottom


def add_args(ap):
    ap.add_argument("--size", default=None, help="WxH; overrides --platform/--layout (default 1080x1080)")
    ap.add_argument("--platform", default=None,
                    help="platform profile, e.g. xiaohongshu:vertical, douyin, youtube (vstudio.platform)")
    ap.add_argument("--layout", choices=("split", "full"), default="split",
                    help="split (default): square slide for a split/top-half layout; "
                         "full: whole platform canvas, content inside the safe zones")
    ap.add_argument("--accent", default=None, help="accent colour (default persona slides.accent or #2dd4bf)")
    ap.add_argument("--no-persona", action="store_true",
                    help="don't inject persona brand vars nor read slides.accent (accent = --accent or teal)")


def accent(a):
    if a.accent:
        return a.accent
    if a.no_persona:
        return DEFAULT_ACCENT
    return (persona().get("slides") or {}).get("accent", DEFAULT_ACCENT)


def _profile(a):
    if a.platform:
        return P.profile(a.platform)
    if a.layout == "full":
        return P.profile((persona().get("platforms") or {}).get("default") or "xiaohongshu")
    return None


def frame(a):
    """-> (w, h, {css var: value}) for the parsed args."""
    p = _profile(a)
    vars_ = {"--slides-accent": accent(a)}
    if a.layout == "full":
        w, h = p.size
        x0, y0, x1, y1 = P.safe_box(p)
        right = p.w - x1
        for kx0, ky0, kx1, ky1 in P.keepouts(p):
            right = max(right, p.w - kx0)            # side button column: keep content left of it
        top, bottom, left = y0, p.h - y1, x0
        vars_.update({"--safe-top": f"{max(BASE_PAD, top)}px", "--safe-right": f"{max(BASE_PAD, right)}px",
                      "--safe-bottom": f"{max(BASE_PAD, bottom)}px", "--safe-left": f"{max(BASE_PAD, left)}px",
                      "--footnote-bottom": f"{max(BASE_FOOT, bottom + 24)}px"})
    elif p is not None:
        w = h = min(p.size)
    else:
        w = h = 1080
    if a.size:
        w, h = (int(v) for v in a.size.lower().split("x"))
    return w, h, vars_


def css(vars_):
    return ":root{" + "".join(f"{k}:{v};" for k, v in vars_.items()) + "}"


def write_page(html, vars_, persona_css=None):
    """Sibling copy of `html` (same dir: assets/fonts resolve) with the slide vars (+ optional persona CSS)
    injected. Caller removes it."""
    src = pathlib.Path(html).resolve()
    page = src.with_name(src.stem + ".slides.html")
    text = inject_css(src.read_text(encoding="utf-8"), css(vars_), style_id="vstudio-slides")
    if persona_css:
        text = inject_css(text, persona_css)
    page.write_text(text, encoding="utf-8")
    return page
