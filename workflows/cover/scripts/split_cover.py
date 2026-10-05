#!/usr/bin/env python3
"""Premium split cover: face photo left, dark panel right (quote, title, thumbnail, chips, stamps).

Driven by a JSON config (see ../examples/split_cover.example.json). Renders one or more sizes
(e.g. 4:3 for 小红书 horizontal posts, 16:9 for YouTube/B站) from the same config.

  python3 split_cover.py work/split_cover.json

Paths in the config are relative to the config file. Colours default to persona.brand
(ground / highlight / accent / ink); fonts come from vstudio.config.font().
Optional "retouch": {...} runs vstudio.retouch on the photo first (cached next to the photo as
*.retouched.png; "retouch_force": true redoes it). Layout itself is vstudio.cover.split_cover.
Per-output keys: path, size [W, H] or aspect ("4:3" | "16:9" | "3:4"), photo_w, photo_shift, quality.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import json

from vstudio.cover import split_cover

PER_OUTPUT = ("size", "aspect", "photo_w", "photo_shift", "quality")


def retouched_photo(cfg, base):
    """Path of the photo to use: the original, or a cached retouched copy when cfg["retouch"] is set."""
    src = base / cfg["photo"]
    rt = cfg.get("retouch")
    if not rt:
        return src
    cached = src.with_name(src.stem + ".retouched.png")
    if not cached.exists() or cfg.get("retouch_force"):
        import cv2
        from vstudio import face as FA
        from vstudio.retouch import retouch
        img = cv2.imread(str(src))
        cv2.imwrite(str(cached), retouch(img, lm=FA.landmarker(1), **(rt if isinstance(rt, dict) else {})))
        print("retouched ->", cached)
    return cached


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config", help="split cover JSON")
    a = ap.parse_args()
    cfgp = pathlib.Path(a.config).resolve()
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    base = cfgp.parent
    common = {k: v for k, v in cfg.items() if k not in ("outputs", "retouch", "retouch_force", "_comment")}
    common["photo"] = str(retouched_photo(cfg, base))
    for out in cfg.get("outputs", [{"path": "cover-16x9.jpg", "size": [1920, 1080], "photo_w": 900}]):
        c = dict(common)
        c.pop("size", None); c.pop("aspect", None)
        c.update({k: out[k] for k in PER_OUTPUT if k in out})
        p = base / out["path"]; p.parent.mkdir(parents=True, exist_ok=True)
        img = split_cover(c, out=str(p), base=str(base))
        print("wrote", p, f"{img.width}x{img.height}")


if __name__ == "__main__":
    main()
