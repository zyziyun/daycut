"""Manifest -> vstudio.batch Recipe: the stage graph (reused batch stages, adapter stages, generic script stages)
plus one **gate stage** per checkpoint.

A gate (``cp_<id>``, resource ``cpu``) runs after the checkpoint's ``after`` stage and before the stages it
``blocks`` (default: every direct dependent of ``after``). It builds the checkpoint payload (options, default,
preview paths), writes it to ``state/checkpoints/<item>/<id>.json`` and

* passes when the payload says there is nothing to decide (``skip``), or when the item's params carry an answer
  (``_answers[<id>] = {value, digest}``) whose digest still matches the payload options (``reask``);
* otherwise raises ``CheckpointPending``: ``ProjectRunner`` (core.py) parks the item in state ``waiting``
  (no circuit-breaker count), the app renders the payload, ``project checkpoint --answer`` records the answer in
  project.yaml (+ the param changes the checkpoint's ``apply`` derives, e.g. a cleanup reply) and the next run
  continues. The gate's stage key hashes the answer, so a changed answer re-runs exactly the stages downstream.

Adapter stages get an ``Env`` (paths, params, dep outputs, templating, a subprocess helper); ``run:`` stages run a
workflow script through the generic script adapter with templated argv (workflow scripts stay unchanged).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace

from vstudio.batch import recipes as RC
from vstudio.batch import spec as S
from vstudio.batch.recipes import Recipe, Stage
from vstudio.batch.util import read_json, sha1_json, write_json

from . import manifests as M

LIB = os.path.join(M.ROOT, "lib")
PREFIX = "project:"


class CheckpointPending(Exception):
    """Raised by a gate stage: the item waits for a human (or agent) answer. Never transient, never retried."""

    def __init__(self, cp, job, payload_path=None):
        self.cp, self.job, self.payload_path = cp, job, payload_path
        super().__init__(f"checkpoint {cp} waits for an answer (item {job})")


# --------------------------------------------------------------------------- env for adapters
def public_params(p):
    return {k: v for k, v in (p or {}).items() if not str(k).startswith("_")}


def file_sha(path, n=16):
    try:
        h = hashlib.sha1()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        return h.hexdigest()[:n]
    except OSError:
        return None


def static_tctx(m, params, job_id=None):
    """Template context without a running stage (keys, watch files, author paths, context dumps)."""
    p = params or {}
    plats = list(p.get("platforms") or [])
    t = dict(public_params(p))
    t.update(vstudio=M.ROOT, workflow_dir=os.path.join(M.WORKFLOWS, m["workflow"]), python=sys.executable,
             project_dir=p.get("_project_dir") or "", item_dir=p.get("_item_dir") or "",
             state_dir=os.path.join(p.get("_project_dir") or "", "state"), item=job_id or p.get("_item") or "",
             platform=plats[0] if plats else "", platforms=plats, platforms_csv=",".join(plats),
             params=public_params(p), input=dict(p.get("_inputs") or {}), source=p.get("source") or "")
    return t


class Env:
    """What an adapter stage function receives (``fn(env) -> outputs dict``)."""

    def __init__(self, ctx, m, entry):
        self.ctx, self.m, self.entry = ctx, m, entry
        self.params, self.spec, self.inputs = ctx.params, ctx.spec, ctx.inputs
        self.job = ctx.job["id"]
        self.dir = ctx.dir
        self.item_dir = self.params.get("_item_dir") or ctx.dir
        self.project_dir = self.params.get("_project_dir") or ctx.batch_dir
        self.state_dir = ctx.batch_dir
        self.workflow_dir = os.path.join(M.WORKFLOWS, m["workflow"])

    def path(self, *names):
        return os.path.join(self.dir, *names)

    def item_path(self, *names):
        os.makedirs(self.item_dir, exist_ok=True)
        return os.path.join(self.item_dir, *names)

    def log(self, msg):
        self.ctx.log(msg)

    def tctx(self):
        t = static_tctx(self.m, self.params, self.job)
        t.update(stage_dir=self.dir, out={k: v for k, v in (self.inputs or {}).items()})
        return t

    def fmt(self, text):
        return M.fmt(text, self.tctx())

    def args(self, argv):
        return M.fmt_args(argv, self.tctx())

    def run(self, argv, cwd=None, env=None, timeout=None, log="run.log", ok=(0,)):
        """Run a subprocess (PYTHONPATH gets lib/); its command + output go to <stage dir>/<log>; a non-ok exit
        raises RuntimeError with the tail of the output."""
        e = dict(os.environ)
        e["PYTHONPATH"] = LIB + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
        e.update({k: str(v) for k, v in (env or {}).items()})
        cwd = cwd or self.item_dir
        os.makedirs(cwd, exist_ok=True)
        r = subprocess.run([str(a) for a in argv], cwd=cwd, capture_output=True, text=True, env=e, timeout=timeout)
        with open(self.path(log), "w", encoding="utf-8") as f:
            f.write(" ".join(map(str, argv)) + f"\n(cwd {cwd}, exit {r.returncode})\n\n" + (r.stdout or "")
                    + "\n--- stderr ---\n" + (r.stderr or ""))
        if r.returncode not in tuple(ok):
            tail = ((r.stderr or "") + (r.stdout or ""))[-1500:]
            raise RuntimeError(f"{os.path.basename(str(argv[1] if len(argv) > 1 else argv[0]))} exit "
                               f"{r.returncode}: {tail}")
        return r


def when_ok(when, params):
    for k, v in (when or {}).items():
        pv = (params or {}).get(k)
        if isinstance(v, dict) and "nonempty" in v:   # {param: {nonempty: true}}: set and not empty
            if bool(pv) != bool(v["nonempty"]):
                return False
        elif isinstance(v, list):
            if pv not in v:
                return False
        elif pv != v:
            return False
    return True


# --------------------------------------------------------------------------- generic script stage
def _set_dotted(d, key, value):
    cur = d
    parts = key.split(".")
    for k in parts[:-1]:
        cur = cur.setdefault(k, {})
    cur[parts[-1]] = value


def _native(v, tctx):
    """A template that is exactly one ``{name}`` keeps the value's type (lists, numbers) in a patched config."""
    if isinstance(v, str):
        mo = M._TPL.fullmatch(v)
        if mo and not mo.group(2):
            try:
                return M.lookup(tctx, mo.group(1))
            except M.Missing:
                return None
        return M.fmt(v, tctx)
    if isinstance(v, list):
        return [_native(x, tctx) for x in v]
    if isinstance(v, dict):
        return {k: _native(x, tctx) for k, x in v.items()}
    return v


