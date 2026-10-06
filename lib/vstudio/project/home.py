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
    keep = [p for p in rows if keep_entry(p["dir"], path, "project.yaml")]
    gone = [p for p in rows if p not in keep]
    if gone:
        try:
            write_json(path, keep)
        except OSError:
            pass
    return gone


def register(pdir, name=None, recipe=None, series=None, client=None):
    from vstudio.batch.clients import is_temp_path
    pdir = os.path.abspath(pdir)
    if is_temp_path(pdir) and not is_temp_path(registry_path()):
        return dict(dir=pdir, name=name, recipe=recipe, series=series, client=client, registered=False)
    rows = [p for p in projects() if os.path.abspath(p["dir"]) != pdir]
    old = next((p for p in projects() if os.path.abspath(p["dir"]) == pdir), {})
    rows.append(dict(dir=pdir, name=name, recipe=recipe, series=series, client=client,
                     created=old.get("created") or time.strftime("%Y-%m-%dT%H:%M:%S")))
    write_json(registry_path(), rows)
    return rows[-1]


def unregister(pdir):
    pdir = os.path.abspath(pdir)
    write_json(registry_path(), [p for p in projects() if os.path.abspath(p["dir"]) != pdir])


def live_projects():
    return [p for p in projects() if os.path.exists(os.path.join(p["dir"], "project.yaml"))]


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
