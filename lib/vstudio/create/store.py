"""Paths + atomic YAML / JSON IO for Create (all human-readable, ``schema_version: 1``, never any key or token).

    <home>/series/<sid>/series.yaml        the normal vstudio series file (id, name, recipe, params, spec ...);
                                           Create keeps its own fields under spec.create {format, budget_cny,
                                           routing, languages, platforms, created}
    <home>/series/<sid>/bible.yaml         engine, beats, cast, rules, gags, hooks, languages, aspect, length_s
    <home>/series/<sid>/ideas.yaml         [{id, title, logline, notes, est_cny, picked}]
    <home>/series/<sid>/spend.jsonl        append-only ledger (costs.ledger_append)
    <home>/series/<sid>/episodes/<eid>/    create.yaml (script, shots, routes, ladder, estimates, takes) +
                                           work/ai/ (the ai-video project.yaml, takes/, state.json, sheets/)
    <home>/create/spend-month.json         {month, cap_cny, used_cny}
    <home>/recordings/<ts>-<slug>/         recorder sessions (record.py)

``home`` = $VSTUDIO_HOME (vstudio.batch.clients.home) unless ``configure(home=...)`` points elsewhere (the desk's
mock mode and tests).
"""
import json
import os
import re
import tempfile
import threading
import time

import yaml

from vstudio import oscompat

from . import SCHEMA_VERSION
from .i18n import CreateError

SID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
EID_RE = SID_RE
SHOT_RE = re.compile(r"^\d{2,3}$")
SECRET_RE = re.compile(r"(api[_-]?key|token|secret|password)", re.I)

_home = None
_lock = threading.RLock()


def configure(home=None):
    """Point the store at another home (None = $VSTUDIO_HOME)."""
    global _home
    _home = os.path.abspath(home) if home else None


def home():
    if _home:
        return _home
    from vstudio.batch.clients import home as vhome
    return vhome()


def series_root():
    return os.path.join(home(), "series")


def create_dir():
    return os.path.join(home(), "create")


def recordings_root():
    """Recorder sessions are written by the desk's main process to $VSTUDIO_HOME/recordings - also in the desk's
    mock mode (whose series live elsewhere)."""
    from vstudio.batch.clients import home as vhome
    return os.path.join(vhome(), "recordings")


def month_path():
    return os.path.join(create_dir(), "spend-month.json")


# --------------------------------------------------------------------------- ids
def slugify(text, n=40):
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:n].strip("-")
    return s


def need_sid(sid):
    if not isinstance(sid, str) or not SID_RE.match(sid):
        raise CreateError("bad-input", field="sid")
    return sid


def need_eid(eid):
    if not isinstance(eid, str) or not EID_RE.match(eid):
        raise CreateError("bad-input", field="eid")
    return eid


def need_shot(no):
    no = str(no)
    if not SHOT_RE.match(no):
        raise CreateError("bad-input", field="shot")
    return no


def new_sid(name):
    base = slugify(name, 36) or "series"
    if not SID_RE.match(base):
        base = "series-" + base
    sid, n = base, 2
    while os.path.exists(series_dir(sid)):
        sid, n = f"{base}-{n}", n + 1
    return sid


