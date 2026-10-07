"""python -m vstudio.intake analyze | plan | revise | apply | schema  (every command: --json -> one document)."""
import argparse
import json
import sys

from . import apply as AP
from . import inventory as I
from . import plan as PL


def _out(a, obj, text=None):
    if a.json or text is None:
        print(json.dumps(obj, ensure_ascii=False, indent=None if a.json else 1, default=str))
    else:
        print(text)


def _echo(a):
    return (lambda s: print(s, file=sys.stderr)) if not a.quiet else None


def _save(path, obj):
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _plan_text(p):
    lines = [p["summary_zh"], ""]
    for x in p["projects"]:
        it = x["items"]
        lines.append(f"[{x['id']}] {x['recipe']} ({x['recipe_label']}) - {x['name']}: {it['method']}"
                     f" x{it.get('count') or '?'}  params {json.dumps(x['params'], ensure_ascii=False)}")
        for r in it.get("rows") or []:
            rng = (r.get("params") or {}).get("range")
            lines.append(f"    {r['id']}: {rng} {(r.get('params') or {}).get('title', '')}  {r.get('why', '')}")
        need = [c["label"] for c in x["checkpoints"] if c["needs_you"]]
        lines.append(f"    needs you: {', '.join(need)} | est {x['estimate']['wall_min']} min, ${x['estimate']['api_usd']}")
    for q in p.get("questions") or []:
        lines.append(f"? {q['text']} {q.get('options') or ''} (default {q.get('default')})")
    for r in p.get("risks") or []:
        lines.append(f"! {r}")
    for w in p.get("warnings") or []:
        lines.append(f"warning: {w}")
    pl = p["planner"]
    lines.append(f"planner: {pl.get('provider')} {pl.get('model') or ''} fallback={pl.get('fallback')} {pl.get('reason') or ''}")
    return "\n".join(lines)


def cmd_analyze(a):
    res = I.analyze(a.inputs, asr=a.asr, use_cache=not a.no_cache, language=a.language, echo=_echo(a))
    _save(a.out, res)
    view = res if a.full else dict(I.compact(res), digest=res["digest"], seconds=res["seconds"], asr=res["asr"],
                                    inputs=res["inputs"], hashes={f["id"]: f.get("qhash") for f in res["files"]})
    lines = [f"{res['totals']}"] + [f"{f['id']} {f['kind']:5} {I.material_role(f):16} {f['rel']}" for f in res["files"]]
    _out(a, view, "\n".join(lines))
    return 0


def cmd_plan(a):
    analysis = _load(a.analysis) if a.analysis else None
    p = PL.make_plan(a.prompt, a.inputs, client=a.client, provider=a.provider, model=a.model, analysis=analysis,
                     asr=a.asr, auto=[x for x in (a.auto or "").split(",") if x], echo=_echo(a), language=a.language,
                     timeout=a.timeout)
    _save(a.out, p)
    _out(a, p, _plan_text(p))
    return 0


def cmd_revise(a):
    p = PL.revise(_load(a.plan), a.prompt, provider=a.provider, model=a.model, client=a.client, echo=_echo(a),
                  timeout=a.timeout)
    _save(a.out or (a.plan if a.in_place else None), p)
    _out(a, p, _plan_text(p))
    return 0


def cmd_apply(a):
    try:
        res = AP.apply_plan(_load(a.plan), a.out, run=a.run, dry_run=a.dry_run, echo=_echo(a))
    except (AP.ApplyError, ValueError) as e:
        _out(a, dict(ok=False, error=str(e)), f"error: {e}")
        return 5
    _out(a, res, "\n".join([f"{c['id']} {c['recipe']}: {c['dir']} items {c.get('items')}" for c in res["projects"]] +
                           ["next:"] + [f"  python -m {n}" for n in res.get("next") or []]))
    return 0


def cmd_schema(a):
    _out(a, PL.schema())
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="python -m vstudio.intake", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        p = sub.add_parser(name, help=help_)
        p.set_defaults(fn=fn)
        p.add_argument("--json", action="store_true", help="one JSON document on stdout")
        p.add_argument("--quiet", action="store_true", help="no progress on stderr")
        return p

    p = add("analyze", cmd_analyze, "inventory files / folders (video, audio, images, pdf / docx / pptx / md / srt)")
    p.add_argument("--inputs", nargs="+", required=True)
    p.add_argument("--asr", default="sample", choices=["off", "sample", "full"])
    p.add_argument("--language", help="ASR language (default: persona)")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--full", action="store_true", help="every fact and path (default: the compact summary)")
    p.add_argument("--out", help="also write the full analysis JSON here")

    p = add("plan", cmd_plan, "natural-language request + materials -> plan JSON")
    p.add_argument("--prompt", required=True)
    p.add_argument("--inputs", nargs="+")
    p.add_argument("--analysis", help="a saved `analyze --out` file instead of --inputs")
    p.add_argument("--client", help="client folder or slug (defaults, llm routes)")
    p.add_argument("--provider", help="LLM provider for task intake (default: the route; none = rules only)")
    p.add_argument("--model")
    p.add_argument("--timeout", type=float, help="seconds per CLI provider attempt (default 90, env "
                                                 "VSTUDIO_LLM_CLI_TIMEOUT); then the route's fallback")
    p.add_argument("--asr", default="auto", choices=["off", "sample", "auto", "full"],
                   help="auto: full transcript only for videos the request selects content from (<= 45 min)")
    p.add_argument("--language")
    p.add_argument("--auto", help="checkpoints the projects may answer with their default (e.g. hook,cover)")
    p.add_argument("--out", help="write the plan JSON here")

    p = add("revise", cmd_revise, "update a plan from a follow-up instruction")
    p.add_argument("--plan", required=True)
    p.add_argument("--prompt", required=True)
    p.add_argument("--client")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--timeout", type=float, help="seconds per CLI provider attempt (default 90)")
    p.add_argument("--out")
    p.add_argument("--in-place", action="store_true", help="overwrite --plan")

    p = add("apply", cmd_apply, "create the project(s) from a plan (a series when mixed); pilot run optional")
    p.add_argument("--plan", required=True)
    p.add_argument("--out", help="parent folder of the project folders (default $VSTUDIO_HOME/projects/<plan id>)")
    p.add_argument("--run", action="store_true", help="start each project's pilot run right away")
    p.add_argument("--dry-run", action="store_true")

    add("schema", cmd_schema, "the plan JSON Schema")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    return a.fn(a)
