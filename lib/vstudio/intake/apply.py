"""`intake apply`: an (edited) plan -> vstudio.project projects, ready to run (pilot first).

    res = apply_plan(plan, out_dir)      # {ok, dir, series, projects [{id, recipe, dir, items, run}], next}

One sub-project = one project folder ``<out>/<NN>-<name>/`` (``project.yaml`` + the agent hook files) created with
``vstudio.project.core.Project.create``; a plan with several sub-projects also gets a **series** (grouping the
projects in the desk app's lanes / inbox) and ``<out>/intake.json`` (the plan as applied + the project dirs).
A focus sub-project whose ranges are still unresolved is resolved here (full transcript, cached) before creation;
planner recipes without rows keep their segment planner (``run`` plans the items, the segments checkpoint asks).
Nothing runs unless ``run=True`` (then: ``Project.run(pilot=N)`` per project - exit 4 waits for the pilot review).
"""
import json
import os
import sys
import time

from vstudio.batch.util import slug
from vstudio.project import home as H
from vstudio.project import manifests as M
from vstudio.project.core import Project, ProjectError

from . import inventory as I
from . import plan as PL
from . import rules as R


class ApplyError(ValueError):
    pass


def default_out(plan):
    from vstudio.batch.clients import home
    return os.path.join(home(), "projects", plan.get("id") or time.strftime("%Y%m%d-%H%M%S"))


def _resolve_unresolved(plan, echo=None):
    todo = [p for p in plan["projects"] if (p.get("items") or {}).get("unresolved")]
    if not todo:
        return []
    srcs = []
    for p in todo:
        m = M.get(p["recipe"])
        fi = m["items"].get("from_input") or "source"
        s = PL._first_path(p["inputs"].get(fi) or p["inputs"].get("source"))
        if s:
            srcs.append(s)
    warn = []
    analysis = I.analyze(srcs, asr="full", echo=echo)
    intent = R.parse_prompt(plan["prompt"] + "\n" + "\n".join(r["prompt"] for r in plan.get("revisions") or []))
    for p in todo:
        PL.resolve_focus(p, analysis, intent, warn)
    return warn


def _create_kwargs(p, plan):
    m = M.get(p["recipe"])
    fi = m["items"].get("from_input")
    items = p.get("items") or {}
    ins = {k: v for k, v in (p.get("inputs") or {}).items()}
    rows = [dict(id=r.get("id"), inputs=dict(r.get("inputs") or {}), params=dict(r.get("params") or {}))
            for r in items.get("rows") or []]
    kw = dict(recipe=p["recipe"], name=p.get("name"), params=dict(p.get("params") or {}), client=plan.get("client"),
              auto=list(p.get("auto") or (plan.get("run") or {}).get("auto") or []))
    if rows:
        if fi and fi in ins and all(fi in r["inputs"] for r in rows):
            ins.pop(fi)
        kw["items"] = rows
    elif items.get("method") == "episodes" and items.get("count"):
        kw["episodes"] = int(items["count"])
    elif items.get("method") == "focus" and not m["items"].get("planner"):
        raise ApplyError(f"{p['id']} ({p['recipe']}): the focus ranges are unresolved - re-run `intake plan` "
                         f"(it transcribes the source) or add items.rows with a range")
    kw["inputs"] = ins
    return kw


def apply_plan(plan, out_dir=None, run=False, dry_run=False, echo=None, on_event=None, autopilot=False):
    """``autopilot``: each project is created on autopilot (project.yaml ``autopilot.on``): its run has no pilot stop
    and answers every checkpoint itself (vstudio.project.autopilot); the ``run`` commands say ``--autopilot``."""
    errs = PL.validate(plan)
    if errs:
        raise ApplyError("plan invalid: " + "; ".join(errs[:8]))
    if not plan.get("projects"):
        raise ApplyError("the plan has no sub-projects")
    warn = _resolve_unresolved(plan, echo) if not dry_run else []
    out_dir = os.path.abspath(os.path.expanduser(out_dir or default_out(plan)))
    created, series = [], None
    plans = []
    for k, p in enumerate(plan["projects"]):
        d = os.path.join(out_dir, f"{k + 1:02d}-{slug(p.get('name') or p['recipe'])[:40]}")
        plans.append((p, d, _create_kwargs(p, plan)))
    if dry_run:
        return dict(ok=True, dry_run=True, dir=out_dir, projects=[dict(id=p["id"], recipe=p["recipe"], dir=d,
                                                                        create={k: v for k, v in kw.items()})
                                                                   for p, d, kw in plans], warnings=warn)
    os.makedirs(out_dir, exist_ok=True)
    ser = plan.get("series")
    if ser and len(plan["projects"]) > 1:
        sid = slug(ser.get("id") or plan.get("id") or "intake")
        try:
            H.new_series(sid, plan["projects"][0]["recipe"], name=ser.get("name") or sid, client=plan.get("client"),
                         notes=f"intake: {plan.get('prompt', '')[:200]} (mixed recipes: "
                               f"{', '.join(dict.fromkeys(p['recipe'] for p in plan['projects']))})")
        except H.SeriesError:
            pass                                       # re-apply of the same plan: the series exists
        series = sid
    for p, d, kw in plans:
        try:
            pr = Project.create(d, series=series, exist_ok=False, **kw)
        except ProjectError as e:
            if "already holds a project" in str(e):
                pr = Project(d)
                warn.append(f"{p['id']}: {d} already holds a project (kept as is)")
            else:
                raise ApplyError(f"{p['id']} ({p['recipe']}): {e}") from e
        if autopilot:
            from vstudio.project import autopilot as APL
            APL.configure(pr, on=True, lang=plan.get("ui_lang"))
            if plan.get("prompt") and not pr.data.get("prompt"):
                pr.data["prompt"] = plan["prompt"][:2000]          # what the AI judge decides for
                pr.save()
        how = ["--autopilot"] if autopilot else ["--pilot", str((plan.get("run") or {}).get("pilot") or 1)]
        entry = dict(id=p["id"], recipe=p["recipe"], name=pr.data.get("name"), dir=pr.dir,
                     items=[i["id"] for i in pr.data["items"]], planner_pending=not pr.data["items"],
                     run=[sys.executable, "-m", "vstudio.project", "run", "--dir", pr.dir, *how, "--json-events"])
        if run:
            res = pr.run(pilot=None if autopilot else (plan.get("run") or {}).get("pilot") or 1, on_event=on_event)
            entry["result"] = {k: res.get(k) for k in ("status", "exit_code", "pending", "items")}
        created.append(entry)
    applied = dict(plan, applied=dict(at=time.strftime("%Y-%m-%dT%H:%M:%S"), dir=out_dir, series=series,
                                      projects=[dict(id=c["id"], dir=c["dir"]) for c in created]))
    with open(os.path.join(out_dir, "intake.json"), "w", encoding="utf-8") as f:
        json.dump(applied, f, ensure_ascii=False, indent=1)
    nxt = [" ".join(c["run"][1:]) for c in created]
    return dict(ok=True, dir=out_dir, series=series, plan=os.path.join(out_dir, "intake.json"), projects=created,
                warnings=warn, next=nxt)
