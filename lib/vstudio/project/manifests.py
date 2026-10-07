"""Recipe manifests: ``workflows/<name>/recipe.yaml``, validated against ``manifest.schema.json``.

    from vstudio.project import manifests as M
    M.all_manifests()          # {id: manifest}
    M.get("talkinghead")
    M.validate(manifest)       # -> [error strings] (JSON Schema + semantic checks)
    M.fmt("{item_dir}/edit.json", tctx)

A manifest declares inputs, how items are formed, params (JSON Schema with defaults / ranges / zh labels), the
stage graph (stage ids, resource class, outputs, preview artifact), checkpoints (human decisions with an answer
schema), outputs per platform and the agent hook (WORKFLOW.md). ``build.py`` turns it into a vstudio.batch Recipe.
"""
import glob
import json
import os
import re
from functools import lru_cache

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
WORKFLOWS = os.path.join(ROOT, "workflows")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "manifest.schema.json")
GATE_PREFIX = "cp_"


class ManifestError(ValueError):
    pass


def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def _yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def manifest_paths():
    return sorted(glob.glob(os.path.join(WORKFLOWS, "*", "recipe.yaml")) + glob.glob(os.path.join(WORKFLOWS, "*", "recipe.*.yaml")))


def load(path):
    m = _yaml(path)
    if not isinstance(m, dict):
        raise ManifestError(f"{path}: not a mapping")
    m["_path"] = os.path.abspath(path)
    format_defaults(m)
    return m


def format_defaults(m):
    """Params with ``x-format: <path>`` (``speed.body``, ``cover.aspect``) take their default from the recipe's
    ``vstudio.formats`` entry (persona ``formats.<id>`` merged) - one number for the pipeline, ``formats show``
    and ``vstudio.firstpass``. Such a param must not also hard-code a default."""
    props = (m.get("params") or {}).get("properties") or {}
    keyed = {k: sch for k, sch in props.items() if isinstance(sch, dict) and sch.get("x-format")}
    if not keyed:
        return m
    from vstudio import formats as F
    fid = F.canonical(m.get("id")) or F.canonical(m.get("workflow"))
    if not fid:
        raise ManifestError(f"{m.get('id')}: x-format params {sorted(keyed)} but no vstudio.formats entry for the "
                            f"recipe or workflow")
    f = F.get(fid)
    for k, sch in keyed.items():
        if "default" in sch:
            raise ManifestError(f"{m.get('id')}: params.{k} has both x-format and a default")
        v = f
        for part in sch["x-format"].split("."):
            if not isinstance(v, dict) or part not in v:
                raise ManifestError(f"{m.get('id')}: params.{k}: x-format {sch['x-format']!r} not in format {fid!r}")
            v = v[part]
        sch["default"] = v
    m["_format"] = fid
    return m


@lru_cache(maxsize=1)
def _cached():
    out = {}
    for p in manifest_paths():
        m = load(p)
        errs = validate(m)
        if errs:
            raise ManifestError(f"{p}: " + "; ".join(errs[:8]))
        out[m["id"]] = m
    return out


def all_manifests():
    return dict(_cached())


def reload():
    _cached.cache_clear()
    return all_manifests()


def get(rid):
    ms = _cached()
    if rid not in ms:
        raise KeyError(f"unknown recipe {rid!r}; known: {', '.join(sorted(ms))}")
    return ms[rid]


# --------------------------------------------------------------------------- validation
def _schema_errors(m):
    data = {k: v for k, v in m.items() if not k.startswith("_")}
    try:
        import jsonschema
    except ImportError:                                  # minimal fallback: required keys only
        req = schema()["required"]
        return [f"missing key {k!r}" for k in req if k not in data]
    v = jsonschema.Draft202012Validator(schema())
    return [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
            for e in sorted(v.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))]


def batch_recipe_names(m):
    br = (m.get("engine") or {}).get("batch_recipe")
    if not br:
        return []
    return [br] if isinstance(br, str) else list(dict.fromkeys(br["map"].values()))


def _param_default_errors(m):
    errs = []
    try:
        import jsonschema
    except ImportError:
        return errs
    for k, sch in ((m.get("params") or {}).get("properties") or {}).items():
        if "default" in sch:
            s = {kk: vv for kk, vv in sch.items() if not kk.startswith("x-")}
            try:
                jsonschema.validate(sch["default"], s)
            except jsonschema.ValidationError as e:
                errs.append(f"params.{k}: default {sch['default']!r} invalid: {e.message}")
    return errs


