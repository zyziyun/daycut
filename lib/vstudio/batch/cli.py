"""python -m vstudio.batch - batch video production (Fleet F0). See references/BATCH.md.

  plan SPEC [--batch DIR] [--planner file|claude] [--segments F] [--sync] [--json]   spec -> jobs, replan
  estimate [--batch DIR] [--json]                       machine / wall time, storage, API cost vs budget
  run [--batch DIR] [--pilot N] [--confirm-pilot] [--resume] [--retry-failed] [--jobs a,b]
      [--concurrency asr=1,cpu-render=2] [--json-events]   run the stage DAGs (resumable; refuses over budget)
  status [--batch DIR] [--json] [--events N]            terminal table
  review [--batch DIR] [--apply decisions.json|JSON] [--confirm-kinds a,b] [--accept-policy] [--jobs a,b]
         [--approve-green] [--json]
                                                        HTML grid + decisions sheet / ingest (+ bulk answers)
  job ID [--batch DIR] [--json] [--no-words]            one job: transcript + cleanup edits, captions, QC, exports
  package [--batch DIR] [--per-day N] [--start YYYY-MM-DD] [--times 12:00,19:00] [--json]   publish folders
  verify-manifest MANIFEST                              recompute a package's confirmation code (JSON)
  clean [--batch DIR] [--dry-run]                       delete regenerable intermediates of finished jobs
  du [--batch DIR]                                      disk use of the batch folder
  bench [--batch DIR]                                   the benchmark table used by estimate
  recipes [--json]                                      registered recipes (--json: labels, inputs, row keys)
v0.2 (desk; all with --json):
  plan-segments --source F [--transcript T] [--client C] [--count N] [--min S --max S] [--platforms a,b]
      [--provider auto|claude|openai|ollama|claude-code|...|none] [--out DIR]      transcript -> candidate segments -> segments.draft.yaml
  client init|show|update|list --client C [--set JSON]  client.yaml layered over the persona (effective config)
  job show ID | job edit --job J --op caption|trim|cut|notes|hook|cover|copy|undo ... | job rerun --job J [--json-events]
  deliver [--client C] [--zip] [--cleanup-days N] [--out DIR]   client delivery package + manifest hash
  cleanup-sources [--batch B | --client C | --all] [--confirm-delete CODE]   list (dry run + code) / delete exactly
                                                                that list; sources outside the batch folder: report only
  metrics --batch B | --client C | --all [--csv]        metrics JSON / weekly CSV
  timing --job J --event start|stop|add --what review [--seconds S]   review timing -> batch store
--json: one JSON document on stdout (paths absolute); run --json-events: one JSON event per line on stdout
(the human log goes to stderr). See references/BATCH.md section 7.
--batch defaults to the current folder when it holds batch.db.
Exit codes (run): 0 ok, 1 some jobs failed, 2 refused over budget, 3 paused (circuit breaker), 4 pilot waits.
"""
import argparse
import json
import os
import sys
import threading

from . import estimate as EST
from . import hygiene, review
from .store import DB_NAME, Store
from .util import human


def _batch(a):
    if a.batch:
        return a.batch
    if os.path.exists(DB_NAME):
        return os.getcwd()
    sys.exit("no batch here: pass --batch DIR (the folder `plan` printed) or cd into it")


def cmd_plan(a):
    from .plan import plan_batch
    ov = {}
    if a.segments:
        ov["segments"] = os.path.abspath(a.segments)
    if a.recipe:
        ov["recipe"] = a.recipe
    if a.source:
        ov["inputs"] = {"source": os.path.abspath(a.source)}
    from .planner import PlannerUnavailable
    try:
        r = plan_batch(a.spec, a.batch, a.planner, ov, sync=a.sync, echo=not a.json)
    except PlannerUnavailable as e:
        if a.json:
            _out(dict(ok=False, error=str(e), code=5))
        else:
            print(f"[plan] {e}")
        return 5
    if a.json:
        _out(dict(ok=True, **r))
    else:
        print(f"next: python -m vstudio.batch estimate --batch {r['batch_dir']}")
    return 0


def _out(obj):
    """The --json document: always on the real stdout (other prints are on stderr while --json is set)."""
    out = sys.__stdout__ or sys.stdout
    out.write(json.dumps(obj, ensure_ascii=False, indent=1, default=str) + "\n")
    out.flush()


