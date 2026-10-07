"""Formats = presets that seed a series (formats/*.yaml, data not code).

    load_all() -> [format dict]    get(fid)    label(fmt, lang)    public(fmt, lang=None)
"""
import glob
import os

import yaml

from .i18n import CreateError

HERE = os.path.dirname(os.path.abspath(__file__))
FORMAT_DIR = os.path.join(HERE, "formats")
LANGS = ("en", "zh", "fr")
IDS = ("series-ad", "product-spot", "interview", "talk-show", "sketch", "record")
REQUIRED = ("id", "labels", "blurb", "recipe", "aspect", "length_s", "beats", "cast_slots", "sources", "rules")
SOURCE_KEYS = ("faces", "no_faces", "drafts", "stills")

_cache = {}


def validate(f):
    miss = [k for k in REQUIRED if k not in f]
    if miss:
        raise ValueError(f"format {f.get('id')}: missing {miss}")
    if f["recipe"] not in ("ai-video", "talkinghead"):
        raise ValueError(f"format {f['id']}: recipe must be ai-video | talkinghead")
    for k in ("labels", "blurb"):
        if "en" not in f[k]:
            raise ValueError(f"format {f['id']}: {k}.en is required")
    lo, hi = f["length_s"]
    if not (0 < lo <= hi <= 600):
        raise ValueError(f"format {f['id']}: length_s")
    for b in f["beats"]:
        if not b.get("id") or "en" not in (b.get("labels") or {}):
            raise ValueError(f"format {f['id']}: every beat needs id + labels.en")
    for c in f["cast_slots"]:
        if not c.get("id"):
            raise ValueError(f"format {f['id']}: cast slot without id")
    if set(f["sources"]) - set(SOURCE_KEYS):
        raise ValueError(f"format {f['id']}: sources keys {SOURCE_KEYS}")
    return f


def load_all():
    if not _cache:
        rows = []
        for p in sorted(glob.glob(os.path.join(FORMAT_DIR, "*.yaml"))):
            with open(p, encoding="utf-8") as fh:
                rows.append(validate(yaml.safe_load(fh) or {}))
        rows.sort(key=lambda f: f.get("order", 99))
        _cache["all"] = rows
    return [dict(f) for f in _cache["all"]]


def get(fid):
    for f in load_all():
        if f["id"] == fid:
            return f
    raise CreateError("not-found", status=404, what="format", id=fid)


def text(d, lang="en"):
    """A {en, zh, fr} dict -> the string for ``lang`` (zh-CN = zh), falling back to English."""
    if isinstance(d, str):
        return d
    d = d or {}
    lang = "zh" if str(lang).startswith("zh") else str(lang)[:2]
    return d.get(lang) or d.get("en") or next(iter(d.values()), "")


def label(fmt, lang="en"):
    return text(fmt.get("labels"), lang)


def public(fmt, lang=None):
    """The JSON the desk renders (all languages unless ``lang``)."""
    keep = ("id", "order", "icon", "labels", "blurb", "recipe", "aspect", "length_s", "episodes", "engine", "beats",
            "cast_slots", "sources", "rules")
    out = {k: fmt.get(k) for k in keep}
    if lang:
        out["label"] = label(fmt, lang)
    return out


def expand_beats(fmt, lang="en"):
    """Beat template with repeats unrolled: [{id, label, n?}] (e.g. Slogan x3 -> 2 Slogan, 3 Slogan, 4 Slogan)."""
    out = []
    for b in fmt["beats"]:
        n = int(b.get("repeat") or 1)
        for i in range(n):
            out.append(dict(id=b["id"] if n == 1 else f"{b['id']}-{i + 1}", label=text(b["labels"], lang),
                            n=(i + 1) if n > 1 else None))
    return out