def validate(m, deep=True):
    """JSON Schema errors + semantic checks (unique ids, deps / after / blocks exist, from_batch stages exist in the
    engine's batch recipe, refs importable, files exist). [] = valid."""
    errs = _schema_errors(m)
    if errs:
        return errs
    errs += _param_default_errors(m)
    ids = [s["id"] for s in m["stages"]]
    if len(ids) != len(set(ids)):
        errs.append(f"duplicate stage ids: {sorted(i for i in ids if ids.count(i) > 1)}")
    if any(i.startswith(GATE_PREFIX) for i in ids):
        errs.append(f"stage ids may not start with {GATE_PREFIX!r} (reserved for checkpoint gates)")
    batch_stage_ids = set()
    if deep and batch_recipe_names(m):
        from vstudio.batch import recipes as RC
        for name in batch_recipe_names(m):
            try:
                batch_stage_ids |= {s.name for s in RC.get(name).stages}
            except KeyError as e:
                errs.append(str(e))
    known = set(ids) | batch_stage_ids
    for s in m["stages"]:
        if s.get("from_batch") and deep and s["id"] not in batch_stage_ids:
            errs.append(f"stage {s['id']}: from_batch but not a stage of {batch_recipe_names(m)}")
        for d in list(s.get("deps") or []) + list(s.get("extra_deps") or []):
            if d not in known:
                errs.append(f"stage {s['id']}: unknown dep {d!r}")
    cps = [c["id"] for c in m["checkpoints"]]
    if len(cps) != len(set(cps)):
        errs.append("duplicate checkpoint ids")
    for c in m["checkpoints"]:
        if c["after"] not in known:
            errs.append(f"checkpoint {c['id']}: after unknown stage {c['after']!r}")
        for b in list(c.get("blocks") or []) + list(c.get("needs") or []):
            if b not in known:
                errs.append(f"checkpoint {c['id']}: blocks unknown stage {b!r}")
        if c["kind"] in ("budget-approval", "consent") and c.get("auto", "never") != "never":
            errs.append(f"checkpoint {c['id']}: {c['kind']} must be auto: never")
        if c["kind"] == "author" and not c.get("author"):
            errs.append(f"checkpoint {c['id']}: kind author needs an `author` block")
        tpl = (c.get("author") or {}).get("template")
        if tpl and deep and not os.path.exists(os.path.join(ROOT, tpl)):
            errs.append(f"checkpoint {c['id']}: template {tpl} missing")
    if deep:
        wf = os.path.join(WORKFLOWS, m["workflow"])
        if not os.path.isdir(wf):
            errs.append(f"workflow folder {m['workflow']} missing")
        md = os.path.join(ROOT, m["agent"]["workflow_md"])
        if not os.path.exists(md):
            errs.append(f"agent.workflow_md {m['agent']['workflow_md']} missing")
        for ref in _refs(m):
            try:
                resolve_ref(ref)
            except Exception as e:  # noqa: BLE001
                errs.append(f"ref {ref}: {type(e).__name__}: {e}")
        for s in m["stages"]:
            for a in ((s.get("run") or {}).get("argv") or [])[:2]:
                if isinstance(a, str) and a.startswith("{workflow_dir}/"):
                    p = a.replace("{workflow_dir}", wf)
                    if not os.path.exists(p):
                        errs.append(f"stage {s['id']}: script {a} missing")
    inputs = {i["key"] for i in m["inputs"]}
    fi = m["items"].get("from_input")
    if fi and fi not in inputs:
        errs.append(f"items.from_input {fi!r} is not an input")
    return errs


def _refs(m):
    out = [m["outputs"]["collect"]]
    for s in m["stages"]:
        if s.get("fn"):
            out.append(s["fn"])
    for c in m["checkpoints"]:
        out += [c[k] for k in ("payload", "apply") if c.get(k)]
    return out


def resolve_ref(ref):
    from vstudio.batch.util import import_ref
    return import_ref(ref)


# --------------------------------------------------------------------------- templates
_TPL = re.compile(r"\{([A-Za-z_][\w.\-]*)(\*)?\}")


class Missing(KeyError):
    pass


def lookup(tctx, name):
    cur = tctx
    for part in name.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            raise Missing(name)
    return cur


def _s(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (list, tuple)):
        return ",".join(_s(x) for x in v)
    if isinstance(v, float) and v.is_integer():
        return str(v)
    return "" if v is None else str(v)


def fmt(text, tctx):
    """"{item_dir}/edit.json" -> the value; dotted names (``out.frames.sheet``, ``params.style``) walk dicts; a
    list renders comma-joined. Raises ``Missing`` for an unknown name."""
    if not isinstance(text, str):
        return text
    return _TPL.sub(lambda mo: _s(lookup(tctx, mo.group(1))), text)


def fmt_args(argv, tctx):
    """argv templates -> list of strings. ``"{x*}"`` alone expands a list into several args; ``{if: name, args}``
    keeps ``args`` only when ``name`` is set (non-empty, not false)."""
    out = []
    for a in argv:
        if isinstance(a, dict):
            try:
                v = lookup(tctx, a["if"])
            except Missing:
                v = None
            if v not in (None, "", False, [], 0):
                out += fmt_args(a["args"], tctx)
            continue
        if isinstance(a, str):
            mo = _TPL.fullmatch(a)
            if mo and mo.group(2):
                v = lookup(tctx, mo.group(1))
                out += [_s(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if _s(x)]
                continue
        out.append(fmt(str(a), tctx))
    return out


def label(m, lang="zh"):
    return (m.get("labels") or {}).get(lang) or m.get("id")


def param_defaults(m):
    return {k: v["default"] for k, v in (m["params"].get("properties") or {}).items() if "default" in v}


def param_scope(m, key):
    return ((m["params"].get("properties") or {}).get(key) or {}).get("x-scope", "project")
