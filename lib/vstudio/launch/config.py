"""launch.config.yaml: one file describes the product, the brand, the release, the shots and what to make.

    from vstudio.launch import config as C
    cfg = C.load("launch.config.yaml")      # validated, defaults filled, paths absolute (relative to the file)
    C.text(cfg["product"]["one_liner"], "zh")
    C.renders(cfg, "demo")                  # [("en", "16:9"), ("en", "9:16"), ...]

Annotated example: workflows/launch-kit/examples/launch.config.example.yaml. Any text field is either a plain
string or a per-language mapping ``{en: ..., zh: ...}``; ``【term】`` marks the word the caption highlights.
Errors are collected and raised together (ConfigError) so the creator fixes the file once.
"""
import copy
import json
import os
import re

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
LANGS = ("en", "zh")
# which platform profiles a canvas is posted to (the layout keeps clear of all of their UI); international first
CANVAS_PLATFORMS = {"16:9": ["x", "linkedin", "youtube", "bilibili"],
                    "9:16": ["tiktok", "youtube-shorts", "instagram", "xiaohongshu:full", "douyin"],
                    "1:1": ["x:square", "linkedin:square"]}
DEFAULT_PLATFORMS = ["x", "linkedin", "youtube", "youtube-shorts", "tiktok", "instagram", "xiaohongshu", "bilibili",
                     "douyin"]

DEFAULTS = {
    "languages": ["en"],
    "platforms": DEFAULT_PLATFORMS,
    "brand": {"theme": "editorial", "colors": {}, "fonts": {}},
    "demo": {"shots": None, "min_seconds": 30, "max_seconds": 60, "title_seconds": 2.6, "end_seconds": 3.2,
             "renders": None},
    "loop": {"shots": None, "seconds": 15, "width": 960, "gif_fps": 15},
    "clips": {"shots": None, "min_seconds": 10, "max_seconds": 20, "end_seconds": 2.4, "renders": None},
    "voiceover": {"enabled": False, "engine": "auto", "voice": None},
    "music": None,
    "gallery": {"shots": None, "lang": "en"},
    "schedule": {"start": None, "slots": {}, "accounts": {}},
    "post": None,
}


class ConfigError(ValueError):
    pass


def text(v, lang="en", fallback=True):
    """A text field -> the string for ``lang`` (str fields are language-neutral)."""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        if v.get(lang):
            return str(v[lang])
        if fallback:
            for k in ("en",) + tuple(v):
                if v.get(k):
                    return str(v[k])
    return ""


def plain(s):
    return re.sub(r"[【】]", "", s or "")


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _abs(root, p):
    if not p:
        return p
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(root, p))


def load_shots(cfg):
    """capture.shots (shots.json written by scripts/capture.mjs) + capture.images (screenshots) ->
    {id: {id, kind video|image, file, still, w, h, duration, focus [{t, x, y, w, h, kind}], caption, title}}."""
    cap = cfg.get("capture") or {}
    out = {}
    sj = cap.get("shots")
    if sj:
        with open(sj, encoding="utf-8") as f:
            d = json.load(f)
        base = os.path.dirname(sj)
        for s in d.get("shots") or []:
            out[s["id"]] = dict(s, kind="video", file=_abs(base, s["file"]), still=_abs(base, s.get("still")),
                                focus=list(s.get("focus") or []))
    for im in cap.get("images") or []:
        im = dict(im)
        im["file"] = im["file"]
        out[im["id"]] = dict(id=im["id"], kind="image", file=im["file"], still=im["file"], w=im.get("w"),
                             h=im.get("h"), duration=float(im.get("duration", 6.0)), title=im.get("title"),
                             caption=im.get("caption"),
                             focus=[dict(dict(t=1.2, kind="focus"), **f) for f in im.get("focus") or []])
    return out


def load(path, overrides=None):
    import yaml
    path = os.path.abspath(path)
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = _merge(DEFAULTS, raw)
    if overrides:
        cfg = _merge(cfg, overrides)
    root = os.path.dirname(path)
    cfg["_path"], cfg["_root"] = path, root
    cfg["out"] = _abs(root, cfg.get("out") or "kit")
    b = cfg["brand"]
    for k in ("logo", "logo_dark", "mark"):
        b[k] = _abs(root, b.get(k))
    b["fonts"] = {k: _abs(root, v) for k, v in (b.get("fonts") or {}).items()}
    rel = cfg.get("release") or {}
    if rel.get("changelog"):
        rel["changelog"] = _abs(root, rel["changelog"])
    if (rel.get("git") or {}).get("repo"):
        rel["git"]["repo"] = _abs(root, rel["git"]["repo"])
    cap = cfg.setdefault("capture", {}) or {}
    for k in ("shots", "shot_list", "app"):
        if cap.get(k):
            cap[k] = _abs(root, cap[k])
    for im in cap.get("images") or []:
        im["file"] = _abs(root, im["file"])
    if cfg.get("music"):
        cfg["music"]["file"] = _abs(root, cfg["music"].get("file"))
    errs = validate(cfg)
    if errs:
        raise ConfigError(f"{path}:\n  - " + "\n  - ".join(errs))
    return cfg


