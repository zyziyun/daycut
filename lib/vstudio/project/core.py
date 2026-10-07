"""Project = a folder + a batch store; N items of one recipe (N=1 is a single video).

    <project>/project.yaml        the editable truth (recipe, params, items, answers, overrides, auto policy) - the
                                  app, the CLI and an embedded agent all edit this file; `refresh` re-plans from it
    <project>/items/<item>/       each item's persistent workspace: authored files (SCRIPT.md, edit.json, spec.py,
                                  timeline.yaml ...), the workflow's own work/ and out/ folders
    <project>/state/              the vstudio.batch batch (batch.db, jobs/<item>/<stage>/, cache/, checkpoints/)
    <project>/exports/            `export`: final files per item / platform + manifest.json (sha256)
    <project>/AGENTS.md, CLAUDE.md   agent hook (`context --write`): what to read, what to edit, which commands

project.yaml:
    version: 1
    name: my-talks
    recipe: talkinghead
    series: daily-tips            # presets inherited from $VSTUDIO_HOME/series/<id>/series.yaml (project wins)
    client: acme                  # optional vstudio.batch client workspace
    params: {style: mixed, platforms: [xiaohongshu:full]}          # project-level (shared) params
    inputs: {music: /abs/bgm.mp3}                                  # project-level inputs
    items: [{id: a, inputs: {video: /abs/a.mp4}, params: {title: ...}}, ...]
    variants: {by: [platform, hook, language], languages: [zh, en]}
    auto: [hook, publish]         # checkpoints `run` may answer with their default (never budget / consent)
    answers: {filler: {a: {value: {...}, digest: ..., at: ...}}, budget: {"*": {...}}}
    overrides: {a: {cleanup_reply: "确认 3,5"}}                     # params derived from answers, per job
    spec: {qc: {...}, budget: {...}, concurrency: {...}, asr: {...}}   # extra vstudio.batch spec sections
"""
import copy
import json
import os
import time

import yaml

from vstudio import messages as MSG
from vstudio.batch import recipes as RC
from vstudio.batch.run import BatchBusy, Runner, runner_active
from vstudio.batch.store import DB_NAME, Store
from vstudio.batch.util import now, read_json, sha256_file, slug, write_json

from . import build as B
from . import home as H
from . import manifests as M

EXIT = dict(done=0, failed=1, refused=2, paused=3, pilot=4, busy=6, waiting=7)
FILE_KINDS = ("video", "audio", "photos", "file", "script", "folder")
NEVER_AUTO = ("budget-approval", "consent")


class ProjectError(ValueError):
    pass


# --------------------------------------------------------------------------- runner
class ProjectRunner(Runner):
    """vstudio.batch Runner + checkpoints: a gate's ``CheckpointPending`` parks the item in ``waiting`` (not a
    failure: no circuit-breaker count, no red QC); the next run re-opens the gates of waiting items."""

    def _select(self):
        for j in self.store.jobs(["waiting", "planned", "running", "interrupted", "failed", "done"]):
            if self.only and j["id"] not in self.only:
                continue
            gates = [st for st, r in self.store.stage_rows(j["id"]).items()
                     if r["state"] == "failed" and str(r.get("error") or "").startswith("CheckpointPending")]
            for st in gates:                           # re-open the gate: it re-checks its answer
                self.store.set_stage(j["id"], st, state="pending", attempts=0, not_before=0, error=None)
            if j["state"] == "waiting" or (gates and j["state"] in ("failed", "done")):
                self.store.set_job(j["id"], state="planned", qc=None, qc_reasons=None)
        return super()._select()

    def _failed(self, jid, st, key, e):
        if not isinstance(e, B.CheckpointPending):
            return super()._failed(jid, st, key, e)
        self._set(jid, st.name, state="failed", error=f"CheckpointPending: {e.cp}", finished=now())
        self.store.log("checkpoint", f"{e.cp} waits", jid, st.name)
        pay = read_json(e.payload_path, {}) or {}
        self.emit("checkpoint", job=jid, checkpoint=e.cp, checkpoint_kind=pay.get("kind"), scope=pay.get("scope"),
                  payload=e.payload_path, labels=pay.get("labels"), n_options=len(pay.get("options") or []))
        self.say(f"{jid}: waiting at checkpoint {e.cp}")
        self._finish_job(jid, "waiting", [f"checkpoint {e.cp}"])

    def _finish_job(self, jid, state, reasons, qc=None):
        if state != "waiting":
            return super()._finish_job(jid, state, reasons, qc=qc)
        if jid not in self.active:
            return
        del self.active[jid]
        self.store.set_job(jid, state="waiting")
        j = self.store.job(jid)
        self.finished.append(dict(id=jid, state="waiting", qc=None, pilot=bool(j.get("pilot"))))
        self.store.log("job", f"waiting ({'; '.join(reasons or [])})", jid)
        self.emit("job-done", job=jid, state="waiting", qc=None, reasons=reasons or [])
        self._progress()


def _live_end(pdir, code, pend, failed):
    """The project's live status after a run (desk app 进行中 lane): needs-you at a checkpoint, done, failed."""
    from vstudio.batch import livestatus as LS
    if code == EXIT["waiting"] or code in (EXIT["paused"], EXIT["pilot"]):
        ids = sorted({p.get("id") for p in pend if p.get("id")})
        LS.write(pdir, "waiting", needs_you=True, by="project",
                 message=("checkpoint: " + ", ".join(ids)) if ids else "waits for you (pilot review / paused)")
    elif code == EXIT["failed"]:
        LS.write(pdir, "failed", by="project", message=f"{len(failed)} item(s) failed")
    elif code == EXIT["done"]:
        LS.write(pdir, "done", by="project", message="done")


