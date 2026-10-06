"""v0.2 adapter (PRODUCT_V02.md): clients, AI segment planning, in-review edits, review timing, client delivery,
metrics. One facade over the mock or real engine.

For every v0.2 operation the adapter checks the engine's capabilities (caps.py). When the engine has the
command it is called (``python -m vstudio.batch <cmd> ... --json``); otherwise the desk's own faithful
implementation runs: always in mock mode, and in real mode for the parts the desk can do itself (clients,
timing, deliver from the publish package, metrics). Operations that need media processing (plan-segments,
job edit, job rerun) report ``engine lacks <cap>`` in real mode without the command.

Engine command contract (what the adapter sends / expects; all with --json):
  plan-segments --source F --count N --min S --max S --provider claude|openai|none [--client DIR]
                [--platforms a,b] --out DIR
      -> {draft, duration, provider, segments: [{id,start,end,title,chapter,hook{start,end,text},
          hook_candidates?[], notes[], tags[], why, risk, score}], words: [{w,t,te}]}
  client init|show --client DIR / client update --client DIR --set JSON   -> {config, effective}
  job edit --batch B --job J --op caption --cue I --text T | trim --start A --end B | hook --pick K
           | cover --t S --text T | copy --title T --body B --tags a,b     -> {ok, faithful, reason, rerun[]}
  job rerun --batch B --job J --json-events                               (streams like run --json-events)
  deliver --batch B --client DIR [--zip] [--cleanup-days N]               -> {dir, zip, items, manifest}
  metrics --batch B | --client DIR | --all [--csv]                        -> metrics JSON (or CSV text)
  timing --batch B --job J --event start|stop --what review [--seconds S]
"""
import datetime as dt
import os
import secrets
import threading
import time

from . import deliver as D
from . import metrics as M
from . import planning as P
from .common import BadRequest, need, read_json
from .v02store import CLIENT_RE, V02Store, dump_yaml, load_yaml, write_text

# ops -> first stage to re-run (everything downstream re-runs too). Mirrors the real DAG (vstudio.batch.stages).
DEPS = {
    "probe": [], "extract": ["probe"], "asr": ["probe", "extract"], "cleanup": ["probe", "asr"],
    "apply": ["cleanup"], "compose": ["apply"], "glossary": ["asr"], "proofread": ["compose", "verify", "glossary"],
    "export": ["compose", "proofread"], "verify": ["apply"], "qc": ["cleanup", "apply", "compose", "export", "verify"],
    "preview": ["export"],
}
OP_ROOTS = {"caption": ["export"], "cover": ["export"], "copy": [], "hook": ["compose"], "trim": ["cleanup"]}
CLEANUP_PROFILES = ("gentle", "standard", "strict")
COVER_STYLES = ("frame", "collage", "face", "text")
DEFAULT_CLIENT = dict(name="", style="", platforms=["xiaohongshu:full"], tags=[], glossary=[],
                      fillers=dict(extra=[], keep=[]), brand=dict(accent="#FF2442", highlight="#FFD60A"),
                      cover_style="frame", cleanup_profile="standard", notes="")


def downstream(roots):
    """Stages that re-run when ``roots`` change: the roots and every stage depending on them, in DAG order."""
    out = set(roots)
    changed = True
    while changed:
        changed = False
        for s, deps in DEPS.items():
            if s not in out and any(d in out for d in deps):
                out.add(s)
                changed = True
    return [s for s in DEPS if s in out]


