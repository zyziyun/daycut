#!/usr/bin/env python3
"""Premium split cover from the project config: retouched speaker on one side, dark panel with a quote,
a two-line title with one highlighted term, a framed thumbnail of the highlights video, outline chips,
a rotated red tag and a "记笔记" note tag. Landscape sizes use the side-by-side split; portrait sizes
(e.g. 3:4) stack the photo over the panel.

  python3 $VSTUDIO/workflows/promo-recut/scripts/make_cover.py promo.config.json [--no-retouch]

Layout + retouch are vstudio.cover.split_cover (face-centred crop, vstudio.retouch: face slim, eye,
de-shine, skin, light makeup, optional body slim). This script only maps the project config onto it.
"""
import sys, pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
import argparse
import os

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import Project  # noqa: E402
from vstudio import cover, media  # noqa: E402
from PIL import Image  # noqa: E402

RETOUCH_DEFAULT = {"slim": 0.05, "eye": 0.04, "makeup": 0.5, "body": 0.07}


def get_photo(prj, cv):
    ph = cv.get("photo") or {}
    if ph.get("image"):
        return prj.p(ph["image"])
    talk = prj.w("raw_graded.mp4") if os.path.exists(prj.w("raw_graded.mp4")) else prj.p(prj.cfg["talk"])
    media.grab_frame(talk, ph.get("talk_at", 1.0), prj.w("cover_frame.png"))
    return prj.w("cover_frame.png")


def get_thumb(prj, cv):
    th = cv.get("thumb") or {}
    if th.get("image"):
        im = Image.open(prj.p(th["image"])).convert("RGB")
    elif prj.cfg.get("highlights") and th.get("highlights_at") is not None:
        out = prj.w("cover_thumb.png")
        media.grab_frame(prj.p(prj.cfg["highlights"]), th["highlights_at"], out)
        im = Image.open(out).convert("RGB")
    else:
        return None
    return im.crop(tuple(th["crop"])) if th.get("crop") else im      # crop in image pixels (find_rows.py)


def split_cfg(cv, photo, thumb, no_retouch):
    rt = cv.get("retouch", {})
    retouch = None if (rt is False or no_retouch) else dict(RETOUCH_DEFAULT, **(rt or {}))
    out = {"photo": photo, "retouch": retouch, "face_x": "auto", "photo_lift": cv.get("brighten", 1.03),
           "title": {"lines": cv.get("title", []), "highlight": [cv["title_highlight"]] if cv.get("title_highlight") else []},
           "chips": cv.get("chips", [])}
    if cv.get("quote"):
        out["quote"] = {"text": cv["quote"], "by": cv.get("attribution")}
    if thumb is not None:
        out["thumbnail"] = thumb
    if cv.get("tag"):
        out["stamp"] = {"text": cv["tag"], "rotate": 8}
    if cv.get("note"):
        out["corner_tag"] = {"text": cv["note"]}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("config")
    ap.add_argument("--no-retouch", action="store_true")
    a = ap.parse_args()
    prj = Project(a.config)
    cv = prj.cfg.get("cover") or {}
    base = split_cfg(cv, get_photo(prj, cv), get_thumb(prj, cv), a.no_retouch)
    sizes = cv.get("sizes") or [{"w": 1440, "h": 1080, "photo_w": 760, "out": "cover-4x3.jpg"},
                                {"w": 1920, "h": 1080, "photo_w": 900, "out": "cover-16x9.jpg"}]
    for s in sizes:
        cfg = dict(base, size=(s["w"], s["h"]), photo_w=s.get("photo_w", int(s["w"] * 0.5)))
        cover.split_cover(cfg, out=prj.p(s["out"]))
        print("cover ->", prj.p(s["out"]))


if __name__ == "__main__":
    main()