def run_state(state_dir, **kw):
    r = ProjectRunner(state_dir, **kw)
    try:
        return r.run()
    finally:
        r.store.close()


# --------------------------------------------------------------------------- answers
class AnswerCtx:
    """What a checkpoint ``apply`` gets: the answer, the payload it answers, the job's params, paths."""

    def __init__(self, project, cp, job, value, payload, params):
        self.project, self.m, self.cp, self.job = project, project.manifest, cp, job
        self.value, self.payload, self.params = value, payload or {}, params or {}
        self.state_dir = project.state_dir

    def answer_path(self, name):
        d = os.path.join(self.state_dir, "answers", self.job)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, name)

    def tctx(self):
        return B.static_tctx(self.m, self.params, self.job)


def _deep_merge(a, b):
    out = copy.deepcopy(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _validate_answer(cp, value):
    try:
        import jsonschema
    except ImportError:
        return
    try:
        jsonschema.validate(value, cp["answer"])
    except jsonschema.ValidationError as e:
        raise ProjectError(f"answer to {cp['id']} invalid: {e.message}")


def _stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------------- the project
class Project:
    def __init__(self, pdir):
        self.dir = os.path.abspath(pdir)
        self.yaml_path = os.path.join(self.dir, "project.yaml")
        self.state_dir = os.path.join(self.dir, "state")
        if not os.path.exists(self.yaml_path):
            raise ProjectError(f"no project at {self.dir} (project.yaml missing) - `project new` first")
        self.data = self._read()
        self.manifest = M.get(self.data["recipe"])

    # ------------------------------------------------------------- file
    def _read(self):
        with open(self.yaml_path, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        for k in ("params", "inputs", "answers", "overrides", "spec", "variants"):
            d[k] = d.get(k) or {}
        d["items"] = d.get("items") or []
        d["auto"] = d.get("auto") or []
        return d

    def save(self):
        tmp = self.yaml_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, self.yaml_path)

    def reload(self):
        self.data = self._read()
        self.manifest = M.get(self.data["recipe"])
        return self

    # ------------------------------------------------------------- creation
    @classmethod
    def create(cls, pdir, recipe=None, name=None, inputs=None, params=None, items=None, series=None, client=None,
               variants=None, auto=None, spec=None, episodes=None, csv_path=None, list_path=None, folder=None,
               glob=None, exist_ok=False, write_agent_files=True):
        pdir = os.path.abspath(pdir)
        if os.path.exists(os.path.join(pdir, "project.yaml")) and not exist_ok:
            raise ProjectError(f"{pdir} already holds a project")
        ser = H.load_series(series) if series else {}
        recipe = recipe or ser.get("recipe")
        if not recipe:
            raise ProjectError("--recipe is required (or a --series with a recipe)")
        m = M.get(recipe)
        inputs = {k: (v if isinstance(v, list) else [v]) for k, v in (inputs or {}).items()}
        known = {i["key"]: i for i in m["inputs"]}
        for k in inputs:
            if k not in known:
                raise ProjectError(f"{recipe}: unknown input {k!r}; inputs: {', '.join(known)}")
        fi = m["items"].get("from_input")
        if folder:
            if not fi:
                raise ProjectError(f"{recipe}: items do not come from files (no items.from_input)")
            inputs.setdefault(fi, [])
            inputs[fi] += _folder_files(folder, glob, known[fi].get("accept"))
        for k, vs in inputs.items():
            if known[k]["kind"] in FILE_KINDS:
                inputs[k] = [os.path.abspath(os.path.expanduser(str(v))) for v in vs]
                missing = [v for v in inputs[k] if not os.path.exists(v)]
                if missing:
                    raise ProjectError(f"input {k}: missing {missing}")
        rows = list(items or [])
        if not rows and csv_path:
            rows = _csv_items(csv_path, known)
        if not rows and list_path:
            with open(list_path, encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
            key = next((i["key"] for i in m["inputs"] if i["kind"] == "text"), fi or "topic")
            rows = [dict(id=f"{k + 1:03d}", inputs={key: ln}) for k, ln in enumerate(lines)]
        if not rows and episodes:
            rows = [dict(id=f"ep{k + 1:02d}") for k in range(int(episodes))]
        if not rows and fi and inputs.get(fi):
            for v in inputs.pop(fi):
                stem = os.path.splitext(os.path.basename(v))[0] if known[fi]["kind"] in FILE_KINDS else v[:24]
                rows.append(dict(id=slug(stem) if known[fi]["kind"] in FILE_KINDS else None, inputs={fi: v}))
        if not rows and not m["items"].get("planner"):
            rows = [dict(id="main")]                     # a single video: N = 1
        seen = set()
        for k, r in enumerate(rows):
            rid = slug(r.get("id") or f"{k + 1:03d}")
            base, n = rid, 2
            while rid in seen:
                rid, n = f"{base}-{n}", n + 1
            seen.add(rid)
            r["id"] = rid
            r["inputs"] = dict(r.get("inputs") or {})
            r["params"] = dict(r.get("params") or {})
        proj_inputs = {k: (v if len(v) != 1 else v[0]) for k, v in inputs.items()}
        for i in m["inputs"]:
            if i["required"] and i["key"] not in proj_inputs and not (rows and all(i["key"] in r["inputs"] for r in rows)):
                raise ProjectError(f"{recipe}: input {i['key']} ({i['labels']['en']}) is required")
        unknown = [k for k in (params or {}) if k not in m["params"]["properties"]]
        if unknown:
            raise ProjectError(f"{recipe}: unknown params {unknown}; known: {', '.join(m['params']['properties'])}")
        check_params(m, dict(M.param_defaults(m), **{k: v for k, v in (ser.get("params") or {}).items()
                                                      if k in m["params"]["properties"]}, **(params or {})))
        os.makedirs(pdir, exist_ok=True)
        data = dict(version=1, name=name or os.path.basename(pdir), recipe=recipe, series=ser.get("id"),
                    client=client or ser.get("client"), created=_stamp(), params=dict(params or {}),
                    inputs=proj_inputs, items=rows, variants=dict(variants or {}),
                    auto=list(auto if auto is not None else ser.get("auto") or []), answers={}, overrides={},
                    spec=dict(spec or {}))
        with open(os.path.join(pdir, "project.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        p = cls(pdir)
        p.validate_params()
        H.register(pdir, data["name"], recipe, data["series"], data["client"])
        if rows:
            p.plan()
        if write_agent_files:
            p.write_agent_files()
        return p

    # ------------------------------------------------------------- params / spec
    def series(self):
        return H.load_series(self.data["series"]) if self.data.get("series") else {}

    def params(self):
        """Effective project-level params: manifest defaults < series params < project params."""
        out = M.param_defaults(self.manifest)
        props = self.manifest["params"]["properties"]
        out.update({k: v for k, v in (self.series().get("params") or {}).items() if k in props})
        out.update(self.data.get("params") or {})
        return out

    def validate_params(self):
        return check_params(self.manifest, self.params())

    def batch(self):
        return B.batch_for(self.manifest, self.params())

    def recipe_name(self):
        return B.recipe_name(self.manifest, self.batch())

    def recipe(self):
        from . import registry  # noqa: F401
        return RC.get(self.recipe_name())

    def checkpoint(self, cid):
        for c in self.manifest["checkpoints"]:
            if c["id"] == cid:
                return c
        raise ProjectError(f"{self.manifest['id']}: no checkpoint {cid!r}; "
                           f"known: {', '.join(c['id'] for c in self.manifest['checkpoints'])}")

    def jobs_rows(self):
        """project.yaml items -> batch job rows (variants expanded, answers + overrides attached)."""
        m, P = self.manifest, self.params()
        props = m["params"]["properties"]
        var = self.data.get("variants") or {}
        by = list(var.get("by") or [])
        rows = []
        for it in self.data["items"]:
            base = dict(it.get("params") or {})
            ins = dict(self.data.get("inputs") or {}, **(it.get("inputs") or {}))
            combos = [("", {})]
            if "hook" in by and base.get("hooks"):
                combos = [(f".h{k + 1}", dict(hook=h)) for k, h in enumerate(base["hooks"])]
            if "platform" in by:
                plats = base.get("platforms") or P.get("platforms") or []
                combos = [(s + "." + slug(p.replace(":", "-")), dict(d, platforms=[p])) for s, d in combos for p in plats]
            if "language" in by:
                combos = [(s + "." + slug(lang), dict(d, language=lang)) for s, d in combos
                          for lang in var.get("languages") or []]
            for suffix, delta in combos:
                jid = it["id"] + suffix
                row = dict(base, **delta)
                row.pop("hooks", None) if "hook" in by else None
                row.update(self.data["overrides"].get(jid) or {})
                row["id"] = jid
                row["_inputs"] = ins
                row["_base_item"] = it["id"]
                row["_answers"] = self._answers_for(jid, it["id"])
                br = (m.get("engine") or {}).get("batch_inputs") or {}
                for bk, src in br.items():
                    if src.endswith("[]") and ins.get(src[:-2]):
                        v = ins[src[:-2]]
                        row["file"] = os.path.basename(v[0] if isinstance(v, list) else v)
                rows.append({k: v for k, v in row.items() if v is not None or k in props})
        return rows

    def _answers_for(self, jid, item):
        out = {}
        for c in self.manifest["checkpoints"]:
            a = self.data["answers"].get(c["id"]) or {}
            v = a.get("*") if c["scope"] == "project" else (a.get(jid) or a.get(item))
            if v is not None:
                out[c["id"]] = v
        return out

    def spec(self):
        m, P = self.manifest, self.params()
        props = m["params"]["properties"]
        batch = self.batch()
        rows = self.jobs_rows()
        spec = dict(name=slug(self.data.get("name") or "project"), recipe=self.recipe_name(),
                    plugins=["vstudio.project.registry"],
                    project=dict(dir=self.dir, recipe=m["id"], batch=batch, name=self.data.get("name")),
                    jobs=rows)
        spec = _deep_merge(spec, (m.get("engine") or {}).get("spec") or {})
        for k, v in P.items():
            xs = (props.get(k) or {}).get("x-spec")
            if xs and v is not None:
                v = ((props.get(k) or {}).get("x-map") or {}).get(v, v) if isinstance(v, str) else v
                cur = spec
                parts = xs.split(".")
                for part in parts[:-1]:
                    cur = cur.setdefault(part, {})
                cur[parts[-1]] = v
        spec = _deep_merge(spec, self.series().get("spec") or {})
        spec = _deep_merge(spec, self.data.get("spec") or {})
        spec["defaults"] = dict(spec.get("defaults") or {},
                                **{k: v for k, v in P.items() if not (props.get(k) or {}).get("x-spec")})
        ins = dict(spec.get("inputs") or {})
        for bk, src in ((m.get("engine") or {}).get("batch_inputs") or {}).items():
            many = src.endswith("[]")
            key = src[:-2] if many else src
            vals = []
            for r in rows:
                v = r["_inputs"].get(key)
                vals += v if isinstance(v, list) else ([v] if v else [])
            vals = list(dict.fromkeys(vals))
            if vals:
                ins[bk] = vals if many else vals[0]
        spec["inputs"] = ins
        if self.data.get("client"):
            spec["client"] = self.data["client"]
        return spec

    # ------------------------------------------------------------- plan / refresh
    def plan(self):
        from vstudio.batch.plan import plan_batch
        self.reload()                                   # project.yaml is the truth (the app / agent edit it)
        if not self.data["items"]:
            return dict(batch_dir=self.state_dir, jobs=[], created=[], updated=[], unchanged=[], dropped=[],
                        note="no items yet: `plan-items` (planner recipes) or add items to project.yaml")
        os.makedirs(self.state_dir, exist_ok=True)
        spec_path = os.path.join(self.state_dir, "spec.yaml")
        with open(spec_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.spec(), f, allow_unicode=True, sort_keys=False)
        from . import registry  # noqa: F401
        r = plan_batch(spec_path, batch_dir=self.state_dir, echo=False)
        self._sync_review()
        self._reopen_stale()
        return r

    def _reopen_stale(self):
        """A finished item whose stage keys changed without a param change (a watched file edited by the agent or
        the app, an engine update) goes back to ``planned`` so the next run re-checks it."""
        stale = self.stale()
        st = Store(self.state_dir)
        try:
            for jid, stages in stale.items():
                j = st.job(jid)
                if stages and j and j["state"] in ("done", "failed"):
                    st.set_job(jid, state="planned")
        finally:
            st.close()

    def _sync_review(self):
        pubs = [c for c in self.manifest["checkpoints"] if c["kind"] == "publish"]
        if not pubs:
            return
        st = Store(self.state_dir)
        try:
            for j in st.jobs():
                a = B.answer_of(j["params"], pubs[0]["id"])
                if a is not None:
                    ok = bool((a.get("value") or {}).get("approve"))
                    st.set_job(j["id"], review="approved" if ok else "needs-replan",
                               review_reason=None if ok else (a.get("value") or {}).get("reason"))
        finally:
            st.close()

    def stale(self):
        """{job: [stages that the next run will (re-)run]}."""
        from vstudio.batch.edits import stale_stages
        st = Store(self.state_dir)
        try:
            spec, recipe = st.spec, self.recipe()
            out = {}
            for j in st.jobs():
                if j["state"] == "dropped":
                    continue
                job = dict(id=j["id"], params=j["params"], recipe=j["recipe"])
                out[j["id"]] = stale_stages(recipe, spec, job, j["params"], st.stage_rows(j["id"]))
            return out
        finally:
            st.close()

    def refresh(self):
        """Re-read project.yaml (+ the watched item files), re-plan; -> what changed and what will re-run."""
        self.reload()
        self.validate_params()
        H.register(self.dir, self.data.get("name"), self.data["recipe"], self.data.get("series"),
                   self.data.get("client"))
        r = self.plan()
        return dict(ok=True, dir=self.dir, plan={k: r[k] for k in ("created", "updated", "unchanged", "dropped")},
                    stale=self.stale(), pending=self.pending(), state=self.status(brief=True)["state"])

    # ------------------------------------------------------------- items planner
    def plan_items(self, replace=False, **kw):
        """Recipes whose items come from a plan (segments of a long recording): run the manifest's
        ``items.planner`` -> draft items in project.yaml (approved at the ``segments`` checkpoint)."""
        ref = self.manifest["items"].get("planner")
        if not ref:
            raise ProjectError(f"{self.manifest['id']}: items are not planned (no items.planner)")
        if self.data["items"] and not replace:
            raise ProjectError("the project has items already (replace=True / --replace to re-plan)")
        rows = M.resolve_ref(ref)(self, **kw) or []
        seen, out = set(), []
        for k, r in enumerate(rows):
            rid = slug(r.get("id") or f"s{k + 1:03d}")
            while rid in seen:
                rid += "x"
            seen.add(rid)
            out.append(dict(id=rid, inputs=dict(r.get("inputs") or {}), params=dict(r.get("params") or {})))
        if not out:
            raise ProjectError("the planner proposed no items")
        self.data["items"] = out
        self.save()
        r = self.plan()
        return dict(ok=True, items=[x["id"] for x in out], plan={k: r.get(k) for k in ("created", "updated", "dropped")})

    # ------------------------------------------------------------- run
    def auto_policy(self, extra=None):
        pol = set(self.data.get("auto") or [])
        pol |= set(extra or [])
        return pol

    def _auto_answerable(self, pay, pol):
        cp = self.checkpoint(pay["id"])
        if cp["kind"] in NEVER_AUTO or cp.get("auto", "never") != "default":
            return False
        if not ({"all", cp["id"], cp["kind"]} & pol):
            return False
        return pay.get("default") is not None

    def run(self, pilot=None, confirm_pilot=False, resume=False, only=None, limits=None, on_event=None, auto=None,
            max_rounds=8, echo=False):
        emit = on_event or (lambda ev: None)
        if not self.data["items"] and self.manifest["items"].get("planner"):
            self.plan_items()
        self.plan()
        pol = self.auto_policy(auto)
        rounds, res = 0, None
        while True:
            try:
                res = run_state(self.state_dir, pilot=pilot, confirm_pilot=confirm_pilot, resume=resume,
                                retry_failed=True, only=set(only) if only else None, limits=limits,
                                on_event=on_event, echo=echo)
            except BatchBusy as e:
                emit(dict(event="project-end", ts=now(), status="busy", exit_code=EXIT["busy"], error=str(e)))
                return dict(status="busy", exit_code=EXIT["busy"], error=str(e))
            pend = self.pending()
            todo = [p for p in pend if self._auto_answerable(p, pol)]
            # a pilot that stopped at an auto-answerable checkpoint ends its batch run as "pilot-review" too: answer
            # and go on (the next round re-runs the same pilot jobs), else a desk pilot never gets past its first one
            if not todo or rounds >= max_rounds or res["status"] in ("paused", "over-budget"):
                break
            for p in todo:
                target = "*" if p["scope"] == "project" else p["item"]
                self.answer(p["id"], p["default"], items=None if target == "*" else [target], replan=False,
                            auto=True)
                emit(dict(event="auto-answer", ts=now(), checkpoint=p["id"], item=target, value=p["default"]))
            self.plan()
            rounds += 1
        s = self.status()
        pend = self.pending()
        failed = [i for i in s["items"] if i["state"] == "failed"]
        if res["status"] == "paused":
            code = EXIT["paused"]
        elif res["status"] == "over-budget":
            code = EXIT["refused"]
        elif res["status"] == "pilot-review" and not (s["items"] and not pend and not failed
                                                      and all(i["state"] == "done" for i in s["items"])):
            code = EXIT["pilot"]                # a pilot that already made every item (a 1-item project) is done
        elif failed:
            code = EXIT["failed"]
        elif pend:
            code = EXIT["waiting"]
        else:
            code = EXIT["done"]
        out = dict(status=s["state"], exit_code=code, batch_status=res["status"], pause_reason=res.get("pause_reason"),
                   ran=[f"{j}:{st}" for j, st in res.get("ran") or []], rounds=rounds,
                   pending=[_brief_pending(p) for p in pend], items=[dict(id=i["id"], state=i["state"],
                                                                         waiting=i["waiting"]) for i in s["items"]])
        emit(dict(event="project-end", ts=now(), status=out["status"], exit_code=code, pending=out["pending"]))
        _live_end(self.dir, code, pend, failed)
        return out

    # ------------------------------------------------------------- checkpoints
    def pending(self, cid=None, item=None):
        """Every checkpoint waiting for an answer: the payloads the gates wrote (options, default, previews)."""
        if not os.path.exists(os.path.join(self.state_dir, DB_NAME)):
            return []
        st = Store(self.state_dir)
        try:
            out = []
            for j in st.jobs():
                if j["state"] == "dropped" or (item and j["id"] != item):
                    continue
                for sname, r in st.stage_rows(j["id"]).items():
                    if r["state"] == "failed" and str(r.get("error") or "").startswith("CheckpointPending"):
                        c = sname[len(M.GATE_PREFIX):]
                        if cid and c != cid:
                            continue
                        pay = B.read_payload(self.state_dir, j["id"], c) or {}
                        pay.update(project=self.dir, project_name=self.data.get("name"), item=j["id"])
                        out.append(pay)
            return out
        finally:
            st.close()

    def answer(self, cid, value, items=None, replan=True, auto=False, run=False):
        """Record an answer (validated against the checkpoint's answer schema), derive the param changes
        (``apply``), re-plan -> {ok, answered, rerun {job: stages}}. ``items`` None = every item waiting at it
        (item scope) / the project (project scope)."""
        cp = self.checkpoint(cid)
        _validate_answer(cp, value)
        if cp["scope"] == "project":
            targets = ["*"]
        elif items:
            targets = list(items)
        else:
            targets = [p["item"] for p in self.pending(cid)]
            if not targets and len(self.jobs_rows()) == 1:
                targets = [self.jobs_rows()[0]["id"]]            # one item: (re-)answer it
            if not targets:
                raise ProjectError(f"no item is waiting at {cid}; name the item(s) to answer ahead")
        known = {r["id"] for r in self.jobs_rows()}
        bad = [t for t in targets if t != "*" and t not in known]
        if bad:
            raise ProjectError(f"unknown item(s) {bad}")
        st = Store(self.state_dir) if os.path.exists(os.path.join(self.state_dir, DB_NAME)) else None
        try:
            answered = []
            for t in targets:
                jid = t if t != "*" else (self.pending(cid) or [{}])[0].get("item")
                pay = (B.read_payload(self.state_dir, jid, cid) if jid else None) or {}
                row = st.job(jid) if (st and jid) else None
                params = (row or {}).get("params") or next((r for r in self.jobs_rows() if r["id"] == jid), {})
                res = {}
                if cp.get("apply"):
                    res = M.resolve_ref(cp["apply"])(AnswerCtx(self, cp, jid or "_project", value, pay, params)) or {}
                rec = dict(value=value, digest=res.get("digest") or pay.get("digest"), at=_stamp())
                if auto:
                    rec["auto"] = True
                self.data["answers"].setdefault(cid, {})[t] = rec
                if res.get("params"):
                    if t == "*":
                        self.data["params"].update({k: v for k, v in res["params"].items()})
                    else:
                        self.data["overrides"].setdefault(t, {}).update(res["params"])
                if res.get("project_params"):
                    self.data["params"].update(res["project_params"])
                for iid, patch in (res.get("items_patch") or {}).items():
                    if patch is None:
                        self.data["items"] = [i for i in self.data["items"] if i["id"] != iid]
                        continue
                    it = next((i for i in self.data["items"] if i["id"] == iid), None)
                    if it is not None:
                        it.setdefault("params", {}).update(patch)
                answered.append(t)
        finally:
            if st:
                st.close()
        self.save()
        out = dict(ok=True, checkpoint=cid, answered=answered)
        if replan:
            self.plan()
            stale = self.stale()
            out["rerun"] = {j: s for j, s in stale.items() if s and (cp["scope"] == "project" or j in answered)}
        if run:
            out["run"] = self.run()
        return out

    # ------------------------------------------------------------- views
    def status(self, brief=False):
        base = dict(dir=self.dir, name=self.data.get("name"), recipe=self.data["recipe"],
                    labels=self.manifest["labels"], series=self.data.get("series"), client=self.data.get("client"))
        if not os.path.exists(os.path.join(self.state_dir, DB_NAME)):
            return dict(base, state="new", state_info=MSG.state("project-state", "new"), items=[],
                        progress=dict(done=0, total=0))
        st = Store(self.state_dir)
        try:
            recipe = self.recipe()
            order = [s.name for s in recipe.order()]
            items, done_all, total_all = [], 0, 0
            for j in st.jobs():
                if j["state"] == "dropped":
                    continue
                rows = st.stage_rows(j["id"])
                stages = []
                for name in order:
                    r = rows.get(name) or {}
                    stages.append(dict(id=name, state=r.get("state") or "pending", seconds=r.get("seconds"),
                                       cached=bool(r.get("cached")),
                                       error=None if str(r.get("error") or "").startswith("CheckpointPending")
                                       else (r.get("error") or None) and str(r["error"])[:300],
                                       gate=name.startswith(M.GATE_PREFIX)))
                waiting = [s["id"][len(M.GATE_PREFIX):] for s in stages
                           if s["gate"] and (rows.get(s["id"]) or {}).get("state") == "failed"
                           and str((rows.get(s["id"]) or {}).get("error") or "").startswith("CheckpointPending")]
                n_done = sum(s["state"] in ("done", "skipped") for s in stages)
                done_all += n_done
                total_all += len(stages)
                state = j["state"]
                if waiting and state != "running":
                    state = "waiting"
                if not brief:
                    for sx in stages:
                        sx["label_info"] = MSG.stage(sx["id"][len(M.GATE_PREFIX):] if sx["gate"] else sx["id"])
                items.append(dict(id=j["id"], state=state, qc=j.get("qc"), review=j.get("review"),
                                  state_info=MSG.state("job-state", "waiting" if state == "waiting" else state),
                                  qc_info=MSG.state("qc-state", j.get("qc")),
                                  waiting=waiting, progress=dict(done=n_done, total=len(stages)),
                                  stages=[] if brief else stages, cost=j.get("cost") or 0.0,
                                  title=(j["params"] or {}).get("title")))
            active = runner_active(self.state_dir)
            states = {i["state"] for i in items}
            if active:
                state = "running"
            elif "waiting" in states:
                state = "needs-you"
            elif "failed" in states:
                state = "error"
            elif st.state() == "paused":
                state = "paused"
            elif "interrupted" in states:
                state = "interrupted"
            elif items and states <= {"done"}:
                state = "done"
            else:
                state = "planned"
            return dict(base, state=state, state_info=MSG.state("project-state", state), batch_state=st.state(),
                        pause_reason=st.meta("pause_reason"),
                        running=active, items=items, pending=sum(len(i["waiting"]) for i in items),
                        progress=dict(done=done_all, total=total_all))
        finally:
            st.close()

    def show(self):
        return dict(project=self.data, manifest=public_manifest(self.manifest), params=self.params(),
                    status=self.status(), batch=self.batch(), recipe_name=self.recipe_name(),
                    paths=dict(dir=self.dir, yaml=self.yaml_path, state=self.state_dir,
                               items=os.path.join(self.dir, "items"), exports=os.path.join(self.dir, "exports")))

    def preview(self, item=None, stage=None):
        """Preview artifacts per item / stage (existing files only): the manifest's ``preview`` of each finished
        stage + the waiting checkpoints' previews."""
        st = Store(self.state_dir)
        try:
            ann = {e["id"]: e for e in self.manifest["stages"]}
            out = []
            for j in st.jobs():
                if j["state"] == "dropped" or (item and j["id"] != item):
                    continue
                rows = st.stage_rows(j["id"])
                arts = []
                for name, r in rows.items():
                    if stage and name != stage:
                        continue
                    pv = (ann.get(name) or {}).get("preview")
                    if r["state"] != "done" or not pv:
                        continue
                    for path in _preview_paths(self.manifest, j, name, r, pv, self.state_dir):
                        arts.append(dict(stage=name, kind=pv["kind"], path=path, label=pv.get("label")))
                for p in self.pending(item=j["id"]):
                    for x in p.get("previews") or []:
                        if isinstance(x, dict) and x.get("path") and os.path.exists(str(x["path"])):
                            arts.append(dict(stage=p["stage"], kind=x.get("kind"), path=x["path"], checkpoint=p["id"]))
                out.append(dict(id=j["id"], state=j["state"], previews=arts))
            return dict(dir=self.dir, items=out)
        finally:
            st.close()

    def export(self, out_dir=None, include_unapproved=False, items=None):
        """Final files of the finished (and, when the recipe has a publish checkpoint, approved) items ->
        ``<project>/exports/<item>/[<clip>-]<platform>-<orientation>.<ext>`` (hard links; ``clip`` when one item
        yields several clips, e.g. lesson points) + manifest.json (sha256)."""
        from .adapters.common import copy_into
        collect = M.resolve_ref(self.manifest["outputs"]["collect"])
        pub = next((c["id"] for c in self.manifest["checkpoints"] if c["kind"] == "publish"), None)
        out_dir = os.path.abspath(out_dir or os.path.join(self.dir, "exports"))
        st = Store(self.state_dir)
        try:
            entries, skipped = [], []
            for j in st.jobs():
                if j["state"] == "dropped" or (items and j["id"] not in items):
                    continue
                if pub and not include_unapproved:
                    a = B.answer_of(j["params"], pub)
                    if not (a and (a.get("value") or {}).get("approve")) or j["state"] != "done":
                        skipped.append(dict(item=j["id"], why="not approved at publish" if j["state"] == "done"
                                            else f"state {j['state']}"))
                        continue
                elif j["state"] != "done" and not include_unapproved:
                    skipped.append(dict(item=j["id"], why=f"state {j['state']}"))
                    continue
                rows = st.stage_rows(j["id"])
                for e in collect(self, j, rows) or []:
                    if not e.get("file") or not os.path.exists(e["file"]):
                        continue
                    tag = "-".join(x for x in (e.get("clip"), e.get("platform"), e.get("orientation")) if x) or "file"
                    ext = os.path.splitext(e["file"])[1]
                    name = f"{tag}{ext}" if e.get("platform") else os.path.basename(e["file"])
                    dst = copy_into(e["file"], os.path.join(out_dir, j["id"], name))
                    rec = dict(item=j["id"], platform=e.get("platform"), orientation=e.get("orientation"),
                               **({"clip": e["clip"]} if e.get("clip") else {}),
                               kind=e.get("kind") or "file", file=dst, sha256=sha256_file(dst),
                               bytes=os.path.getsize(dst), title=(j["params"] or {}).get("title"))
                    for k in ("cover", "post"):
                        if e.get(k) and os.path.exists(e[k]):
                            d2 = copy_into(e[k], os.path.join(out_dir, j["id"], f"{tag}.{k}{os.path.splitext(e[k])[1]}"))
                            rec[k] = d2
                    entries.append(rec)
            man = dict(project=self.dir, name=self.data.get("name"), recipe=self.data["recipe"], at=_stamp(),
                       items=entries, skipped=skipped)
            write_json(os.path.join(out_dir, "manifest.json"), man)
            return dict(ok=True, dir=out_dir, manifest=os.path.join(out_dir, "manifest.json"), files=len(entries),
                        items=sorted({e["item"] for e in entries}), skipped=skipped, entries=entries)
        finally:
            st.close()

    # ------------------------------------------------------------- agent hook
    def context(self):
        m = self.manifest
        s = self.status(brief=True)
        pend = [_brief_pending(p) for p in self.pending()]
        edit = [self.yaml_path]
        for r in self.jobs_rows()[:50]:
            p = dict(r, _project_dir=self.dir, _item_dir=os.path.join(self.dir, "items", r.get("_base_item") or r["id"]))
            t = B.static_tctx(m, p, r["id"])
            for c in m["checkpoints"]:
                if c.get("author"):
                    edit.append(M.fmt(c["author"]["file"], t))
            for f in m["agent"].get("edit_files") or []:
                try:
                    edit.append(M.fmt(f, t))
                except M.Missing:
                    pass
        cli = f"python3 -m vstudio.project"
        d = self.dir
        return dict(
            project=d, name=self.data.get("name"), recipe=m["id"], labels=m["labels"], state=s["state"],
            workflow_md=os.path.join(M.ROOT, m["agent"]["workflow_md"]), manifest=m["_path"],
            vstudio=M.ROOT, project_yaml=self.yaml_path, state_dir=self.state_dir,
            params=self.params(), items=[dict(id=i["id"], state=i["state"], waiting=i["waiting"]) for i in s["items"]],
            pending=pend, edit_files=list(dict.fromkeys(edit)),
            notes=m["agent"].get("notes"),
            commands=dict(
                status=f"{cli} status --dir {d} --json",
                refresh=f"{cli} refresh --dir {d} --json",
                run=f"{cli} run --dir {d} --json",
                pending=f"{cli} checkpoint --dir {d} --json",
                answer=f"{cli} checkpoint --dir {d} --id <checkpoint> [--item <item>] --answer '<json>' --json",
                preview=f"{cli} preview --dir {d} --json",
                export=f"{cli} export --dir {d} --json",
                batch=f"python3 -m vstudio.batch status --batch {self.state_dir}  (job edit / job rerun / review work here too)"),
            rules=["project.yaml is the truth: edit params / items / overrides there, or the item files listed in "
                   "edit_files; then run `refresh` (the app does it too) - only the affected stages re-run.",
                   "Never edit state/ by hand (it is the scheduler's store); answers go through `checkpoint --answer`.",
                   "Read workflow_md for the craft rules of this recipe before changing creative params.",
                   "Budget / consent checkpoints are the creator's call: never answer them for the user."])

    def write_agent_files(self):
        c = self.context()
        lines = [f"# Project {c['name']} ({c['recipe']}: {c['labels']['zh']} / {c['labels']['en']})", "",
                 "This folder is a video-studio project. The desk app and you edit the SAME state.", "",
                 f"- Playbook (read first): `{c['workflow_md']}`",
                 f"- Recipe manifest: `{c['manifest']}`",
                 f"- Editable truth: `{c['project_yaml']}` (+ item files under `items/<item>/`)",
                 f"- Live state as JSON: `{c['commands']['status']}` / context: "
                 f"`python3 -m vstudio.project context --dir {c['project']} --json`", "", "## Commands", ""]
        lines += [f"- {k}: `{v}`" for k, v in c["commands"].items()]
        lines += ["", "## Rules", ""] + [f"- {r}" for r in c["rules"]]
        txt = "\n".join(lines) + "\n"
        for name in ("AGENTS.md", "CLAUDE.md"):
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as f:
                f.write(txt)
        return [os.path.join(self.dir, n) for n in ("AGENTS.md", "CLAUDE.md")]


# --------------------------------------------------------------------------- helpers
def check_params(m, params):
    try:
        import jsonschema
    except ImportError:
        return []
    sch = dict(m["params"], properties={k: {kk: vv for kk, vv in v.items() if not kk.startswith("x-")}
                                        for k, v in m["params"]["properties"].items()})
    errs = [f"{'/'.join(map(str, e.absolute_path))}: {e.message}"
            for e in jsonschema.Draft202012Validator(sch).iter_errors(params)]
    if errs:
        raise ProjectError("params: " + "; ".join(errs))
    return errs


def _brief_pending(p):
    return dict(project=p.get("project"), item=p.get("item"), id=p.get("id"), kind=p.get("kind"),
                scope=p.get("scope"), labels=p.get("labels"), n_options=len(p.get("options") or []),
                default=p.get("default"), payload=os.path.join(p.get("project") or "", "state", "checkpoints",
                                                                p.get("item") or "", f"{p.get('id')}.json"))


def _preview_paths(m, job, stage, row, pv, state_dir):
    out = row.get("out") or {}
    path = pv.get("path")
    cands = []
    if not path:
        cands = [f for f in out.get("files") or []]
    elif path.startswith("out:"):
        v = out.get(path[4:])
        cands = v if isinstance(v, list) else [v]
    else:
        t = B.static_tctx(m, job["params"], job["id"])
        t["stage_dir"] = os.path.join(state_dir, "jobs", job["id"], stage)
        t["out"] = out
        try:
            p = M.fmt(path, t)
        except M.Missing:
            return []
        import glob as G
        cands = sorted(G.glob(p)) if any(ch in p for ch in "*?[") else [p]
    return [c for c in cands if isinstance(c, str) and os.path.exists(c)]


def _folder_files(folder, glob_pat, accept):
    import glob as G
    pats = [x.strip() for x in (glob_pat or "*").split(",") if x.strip()]
    files = []
    for pat in pats:
        files += [f for f in sorted(G.glob(os.path.join(os.path.abspath(folder), pat))) if os.path.isfile(f)
                  and not os.path.basename(f).startswith(".")]
    if accept:
        acc = tuple(a.lower() for a in accept)
        files = [f for f in files if f.lower().endswith(acc)]
    if not files:
        raise ProjectError(f"no matching files in {folder}")
    return list(dict.fromkeys(files))


def _csv_items(path, known):
    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for k, r in enumerate(rows):
        r = {kk.strip(): vv for kk, vv in r.items() if kk and vv not in (None, "")}
        it = dict(id=r.pop("id", None) or f"{k + 1:03d}", inputs={}, params={})
        for kk, vv in r.items():
            if kk in known:
                it["inputs"][kk] = os.path.abspath(vv) if known[kk]["kind"] in FILE_KINDS else vv
            else:
                it["params"][kk] = vv
        out.append(it)
    return out


def public_manifest(m):
    d = {k: v for k, v in m.items() if not k.startswith("_")}
    d["params"] = M.public_params(m)       # x-format defaults resolved (vstudio.formats <- persona formats)
    d["path"] = m.get("_path")
    d["messages"] = MSG.recipe(m)          # recipe.<id>.label / .description codes (references/MESSAGES.md)
    return d


def find(pdir=None):
    """The project folder: ``pdir`` or the cwd (or a parent) holding project.yaml."""
    d = os.path.abspath(pdir or os.getcwd())
    cur = d
    while True:
        if os.path.exists(os.path.join(cur, "project.yaml")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return d
        cur = parent
