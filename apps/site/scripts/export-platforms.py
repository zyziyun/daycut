#!/usr/bin/env python3
"""Export the engine's platform profiles (lib/vstudio/platform.py) to src/data/platforms.json for the
/platforms/ spec page. Run from apps/site after the profiles change:  python3 scripts/export-platforms.py
The JSON is committed, so `npm run build` never needs Python."""
import json, pathlib, sys
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "lib"))
from vstudio import platform as P  # noqa: E402

out = []
for name in P.ORDER:
    d = P.PLATFORMS[name]
    orients = []
    for o, v in d["orientations"].items():
        c = v.get("cover") or {}
        orients.append(dict(name=o, w=v["w"], h=v["h"], aspect=v["aspect"],
                            cover=dict(w=c.get("w"), h=c.get("h"), aspect=c.get("aspect")) if c else None))
    # the default orientation first
    orients.sort(key=lambda x: x["name"] != d.get("default"))
    ln = d.get("length", {})
    out.append(dict(
        id=name, group=d.get("group"), label=d.get("label"),
        orientations=orients,
        length=dict(min=ln.get("min"), max=ln.get("max"), sweet=ln.get("sweet")),
        titleMax=d.get("title_max") or None, descMax=d.get("desc_max"),
        hashtagsMax=(d.get("hashtags") or {}).get("max"),
        linksClickable=bool((d.get("links") or {}).get("clickable")),
        chapters=bool((d.get("chapters") or {}).get("supported")),
        lufs=(d.get("loudness") or {}).get("lufs"),
    ))
dest = pathlib.Path(__file__).resolve().parents[1] / "src/data/platforms.json"
dest.write_text(json.dumps(dict(checked="2026-10-06", source="lib/vstudio/platform.py", platforms=out), ensure_ascii=False, indent=1) + "\n")
print(f"wrote {dest} ({len(out)} platforms)")
