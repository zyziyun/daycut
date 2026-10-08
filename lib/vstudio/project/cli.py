"""python -m vstudio.project - every workflow as a recipe; projects of N items (N=1 = one video). See
references/PROJECTS.md.

  recipes [--json] [--schema]                         all recipe manifests + capabilities (--schema: the JSON Schema)
  new --recipe R --dir P [--name N] [--input key=path ...] [--folder D [--glob G]] [--list F] [--csv F]
      [--episodes N] [--param k=v ...] [--set JSON] [--series S] [--client C] [--variants JSON] [--auto a,b]
      [--spec JSON]                                   create a project (items from files / lines / rows / episodes)
  plan-items --dir P [--replace] [--provider X] [--count N] [--min S --max S]   planner recipes: draft the items
  show | status | preview [--item I] [--stage S] | context [--write] | refresh   --dir P [--json]
  run | resume --dir P [--pilot N] [--confirm-pilot] [--items a,b] [--auto ids|all] [--concurrency k=n]
      [--json | --json-events]                        run until done or a checkpoint needs you (exit 7)
  checkpoint --dir P [--id X] [--item I | --items a,b] [--answer JSON | --answer-file F | --default] [--run]
                                                      list pending payloads / record an answer
  set --dir P [--item I] (--param k=v ... | --set JSON)   edit params in project.yaml, then refresh
  export --dir P [--out D] [--all] [--items a,b]      final files + manifest.json (sha256)
  list                                                registered projects (lanes) with their state + adopted work
                                                      folders (kind work) + series
  adopt DIR [--recipe guess|NAME] [--title T] [--client C]   a plain folder made with the skill (final/, REPORT.md,
                                                      post.md, ...) -> DIR/.vstudio/work.json + registry (works.py)
  touch DIR [--status running|waiting|done|failed] [--stage S] [--progress 0..1] [--message M] [--eta S]
      [--needs-you] [--recipe R] [--title T] [--outputs a,b]   register a job folder + its live status (heartbeat);
                                                      a recipe project folder gets only its status (row untouched)
  output list | show | edit | preview-edl | render | undo | redo | revert | ai | chat | effects  --project P --output O   2nd-pass edit of
      one finished output (references/OUTPUT_EDIT.md): edit --ops JSON | --op NAME --param k=v | --op ai
      --instruction T [--apply]; render [--quality preview|final] [--targets primary,douyin:vertical|all]
  ai --project P --instruction T [--outputs all|a,b] [--context JSON] [--timeout 120] [--json | --json-events]
                                                      project-level AI edit: one model call for every output ->
                                                      grouped changes per output, or needs_rerender (burned-in text
                                                      on flattened outputs; answered by rules, no model call)
  series new --id S --recipe R [--name N] [--set JSON] [--cadence JSON] | show --id S | list | update --id S --set JSON
  inbox [--json] | inbox answer (--project P --id X [--item I] | --id X / --kind K [--projects a,b]) (--answer JSON | --default)
  calendar account add --id A --platform P [--times 12:00,19:00] [--per-day N] [--days 0,1,2,3,4]
  calendar plan --project P [--accounts a,b] [--start ISO] | calendar set --post ID --state S [--at ISO] [--url U]
  calendar list [--start ISO] [--end ISO] [--account A] | calendar add --account A --at ISO [--title T]
  share --dir P [--outputs a,b] [--items a,b] [--out D] [--quality small|standard|high] [--no-footer] [--title T]
      [--expiry-note T] [--reply-to EMAIL] [--owner-name N] [--lang auto|en|zh] [--no-zip] [--scan]
                                                      static review page (index.html + previews + posters +
                                                      captions + review.json, + zip); --scan: privacy warnings only
  feedback import (--file F | --text T | stdin) [--dir P] [--no-pin] | list --dir P [--all] | resolve --dir P --id X
                                                      reviewer answers -> feedback items (approve -> ready; change
                                                      -> comment pinned in the clip's chat)
--json: one JSON document on stdout; --json-events: one JSON event per line on stdout (logs -> stderr).
Exit codes: 0 ok, 1 failed items, 2 refused (budget), 3 paused, 4 pilot waits, 5 bad input, 6 busy, 7 needs you.
"""
import argparse
import json
import os
import sys


def _out(a, obj, text=None):
    if getattr(a, "json", False) or text is None:
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    else:
        print(text)


