"""Estimates (machine time, wall time, storage, API cost) from a small benchmark table, and the budget gate.

Benchmark table: seconds and output bytes per work unit (unit = seconds of media a stage processes, or 1 per
job for fixed-cost stages), per stage. Lookup order: this batch's ``bench`` table (measured here) -> the
machine table ``$VSTUDIO_CACHE/batch_bench.json`` (default ``~/.cache/vstudio/``, measured by earlier batches on
this machine; env VSTUDIO_BATCH_BENCH overrides the path) -> the built-in guesses below (``measured: false`` in the output). Every non-cached stage run
updates both (exponential moving average), so the second batch on a machine is estimated from real timings.

Wall time = max over resource classes of (that class's work / its concurrency limit): the slowest queue.
"""
import os
import shutil

from .util import human, hms, read_json, sha1_json, write_json

# Built-in guesses for an Apple-silicon laptop at 1080x1920 (replaced by measurements as soon as stages run).
DEFAULT_BENCH = {
    "probe": dict(sec_per_unit=1.0, bytes_per_unit=0.0),            # per source (content hash)
    "extract": dict(sec_per_unit=0.004, bytes_per_unit=32000.0),     # 16 kHz mono s16
    "asr": dict(sec_per_unit=0.06, bytes_per_unit=40.0),             # mlx whisper-large-v3-turbo
    "geometry": dict(sec_per_unit=0.02, bytes_per_unit=200.0),     # longform-split: geo frames + crop spans, per source s
    "cleanup": dict(sec_per_unit=0.03, bytes_per_unit=600.0),
    "apply": dict(sec_per_unit=0.35, bytes_per_unit=1.2e6),          # frame-exact cut, crf 14
    "compose": dict(sec_per_unit=0.25, bytes_per_unit=1.0e6),
    "export": dict(sec_per_unit=1.0, bytes_per_unit=0.9e6),          # per platform-second (reframe + encode + loudnorm)
    "verify": dict(sec_per_unit=0.06, bytes_per_unit=50.0),
    "qc": dict(sec_per_unit=0.15, bytes_per_unit=20.0),
    "preview": dict(sec_per_unit=3.0, bytes_per_unit=400000.0),      # per job
}
FALLBACK = dict(sec_per_unit=0.5, bytes_per_unit=1e5)
EMA = 0.3


def machine_bench_path():
    if os.environ.get("VSTUDIO_BATCH_BENCH"):
        return os.environ["VSTUDIO_BATCH_BENCH"]
    root = os.environ.get("VSTUDIO_CACHE") or os.path.join(os.path.expanduser("~"), ".cache", "vstudio")
    return os.path.join(root, "batch_bench.json")


def machine_bench():
    return read_json(machine_bench_path(), {}) or {}


def bench_table(store):
    """{stage: {sec_per_unit, bytes_per_unit, n, measured, source}}"""
    out = {k: dict(v, n=0, measured=False, source="default") for k, v in DEFAULT_BENCH.items()}
    for k, v in machine_bench().items():
        out[k] = dict(sec_per_unit=v["sec_per_unit"], bytes_per_unit=v.get("bytes_per_unit", 0.0), n=v.get("n", 1),
                      measured=True, source="machine")
    if store is not None:
        for k, r in store.bench().items():
            out[k] = dict(sec_per_unit=r["sec_per_unit"], bytes_per_unit=r["bytes_per_unit"] or 0.0, n=r["n"],
                          measured=True, source="batch")
    return out


def record(store, stage, resource, seconds, units, nbytes):
    """Fold one measured run into the batch + machine tables."""
    if not units or units <= 0:
        return
    spu, bpu = seconds / units, nbytes / units
    cur = store.bench().get(stage)
    if cur:
        n = cur["n"] + 1
        spu = (1 - EMA) * cur["sec_per_unit"] + EMA * spu
        bpu = (1 - EMA) * (cur["bytes_per_unit"] or 0) + EMA * bpu
    else:
        n = 1
    store.set_bench(stage, resource, spu, bpu, n)
    path = machine_bench_path()
    try:
        mb = machine_bench()
        m = mb.get(stage)
        if m:
            m = dict(sec_per_unit=(1 - EMA) * m["sec_per_unit"] + EMA * (seconds / units),
                     bytes_per_unit=(1 - EMA) * m.get("bytes_per_unit", 0) + EMA * (nbytes / units),
                     n=m.get("n", 1) + 1, resource=resource)
        else:
            m = dict(sec_per_unit=seconds / units, bytes_per_unit=nbytes / units, n=1, resource=resource)
        mb[stage] = m
        write_json(path, mb)
    except OSError:
        pass


PENDING_STATES = ("planned", "running", "interrupted", "failed")


