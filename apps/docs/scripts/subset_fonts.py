#!/usr/bin/env python3
"""Subset the display fonts (both SIL OFL 1.1) so headings cost ~50 KB instead of ~10 MB.

    python3 apps/docs/scripts/subset_fonts.py

1. Newsreader (the site's display serif), from @fontsource-variable/newsreader: weight pinned to 400, optical sizes
   16-72 kept, Latin only -> src/assets/fonts/newsreader-{normal,italic}.woff2 (~50 KB each, vs ~140 KB).
2. Noto Serif SC, to the glyphs the Chinese docs use in serif display text:

Collects every character of the zh page titles, headings, card titles and sidebar group labels, and writes
src/assets/fonts/noto-serif-sc-sub.woff2 (~tens of KB instead of ~10 MB). Re-run after adding Chinese pages
(`npm run gen` does both generators). Needs fontTools + brotli (`pip install fonttools brotli`).

Source font: NotoSerifSC-Bold.otf from the engine's font cache (install.sh downloads it into
~/.cache/video-studio/fonts), or a path in $NOTO_SERIF_SC.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1]
ZH = DOCS / "src" / "content" / "docs" / "zh"
OUT = DOCS / "src" / "assets" / "fonts" / "noto-serif-sc-sub.woff2"
CACHE = Path(os.environ.get("VSTUDIO_CACHE", Path.home() / ".cache" / "video-studio")) / "fonts"


def collect() -> str:
    chars: set[str] = set()
    for f in ZH.rglob("*.md*"):
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^\s*(?:title|label|text):\s*(.+)$", text, re.M):
            chars.update(m.group(1))
        for m in re.finditer(r"^#{1,4}\s+(.+)$", text, re.M):
            chars.update(m.group(1))
        for m in re.finditer(r'title="([^"]+)"', text):
            chars.update(m.group(1))
    sidebar = (DOCS / "src" / "sidebar.mjs").read_text(encoding="utf-8")
    chars.update(re.sub(r"[\x00-\x7f]", "", sidebar))
    chars.update("千剪文档参考一条素材，千条成片。使用")
    chars.update(chr(c) for c in range(0x20, 0x7F))
    chars.update("，。：；、！？「」『』（）《》—…·")
    return "".join(sorted(chars))


NEWSREADER = DOCS.parents[1] / "node_modules" / "@fontsource-variable" / "newsreader" / "files"
LATIN = "U+0020-007E,U+00A0-00FF,U+0131,U+0152-0153,U+2010-2027,U+2030-203A,U+2122,U+2190-2193,U+2212"


def newsreader() -> None:
    from fontTools import subset
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    for style in ("normal", "italic"):
        font = TTFont(str(NEWSREADER / f"newsreader-latin-opsz-{style}.woff2"))
        font = instancer.instantiateVariableFont(font, {"wght": 400, "opsz": (16, 72)})
        opts = subset.Options()
        opts.flavor = "woff2"
        opts.layout_features = ["kern", "liga", "calt", "onum", "lnum", "tnum", "pnum"]
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=subset.parse_unicodes(LATIN))
        sub.subset(font)
        out = OUT.parent / f"newsreader-{style}.woff2"
        subset.save_font(font, str(out), opts)
        print(f"wrote {out.relative_to(DOCS)}: {out.stat().st_size // 1024} KB")


def main() -> None:
    from fontTools import subset

    newsreader()

    src = Path(os.environ.get("NOTO_SERIF_SC", CACHE / "NotoSerifSC-Bold.otf"))
    if not src.exists():
        sys.exit(f"missing {src}: run the engine's install.sh, or set NOTO_SERIF_SC=/path/to/NotoSerifSC-Bold.otf")
    text = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga", "palt", "vert"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    font = subset.load_font(str(src), opts)
    sub = subset.Subsetter(opts)
    sub.populate(text=text)
    sub.subset(font)
    subset.save_font(font, str(OUT), opts)
    print(f"wrote {OUT.relative_to(DOCS)}: {len(text)} chars, {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
