#!/usr/bin/env python3
"""Batch-render every slide of a single-file slide deck to PNG.

Slides are <section class="slide" data-key="..."> blocks selected with ?export=<key>. Keys are
discovered from the HTML unless given. Output: <out>/slide_<key>.png, 1080x1080 by default.

  python3 render_slides.py work/slides.html work/slides/ [01_title 06_bars ...]
      [--platform xiaohongshu:vertical] [--layout split|full] [--accent "#2dd4bf"] [--size WxH]

Accent: persona slides.accent (default teal), not brand.accent. --layout split (default) = square
(side = min of the platform canvas); --layout full = platform canvas with content inside its safe zones.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import re

from vstudio.render import html_to_png
from slide_frame import add_args, frame, write_page


def keys_of(html):
    text = re.sub(r"<!--.*?-->", "", pathlib.Path(html).read_text(encoding="utf-8"), flags=re.S)  # skip commented examples
    return re.findall(r'<section[^>]*class="[^"]*\bslide\b[^"]*"[^>]*data-key="([^"]+)"', text)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html"); ap.add_argument("out")
    ap.add_argument("keys", nargs="*", help="slide keys (default: all data-key values in the HTML)")
    ap.add_argument("--wait", type=int, default=1500, help="virtual time budget ms (lets JS diagrams settle)")
    add_args(ap)
    a = ap.parse_args()
    w, h, vars_ = frame(a)
    keys = a.keys or keys_of(a.html)
    if not keys:
        raise SystemExit("no data-key slides found")
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    page = write_page(a.html, vars_)
    try:
        for k in keys:
            html_to_png(str(page), out / f"slide_{k}.png", size=(w, h), wait=a.wait, query=f"export={k}",
                        use_persona=not a.no_persona)
            print(f"  slide_{k}.png  {w}x{h}")
    finally:
        page.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
