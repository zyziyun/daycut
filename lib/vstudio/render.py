"""HTML -> PNG with headless Chrome/Chromium (portable lookup) or Playwright, plus font staging/subsetting
and persona CSS variables for HTML / HyperFrames projects.

    from vstudio.render import find_chrome, html_to_png, stage_fonts, subset_font, persona_css
    html_to_png("cover.html", "cover.png", size=(1080, 1920))        # path or an HTML string
    stage_fonts("project/assets/fonts", ["cjk", "cjk-bold"])          # copies from config.FONT_DIR
    subset_font(font("cjk-bold"), "用到的字", "assets/fonts/cjk-700.woff2")   # .otf if brotli is missing
    persona_css()  -> ':root{--accent:..;--highlight:..;--ink:..;--t-paper:..;--t-ink:..;...}' (brand + theme tokens)

CLI:  python -m vstudio.render page.html -o out.png [--size 1080x1920] [--scale 1] [--wait 2000]
"""
import argparse
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile

from .config import FONT_DIR, FONTS, MissingAsset, font, persona

CHROME_PATHS = {
    "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Chromium.app/Contents/MacOS/Chromium",
               "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    "Linux": ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
              "/usr/bin/chromium-browser", "/snap/bin/chromium", "/opt/google/chrome/chrome"],
    "Windows": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
}
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"]
_OK = {}


def _works(path, timeout=15):
    """A binary counts only if `--version` exits 0 (a broken/quarantined chromium returned 126 here)."""
    if path not in _OK:
        try:
            r = subprocess.run([path, "--version"], capture_output=True, timeout=timeout)
            _OK[path] = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _OK[path] = False
    return _OK[path]


def chrome_candidates():
    """Every plausible binary, $CHROME first, then PATH names, then per-OS install paths (unverified)."""
    out = []
    env = os.environ.get("CHROME")
    if env and os.path.exists(env):
        out.append(env)
    out += [p for p in (shutil.which(n) for n in CHROME_NAMES) if p]
    out += [p for p in CHROME_PATHS.get(platform.system(), []) if os.path.exists(p)]
    return list(dict.fromkeys(out))


def find_chromes():
    return [p for p in chrome_candidates() if _works(p)]


def find_chrome():
    """First working Chrome/Chromium/Edge path, or None. Never raises."""
    try:
        for p in chrome_candidates():
            if _works(p):
                return p
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------- CSS / fonts
def persona_css(extra: dict = None) -> str:
    """':root{--accent:..;--highlight:..;--ink:..;--ground:..;...}' from persona.brand (+ extra vars)."""
    from .draw import brand
    from .theme import css_vars
    b = dict(persona().get("brand") or {})
    br = brand()
    b.update(accent="#%02X%02X%02X" % br["accent"], highlight="#%02X%02X%02X" % br["highlight"])
    b.update(extra or {})
    vars_ = "".join(f"--{k.replace('_', '-')}:{v};" for k, v in b.items()
                    if isinstance(v, str) and v.startswith("#"))
    theme_vars = css_vars()[len(":root{"):-1].replace("--", "--t-")         # theme tokens: --t-paper, --t-ink ...
    return ":root{" + vars_ + theme_vars + "}"


def inject_css(html: str, css: str, style_id="vstudio-persona") -> str:
    tag = f'<style id="{style_id}">{css}</style>'
    return html.replace("</head>", tag + "\n</head>", 1) if "</head>" in html else tag + html


def _role_files(roles):
    out = {}
    for role in roles:
        try:
            out[role] = font(role)
        except MissingAsset:
            print(f"  warning: font role '{role}' missing (run ./install.sh)")
    return out


def stage_fonts(dst_dir, roles=None):
    """Copy font files for `roles` (default: every installed role) into dst_dir.
    Returns {role: filename}. Persona font overrides are honoured (via config.font)."""
    dst = pathlib.Path(dst_dir); dst.mkdir(parents=True, exist_ok=True)
    roles = list(roles) if roles else list(FONTS)
    staged = {}
    for role, src in _role_files(roles).items():
        name = os.path.basename(src)
        if not (dst / name).exists() or os.path.getsize(dst / name) != os.path.getsize(src):
            shutil.copy2(src, dst / name)
        staged[role] = name
    if not staged:
        print(f"  warning: no fonts staged from {FONT_DIR}; text will fall back to browser defaults")
    return staged


def font_face_css(faces: dict, url_prefix="assets/fonts/") -> str:
    """@font-face rules. faces: {family: filename} or {family: (filename, weight, style)}."""
    fmt = {".woff2": "woff2", ".woff": "woff", ".otf": "opentype", ".ttf": "truetype"}
    rules = []
    for fam, v in faces.items():
        fn, weight, style = (v, 400, "normal") if isinstance(v, str) else (list(v) + [400, "normal"])[:3]
        f = fmt.get(os.path.splitext(fn)[1].lower(), "opentype")
        rules.append(f'@font-face {{ font-family: "{fam}"; src: url("{url_prefix}{fn}") format("{f}"); '
                     f'font-weight: {weight}; font-style: {style}; font-display: block; }}')
    return "\n".join(rules)


BASE_CHARS = "".join(chr(i) for i in range(32, 127)) + "−×÷≈≤≥→←·…—–“”‘’（）【】「」《》：；，。、？！％·↓↑"