def _kv(pairs):
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise SystemExit(f"expected key=value, got {p!r}")
        k, v = p.split("=", 1)
        try:
            v = json.loads(v)
        except ValueError:
            pass
        out.setdefault(k, [])
        out[k].append(v)
    return out


def _params(a):
    p = {}
    for k, vs in _kv(getattr(a, "param", None)).items():
        p[k] = vs[0] if len(vs) == 1 else vs
    if getattr(a, "set", None):
        p.update(json.loads(a.set))
    return p


def _dir(a):
    from .core import find
    return find(a.dir)


def _csv(v):
    return [x.strip() for x in v.split(",") if x.strip()] if v else None


# --------------------------------------------------------------------------- commands
def cmd_recipes(a):
    from . import manifests as M
    if a.schema:
        print(json.dumps(M.schema(), indent=1))
        return 0
    from .core import public_manifest
    from . import build as B
    rs = []
    for m in M.all_manifests().values():
        d = public_manifest(m)
        graphs = {}
        for b in B.variants(m):
            from vstudio.batch import recipes as RC
            from . import registry  # noqa: F401
            r = RC.get(B.recipe_name(m, b))
            graphs[b or "default"] = [dict(id=s.name, deps=list(s.deps), shared=s.shared, paid=s.paid,
                                           resource=s.resource if isinstance(s.resource, str) else "dynamic",
                                           gate=s.name.startswith(M.GATE_PREFIX)) for s in r.order()]
        d["graph"] = graphs
        rs.append(d)
    caps = ["projects", "items", "variants", "checkpoints", "inbox", "series", "calendar", "pilot", "resume",
            "json-events", "agent-context", "refresh", "export", "batch-store", "job-edit", "deliver", "metrics"]
    obj = dict(recipes=rs, capabilities=caps, schema=M.SCHEMA_PATH)
    _out(a, obj, "\n".join(f"{m['id']:18s} {m['labels']['zh']} / {m['labels']['en']}  checkpoints: "
                           + ", ".join(c["id"] for c in m["checkpoints"]) for m in rs))
    return 0


def cmd_new(a):
    from .core import Project
    inputs = _kv(a.input)
    p = Project.create(a.dir, recipe=a.recipe, name=a.name, inputs=inputs, params=_params(a), series=a.series,
                       client=a.client, variants=json.loads(a.variants) if a.variants else None,
                       auto=_csv(a.auto), spec=json.loads(a.spec) if a.spec else None, episodes=a.episodes,
                       csv_path=a.csv, list_path=a.list, folder=a.folder, glob=a.glob,
                       items=json.loads(a.items_json) if a.items_json else None)
    s = p.status(brief=True)
    _out(a, dict(ok=True, dir=p.dir, recipe=p.data["recipe"], items=[i["id"] for i in s["items"]],
                 state=s["state"], context=os.path.join(p.dir, "AGENTS.md")),
         f"project {p.dir}: {len(s['items'])} item(s) of {p.data['recipe']}")
    return 0


def cmd_plan_items(a):
    from .core import Project
    kw = {k: v for k, v in dict(provider=a.provider, count=a.count, min_s=a.min, max_s=a.max).items() if v is not None}
    _out(a, Project(_dir(a)).plan_items(replace=a.replace, **kw))
    return 0


def cmd_show(a):
    from .core import Project
    _out(a, Project(_dir(a)).show())
    return 0


def cmd_status(a):
    from .core import Project
    s = Project(_dir(a)).status(brief=a.brief)
    lines = [f"{s['name']} ({s['recipe']}): {s['state']}  {s['progress']['done']}/{s['progress']['total']} stages"]
    for i in s["items"]:
        lines.append(f"  {i['id']:20s} {i['state']:11s} {i['progress']['done']}/{i['progress']['total']}"
                     + (f"  waiting: {', '.join(i['waiting'])}" if i["waiting"] else ""))
    _out(a, s, "\n".join(lines))
    return 0


def cmd_preview(a):
    from .core import Project
    _out(a, Project(_dir(a)).preview(item=a.item, stage=a.stage))
    return 0


def cmd_context(a):
    from .core import Project
    p = Project(_dir(a))
    c = p.context()
    if a.write:
        c["written"] = p.write_agent_files()
    _out(a, c)
    return 0


def cmd_refresh(a):
    from .core import Project
    _out(a, Project(_dir(a)).refresh())
    return 0


