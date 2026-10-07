"""Plugin discovery, manifests, on/off state.

Where plugins come from (in this order; a later one with the same kind + id is reported as a duplicate):
  1. built-in   lib/vstudio/plugins/builtin/manifests/*.yaml        (on by default)
  2. folders    $VSTUDIO_HOME/plugins/<name>/plugin.yaml, and every dir in $VSTUDIO_PLUGINS_PATH (os.pathsep list),
                each holding <name>/plugin.yaml                     (off until the user turns them on)
  3. packages   Python entry points, group ``reelfold.plugins``: the object is a manifest dict (or a list of them,
                or a callable returning either); ``entry`` is a normal module path   (off until turned on)

Manifest (plugin.yaml):
    id: hyperframes                    [a-z][a-z0-9-]{1,40}
    kind: importer | shot-provider | agent-runner
    name: HyperFrames                  or {en, zh, fr}
    version: 1.0.0
    api: 1                             the contract version it was written for (<= contract.API_VERSION)
    entry: package.module:Class        Python (a folder plugin's modules import from the folder)   - or -
    command: [./tool, "{job_dir}"]     importer / agent-runner as a plain command, no Python
    description, homepage, permissions [read-files, write-job, exec:<cli>, network, spend],
    cost {kind: free|local|subscription|paid, notes: {en, zh, fr}}, concurrency, timeout_s, rates {model: {...}},
    exts [.md, .json] (importers: file types it reads)

State: $VSTUDIO_HOME/plugins.json  {"enabled": {"<kind>:<id>": true}, "settings": {"<kind>:<id>": {...}}}.
Nothing is imported until a plugin is enabled AND used; a broken manifest / entry is listed with ``error``.
"""
import glob
import importlib
import json
import os
import re
import sys
import threading

import yaml

from . import contract

HERE = os.path.dirname(os.path.abspath(__file__))
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
ENTRY_RE = re.compile(r"^[A-Za-z_][\w.]*:[A-Za-z_]\w*$")
PERM_RE = re.compile(r"^(read-files|write-job|network|spend|exec:[\w.+-]{1,40})$")
GROUP = "reelfold.plugins"
_lock = threading.Lock()
_cache = {"key": None, "rows": None}
_objs = {}


class PluginError(RuntimeError):
    def __init__(self, code, **params):
        self.code = code if code.startswith("create.") else f"create.{code}"
        self.params = params
        super().__init__(f"{self.code} {params}")


def home():
    return os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio")


def state_path():
    return os.path.join(home(), "plugins.json")


def plugins_dirs():
    out = [os.path.join(home(), "plugins")]
    for d in (os.environ.get("VSTUDIO_PLUGINS_PATH") or "").split(os.pathsep):
        if d.strip():
            out.append(os.path.expanduser(d.strip()))
    return out


def key(kind, pid):
    return f"{kind}:{pid}"


# ------------------------------------------------------------------ manifests
def validate(m):
    """-> list of problems (empty = fine)."""
    bad = []
    if not isinstance(m, dict):
        return ["manifest is not a mapping"]
    if not ID_RE.match(str(m.get("id") or "")):
        bad.append("id: [a-z][a-z0-9-]{1,40}")
    if m.get("kind") not in contract.KINDS:
        bad.append("kind: " + " | ".join(contract.KINDS))
    try:
        api = int(m.get("api", 0))
        if api < 1 or api > contract.API_VERSION:
            bad.append(f"api: 1..{contract.API_VERSION} (this Reelfold speaks plugin API {contract.API_VERSION})")
    except (TypeError, ValueError):
        bad.append("api: an integer")
    if not str(m.get("version") or "").strip():
        bad.append("version")
    has_entry = isinstance(m.get("entry"), str) and ENTRY_RE.match(m["entry"])
    has_cmd = isinstance(m.get("command"), list) and m["command"] and all(isinstance(x, str) for x in m["command"])
    if m.get("kind") == "shot-provider" and not has_entry:
        bad.append("entry: module:Class (shot providers are Python)")
    elif not (has_entry or has_cmd or m.get("settings_command")):
        bad.append("entry: module:Class, or command: [argv...]")
    for p in m.get("permissions") or []:
        if not PERM_RE.match(str(p)):
            bad.append(f"permission {p!r}: read-files | write-job | exec:<cli> | network | spend")
    cost = (m.get("cost") or {}).get("kind", "free")
    if cost not in contract.COSTS:
        bad.append("cost.kind: " + " | ".join(contract.COSTS))
    if cost == "paid" and "spend" not in (m.get("permissions") or []):
        bad.append("a paid plugin must declare the 'spend' permission")
    return bad


