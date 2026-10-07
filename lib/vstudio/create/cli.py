"""python -m vstudio.create <command> ... --json   (one JSON object on stdout; errors {error: {code, params}},
exit code 2). ``--json-events``: progress as JSON lines (``{"event": ...}``) before the final ``{"result": ...}``.

    formats                                   providers [--detect] [--local]
    plan --prompt P [--format F] [--budget CNY] [--platforms a,b] [--lang zh|en|fr] [--mode template] -> draft
    series new --draft FILE|--draft-json JSON | series show SID | series list | sample [--lang L]
    bible revise SID (--instruction TEXT | --patch-json JSON)      ideas SID [--n 4]
    episodes add SID --ideas i1,i2            script write EID | script revise EID --instruction TEXT
    board show EID | board set EID --shot 07 --source cloud:veo/veo-3.1-fast | board route EID --instruction T [--apply]
    estimate EID --stage stills|animatic|drafts|finals [--only 07,09]
    run EID --stage S [--estimate ID --confirm CODE --max-cny N] [--allow-unknown] [--only 07]   stop EID
    making [--series SID]                     takes pick EID --shot 07 --take FILE | takes import EID FILES...
    prompts EID                               (即梦: the prompts to paste; you press Generate on the site)
    handoff EID [--languages zh,en,fr] [--no-schedule]
    record ingest DIR --target project:talkinghead|shot:EID/NO [--series SID] | record recover
    spend [--series SID] [--set-cap CNY]
    plugins [list | enable KEY | disable KEY | set KEY --settings-json J]     (KEY = <kind>:<id>; docs/PLUGINS.md)
    import PATH [--into EID] [--importer ID] [--format F]   a board (HyperFrames, shot list, EDL / OTIO / XML)
    make EID [--only 01,02] [--lanes N]       plugin: / agent: shots in parallel lanes (job folders, QC, takes)
Global: --home DIR (store root instead of $VSTUDIO_HOME).
"""
import argparse
import json
import sys

from . import formats as F
from .i18n import CreateError


