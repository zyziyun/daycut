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