def _row(m, origin, where):
    m = dict(m) if isinstance(m, dict) else {}
    probs = validate(m)
    pid, kind = str(m.get("id") or "?"), str(m.get("kind") or "?")
    cost = dict(m.get("cost") or {})
    cost.setdefault("kind", "free")
    return dict(key=key(kind, pid), id=pid, kind=kind, name=m.get("name") or pid, version=str(m.get("version") or ""),
                api=m.get("api"), origin=origin, where=where, description=m.get("description") or "",
                homepage=m.get("homepage"), permissions=list(m.get("permissions") or []), cost=cost,
                concurrency=int(m.get("concurrency") or 2), timeout_s=float(m.get("timeout_s") or 1800),
                exts=[str(x).lower() for x in m.get("exts") or []], default_enabled=bool(m.get("default_enabled", True)),
                error="; ".join(probs) if probs else None, _m=m)


def _read_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _builtin():
    rows = []
    for p in sorted(glob.glob(os.path.join(HERE, "builtin", "manifests", "*.yaml"))):
        try:
            rows.append(_row(_read_yaml(p), "builtin", p))
        except (OSError, yaml.YAMLError) as e:
            rows.append(_row({"id": os.path.basename(p)[:-5]}, "builtin", p) | dict(error=str(e)[:200]))
    return rows


def _folders():
    rows = []
    for d in plugins_dirs():
        for p in sorted(glob.glob(os.path.join(d, "*", "plugin.yaml"))):
            try:
                m = _read_yaml(p)
                if isinstance(m, dict):
                    m["_dir"] = os.path.dirname(p)
                rows.append(_row(m, "folder", p))
            except (OSError, yaml.YAMLError) as e:
                rows.append(dict(_row({"id": os.path.basename(os.path.dirname(p))}, "folder", p),
                                 error=f"plugin.yaml: {str(e)[:200]}"))
    return rows


def _entry_points():
    rows = []
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group=GROUP)
    except Exception:  # noqa: BLE001  (no metadata: no packaged plugins)
        return rows
    for ep in eps:
        try:
            obj = ep.load()
            obj = obj() if callable(obj) else obj
            for m in obj if isinstance(obj, list) else [obj]:
                rows.append(_row(m, "package", f"{ep.value} ({getattr(ep.dist, 'name', '?')})"))
        except Exception as e:  # noqa: BLE001
            rows.append(dict(_row({"id": re.sub(r"[^a-z0-9-]", "-", ep.name.lower())[:40] or "x"}, "package",
                                  ep.value), error=f"entry point: {str(e)[:200]}"))
    return rows


def _fingerprint():
    parts = [os.environ.get("VSTUDIO_PLUGINS_PATH") or "", home()]
    for d in plugins_dirs():
        for p in glob.glob(os.path.join(d, "*", "plugin.yaml")):
            try:
                parts.append(f"{p}:{os.path.getmtime(p)}")
            except OSError:
                pass
    return "|".join(parts)


def discover(refresh=False):
    """-> [row]: every plugin found (duplicates and broken ones included, with ``error``)."""
    fp = _fingerprint()
    with _lock:
        if not refresh and _cache["key"] == fp and _cache["rows"] is not None:
            return _cache["rows"]
        rows, seen = [], set()
        for r in _builtin() + _folders() + _entry_points():
            if r["key"] in seen and not r["error"]:
                r["error"] = f"duplicate {r['kind']} id {r['id']!r} (the first one wins)"
            if not r["error"]:
                seen.add(r["key"])
            rows.append(r)
        _cache.update(key=fp, rows=rows)
        _objs.clear()
        return rows


# ------------------------------------------------------------------ on / off + settings
def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(d):
    os.makedirs(os.path.dirname(state_path()), exist_ok=True)
    tmp = state_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    os.replace(tmp, state_path())


def is_enabled(row, state=None):
    st = (state if state is not None else load_state()).get("enabled") or {}
    if row["key"] in st:
        return bool(st[row["key"]]) and not row["error"]
    return row["origin"] == "builtin" and row["default_enabled"] and not row["error"]


def set_enabled(k, on):
    row = find(k)
    if row["error"] and on:
        raise PluginError("plugin.not-ready", name=row["id"], detail=row["error"])
    st = load_state()
    st.setdefault("enabled", {})[row["key"]] = bool(on)
    save_state(st)
    _objs.pop(row["key"], None)
    return public(row)


def settings_of(k):
    return dict((load_state().get("settings") or {}).get(k) or {})


def set_settings(k, values):
    row = find(k)
    if not isinstance(values, dict):
        raise PluginError("bad-input", field="settings")
    st = load_state()
    st.setdefault("settings", {})[row["key"]] = values
    save_state(st)
    _objs.pop(row["key"], None)
    return public(row)


