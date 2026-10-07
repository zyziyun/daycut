"""JSON views for the desk (and ``--json`` CLI output): series list / detail, episode board, the Making view."""
import os
import time

from . import costs, formats as F, jobs, providers as PR, routing, store

CELL = {"done": "ok", "running": "run", "submitting": "run", "queued": "q", "failed": "bad", "unknown-charge": "bad",
        "manual-waiting": "you", "skipped": "q", "stopped": "q"}     # finals units and make (plugin / agent) units


def _public(ep):
    return {k: v for k, v in ep.items() if not k.startswith("_") and k not in ("estimates",)}


def series_summary(sid):
    s = store.load_series_file(sid)
    meta = store.create_meta(s)
    eps = store.list_episodes(sid)
    status = None
    for ep in eps:
        st = episode_status(ep)
        if st["code"] in ("create.status.pick", "create.status.you"):
            status = st
            break
        status = status or (st if st["code"] != "create.status.draft" else None)
    cover = next((c for c in (episode_cover(ep) for ep in eps) if c), None)
    return dict(id=sid, name=s.get("name"), format=meta.get("format"), recipe=s.get("recipe"),
                episodes=len(eps), planned=meta.get("episodes"), last=eps[-1]["no"] if eps else 0,
                budget=costs.series_budget(s), spent=costs.spent(sid), status=status, cover=cover,
                sample=bool(meta.get("sample")), updated=max([os.path.getmtime(os.path.join(store.series_dir(sid),
                                                                                                 "series.yaml"))] +
                                                                [os.path.getmtime(os.path.join(e["_dir"], "create.yaml"))
                                                                 for e in eps]))


def episode_cover(ep):
    """The first frame with people in it (the most telling), else the first frame."""
    shots = [sh for sh in ep.get("shots") or [] if sh.get("still")]
    return next((sh["still"] for sh in shots if sh.get("faces")), shots[0]["still"] if shots else None)


def list_series():
    rows = [series_summary(sid) for sid in store.list_series_ids()]
    rows.sort(key=lambda r: -r["updated"])
    return rows


def episode_status(ep):
    run = ep.get("run") or {}
    lad = ep.get("ladder") or {}
    if (ep.get("handoff") or {}).get("dir"):
        return dict(code="create.status.ready", params={})
    if lad.get("finals") == "pick" or jobs.needs_pick(ep):
        n = sum(1 for no, v in (ep.get("takes") or {}).items() if len(v) > 1 and not (ep.get("picks") or {}).get(no))
        return dict(code="create.status.pick", params=dict(n=n))
    if run.get("state") == "paused":
        return dict(code="create.status.you", params={})
    if run.get("state") == "running":
        u = run.get("units") or {}
        done = sum(1 for v in u.values() if v.get("state") == "done")
        return dict(code="create.status.making", params=dict(done=done, total=len(u)))
    if lad.get("finals") == "done":
        return dict(code="create.status.assemble", params={})
    if ep.get("shots"):
        return dict(code="create.status.board", params=dict(n=len(ep["shots"])))
    return dict(code="create.status.draft", params={})


def series_view(sid):
    s = store.load_series_file(sid)
    meta = store.create_meta(s)
    fmt = F.get(meta["format"])
    eps = store.list_episodes(sid)
    return dict(id=sid, name=s.get("name"), format=F.public(fmt), recipe=s.get("recipe"), meta=meta,
                platforms=(s.get("params") or {}).get("platforms") or [], bible=store.load_bible(sid),
                ideas=store.load_ideas(sid),
                episodes=[dict(id=e["id"], no=e.get("no"), title=e.get("title"), logline=e.get("logline"),
                               shots=len(e.get("shots") or []), status=episode_status(e),
                               state=e.get("state"), ladder=e.get("ladder"),
                               handoff=e.get("handoff"),
                               cover=episode_cover(e))
                          for e in eps],
                spend=costs.summary(sid), counts=dict(
                    making=sum(1 for e in eps if (e.get("run") or {}).get("state") in ("running", "paused")
                               or jobs.needs_pick(e)),
                    ready=sum(1 for e in eps if (e.get("ladder") or {}).get("finals") == "done" or e.get("handoff"))))


def next_step(ep, est):
    lad = ep.get("ladder") or {}
    run = ep.get("run") or {}
    if run.get("state") == "running":
        return dict(step="making")
    if lad.get("stills") != "done":
        return dict(step="stills")
    mk = ep.get("make") or {}
    if mk.get("state") == "running":
        return dict(step="making")
    pend = [no for no, v in ((est or {}).get("shots") or {}).items()
            if v.get("kind") in routing.MADE_BY_PLUGINS and not (ep.get("takes") or {}).get(no)
            and ((mk.get("units") or {}).get(no) or {}).get("state") != "manual-waiting"]
    if pend:
        return dict(step="make", n=len(pend))
    if lad.get("animatic") != "done":
        return dict(step="animatic")
    if jobs.needs_pick(ep):
        return dict(step="pick")
    if lad.get("finals") in ("todo", None, "paused", "stopped") or not ep.get("takes"):
        if est and (est["n_paid"] or est["n_manual"]):
            return dict(step="finals", n=est["n_paid"] + est["n_manual"], cny=est["subtotal_cny"])
    if ep.get("handoff"):
        return dict(step="ready")
    return dict(step="assemble")


