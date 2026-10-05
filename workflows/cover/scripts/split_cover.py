#!/usr/bin/env python3
"""Premium split cover: face photo left, dark panel right (quote, title, thumbnail, chips, stamps).

Driven by a JSON config (see ../examples/split_cover.example.json). Renders one or more sizes
(e.g. 4:3 for 小红书 horizontal posts, 16:9 for YouTube/B站) from the same config.

  python3 split_cover.py work/split_cover.json

Paths in the config are relative to the config file. Colours default to persona.brand
(ground / highlight / accent / ink); fonts come from vstudio.config.font().
Optional "retouch": {...} runs vstudio.retouch on the photo first (cached next to the photo as
*.retouched.png; "retouch_force": true redoes it). Layout itself is vstudio.cover.split_cover.
Per-output keys: path, size [W, H] or aspect ("4:3" | "16:9" | "3:4"), photo_w, photo_shift, quality,
  platform ("xiaohongshu:horizontal", "douyin", "youtube", ...: size = vstudio.platform.cover_size; portrait
  sizes (3:4 1080x1440, 9:16 1080x1920) use the stacked photo-over-panel layout),
  feed_safe (true/false; default true when the platform's feed shows a centre crop of a landscape cover, i.e.
  小红书 16:9 -> 4:3): the whole design is laid out inside the centre 4:3 and the photo is extended to the
  left edge, so nothing important is cut in the feed tile. A <path>.feed.jpg preview of the crop is written.
CLI --platforms a,b,c adds one output per platform (path <stem>.<platform>-<orientation>.jpg next to the config)
to the config's outputs.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))

import argparse
import json

from vstudio.cover import split_cover
from vstudio import platform as P

PER_OUTPUT = ("size", "aspect", "photo_w", "photo_shift", "quality")
TEXT_KEYS = ("quote", "title", "thumbnail", "chips", "stamp", "corner_tag")


def _crop_ratio(fc):
    aw, ah = (float(v) for v in fc.split(":")); return aw / ah


def feed_safe_cover(c, base, fc):
    """Landscape split cover whose design sits inside the centre feed crop (e.g. 4:3 of 16:9): the inner
    crop-size cover is pasted over a full-width render of the same photo (no text) whose photo band is
    widened by the margin, so the face lines up and the photo runs to the left edge."""
    W, H = c["size"]
    iw = int(round(H * _crop_ratio(fc) / 2)) * 2
    xo = (W - iw) // 2
    pw = int(c.get("photo_w") or 760 * H / 1080 * iw / 1440)
    inner = split_cover(dict(c, size=[iw, H], photo_w=pw), base=str(base))
    back = dict(c, size=[W, H], photo_w=pw + xo, photo_shift=c.get("photo_shift", 0))
    for k in TEXT_KEYS: back.pop(k, None)
    full = split_cover(back, base=str(base))
    full.paste(inner, (xo, 0))
    return full


def feed_preview(img, fc, path):
    W, H = img.size; r = _crop_ratio(fc)
    cw, ch = (H * r, H) if W / H > r else (W, W / r)
    x0, y0 = (W - cw) / 2, (H - ch) / 2
    p = path.with_name(path.stem + ".feed.jpg")
    img.crop((int(x0), int(y0), int(x0 + cw), int(y0 + ch))).save(p, quality=90)
    return p


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
    ap.add_argument("--platforms", help="comma list, e.g. xiaohongshu:horizontal,xiaohongshu,douyin,youtube")
    a = ap.parse_args()
    cfgp = pathlib.Path(a.config).resolve()
    cfg = json.loads(cfgp.read_text(encoding="utf-8"))
    base = cfgp.parent
    common = {k: v for k, v in cfg.items() if k not in ("outputs", "retouch", "retouch_force", "_comment")}
    common["photo"] = str(retouched_photo(cfg, base))
    outputs = list(cfg.get("outputs", [{"path": "cover-16x9.jpg", "size": [1920, 1080], "photo_w": 900}]))
    for sp in (a.platforms.split(",") if a.platforms else []):
        prof = P.profile(sp.strip())
        outputs.append({"path": f"{cfgp.stem}.{prof.name}-{prof.orientation}.jpg", "platform": prof.key})
    for out in outputs:
        c = dict(common)
        c.pop("size", None); c.pop("aspect", None)
        c.update({k: out[k] for k in PER_OUTPUT if k in out})
        fc = None
        if out.get("platform"):
            prof = P.profile(out["platform"])
            c["size"] = list(P.cover_size(prof)); c.pop("aspect", None)
            fc = prof.cover.get("feed_crop")
            if "photo_w" not in out:
                W_, H_ = c["size"]
                c["photo_w"] = int(W_ * 0.47) if W_ > H_ else int(H_ * (0.52 if H_ / W_ > 1.5 else 0.47))
        p = base / out["path"]; p.parent.mkdir(parents=True, exist_ok=True)
        W_, H_ = (c["size"] if c.get("size") else (0, 0))
        safe = out.get("feed_safe", bool(fc) and W_ > H_ and W_ / H_ > _crop_ratio(fc) + 0.01)
        if safe:
            img = feed_safe_cover(c, base, fc); img.save(p, quality=int(c.get("quality", 94)))
        else:
            img = split_cover(c, out=str(p), base=str(base))
        mb = out.get("max_bytes") or (prof.cover.get("max_bytes") if out.get("platform") else None)
        q = int(c.get("quality", 94))
        while mb and p.stat().st_size > mb and q > 60:
            q -= 8; img.save(p, quality=q)
        extra = f"  feed {fc} preview {feed_preview(img, fc, p).name}" if fc else ""
        print("wrote", p, f"{img.width}x{img.height}" + (" (feed-safe layout)" if safe else "") + extra)


if __name__ == "__main__":
    main()