def estimate(store, recipe, spec, limits, jobs=None, include_done=False):
    """Work still to do for ``jobs`` (default: every job not done / approved / packaged / dropped)."""
    from .run import stage_satisfied_rows
    bench = bench_table(store)
    if jobs is None:
        jobs = store.jobs(None if include_done else PENDING_STATES)
    rows = store.all_stage_rows()
    per_stage, per_res = {}, {}
    seen_shared = set()
    if not include_done:                                  # shared outputs already made for some job are free
        shared = [st for st in recipe.order() if st.shared]
        for j in store.jobs():
            jj = dict(id=j["id"], params=j["params"], recipe=j["recipe"])
            for st in shared:
                r = rows.get(j["id"], {}).get(st.name)
                if r and r["state"] == "done":
                    seen_shared.add((st.name, sha1_json(st.params(jj, spec))))
    cost = storage = 0.0
    for j in jobs:
        jj = dict(id=j["id"], params=j["params"], recipe=j["recipe"])
        done = stage_satisfied_rows(rows.get(j["id"], {}))
        for st in recipe.order():
            if not st.enabled(jj, spec) or st.name in done and not include_done:
                continue
            if st.shared:
                sk = (st.name, sha1_json(st.params(jj, spec)))
                if sk in seen_shared:
                    continue
                seen_shared.add(sk)
            u = float(st.units(jj, spec) or 0.0)
            b = bench.get(st.name, FALLBACK)
            sec = u * b["sec_per_unit"]
            res = st.resource_of(jj, spec)
            ps = per_stage.setdefault(st.name, dict(units=0.0, seconds=0.0, bytes=0.0, n=0, resource=res,
                                                    measured=b.get("measured", False)))
            ps["units"] += u
            ps["seconds"] += sec
            ps["bytes"] += u * b["bytes_per_unit"]
            ps["n"] += 1
            per_res[res] = per_res.get(res, 0.0) + sec
            storage += u * b["bytes_per_unit"]
            cost += float(st.cost(jj, spec) or 0.0)
    wall = 0.0
    for res, sec in per_res.items():
        lim = limits.get(res) or (limits.get("api:*") if res.startswith("api:") else None) or 1
        wall = max(wall, sec / lim)
    planner_cost = float((spec.get("planner_opts") or {}).get("est_usd", 0.0)) if spec.get("planner") == "claude" else 0.0
    cost += planner_cost
    spent = sum(float(j.get("cost") or 0) for j in store.jobs())
    try:
        free = shutil.disk_usage(store.dir).free
    except OSError:
        free = None
    est = dict(jobs=len(jobs), stages=per_stage, resources=per_res, machine_s=sum(per_res.values()), wall_s=wall,
               storage_bytes=storage, api_usd=round(cost, 4), spent_usd=round(spent, 4), free_bytes=free,
               limits=limits)
    est["budget"] = check_budget(est, spec.get("budget") or {})
    return est


def check_budget(est, budget):
    over = []
    if budget.get("max_usd") is not None and est["api_usd"] + est["spent_usd"] > float(budget["max_usd"]):
        over.append(f"API cost ${est['api_usd'] + est['spent_usd']:.2f} > max_usd ${float(budget['max_usd']):.2f}")
    if budget.get("max_hours") is not None and est["wall_s"] / 3600.0 > float(budget["max_hours"]):
        over.append(f"wall time {est['wall_s'] / 3600:.2f} h > max_hours {budget['max_hours']}")
    if budget.get("max_storage_gb") is not None and est["storage_bytes"] / 1e9 > float(budget["max_storage_gb"]):
        over.append(f"storage {est['storage_bytes'] / 1e9:.2f} GB > max_storage_gb {budget['max_storage_gb']}")
    if est.get("free_bytes") is not None and est["storage_bytes"] > est["free_bytes"]:
        over.append(f"storage {human(est['storage_bytes'])} > free disk {human(est['free_bytes'])}")
    return dict(ok=not over, over=over, budget=budget)


def format_estimate(est):
    lines = [f"jobs to run: {est['jobs']}"]
    lines.append(f"{'stage':10s} {'resource':12s} {'units':>9s} {'machine':>9s} {'storage':>9s}  bench")
    for name, s in est["stages"].items():
        lines.append(f"{name:10s} {s['resource']:12s} {s['units']:9.0f} {hms(s['seconds']):>9s} "
                     f"{human(s['bytes']):>9s}  {'measured' if s['measured'] else 'guess'}")
    lines.append("per resource (work / limit): " + ", ".join(
        f"{r} {hms(sec)}/{est['limits'].get(r, est['limits'].get('api:*', 1))}" for r, sec in est["resources"].items()))
    lines.append(f"machine time {hms(est['machine_s'])}, wall time ~{hms(est['wall_s'])}, "
                 f"storage +{human(est['storage_bytes'])} (free {human(est['free_bytes'])}), "
                 f"API ${est['api_usd']:.2f} (spent ${est['spent_usd']:.2f})")
    b = est["budget"]
    lines.append("budget: OK" if b["ok"] else "budget: OVER - " + "; ".join(b["over"]))
    return "\n".join(lines)