def cmd_estimate(a):
    from .run import load_recipe, resolve_limits
    st = Store(_batch(a))
    try:
        spec = st.spec
        est = EST.estimate(st, load_recipe(spec), spec, resolve_limits(spec))
    finally:
        st.close()
    if a.json:
        print(json.dumps(est, indent=1, default=str))
    else:
        print(EST.format_estimate(est))
    return 0 if est["budget"]["ok"] else 2


def json_event_sink():
    """stdout becomes a pure JSON-lines channel: the real fd 1 is kept for the events, and fd 1 itself is pointed
    at stderr so every other print (stage code, libraries, child processes) lands on stderr."""
    sys.stdout.flush()
    fd = os.dup(1)
    os.dup2(2, 1)
    stream = os.fdopen(fd, "w", buffering=1, encoding="utf-8")
    lock = threading.Lock()

    def emit(ev):
        line = json.dumps(ev, ensure_ascii=False, default=str)
        with lock:
            stream.write(line + "\n")
            stream.flush()
    return emit, stream


def cmd_run(a):
    from .run import BatchBusy, parse_limits, run_batch
    only = set(x.strip() for x in a.jobs.split(",")) if a.jobs else None
    emit, stream = json_event_sink() if a.json_events else (None, None)
    try:
        r = run_batch(_batch(a), pilot=a.pilot, limits=parse_limits(a.concurrency), confirm_pilot=a.confirm_pilot,
                      resume=a.resume, retry_failed=a.retry_failed, only=only, on_event=emit)
    except BatchBusy as e:
        if emit:
            emit(dict(event="run-end", status="busy", exit_code=6, error=str(e)))
        else:
            print(f"[batch] {e}")
        return 6
    if r["status"] in ("done", "done-with-failures", "pilot-review"):
        print(f"next: python -m vstudio.batch review --batch {_batch(a)}", file=sys.stderr if emit else sys.stdout)
    if stream:
        stream.flush()
    return r["exit_code"]


LIGHT = {"green": "GREEN", "red": "RED", None: "-"}
# v0.2 commands, as the desk probes them (`recipes --json` -> capabilities)
CAPABILITIES = ("plan-segments", "client", "job-edit", "job-rerun", "deliver", "metrics", "timing", "job-undo",
                "cleanup-sources", "recipe:podcast-clips", "recipe:talkinghead-folder")


def status_rows(store):
    from .run import load_recipe, runner_active
    spec = store.spec
    live = runner_active(store.dir)
    try:
        n_st = len(load_recipe(spec).order())
    except Exception:  # noqa: BLE001
        n_st = 0
    rows = []
    all_rows = store.all_stage_rows()
    for j in store.jobs():
        sr = all_rows.get(j["id"], {})
        done = sum(r["state"] in ("done", "skipped") for r in sr.values())
        cur = next((k for k, r in sr.items() if r["state"] == "running"), None) or \
            next((k for k, r in sr.items() if r["state"] == "failed"), None) or \
            next((k for k, r in sr.items() if r["state"] == "pending" and (r["not_before"] or 0) > 0), None)
        cm = (sr.get("compose") or {}).get("out") or {}
        qr = j["qc_reasons"] if isinstance(j["qc_reasons"], dict) else {}
        note = j["review_reason"] or ((qr.get("red") or [""])[0]) or ""
        state = j["state"]
        if state == "running" and not live:            # the run that owned it died (kill -9, power loss)
            state = "interrupted"
            cur = None if cur and sr.get(cur, {}).get("state") == "running" else cur
        rows.append(dict(id=j["id"], state=state, progress=f"{done}/{n_st}", stage=cur or "",
                         qc=j["qc"], sample=bool(j["sample"]), pilot=bool(j["pilot"]), review=j["review"] or "",
                         duration=cm.get("duration"), cost=j["cost"] or 0.0, note=note))
    return rows