def subset_font(src, chars, dst, face_name=None):
    """Subset `src` (.otf/.ttf/.ttc) to `chars` (+ ASCII and common punctuation).
    dst *.woff2 is written as woff2 when brotli is installed, else as the source format (extension changed).
    Returns the path actually written."""
    from fontTools import subset
    from fontTools.ttLib import TTCollection
    src = str(src); dst = pathlib.Path(dst); dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    if src.lower().endswith(".ttc"):
        col = TTCollection(src)
        face = next((f for f in col.fonts if not face_name or f["name"].getDebugName(4) == face_name), col.fonts[0])
        tmp = tempfile.NamedTemporaryFile(suffix=".ttf", delete=False).name; face.save(tmp); src = tmp
    flavor = None
    if dst.suffix.lower() in (".woff2", ".woff"):
        try:
            if dst.suffix.lower() == ".woff2":
                import brotli  # noqa: F401
            flavor = dst.suffix.lower()[1:]
        except ImportError:
            ext = os.path.splitext(src)[1].lower() if os.path.splitext(src)[1].lower() in (".otf", ".ttf") else ".otf"
            print(f"  brotli not installed -> writing {ext} instead of woff2 (pip install brotli)")
            dst = dst.with_suffix(ext)
    o = subset.Options(); o.flavor = flavor; o.layout_features = ["*"]; o.name_IDs = ["*"]; o.notdef_outline = True
    ft = subset.load_font(src, o)
    ss = subset.Subsetter(o); ss.populate(text="".join(sorted(set(str(chars) + BASE_CHARS)))); ss.subset(ft)
    subset.save_font(ft, str(dst), o)
    if tmp:
        os.unlink(tmp)
    return str(dst)


def subset_project_fonts(out_dir, text, roles=(("cjk", "cjk-400"), ("cjk-bold", "cjk-700"),
                                                ("serif", "serif"), ("serif-italic", "serif-italic"))):
    """Subset several roles for an HTML project -> {name: path}. Missing roles are skipped."""
    out = {}
    for role, name in roles:
        try:
            out[name] = subset_font(font(role), text, os.path.join(out_dir, name + ".woff2"))
        except MissingAsset as e:
            print("  skip:", e)
    return out


# ---------------------------------------------------------------- render
def html_to_png(html, out, size=(1080, 1920), scale=1, wait=2000, query="", use_persona=True,
                fonts=True, transparent=False, extra_css=None):
    """Render an HTML file path or HTML string to PNG. Fonts are staged into <html dir>/assets/fonts/
    and persona colours injected as CSS variables (into a temp sibling copy, the source is untouched).
    extra_css: a CSS string, or a dict of :root variables ({"accent": "#..."} -> --accent), injected
    after the persona block (so it wins) without writing a second copy.
    Tries each working Chrome, then Playwright. Returns the output path."""
    w, h = (int(v) for v in size)
    tmpdir = None
    if isinstance(html, str) and not os.path.exists(html) and "<" in html:
        tmpdir = tempfile.mkdtemp(prefix="vstudio_html_")
        src = pathlib.Path(tmpdir) / "page.html"; src.write_text(html, encoding="utf-8")
    else:
        src = pathlib.Path(html).resolve()
    if fonts:
        stage_fonts(src.parent / "assets" / "fonts")
    page = src
    if isinstance(extra_css, dict):
        extra_css = ":root{" + "".join(f"--{str(k).replace('_', '-')}:{v};" for k, v in extra_css.items()) + "}"
    if use_persona or extra_css:
        page = src.with_name(src.stem + ".render.html")
        txt = src.read_text(encoding="utf-8")
        if use_persona:
            txt = inject_css(txt, persona_css())
        if extra_css:
            txt = inject_css(txt, extra_css, style_id="vstudio-extra")
        page.write_text(txt, encoding="utf-8")
    url = page.as_uri() + (f"?{query}" if query else "")
    png = pathlib.Path(out).resolve(); png.parent.mkdir(parents=True, exist_ok=True); png.unlink(missing_ok=True)
    try:
        for chrome in find_chromes():
            args = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--force-device-scale-factor={scale}",
                    f"--window-size={w},{h}", f"--virtual-time-budget={wait}", f"--screenshot={png}"]
            if transparent:
                args.append("--default-background-color=00000000")
            try:
                r = subprocess.run(args + [url], capture_output=True, timeout=120)
            except subprocess.TimeoutExpired:
                print(f"  {chrome} timed out; trying next"); continue
            if png.exists() and (r.returncode == 0 or b"bytes written to file" in (r.stderr or b"")):
                return str(png)          # macOS Chrome can exit 2 on a teardown watchdog after writing the file
            print(f"  {chrome} failed (exit {r.returncode}); trying next")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError("No working Chrome/Chromium (set $CHROME) and Playwright not installed "
                               "(pip install playwright && playwright install chromium)")
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
            pg.goto(url); pg.wait_for_timeout(wait)
            pg.screenshot(path=str(png), omit_background=transparent); b.close()
        return str(png)
    finally:
        if page != src:
            page.unlink(missing_ok=True)
        if tmpdir:
            shutil.rmtree(tmpdir, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description="Render HTML to PNG (headless Chrome, Playwright fallback).")
    ap.add_argument("html"); ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--size", default="1080x1920"); ap.add_argument("--scale", type=float, default=1)
    ap.add_argument("--wait", type=int, default=2000); ap.add_argument("--query", default="")
    ap.add_argument("--no-persona", action="store_true"); ap.add_argument("--transparent", action="store_true")
    a = ap.parse_args()
    print(html_to_png(a.html, a.out, tuple(int(v) for v in a.size.lower().split("x")), a.scale, a.wait, a.query,
                      not a.no_persona, transparent=a.transparent))


if __name__ == "__main__":
    main()
