"""Batch spec (YAML / JSON; job rows also from CSV) -> normalized spec + job list with variants.

Spec keys (all optional except recipe + inputs; see references/BATCH.md):
  name, recipe, plugins, inputs, planner, segments (job-list file), jobs (inline rows), defaults,
  variants {by: [hook, platform], include_no_hook}, budget {max_usd, max_hours, max_storage_gb},
  concurrency {resource: n}, qc {...}, breaker {max_fail_rate, min_jobs, max_red_rate}, retry {backoff},
  asr {backend, language, prompt, transcriber}, schedule {per_day, start, times}, prices {...}

A job row: id, range (or start/end), title, hook {src, lines} (or hook_start/hook_end/hook_lines, or the
segments.yaml shape {start, end, text}), hooks [...] (variant hooks), body, tags, platforms, layout, speed,
cleanup_reply, cover, cuts [[a, b, why]], ... - unknown keys (chapter, notes, why, risk, ...) are kept as params,
so recipes can read their own.

segments.yaml adapter: a job-list file may carry a header next to its rows ({source, series, speed, ...,
segments: [...]}): ``source`` fills inputs.source when the spec has none, every other header key is a job
default (below the spec's own ``defaults``). Spec top-level ``source`` / ``speed`` / ``series`` work the same
way, so a segments.yaml can also be planned directly (``plan segments.yaml --recipe longform-split``).
Spec sections read by longform-split: privacy {exclude}, screen {region, min_scale, ..., geometry {...}},
vertical {mode, split, speaker, series, master_preset}, subtitles {term_fixes, errata}, notes {window, tag}, style.
"""
import copy
import csv
import os

from .util import parse_range, slug, split_list

DEFAULTS = dict(
    platforms=["xiaohongshu:full"],
    layout="pad-blur",            # export reframe mode when the aspect changes: face | center | pad-blur | letterbox
    cleanup_profile=None,         # gentle | standard | tight | off (default persona cleanup.profile -> standard)
    speed=1.0,
    hook_speed=None,
    captions=True,
    preset="medium",
)


def _load_any(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        with open(path, encoding="utf-8-sig", newline="") as f:
            return [dict(r) for r in csv.DictReader(f)]
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if ext == ".json":
        import json
        return json.loads(txt)
    import yaml
    return yaml.safe_load(txt)


def _abs(base, p):
    if not p:
        return p
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(base, p))


def load_spec(path, overrides=None):
    """Spec file -> dict. A .csv path is a bare job list: recipe / inputs come from ``overrides``."""
    path = os.path.abspath(path)
    base = os.path.dirname(path)
    data = _load_any(path)
    if isinstance(data, list):
        spec = dict(jobs=data)
    else:
        spec = dict(data or {})
    for k, v in (overrides or {}).items():
        if v is not None:
            if isinstance(v, dict):
                spec[k] = dict(spec.get(k) or {}, **v)
            else:
                spec[k] = v
    spec["_path"] = path
    spec["_dir"] = base
    spec.setdefault("name", slug(os.path.splitext(os.path.basename(path))[0]))
    if not spec.get("recipe"):
        raise ValueError(f"{path}: `recipe` is required (e.g. longform-slices, talkinghead-clips)")
    inp = dict(spec.get("inputs") or {})
    for k in ("source", "folder", "transcript"):
        if inp.get(k):
            inp[k] = _abs(base, inp[k])
    if inp.get("clips"):
        inp["clips"] = [_abs(base, c) for c in inp["clips"]]
    if spec.get("plugin_paths"):
        spec["plugin_paths"] = [_abs(base, x) for x in spec["plugin_paths"]]
    header = {k: spec[k] for k in HEADER_KEYS if k in spec and k != "source"}
    if not inp.get("source") and spec.get("source"):
        inp["source"] = _abs(base, spec["source"])
    if spec.get("segments") and isinstance(spec["segments"], str):
        spec["segments"] = _abs(base, spec["segments"])
        h = segments_header(spec["segments"])
        if h.get("source") and not inp.get("source"):
            inp["source"] = _abs(os.path.dirname(spec["segments"]), h["source"])
        header = dict({k: v for k, v in h.items() if k != "source"}, **header)
    spec["inputs"] = inp
    user = dict(spec.get("defaults") or {})
    spec["_user_defaults"] = user
    spec["defaults"] = dict(DEFAULTS, **header, **user)
    return spec


HEADER_KEYS = ("source", "speed", "series")
_NOT_DEFAULTS = ("segments", "jobs", "items", "source", "inputs", "name", "recipe", "defaults")


