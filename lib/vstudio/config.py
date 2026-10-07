"""Shared paths, fonts, models and the creator persona.

Everything that used to be hard-coded (system fonts, ~/Desktop/... model files, the creator's
speed defaults and brand colours) resolves through here.

    from vstudio.config import font, model, persona
    font("cjk-bold")          -> path to Noto Sans SC Bold (downloaded by install.sh)
    font("cjk-serif")         -> Noto Serif SC (titles in 文艺 / photo-story modes)
    model("face_landmarker")  -> path to MediaPipe face_landmarker.task
    persona()["speed"]["body"]
"""
import json
import os
import re
import sys
from functools import lru_cache

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE = os.environ.get("VSTUDIO_CACHE", os.path.expanduser("~/.cache/video-studio"))
# Older builds wrote some caches (ASR fallback sidecars, the batch bench table) to ~/.cache/vstudio. ONE root now:
# everything is written under CACHE; the legacy folder is still READ (cache_dirs) so nothing is recomputed.
LEGACY_CACHE = os.path.expanduser("~/.cache/vstudio")
FONT_DIR = os.path.join(CACHE, "fonts")
MODEL_DIR = os.path.join(CACHE, "models")

# role -> candidate files (first that exists wins). All OFL / Apache, fetched by install.sh.
FONTS = {
    "cjk": ["NotoSansSC-Regular.otf"],
    "cjk-bold": ["NotoSansSC-Bold.otf"],
    "cjk-serif": ["NotoSerifSC-Regular.otf"],
    "cjk-serif-bold": ["NotoSerifSC-Bold.otf"],
    "serif": ["STIXTwoText-Regular.ttf"],
    "serif-italic": ["STIXTwoText-Italic.ttf"],
    "mono": ["JetBrainsMono-Regular.ttf"],
    "mono-bold": ["JetBrainsMono-Bold.ttf"],
}
MODELS = {
    "face_landmarker": "face_landmarker.task",       # MediaPipe, Apache-2.0
    "selfie_segmenter": "selfie_segmenter.tflite",   # MediaPipe, Apache-2.0
    "selfie_multiclass": "selfie_multiclass_256x256.tflite",  # MediaPipe, Apache-2.0 (model card 2023-05-10)
}


def cache_dir(*parts, create=True):
    """``<cache root>/<parts>`` (``$VSTUDIO_CACHE``, default ~/.cache/video-studio) - where caches are written."""
    root = os.environ.get("VSTUDIO_CACHE") or CACHE
    d = os.path.join(root, *parts)
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def cache_dirs(*parts):
    """Where to READ a cache: the current root first, then the legacy ~/.cache/vstudio (unless $VSTUDIO_CACHE
    is set, which pins one root)."""
    out = [cache_dir(*parts, create=False)]
    if not os.environ.get("VSTUDIO_CACHE"):
        old = os.path.join(LEGACY_CACHE, *parts)
        if os.path.isdir(old) and old not in out:
            out.append(old)
    return out


class MissingAsset(FileNotFoundError):
    pass


_WARNED = set()


def _warn_once(key, msg):
    if key not in _WARNED:
        _WARNED.add(key)
        print(f"!! video-studio: {msg}", file=sys.stderr)


def ttc_face(path: str, index: int) -> str:
    """Face ``index`` of a .ttc/.otc collection extracted (once, fontTools) to a standalone font file
    under FONT_DIR/extracted/, so every consumer (PIL, ffmpeg drawtext, libass) gets the right face.
    Collections often put the Black/heavy face at index 0 (e.g. a system Songti), hence "file.ttc#N"."""
    from fontTools.ttLib import TTCollection
    stem = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.join(FONT_DIR, "extracted")
    for ext in (".ttf", ".otf"):
        p = os.path.join(out_dir, f"{stem}-{index}{ext}")
        if os.path.exists(p) and os.path.getmtime(p) >= os.path.getmtime(path):
            return p
    coll = TTCollection(path)
    if not 0 <= index < len(coll.fonts):
        raise MissingAsset(f"{path} has {len(coll.fonts)} faces; index {index} is out of range")
    f = coll.fonts[index]
    os.makedirs(out_dir, exist_ok=True)
    p = os.path.join(out_dir, f"{stem}-{index}{'.otf' if 'CFF ' in f else '.ttf'}")
    f.save(p)
    return p


