"""v0.2 adapter (PRODUCT_V02.md): clients, AI segment planning, in-review edits, review timing, client delivery,
metrics. One facade over the engine.

For every v0.2 operation the adapter checks the engine's capabilities (caps.py). When the engine has the
command it is called (``python -m vstudio.batch <cmd> ... --json``); otherwise the desk's own faithful
implementation runs for the parts the desk can do itself (clients, timing, deliver from the publish package,
metrics). Operations that need media processing (plan-segments, job edit, job rerun) report ``engine lacks <cap>``
without the command. (The in-memory test engine in engine/tests/fixtures subclasses this for the desk's tests.)

Engine command contract (python -m vstudio.batch ..., all with --json; matches the engine's v0.2 CLI):
  plan-segments --source F --count N --min S --max S --provider claude|openai|none [--client DIR]
                [--platforms a,b] --out DIR
      -> {provider, duration, draft, segments: [{id,start,end,title,chapter,hook{start,end,text},
          hook_candidates[], notes[], tags[], why, risk, score}], words: [{w,t,te}]}
  client init|show|update --client DIR [--set JSON]       (update: glossary_add; crm mirrored here)
      -> {dir, slug, config, effective, batches}
  job edit --batch B --job J --op caption --cue I --text T | trim --start A --end B | hook --pick K
           | cover --t S --text T | copy --title T --body B --tags a,b | undo
      -> {ok, faithful, reason, rerun[], pending[], glossary_added[], undone?}
  job show (``job ID --json``) -> ... + edit{range, hook_pick, hook_candidates, cover, copy, history, pending}
  job rerun --batch B --job J                              (streamed like run; only the stale stages)
  deliver --batch B [--client DIR] [--zip] [--cleanup-days N] -> {dir, zip, items, jobs, manifest_data}
  metrics --batch B | --client DIR | --all [--csv]         -> {scope, summary, jobs?, batches?, rows?, csv?}
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
OP_ROOTS = {"caption": ["export"], "cover": ["export"], "copy": [], "hook": ["compose"], "trim": ["cleanup"],
            "cut": ["cleanup"], "notes": ["export"]}
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

    def has(self, cap):
        return self.caps.has(cap)

    def can(self, what):
        """plan | edit | rerun: the engine command behind it exists."""
        return self.has({"plan": "plan-segments", "edit": "job-edit", "rerun": "job-rerun"}[what])

    def _lacks(self, cap):
        raise BadRequest(f"engine lacks {cap} (update video-studio to use this in real mode)")

    def capabilities(self):
        return dict(mode=self.e.mode, **self.caps.info(),
                    fallback=dict(plan=self.can("plan"), edit=self.can("edit"), rerun=self.can("rerun")))

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
                   "# client.yaml - overrides the global persona for this client's batches (Reelfold)\n"
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
        crm = self.crm(slug)
        if self.has("client") and os.path.exists(os.path.join(self.client_dir(slug), "client.yaml")):
            try:
                self.runner.json(["client", "update", "--client", self.client_dir(slug), "--set",
                                  _json(dict(crm=dict(history=crm["history"], revenue=crm["revenue"],
                                                      posts=crm["posts"], price_next=crm["price_next"]))), "--json"])
            except Exception:  # noqa: BLE001  (the desk copy stays authoritative for the UI)
                pass
        return crm

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
        if not self.can("plan"):
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
        try:
            plan.update(state="done", progress="done", result=self._plan_segments(plan))
        except Exception as e:  # noqa: BLE001
            plan.update(state="error", error=str(e))
        self.bus.publish("plan", plan=plan["id"], state=plan["state"], progress=plan["progress"])

    def _plan_segments(self, plan):
        """``plan-segments`` through the engine -> {source, duration, provider, segments, words, draft}."""
        b = plan["request"]
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
        return res

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
        ee = d.pop("engine_edit", None)
        ee = ee if self.has("job-edit") else None
        if ee:                                     # the engine's own edit log is the source of truth
            hooks = ee.get("hook_candidates") or hooks
            copy = ee.get("copy") or {}
            p = dict(p, title=copy.get("title", p.get("title")), body=copy.get("body", p.get("body")),
                     tags=copy.get("tags", p.get("tags")), hook_pick=ee.get("hook_pick", p.get("hook_pick")),
                     cover=ee.get("cover") or p.get("cover"))
            rng = ee.get("range") or rng
            hist = [dict(n=h["n"], op=h["op"], args=h.get("value") or {}, before=h.get("before") or {}, at=h.get("at"),
                         rerun=h.get("rerun") or [], glossary_added=None)
                    for h in ee.get("history") or [] if not h.get("undone")]
            ent = dict(ent, history=hist, pending=ee.get("pending") or [])
        row_cuts = (d.get("cleanup") or {}).get("row_cuts") or p.get("cuts") or []
        d["edit"] = dict(
            range=rng, words=words, cues=cues, notes=[str(x) for x in (p.get("notes") or []) if x],
            cuts=[dict(start=c[0], end=c[1], why=c[2] if len(c) > 2 else "") for c in row_cuts
                  if isinstance(c, (list, tuple)) and len(c) >= 2],
            caption_overrides_missed=(ee or {}).get("caption_overrides_missed") or [], hooks=[_hook(h) for h in hooks], hook_pick=p.get("hook_pick"),
            cover=dict(t=(p.get("cover") or {}).get("t"), text=(p.get("cover") or {}).get("text", ""),
                       file=next((x.get("cover") for x in exports if x.get("cover")), None)),
            copy=dict(title=p.get("title") or "", body=p.get("body") or "", tags=p.get("tags") or []),
            history=ent.get("history") or [], pending=ent.get("pending") or [], reruns=ent.get("reruns") or 0,
            can_edit=self.can("edit"), can_rerun=self.can("rerun"),
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
        if op == "cut":
            need(e["range"], "this job has no source range to cut in")
            return dict(cuts=[[c["start"], c["end"], c["why"]] for c in e["cuts"]]), None
        if op == "notes":
            return dict(lines=list(e["notes"])), None
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
        if undo_of is None and _same(op, args, before):
            return dict(ok=True, faithful=True, reason="unchanged", rerun=[], glossary_added=None, noop=True,
                        pending=e["pending"], history=e["history"])
        res = dict(ok=True, faithful=True, reason=None, rerun=downstream(OP_ROOTS[op]), glossary_added=None)
        if op == "caption" and undo_of is None and not self.has("job-edit"):
            # the engine's own check re-hears the cue window (a correct re-hearing is accepted even when it is not a
            # sound-alike); without it, the desk's text check decides
            chk = P.faithful(cue["text"], args["text"], cue.get("heard"))
            res.update(faithful=chk["faithful"], reason=chk["reason"], reason_code=chk["reason"], ratio=chk["ratio"])
            if not chk["faithful"]:
                res.update(ok=False, rerun=[])
                return res
        if op == "cut" and undo_of is None:
            words = e["words"]
            a, b = P.snap(args["start"], words, "start"), P.snap(args["end"], words, "end")
            need(b > a, "the cut holds no whole word")
            rng = e["range"]
            need(rng[0] <= a and b <= rng[1], "the cut must be inside the clip range")
            need((rng[1] - rng[0]) - (b - a) >= 3.0, "a clip must keep at least 3 s")
            args = dict(args, start=round(a, 2), end=round(b, 2))
        if op == "trim":
            words = e["words"]
            a, b = P.snap(args["start"], words, "start"), P.snap(args["end"], words, "end")
            need(b - a >= 3.0, "a clip must be at least 3 s")
            args = dict(start=round(a, 2), end=round(b, 2))
        if self.has("job-edit"):
            doc = self.runner.json(["job", "edit", "--batch", self.e.dir_of(bid), "--job", jid, "--op", op,
                                    *_edit_args(op, args), "--json"])
            res.update(ok=bool(doc.get("ok", True)), faithful=bool(doc.get("faithful", doc.get("ok", True))),
                       reason=doc.get("reason") or doc.get("error"), reason_code=doc.get("reason_code"),
                       heard=doc.get("heard"), matched=doc.get("matched"),
                       rerun=doc.get("rerun") if doc.get("rerun") is not None else res["rerun"])
            ga = doc.get("glossary_added")
            res["glossary_added"] = (ga[0] if isinstance(ga, list) and ga else ga if isinstance(ga, dict) else None)
            if doc.get("pending") is not None:
                res["engine_pending"] = doc["pending"]
            if not res["ok"]:
                return res
        else:
            self.e.apply_edit(bid, jid, op, args, res["rerun"])
        if op == "caption" and undo_of is None and e.get("client") and not self.has("job-edit"):
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
        if "engine_pending" in res:
            ent["pending"] = res.pop("engine_pending")
        elif ent["since_rerun"] == 0 and undo_of is not None:
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
        if self.has("job-edit"):
            doc = self.runner.json(["job", "edit", "--batch", self.e.dir_of(bid), "--job", jid, "--op", "undo", "--json"])
            need(doc.get("ok", True), doc.get("reason") or "nothing to undo")
            ent = self._edits(bid).get(jid) or dict(history=[], pending=[], reruns=0, count=0, since_rerun=0)
            ent["pending"] = doc.get("pending") or []
            self._put_edits(bid, jid, ent)
            self.bus.publish("job-edit", batch=bid, job=jid)
            u = doc.get("undone") or {}
            return dict(ok=True, faithful=True, reason=None, rerun=doc.get("rerun") or [], pending=ent["pending"],
                        glossary_added=None, undone=dict(n=u.get("n"), op=u.get("op")))
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

    def _rerun(self, bid, jid, stages):
        if self.has("job-rerun"):
            return self.e.spawn_rerun(bid, jid)
        if self.has("job-edit"):         # the engine caches stages by params: a targeted run redoes only stale ones
            return self.e.run(bid, dict(jobs=[jid]))
        self._lacks("job-rerun")

    def rerun(self, bid, jid):
        ent = self._edits(bid).get(jid) or dict(history=[], pending=[], reruns=0, count=0, since_rerun=0)
        stages = ent.get("pending") or []
        need(stages, "nothing to re-render: no pending edits")
        r = self._rerun(bid, jid, stages)
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
        # None = the client's / engine default (never); 0 = never delete the sources (passed through, not dropped).
        # The creator's own workspace (no client / client "self") never schedules a cleanup.
        days = int(body["cleanup_days"]) if body.get("cleanup_days") is not None else None
        own = not client or client in OWN_CLIENTS
        if own:
            days = 0
        if self.has("deliver"):
            args = ["deliver", "--batch", self.e.dir_of(bid), "--json"]
            if client:
                args += ["--client", self.client_dir(client)]
            if body.get("zip", True):
                args.append("--zip")
            if days is not None:
                args += ["--cleanup-days", str(days)]
            r = self.runner.json(args, timeout=3600)
            if not isinstance(r.get("manifest"), dict):
                r["manifest"] = r.get("manifest_data") or {}
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
        rec = dict(batch=bid, client=client, at=time.time(), cleanup_note="own workspace: sources are never cleaned up"
                   if own and body.get("cleanup_days") else None, date=dt.date.today().isoformat(), dir=r.get("dir"),
                   zip=r.get("zip"), items=r.get("items") or len((r.get("manifest") or {}).get("items") or []),
                   jobs=r.get("jobs") or 0, duration_s=r.get("duration_s"),
                   cleanup=dict(enabled=bool(days), days=days, due=(time.time() + days * 86400) if days else None,
                                done=False),
                   manifest=dict(items=[dict(path=i.get("path"), sha256=i.get("sha256"), bytes=i.get("bytes"))
                                        for i in (r.get("manifest") or {}).get("items") or []]))
        self.store.update("deliveries", lambda d: d.__setitem__(bid, rec))
        if client:
            self.set_crm(client, dict(stage="delivered"))
        self.bus.publish("batches")
        return rec

    def delivery(self, bid):
        return (self.store.get("deliveries", {}) or {}).get(bid)

    def set_cleanup(self, bid, body):
        def f(d):
            need(bid in d, "not delivered yet")
            need(not body["enabled"] or (d[bid].get("client") and d[bid]["client"] not in OWN_CLIENTS),
                 "own workspace: source recordings are never cleaned up")
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
            if d.get("client") in OWN_CLIENTS or not d.get("client"):
                continue                                # own workspace: never
            m = self.store.batch_meta(bid)
            try:
                bdir = os.path.realpath(self.e.dir_of(bid))
            except KeyError:
                continue
            found = [p for p in (m.get("source"), m.get("folder")) if p and os.path.exists(p)]
            inside = [p for p in found if _inside(p, bdir)]
            out.append(dict(batch=bid, due=c["due"], paths=inside, outside=[p for p in found if p not in inside]))
        return out

    def cleanup_done(self, bid, paths):
        allowed = {p for x in self.cleanup_due(now=float("inf")) if x["batch"] == bid for p in x["paths"]}
        need(set(paths) <= allowed, "only the listed sources of this delivery can be marked cleaned")

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
                return self._from_engine(self.runner.json(args), client)
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

    def _from_engine(self, doc, client=None):
        from .common import batch_id
        doc = dict(doc, source="engine")
        for b in doc.get("batches") or []:
            b["name"] = b.get("batch")
            if b.get("dir"):
                b["batch"] = batch_id(b["dir"])
        if doc.get("scope") == "batch" and doc.get("dir"):
            doc["name"], doc["batch"] = doc.get("batch"), batch_id(doc["dir"])
        if doc.get("scope") == "all":
            doc["clients"] = [dict(c, crm=self.crm(c["slug"])) for c in self.list_clients()]
        if client:
            doc["crm"] = self.crm(client)
        return doc

    def weekly(self, today=None):
        if self.has("metrics"):
            try:
                doc = self.runner.json(["metrics", "--all", "--csv", "--json"])
                if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
                    rows = doc["rows"]
                    # the funnel lives with the desk's clients: fill what the engine left blank
                    funnel = {r["周"]: r for r in M.weekly_rows(self.store.get("crm", {}) or {}, [], [], {}, today=today)}
                    for r in rows:
                        d = funnel.get(r.get("周")) or {}
                        for c in ("线索数", "沟通数", "样片数", "确认试点数", "回传数据数", "付费数", "收入(¥)"):
                            if r.get(c) in (None, "") and c in d:
                                r[c] = d[c]
                    manual = self.store.get("weekly_manual", {}) or {}
                    for r in rows:
                        for c, v in M.manual_values(manual.get(str(r.get("周", "")).split("(")[0])).items():
                            if v not in (None, ""):
                                r[c] = v
                    return dict(csv=M.to_csv(rows), rows=rows, columns=M.WEEKLY_COLUMNS, source="engine")
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
OWN_CLIENTS = {"self", "me", "own"}


def _inside(path, folder):
    rp = os.path.realpath(path)
    return rp != folder and rp.startswith(folder.rstrip(os.sep) + os.sep)


def _json(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)


def _quiet(fn, args):
    try:
        fn(args)
    except Exception:  # noqa: BLE001
        pass


def _same(op, args, before):
    if op == "cut":
        return False
    if op == "trim":
        return abs(args["start"] - before["start"]) < 0.005 and abs(args["end"] - before["end"]) < 0.005
    return all(args.get(k) == before.get(k) for k in args)


def _hook(h):
    if not isinstance(h, dict):
        return dict(start=None, end=None, text=str(h))
    src = h.get("src") or [h.get("start"), h.get("end")]
    text = h.get("text") if isinstance(h.get("text"), str) else " ".join(h.get("lines") or [])
    return dict(start=src[0], end=src[1], text=text)


def _edit_args(op, a):
    if op == "caption":
        return ["--cue", str(a["cue"]), "--text", a["text"]] + (["--reasr"] if a.get("reasr") else [])
    if op == "cut":
        if "cuts" in a:                            # undo through the desk: the engine has its own `--op undo`
            raise BadRequest("undo a cut with the engine's undo")
        return ["--start", f"{a['start']:.2f}", "--end", f"{a['end']:.2f}"] + (["--why", a["why"]] if a.get("why") else [])
    if op == "notes":
        return ["--set", "|".join(a.get("lines") or [])]
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
PLAT = __import__("re").compile(r"^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$")


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
