"""Brand -> theme tokens, font faces and measured text fitting, shared by the videos and the stills.

    T = theme(cfg)                         # vstudio.theme preset + the brand's colours (paper / ink / accent / marker)
    faces = stage_fonts(cfg, dst, text)    # copies / subsets fonts into dst -> {"display": (family, file), ...}
    px, lines = fit(text, role_file, (56, 40), width, max_lines, lang)

Fonts: ``brand.fonts.display`` / ``brand.fonts.text`` (any OFL font file: .woff2/.ttf/.otf) for Latin; Chinese text
always uses the engine's Noto Serif SC / Noto Sans SC (vstudio.config.FONTS), subset to the characters on screen.
Without brand fonts the theme's own roles are used (STIX Two Text serif for display, Noto Sans SC for text).
"""
import functools
import os
import re
import shutil
import tempfile

from vstudio import config as VC
from vstudio import theme as TH

COLOR_KEYS = ("paper", "ink", "ink2", "rule", "accent", "accent_ink", "marker", "card", "card_ink")
# a few brand colours read as "red" (the old look she rejected); warn instead of silently shipping them
RED_HUES = ((345, 360), (0, 15))


def theme(cfg):
    b = cfg.get("brand") or {}
    layer = {"theme": b.get("theme") or "editorial"}
    layer.update({k: v for k, v in (b.get("colors") or {}).items() if k in COLOR_KEYS and v})
    return TH.resolve(layer)


def is_reddish(hex_color):
    import colorsys
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    deg = hue * 360
    return sat > 0.45 and 0.25 < light < 0.75 and any(lo <= deg <= hi for lo, hi in RED_HUES)


def warnings(cfg):
    T = theme(cfg)
    out = []
    if is_reddish(T["accent"]):
        out.append(f"brand accent {T['accent']} reads as red; the editorial look keeps red out of overlays")
    c = TH.contrast(TH.rgb(T, "ink"), TH.rgb(T, "paper"))
    if c < 7:
        out.append(f"ink {T['ink']} on paper {T['paper']}: contrast {c:.1f} < 7")
    return out


def _engine_font(role):
    return VC.font(role)


def font_files(cfg, lang):
    """{display, text, text_bold} -> font file paths for ``lang``."""
    f = (cfg.get("brand") or {}).get("fonts") or {}
    if lang == "zh":
        return dict(display=_engine_font("cjk-serif-bold"), text=_engine_font("cjk"), text_bold=_engine_font("cjk-bold"))
    return dict(display=f.get("display") or _engine_font("serif"), text=f.get("text") or _engine_font("cjk"),
                text_bold=f.get("text_bold") or f.get("text") or _engine_font("cjk-bold"))


@functools.lru_cache(maxsize=32)
def _pil_path(path):
    """PIL cannot always read .woff2: convert once to a temp .ttf with fontTools."""
    if not path.lower().endswith((".woff2", ".woff")):
        return path
    from fontTools.ttLib import TTFont
    ft = TTFont(path)
    ft.flavor = None
    out = os.path.join(tempfile.gettempdir(), "vstudio-launch-" + os.path.basename(path) + ".ttf")
    ft.save(out)
    return out


@functools.lru_cache(maxsize=256)
def _font(path, px, weight=None):
    from PIL import ImageFont
    f = ImageFont.truetype(_pil_path(path), int(px))
    if weight:
        try:                                          # variable fonts: pick the weight the CSS will use
            axes = f.get_variation_axes()
        except Exception:                             # noqa: BLE001 - static font
            axes = []
        if axes:
            vals = [a["default"] for a in axes]
            for i, a in enumerate(axes):
                if a.get("name") in (b"Weight", "Weight"):
                    vals[i] = weight
            f.set_variation_by_axes(vals)
    return f


def measure(text, path, px, weight=None):
    return _font(path, px, weight).getlength(re.sub(r"[【】]", "", text))


