"""``plan``: spec -> jobs (+ variants) in the batch store, one isolated folder per job.

Sources are referenced read-only by absolute path (never copied). Re-running ``plan`` on an edited spec /
job list is a replan: new jobs are added, changed jobs go back to ``planned`` (only the stages whose inputs
changed re-run), jobs no longer listed become ``dropped``.
"""
import os

from . import planner as PL
from . import spec as S
from .run import load_recipe
from .store import Store
from .util import write_json

KEEP_STATES = ("packaged",)


def default_batch_dir(spec):
    return os.path.join(spec["_dir"], f"batch-{spec['name']}")


def _public_spec(spec):
    return {k: v for k, v in spec.items() if k not in ("jobs",)}


def plan_batch(spec_path, batch_dir=None, planner=None, overrides=None, sync=False, echo=True):
    spec = S.load_spec(spec_path, overrides)
    if planner:
        spec["planner"] = planner
    recipe = load_recipe(spec)
    bdir = os.path.abspath(batch_dir or spec.get("batch_dir") and os.path.join(spec["_dir"], spec["batch_dir"])
                           or default_batch_dir(spec))
    store = Store(bdir, create=True)
    try:
        rows = PL.get(spec.get("planner"), store, sync).rows(spec)
        if not rows and spec["recipe"] != "talkinghead-clips":
            raise ValueError("no jobs: give `segments:` (a job-list file) or inline `jobs:` in the spec")
        items = recipe.expand(spec, rows)
        jobs = S.apply_variants(spec, items)
        old = {j["id"]: j for j in store.jobs()}
        stats = dict(created=[], updated=[], unchanged=[], dropped=[])
        for k, j in enumerate(jobs):
            j = dict(j, recipe=spec["recipe"], ord=k)
            o = old.get(j["id"])
            if o is None:
                store.upsert_job(dict(j, state="planned"))
                stats["created"].append(j["id"])
            elif (o["params"] or {}) != j["params"] or o["state"] == "dropped":
                store.upsert_job(j)
                if o["state"] in KEEP_STATES and echo:
                    print(f"[plan] {j['id']} was already packaged; it is re-planned (package again afterwards)")
                store.set_job(j["id"], state="planned", review=None, review_reason=None, qc=None, qc_reasons=None,
                              sample=0)
                stats["updated"].append(j["id"])
            else:
                store.set_job(j["id"], ord=k)
                stats["unchanged"].append(j["id"])
            jd = os.path.join(bdir, "jobs", j["id"])
            os.makedirs(jd, exist_ok=True)
            write_json(os.path.join(jd, "job.json"), dict(id=j["id"], item=j["item"], variant=j["variant"],
                                                          recipe=spec["recipe"], params=j["params"]))
        new_ids = {j["id"] for j in jobs}
        for jid, o in old.items():
            if jid not in new_ids and o["state"] != "dropped":
                store.set_job(jid, state="dropped")
                stats["dropped"].append(jid)
        store.set_meta("spec", _public_spec(spec))
        if store.state() in (None, "planned", "ran") or not old:
            store.set_meta("state", "planned")
        store.log("plan", {k: len(v) for k, v in stats.items()})
        if echo:
            print(f"[plan] {bdir}: {len(jobs)} job(s) - " + ", ".join(f"{len(v)} {k}" for k, v in stats.items()))
        return dict(batch_dir=bdir, jobs=[j["id"] for j in jobs], **stats)
    finally:
        store.close()