def cmd_run(a, resume=False):
    from vstudio.batch.cli import json_event_sink
    from vstudio.batch.run import parse_limits
    from .core import Project
    emit, stream = json_event_sink() if a.json_events else (None, None)
    p = Project(_dir(a))
    auto = _csv(a.auto) or []
    r = p.run(pilot=a.pilot, confirm_pilot=a.confirm_pilot, resume=resume or a.resume, only=_csv(a.items),
              limits=parse_limits(a.concurrency), on_event=emit, auto=auto, echo=not (a.json or emit))
    if emit:
        stream.flush()
    else:
        txt = f"{r['status']} (exit {r['exit_code']})" + "".join(
            f"\n  needs you: {x['item']} {x['id']} ({x['kind']})" for x in r["pending"])
        _out(a, r, txt)
    return r["exit_code"]


def cmd_checkpoint(a):
    from .core import Project
    p = Project(_dir(a))
    value = None
    if a.answer is not None:
        value = json.loads(a.answer)
    elif a.answer_file:
        with open(a.answer_file, encoding="utf-8") as f:
            value = json.load(f)
    if value is None and not a.default:
        pend = p.pending(cid=a.id, item=a.item)
        _out(a, dict(pending=pend, n=len(pend)),
             "\n".join(f"{x['item']}: {x['id']} ({x['kind']}) {len(x.get('options') or [])} option(s)" for x in pend)
             or "nothing pending")
        return 0
    if not a.id:
        raise SystemExit("--id is required to answer")
    items = _csv(a.items) or ([a.item] if a.item else None)
    if a.default:
        pend = p.pending(cid=a.id)
        if items:
            pend = [x for x in pend if x["item"] in items]
        res = []
        for x in pend:
            if x.get("default") is None:
                continue
            res.append(p.answer(a.id, x["default"], items=None if x["scope"] == "project" else [x["item"]]))
        out = dict(ok=True, answered=[r["answered"] for r in res])
        if a.run:
            out["run"] = p.run()
        _out(a, out)
        return 0
    _out(a, p.answer(a.id, value, items=items, run=a.run))
    return 0


def cmd_set(a):
    from .core import Project
    p = Project(_dir(a))
    vals = _params(a)
    props = p.manifest["params"]["properties"]
    unknown = [k for k in vals if k not in props and not a.item]
    if unknown:
        raise SystemExit(f"unknown params {unknown}")
    if a.item:
        it = next((i for i in p.data["items"] if i["id"] == a.item), None)
        if not it:
            raise SystemExit(f"unknown item {a.item}")
        it.setdefault("params", {}).update(vals)
    else:
        p.data["params"].update(vals)
    p.save()
    _out(a, p.refresh())
    return 0


def cmd_export(a):
    from .core import Project
    _out(a, Project(_dir(a)).export(out_dir=a.out, include_unapproved=a.all, items=_csv(a.items)))
    return 0


def cmd_list(a):
    from . import home as H
    from .core import Project
    rows = []
    H.prune()                                   # missing folders / temp-dir test junk
    for r in H.live_projects():
        try:
            s = Project(r["dir"]).status(brief=True)
            rows.append(dict(r, state=s["state"], items=len(s["items"]), pending=s.get("pending", 0),
                             progress=s["progress"]))
        except Exception as e:  # noqa: BLE001
            rows.append(dict(r, state="error", error=str(e)))
    from . import works as W
    for r in H.live_works():
        rec = W.show(r["dir"]) or {}
        rows.append(dict(r, kind="work", state="adopted", type=rec.get("type"), items=len(rec.get("outputs") or []),
                         outputs=rec.get("outputs") or [], pending=0, progress=None))
    try:
        series = [dict(id=x.get("id"), name=x.get("name"), recipe=x.get("recipe"), client=x.get("client"),
                       projects=x.get("projects") or []) for x in H.list_series()]
    except Exception:  # noqa: BLE001  (a broken series.yaml must not hide the projects)
        series = []
    _out(a, dict(projects=rows, series=series), "\n".join(f"{r['state']:10s} {r['dir']}" for r in rows) or "no projects")
    return 0


def cmd_adopt(a):
    from . import works as W
    r = W.adopt(a.path, recipe=a.recipe or "guess", title=a.title, client=a.client)
    _out(a, r, f"adopted {r['dir']} as {r['type']} ({r['recipe'] or 'no recipe'}), {len(r['outputs'])} output(s)")
    return 0