def patch_config(env, patch):
    """Load the item's JSON / YAML config (seeded from a template when missing), set the templated keys, write it
    back. Keys whose value renders to None are left alone."""
    t = env.tctx()
    path = M.fmt(patch["file"], t)
    src = M.fmt(patch["from"], t) if patch.get("from") else path
    if not os.path.exists(path) and patch.get("seed"):
        seed = M.fmt(patch["seed"], t)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        shutil.copy(seed if os.path.isabs(seed) else os.path.join(M.ROOT, seed), path)
    yml = path.endswith((".yaml", ".yml"))
    if os.path.exists(src):
        with open(src, encoding="utf-8") as f:
            import yaml
            data = (yaml.safe_load(f) if yml else json.load(f)) or {}
    else:
        data = {}
    for k, v in patch["set"].items():
        val = _native(v, t)
        if val is not None:
            _set_dotted(data, k, val)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if yml:
            import yaml
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        else:
            json.dump(data, f, ensure_ascii=False, indent=1)
    return path


def script_stage(env):
    """``run:`` stage: optional config patch, then the workflow script with templated argv / cwd / env."""
    r = env.entry["run"]
    patched = patch_config(env, r["patch"]) if r.get("patch") else None
    argv = env.args(r["argv"])
    cwd = env.fmt(r.get("cwd") or "{item_dir}")
    res = env.run(argv, cwd=cwd, env={k: env.fmt(v) for k, v in (r.get("env") or {}).items()},
                  timeout=r.get("timeout"), ok=tuple(r.get("ok_codes") or (0,)))
    out = dict(cmd=argv, cwd=cwd, exit=res.returncode, stdout_tail=(res.stdout or "")[-2000:])
    if r.get("stdout"):
        p = env.fmt(r["stdout"])
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(res.stdout or "")
        out["stdout_file"] = p
    files = [env.fmt(f) for f in r.get("files") or []]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        raise RuntimeError(f"{env.entry['id']}: the script wrote no {', '.join(missing)}")
    files += [f for f in (env.fmt(x) for x in r.get("optional_files") or []) if os.path.exists(f)]
    if patched:
        out["config"] = patched
    out["files"] = files
    out["digest"] = sha1_json([file_sha(f) for f in files])[:16] if files else None
    return out


# --------------------------------------------------------------------------- stages from the manifest
def _units(kind):
    if kind == "duration":
        return lambda j, s: float(j["params"].get("_dur") or 0.0)
    if kind == "platforms":
        return lambda j, s: float(j["params"].get("_dur") or 0.0) * max(1, len(j["params"].get("platforms") or []))
    return lambda j, s: 1.0