def _csv(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def parser():
    ap = argparse.ArgumentParser(prog="python -m vstudio.create", description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--json-events", action="store_true")
    ap.add_argument("--home")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("formats")
    s = sub.add_parser("providers")
    s.add_argument("--detect", action="store_true")
    s.add_argument("--local", action="store_true")
    s = sub.add_parser("plan")
    s.add_argument("--prompt", default="")
    s.add_argument("--format")
    s.add_argument("--budget", type=float)
    s.add_argument("--platforms")
    s.add_argument("--lang", default="en")
    s.add_argument("--mode", choices=["auto", "template"], default="auto",
                   help="template = the format's own outline, no AI call ('Start from the template')")
    s = sub.add_parser("series")
    s.add_argument("action", choices=["new", "show", "list", "set"])
    s.add_argument("sid", nargs="?")
    s.add_argument("--draft")
    s.add_argument("--draft-json")
    s.add_argument("--budget", help="series budget in CNY, or 'none'")
    s.add_argument("--platforms")
    s = sub.add_parser("sample")
    s.add_argument("--lang", default="en")
    s = sub.add_parser("bible")
    s.add_argument("action", choices=["revise", "show"])
    s.add_argument("sid")
    s.add_argument("--instruction")
    s.add_argument("--patch-json")
    s = sub.add_parser("ideas")
    s.add_argument("sid")
    s.add_argument("--n", type=int, default=4)
    s = sub.add_parser("episodes")
    s.add_argument("action", choices=["add"])
    s.add_argument("sid")
    s.add_argument("--ideas", required=True)
    s = sub.add_parser("script")
    s.add_argument("action", choices=["write", "revise"])
    s.add_argument("eid")
    s.add_argument("--instruction")
    s = sub.add_parser("board")
    s.add_argument("action", choices=["show", "set", "route"])
    s.add_argument("eid")
    s.add_argument("--shot")
    s.add_argument("--source")
    s.add_argument("--instruction")
    s.add_argument("--apply", action="store_true")
    s = sub.add_parser("estimate")
    s.add_argument("eid")
    s.add_argument("--stage", default="finals")
    s.add_argument("--only")
    s = sub.add_parser("run")
    s.add_argument("eid")
    s.add_argument("--stage", required=True)
    s.add_argument("--estimate")
    s.add_argument("--confirm")
    s.add_argument("--max-cny", type=float)
    s.add_argument("--allow-unknown", action="store_true")
    s.add_argument("--only")
    s.add_argument("--check", action="store_true", help="run the spend gate only (no side effects)")
    s.add_argument("--no-early-stop", action="store_true", help="do not pause after 2 failed hard shots")
    s = sub.add_parser("stop")
    s.add_argument("eid")
    s = sub.add_parser("making")
    s.add_argument("--series")
    s = sub.add_parser("status")
    s.add_argument("--series")
    s = sub.add_parser("takes")
    s.add_argument("action", choices=["pick", "import"])
    s.add_argument("eid")
    s.add_argument("files", nargs="*")
    s.add_argument("--shot")
    s.add_argument("--take")
    s = sub.add_parser("prompts")
    s.add_argument("eid")
    s = sub.add_parser("handoff")
    s.add_argument("eid")
    s.add_argument("--languages")
    s.add_argument("--no-schedule", action="store_true")
    s.add_argument("--no-register", action="store_true")
    s = sub.add_parser("record")
    s.add_argument("action", choices=["ingest", "recover"])
    s.add_argument("dir", nargs="?")
    s.add_argument("--target", default="project:talkinghead")
    s.add_argument("--series")
    s = sub.add_parser("spend")
    s.add_argument("--series")
    s.add_argument("--set-cap", type=float)
    s = sub.add_parser("plugins")
    s.add_argument("action", nargs="?", default="list", choices=["list", "enable", "disable", "set"])
    s.add_argument("key", nargs="?")
    s.add_argument("--settings-json")
    s.add_argument("--lang", default="en")
    s = sub.add_parser("import")
    s.add_argument("path")
    s.add_argument("--into")
    s.add_argument("--importer")
    s.add_argument("--format")
    s.add_argument("--lang", default="en")
    s.add_argument("--sniff", action="store_true", help="only say which importer reads it")
    s = sub.add_parser("make")
    s.add_argument("eid")
    s.add_argument("--only")
    s.add_argument("--lanes", type=int)
    return ap


def dispatch(a, on_event=None):
    from . import bible as BI, costs, handoff as HO, jobs, providers as PR, record as RE, routing, sample, script, \
        store, views
    c = a.cmd
    if c == "formats":
        return dict(formats=[F.public(f) for f in F.load_all()])
    if c == "providers":
        return dict(providers=PR.detect(include_local=a.local) if a.detect or a.local else PR.list_info(),
                    rates_version=costs.load_rates().get("version"))
    if c == "plan":
        if a.format:
            F.get(a.format)
        return dict(draft=BI.plan_series(a.prompt, a.format, a.budget, _csv(a.platforms), a.lang, mode=a.mode,
                                         on_event=on_event))
    if c == "series":
        if a.action == "list":
            return dict(series=views.list_series())
        if a.action == "show":
            return views.series_view(store.need_sid(a.sid))
        if a.action == "set":
            s = store.load_series_file(store.need_sid(a.sid))
            meta = s.setdefault("spec", {}).setdefault("create", {})
            if a.budget is not None:
                meta["budget_cny"] = None if a.budget == "none" else costs.check_money(a.budget)
            if a.platforms is not None:
                s.setdefault("params", {})["platforms"] = _csv(a.platforms)
            store.save_series_file(s)
            return views.series_view(a.sid)
        raw = a.draft_json if a.draft_json else open(a.draft, encoding="utf-8").read() if a.draft else None
        if not raw:
            raise CreateError("bad-input", field="draft")
        draft = json.loads(raw)
        F.get(draft.get("format"))
        sid = BI.create_series(draft)
        return dict(ok=True, series=sid, view=views.series_view(sid))
    if c == "sample":
        return sample.open_sample(a.lang)
    if c == "bible":
        store.need_sid(a.sid)
        if a.action == "show":
            return dict(bible=store.load_bible(a.sid))
        patch = json.loads(a.patch_json) if a.patch_json else None
        return dict(bible=BI.revise_bible(a.sid, a.instruction, patch))
    if c == "ideas":
        return dict(ideas=BI.more_ideas(store.need_sid(a.sid), a.n))
    if c == "episodes":
        eps = script.add_episodes(store.need_sid(a.sid), _csv(a.ideas), on_event=on_event)
        for e in eps:
            jobs.run_stills(e["id"])
        return dict(ok=True, episodes=[e["id"] for e in eps])
    if c == "script":
        store.need_eid(a.eid)
        if a.action == "write":
            ep = store.load_episode(a.eid)
            script.write(ep)
            store.save_episode(ep)
            jobs.run_stills(a.eid)
        else:
            script.revise(a.eid, a.instruction)
            jobs.run_stills(a.eid)
        return views.episode_view(a.eid)
    if c == "board":
        store.need_eid(a.eid)
        if a.action == "set":
            jobs.set_source(a.eid, a.shot, a.source)
            return views.episode_view(a.eid)
        if a.action == "route":
            ep, s, fmt, _ = jobs.context(a.eid)
            routes, _, _ = jobs.plan(ep, s, fmt)
            changes = routing.rule_instruction(ep, routes, a.instruction, PR.connected())
            if a.apply:
                for ch in changes:
                    jobs.set_source(a.eid, ch["no"], ch["to"])
            return dict(changes=changes, applied=bool(a.apply), view=views.episode_view(a.eid) if a.apply else None)
        return views.episode_view(a.eid)
    if c == "estimate":
        return jobs.estimate(store.need_eid(a.eid), a.stage, only=_csv(a.only) or None)
    if c == "run":
        if a.check:
            if a.stage == "finals":
                jobs.gate(store.need_eid(a.eid), a.estimate, a.confirm, a.max_cny, a.allow_unknown, _csv(a.only) or None)
            return dict(ok=True, checked=True)
        return jobs.run(store.need_eid(a.eid), a.stage, a.estimate, a.confirm, a.max_cny, a.allow_unknown,
                        only=_csv(a.only) or None, on_event=on_event, early_stop=not a.no_early_stop)
    if c == "stop":
        return jobs.stop(store.need_eid(a.eid))
    if c in ("making", "status"):
        return views.making(store.need_sid(a.series) if a.series else None)
    if c == "takes":
        if a.action == "pick":
            return jobs.pick(store.need_eid(a.eid), a.shot, a.take)
        return jobs.import_takes(store.need_eid(a.eid), a.files)
    if c == "prompts":
        return dict(prompts=jobs.manual_prompts(store.need_eid(a.eid)))
    if c == "handoff":
        return HO.handoff(store.need_eid(a.eid), _csv(a.languages) or None, schedule=not a.no_schedule,
                          register=not a.no_register, on_event=on_event)
    if c == "record":
        if a.action == "recover":
            return dict(recovered=RE.recover())
        return RE.ingest(a.dir, a.target, a.series, on_event=on_event)
    if c == "spend":
        if a.set_cap is not None:
            costs.set_cap(a.set_cap)
        return costs.summary(store.need_sid(a.series) if a.series else None)
    if c == "plugins":
        return _plugins(a)
    if c == "import":
        from vstudio.plugins import importing as IM
        if a.sniff:
            return dict(importers=IM.sniff(a.path))
        if a.into:
            return IM.into_episode(store.need_eid(a.into), a.path, a.importer)
        return IM.into_new_series(a.path, a.importer, a.format, a.lang)
    if c == "make":
        from vstudio.plugins import lanes
        return lanes.make(store.need_eid(a.eid), only=_csv(a.only) or None, lanes=a.lanes, on_event=on_event)
    raise CreateError("bad-input", field="command")


def _plugins(a):
    from vstudio.plugins import registry as R
    try:
        if a.action == "list":
            return R.listing(a.lang)
        if not a.key:
            raise CreateError("bad-input", field="key")
        if a.action in ("enable", "disable"):
            return dict(plugin=R.set_enabled(a.key, a.action == "enable"))
        return dict(plugin=R.set_settings(a.key, json.loads(a.settings_json or "{}")))
    except R.PluginError as e:
        raise CreateError(e.code, status=404 if e.code.endswith("not-found") else 409, **e.params) from e


def main(argv=None):
    a = parser().parse_args(argv)
    from . import store
    if a.home:
        store.configure(a.home)

    def emit(ev):
        if a.json_events:
            sys.stdout.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
            sys.stdout.flush()
    try:
        res = dispatch(a, on_event=emit)
    except CreateError as e:
        out = e.doc()
        out["error"]["status"] = e.status
        print(json.dumps({"result": out} if a.json_events else out, ensure_ascii=False, default=str))
        return 2
    print(json.dumps({"result": res} if a.json_events else res, ensure_ascii=False, default=str,
                     indent=None if (a.json or a.json_events) else 1))
    return 0
