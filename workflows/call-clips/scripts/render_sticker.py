#!/usr/bin/env python3
"""Rasterise a sticker / avatar HTML (assets/*_sticker.html, cat_avatar.html) to PNG
with a transparent background, using headless Chrome/Chromium or Playwright.

The bundled PNGs were produced this way from the HTML next to them; re-run after
editing the SVG, then re-derive --scale / --y-offset with verify_coverage.py if the
head ellipse moved.

Usage:
  render_sticker.py assets/cat_sticker.html --out assets/cat.png [--size 512x512]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse, os, shutil, subprocess, tempfile

CANDIDATES = [
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def find_chrome():
    for c in CANDIDATES:
        p = shutil.which(c) or (c if os.path.exists(c) else None)
        if p:
            return p
    return None


def main():
    ap = argparse.ArgumentParser(description="HTML sticker -> transparent PNG")
    ap.add_argument("html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="512x512", help="WxH (avatar: 960x540)")
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.lower().split("x"))
    url = pathlib.Path(args.html).resolve().as_uri()

    chrome = find_chrome()
    if chrome:
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "shot.png")
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--window-size={w},{h}", "--default-background-color=00000000",
                            f"--screenshot={shot}", url], check=True, capture_output=True)
            shutil.move(shot, args.out)
    else:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            sys.exit("need Chrome/Chromium on PATH or `pip install playwright && playwright install chromium`")
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": w, "height": h})
            pg.goto(url)
            pg.screenshot(path=args.out, omit_background=True)
            b.close()
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