# ------------------------------------------------------------------ lookup + objects
def find(k, kind=None):
    """``k``: "<kind>:<id>" or a bare id with ``kind``."""
    if kind and ":" not in str(k):
        k = key(kind, k)
    for r in discover():
        if r["key"] == k and not (r["error"] or "").startswith("duplicate"):
            return r
    raise PluginError("plugin.not-found", id=str(k))


def rows(kind=None, enabled_only=False):
    st = load_state()
    out = [r for r in discover() if (kind is None or r["kind"] == kind)]
    if enabled_only:
        out = [r for r in out if is_enabled(r, st)]
    return out


def _import_entry(row):
    mod, _, attr = row["_m"]["entry"].partition(":")
    d = row["_m"].get("_dir")
    if d and d not in sys.path:
        sys.path.insert(0, d)
    return getattr(importlib.import_module(mod), attr)


def load_class(row):
    """The Python class / object a manifest points at (imports the module)."""
    return _import_entry(row)


def instance(k, kind=None, check_enabled=True):
    """A ready-to-use plugin object (importer / runner instance; shot providers: the provider class)."""
    row = find(k, kind)
    if row["error"]:
        raise PluginError("plugin.not-ready", name=row["id"], detail=row["error"])
    if check_enabled and not is_enabled(row):
        raise PluginError("plugin.disabled", name=display_name(row))
    if row["key"] in _objs:
        return _objs[row["key"]]
    m = row["_m"]
    sets = settings_of(row["key"])
    if row["kind"] == "agent-runner":
        obj = _import_entry(row)(m, sets) if m.get("entry") else contract.CommandRunner(m, sets)
    elif row["kind"] == "importer":
        obj = _import_entry(row)(m) if m.get("entry") else CommandImporter(m)
    else:
        obj = _import_entry(row)
    _objs[row["key"]] = obj
    return obj


def display_name(row, lang="en"):
    n = row.get("name")
    if isinstance(n, dict):
        return n.get(lang[:2]) or n.get("en") or row["id"]
    return str(n or row["id"])


def public(row, lang="en", st=None, with_status=True):
    """The JSON the desk shows (no private fields)."""
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    out["enabled"] = is_enabled(row, st)
    out["label"] = display_name(row, lang)
    sets = ((st if st is not None else load_state()).get("settings") or {}).get(row["key"]) or {}
    out["lanes"] = int(sets.get("lanes") or row["concurrency"])
    out["configured"] = sorted(k for k in sets if k != "lanes")
    if with_status and out["enabled"] and row["kind"] == "agent-runner":
        try:
            out["status"] = instance(row["key"]).status()
        except Exception as e:  # noqa: BLE001
            out["status"] = dict(ready=False, code="create.plugin.not-ready", params=dict(detail=str(e)[:200]))
    elif with_status and out["enabled"] and row["kind"] == "shot-provider" and not row["error"]:
        try:
            cls = instance(row["key"])
            info = getattr(cls, "info", {}) or {}
            out["provider_kind"] = info.get("kind")
            if info.get("kind") == "render":
                out["status"] = cls().status()
        except Exception as e:  # noqa: BLE001
            out["status"] = dict(ready=False, code="create.plugin.not-ready", params=dict(detail=str(e)[:200]))
    return out


def listing(lang="en"):
    st = load_state()
    return dict(api=contract.API_VERSION, dirs=plugins_dirs(),
                plugins=[public(r, lang, st) for r in discover()])


# ------------------------------------------------------------------ command importers
class CommandImporter(contract.Importer):
    """``command: [./import, "{path}"]`` -> a Board as JSON on stdout (60 s limit, cwd = the plugin folder)."""

    def __init__(self, manifest=None):
        super().__init__(manifest)
        self.id = (manifest or {}).get("id") or "command"
        self.exts = tuple((manifest or {}).get("exts") or ())

    def load(self, path):
        import subprocess
        m = self.manifest
        base = m.get("_dir") or os.getcwd()
        argv = [os.path.join(base, a[2:]) if a.startswith("./") else a for a in m["command"]]
        argv = [a.replace("{path}", str(path)) for a in argv]
        r = subprocess.run(argv, capture_output=True, text=True, cwd=base, timeout=60, stdin=subprocess.DEVNULL)
        if r.returncode:
            raise PluginError("import.unreadable", name=os.path.basename(str(path)),
                              error=(r.stderr or "").strip()[-200:] or f"exit {r.returncode}")
        try:
            return json.loads(r.stdout)
        except ValueError as e:
            raise PluginError("import.unreadable", name=os.path.basename(str(path)), error="no JSON board") from e
