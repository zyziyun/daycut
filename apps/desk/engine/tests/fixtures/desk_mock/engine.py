"""The test engine: same API as RealEngine, in memory, no ffmpeg / whisper needed. Tests only (the desk's e2e
harness starts it with DESK_ENGINE_MOCK=1 in a dev build; it is not shipped in the app).

A run walks every job through the real stage names with a short sleep per stage; job 4, 8, ... go red.
"""
import datetime as dt
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time

from desk_engine.common import safe_name, BadRequest, batch_id, need, sha1_json, write_json
from desk_engine.real import verify_manifest

from .transcript import fake_transcript

STAGES = ["probe", "extract", "asr", "cleanup", "apply", "compose", "glossary", "proofread", "export", "verify", "qc",
          "preview"]
RECIPES = [
    dict(name="longform-slices", description="one long recording + a job list of ranges -> cleaned, captioned "
                                             "vertical slices per platform", stages=STAGES),
    dict(name="talkinghead-clips", description="a folder of raw 口播 clips -> one cleaned, captioned short per clip "
                                               "per platform", stages=STAGES),
]

WORDS = ("嗯 今天 我们 来 讲 那个 就是 怎么 用 一个 文件夹 批量 剪 口播 呃 首先 你 要 准备 好 素材 然后 然后 "
         "选 一个 配方 再 点 开始").split()


def _fake_cleanup(seed):
    words, t = [], 0.0
    for w in WORDS:
        te = t + 0.18 + 0.04 * (len(w))
        words.append(dict(w=w, t=round(t, 2), te=round(te, 2)))
        t = te + 0.08
    edits = [
        dict(id=1, kind="filler", text="嗯", words=[0], action="auto", reason="hesitation", confidence=0.97),
        dict(id=2, kind="filler", text="那个", words=[5], action="confirm", reason="semantic filler, isolated",
             confidence=0.6),
        dict(id=3, kind="filler", text="就是", words=[6], action="confirm", reason="semantic filler", confidence=0.55),
        dict(id=4, kind="filler", text="呃", words=[14], action="auto", reason="hesitation", confidence=0.95),
        dict(id=5, kind="repeat", text="然后", words=[22], action="auto", reason="immediate repeat", confidence=0.9),
        dict(id=6, kind="pause", text="", words=[], action="auto", reason="pause 0.9s -> 0.3s", confidence=0.99),
    ]
    for e in edits:
        ws = e["words"] or [10]
        e["t0"], e["t1"] = words[ws[0]]["t"], words[ws[-1]]["te"]
    return words, edits