def _keyfn(m, e):
    keys, watch = e.get("keys"), e.get("watch") or []

    def f(job, spec):
        p = job["params"]
        d = {k: p.get(k) for k in keys} if keys is not None else public_params(p)
        d["_inputs"] = p.get("_inputs")
        if watch:
            t = static_tctx(m, p, job["id"])
            d["_watch"] = {w: file_sha(M.fmt(w, t)) for w in watch}
        return d
    return f


def _wrap(m, e, fn):
    def stage_fn(ctx):
        return fn(Env(ctx, m, e)) or {}
    stage_fn.__name__ = f"{m['id']}.{e['id']}"
    return stage_fn


def make_stage(m, e, names):
    fn = script_stage if e.get("run") else M.resolve_ref(e["fn"])
    when = e.get("when")
    cost = M.resolve_ref(e["cost"]) if e.get("cost") else None
    return Stage(e["id"], e["resource"], _wrap(m, e, fn), deps=tuple(d for d in e.get("deps") or [] if d in names),
                 params=_keyfn(m, e), units=_units(e.get("units")), enabled=lambda j, s, w=when: when_ok(w, j["params"]),
                 paid=bool(e.get("paid")), retries=0 if e.get("paid") else 1, shared=bool(e.get("shared")),
                 **({"cost": cost} if cost else {}))


# --------------------------------------------------------------------------- gates
def answer_of(params, cp_id):
    a = ((params or {}).get("_answers") or {}).get(cp_id)
    return a if isinstance(a, dict) and "value" in a else None


def checkpoint_dir(state_dir, job):
    return os.path.join(state_dir, "checkpoints", job)


def finalize_payload(env, cp, payload):
    p = dict(payload or {})
    opts = p.get("options") or []
    p.update(id=cp["id"], kind=cp["kind"], scope=cp["scope"], item=env.job, recipe=env.m["id"],
             project_dir=env.project_dir, labels=cp["labels"], help=cp.get("help"), answer_schema=cp["answer"],
             auto=cp.get("auto", "never"), batch_by=cp.get("batch_by"), aggregate=cp.get("aggregate") or [],
             stage=M.GATE_PREFIX + cp["id"], after=cp["after"])
    if "default" not in p and "default" in cp:
        p["default"] = cp["default"]
    p.setdefault("digest", sha1_json(opts)[:16])
    p.setdefault("previews", [])
    p["previews"] = [x for x in p["previews"] if x and (not isinstance(x, dict) or x.get("path"))]
    return p


def default_payload(env, cp):
    """No payload adapter: the ``after`` stage's files as previews, no options."""
    out = env.inputs.get(cp["after"]) or {}
    return dict(options=[], previews=[dict(kind="file", path=f) for f in out.get("files") or []][:12])


def run_gate(env, cp):
    pay = M.resolve_ref(cp["payload"])(env, cp) if cp.get("payload") else default_payload(env, cp)
    pay = finalize_payload(env, cp, pay)
    cdir = checkpoint_dir(env.state_dir, env.job)
    path = write_json(os.path.join(cdir, f"{cp['id']}.json"), pay)
    write_json(env.path("checkpoint.json"), pay)
    files = [path]
    if pay.get("skip") or (cp.get("auto") == "skip-if-empty" and not pay.get("options")):
        return dict(state="skipped", reason=pay.get("skip_reason") or "nothing to decide", payload=path, files=files)
    ans = answer_of(env.params, cp["id"])
    reask = cp.get("reask", cp["kind"] != "author")      # authored files: edits re-run the watchers, no re-ask
    if ans is not None and (not reask or not ans.get("digest") or ans["digest"] == pay["digest"]):
        return dict(state="answered", answer=ans["value"], payload=path, files=files)
    raise CheckpointPending(cp["id"], env.job, path)


def gate_stage(m, cp, names=()):
    def fn(ctx):
        return run_gate(Env(ctx, m, cp), cp)
    fn.__name__ = f"{m['id']}.gate.{cp['id']}"

    def params(job, spec):
        return dict(answer=answer_of(job["params"], cp["id"]), v=1)
    return Stage(M.GATE_PREFIX + cp["id"], "cpu", fn, deps=(cp["after"], *[n for n in cp.get("needs") or []
                                                                       if n in names and n != cp["after"]]),
                 params=params,
                 enabled=lambda j, s, w=cp.get("when"): when_ok(w, j["params"]), retries=0, drain=False)


# --------------------------------------------------------------------------- recipe
def recipe_name(m, batch=None):
    return f"{PREFIX}{m['id']}" + (f"@{batch}" if batch and isinstance((m.get('engine') or {}).get('batch_recipe'),
                                                                        dict) else "")


