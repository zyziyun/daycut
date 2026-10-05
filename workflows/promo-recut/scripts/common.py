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