def cmd_touch(a):
    from . import works as W
    r = W.touch(a.path, recipe=a.recipe, title=a.title, client=a.client,
                outputs=[x for x in (a.outputs or "").split(",") if x] or None, status=a.status, stage=a.stage,
                progress=a.progress, message=a.message, eta=a.eta, needs_you=True if a.needs_you else None)
    _out(a, r, f"{r['dir']}: {a.status or 'registered'}{' · ' + a.stage if a.stage else ''}")
    return 0


def cmd_output(a):
    from . import outfx as FX
    from . import outputs as O
    act = a.action
    if act == "effects":
        rows = FX.catalogue(thumbs=not a.no_thumbs)
        _out(a, dict(ok=True, effects=rows, n=len(rows)),
             "\n".join(f"{r['id']:18s} {r['label']['zh']} / {r['label']['en']}  ({r['stage']})" for r in rows))
        return 0
    proj = a.project or a.dir or os.getcwd()
    if act == "list":
        r = O.list_outputs(proj)
        _out(a, r, "\n".join(f"{x['id']}  {'edited ' + str(x['steps']) if x['edited'] else ''}" for x in r["outputs"])
             or "no outputs")
        return 0
    if not a.output:
        raise O.OutputError("bad-param", "--output is required (output list --json shows the ids)",
                            "需要 --output", name="output")
    if act == "show":
        _out(a, O.show(proj, a.output))
        return 0
    if act == "undo":
        _out(a, O.undo(proj, a.output))
        return 0
    if act == "redo":
        _out(a, O.redo(proj, a.output))
        return 0
    if act == "revert":
        if not a.step:
            raise O.OutputError("bad-param", "--step is required (show --json: history.steps[].id)", "需要 --step",
                                name="step")
        _out(a, O.revert(proj, a.output, a.step, note=a.note))
        return 0
    if act == "chat":
        if a.add:
            _out(a, O.chat_add(proj, a.output, json.loads(a.add)))
        elif a.turn:
            _out(a, O.chat_update(proj, a.output, a.turn, json.loads(a.set or "{}")))
        else:
            r = O.chat(proj, a.output)
            _out(a, r, "\n".join(f"{t['id']}  {t.get('status', '')}  {t.get('text', '')}" for t in r["turns"])
                 or "no chat yet")
        return 0
    if act == "render":
        from . import outrender as R
        emit, stream = (None, None)
        if a.json_events:
            from vstudio.batch.cli import json_event_sink
            emit, stream = json_event_sink()
        r = R.render(proj, a.output, quality=a.quality, targets=_csv(a.targets) or ["primary"], on_event=emit,
                     with_ops=json.loads(a.with_ops) if a.with_ops else None)
        if emit:
            emit(dict(event="render-done", **r))
            stream.flush()
        else:
            _out(a, r, "\n".join(f"{t['target']}: {t['file']}{' (cached)' if t['cached'] else ''}"
                                  for t in r["targets"]))
        return 0
    if act == "ai" or (act == "edit" and a.op == "ai"):
        if not a.instruction:
            raise O.OutputError("bad-param", "--instruction is required", "需要 --instruction", name="instruction")
        _out(a, O.ai(proj, a.output, a.instruction, apply=a.apply, provider=a.provider, model=a.model,
                     use_asr=not a.no_asr, context=json.loads(a.context) if a.context else None,
                     record=not a.no_record, timeout=a.timeout))
        return 0
    # edit / preview-edl
    if a.ops:
        ops = json.loads(a.ops)
    elif a.ops_file:
        with open(a.ops_file, encoding="utf-8") as f:
            ops = json.load(f)
    elif a.op:
        ops = dict(_params(a), op=a.op)
    else:
        raise O.OutputError("no-ops", f"{act} needs --ops JSON, --ops-file F or --op NAME", "需要 --ops 或 --op")
    if act == "preview-edl":
        r = O.preview_edl(proj, a.output, ops)
        _out(a, r, "\n".join(f"keep {x:.3f}-{y:.3f}" for x, y in r["keep"]) + f"\n-> {r['duration']:.2f}s")
        return 0
    _out(a, O.edit(proj, a.output, ops, note=a.note, turn=a.turn))
    return 0