def batch_for(m, params):
    br = (m.get("engine") or {}).get("batch_recipe")
    if not br:
        return None
    if isinstance(br, str):
        return br
    v = (params or {}).get(br["param"])
    if v is None:
        v = M.param_defaults(m).get(br["param"])
    if v not in br["map"]:
        raise ValueError(f"{m['id']}: {br['param']}={v!r} not one of {sorted(br['map'])}")
    return br["map"][v]


def build(m, batch=None):
    stages = {}
    if batch:
        for bs in RC.get(batch).stages:
            stages[bs.name] = bs
    names = set(stages) | {e["id"] for e in m["stages"] if not e.get("from_batch")}
    for e in m["stages"]:
        if e.get("from_batch"):
            if e["id"] in stages and e.get("extra_deps"):
                bs = stages[e["id"]]
                extra = tuple(d for d in e["extra_deps"] if d in names and d not in bs.deps)
                stages[e["id"]] = replace(bs, deps=tuple(bs.deps) + extra)
            continue
        stages[e["id"]] = make_stage(m, e, names)
    for cp in m["checkpoints"]:
        if cp["after"] not in stages:
            continue                                   # not in this engine variant
        g = gate_stage(m, cp, set(stages))
        blocks = cp.get("blocks") or [n for n, s in stages.items()
                                      if cp["after"] in s.deps and not n.startswith(M.GATE_PREFIX)]
        for b in blocks:
            if b in stages and g.name not in stages[b].deps:
                stages[b] = replace(stages[b], deps=tuple(stages[b].deps) + (g.name,))
        stages[g.name] = g
    r = Recipe(recipe_name(m, batch), list(stages.values()), expand_items,
               description=m["description"]["en"], label=m["labels"]["en"],
               inputs=[dict(key=i["key"], label=i["labels"]["en"], kind=i["kind"], required=i["required"])
                       for i in m["inputs"]],
               row_keys=list(m["items"].get("per_item") or []))
    r.order()
    return r


def variants(m):
    br = (m.get("engine") or {}).get("batch_recipe")
    if isinstance(br, dict):
        return list(dict.fromkeys(br["map"].values()))
    return [br] if br else [None]


# --------------------------------------------------------------------------- items
def _probe_dur(path):
    try:
        from vstudio import media
        return float(media.probe(path)["duration"])
    except Exception:  # noqa: BLE001  (not media / unreadable: duration unknown)
        return 0.0


VIDEO_KINDS = ("video",)


def seed_author_files(m, params, job_id):
    t = static_tctx(m, params, job_id)
    for cp in m["checkpoints"]:
        a = cp.get("author")
        if not a or not a.get("template") or not when_ok(cp.get("when"), params):
            continue
        dst = M.fmt(a["file"], t)
        if not os.path.exists(dst):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            given = (params.get("_inputs") or {}).get("script")
            given = given[0] if isinstance(given, list) and given else given
            if given and dst.endswith(".md") and os.path.isfile(str(given)):
                shutil.copy(given, dst)              # the item's own draft seeds its script file
            else:
                shutil.copy(os.path.join(M.ROOT, a["template"]), dst)


def expand_items(spec, rows):
    """Recipe.expand of every project recipe: the batch recipe's own expansion (``engine.expand: batch``) or the
    generic one (row params over the defaults), then the project fields: ``_item_dir`` (the item's persistent
    workspace: authored files, workflow work/ and out/), ``source`` + ``_dur`` from the first video input, and the
    author templates seeded into the item folder."""
    pj = spec.get("project") or {}
    m = M.get(pj["recipe"])
    if (m.get("engine") or {}).get("expand") == "batch":
        items = RC.get(pj["batch"]).expand(spec, rows)
    else:
        items = [dict(item=r["id"], params=S.with_defaults(spec, r)) for r in rows]
    vkeys = [i["key"] for i in m["inputs"] if i["kind"] in VIDEO_KINDS]
    for it in items:
        p = it["params"]
        p.pop("_auto_id", None)
        p["_project_dir"] = pj["dir"]
        p["_item"] = it["item"]
        p["_item_dir"] = os.path.join(pj["dir"], "items", it["item"])
        os.makedirs(p["_item_dir"], exist_ok=True)
        ins = dict(p.get("_inputs") or {})
        if not p.get("source"):
            for k in vkeys:
                v = ins.get(k)
                v = v[0] if isinstance(v, list) and v else v
                if v:
                    p["source"] = os.path.abspath(v)
                    break
        if p.get("source") and not p.get("_dur"):
            d = _probe_dur(p["source"])
            rng = p.get("range")
            p["_dur"] = round((rng[1] - rng[0]) if rng else d, 3)
            p["_src_dur"] = round(d, 3)
        seed_author_files(m, p, it["item"])
    return items


def read_payload(state_dir, job, cp_id):
    return read_json(os.path.join(checkpoint_dir(state_dir, job), f"{cp_id}.json"))