def cmd_status(a):
    st = Store(_batch(a))
    try:
        rows = status_rows(st)
        from .run import runner_active
        state = st.state()
        if state == "running" and not runner_active(st.dir):
            state = "interrupted"
        meta = dict(name=st.spec.get("name"), recipe=st.spec.get("recipe"), state=state,
                    pause_reason=st.meta("pause_reason"), package=st.meta("package"))
        ev = st.events(a.events) if a.events else []
    finally:
        st.close()
    if a.json:
        print(json.dumps(dict(meta=meta, jobs=rows), ensure_ascii=False, indent=1, default=str))
        return 0
    print(f"batch {meta['name']} ({meta['recipe']}) - state {meta['state']}"
          + (f" - PAUSED: {meta['pause_reason']}" if meta["state"] == "paused" else ""))
    hdr = f"{'job':24s} {'state':13s} {'stages':7s} {'at':9s} {'qc':6s} {'dur':>6s} {'review':9s} {'$':>6s}  note"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        qc = LIGHT.get(r["qc"], r["qc"] or "-") + ("*" if r["sample"] else "")
        dur = f"{r['duration']:.1f}" if r["duration"] else "-"
        print(f"{r['id'][:24]:24s} {r['state'][:13]:13s} {r['progress']:7s} {r['stage'][:9]:9s} {qc:6s} "
              f"{dur:>6s} {r['review'][:9]:9s} "
              f"{r['cost']:6.2f}  {r['note'][:60]}")
    counts = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print("-" * len(hdr))
    print("  ".join(f"{k}: {v}" for k, v in counts.items())
          + f"   green {sum(r['qc'] == 'green' for r in rows)}, red {sum(r['qc'] == 'red' for r in rows)}, "
            f"sampled for review (*) {sum(r['sample'] for r in rows)}")
    if meta["package"]:
        print(f"package: {meta['package']['items']} posts, confirmation code {meta['package']['code']}")
    for e in ev:
        print(f"  {e['kind']:7s} {e['job'] or '':20s} {e['stage'] or '':9s} {e['msg'][:90]}")
    return 0


def cmd_review(a):
    b = _batch(a)
    if a.apply or a.confirm_kinds or a.accept_policy:
        dec = (json.loads(a.apply) if a.apply.lstrip().startswith("{") else a.apply) if a.apply else {}
        if a.confirm_kinds or a.accept_policy:
            dec = dict(review.read_json(dec) if isinstance(dec, str) else dec)
            if a.confirm_kinds:
                dec["confirm_kinds"] = [k.strip() for k in a.confirm_kinds.split(",") if k.strip()]
            if a.accept_policy:
                dec["accept_policy"] = True
        if a.jobs:
            dec = dict(review.read_json(dec) if isinstance(dec, str) else dec)
            dec["jobs"] = [j.strip() for j in a.jobs.split(",") if j.strip()]
        r = review.apply_decisions(b, dec)
        if a.json:
            _out(dict(ok=True, approved=r["approved"], rejected=r["rejected"], replied=r["replied"],
                      bulk=r["bulk"], learned=r["learned"], skipped=[dict(job=j, why=w) for j, w in r["skipped"]],
                      jobs=sorted(dec["jobs"]) if isinstance(dec, dict) and dec.get("jobs") else None))
            return 0
        print(f"[review] approved {len(r['approved'])}, rejected -> needs-replan {len(r['rejected'])}, "
              f"cleanup replies {len(r['replied'])} (re-run: `run`)" +
              (f"; bulk-confirmed {sum(len(v) for v in r['bulk'].values())} edit(s) in {len(r['bulk'])} job(s)"
               if r["bulk"] else "") + (f"; {r['learned']} answer(s) learned" if r["learned"] else ""))
        for jid, why in r["skipped"]:
            print(f"  skipped {jid}: {why}")
        return 0
    if a.approve_green:
        st = Store(b)
        try:
            ok = [j["id"] for j in st.jobs(("done",)) if j["qc"] == "green" and not j["sample"]]
        finally:
            st.close()
        r = review.apply_decisions(b, {"decisions": {j: {"decision": "approve"} for j in ok}})
        if not a.json:
            print(f"[review] approved {len(r['approved'])} green, unsampled job(s); red + sampled ones still need you")
    r = review.generate(b)
    if a.json:
        from . import api
        _out(dict(r, batch_dir=os.path.abspath(b), items=api.review_items(b)))
        return 0
    pt = r.get("policy") or {}
    print(f"[review] {r['page']}  ({r['jobs']} jobs, {r['red']} red, {r['sampled']} sampled; "
          f"{r['confirm_edits']} cleanup edits to confirm in {r['confirm_jobs']} jobs -> {r['decisions_needed']})")
    if pt.get("auto") or pt.get("keep"):
        print(f"[review] confirm policy answered {pt['auto'] + pt['keep']} question(s): {pt['auto']} cut, {pt['keep']} kept"
              + (f"; {pt['pending']} cut(s) not rendered yet (`review --accept-policy`, or `run --jobs <ids>` re-runs cleanup)" if pt["pending"] else ""))
    if r.get("caption_guesses"):
        print(f"[review] {r['caption_guesses']} caption fix(es) are guesses: marked yellow, look at them")
    print(f"then: python -m vstudio.batch review --batch {b} --apply <downloaded decisions.json>")
    return 0