def cmd_ai(a):
    from . import projai as PA
    emit, stream = (None, None)
    if a.json_events:
        from vstudio.batch.cli import json_event_sink
        emit, stream = json_event_sink()
    from .outputs import OutputError
    try:
        r = PA.plan(a.project or a.dir or os.getcwd(), a.instruction, outputs=a.outputs,
                    context=json.loads(a.context) if a.context else None, provider=a.provider, model=a.model,
                    timeout=a.timeout, on_event=emit)
    except OutputError as e:
        if not emit:
            raise
        emit(dict(event="failed", ok=False, error=e.info["message"], **e.info))
        stream.flush()
        return 5
    if emit:
        emit(dict(event="done", result=r))
        stream.flush()
        return 0
    lines = [f"{r['answer']} ({r['seconds']}s, {r['provider']})"]
    for g in r["groups"]:
        lines.append(f"  {g['output']}: " + "; ".join(p["describe"]["message"] for p in g["proposed"]))
    if r["needs_rerender"]:
        n = r["needs_rerender"]
        lines.append(f"  needs re-render: {', '.join(n['outputs'])} - {n['reason']['message']}")
        lines += [f"    path: {p['kind']} - {p['message']['message']}" for p in n["paths"]]
    _out(a, r, "\n".join(lines))
    return 0


def cmd_series(a):
    from . import home as H
    if a.action == "new":
        s = H.new_series(a.id, a.recipe, name=a.name, params=json.loads(a.set) if a.set else None,
                         cadence=json.loads(a.cadence) if a.cadence else None, accounts=_csv(a.accounts),
                         client=a.client)
    elif a.action == "show":
        s = H.series_view(a.id)
    elif a.action == "update":
        s = H.update_series(a.id, json.loads(a.set or "{}"))
    else:
        s = dict(series=H.list_series())
    _out(a, s)
    return 0


def cmd_inbox(a):
    from . import inbox as I
    if a.action == "answer":
        value = json.loads(a.answer) if a.answer else None
        if a.project and not a.default:
            r = I.answer(a.project, a.id, value, items=_csv(a.items) or ([a.item] if a.item else None), run=a.run)
        else:
            r = I.answer_bulk(cid=a.id, kind=a.kind, value=value, use_default=a.default, projects=_csv(a.projects)
                              or ([a.project] if a.project else None), items=_csv(a.items), run=a.run)
        _out(a, r)
        return 0
    r = I.inbox()
    _out(a, r, "\n".join(f"{e['project_name'] or e['project']}  {e['item']}  {e['id']} ({e['kind']})"
                         for e in r["entries"]) or "inbox empty")
    return 0


def cmd_calendar(a):
    from . import pubcal as C
    if a.action == "account":
        r = C.add_account(a.id, a.platform, name=a.name, times=_csv(a.times), per_day=a.per_day,
                          days=[int(x) for x in _csv(a.days)] if a.days else None)
    elif a.action == "plan":
        r = C.plan(a.project, accounts=_csv(a.accounts), start=a.start)
    elif a.action == "set":
        r = C.set_state(a.post, a.state, at=a.at, url=a.url)
    elif a.action == "add":
        r = C.add_post(a.account, a.at, project=a.project, title=a.title)
    else:
        r = C.listing(start=a.start, end=a.end, account=a.account)
    _out(a, r)
    return 0


def cmd_share(a):
    from . import share as SH
    if a.scan:
        clips = SH.collect_clips(_dir_or_work(a), outputs=_csv(a.outputs), items=_csv(a.items))
        r = SH.privacy_scan(_dir_or_work(a), clips)
        _out(a, dict(r, clips=[dict(id=c["id"], title=c["title"], versions=len(c["versions"])) for c in clips]),
             "\n".join(f"{w['level']}: {w['message']}" for w in r["warnings"]) or "no privacy warnings")
        return 0
    r = SH.share(_dir_or_work(a), out=a.out, outputs=_csv(a.outputs), items=_csv(a.items), quality=a.quality,
                 footer=not a.no_footer, title=a.title, lang=a.lang, expiry_note=a.expiry_note, reply_to=a.reply_to,
                 owner_name=a.owner_name, make_zip=not a.no_zip)
    lines = [f"review page: {r['index']}", f"zip: {r['zip']}" if r["zip"] else "", f"share id: {r['share']}"]
    lines += [f"{w['level']}: {w['message']}" for w in r["privacy"]["warnings"]]
    _out(a, r, "\n".join(x for x in lines if x))
    return 0


