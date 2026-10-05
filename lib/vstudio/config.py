"""Shared paths, fonts, models and the creator persona.

Everything that used to be hard-coded (system fonts, ~/Desktop/... model files, the creator's
speed defaults and brand colours) resolves through here.

    from vstudio.config import font, model, persona
    font("cjk-bold")          -> path to Noto Sans SC Bold (downloaded by install.sh)
    model("face_landmarker")  -> path to MediaPipe face_landmarker.task
    persona()["speed"]["body"]
"""
import json
import os
from functools import lru_cache

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.environ.get("VSTUDIO_CACHE", os.path.expanduser("~/.cache/video-studio"))
FONT_DIR = os.path.join(CACHE, "fonts")
MODEL_DIR = os.path.join(CACHE, "models")

# role -> candidate files (first that exists wins). All OFL / Apache, fetched by install.sh.
FONTS = {
    "cjk": ["NotoSansSC-Regular.otf"],
    "cjk-bold": ["NotoSansSC-Bold.otf"],
    "serif": ["STIXTwoText-Regular.ttf"],
    "serif-italic": ["STIXTwoText-Italic.ttf"],
    "mono": ["JetBrainsMono-Regular.ttf"],
    "mono-bold": ["JetBrainsMono-Bold.ttf"],
}
MODELS = {
    "face_landmarker": "face_landmarker.task",       # MediaPipe, Apache-2.0
    "selfie_segmenter": "selfie_segmenter.tflite",   # MediaPipe, Apache-2.0
}


class MissingAsset(FileNotFoundError):
    pass


def font(role: str) -> str:
    """Path of a font for a role. persona.fonts.<role> may point to your own file."""
    custom = (persona().get("fonts") or {}).get(role)
    if custom and os.path.exists(os.path.expanduser(custom)):
        return os.path.expanduser(custom)
    for name in FONTS.get(role, [role]):
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return p
    raise MissingAsset(f"font '{role}' not found in {FONT_DIR} - run ./install.sh (or set fonts.{role} in persona.local.yaml)")


def model(name: str) -> str:
    p = os.path.join(MODEL_DIR, MODELS.get(name, name))
    if not os.path.exists(p):
        raise MissingAsset(f"model '{name}' not found at {p} - run ./install.sh")
    return p


def _load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    try:
        import yaml  # PyYAML
        return yaml.safe_load(txt) or {}
    except ImportError:
        return json.loads(txt)


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache(maxsize=1)
def persona() -> dict:
    """persona.example.yaml (defaults) <- persona.yaml <- persona.local.yaml (private, gitignored)."""
    data = {}
    for name in ("persona.example.yaml", "persona.yaml", "persona.local.yaml"):
        d = _load(os.path.join(REPO, name))
        if d:
            data = _merge(data, d)
    env = os.environ.get("VSTUDIO_PERSONA")
    if env:
        data = _merge(data, _load(os.path.expanduser(env)) or {})
    return data


def xhs_len(title: str) -> float:
    """小红书 title length: CJK/full-width = 1, latin letter/digit/space = 0.5."""
    return sum(0.5 if ord(c) < 0x2E80 else 1.0 for c in title)