def segments_header(path):
    """Header keys of a job-list file ({source, series, speed, ..., segments: [...]}); {} for a bare list / CSV."""
    if os.path.splitext(path)[1].lower() == ".csv" or not os.path.exists(path):
        return {}
    data = _load_any(path)
    if not isinstance(data, dict):
        return {}
    out = {k: v for k, v in data.items() if k not in _NOT_DEFAULTS}
    if data.get("source"):
        out["source"] = data["source"]
    return out


def read_rows(src, base=None):
    """Job rows from a file (YAML list / {jobs|segments: [...]} / CSV) or an inline list."""
    if src is None:
        return []
    if isinstance(src, str):
        data = _load_any(_abs(base or os.getcwd(), src))
    else:
        data = src
    if isinstance(data, dict):
        data = data.get("jobs") or data.get("segments") or data.get("items") or []
    return [normalize_row(r, i) for i, r in enumerate(data or [])]


def _hook(v, lines=None):
    if not v:
        return None
    if isinstance(v, dict):
        rng = v.get("src") or v.get("range")
        if rng is None and v.get("start") is not None and v.get("end") is not None:    # segments.yaml shape
            rng = [v["start"], v["end"]]
        src = parse_range(rng)
        ls = split_list(v.get("lines") or lines or ([v["text"]] if v.get("text") else None), "|")
    else:
        src, ls = parse_range(v), split_list(lines, "|")
    return dict(src=list(src), lines=ls) if src else None


def normalize_row(r, i=0):
    """One raw row (YAML dict or CSV dict of strings) -> canonical params dict (with ``id``)."""
    r = {k.strip() if isinstance(k, str) else k: v for k, v in dict(r).items() if v not in (None, "")}
    out = {}
    rid = r.pop("id", None)
    out["id"] = slug(rid) if rid else f"s{i + 1:03d}"
    if not rid:
        out["_auto_id"] = True
    rng = r.pop("range", None) or r.pop("src", None)
    if rng is None and "start" in r and "end" in r:
        rng = [r.pop("start"), r.pop("end")]
    if rng is not None:
        out["range"] = list(parse_range(rng))
    hl = r.pop("hook_lines", None)
    hk = _hook(r.pop("hook", None), hl)
    if hk is None and "hook_start" in r and "hook_end" in r:
        hk = _hook([r.pop("hook_start"), r.pop("hook_end")], hl)
    r.pop("hook_start", None), r.pop("hook_end", None)
    if hk:
        out["hook"] = hk
    hooks = r.pop("hooks", None)
    if hooks:
        out["hooks"] = [h for h in (_hook(x) for x in hooks) if h]
    if "tags" in r:
        out["tags"] = split_list(r.pop("tags"))
    if "platforms" in r:
        out["platforms"] = split_list(r.pop("platforms"))
    for k in ("cuts", "notes"):                       # CSV: "169.6-172.1|185.3-193.5" / "note 1|note 2"
        if isinstance(r.get(k), str):
            out[k] = split_list(r.pop(k), "|")
    for k in ("speed", "hook_speed"):
        if k in r:
            out[k] = float(r.pop(k))
    for k, v in r.items():
        out[k] = v
    return out


def _pkey(p):
    return slug(p.replace(":", "-"))


def apply_variants(spec, items):
    """items [{"item", "params"}] -> jobs [{"id", "item", "variant", "params"}] (hook x platform fan-out)."""
    by = split_list((spec.get("variants") or {}).get("by"))
    with_none = bool((spec.get("variants") or {}).get("include_no_hook"))
    jobs = []
    for it in items:
        base = it["params"]
        hv = [(None, base.get("hook"))]
        if "hook" in by and base.get("hooks"):
            hv = ([("h0", None)] if with_none else []) + [(f"h{k + 1}", h) for k, h in enumerate(base["hooks"])]
        pv = [(None, base.get("platforms"))]
        if "platform" in by:
            pv = [(_pkey(p), [p]) for p in base.get("platforms") or []]
        for hk, h in hv:
            for pk, pl in pv:
                p = copy.deepcopy(base)
                p.pop("hooks", None)
                if h:
                    p["hook"] = h
                else:
                    p.pop("hook", None)
                p["platforms"] = pl
                var = ".".join(x for x in (hk, pk) if x)
                jobs.append(dict(id=it["item"] + (f".{var}" if var else ""), item=it["item"], variant=var, params=p))
    seen = set()
    for j in jobs:
        if j["id"] in seen:
            raise ValueError(f"duplicate job id {j['id']} (give rows unique `id`s)")
        seen.add(j["id"])
    return jobs


def with_defaults(spec, row):
    p = dict(spec.get("defaults") or {})
    p.update({k: v for k, v in row.items() if k not in ("id", "_auto_id")})
    return p