def _dir_or_work(a):
    d = os.path.abspath(a.dir or os.getcwd())
    if os.path.exists(os.path.join(d, "batch.db")):          # a plain vstudio.batch folder: shared as is
        return d
    from . import outputs as O
    return O._owner(d)[0]


def cmd_feedback(a):
    from . import share as SH
    if a.action == "import":
        if a.file:
            with open(a.file, encoding="utf-8", errors="replace") as f:
                text = f.read(SH.MAX_FEEDBACK_BYTES + 1)
        elif a.text:
            text = a.text
        else:
            text = sys.stdin.read(SH.MAX_FEEDBACK_BYTES + 1)
        r = SH.import_feedback(text, owner=os.path.abspath(a.dir) if a.dir else None, pin=not a.no_pin)
        _out(a, r, f"{len(r['items'])} new feedback item(s) for {r['title']} ({r['owner']})"
             + (f", {r['duplicates']} already imported" if r["duplicates"] else ""))
        return 0
    owner = _dir_or_work(a)
    if a.action == "resolve":
        if not a.id:
            raise SH.ShareError("bad-param", "--id is required", "需要 --id")
        _out(a, SH.resolve(owner, a.id))
        return 0
    rows = SH.feedback_items(owner, status="all" if a.all else "open")
    _out(a, dict(ok=True, items=rows), "\n".join(f"{x['id']}  {x['decision']:8s} {x['clip']}  {x['comment']}"
                                                   for x in rows) or "no open feedback")
    return 0