# --------------------------------------------------------------------------- IO
def _no_secrets(obj, path=""):
    """Refuse to write anything that looks like a key into a Create file (defence in depth)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and SECRET_RE.search(k) and v not in (None, "", False):
                raise ValueError(f"refusing to write a secret-looking field {path}{k} into a Create file")
            _no_secrets(v, f"{path}{k}.")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _no_secrets(v, f"{path}{i}.")


def _atomic(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    oscompat.replace(tmp, path)
    return path


def write_yaml(path, obj):
    _no_secrets(obj)
    return _atomic(path, yaml.safe_dump(obj, allow_unicode=True, sort_keys=False))


def read_yaml(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            v = yaml.safe_load(f)
        return default if v is None else v
    except FileNotFoundError:
        return default


def write_json(path, obj):
    _no_secrets(obj)
    return _atomic(path, json.dumps(obj, ensure_ascii=False, indent=1))


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def append_jsonl(path, row):
    _no_secrets(row)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path):
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    try:
                        rows.append(json.loads(ln))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return rows


def stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------------- series
def series_dir(sid):
    return os.path.join(series_root(), need_sid(sid))


def series_exists(sid):
    return os.path.exists(os.path.join(series_dir(sid), "series.yaml"))


SERIES_KEYS = ("id", "name", "recipe", "params", "cadence", "accounts", "spec", "notes", "client", "auto")


def save_series_file(data):
    bad = [k for k in data if k not in SERIES_KEYS]
    if bad:
        raise ValueError(f"unknown series keys {bad}")
    d = series_dir(data["id"])
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    return write_yaml(os.path.join(d, "series.yaml"), data)


def load_series_file(sid):
    s = read_yaml(os.path.join(series_dir(sid), "series.yaml"))
    if not s:
        raise CreateError("not-found", status=404, what="series", id=sid)
    return s


def create_meta(s):
    return ((s.get("spec") or {}).get("create") or {})


def is_create_series(s):
    return bool(create_meta(s).get("format"))


def list_series_ids():
    root = series_root()
    out = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            if SID_RE.match(d) and os.path.exists(os.path.join(root, d, "series.yaml")):
                s = read_yaml(os.path.join(root, d, "series.yaml"), {}) or {}
                if is_create_series(s):
                    out.append(d)
    return out


def load_bible(sid):
    return read_yaml(os.path.join(series_dir(sid), "bible.yaml"), {}) or {}


def save_bible(sid, bible):
    bible = dict(bible, schema_version=SCHEMA_VERSION)
    return write_yaml(os.path.join(series_dir(sid), "bible.yaml"), bible)


def load_ideas(sid):
    return read_yaml(os.path.join(series_dir(sid), "ideas.yaml"), []) or []


def save_ideas(sid, ideas):
    return write_yaml(os.path.join(series_dir(sid), "ideas.yaml"), list(ideas))


def ledger_path(sid):
    return os.path.join(series_dir(sid), "spend.jsonl")


# --------------------------------------------------------------------------- episodes
def episode_dir(eid, sid=None):
    need_eid(eid)
    if sid:
        return os.path.join(series_dir(sid), "episodes", eid)
    for s in list_series_ids():
        d = os.path.join(series_root(), s, "episodes", eid)
        if os.path.exists(os.path.join(d, "create.yaml")):
            return d
    raise CreateError("not-found", status=404, what="episode", id=eid)


def load_episode(eid):
    d = episode_dir(eid)
    ep = read_yaml(os.path.join(d, "create.yaml"), {}) or {}
    ep["_dir"] = d
    return ep


def save_episode(ep):
    d = ep.get("_dir") or episode_dir(ep["id"], ep["series"])
    body = {k: v for k, v in ep.items() if not k.startswith("_")}
    body["schema_version"] = SCHEMA_VERSION
    body["updated"] = stamp()
    write_yaml(os.path.join(d, "create.yaml"), body)
    ep["_dir"] = d
    return ep


def list_episodes(sid):
    root = os.path.join(series_dir(sid), "episodes")
    out = []
    if os.path.isdir(root):
        for e in sorted(os.listdir(root)):
            p = os.path.join(root, e, "create.yaml")
            if EID_RE.match(e) and os.path.exists(p):
                ep = read_yaml(p, {}) or {}
                ep["_dir"] = os.path.join(root, e)
                out.append(ep)
    out.sort(key=lambda e: e.get("no") or 0)
    return out


def new_eid(sid, no):
    base = f"{sid[:40]}-e{int(no):02d}"
    eid, n = base, 2
    while os.path.exists(os.path.join(series_dir(sid), "episodes", eid)):
        eid, n = f"{base}-{n}", n + 1
    return eid


def work_dir(ep):
    return os.path.join(ep["_dir"], "work", "ai")