def _merge(a, b):
    out = dict(a)
    for k, v in (b or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Studio:
    def __init__(self, engine, data_dir, bus, caps, runner=None):
        self.e, self.bus, self.caps, self.runner = engine, bus, caps, runner
        self.store = V02Store(data_dir)
        self.clients_root = self.store.path("clients")
        os.makedirs(self.clients_root, exist_ok=True)
        self.plans = {}
        self._lock = threading.RLock()
        self.step = float(getattr(engine, "step", 0.25) or 0.25)
        if engine.mode == "mock":
            self._seed_mock()

    @property
    def mock(self):
        return self.e.mode == "mock"

    def has(self, cap):
        return (not self.mock) and self.caps.has(cap)

    def _lacks(self, cap):
        raise BadRequest(f"engine lacks {cap} (update video-studio to use this in real mode)")

    def capabilities(self):
        info = self.caps.info() if not self.mock else dict(source="mock", commands={c: False for c in
                                                                                  ("plan-segments", "client", "job-edit",
                                                                                   "job-rerun", "deliver", "metrics",
                                                                                   "timing")})
        return dict(mode=self.e.mode, **info,
                    fallback=dict(plan=self.mock or self.has("plan-segments"), edit=self.mock or self.has("job-edit"),
                                  rerun=self.mock or self.has("job-rerun")))

    def _seed_mock(self):
        if self.list_clients():
            return
        self.create_client(dict(slug="demo", name="示例客户 · 知识讲师", style="干净、信息密度高、不花哨",
                                platforms=["xiaohongshu:full", "tiktok:vertical"], tags=["RAG", "面试", "AI"],
                                glossary=[dict(wrong="rag", right="RAG")], cleanup_profile="strict"))
        demo = next((b for b in self.e.list_batches() if b["name"] == "demo-course"), None)
        if demo:
            self.store.set_batch_meta(demo["id"], client="demo", created=time.time())
            self.set_crm("demo", dict(stage="pilot"))

    # ================================================================ clients
    def client_dir(self, slug):
        need(isinstance(slug, str) and CLIENT_RE.match(slug), "client: a-z 0-9 _ - (max 40)")
        return os.path.join(self.clients_root, slug)

    def _read_client(self, slug):
        p = os.path.join(self.client_dir(slug), "client.yaml")
        if not os.path.exists(p):
            raise KeyError(f"unknown client {slug}")
        with open(p, encoding="utf-8") as f:
            return load_yaml(f.read()) or {}

    def _persona_defaults(self):
        base = dict(DEFAULT_CLIENT)
        if not self.mock:
            try:
                from vstudio.config import persona
                p = persona() or {}
                br = p.get("brand") or {}
                base["brand"] = dict(accent=br.get("accent", base["brand"]["accent"]),
                                     highlight=br.get("highlight", base["brand"]["highlight"]))
            except Exception:  # noqa: BLE001
                pass
        return base

    def _client_view(self, slug, cfg):
        if self.has("client"):
            doc = self.runner.json(["client", "show", "--client", self.client_dir(slug), "--json"])
            eff = doc.get("effective") or doc
        else:
            eff = _merge(self._persona_defaults(), cfg)
        batches = [b for b, m in (self.store.get("batches", {}) or {}).items() if m.get("client") == slug]
        return dict(slug=slug, dir=self.client_dir(slug), config=cfg, effective=eff, batches=batches,
                    crm=self.crm(slug))

    def list_clients(self):
        out = []
        for slug in sorted(os.listdir(self.clients_root)):
            if CLIENT_RE.match(slug) and os.path.exists(os.path.join(self.clients_root, slug, "client.yaml")):
                cfg = self._read_client(slug)
                crm = self.crm(slug)
                n = sum(1 for m in (self.store.get("batches", {}) or {}).values() if m.get("client") == slug)
                out.append(dict(slug=slug, name=cfg.get("name") or slug, platforms=cfg.get("platforms") or [],
                                stage=crm.get("stage"), batches=n, glossary=len(cfg.get("glossary") or [])))
        return out

    def get_client(self, slug):
        return self._client_view(slug, self._read_client(slug))

    def _write_client(self, slug, cfg):
        write_text(os.path.join(self.client_dir(slug), "client.yaml"),
                   "# client.yaml - overrides the global persona for this client's batches (video-studio desk)\n"
                   + dump_yaml(cfg))

    def create_client(self, body):
        slug = body["slug"]
        d = self.client_dir(slug)
        need(not os.path.exists(os.path.join(d, "client.yaml")), f"client {slug} exists")
        cfg = validate_client(body, partial=False)
        if self.has("client"):
            os.makedirs(d, exist_ok=True)
            self.runner.json(["client", "init", "--client", d, "--set", _json(cfg), "--json"])
        if not os.path.exists(os.path.join(d, "client.yaml")):
            self._write_client(slug, cfg)
        self.set_crm(slug, dict(stage="lead"))
        self.bus.publish("clients")
        return self.get_client(slug)

    def update_client(self, slug, patch):
        cfg = self._read_client(slug)
        upd = validate_client(patch, partial=True)
        add = upd.pop("glossary_add", None)
        cfg.update(upd)
        if add:
            cfg["glossary"] = _glossary_add(cfg.get("glossary") or [], add)
        if self.has("client"):
            self.runner.json(["client", "update", "--client", self.client_dir(slug), "--set",
                              _json(dict(upd, **({"glossary_add": add} if add else {}))), "--json"])
            if os.path.exists(os.path.join(self.client_dir(slug), "client.yaml")):
                cfg = self._read_client(slug)
        else:
            self._write_client(slug, cfg)
        self.bus.publish("clients")
        return self.get_client(slug)

    # ---------------------------------------------------------------- CRM (manual funnel + 7-day data)
    def crm(self, slug):
        c = (self.store.get("crm", {}) or {}).get(slug) or {}
        hist = c.get("history") or []
        reached = {h["stage"] for h in hist}
        stage = next((s for s in reversed(M.FUNNEL) if s in reached), None)
        if c.get("lost"):
            stage = "lost"
        return dict(stage=stage, history=hist, revenue=c.get("revenue") or [], posts=c.get("posts") or [],
                    price_next=c.get("price_next"), note=c.get("note") or "", lost=bool(c.get("lost")))

    def set_crm(self, slug, body):
        self.client_dir(slug)
        today = body.get("date") or dt.date.today().isoformat()

        def f(d):
            c = d.setdefault(slug, dict(history=[], revenue=[], posts=[]))
            have = {h["stage"] for h in c["history"]}
            if body.get("stage") == "lost":
                c["lost"] = True
            elif body.get("stage"):
                c["lost"] = False
                for s in M.FUNNEL[:M.FUNNEL.index(body["stage"]) + 1]:      # the funnel is monotonic
                    if s not in have:
                        c["history"].append(dict(stage=s, at=today))
            if body.get("revenue"):
                c["revenue"].append(dict(at=today, amount=float(body["revenue"])))
                if "paid" not in have:
                    c["history"].append(dict(stage="paid", at=today))
            if body.get("post"):
                c["posts"].append(dict(body["post"], at=today))
                for s in M.FUNNEL[:M.FUNNEL.index("data") + 1]:
                    if s not in {h["stage"] for h in c["history"]}:
                        c["history"].append(dict(stage=s, at=today))
            if body.get("price_next") is not None:
                c["price_next"] = body["price_next"]
            if body.get("note") is not None:
                c["note"] = body["note"]
        self.store.update("crm", f)
        return self.crm(slug)

    # ================================================================ batches
    def create_batch(self, body):
        client = body.pop("client", None)
        if client:
            self._read_client(client)
            if self.has("client"):
                body["client_dir"] = self.client_dir(client)
        r = self.e.create_batch(body)
        self.store.set_batch_meta(r["id"], client=client, source=body.get("source"), folder=body.get("folder"),
                                  created=time.time(), plan=body.get("plan_id"))
        if client:
            self.bus.publish("clients")
        return r

    def list_batches(self):
        meta = self.store.get("batches", {}) or {}
        dels = self.store.get("deliveries", {}) or {}
        out = self.e.list_batches()
        for b in out:
            m = meta.get(b["id"]) or {}
            b["client"] = m.get("client")
            d = dels.get(b["id"])
            b["delivered"] = dict(at=d["at"], items=d["items"], dir=d["dir"]) if d else None
        return out

    def set_batch_client(self, bid, client):
        if client:
            self._read_client(client)
        self.e.status(bid)
        self.store.set_batch_meta(bid, client=client or "")
        self.bus.publish("batches")
        return dict(id=bid, client=client)

    def batch_client(self, bid):
        return (self.store.batch_meta(bid) or {}).get("client") or None

    # ================================================================ planning
    def start_plan(self, body):
        pid = secrets.token_hex(6)
        if body.get("client"):
            self._read_client(body["client"])
        if not self.mock and not self.has("plan-segments"):
            self._lacks("plan-segments")
        if body["provider"] == "claude" and not os.environ.get("ANTHROPIC_API_KEY") and not self.has("plan-segments"):
            raise BadRequest("ANTHROPIC_API_KEY missing: add it in Settings -> API keys, or use provider none")
        if body["provider"] == "openai" and not os.environ.get("OPENAI_API_KEY") and not self.has("plan-segments"):
            raise BadRequest("OPENAI_API_KEY missing: add it in Settings -> API keys, or use provider none")
        pdir = self.store.path("plans", pid)
        os.makedirs(pdir, exist_ok=True)
        plan = dict(id=pid, state="running", progress="probe", error=None, request=body, dir=pdir,
                    started=time.time(), result=None)
        with self._lock:
            self.plans[pid] = plan
        threading.Thread(target=self._plan, args=(plan,), daemon=True).start()
        return dict(id=pid)

    def _plan_progress(self, plan, progress):
        plan["progress"] = progress
        self.bus.publish("plan", plan=plan["id"], state=plan["state"], progress=progress)

    def _plan(self, plan):
        b = plan["request"]
        try:
            if self.has("plan-segments"):
                self._plan_progress(plan, "engine")
                args = ["plan-segments", "--source", b["source"], "--count", str(b["count"]), "--min", str(b["min"]),
                        "--max", str(b["max"]), "--provider", b["provider"], "--out", plan["dir"], "--json"]
                if b.get("client"):
                    args += ["--client", self.client_dir(b["client"])]
                if b.get("platforms"):
                    args += ["--platforms", ",".join(b["platforms"])]
                doc = self.runner.json(args, timeout=3 * 3600)
                res = dict(source=b["source"], duration=doc.get("duration"), provider=doc.get("provider", b["provider"]),
                           segments=doc.get("segments") or [], words=doc.get("words") or [],
                           draft=doc.get("draft"))
                if not res["words"] and doc.get("transcript"):
                    tr = read_json(doc["transcript"], {}) or {}
                    res["words"] = [dict(w=w.get("w") or w.get("word", "").strip(), t=w.get("t", w.get("start")),
                                         te=w.get("te", w.get("end")))
                                    for sg in tr.get("segments") or [] for w in sg.get("words") or []]
            else:
                dur = P.probe_duration(b["source"])
                for p in ("asr", "planning"):
                    time.sleep(self.step * 2)
                    self._plan_progress(plan, p)
                words = P.fake_transcript(dur)
                segs = P.rule_plan(words, count=b["count"], min_s=b["min"], max_s=b["max"])
                if b["provider"] != "none":
                    for s in segs:
                        s["why"] = f"[{b['provider']} mock] " + s["why"]
                draft = os.path.join(plan["dir"], "segments.draft.yaml")
                write_text(draft, dump_yaml(dict(source=b["source"], segments=segs)))
                res = dict(source=b["source"], duration=round(dur, 2), provider=b["provider"], segments=segs,
                           words=[dict(w=w["w"], t=w["t"], te=w["te"]) for w in words], draft=draft)
            plan.update(state="done", progress="done", result=res)
        except Exception as e:  # noqa: BLE001
            plan.update(state="error", error=str(e))
        self.bus.publish("plan", plan=plan["id"], state=plan["state"], progress=plan["progress"])

    def get_plan(self, pid):
        p = self.plans.get(pid)
        if not p:
            raise KeyError(f"unknown plan {pid}")
        return {k: p[k] for k in ("id", "state", "progress", "error", "request", "result")}

    def plan_to_batch(self, pid, body):
        p = self.plans.get(pid)
        if not p:
            raise KeyError(f"unknown plan {pid}")
        need(p["state"] == "done", "the plan is not finished")
        words = p["result"].get("words") or []
        dur = p["result"].get("duration") or (words[-1]["te"] if words else None)
        rows = []
        for n, s in enumerate(body["segments"]):
            a, b = P.snap(s["start"], words, "start"), P.snap(s["end"], words, "end")
            need(b - a >= 1.0, f"segment {n + 1}: end must be after start")
            need(dur is None or b <= dur + 0.5, f"segment {n + 1}: past the end of the recording")
            row = dict(id=f"s{n + 1:03d}", start=round(a, 2), end=round(b, 2), title=s["title"])
            for k in ("chapter", "notes", "tags", "why", "risk", "hook", "hook_candidates", "body"):
                if s.get(k):
                    row[k] = s[k]
            rows.append(row)
        seg_path = os.path.join(p["dir"], "segments.yaml")
        write_text(seg_path, dump_yaml(dict(source=p["request"]["source"], segments=rows)))
        req = dict(name=body["name"], recipe="longform-slices", source=p["request"]["source"], segments=seg_path,
                   platforms=body["platforms"], plan_id=pid)
        for k in ("budget", "out_dir"):
            if body.get(k):
                req[k] = body[k]
        req["client"] = body.get("client") or p["request"].get("client")
        return self.create_batch(req)

    # ================================================================ job detail + edits
    def _edits(self, bid):
        return self.store.get(f"edits-{bid}", {}) or {}

    def _put_edits(self, bid, jid, ent):
        self.store.update(f"edits-{bid}", lambda d: d.__setitem__(jid, ent))

    def job_detail(self, bid, jid):
        d = self.e.job(bid, jid)
        ent = self._edits(bid).get(jid) or {}
        p = d["job"].get("params") or {}
        cues = []
        for i, c in enumerate(((d.get("captions") or {}).get("cues")) or []):
            text = c.get("text") if isinstance(c.get("text"), str) else "".join(c.get("lines") or [])
            cues.append(dict(i=c.get("i", i), start=c.get("start", c.get("t0")), end=c.get("end", c.get("t1")),
                             text=text, heard=c.get("heard", text)))
        words = []
        for seg in d.get("transcript") or []:
            words += [dict(w=w["w"], t=w["t"], te=w["te"]) for w in seg.get("words") or []]
        words.sort(key=lambda w: w["t"])
        exports = (d.get("media") or {}).get("exports") or []
        hooks = p.get("hook_candidates") or ([p["hook"]] if isinstance(p.get("hook"), dict) else [])
        rng = p.get("range") or ([p["start"], p["end"]] if p.get("start") is not None and p.get("end") is not None
                                 else None)
        d["edit"] = dict(
            range=rng, words=words, cues=cues, hooks=[_hook(h) for h in hooks], hook_pick=p.get("hook_pick"),
            cover=dict(t=(p.get("cover") or {}).get("t"), text=(p.get("cover") or {}).get("text", ""),
                       file=next((x.get("cover") for x in exports if x.get("cover")), None)),
            copy=dict(title=p.get("title") or "", body=p.get("body") or "", tags=p.get("tags") or []),
            history=ent.get("history") or [], pending=ent.get("pending") or [], reruns=ent.get("reruns") or 0,
            can_edit=self.mock or self.has("job-edit"), can_rerun=self.mock or self.has("job-rerun"),
            client=self.batch_client(bid))
        return d

    def _snapshot(self, d, op, args):
        e = d["edit"]
        if op == "caption":
            c = next((c for c in e["cues"] if c["i"] == args["cue"]), None)
            need(c is not None, f"no caption cue {args['cue']}")
            return dict(cue=args["cue"], text=c["text"]), c
        if op == "trim":
            need(e["range"], "this job has no source range to trim")
            return dict(start=e["range"][0], end=e["range"][1]), None
        if op == "hook":
            need(0 <= args["pick"] < len(e["hooks"]), f"no hook candidate {args['pick']}")
            return dict(pick=e["hook_pick"] if e["hook_pick"] is not None else 0), None
        if op == "cover":
            return dict(t=e["cover"]["t"], text=e["cover"]["text"]), None
        return dict(title=e["copy"]["title"], body=e["copy"]["body"], tags=e["copy"]["tags"]), None

    def edit(self, bid, jid, op, args, undo_of=None):
        d = self.job_detail(bid, jid)
        e = d["edit"]
        need(e["can_edit"], "engine lacks job-edit (update video-studio to edit in the desk)")
        before, cue = self._snapshot(d, op, args)
        res = dict(ok=True, faithful=True, reason=None, rerun=downstream(OP_ROOTS[op]), glossary_added=None)
        if op == "caption" and undo_of is None:
            chk = P.faithful(cue["text"], args["text"], cue.get("heard"))
            res.update(faithful=chk["faithful"], reason=chk["reason"], ratio=chk["ratio"])
            if not chk["faithful"]:
                res.update(ok=False, rerun=[])
                return res
        if op == "trim":
            words = e["words"]
            a, b = P.snap(args["start"], words, "start"), P.snap(args["end"], words, "end")
            need(b - a >= 3.0, "a clip must be at least 3 s")
            args = dict(start=round(a, 2), end=round(b, 2))
        if self.has("job-edit"):
            doc = self.runner.json(["job", "edit", "--batch", self.e.dir_of(bid), "--job", jid, "--op", op,
                                    *_edit_args(op, args), "--json"])
            res.update(ok=bool(doc.get("ok", True)), faithful=bool(doc.get("faithful", doc.get("ok", True))),
                       reason=doc.get("reason"), rerun=doc.get("rerun") or res["rerun"])
            if not res["ok"]:
                return res
        else:
            self.e.apply_edit(bid, jid, op, args, res["rerun"])
        if op == "caption" and undo_of is None and e.get("client"):
            tf = P.term_fix(cue["text"], args["text"])
            if tf:
                tf.update(source="caption-fix", batch=bid, job=jid)
                self.update_client(e["client"], dict(glossary_add=[tf]))
                res["glossary_added"] = tf
        ent = self._edits(bid).get(jid) or dict(history=[], pending=[], reruns=0, count=0, since_rerun=0)
        if undo_of is None:
            ent["history"].append(dict(n=ent["count"] + 1, op=op, args=args, before=before, at=time.time(),
                                       rerun=res["rerun"], glossary_added=res["glossary_added"]))
            ent["count"] += 1
            ent["since_rerun"] = ent.get("since_rerun", 0) + 1
        else:
            ent["since_rerun"] = max(0, ent.get("since_rerun", 0) - 1)
        if ent["since_rerun"] == 0 and undo_of is not None:
            ent["pending"] = []
            if not self.has("job-edit"):
                self.e.clear_pending(bid, jid)
        else:
            ent["pending"] = [s for s in DEPS if s in set(ent["pending"]) | set(res["rerun"])]
        self._put_edits(bid, jid, ent)
        res["pending"] = ent["pending"]
        res["history"] = ent["history"]
        self.bus.publish("job-edit", batch=bid, job=jid)
        return res

    def undo(self, bid, jid):
        ent = self._edits(bid).get(jid) or {}
        hist = ent.get("history") or []
        need(hist, "nothing to undo")
        last = hist[-1]
        ent["history"] = hist[:-1]
        self._put_edits(bid, jid, ent)
        if last.get("glossary_added") and self.batch_client(bid):
            g = last["glossary_added"]
            cfg = self._read_client(self.batch_client(bid))
            cfg["glossary"] = [x for x in cfg.get("glossary") or []
                               if not (x.get("wrong") == g["wrong"] and x.get("right") == g["right"])]
            if not self.has("client"):
                self._write_client(self.batch_client(bid), cfg)
        r = self.edit(bid, jid, last["op"], last["before"], undo_of=last["n"])
        r["undone"] = last
        return r

    def rerun(self, bid, jid):
        ent = self._edits(bid).get(jid) or dict(history=[], pending=[], reruns=0, count=0, since_rerun=0)
        stages = ent.get("pending") or []
        need(stages, "nothing to re-render: no pending edits")
        if self.has("job-rerun"):
            r = self.e.spawn_rerun(bid, jid)
        elif self.mock:
            r = self.e.rerun_job(bid, jid, stages)
        elif self.has("job-edit"):       # the engine caches stages by params: a targeted run redoes only stale ones
            r = self.e.run(bid, dict(jobs=[jid]))
        else:
            self._lacks("job-rerun")
        ent.update(pending=[], reruns=int(ent.get("reruns") or 0) + 1, since_rerun=0)
        self._put_edits(bid, jid, ent)
        return dict(r or {}, stages=stages)

    # ================================================================ timing
    def timing(self, bid, body):
        self.e.status(bid)
        rec = dict(batch=bid, job=body["job"], event=body["event"], what=body["what"], at=time.time(),
                   active_s=round(float(body.get("active_s") or 0), 2) if body["event"] == "stop" else None)
        self.store.add_timing(rec)
        if self.has("timing"):
            args = ["timing", "--batch", self.e.dir_of(bid), "--job", body["job"], "--event", body["event"],
                    "--what", body["what"], "--json"]
            if rec["active_s"] is not None:
                args += ["--seconds", str(rec["active_s"])]
            threading.Thread(target=_quiet, args=(self.runner.json, args), daemon=True).start()
        rs = self.store.review_seconds(bid)
        return dict(ok=True, job_s=round(rs.get((bid, body["job"]), 0.0), 1))

    # ================================================================ deliver
    def deliver(self, bid, body):
        client = body.get("client") or self.batch_client(bid)
        st = self.e.status(bid)
        cname = (self._read_client(client).get("name") or client) if client else "客户"
        days = int(body["cleanup_days"]) if body.get("cleanup_days") else None
        if self.has("deliver"):
            args = ["deliver", "--batch", self.e.dir_of(bid), "--json"]
            if client:
                args += ["--client", self.client_dir(client)]
            if body.get("zip", True):
                args.append("--zip")
            if days:
                args += ["--cleanup-days", str(days)]
            r = self.runner.json(args, timeout=3600)
        else:
            m = self.e.manifest(bid)
            if not m.get("manifest") or not (m.get("verify") or {}).get("ok"):
                self.e.package(bid, {})
                m = self.e.manifest(bid)
            need(m.get("manifest") and m["manifest"].get("items"), "nothing to deliver: approve and package first")
            jobs = {j["id"]: dict(qc=j.get("qc"), qc_warn=j.get("qc_warn") or []) for j in st["jobs"]}
            copies = {}
            for jid, ent in self._edits(bid).items():
                if any(h["op"] == "copy" for h in ent.get("history") or []):
                    try:
                        copies[jid] = self.job_detail(bid, jid)["edit"]["copy"]
                    except KeyError:
                        pass
            r = D.build(m["dir"], m["manifest"], os.path.join(st["meta"]["dir"], "delivery"), cname,
                        st["meta"]["name"], jobs=jobs, make_zip=body.get("zip", True), cleanup_days=days,
                        copy_overrides=copies)
        rec = dict(batch=bid, client=client, at=time.time(), date=dt.date.today().isoformat(), dir=r.get("dir"),
                   zip=r.get("zip"), items=r.get("items") or len((r.get("manifest") or {}).get("items") or []),
                   jobs=r.get("jobs") or 0, duration_s=r.get("duration_s"),
                   cleanup=dict(enabled=bool(days), days=days, due=(time.time() + days * 86400) if days else None,
                                done=False))
        self.store.update("deliveries", lambda d: d.__setitem__(bid, rec))
        if client:
            self.set_crm(client, dict(stage="delivered"))
        self.bus.publish("batches")
        return dict(rec, manifest=r.get("manifest"))

    def delivery(self, bid):
        return (self.store.get("deliveries", {}) or {}).get(bid)

    def set_cleanup(self, bid, body):
        def f(d):
            need(bid in d, "not delivered yet")
            days = body.get("days")
            d[bid]["cleanup"] = dict(enabled=bool(body["enabled"]), days=days,
                                     due=d[bid]["at"] + days * 86400 if body["enabled"] and days else None,
                                     done=d[bid]["cleanup"].get("done", False))
        return self.store.update("deliveries", f)[bid]

    def cleanup_due(self, now=None):
        now = now or time.time()
        out = []
        for bid, d in (self.store.get("deliveries", {}) or {}).items():
            c = d.get("cleanup") or {}
            if not c.get("enabled") or c.get("done") or not c.get("due") or c["due"] > now:
                continue
            m = self.store.batch_meta(bid)
            paths = [p for p in (m.get("source"), m.get("folder")) if p and os.path.exists(p)]
            out.append(dict(batch=bid, paths=paths))
        return out

    def cleanup_done(self, bid, paths):
        def f(d):
            if bid in d:
                d[bid]["cleanup"].update(done=True, at=time.time(), paths=paths)
        self.store.update("deliveries", f)
        return dict(ok=True)

    # ================================================================ metrics
    def _batch_metrics(self, bid):
        st = self.e.status(bid)
        rs = {j: s for (b, j), s in self.store.review_seconds(bid).items()}
        rows = M.job_rows(st, rs, self._edits(bid))
        d = self.delivery(bid)
        s = M.summarize(rows, [d] if d else [])
        created = (self.store.batch_meta(bid) or {}).get("created")
        s["turnaround_h"] = round((d["at"] - created) / 3600, 1) if d and created else None
        return dict(batch=bid, name=st["meta"]["name"], client=self.batch_client(bid), summary=s, jobs=rows,
                    delivered=d)

    def metrics(self, batch=None, client=None):
        if self.has("metrics"):
            args = ["metrics", "--json"]
            if batch:
                args += ["--batch", self.e.dir_of(batch)]
            elif client:
                args += ["--client", self.client_dir(client)]
            else:
                args.append("--all")
            try:
                return dict(self.runner.json(args), source="engine")
            except Exception:  # noqa: BLE001  (fall back to the desk's own numbers)
                pass
        if batch:
            return dict(self._batch_metrics(batch), scope="batch", source="desk")
        bids = [b["id"] for b in self.e.list_batches()]
        if client:
            bids = [b for b in bids if self.batch_client(b) == client]
        per = []
        for b in bids:
            try:
                per.append(self._batch_metrics(b))
            except (KeyError, FileNotFoundError, OSError):
                pass
        rows = [r for p in per for r in p["jobs"]]
        dels = [p["delivered"] for p in per if p["delivered"]]
        s = M.summarize(rows, dels)
        out = dict(scope="client" if client else "all", source="desk", summary=s,
                   batches=[dict(batch=p["batch"], name=p["name"], client=p["client"], **{
                       k: p["summary"][k] for k in ("jobs", "review_s_median", "rework_rate", "red_rate",
                                                    "cost_per_clip", "delivered_clips", "turnaround_h")})
                            for p in per])
        if client:
            out["crm"] = self.crm(client)
        else:
            out["clients"] = [dict(c, crm=self.crm(c["slug"])) for c in self.list_clients()]
        return out

    def weekly(self, today=None):
        if self.has("metrics"):
            try:
                doc = self.runner.json(["metrics", "--all", "--csv", "--json"])
                if isinstance(doc, dict) and doc.get("csv"):
                    return dict(csv=doc["csv"], rows=doc.get("rows") or [], columns=M.WEEKLY_COLUMNS, source="engine")
            except Exception:  # noqa: BLE001
                pass
        crm = self.store.get("crm", {}) or {}
        dels = [dict(at=d["at"], items=d.get("items"), jobs=d.get("jobs")) for d in
                (self.store.get("deliveries", {}) or {}).values()]
        last_at = {}
        for e in self.store.timing_events():
            if e.get("event") == "stop" and e.get("what") == "review":
                k = (e["batch"], e["job"])
                last_at[k] = max(last_at.get(k, 0), e["at"])
        tj = []
        by_batch = {}
        for (b, j), at in last_at.items():
            if b not in by_batch:
                try:
                    by_batch[b] = {r["id"]: r for r in self._batch_metrics(b)["jobs"]}
                except (KeyError, FileNotFoundError, OSError):
                    by_batch[b] = {}
            r = by_batch[b].get(j)
            if r:
                tj.append(dict(at=at, review_s=r["review_s"], rework=r["rework"] > 0, qc=r["qc"], cost=r["cost"]))
        rows = M.weekly_rows(crm, dels, tj, self.store.get("weekly_manual", {}) or {}, today=today)
        return dict(csv=M.to_csv(rows), rows=rows, columns=M.WEEKLY_COLUMNS, source="desk")

    def set_weekly_manual(self, body):
        self.store.update("weekly_manual", lambda d: d.setdefault(body["week"], {}).update(body["values"]))
        return self.weekly()


# ---------------------------------------------------------------------- helpers
def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


def _quiet(fn, args):
    try:
        fn(args)
    except Exception:  # noqa: BLE001
        pass


def _hook(h):
    if not isinstance(h, dict):
        return dict(start=None, end=None, text=str(h))
    src = h.get("src") or [h.get("start"), h.get("end")]
    text = h.get("text") if isinstance(h.get("text"), str) else " ".join(h.get("lines") or [])
    return dict(start=src[0], end=src[1], text=text)


def _edit_args(op, a):
    if op == "caption":
        return ["--cue", str(a["cue"]), "--text", a["text"]]
    if op == "trim":
        return ["--start", f"{a['start']:.2f}", "--end", f"{a['end']:.2f}"]
    if op == "hook":
        return ["--pick", str(a["pick"])]
    if op == "cover":
        return (["--t", f"{a['t']:.2f}"] if a.get("t") is not None else []) + ["--text", a.get("text") or ""]
    return ["--title", a.get("title") or "", "--body", a.get("body") or "", "--tags", ",".join(a.get("tags") or [])]


def _glossary_add(glossary, add):
    out = list(glossary)
    for g in add:
        if not any(x.get("wrong") == g["wrong"] for x in out):
            out.append(g)
    return out


HEX = __import__("re").compile(r"^#[0-9A-Fa-f]{6}$")
PLAT = __import__("re").compile(r"^[a-z][a-z-]{1,30}(:[a-z]{3,12})?$")


def _strs(v, name, n=50, ln=40):
    need(isinstance(v, list) and len(v) <= n and all(isinstance(x, str) and 0 < len(x) <= ln for x in v),
         f"{name}: up to {n} strings of max {ln} chars")
    return [x.strip() for x in v]


def validate_client(b, partial):
    """client.yaml fields (strict). ``partial``: an update (any subset; ``glossary_add`` allowed)."""
    need(isinstance(b, dict), "body must be an object")
    allowed = {"slug", "name", "style", "platforms", "tags", "glossary", "glossary_add", "fillers", "brand",
               "cover_style", "cleanup_profile", "notes"}
    extra = set(b) - allowed
    need(not extra, f"unknown client fields: {', '.join(sorted(extra))}")
    out = {} if partial else dict(DEFAULT_CLIENT)
    if not partial:
        need(isinstance(b.get("name"), str) and b["name"].strip(), "name required")
    if "name" in b:
        need(isinstance(b["name"], str) and 0 < len(b["name"].strip()) <= 60, "name: 1-60 chars")
        out["name"] = b["name"].strip()
    for k, n in (("style", 500), ("notes", 2000)):
        if k in b:
            need(isinstance(b[k], str) and len(b[k]) <= n, f"{k}: max {n} chars")
            out[k] = b[k]
    if "platforms" in b:
        need(isinstance(b["platforms"], list) and len(b["platforms"]) <= 8 and
             all(isinstance(p, str) and PLAT.match(p) for p in b["platforms"]), "platforms: like xiaohongshu:full")
        out["platforms"] = b["platforms"]
    if "tags" in b:
        out["tags"] = _strs(b["tags"], "tags", 50, 30)
    for k in ("glossary", "glossary_add"):
        if k in b:
            g = b[k]
            need(isinstance(g, list) and len(g) <= 500, f"{k}: list (max 500)")
            rows = []
            for x in g:
                need(isinstance(x, dict) and isinstance(x.get("wrong"), str) and isinstance(x.get("right"), str)
                     and 0 < len(x["wrong"]) <= 40 and 0 < len(x["right"]) <= 40, f"{k}: [{{wrong, right}}]")
                row = dict(wrong=x["wrong"], right=x["right"])
                for extra_k in ("source", "batch", "job"):
                    if isinstance(x.get(extra_k), str) and len(x[extra_k]) <= 128:
                        row[extra_k] = x[extra_k]
                rows.append(row)
            out[k] = rows
    if "fillers" in b:
        f = b["fillers"]
        need(isinstance(f, dict) and set(f) <= {"extra", "keep"}, "fillers: {extra: [], keep: []}")
        out["fillers"] = dict(extra=_strs(f.get("extra") or [], "fillers.extra", 100, 12),
                              keep=_strs(f.get("keep") or [], "fillers.keep", 100, 12))
    if "brand" in b:
        br = b["brand"]
        need(isinstance(br, dict) and set(br) <= {"accent", "highlight", "ink"} and
             all(isinstance(v, str) and HEX.match(v) for v in br.values()), "brand: {accent, highlight, ink} as #RRGGBB")
        out["brand"] = dict(br)
    if "cover_style" in b:
        need(b["cover_style"] in COVER_STYLES, f"cover_style: {' | '.join(COVER_STYLES)}")
        out["cover_style"] = b["cover_style"]
    if "cleanup_profile" in b:
        need(b["cleanup_profile"] in CLEANUP_PROFILES, f"cleanup_profile: {' | '.join(CLEANUP_PROFILES)}")
        out["cleanup_profile"] = b["cleanup_profile"]
    return out