def cmd_package(a):
    from .package import package
    times = [t.strip() for t in a.times.split(",")] if a.times else None
    r = package(_batch(a), out=a.out, per_day=a.per_day, start=a.start, times=times)
    if a.json:
        from .api import verify_manifest
        from .util import read_json
        man = read_json(r["manifest"])
        _out(dict(r, manifest_data=man, verify=verify_manifest(man)))
        return 0
    print(f"[package] {r['items']} posts from {r['jobs']} jobs -> {r['dir']}")
    print(f"confirmation code: {r['code']}  (manifest: {r['manifest']}; nothing was uploaded)")
    return 0


def cmd_clean(a):
    r = hygiene.clean(_batch(a), dry_run=a.dry_run)
    print(f"[clean] {'would free' if a.dry_run else 'freed'} {human(r['freed'])} in {r['files']} file(s)")
    print(hygiene.format_usage(r["usage"]))
    return 0


def cmd_du(a):
    print(hygiene.format_usage(hygiene.usage(os.path.abspath(_batch(a)))))
    return 0


def cmd_bench(a):
    st = Store(_batch(a)) if (a.batch or os.path.exists(DB_NAME)) else None
    try:
        t = EST.bench_table(st)
    finally:
        if st:
            st.close()
    print(f"{'stage':10s} {'s/unit':>9s} {'bytes/unit':>11s} {'n':>4s}  source")
    for k, v in t.items():
        print(f"{k:10s} {v['sec_per_unit']:9.4f} {human(v['bytes_per_unit']):>11s} {v.get('n', 0):4d}  {v['source']}")
    print(f"machine table: {EST.machine_bench_path()}")
    return 0


def _fail(a, e, code=1):
    if getattr(a, "json", False):
        _out(dict(ok=False, error=str(e)))
    else:
        print(f"[{a.cmd}] {e}", file=sys.stderr)
    return code


def cmd_job_edit(a):
    from . import edits as ED
    args = {k: getattr(a, k) for k in ("cue", "text", "start", "end", "pick", "t", "title", "body", "tags", "why", "set")
            if getattr(a, k, None) is not None}
    if getattr(a, "reasr", False):
        args["reasr"] = True
    try:
        r = ED.edit(_batch(a), a.job, a.op, **args)
    except (KeyError, ValueError) as e:
        return _fail(a, e)
    if a.json:
        _out(r)
        return 0 if r["ok"] else 1
    if not r["ok"]:
        print(f"[job edit] refused ({r.get('reason_code') or 'refused'}): {r.get('reason')}"
              + (f"\n  heard: {r['heard']}" if r.get("heard") else ""))
        return 1
    print(f"[job edit] {a.job} {a.op} ok; stale: {', '.join(r['rerun']) or 'nothing'}; pending: "
          f"{', '.join(r['pending']) or 'nothing'}" + (f"; glossary +{len(r['glossary_added'])}"
                                                      if r.get("glossary_added") else ""))
    for w in r.get("warnings") or []:
        print(f"  warn: {w}")
    if r["pending"]:
        print(f"next: python -m vstudio.batch job rerun --batch {_batch(a)} --job {a.job}")
    return 0


def cmd_job_rerun(a):
    from . import edits as ED
    from .run import BatchBusy
    emit, stream = json_event_sink() if a.json_events else (None, None)
    try:
        r = ED.rerun(_batch(a), a.job, on_event=emit, echo=not a.json)
    except BatchBusy as e:
        if emit:
            emit(dict(event="run-end", status="busy", exit_code=6, error=str(e)))
            return 6
        return _fail(a, e, 6)
    except (KeyError, ValueError) as e:
        return _fail(a, e)
    if emit:
        emit(dict(event="rerun-done", **r))
        stream.flush()
    elif a.json:
        _out(r)
    else:
        print(f"[job rerun] {a.job}: {', '.join(r['stages']) or 'nothing to do'} in {r['seconds']:.1f}s "
              f"-> {r['state']} qc={r['qc']}")
    return 0 if r["ok"] else (r["exit_code"] or 1)