def episode_view(eid):
    ep, s, fmt, bible = jobs.context(eid)
    connected = PR.connected()
    routes, units, warns = jobs.plan(ep, s, fmt)
    est = costs.build(ep, s, "finals", routes, units)
    est.update(costs.context(est, s, ep["series"]))
    by_no = {r["no"]: r for r in routes}
    shots = []
    local = os.environ.get("VSTUDIO_CREATE_LOCAL") == "1"
    for sh in ep.get("shots") or []:
        r = by_no.get(sh["no"]) or {}
        takes = (ep.get("takes") or {}).get(sh["no"]) or []
        shots.append(dict(sh, route=r, takes=takes, pick=(ep.get("picks") or {}).get(sh["no"]),
                          options=routing.options(sh, connected, local)))
    pol = routing.policy(s, fmt)
    return dict(_public(ep), shots=shots, series_name=s.get("name"), format=F.public(fmt),
                bible=dict(cast=bible.get("cast") or [], aspect=bible.get("aspect"), length_s=bible.get("length_s"),
                           languages=bible.get("languages") or []),
                policy=pol, warnings=warns, estimate=est, next=next_step(ep, est), status=episode_status(ep),
                connected=connected, runtime=round(sum(float(x.get("dur") or 0) for x in ep.get("shots") or []), 1),
                manual_prompts_file=os.path.join(store.work_dir(ep), "sheets", "PROMPTS.md")
                if os.path.exists(os.path.join(store.work_dir(ep), "sheets", "PROMPTS.md")) else None)


def making(sid=None):
    """The Making view: per-episode cells (ok | run | local | you | bad | q | pick) + run money + alerts."""
    sids = [sid] if sid else store.list_series_ids()
    rows, alerts, runs = [], [], []
    running = {}
    for x in sids:
        for ep in store.list_episodes(x):
            run = ep.get("run") or {}
            mk = ep.get("make") or {}
            if not run and not ep.get("takes") and not mk:
                continue
            units = run.get("units") or {}
            by_shot = {no: u for u in units.values() for no in u.get("shots") or []}
            for no, u in (mk.get("units") or {}).items():            # plugin / agent shots made in lanes
                by_shot[no] = dict(u, provider=f"{u.get('kind')}:{u.get('runner')}")
            cells = []
            for sh in ep.get("shots") or []:
                tk = (ep.get("takes") or {}).get(sh["no"]) or []
                picked = (ep.get("picks") or {}).get(sh["no"])
                u = by_shot.get(sh["no"])
                if len(tk) > 1 and not picked:
                    st = "pick"
                elif picked or (tk and len(tk) == 1):
                    st = "ok"
                elif sh.get("card"):
                    st = "ok"
                elif u:
                    st = CELL.get(u.get("state"), "q")
                else:
                    st = "q"
                cells.append(dict(no=sh["no"], state=st, still=sh.get("still"), n_takes=len(tk),
                                  provider=(u or {}).get("provider")))
            for u in units.values():
                if u.get("state") in ("running", "submitting"):
                    running[u.get("provider")] = running.get(u.get("provider"), 0) + 1
            led = costs.ledger(x)
            ep_spent = round(sum(float(r.get("est_cny") or 0) for r in led
                                 if r.get("episode") == ep["id"] and r.get("status") in costs.COUNTED), 1)
            if run.get("id"):
                runs.append((run.get("started") or "", round(sum(
                    float(r.get("est_cny") or 0) for r in led if r.get("episode") == ep["id"]
                    and r.get("run") == run["id"] and r.get("status") in costs.COUNTED), 1),
                    float(run.get("approved_cny") or 0), run.get("state") == "running"))
            for a in run.get("alerts") or []:
                alerts.append(dict(a, episode=ep["id"], episode_no=ep.get("no"), series=x))
            n_pick = sum(1 for c in cells if c["state"] == "pick")
            done = sum(1 for c in cells if c["state"] == "ok")
            mku = mk.get("units") or {}
            make = dict(state=mk.get("state"), lanes=mk.get("lanes") or {}, total=len(mku),
                        done=sum(1 for u in mku.values() if u.get("state") == "done"),
                        failed=[dict(no=no, code=u.get("code"), params=u.get("params") or {})
                                for no, u in sorted(mku.items()) if u.get("state") == "failed"],
                        waiting=[dict(no=no, code=u.get("code"), params=u.get("params") or {})
                                 for no, u in sorted(mku.items()) if u.get("state") == "manual-waiting"]) if mk else None
            state = run.get("state") or "done"
            if mk.get("state") == "running":
                state = "running"
            rows.append(dict(id=ep["id"], series=x, no=ep.get("no"), title=ep.get("title"),
                             stage=run.get("stage") or ("make" if mk else None), make=make,
                             state=state, cells=cells, spent=ep_spent, pick=n_pick,
                             done=done, total=len(cells), paused=run.get("paused"),
                             eta_min=max(1, round((len(cells) - done) * 1.5)) if run.get("state") == "running" else None))
    live = [r for r in runs if r[3]] or sorted(runs)[-1:]       # the runs going now, else the latest one
    spent = sum(r[1] for r in live)
    approved = sum(r[2] for r in live)
    left = sum(r["total"] - r["done"] for r in rows if r["state"] == "running")
    return dict(rows=rows, alerts=alerts[-6:], spent=round(spent, 1), approved=round(approved, 1),
                running=running, eta=time.strftime("%H:%M", time.localtime(time.time() + left * 90)) if left else None,
                limits={p: PR.info(p).get("concurrency") for p in running})