def _custom_font(role, spec):
    """persona fonts.<role>: "path" or "path.ttc#N" (face N of a collection). None if unusable."""
    m = re.match(r"^(.*?\.(?:ttc|otc))#(\d+)$", str(spec), re.I)
    path, idx = (m.group(1), int(m.group(2))) if m else (str(spec), None)
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        _warn_once(("custom", role), f"fonts.{role} = {spec!r} does not exist; using the default for '{role}'")
        return None
    if idx is None:
        return path
    try:
        return ttc_face(path, idx)
    except Exception as e:  # noqa: BLE001 - surface it, then use the default role font
        _warn_once(("ttc", role), f"fonts.{role} = {spec!r}: cannot extract face {idx} ({e})")
        return None


def font(role: str) -> str:
    """Path of a font for a role. persona.fonts.<role> may point to your own file, or to one face of
    a collection as "path/to/Fonts.ttc#2". A missing role font raises MissingAsset AND prints a loud
    warning once (callers that fall back to another role then do so visibly, not silently)."""
    custom = (persona().get("fonts") or {}).get(role)
    if custom:
        p = _custom_font(role, custom)
        if p:
            return p
    for name in FONTS.get(role, [role]):
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return p
    msg = f"font '{role}' not found in {FONT_DIR} - run ./install.sh (or set fonts.{role} in persona.local.yaml)"
    if role in FONTS:
        _warn_once(("missing", role), msg + "; anything drawn with it will use a fallback face")
    raise MissingAsset(msg)


def model(name: str) -> str:
    p = os.path.join(MODEL_DIR, MODELS.get(name, name))
    if not os.path.exists(p):
        raise MissingAsset(f"model '{name}' not found at {p} - run ./install.sh")
    return p


class YAMLUnavailable(RuntimeError):
    """A YAML file must be read but PyYAML is not installed (never silently read as JSON)."""


def load_yaml_text(txt, path="<yaml>"):
    """YAML text -> data. Without PyYAML only JSON-compatible text is accepted; anything else raises
    ``YAMLUnavailable`` with the fix, instead of a confusing JSONDecodeError (or silently empty settings)."""
    try:
        import yaml  # PyYAML
    except ImportError:
        try:
            return json.loads(txt) if txt.strip() else {}
        except ValueError:
            raise YAMLUnavailable(f"{path} is YAML but PyYAML is not installed: pip install pyyaml "
                                  "(or pip install -r requirements.txt)") from None
    return yaml.safe_load(txt) or {}


def load_yaml(path):
    """A YAML file -> data (``load_yaml_text``); None when the file does not exist."""
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return load_yaml_text(f.read(), path)


_load = load_yaml


def load_py(path, name="cfg"):
    """Run a Python config / reply file (``strict.py``, ``edit_list.py`` ...) as a module, always from its source.
    importlib's .pyc check (mtime in whole seconds + size) cannot see a file rewritten within the same second
    with the same size, so a cached bytecode would silently replay the previous REPLY."""
    import types
    path = os.path.abspath(path)
    m = types.ModuleType(name)
    m.__file__ = path
    with open(path, encoding="utf-8") as f:
        src = f.read()
    exec(compile(src, path, "exec"), m.__dict__)  # noqa: S102 - the creator's own config file
    return m


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@lru_cache(maxsize=1)
def persona() -> dict:
    """persona.example.yaml (defaults) <- persona.yaml <- persona.local.yaml (private, gitignored)."""
    data = {}
    names = ("persona.example.yaml", "persona.yaml", "persona.local.yaml")
    if os.environ.get("VSTUDIO_DEFAULT_PERSONA"):     # tests: ignore the creator's own persona files
        names = names[:1]
    for name in names:
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