def cmd_plan_segments(a):
    from . import segplan
    try:
        r = segplan.plan_segments(
            a.source, transcript=a.transcript, client=a.client, count=a.count, min_s=a.min, max_s=a.max,
            platforms=[x.strip() for x in a.platforms.split(",")] if a.platforms else None, provider=a.provider,
            model=a.model, out=a.out, language=a.language, echo=not a.json)
    except (segplan.PlanError, FileNotFoundError, ValueError) as e:
        return _fail(a, e, 5 if isinstance(e, segplan.PlanError) else 1)
    if a.json:
        _out(r)
        return 0
    for s_ in r["segments"]:
        print(f"{s_['id']}  {s_['start']:8.2f}-{s_['end']:8.2f} ({s_['end'] - s_['start']:5.1f}s) "
              f"score {s_['score']:.2f}  {s_['title']}")
    print(f"[plan-segments] {len(r['segments'])} segment(s) ({r['provider']}) -> {r['draft']}")
    return 0


def cmd_client(a):
    from . import clients as CL
    try:
        if a.verb == "list":
            r = dict(ok=True, root=CL.clients_root(), clients=CL.list_clients())
        else:
            if not a.client:
                raise CL.ClientError("--client C (a folder or a slug)")
            cdir = CL.resolve(a.client)
            fields = json.loads(a.set) if a.set else {}
            if a.name:
                fields["name"] = a.name
            if a.verb == "init":
                r = CL.init(cdir, fields, exist_ok=a.exist_ok)
            elif a.verb == "update":
                r = CL.update(cdir, fields)
            else:
                r = CL.view(cdir)
    except (CL.ClientError, ValueError) as e:
        return _fail(a, e)
    if a.json or a.verb != "list":
        _out(r)
    else:
        for c in r["clients"]:
            print(f"{c['slug']:20s} {c['name']:24s} {','.join(c['platforms']):30s} glossary {c['glossary']}, "
                  f"batches {c['batches']}")
    return 0


def cmd_deliver(a):
    from . import deliver as DV
    try:
        r = DV.deliver(_batch(a), client=a.client, make_zip=a.zip, cleanup_days=a.cleanup_days, out=a.out)
    except (ValueError, FileNotFoundError, KeyError) as e:
        return _fail(a, e)
    if a.json:
        _out(r)
        return 0
    print(f"[deliver] {r['items']} file(s) of {r['jobs']} job(s) -> {r['dir']}" + (f" (+ {r['zip']})" if r["zip"] else ""))
    print(f"delivery code {r['code']} (package {r['package_code']}); sources cleaned up on {r['cleanup_on'] or 'never'}")
    return 0


def cmd_cleanup_sources(a):
    from . import clients as CL
    from . import deliver as DV
    if a.batch:
        dirs = [a.batch]
    elif a.client:
        dirs = [b["dir"] for b in CL.batches(CL.resolve(a.client))]
    elif a.all:
        dirs = [b["dir"] for b in CL.batches()]
    else:
        dirs = [_batch(a)]
    if getattr(a, "yes", False):
        return _fail(a, ValueError("--yes is gone: run the dry run, check the list, then --confirm-delete <code>"))
    try:
        r = DV.cleanup_sources(dirs, confirm=a.confirm_delete)
    except ValueError as e:
        return _fail(a, e)
    if a.json:
        _out(r)
        return 0
    lst = r.get("would_delete") if r["dry_run"] else r.get("deleted")
    for x in lst:
        print(f"  {'would delete' if r['dry_run'] else 'deleted'} {x['path']} ({human(x['bytes'])})")
    for x in r["outside"]:
        print(f"  NOT deleted (outside the batch folder) {x['path']}")
    for x in r["kept"]:
        print(f"  kept {x['path']}: {x['why']}")
    if r["dry_run"]:
        print(f"[cleanup-sources] would free {human(r['freed'])}"
              + (f"; to delete exactly these files: --confirm-delete {r['confirm_code']}" if r["confirm_code"] else ""))
    else:
        print(f"[cleanup-sources] freed {human(r['freed'])}")
    return 0