# --------------------------------------------------------------------------- parser
def build_parser():
    ap = argparse.ArgumentParser(prog="python -m vstudio.project", description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_, d=True):
        p = sub.add_parser(name, help=help_)
        if d:
            p.add_argument("--dir", help="project folder (default: cwd or a parent with project.yaml)")
        p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
        return p
    p = add("recipes", cmd_recipes, "list recipe manifests", d=False)
    p.add_argument("--schema", action="store_true")
    p = add("new", cmd_new, "create a project", d=False)
    p.add_argument("--dir", required=True)
    p.add_argument("--recipe")
    p.add_argument("--name")
    p.add_argument("--input", action="append", help="key=path (repeat for several files)")
    p.add_argument("--folder", help="every matching file of this folder is an item")
    p.add_argument("--glob")
    p.add_argument("--list", help="text file: one item per line (topics / titles)")
    p.add_argument("--csv", help="rows: id + input / param columns")
    p.add_argument("--episodes", type=int)
    p.add_argument("--items-json", help="explicit items [{id, inputs, params}]")
    p.add_argument("--param", action="append")
    p.add_argument("--set", help="params as JSON")
    p.add_argument("--series")
    p.add_argument("--client")
    p.add_argument("--variants", help='JSON, e.g. {"by": ["platform"]}')
    p.add_argument("--auto", help="checkpoints run may answer with their default (comma list or all)")
    p.add_argument("--spec", help="extra vstudio.batch spec sections (JSON)")
    p = add("plan-items", cmd_plan_items, "planner recipes: draft the items (segments of a recording)")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--provider", help="segment planner: auto | none | claude | openai | ... (vstudio.llm)")
    p.add_argument("--count", type=int)
    p.add_argument("--min", type=float)
    p.add_argument("--max", type=float)
    add("show", cmd_show, "manifest + project.yaml + status")
    p = add("status", cmd_status, "items and stages")
    p.add_argument("--brief", action="store_true")
    p = add("preview", cmd_preview, "preview artifacts")
    p.add_argument("--item")
    p.add_argument("--stage")
    p = add("context", cmd_context, "agent hook: compact state + playbook + commands")
    p.add_argument("--write", action="store_true", help="also (re)write AGENTS.md / CLAUDE.md in the project")
    add("refresh", cmd_refresh, "re-read project.yaml + item files, re-plan")
    for name, res in (("run", False), ("resume", True)):
        p = add(name, (lambda a, r=res: cmd_run(a, resume=r)), "run until done or a checkpoint")
        p.add_argument("--pilot", type=int)
        p.add_argument("--confirm-pilot", action="store_true")
        p.add_argument("--resume", action="store_true")
        p.add_argument("--items")
        p.add_argument("--auto")
        p.add_argument("--concurrency")
        p.add_argument("--json-events", action="store_true")
    p = add("checkpoint", cmd_checkpoint, "pending checkpoints / answer one")
    p.add_argument("--id")
    p.add_argument("--item")
    p.add_argument("--items")
    p.add_argument("--answer")
    p.add_argument("--answer-file")
    p.add_argument("--default", action="store_true", help="answer with each payload's default")
    p.add_argument("--run", action="store_true", help="continue the run after answering")
    p = add("set", cmd_set, "edit params")
    p.add_argument("--item")
    p.add_argument("--param", action="append")
    p.add_argument("--set")
    p = add("export", cmd_export, "collect final files")
    p.add_argument("--out")
    p.add_argument("--all", action="store_true", help="also unapproved / unfinished items")
    p.add_argument("--items")
    add("list", cmd_list, "registered projects (+ adopted work folders, series)", d=False)
    p = add("adopt", cmd_adopt, "an existing folder made with the skill -> work record + registry", d=False)
    p.add_argument("path")
    p.add_argument("--recipe", help="guess (default) or a recipe / type name")
    p.add_argument("--title")
    p.add_argument("--client")
    p = add("touch", cmd_touch, "register a job folder + report its live status (desk 进行中 lane)", d=False)
    p.add_argument("path")
    p.add_argument("--status", choices=["running", "waiting", "done", "failed"])
    p.add_argument("--stage")
    p.add_argument("--progress", type=float, help="0..1")
    p.add_argument("--message")
    p.add_argument("--eta", type=float, help="seconds left")
    p.add_argument("--needs-you", action="store_true", help="waiting on the creator (a checkpoint / question)")
    p.add_argument("--recipe")
    p.add_argument("--title")
    p.add_argument("--client")
    p.add_argument("--outputs", help="comma list (default: videos in final/ exports/ out/)")
    p = add("output", cmd_output, "second-pass edit of a finished output (references/OUTPUT_EDIT.md)")
    p.add_argument("action", choices=["list", "show", "edit", "render", "undo", "redo", "revert", "ai", "chat",
                                      "effects", "preview-edl"])
    p.add_argument("--project", help="project folder or adopted work folder (default --dir / cwd)")
    p.add_argument("--output", help="output id (output list), or its file path")
    p.add_argument("--ops", help="JSON op or list of ops")
    p.add_argument("--ops-file")
    p.add_argument("--op", help="one op name (with --param k=v / --set JSON); ai = natural language")
    p.add_argument("--param", action="append")
    p.add_argument("--set")
    p.add_argument("--note")
    p.add_argument("--instruction", help="ai: what to change, in plain language")
    p.add_argument("--apply", action="store_true", help="ai: apply the proposed ops (default: propose only)")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--no-asr", action="store_true", help="ai: do not transcribe a flattened output for context")
    p.add_argument("--context", help='ai: what the creator points at, JSON {"range": [a, b], "cues": [..], '
                   '"effect": "fx2"}')
    p.add_argument("--no-record", action="store_true", help="ai: do not add the turn to the chat transcript")
    p.add_argument("--timeout", type=float, help="ai: seconds per CLI provider attempt before the fallback (60)")
    p.add_argument("--step", help="revert: the history step id to cancel (later steps stay)")
    p.add_argument("--turn", help="edit: the chat turn the ops come from (marked applied); chat: the turn to patch")
    p.add_argument("--add", help="chat: append a turn (JSON)")
    p.add_argument("--with-ops", help="render: preview these ops without applying them (before / after compare)")
    p.add_argument("--quality", choices=["preview", "final"], default="preview")
    p.add_argument("--targets", help="render: primary (default), platform:orientation list, or all")
    p.add_argument("--json-events", action="store_true")
    p.add_argument("--no-thumbs", action="store_true", help="effects: skip the preview thumbnails")
    p = add("ai", cmd_ai, "project-level AI edit of every output (grouped per output; needs_rerender)")
    p.add_argument("--project", help="project folder or adopted work folder (default --dir / cwd)")
    p.add_argument("--instruction", required=True)
    p.add_argument("--outputs", default="all", help="all (default) or a comma list of output ids")
    p.add_argument("--context", help="JSON: what the creator points at (e.g. {\"selected\": \"<output id>\"})")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--timeout", type=float, default=120.0, help="seconds per provider before the fallback (120)")
    p.add_argument("--json-events", action="store_true", help="stage / fallback events, then {event: done, result}")
    p = add("series", cmd_series, "series presets", d=False)
    p.add_argument("action", choices=["new", "show", "list", "update"])
    p.add_argument("--id")
    p.add_argument("--recipe")
    p.add_argument("--name")
    p.add_argument("--set")
    p.add_argument("--cadence")
    p.add_argument("--accounts")
    p.add_argument("--client")
    p = add("inbox", cmd_inbox, "pending checkpoints across projects", d=False)
    p.add_argument("action", nargs="?", choices=["list", "answer"], default="list")
    p.add_argument("--project")
    p.add_argument("--projects")
    p.add_argument("--id")
    p.add_argument("--kind")
    p.add_argument("--item")
    p.add_argument("--items")
    p.add_argument("--answer")
    p.add_argument("--default", action="store_true")
    p.add_argument("--run", action="store_true")
    p = add("calendar", cmd_calendar, "publish calendar", d=False)
    p.add_argument("action", choices=["account", "plan", "set", "list", "add"])
    p.add_argument("sub", nargs="?", help="account: add")
    p.add_argument("--id")
    p.add_argument("--platform")
    p.add_argument("--name")
    p.add_argument("--times")
    p.add_argument("--per-day", type=int)
    p.add_argument("--days")
    p.add_argument("--project")
    p.add_argument("--accounts")
    p.add_argument("--account")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--post")
    p.add_argument("--state")
    p.add_argument("--at")
    p.add_argument("--url")
    p.add_argument("--title")
    p = add("share", cmd_share, "static review page for a project / clips (share for review)")
    p.add_argument("--outputs", help="comma list of output ids or clip ids (default: every finished clip)")
    p.add_argument("--items", help="comma list of item ids")
    p.add_argument("--out", help="the review folder (default <project>/review-links/<title>-<id>)")
    p.add_argument("--quality", default="standard", help="small (540p) | standard (720p, default) | high (1080p)")
    p.add_argument("--no-footer", action="store_true", help='leave out the "Made with Reelfold" footer')
    p.add_argument("--title")
    p.add_argument("--lang", default="auto", choices=["auto", "en", "zh"], help="page language (auto: the browser's)")
    p.add_argument("--expiry-note", help='shown on the page, e.g. "Please reply by Friday"')
    p.add_argument("--reply-to", help="email address the page's Email button writes to")
    p.add_argument("--owner-name", help='"From <name>" on the page')
    p.add_argument("--no-zip", action="store_true")
    p.add_argument("--scan", action="store_true", help="only the privacy warnings + the clips that would be shared")
    p = add("feedback", cmd_feedback, "reviewer feedback: import / list / resolve")
    p.add_argument("action", nargs="?", choices=["import", "list", "resolve"], default="list")
    p.add_argument("--file", help="import: the .reelfold.json file (or any text with the feedback code)")
    p.add_argument("--text", help="import: the pasted code / text")
    p.add_argument("--no-pin", action="store_true", help="import: do not add change requests to the clip chat")
    p.add_argument("--all", action="store_true", help="list: also resolved items")
    p.add_argument("--id", help="resolve: the feedback item id")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    from vstudio.batch.run import BatchBusy
    from .core import ProjectError
    from .home import SeriesError
    from .manifests import ManifestError
    from .pubcal import CalendarError
    from .outputs import OutputError
    from .share import ShareError
    try:
        return a.fn(a)
    except (OutputError, ShareError) as e:
        if getattr(a, "json", False) or getattr(a, "json_events", False):
            print(json.dumps(dict(ok=False, error=e.info["message"], **e.info), ensure_ascii=False, default=str))
        else:
            print(f"error: {e.info['message']}", file=sys.stderr)
        return 5
    except BatchBusy as e:
        _out(a, dict(ok=False, error=str(e)), f"busy: {e}")
        return 6
    except (ProjectError, SeriesError, ManifestError, CalendarError, KeyError, FileNotFoundError, ValueError) as e:
        msg = str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)
        if getattr(a, "json", False) or getattr(a, "json_events", False):
            extra = {}
            if getattr(e, "info", None):              # e.g. plan-segments failed: every AI provider tried
                extra = dict(e.info, attempts=getattr(e, "attempts", None) or [])
            print(json.dumps(dict(ok=False, error=msg, type=type(e).__name__, **extra), ensure_ascii=False,
                             default=str))
        else:
            print(f"error: {msg}", file=sys.stderr)
        return 5
