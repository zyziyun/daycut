#!/usr/bin/env python3
"""Batch-render every slide of a single-file slide deck to PNG.

Slides are <section class="slide" data-key="..."> blocks selected with ?export=<key>. Keys are
discovered from the HTML unless given. Output: <out>/slide_<key>.png at --size (default 1080x1080).

  python3 render_slides.py work/slides.html work/slides/ [01_title 06_bars ...] [--size 1080x1080]
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import re

from vstudio.render import html_to_png


def keys_of(html):
    return re.findall(r'<section[^>]*class="[^"]*\bslide\b[^"]*"[^>]*data-key="([^"]+)"', pathlib.Path(html).read_text(encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html"); ap.add_argument("out")
    ap.add_argument("keys", nargs="*", help="slide keys (default: all data-key values in the HTML)")
    ap.add_argument("--size", default="1080x1080")
    ap.add_argument("--wait", type=int, default=1500, help="virtual time budget ms (lets JS diagrams settle)")
    ap.add_argument("--no-persona", action="store_true")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.lower().split("x"))
    keys = a.keys or keys_of(a.html)
    if not keys:
        raise SystemExit("no data-key slides found")
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for k in keys:
        html_to_png(a.html, out / f"slide_{k}.png", size=(w, h), wait=a.wait, query=f"export={k}",
                    use_persona=not a.no_persona)
        print(f"  slide_{k}.png")


if __name__ == "__main__":
    main()