def cmd_metrics(a):
    from . import clients as CL
    from . import metrics as MT
    try:
        if a.batch:
            r = MT.metrics(batch=a.batch, csv_=a.csv)
        elif a.client:
            r = MT.metrics(client=CL.resolve(a.client), csv_=a.csv)
        else:
            if not a.all and os.path.exists(DB_NAME):
                r = MT.metrics(batch=os.getcwd(), csv_=a.csv)
            else:
                r = MT.metrics(all_=True, csv_=a.csv)
    except (FileNotFoundError, ValueError) as e:
        return _fail(a, e)
    if a.json:
        _out(r)
    elif a.csv:
        sys.stdout.write(r["csv"])
    else:
        _out(r)
    return 0


def cmd_timing(a):
    from . import metrics as MT
    try:
        r = MT.timing(_batch(a), a.job, a.event, a.what, a.seconds, a.actor)
    except (KeyError, ValueError) as e:
        return _fail(a, e)
    if a.json:
        _out(r)
    else:
        print(f"[timing] {a.job} {a.what} {a.event}: {r['total_s']:.1f}s in total")
    return 0


def cmd_job(a):
    from . import api
    try:
        d = api.job_detail(_batch(a), a.id, words=not a.no_words)
    except KeyError as e:
        if a.json:
            _out(dict(ok=False, error=str(e)))
        else:
            print(f"[job] {e}")
        return 1
    if a.json:
        _out(d)
        return 0
    j = d["job"]
    print(f"{j['id']}  {j['state']}  qc={j['qc']}  {(j['params'] or {}).get('title', '')}")
    for pt in d["cleanup"]["parts"]:
        cut = [e for e in pt["edits"] if e["cut"]]
        print(f"  {pt['part']}: {len(pt['edits'])} edit(s), {len(cut)} cut under reply {d['cleanup']['reply']!r}")
        for e in pt["edits"]:
            if e["action"] != "keep":
                print(f"    #{e['id']:<3} {'CUT ' if e['cut'] else 'keep'} {e['action']:7s} {e['kind']:8s} "
                      f"{e['t0']:.2f}-{e['t1']:.2f} {e['text']}")
    for t in d["transcript"] or []:
        print(f"  transcript {t['range'][0]:.1f}-{t['range'][1]:.1f}: {t['text']}")
    for c in d["captions"]["changes"]:
        print(f"  caption #{c['i']} [{c.get('source')}] {c['before']} -> {c['after']}")
    for s in d["qc"]["suggestions"]:
        print(f"  suggestion: {s['text']}")
    return 0


def cmd_verify_manifest(a):
    from .api import verify_manifest
    r = verify_manifest(a.manifest)
    _out(r)
    return 0 if r["ok"] else 1


