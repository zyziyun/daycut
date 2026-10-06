"""The inbox ("needs you"): every pending checkpoint across all registered projects, one entry per (project,
checkpoint, item) - project-scope checkpoints (e.g. an AIGC budget) once per project with the item payloads
aggregated - plus bulk groups (``batch_by``: filler confirms grouped by edit kind across items and projects).

    inbox()                                  -> {entries [...], groups [...], counts {...}}
    answer(project, cid, value, items=None)  -> the project's answer result
    answer_bulk(entries, value | use_default) -> resolve many at once (same checkpoint id per project)
"""
import os

from .core import Project, ProjectError, _brief_pending
from . import home as H


def _entry(p, pay):
    e = _brief_pending(pay)
    e.update(project_name=pay.get("project_name"), recipe=pay.get("recipe"), options=pay.get("options") or [],
             previews=pay.get("previews") or [], answer_schema=pay.get("answer_schema"), auto=pay.get("auto"),
             batch_by=pay.get("batch_by"), help=pay.get("help"))
    for k in ("exports", "qc", "copy", "file", "exists", "content", "estimate", "kinds"):
        if k in pay:
            e[k] = pay[k]
    return e


def collect(projects=None):
    rows = []
    errors = []
    for reg in projects if projects is not None else H.live_projects():
        d = reg["dir"] if isinstance(reg, dict) else reg
        try:
            p = Project(d)
            pend = p.pending()
        except Exception as e:  # noqa: BLE001  (a broken project never hides the others)
            errors.append(dict(project=d, error=f"{type(e).__name__}: {e}"))
            continue
        scoped = {}
        for pay in pend:
            if pay.get("scope") == "project":
                scoped.setdefault(pay["id"], []).append(pay)
            else:
                rows.append(_entry(p, pay))
        for cid, pays in scoped.items():
            e = _entry(p, pays[0])
            e["item"] = "*"
            e["items"] = [x["item"] for x in pays]
            agg = {}
            for f in pays[0].get("aggregate") or []:
                agg[f] = round(sum(float(x.get(f) or 0) for x in pays), 4)
            e["aggregate"] = agg
            e["per_item"] = [{k: x.get(k) for k in ["item"] + list(pays[0].get("aggregate") or [])} for x in pays]
            rows.append(e)
    return rows, errors


def groups(entries):
    """Bulk groups: same recipe + checkpoint kind (+ the ``batch_by`` key of each option, e.g. filler kinds)."""
    out = {}
    for e in entries:
        key = (e["recipe"], e["id"], e["kind"])
        g = out.setdefault(key, dict(recipe=e["recipe"], id=e["id"], kind=e["kind"], labels=e["labels"], entries=[],
                                     by={}))
        g["entries"].append(dict(project=e["project"], item=e["item"]))
        if e.get("batch_by"):
            for o in e.get("options") or []:
                v = o.get(e["batch_by"])
                if v is not None:
                    g["by"].setdefault(str(v), []).append(dict(project=e["project"], item=e["item"], option=o.get("id")))
    res = []
    for g in out.values():
        g["n"] = len(g["entries"])
        g["by"] = [dict(value=k, n=len(v), refs=v) for k, v in sorted(g["by"].items(), key=lambda kv: -len(kv[1]))]
        res.append(g)
    return sorted(res, key=lambda g: -g["n"])


def inbox(projects=None):
    entries, errors = collect(projects)
    counts = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return dict(entries=entries, groups=groups(entries), counts=counts, total=len(entries), errors=errors)


def answer(project, cid, value, items=None, run=False):
    return Project(project).answer(cid, value, items=items, run=run)


def answer_bulk(cid=None, kind=None, value=None, use_default=False, projects=None, items=None, run=False):
    """Answer every pending entry matching (checkpoint id and/or kind, optional projects / items) with ``value``
    or each entry's own default. Budget / consent are never answered with a default."""
    if not cid and not kind:
        raise ProjectError("bulk answer: give --id and/or --kind")
    entries, _ = collect([dict(dir=os.path.abspath(p)) for p in projects] if projects else None)
    picked = [e for e in entries if (not cid or e["id"] == cid) and (not kind or e["kind"] == kind)
              and (not items or e["item"] in items)]
    done, skipped = [], []
    by_proj = {}
    for e in picked:
        by_proj.setdefault((e["project"], e["id"]), []).append(e)
    for (proj, c), es in by_proj.items():
        p = Project(proj)
        cp = p.checkpoint(c)
        for e in es:
            v = value
            if use_default:
                if cp["kind"] in ("budget-approval", "consent"):
                    skipped.append(dict(project=proj, item=e["item"], id=c, why="never answered with a default"))
                    continue
                v = e.get("default")
                if v is None:
                    skipped.append(dict(project=proj, item=e["item"], id=c, why="no default"))
                    continue
            try:
                r = p.answer(c, v, items=None if e["item"] == "*" else [e["item"]])
                done.append(dict(project=proj, item=e["item"], id=c, rerun=r.get("rerun")))
            except ProjectError as ex:
                skipped.append(dict(project=proj, item=e["item"], id=c, why=str(ex)))
        if run:
            p.run()
    return dict(ok=not skipped or bool(done), answered=done, skipped=skipped)
