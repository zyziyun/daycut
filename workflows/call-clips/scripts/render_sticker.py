#!/usr/bin/env python3
"""Rasterise a sticker / avatar HTML (assets/*_sticker.html, cat_avatar.html) to PNG
with a transparent background (vstudio.render.html_to_png: the first working
Chrome/Chromium/Edge, $CHROME first, else Playwright).

The bundled PNGs were produced this way from the HTML next to them; re-run after
editing the SVG, then re-derive --scale / --y-offset with verify_coverage.py if the
head ellipse moved.

Usage:
  render_sticker.py assets/cat_sticker.html --out assets/cat.png [--size 512x512]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse

from vstudio.render import html_to_png


def main():
    ap = argparse.ArgumentParser(description="HTML sticker -> transparent PNG")
    ap.add_argument("html")
    ap.add_argument("--out", required=True)
    ap.add_argument("--size", default="512x512", help="WxH (avatar: 960x540)")
    args = ap.parse_args()
    w, h = (int(v) for v in args.size.lower().split("x"))
    # the stickers are self-contained SVG: no persona CSS, no fonts staged next to the asset
    html_to_png(args.html, args.out, size=(w, h), use_persona=False, fonts=False, transparent=True)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
