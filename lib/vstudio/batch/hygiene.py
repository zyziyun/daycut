"""Storage hygiene: delete regenerable intermediates of finished jobs, keep hashes + small files; report disk use.

``clean`` removes, per stage, the files matching that stage's ``purge`` globs (cut / composed masters, the 16 kHz
wav, and - once a job is packaged - its exports, which the package folder hard-links) for jobs that are
approved / packaged / dropped / rejected. JSON (EDLs, transcripts, manifests, QC reports), covers, contact
sheets and snippets stay. Stage rows keep their keys and are marked ``purged``; if a later change needs a
purged output, the scheduler rebuilds it from the source (the keys tell it what to make).
Shared cache entries (one per source) are purged only when every job using them is finished.
"""
import glob
import os

from .run import load_recipe
from .store import Store
from .util import du, human

FINISHED = ("approved", "packaged", "dropped", "needs-replan")


def _purge_dir(d, patterns, dry):
    freed, gone = 0, []
    for pat in patterns:
        for f in glob.glob(os.path.join(d, pat)):
            if os.path.isfile(f):
                n = os.path.getsize(f)
                if not dry:
                    os.remove(f)
                freed += n
                gone.append(f)
    return freed, gone


def clean(batch_dir, dry_run=False):
    store = Store(batch_dir)
    try:
        recipe = load_recipe(store.spec)
        stages = {s.name: s for s in recipe.order()}
        jobs = store.jobs()
        done = {j["id"] for j in jobs if j["state"] in FINISHED}
        packaged = {j["id"] for j in jobs if j["state"] == "packaged"}
        freed, files = 0, 0
        shared_users = {}
        for jid, rows in store.all_stage_rows().items():
            for name, r in rows.items():
                st = stages.get(name)
                if st is None or not st.purge or r["state"] != "done":
                    continue
                if st.shared:
                    shared_users.setdefault((name, r["key"]), set()).add(jid)
                    continue
                if jid not in done:
                    continue
                pats = [p for p in st.purge if not p.startswith("exports/") or jid in packaged]
                d = os.path.join(store.dir, "jobs", jid, name)
                n, gone = _purge_dir(d, pats, dry_run)
                if gone and not dry_run:
                    out = dict(r["out"] or {}, purged=True)
                    store.set_stage(jid, name, out=out)
                freed += n
                files += len(gone)
        for (name, key), users in shared_users.items():
            if not users <= done:
                continue
            a = store.art(name, key)
            if not a:
                continue
            n, gone = _purge_dir(a["dir"], stages[name].purge, dry_run)
            freed += n
            files += len(gone)
        if not dry_run:
            store.log("clean", f"freed {human(freed)} in {files} file(s)")
        return dict(freed=freed, files=files, dry_run=dry_run, usage=usage(store.dir))
    finally:
        store.close()


def usage(batch_dir):
    parts = {k: du(os.path.join(batch_dir, k)) for k in ("cache", "jobs", "review", "package")}
    by_stage = {}
    jroot = os.path.join(batch_dir, "jobs")
    if os.path.isdir(jroot):
        for jid in os.listdir(jroot):
            jd = os.path.join(jroot, jid)
            for st in os.listdir(jd) if os.path.isdir(jd) else []:
                p = os.path.join(jd, st)
                if os.path.isdir(p):
                    by_stage[st] = by_stage.get(st, 0) + du(p)
    return dict(total=du(batch_dir), parts=parts, by_stage=by_stage)


def format_usage(u):
    lines = [f"batch folder: {human(u['total'])} (hard links counted once)"]
    lines += [f"  {k:8s} {human(v)}" for k, v in u["parts"].items()]
    if u["by_stage"]:
        lines.append("  jobs by stage: " + ", ".join(f"{k} {human(v)}" for k, v in sorted(u["by_stage"].items(),
                                                                                          key=lambda x: -x[1])))
    return "\n".join(lines)