def validate(cfg, check_files=True):
    e = []
    p = cfg.get("product") or {}
    if not p.get("name"):
        e.append("product.name is required")
    if not text(p.get("one_liner")):
        e.append("product.one_liner is required")
    langs = cfg.get("languages") or []
    bad = [x for x in langs if x not in LANGS]
    if bad or not langs:
        e.append(f"languages: pick from {LANGS} (got {langs})")
    from vstudio import platform as PF
    for pl in cfg.get("platforms") or []:
        try:
            PF.profile(pl, use_persona=False)
        except Exception as ex:                       # noqa: BLE001 - reported as a config error
            e.append(f"platforms: {pl}: {ex}")
    feats = cfg.get("features") or []
    if not feats:
        e.append("features: list the 3-6 features to show (draft them with `python -m vstudio.launch features`)")
    ids = [f.get("id") for f in feats]
    if len(set(ids)) != len(ids) or not all(ids):
        e.append("features: every feature needs a unique id")
    for f in feats:
        if not text(f.get("caption")):
            e.append(f"features.{f.get('id')}: caption is required (the on-screen line)")
        for lang in langs:
            if isinstance(f.get("caption"), dict) and not f["caption"].get(lang):
                e.append(f"features.{f.get('id')}: caption has no '{lang}' text")
    for cut in ("demo", "loop", "clips", "gallery"):
        for sid in (cfg.get(cut) or {}).get("shots") or []:
            if sid not in ids:
                e.append(f"{cut}.shots: unknown feature '{sid}'")
    for cut in ("demo", "clips"):
        for r in (cfg.get(cut) or {}).get("renders") or []:
            try:
                lang, asp = parse_render(r)
                if lang not in langs:
                    e.append(f"{cut}.renders: {r}: language '{lang}' not in languages")
            except ValueError as ex:
                e.append(f"{cut}.renders: {ex}")
    m = cfg.get("music")
    if m:
        if not m.get("license"):
            e.append("music.license is required (only license-safe tracks: say where it is from and the license)")
        if check_files and not (m.get("file") and os.path.exists(m["file"])):
            e.append(f"music.file not found: {m.get('file')}")
    if check_files:
        b = cfg.get("brand") or {}
        for k in ("logo", "logo_dark", "mark"):
            if b.get(k) and not os.path.exists(b[k]):
                e.append(f"brand.{k} not found: {b[k]}")
        for k, v in (b.get("fonts") or {}).items():
            if v and not os.path.exists(v):
                e.append(f"brand.fonts.{k} not found: {v}")
        cap = cfg.get("capture") or {}
        if cap.get("shots") and not os.path.exists(cap["shots"]) and not cap.get("shot_list"):
            e.append(f"capture.shots not found: {cap['shots']} (run the capture step first)")
        for im in cap.get("images") or []:
            if not os.path.exists(im["file"]):
                e.append(f"capture.images.{im.get('id')}: not found: {im['file']}")
    vo = cfg.get("voiceover") or {}
    if vo.get("enabled"):
        for f in feats:
            if not text(f.get("vo")):
                e.append(f"features.{f.get('id')}: voiceover.enabled needs a vo line per feature")
    return e


def parse_render(r):
    """"en:16:9" -> ("en", "16:9")."""
    lang, _, asp = str(r).partition(":")
    if asp not in ASPECTS:
        raise ValueError(f"{r}: want LANG:ASPECT with aspect one of {', '.join(ASPECTS)}")
    return lang, asp


def renders(cfg, cut):
    """[(lang, aspect)] to render for a cut. Defaults: demo = every aspect in the first language + 16:9 and 9:16
    in the others; clips = 1:1 and 9:16 in the first language + 9:16 in the others; loop = 16:9 first language."""
    if cut == "loop":
        return [(cfg["languages"][0], "16:9")]
    given = (cfg.get(cut) or {}).get("renders")
    if given:
        return [parse_render(r) for r in given]
    first, rest = cfg["languages"][0], cfg["languages"][1:]
    if cut == "demo":
        return [(first, a) for a in ("16:9", "9:16", "1:1")] + [(lang, a) for lang in rest for a in ("16:9", "9:16")]
    return [(first, a) for a in ("1:1", "9:16")] + [(lang, "9:16") for lang in rest]


def feature(cfg, fid):
    return next(f for f in cfg["features"] if f["id"] == fid)


def cut_features(cfg, cut):
    """Feature ids a cut shows, in order (default: every feature; loop: the first three)."""
    ids = (cfg.get(cut) or {}).get("shots")
    if ids:
        return list(ids)
    all_ids = [f["id"] for f in cfg["features"]]
    return all_ids[:3] if cut in ("loop",) else all_ids
