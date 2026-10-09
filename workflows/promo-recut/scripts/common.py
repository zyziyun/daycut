"""Shared helpers for the promo-recut scripts: project config, paths, persona lookup, link_or_copy.

ffmpeg / whisper / time maps live in lib/vstudio (media, asr, cut.TimeMap).

Every path in the project config is relative to the folder that holds the config file
(the "project dir"). Nothing here knows about any particular video.
"""
import json
import os
import shutil
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "lib"))
from vstudio.config import persona  # noqa: E402


# ---------------------------------------------------------------- config
class Project:
    def __init__(self, config_path):
        self.config_path = os.path.abspath(config_path)
        self.dir = os.path.dirname(self.config_path)
        self.cfg = load_config(self.config_path)
        self.work = self.p(self.cfg.get("work_dir", "work"))
        os.makedirs(self.work, exist_ok=True)

    def p(self, rel):
        """Absolute path for a config-relative path (absolute paths pass through)."""
        return rel if os.path.isabs(rel) else os.path.join(self.dir, rel)

    def w(self, name):
        return os.path.join(self.work, name)

    def get(self, dotted, default=None):
        cur = self.cfg
        for k in dotted.split("."):
            if not isinstance(cur, dict) or k not in cur:
                return default
            cur = cur[k]
        return cur


def load_config(path):
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml
        return yaml.safe_load(txt) or {}
    return json.loads(txt)


def _persona_promo():
    from vstudio import formats
    return formats._persona_formats().get("promo") or {}


def body_rate(prj):
    """Body playback rate: config rates.body > persona formats.promo.speed.body > persona speed.body > the
    promo format default (vstudio.formats). An explicit value is used as given (no clamp)."""
    from vstudio import formats
    if prj.get("rates.body") is not None:
        return float(prj.get("rates.body"))
    pf = (_persona_promo().get("speed") or {}).get("body")
    if pf is not None:
        return float(pf)
    if P("speed.body") is not None:
        return float(P("speed.body"))
    return float(formats.get("promo")["speed"]["body"])


def hook_speed(prj):
    """Hook montage speed: config hooks.speed > persona formats.promo.hooks_speed > persona
    formats.promo.speed.hook > persona speed.hook > the promo format default. No clamp."""
    from vstudio import formats
    if prj.get("hooks.speed") is not None:
        return float(prj.get("hooks.speed"))
    pf = _persona_promo()
    for v in (pf.get("hooks_speed"), (pf.get("speed") or {}).get("hook"), P("speed.hook")):
        if v is not None:
            return float(v)
    return float(formats.get("promo")["speed"]["hook"])


# ---------------------------------------------------------------- montage clips
_NUM = (int, float)


def parse_clip(c, k=0):
    """One montage.clips entry -> {"src": source ref or None (= highlights), "start", "end", "label", + "crop" /
    "fit" when given}. Forms:
      [start, end] / [start, end, label]                 the `highlights` file (label null = previous continues)
      [source, start, end] / [source, start, end, label] source: a broll index (0 = first), a broll file name /
                                                         stem / path, "highlights", or a config-relative path
      {src, start, end, label, crop, fit}                the same as a mapping (crop / fit per clip)"""
    if isinstance(c, dict):
        src = c.get("src", c.get("source"))
        if c.get("start") is None or c.get("end") is None:
            raise SystemExit(f"montage.clips[{k}]: needs start and end")
        out = dict(src=src, start=float(c["start"]), end=float(c["end"]), label=c.get("label"))
        out.update({x: c[x] for x in ("crop", "fit") if x in c})
    else:
        c = list(c or [])
        new = len(c) == 4 or (len(c) == 3 and (isinstance(c[0], str) or
                                               (isinstance(c[2], _NUM) and not isinstance(c[2], bool))))
        if new:
            src, a, b, lab = (c + [None])[:4]
        elif len(c) in (2, 3):
            src, a, b, lab = None, c[0], c[1], (c[2] if len(c) > 2 else None)
        else:
            raise SystemExit(f"montage.clips[{k}]: want [start, end, label] or [source, start, end, label], got {c!r}")
        out = dict(src=src, start=float(a), end=float(b), label=lab)
    if isinstance(out["src"], bool) or (out["src"] is not None and not isinstance(out["src"], (str, int))):
        raise SystemExit(f"montage.clips[{k}]: source {out['src']!r}: a broll index, file name or path")
    if out["end"] - out["start"] < 0.5:
        raise SystemExit(f"montage.clips[{k}]: [{out['start']}, {out['end']}] is shorter than 0.5 s")
    return out


def montage_clips(prj):
    """config montage.clips, parsed (``parse_clip``); [] when there is no montage."""
    return [parse_clip(c, k) for k, c in enumerate((prj.get("montage") or {}).get("clips") or [])]


def broll_list(prj):
    """The project's b-roll videos (config ``broll``: one path or a list), absolute."""
    b = prj.get("broll") or []
    return [prj.p(x) for x in ([b] if isinstance(b, str) else b) if x]


def resolve_source(prj, ref, k=0):
    """A clip's source ref -> absolute path. None / "highlights" = config highlights; an int = broll[ref];
    a string = the broll entry with that path / file name / stem, else a config-relative path."""
    br = broll_list(prj)
    if ref is None or ref == "highlights":
        if not prj.get("highlights"):
            raise SystemExit(f"montage.clips[{k}]: no source named and the config has no highlights file: "
                             "use [source, start, end, label] with a broll index or file name")
        return prj.p(prj.get("highlights"))
    if isinstance(ref, int):
        if not 0 <= ref < len(br):
            raise SystemExit(f"montage.clips[{k}]: broll index {ref} out of range (have {len(br)}: 0..{len(br) - 1})")
        return br[ref]
    for x in br:
        base = os.path.basename(x)
        if ref in (x, base, os.path.splitext(base)[0]):
            return x
    p = prj.p(ref)
    if os.path.exists(p):
        return p
    names = ", ".join(f"{i}: {os.path.basename(x)}" for i, x in enumerate(br)) or "none"
    raise SystemExit(f"montage.clips[{k}]: source {ref!r} is not a broll file ({names}) nor an existing path")


def P(dotted, default=None):
    """persona lookup with a safe default, e.g. P('audio.loudness_lufs', -14)."""
    cur = persona()
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# ---------------------------------------------------------------- files
def link_or_copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        if os.path.getsize(dst) == os.path.getsize(src) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return dst
        os.remove(dst)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
    return dst
