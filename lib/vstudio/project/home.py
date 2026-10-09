"""Cross-project state under ``$VSTUDIO_HOME`` (default ``~/.config/vstudio``): the projects registry (for the
inbox / lanes) and **series** - a recurring format above projects with shared presets.

    $VSTUDIO_HOME/projects.json                 [{dir, name, recipe, series, client, created}]
    $VSTUDIO_HOME/series/<id>/series.yaml       {id, name, recipe, params {style, intro, outro, cover_style, tags,
                                                 platforms, ...}, cadence {per_week, days, times}, accounts [..],
                                                 spec {...}, notes}
    $VSTUDIO_HOME/series/<id>/assets/           shared refs (character sheets, intro / outro clips, music)

``project new --series S`` inherits the series recipe and params (project params win); every project of a series
shares the vstudio caches (one transcript per source, TTS clips, AIGC character refs in the series assets).
"""
import os
import time

import yaml

from vstudio.batch.clients import home
from vstudio.batch.util import read_json, slug, write_json


def registry_path():
    return os.path.join(home(), "projects.json")


def projects():
    return [p for p in (read_json(registry_path(), []) or []) if isinstance(p, dict) and p.get("dir")]


def prune():
    """Rewrite projects.json without missing / temp-dir projects (test junk). -> the removed entries."""
    from vstudio.batch.clients import keep_entry
    path = registry_path()
    rows = projects()
    keep = [p for p in rows if keep_entry(p["dir"], path) and _live(p)]
    gone = [p for p in rows if p not in keep]
    if gone:
        try:
            write_json(path, keep)
        except OSError:
            pass
    return gone


def _live(p):
    """A registered project folder still holds its project.yaml, or (``kind: work``) its work record."""
    d = p.get("dir") or ""
    if p.get("kind") == "work":
        return os.path.exists(os.path.join(d, ".vstudio", "work.json"))
    return os.path.exists(os.path.join(d, "project.yaml"))


class _RegistryLock:
    """projects.json is read, changed and written by every process that makes or runs a project: several projects
    started at once (the desk's autopilot) must not drop each other's row. One lock file next to it."""

    def __enter__(self):
        from vstudio import oscompat
        path = registry_path() + ".lock"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "a")  # noqa: SIM115
        oscompat.lock(self.f)
        return self

    def __exit__(self, *exc):
        from vstudio import oscompat
        oscompat.unlock(self.f)
        self.f.close()


def register(pdir, name=None, recipe=None, series=None, client=None, kind=None):
    with _RegistryLock():
        return _register(pdir, name, recipe, series, client, kind)


def _register(pdir, name=None, recipe=None, series=None, client=None, kind=None):
    """Add / update the projects.json row of ``pdir``. ``name``, ``recipe`` or ``kind`` passed as None keep the
    row's existing value, so a partial call never rewrites a project into something else (series / client are
    taken as given: project.yaml is their source). One exception: an old ``kind: work`` row whose folder now holds
    project.yaml, registered without a kind (vstudio.project.core), becomes a project row again."""
    from vstudio.batch.clients import is_temp_path
    pdir = os.path.abspath(pdir)
    if is_temp_path(pdir) and not is_temp_path(registry_path()):
        return dict(dir=pdir, name=name, recipe=recipe, series=series, client=client, registered=False)
    real = os.path.realpath(pdir)                    # /var/... and /private/var/... are one project
    rows = [p for p in projects() if os.path.realpath(p["dir"]) != real]
    old = next((p for p in projects() if os.path.realpath(p["dir"]) == real), {})
    keep = lambda k, v: old.get(k) if v is None else v  # noqa: E731
    row = dict(dir=pdir, name=keep("name", name), recipe=keep("recipe", recipe), series=series, client=client,
               created=old.get("created") or time.strftime("%Y-%m-%dT%H:%M:%S"))
    if kind is None and old.get("kind") == "work" and os.path.exists(os.path.join(pdir, "project.yaml")):
        kind = None
    else:
        kind = keep("kind", kind)
    if kind:
        row["kind"] = kind
    rows.append(row)
    write_json(registry_path(), rows)
    return rows[-1]


def unregister(pdir):
    real = os.path.realpath(pdir)
    with _RegistryLock():
        write_json(registry_path(), [p for p in projects() if os.path.realpath(p["dir"]) != real])


def live_projects():
    """Recipe projects (project.yaml) still on disk; work records (``kind: work``) are in ``live_works``."""
    return [p for p in projects() if p.get("kind") != "work" and _live(p)]


def live_works():
    return [p for p in projects() if p.get("kind") == "work" and _live(p)]


# --------------------------------------------------------------------------- series
class SeriesError(ValueError):
    pass


def series_root():
    return os.path.join(home(), "series")


def series_dir(sid):
    return os.path.join(series_root(), slug(sid))


def series_path(sid):
    return os.path.join(series_dir(sid), "series.yaml")


SERIES_KEYS = ("id", "name", "recipe", "params", "cadence", "accounts", "spec", "notes", "client", "auto")


def load_series(sid):
    p = series_path(sid)
    if not os.path.exists(p):
        raise SeriesError(f"no series {sid!r} ({p})")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_series(data):
    bad = [k for k in data if k not in SERIES_KEYS]
    if bad:
        raise SeriesError(f"unknown series keys {bad}; allowed: {', '.join(SERIES_KEYS)}")
    d = series_dir(data["id"])
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    with open(series_path(data["id"]), "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    return data


def new_series(sid, recipe, name=None, params=None, cadence=None, accounts=None, spec=None, client=None, notes=None):
    from . import manifests as M
    M.get(recipe)
    if os.path.exists(series_path(sid)):
        raise SeriesError(f"series {sid!r} exists (use `series update`)")
    return save_series(dict(id=slug(sid), name=name or sid, recipe=recipe, params=dict(params or {}),
                            cadence=dict(cadence or {}), accounts=list(accounts or []), spec=dict(spec or {}),
                            client=client, notes=notes))


def update_series(sid, patch):
    s = load_series(sid)
    for k, v in (patch or {}).items():
        if k in ("params", "cadence", "spec") and isinstance(v, dict):
            s[k] = dict(s.get(k) or {}, **v)
        else:
            s[k] = v
    return save_series(s)


def list_series():
    root = series_root()
    out = []
    if os.path.isdir(root):
        for d in sorted(os.listdir(root)):
            p = os.path.join(root, d, "series.yaml")
            if os.path.exists(p):
                s = load_series(d)
                s["projects"] = [x["dir"] for x in projects() if x.get("series") == s.get("id")]
                s["dir"] = os.path.join(root, d)
                out.append(s)
    return out


def series_view(sid):
    s = load_series(sid)
    s["dir"] = series_dir(sid)
    s["assets"] = os.path.join(s["dir"], "assets")
    s["projects"] = [x for x in projects() if x.get("series") == s.get("id")]
    return s