class MockEngine:
    mode = "mock"

    def __init__(self, data_dir, registry, bus, step=0.25):
        self.data_dir = data_dir
        self.bus = bus
        self.step = step
        self.batches = {}
        self.threads = {}
        self.cancel_flags = {}
        self._lock = threading.RLock()
        if os.environ.get("DESK_MOCK_SEED", "1") != "0":       # tests: an empty desk (first run)
            self._seed()

    # ------------------------------------------------------------------ seed data
    def _seed(self):
        b = self._new("demo-course", "longform-slices", ["xiaohongshu:full", "tiktok:vertical"], n=8,
                      d=os.path.join(self.data_dir, "mock", "batch-demo-course"))
        for i, j in enumerate(b["jobs"]):
            if i < 5:
                self._finish_job(b, j, red=(i == 3))
            if i < 2:
                j["state"], j["review"] = "approved", "approved"
        b["state"] = "pilot-review"

    def _new(self, name, recipe, platforms, n, d, budget=None, rows=None):
        bid = batch_id(d)
        jobs = []
        rows = rows or [None] * n
        for i, row in enumerate(rows):
            jid = (row or {}).get("id") or f"s{i + 1:03d}"
            params = dict(title=f"第 {i + 1} 集：批量剪口播的小技巧", platforms=platforms,
                          range=[60.0 * i, 60.0 * i + 48.5], cleanup_reply="")
            if row:
                params.update({k: v for k, v in row.items() if k not in ("id", "start", "end")})
                params["range"] = [float(row["start"]), float(row["end"])]
                params["platforms"] = row.get("platforms") or platforms
            hooks = _mock_hooks(params["range"])
            params.setdefault("hook_candidates", hooks)
            params.setdefault("hook", params["hook_candidates"][0] if params["hook_candidates"] else None)
            params.setdefault("body", "用一个文件夹批量剪口播，省掉 80% 的重复劳动。")
            params.setdefault("tags", ["口播", "剪辑", "效率"])
            jobs.append(dict(id=jid, item=jid, variant="", state="planned", qc=None,
                             qc_reasons=None, sample=0, review=None, review_reason=None, pilot=0, cost=0.0,
                             params=params, stages={s: "pending" for s in STAGES}, duration=None))
        b = dict(id=bid, dir=d, name=name, recipe=recipe, state="planned", pause_reason=None, package=None,
                 pilot_jobs=[], budget=budget or dict(max_usd=5.0, max_hours=4), platforms=platforms, jobs=jobs,
                 events=[], manifest=None)
        self.batches[bid] = b
        return b

    def _finish_job(self, b, j, red=False):
        for s in STAGES:
            j["stages"][s] = "done"
        j["state"] = "done"
        j["qc"] = "red" if red else "green"
        j["qc_reasons"] = dict(red=["loudness -11.2 LUFS (target -14 ±1)"] if red else [],
                               warn=["title 21/20 chars (小红书)"] if red else [])
        a, z = j["params"]["range"]
        j["duration"] = round((z - a) * 0.85, 1)
        j["cost"] = 0.012

    def _b(self, bid):
        b = self.batches.get(bid)
        if not b:
            raise KeyError(f"unknown batch {bid}")
        return b

    def _log(self, b, kind, msg, job=None, stage=None):
        b["events"].insert(0, dict(ts=time.time(), job=job, stage=stage, kind=kind, msg=msg))
        del b["events"][200:]

    # ------------------------------------------------------------------ info
    def health(self):
        return dict(mode=self.mode, engine_path=None, vstudio=None, python=sys.executable,
                    h264_encoder=os.environ.get("VSTUDIO_H264_ENCODER") or os.environ.get("DESK_H264_ENCODER") or None)

    def recipes(self):
        return RECIPES

    def running(self, bid):
        t = self.threads.get(bid)
        return bool(t and t.is_alive())

    def list_batches(self):
        out = []
        for b in self.batches.values():
            c = {}
            for j in b["jobs"]:
                c[j["state"]] = c.get(j["state"], 0) + 1
            c.update(total=len(b["jobs"]), green=sum(j["qc"] == "green" for j in b["jobs"]),
                     red=sum(j["qc"] == "red" for j in b["jobs"]))
            out.append(dict(id=b["id"], dir=b["dir"], name=b["name"], recipe=b["recipe"], state=b["state"],
                            package=b["package"], pause_reason=b["pause_reason"], counts=c, running=self.running(b["id"])))
        return out

    def roots(self):
        return [os.path.join(self.data_dir, "mock")] + sorted({b["dir"] for b in self.batches.values()})

    def dir_of(self, bid):
        return self._b(bid)["dir"]

    def create_batch(self, body):
        name = body["name"]
        need(not any(b["name"] == name for b in self.batches.values()), f"a batch named {name} exists")
        d = body.get("out_dir") or os.path.join(self.data_dir, "mock", f"batch-{safe_name(name)}")
        n = 6 if body["recipe"] == "longform-slices" else 4
        rows = _read_rows(body["segments"]) if body.get("segments") else None
        b = self._new(name, body["recipe"], body.get("platforms") or ["xiaohongshu:full"], n, d, body.get("budget"),
                      rows=rows)
        os.makedirs(d, exist_ok=True)
        self._log(b, "plan", f"{len(b['jobs'])} created")
        self.bus.publish("batches")
        return dict(id=b["id"], dir=d, spec=None, jobs=[j["id"] for j in b["jobs"]],
                    created=[j["id"] for j in b["jobs"]], updated=[], dropped=[])

    def import_batch(self, path):
        raise BadRequest("import needs the real engine (mock mode)")

    # ------------------------------------------------------------------ status / estimate
    def status(self, bid):
        b = self._b(bid)
        rows = []
        for j in b["jobs"]:
            done = sum(s == "done" for s in j["stages"].values())
            cur = next((k for k, s in j["stages"].items() if s == "running"), "")
            qr = j["qc_reasons"] or {}
            rows.append(dict(id=j["id"], state=j["state"], progress=f"{done}/{len(STAGES)}", stage=cur, qc=j["qc"],
                             sample=bool(j["sample"]), pilot=bool(j["pilot"]), review=j["review"] or "",
                             duration=j["duration"], cost=j["cost"], note=j["review_reason"] or ((qr.get("red") or [""])[0]),
                             title=j["params"]["title"], platforms=j["params"]["platforms"], item=j["item"],
                             variant=j["variant"], qc_red=qr.get("red") or [], qc_warn=qr.get("warn") or [],
                             review_reason=j["review_reason"]))
        meta = dict(id=bid, dir=b["dir"], name=b["name"], recipe=b["recipe"], state=b["state"],
                    pause_reason=b["pause_reason"], package=b["package"], pilot_jobs=b["pilot_jobs"],
                    budget=b["budget"], platforms=b["platforms"], running=self.running(bid))
        return dict(meta=meta, jobs=rows)

    def estimate(self, bid):
        b = self._b(bid)
        todo = [j for j in b["jobs"] if j["state"] in ("planned", "running", "failed")]
        sec = 48.5 * len(todo)
        stages = {s: dict(units=sec, seconds=sec * f, bytes=sec * 1e6 * f, n=len(todo), resource=r, measured=False)
                  for s, f, r in (("asr", 0.06, "asr"), ("apply", 0.35, "cpu-render"), ("export", 1.0, "cpu-render"))}
        machine = sum(s["seconds"] for s in stages.values())
        est = dict(jobs=len(todo), stages=stages, resources={"asr": stages["asr"]["seconds"],
                                                             "cpu-render": machine - stages["asr"]["seconds"]},
                   machine_s=machine, wall_s=machine / 3, storage_bytes=sum(s["bytes"] for s in stages.values()),
                   api_usd=0.0, spent_usd=0.0, free_bytes=200e9, limits={"asr": 1, "cpu-render": 3})
        over = []
        bud = b["budget"] or {}
        if bud.get("max_hours") is not None and est["wall_s"] / 3600 > float(bud["max_hours"]):
            over.append(f"wall time {est['wall_s'] / 3600:.2f} h > max_hours {bud['max_hours']}")
        est["budget"] = dict(ok=not over, over=over, budget=bud)
        est["text"] = f"mock estimate: {len(todo)} job(s)"
        return est

    def events(self, bid, n=50, job=None):
        ev = self._b(bid)["events"]
        return [e for e in ev if job is None or e["job"] == job][:n]

    # ------------------------------------------------------------------ run
    def run(self, bid, opts):
        b = self._b(bid)
        if self.running(bid):
            raise BadRequest("this batch is already running")
        if b["state"] == "pilot-review" and not opts.get("pilot") and not opts.get("confirm_pilot"):
            self.bus.publish("run-exit", batch=bid, code=4, status="pilot-waits")
            return dict(started=False, status="pilot-waits")
        est = self.estimate(bid)
        if not est["budget"]["ok"]:
            self.bus.publish("run-exit", batch=bid, code=2, status="over-budget")
            return dict(started=False, status="over-budget", over=est["budget"]["over"])
        todo = [j for j in b["jobs"] if j["state"] in ("planned", "failed")]
        if opts.get("retry_failed"):
            todo = [j for j in b["jobs"] if j["state"] == "failed"] + todo
        if opts.get("jobs"):
            todo = [j for j in todo if j["id"] in set(opts["jobs"])]
        if opts.get("pilot"):
            todo = todo[:int(opts["pilot"])]
            for j in todo:
                j["pilot"] = 1
            b["pilot_jobs"] = [j["id"] for j in todo]
        self.cancel_flags[bid] = threading.Event()
        t = threading.Thread(target=self._run, args=(b, todo, bool(opts.get("pilot"))), daemon=True)
        self.threads[bid] = t
        b["state"] = "running"
        self.bus.publish("run-start", batch=bid, cmd=["run"] + [k for k, v in opts.items() if v])
        t.start()
        return dict(started=True, pid=None)

    def _run(self, b, todo, pilot):
        bid = b["id"]
        stop = self.cancel_flags[bid]
        self.bus.publish("log", batch=bid, line=f"[batch] {len(todo)} job(s){' (pilot)' if pilot else ''} (mock)")
        for j in todo:
            j["state"] = "running"
        for j in todo:
            idx = int(j["id"][1:])
            for s in STAGES:
                if stop.is_set():
                    break
                j["stages"][s] = "running"
                self.bus.publish("status", batch=bid, status=self.status(bid))
                time.sleep(self.step)
                j["stages"][s] = "done"
            if stop.is_set():
                j["state"] = "planned"
                continue
            self._finish_job(b, j, red=(idx % 4 == 0))
            self._log(b, "done", f"qc {j['qc']}", job=j["id"])
            self.bus.publish("log", batch=bid, line=f"[batch] {j['id']} done, qc {j['qc']}")
        if stop.is_set():
            b["state"] = "planned"
            self.bus.publish("run-exit", batch=bid, code=130, status="cancelled")
        else:
            b["state"] = "pilot-review" if pilot else "ran"
            self.bus.publish("run-exit", batch=bid, code=0, status="pilot-review" if pilot else "ok")
        self.bus.publish("status", batch=bid, status=self.status(bid))

    def cancel(self, bid):
        f = self.cancel_flags.get(bid)
        if f and self.running(bid):
            f.set()
            return dict(cancelled=True)
        return dict(cancelled=False)

    def shutdown(self):
        for f in self.cancel_flags.values():
            f.set()

    # ------------------------------------------------------------------ review
    def review_items(self, bid):
        b = self._b(bid)
        out = []
        for j in b["jobs"]:
            if j["state"] not in ("done", "approved", "needs-replan", "packaged", "failed"):
                continue
            qr = j["qc_reasons"] or {}
            _, edits = _fake_cleanup(j["id"])
            confirm = [dict(id=e["id"], part="body", kind=e["kind"], text=e["text"], t0=e["t0"], t1=e["t1"],
                            before="今天我们来讲", after="怎么用一个文件夹", reason=e["reason"], confidence=e["confidence"])
                       for e in edits if e["action"] == "confirm"] if j["state"] == "done" else []
            out.append(dict(id=j["id"], item=j["item"], variant=j["variant"], state=j["state"], qc=j["qc"] or "none",
                            reasons=qr.get("red") or [], warnings=qr.get("warn") or [], sample=bool(j["sample"]),
                            pilot=bool(j["pilot"]), review=j["review"], review_reason=j["review_reason"],
                            title=j["params"]["title"], platforms=j["params"]["platforms"], range=j["params"]["range"],
                            hook=[], duration=j["duration"], sheet=None, snippet=None, files=[], confirm=confirm,
                            reply=j["params"].get("cleanup_reply") or ""))
        return out

    def apply_review(self, bid, d):
        b = self._b(bid)
        by = {j["id"]: j for j in b["jobs"]}
        out = dict(approved=[], rejected=[], replied=[], skipped=[])
        for jid, reply in (d.get("cleanup") or {}).items():
            j = by.get(jid)
            if not j:
                out["skipped"].append([jid, "unknown job"])
                continue
            if (j["params"].get("cleanup_reply") or "") == (reply or ""):
                continue
            j["params"]["cleanup_reply"] = reply
            j.update(state="planned", review=None, review_reason=None, qc=None, qc_reasons=None)
            j["stages"].update({s: "pending" for s in STAGES[STAGES.index("apply"):]})
            out["replied"].append(jid)
        for jid, dec in (d.get("decisions") or {}).items():
            j = by.get(jid)
            if not j:
                out["skipped"].append([jid, "unknown job"])
                continue
            if jid in out["replied"]:
                out["skipped"].append([jid, "cleanup reply given: re-run and review again"])
                continue
            kind = dec.get("decision") if isinstance(dec, dict) else dec
            if kind == "approve":
                if j["state"] not in ("done", "approved", "needs-replan"):
                    out["skipped"].append([jid, f"state {j['state']} cannot be approved"])
                    continue
                j.update(state="approved", review="approved", review_reason=None)
                out["approved"].append(jid)
            elif kind == "reject":
                j.update(state="needs-replan", review="rejected", review_reason=dec.get("reason") or "rejected")
                out["rejected"].append(jid)
            else:
                out["skipped"].append([jid, f"unknown decision {kind!r}"])
                continue
            self._log(b, "review", kind, job=jid)
        self.bus.publish("status", batch=bid, status=self.status(bid))
        return out

    # ------------------------------------------------------------------ package
    def _mock_video(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            return path
        if shutil.which("ffmpeg"):
            try:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                "testsrc=size=540x960:rate=30:duration=2", "-pix_fmt", "yuv420p", path],
                               check=True, timeout=30)
                return path
            except (subprocess.SubprocessError, OSError):
                pass
        with open(path, "wb") as f:
            f.write(b"mock video placeholder")
        return path

    def _mock_cover(self, path):
        if os.path.exists(path):
            return path
        if shutil.which("ffmpeg"):
            try:
                subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                                "testsrc=size=540x720:rate=1:duration=1", "-frames:v", "1", path],
                               check=True, timeout=30)
                return path
            except (subprocess.SubprocessError, OSError):
                pass
        return None

    def package(self, bid, opts):
        b = self._b(bid)
        jobs = [j for j in b["jobs"] if j["state"] in ("approved", "packaged")]
        if not jobs:
            raise BadRequest("no approved jobs to package (review first)")
        per_day = int(opts.get("per_day") or 1)
        start = opts.get("start") or (dt.date.today() + dt.timedelta(days=1)).isoformat()
        times = list(opts.get("times") or ["12:00", "19:00", "21:00"])
        while len(times) < per_day:
            times.append(times[-1])
        times = times[:per_day]
        pdir = os.path.join(b["dir"], "package")
        items, counters = [], {}
        for j in jobs:
            for p in j["params"]["platforms"]:
                name, _, orient = p.partition(":")
                key = f"{name}-{orient or 'vertical'}"
                k = counters.get(key, 0)
                counters[key] = k + 1
                folder = os.path.join(pdir, key, f"{k + 1:03d}_{j['id']}")
                vid = self._mock_video(os.path.join(folder, "video.mp4"))
                pp = j["params"]
                with open(os.path.join(folder, "post.md"), "w", encoding="utf-8") as f:
                    f.write(f"{pp['title']}\n\n{pp.get('body') or ''}\n\n"
                            + " ".join(f"#{t}" for t in pp.get("tags") or []) + "\n")
                cover = self._mock_cover(os.path.join(folder, "cover.jpg"))
                with open(vid, "rb") as f:
                    sha = hashlib.sha256(f.read()).hexdigest()
                day, slot = divmod(k, per_day)
                items.append(dict(job=j["id"], platform=key, title=j["params"]["title"],
                                  date=(dt.date.fromisoformat(start) + dt.timedelta(days=day)).isoformat(),
                                  time=times[slot], files=dict(video=os.path.relpath(vid, pdir),
                                                               post=os.path.relpath(os.path.join(folder, "post.md"), pdir),
                                                               **({"cover": os.path.relpath(cover, pdir)} if cover else {})),
                                  sha256=sha, bytes=os.path.getsize(vid), duration=j["duration"]))
                j["state"] = "packaged"
        items.sort(key=lambda x: (x["date"], x["time"], x["platform"], x["job"]))
        sched = dict(per_day=per_day, start=start, times=times)
        code = sha1_json(dict(batch=b["name"], schedule=sched, items=items))[:12]
        man = dict(batch=b["name"], schedule=sched, items=items, confirmation_code=code, note="mock package")
        write_json(os.path.join(pdir, "manifest.json"), man)
        b["manifest"] = man
        b["package"] = dict(code=code, dir=pdir, items=len(items))
        self.bus.publish("status", batch=bid, status=self.status(bid))
        return dict(dir=pdir, code=code, items=len(items), jobs=len(jobs), manifest=os.path.join(pdir, "manifest.json"))

    def manifest(self, bid):
        b = self._b(bid)
        if not b["package"]:
            return dict(manifest=None, dir=None, verify=dict(ok=False, reason="not packaged yet"))
        from desk_engine.common import read_json
        man = read_json(os.path.join(b["package"]["dir"], "manifest.json"))
        return dict(manifest=man, dir=b["package"]["dir"], verify=verify_manifest(man))

    # ------------------------------------------------------------------ job detail
    def _job(self, bid, jid):
        j = next((x for x in self._b(bid)["jobs"] if x["id"] == jid), None)
        if not j:
            raise KeyError(f"unknown job {jid}")
        return j

    def job(self, bid, jid):
        """Same shape as vstudio.batch.api.job_detail (job, stages, events, cleanup, transcript, captions, media)."""
        b = self._b(bid)
        j = self._job(bid, jid)
        words, edits = _fake_cleanup(jid)
        from desk_engine.real import _parse_reply_local
        r = _parse_reply_local(j["params"].get("cleanup_reply") or "")
        for e in edits:
            if e["action"] == "auto":
                e["cut"] = e["id"] not in r["keep"]
            else:
                e["cut"] = (e["id"] in r["approve"] or r["all_confirm"]) and e["id"] not in r["keep"]
        a, z = j["params"]["range"]
        src = [w for w in fake_transcript(z + 25) if a - 20 <= w["t"] and w["te"] <= z + 20]
        inside = [w for w in src if a <= (w["t"] + w["te"]) / 2 <= z]
        cues, over = [], j["params"].get("caption_overrides") or {}
        for k in range(0, len(inside), 8):
            ws = inside[k:k + 8]
            i = len(cues)
            heard = "".join(w["w"] for w in ws)
            cues.append(dict(i=i, start=round(ws[0]["t"] - a, 2), end=round(ws[-1]["te"] - a, 2),
                             text=over.get(str(i), heard), heard=heard))
        pdir = (b.get("package") or {}).get("dir")
        exports = []
        if pdir and j["state"] == "packaged":
            for it in (b.get("manifest") or {}).get("items") or []:
                if it["job"] == jid:
                    exports.append(dict(platform=it["platform"].rpartition("-")[0], orientation=it["platform"].rpartition("-")[2],
                                        file=os.path.join(pdir, it["files"]["video"]),
                                        cover=os.path.join(pdir, it["files"]["cover"]) if it["files"].get("cover") else None,
                                        post=os.path.join(pdir, it["files"]["post"]), duration=it["duration"]))
        return dict(job={k: j[k] for k in ("id", "item", "variant", "state", "qc", "qc_reasons", "review",
                                           "review_reason", "pilot", "sample", "cost", "params")},
                    recipe=b["recipe"],
                    stages=[dict(name=s, state=st, seconds=self.step if st == "done" else None, error=None, cached=False,
                                 attempts=1 if st == "done" else 0) for s, st in j["stages"].items()],
                    events=self.events(bid, 20, job=jid),
                    cleanup=dict(reply=j["params"].get("cleanup_reply") or "",
                                 parts=[dict(part="body", words=words, edits=edits, stats=None)]),
                    transcript=[dict(range=[a - 20, z + 20], text="".join(w["w"] for w in src),
                                     words=[dict(w=w["w"], t=w["t"], te=w["te"], cut=False) for w in src])],
                    captions=dict(cues=cues, provider="mock", changes=[], rejected=[], warnings=[]),
                    media=dict(master=None, sheet=None, snippet=None, exports=exports))

    # ------------------------------------------------------------------ v0.2 edits (desk adapter, mock side)
    def apply_edit(self, bid, jid, op, args, stages):
        """Apply a job edit to the params and mark ``stages`` stale (what `job edit` does in the engine)."""
        with self._lock:
            j = self._job(bid, jid)
            p = j["params"]
            if op == "caption":
                p.setdefault("caption_overrides", {})[str(args["cue"])] = args["text"]
            elif op == "trim":
                p["range"] = [float(args["start"]), float(args["end"])]
            elif op == "hook":
                p["hook_pick"] = int(args["pick"])
                p["hook"] = p["hook_candidates"][int(args["pick"])]
            elif op == "cover":
                p["cover"] = dict(t=args.get("t"), text=args.get("text") or "")
            elif op == "copy":
                p.update(title=args.get("title") or p.get("title"), body=args.get("body") or "", tags=args.get("tags") or [])
            elif op == "cut":
                if "cuts" in args:                 # undo
                    p["cuts"] = [list(c) for c in args["cuts"]]
                else:
                    p.setdefault("cuts", []).append([float(args["start"]), float(args["end"]), args.get("why") or ""])
            elif op == "notes":
                p["notes"] = list(args.get("lines") or [])
            for s in stages:
                if j["stages"].get(s) == "done":
                    j["stages"][s] = "stale"
            self._log(self._b(bid), "edit", f"{op} -> rerun {','.join(stages) or 'none'}", job=jid)
        self.bus.publish("status", batch=bid, status=self.status(bid))

    def clear_pending(self, bid, jid):
        j = self._job(bid, jid)
        for s, st in j["stages"].items():
            if st == "stale":
                j["stages"][s] = "done"
        self.bus.publish("status", batch=bid, status=self.status(bid))

    def rerun_job(self, bid, jid, stages):
        b = self._b(bid)
        j = self._job(bid, jid)
        if self.running(bid) or j["state"] == "running":
            raise BadRequest("this batch is already running")
        prev = j["state"]
        j["state"] = "running"

        def go():
            self.bus.publish("log", batch=bid, line=f"[rerun] {jid}: {', '.join(stages)} (mock)")
            for s in stages:
                j["stages"][s] = "running"
                self.bus.publish("status", batch=bid, status=self.status(bid))
                time.sleep(self.step)
                j["stages"][s] = "done"
            self._finish_job(b, j, red=False)
            if prev == "packaged" or prev == "approved":
                j.update(review=None, review_reason=None)          # an edited clip is reviewed again
            self._log(b, "rerun", f"{len(stages)} stage(s)", job=jid)
            self.bus.publish("run-exit", batch=bid, code=0, status="ok")
            self.bus.publish("status", batch=bid, status=self.status(bid))
        t = threading.Thread(target=go, daemon=True)
        self.threads[bid] = t
        t.start()
        return dict(started=True)


def _read_rows(path):
    from desk_engine.v02store import load_yaml
    with open(path, encoding="utf-8") as f:
        doc = load_yaml(f.read())
    rows = doc.get("segments") if isinstance(doc, dict) else doc
    need(isinstance(rows, list) and rows, "segments file has no rows")
    return rows


def _mock_hooks(rng):
    a, _z = rng
    lines = ["这一点 90% 的人都做错了", "先说结论：别再这么做", "面试官最想听的其实是这句"]
    return [dict(start=round(a + 2 + 6 * k, 2), end=round(a + 6 + 6 * k, 2), text=t) for k, t in enumerate(lines)]
