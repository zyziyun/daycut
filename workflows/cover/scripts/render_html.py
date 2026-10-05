#!/usr/bin/env python3
"""Render an HTML page to PNG with headless Chrome/Chromium (portable lookup) or Playwright.

Before rendering it
  * copies the repo fonts (vstudio.config.FONT_DIR) into <html dir>/assets/fonts/ so templates can
    @font-face them by relative URL (no system fonts), and
  * injects persona brand colours as CSS variables (--accent, --highlight, --ink, --ground) into a
    sibling <name>.render.html (templates use var(--accent, <fallback>)). --no-persona skips that.

Usage:
  python3 render_html.py cover.html -o cover.png [--size 1080x1920] [--query export=01_title] [--wait 2000]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import os
import platform
import shutil
import subprocess

from vstudio.config import FONT_DIR, persona

CANDIDATES = {
    "Darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
               "/Applications/Chromium.app/Contents/MacOS/Chromium",
               "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
               "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"],
    "Windows": [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"],
}
NAMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"]


def find_chromes():
    """All plausible Chrome/Chromium binaries, $CHROME first (a broken one is skipped at render time)."""
    out = []
    env = os.environ.get("CHROME")
    if env and os.path.exists(env):
        out.append(env)
    out += [p for p in (shutil.which(n) for n in NAMES) if p]
    out += [p for p in CANDIDATES.get(platform.system(), []) if os.path.exists(p)]
    return list(dict.fromkeys(out))


def stage_fonts(html_dir: pathlib.Path):
    dst = html_dir / "assets" / "fonts"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    if os.path.isdir(FONT_DIR):
        for f in os.listdir(FONT_DIR):
            if f.lower().endswith((".otf", ".ttf", ".woff", ".woff2")) and not (dst / f).exists():
                shutil.copy2(os.path.join(FONT_DIR, f), dst / f); n += 1
    if not any(dst.iterdir()):
        print(f"  warning: no fonts in {FONT_DIR} (run ./install.sh); text will fall back to browser defaults")
    return n


def inject_persona(html: pathlib.Path) -> pathlib.Path:
    b = persona().get("brand", {}) or {}
    css = ":root{" + "".join(f"--{k}:{b[k]};" for k in ("accent", "highlight", "ink", "ground") if b.get(k)) + "}"
    txt = html.read_text(encoding="utf-8")
    tag = f'<style id="vstudio-persona">{css}</style>'
    txt = txt.replace("</head>", tag + "\n</head>", 1) if "</head>" in txt else tag + txt
    out = html.with_name(html.stem + ".render.html")
    out.write_text(txt, encoding="utf-8")
    return out


def render(html, png, w, h, query="", wait=2000, use_persona=True):
    html = pathlib.Path(html).resolve()
    stage_fonts(html.parent)
    page = inject_persona(html) if use_persona else html
    url = page.as_uri() + (f"?{query}" if query else "")
    png = pathlib.Path(png).resolve()
    png.parent.mkdir(parents=True, exist_ok=True)
    png.unlink(missing_ok=True)
    try:
        done = False
        for chrome in find_chromes():
            r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                "--force-device-scale-factor=1", f"--window-size={w},{h}",
                                f"--virtual-time-budget={wait}", f"--screenshot={png}", url], capture_output=True)
            if r.returncode == 0 and png.exists():
                done = True
                break
            print(f"  {chrome} failed (exit {r.returncode}); trying next")
        if not done:
            try:
                from playwright.sync_api import sync_playwright
            except ImportError:
                raise SystemExit("No Chrome/Chromium found (set $CHROME) and Playwright not installed "
                                 "(pip install playwright && playwright install chromium)")
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
                pg.goto(url); pg.wait_for_timeout(wait); pg.screenshot(path=str(png)); b.close()
    finally:
        if page != html:
            page.unlink(missing_ok=True)
    return png


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--size", default="1080x1920", help="WxH viewport (default 1080x1920)")
    ap.add_argument("--query", default="", help="URL query string, e.g. export=01_title")
    ap.add_argument("--wait", type=int, default=2000, help="virtual time budget ms for fonts/JS to settle")
    ap.add_argument("--no-persona", action="store_true", help="don't inject persona brand colours")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    print(render(a.html, a.out, w, h, a.query, a.wait, not a.no_persona))


if __name__ == "__main__":
    main()