def cmd_recipes(a):
    from . import recipes
    if a.json:
        from . import api
        _out(dict(recipes=api.recipes(), capabilities=list(CAPABILITIES)))
        return 0
    for n in recipes.names():
        r = recipes.REGISTRY[n]
        print(f"{n:20s} {r.description}")
        print(" " * 21 + " -> ".join(s.name for s in r.order()))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m vstudio.batch", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.add_argument("--batch", help="batch folder (default: cwd if it holds batch.db)")
        p.set_defaults(fn=fn)
        return p
    p = add("plan", cmd_plan, "spec -> jobs in the batch store")
    p.add_argument("spec", help="batch spec (.yaml/.json) or a job-list .csv (with --recipe / --source)")
    p.add_argument("--planner", choices=["file", "claude"])
    p.add_argument("--segments", help="job-list file (segments.yaml / .csv) for the file planner")
    p.add_argument("--recipe")
    p.add_argument("--source", help="long recording (longform-slices / longform-split)")
    p.add_argument("--sync", action="store_true", help="claude planner: regular API instead of Message Batches")
    p.add_argument("--json", action="store_true", help="print the result as JSON")
    p = add("estimate", cmd_estimate, "time / storage / cost estimate and budget check")
    p.add_argument("--json", action="store_true")
    p = add("run", cmd_run, "run the jobs")
    p.add_argument("--pilot", type=int, help="run only the first N jobs end to end, then stop for review")
    p.add_argument("--confirm-pilot", action="store_true", help="the pilot was reviewed: run everything")
    p.add_argument("--resume", action="store_true", help="clear a circuit-breaker pause and continue")
    p.add_argument("--retry-failed", action="store_true", help="re-run failed jobs from their failed stage")
    p.add_argument("--jobs", help="only these job ids (comma list)")
    p.add_argument("--concurrency", help="override limits, e.g. asr=1,cpu-render=2,face=1")
    p.add_argument("--json-events", action="store_true",
                   help="progress stream on stdout, one JSON object per line (human log -> stderr)")
    p = add("status", cmd_status, "job table")
    p.add_argument("--json", action="store_true")
    p.add_argument("--events", type=int, default=0, help="also show the last N events")
    p = add("review", cmd_review, "HTML review page / apply decisions")
    p.add_argument("--apply", help="decisions.json downloaded from the review page (or the JSON itself)")
    p.add_argument("--confirm-kinds", help="bulk: cut every open question of these classes, e.g. filler-merged,filler/lead")
    p.add_argument("--accept-policy", action="store_true",
                   help="also cut the policy approvals not rendered yet (never learned as creator answers)")
    p.add_argument("--jobs", help="limit --accept-policy / --confirm-kinds to these job ids (comma list)")
    p.add_argument("--approve-green", action="store_true", help="approve every green job not sampled for review")
    p.add_argument("--json", action="store_true", help="print the result / review items (absolute paths) as JSON")
    p = sub.add_parser("job", help="one job: show (transcript, edits, captions, QC, exports) | edit | rerun")
    jsub = p.add_subparsers(dest="verb", required=True)
    q = jsub.add_parser("show", help="one job as JSON / text (`job ID` works too)")
    q.add_argument("id")
    q.add_argument("--batch")
    q.add_argument("--json", action="store_true")
    q.add_argument("--no-words", action="store_true", help="skip the per-word transcript")
    q.set_defaults(fn=cmd_job)
    q = jsub.add_parser("edit", help="in-review edit: caption | trim | cut | notes | hook | cover | copy | undo")
    q.add_argument("--batch")
    q.add_argument("--job", required=True)
    q.add_argument("--op", required=True, choices=["caption", "trim", "cut", "notes", "hook", "cover", "copy", "undo"])
    q.add_argument("--cue", type=int, help="caption: cue index (job show --json captions.cues[].i)")
    q.add_argument("--text", help="caption: the corrected caption; cover: the cover text (a|b = two lines)")
    q.add_argument("--reasr", action="store_true",
                   help="caption: re-hear the cue's audio and accept the text when it matches what is heard")
    q.add_argument("--start", type=float, help="trim: new start / cut: start of the inner cut (source seconds, "
                                               "snapped to a word edge)")
    q.add_argument("--end", type=float, help="trim: new end / cut: end of the inner cut (source seconds)")
    q.add_argument("--why", help="cut: why (kept with the cut, shown in job show)")
    q.add_argument("--set", help='notes: the 记笔记 panel lines, "a|b|c" ("" clears the panel)')
    q.add_argument("--pick", type=int, help="hook: candidate index (-1 = no cold open)")
    q.add_argument("--t", type=float, help="cover: frame time in the output video (seconds)")
    q.add_argument("--title")
    q.add_argument("--body")
    q.add_argument("--tags", help="copy: a,b,c")
    q.add_argument("--json", action="store_true")
    q.set_defaults(fn=cmd_job_edit)
    q = jsub.add_parser("rerun", help="re-run only the stages the edits made stale")
    q.add_argument("--batch")
    q.add_argument("--job", required=True)
    q.add_argument("--json", action="store_true")
    q.add_argument("--json-events", action="store_true", help="progress stream, one JSON object per line")
    q.set_defaults(fn=cmd_job_rerun)
    p = sub.add_parser("plan-segments", help="transcript -> candidate segments (segments.draft.yaml)")
    p.add_argument("--source", required=True, help="the long recording")
    p.add_argument("--transcript", help="reuse a transcript (whisper JSON / vstudio.asr cache) instead of ASR")
    p.add_argument("--client", help="client folder or slug (tags, glossary, style, platforms)")
    p.add_argument("--count", type=int, help="how many segments (default: by duration)")
    p.add_argument("--min", type=float, help="min seconds per segment (default from the platforms)")
    p.add_argument("--max", type=float, help="max seconds per segment")
    p.add_argument("--platforms", help="a,b (title length + length window)")
    p.add_argument("--provider", default="auto",
                   help="auto = the configured llm route (segment_plan), else claude with ANTHROPIC_API_KEY, else none; "
                        "or any vstudio.llm provider: claude | openai | deepseek | qwen | kimi | glm | openrouter | "
                        "ollama | lmstudio | vllm | llamacpp | gemini | claude-code | codex | none")
    p.add_argument("--model")
    p.add_argument("--language")
    p.add_argument("--out", help="output folder (default <source dir>/plan-<source stem>)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_plan_segments, batch=None)
    p = sub.add_parser("client", help="client workspace: init | show | update | list")
    p.add_argument("verb", choices=["init", "show", "update", "list"])
    p.add_argument("--client", help="client folder or slug")
    p.add_argument("--set", help="JSON object of client.yaml fields (update: also glossary_add / glossary_remove / "
                                 "tags_add)")
    p.add_argument("--name")
    p.add_argument("--exist-ok", action="store_true", help="init: update when it exists")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_client, batch=None)
    p = add("deliver", cmd_deliver, "client delivery package (per-platform folders, 文案.md, 排期表, zip)")
    p.add_argument("--client", help="client folder or slug (default: the batch's client)")
    p.add_argument("--zip", action="store_true")
    p.add_argument("--cleanup-days", type=int, help="delete the sources N days after delivery (0 = never)")
    p.add_argument("--out", help="delivery root (default <batch>/delivery)")
    p.add_argument("--json", action="store_true")
    p = add("cleanup-sources", cmd_cleanup_sources, "list (dry run) / delete, with the dry run's code, source files "
                                                     "of deliveries past their cleanup date")
    p.add_argument("--client")
    p.add_argument("--all", action="store_true")
    p.add_argument("--confirm-delete", metavar="CODE", help="delete exactly the files of the dry run with this code")
    p.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--json", action="store_true")
    p = add("metrics", cmd_metrics, "metrics: --batch / --client / --all, JSON or the weekly CSV")
    p.add_argument("--client")
    p.add_argument("--all", action="store_true")
    p.add_argument("--csv", action="store_true", help="the weekly table (gtm weekly metrics columns)")
    p.add_argument("--json", action="store_true")
    p = add("timing", cmd_timing, "review timing event -> batch store")
    p.add_argument("--job", required=True)
    p.add_argument("--event", required=True, choices=["start", "stop", "add"])
    p.add_argument("--what", default="review")
    p.add_argument("--seconds", type=float, help="active seconds (stop / add)")
    p.add_argument("--actor")
    p.add_argument("--json", action="store_true")
    p = add("package", cmd_package, "publish folders + schedule + confirmation code")
    p.add_argument("--per-day", type=int)
    p.add_argument("--start", help="first posting date YYYY-MM-DD (default spec schedule.start, else tomorrow)")
    p.add_argument("--times", help="posting times, e.g. 12:00,19:00")
    p.add_argument("--out")
    p.add_argument("--json", action="store_true", help="print the result + manifest + verify as JSON")
    p = sub.add_parser("verify-manifest", help="recompute a package confirmation code")
    p.add_argument("manifest")
    p.set_defaults(fn=cmd_verify_manifest)
    p = add("clean", cmd_clean, "delete regenerable intermediates")
    p.add_argument("--dry-run", action="store_true")
    add("du", cmd_du, "disk use")
    add("bench", cmd_bench, "benchmark table")
    p = sub.add_parser("recipes", help="list recipes")
    p.add_argument("--json", action="store_true", help="labels, inputs needed, row keys, stages")
    p.set_defaults(fn=cmd_recipes)
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) >= 2 and argv[0] == "job" and argv[1] not in ("show", "edit", "rerun", "-h", "--help"):
        argv.insert(1, "show")                         # `job ID` (F0) == `job show ID`
    a = ap.parse_args(argv)
    if not hasattr(a, "batch"):
        a.batch = None
    if getattr(a, "json", False) and a.cmd not in ("status", "estimate"):
        import contextlib
        with contextlib.redirect_stdout(sys.stderr):        # stdout carries the JSON document only
            return a.fn(a) or 0
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