def _tokens(text, lang):
    """Breakable units: words (+ their trailing space) for Latin, characters for CJK; 【...】 stays one unit."""
    if lang == "zh":
        out, i = [], 0
        while i < len(text):
            if text[i] == "【":
                j = text.find("】", i)
                j = len(text) - 1 if j < 0 else j
                out.append(text[i:j + 1])
                i = j + 1
            else:
                out.append(text[i])
                i += 1
        # keep closing punctuation with the previous unit
        merged = []
        for t in out:
            if merged and t in "，。、！？；：）」》,.!?;:":
                merged[-1] += t
            else:
                merged.append(t)
        return merged
    return re.findall(r"【[^】]*】\S*\s*|\S+\s*", text)


def wrap(text, path, px, width, lang, weight=None):
    lines, cur = [], ""
    for tok in _tokens(text, lang):
        trial = cur + tok
        if cur and measure(trial.rstrip(), path, px, weight) > width:
            lines.append(cur.rstrip())
            cur = tok.lstrip() if lang != "zh" else tok
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return lines


def fit(text, path, px_range, width, max_lines, lang="en", weight=None):
    """Largest font size in px_range (hi, lo) at which ``text`` wraps into <= max_lines within ``width``.
    -> (px, lines). Raises ValueError when even the smallest size needs more lines (shorten the caption)."""
    hi, lo = px_range
    for px in range(int(hi), int(lo) - 1, -2):
        lines = wrap(text, path, px, width, lang, weight)
        if len(lines) <= max_lines and all(measure(ln, path, px, weight) <= width for ln in lines):
            return px, _balance(lines, text, path, px, width, lang, weight)
    raise ValueError(f"caption too long for {max_lines} line(s) at {lo}px in {width}px: {text!r}")


def _balance(lines, text, path, px, width, lang, weight):
    """Same number of lines, more even lengths (no lonely last word): the narrowest width that still wraps into
    as many lines."""
    n = len(lines)
    if n < 2:
        return lines
    w = measure(text, path, px, weight) / n
    while w < width:
        cand = wrap(text, path, px, w, lang, weight)
        if len(cand) <= n:
            return cand
        w += px * 0.5
    return lines


def stage_fonts(cfg, dst, text, langs):
    """Copy (Latin brand fonts) / subset (CJK) the fonts a project uses into ``dst`` (assets/fonts) ->
    {(lang, role): (css_family, filename)}."""
    os.makedirs(dst, exist_ok=True)
    out = {}
    from vstudio import render as R
    for lang in langs:
        for role, path in font_files(cfg, lang).items():
            fam = f"LK-{lang}-{role}"
            base = os.path.splitext(os.path.basename(path))[0]
            if lang == "zh" or path.lower().endswith((".otf", ".ttf", ".ttc")):
                name = R.subset_font(path, text, os.path.join(dst, f"{lang}-{role}-{base}.woff2"))
            else:
                name = os.path.join(dst, os.path.basename(path))
                if not os.path.exists(name) or os.path.getsize(name) != os.path.getsize(path):
                    shutil.copy2(path, name)
            out[(lang, role)] = (fam, os.path.basename(name))
    return out


def font_css(faces, url_prefix="assets/fonts/"):
    fmt = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype", ".ttf": "truetype"}
    rules = []
    for (lang, role), (fam, fn) in faces.items():
        f = fmt.get(os.path.splitext(fn)[1].lower(), "opentype")
        rules.append(f'@font-face {{ font-family: "{fam}"; src: url("{url_prefix}{fn}") format("{f}"); '
                     f'font-weight: 100 900; font-display: block; }}')
    return "\n".join(rules)


def families(faces, lang, role):
    """CSS font-family list for a role: the language's face first, then the other language's same role."""
    fams = [faces[(lang, role)][0]] if (lang, role) in faces else []
    fams += [fam for (lg, r), (fam, _) in faces.items() if r == role and lg != lang]
    return ", ".join(f'"{f}"' for f in fams) + (", serif" if role == "display" else ", sans-serif")
