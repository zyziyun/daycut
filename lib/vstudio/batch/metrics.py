"""Review timing + production metrics (batch / client / all), JSON or the weekly CSV of the pilot tracker.

    python -m vstudio.batch timing  --batch B --job ep02 --event start --what review
    python -m vstudio.batch timing  --batch B --job ep02 --event stop  --what review [--seconds 41.5]
    python -m vstudio.batch metrics --batch B            # one batch: per job + summary
    python -m vstudio.batch metrics --client acme        # every batch of the client + its funnel (client.yaml crm)
    python -m vstudio.batch metrics --all [--csv]        # every registered batch; --csv: the weekly table

Timing events live in the batch store (``timing`` table). A job's review seconds = the sum of its ``stop``
events' ``--seconds`` (the active time the desk measured), or stop - start when a stop carries no seconds;
``--event add --seconds S`` books time directly.

Per job: review_s, edits, reruns, rework (edited / re-run / rejected), QC light, cost, output duration.
Summary: jobs, done, approved, delivered, review_s_total / median per clip, rework rate, red rate, cost per
clip, deliveries, turnaround (first plan -> first delivery, hours).

Weekly CSV columns (gtm weekly metrics sheet): 周, 线索数, 沟通数, 样片数, 确认试点数, 交付数, 回传数据数, 付费数, 收入(¥),
交付条数, 人审秒数中位数/条, 返工率, 质检红灯率, 每条成本($), 内容号播放中位数, 内容号收藏率, 内容号涨粉, 工作室号有效线索 - filled
where the engine has the data (deliveries, review timing, QC, cost; the funnel from client.yaml ``crm``:
``history: [{stage: lead|contacted|sample|pilot|delivered|data|paid, at: YYYY-MM-DD}]``, ``revenue: [{at,
amount}]``), blank otherwise. Weeks start Monday ``week0`` (default 2026-10-06 = W1, ``$VSTUDIO_WEEK0``).
"""
import csv
import datetime as dt
import io
import os
import statistics

from .store import Store

FUNNEL = ("lead", "contacted", "sample", "pilot", "delivered", "data", "paid")
WEEKLY_COLUMNS = ["周", "线索数", "沟通数", "样片数", "确认试点数", "交付数", "回传数据数", "付费数", "收入(¥)", "交付条数",
                  "人审秒数中位数/条", "返工率", "质检红灯率", "每条成本($)", "内容号播放中位数", "内容号收藏率", "内容号涨粉",
                  "工作室号有效线索"]
FUNNEL_COL = {"lead": "线索数", "contacted": "沟通数", "sample": "样片数", "pilot": "确认试点数", "data": "回传数据数",
              "paid": "付费数"}
EVENTS = ("start", "stop", "add")


def _week0():
    return dt.date.fromisoformat(os.environ.get("VSTUDIO_WEEK0") or "2026-10-06")


def _median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def _rate(n, d):
    return round(n / d, 3) if d else None


# --------------------------------------------------------------------------- timing
def review_seconds(events, what="review"):
    """Timing rows ({event, what, seconds, ts}) -> active seconds."""
    total, open_ts = 0.0, None
    for e in sorted(events or [], key=lambda e: e.get("ts") or 0):
        if e.get("what", what) != what:
            continue
        ev = e.get("event")
        if ev == "start":
            open_ts = e.get("ts")
        elif ev == "stop":
            if e.get("seconds") is not None:
                total += float(e["seconds"])
            elif open_ts is not None and e.get("ts") is not None:
                total += max(0.0, float(e["ts"]) - float(open_ts))
            open_ts = None
        elif ev == "add" and e.get("seconds") is not None:
            total += float(e["seconds"])
    return round(total, 1)


def timing(batch_dir, job, event, what="review", seconds=None, actor=None, ts=None):
    if event not in EVENTS:
        raise ValueError(f"--event {event}: {' | '.join(EVENTS)}")
    if seconds is not None and (float(seconds) < 0 or float(seconds) > 24 * 3600):
        raise ValueError("--seconds: 0 .. 86400")
    st = Store(batch_dir)
    try:
        if not st.job(job):
            raise KeyError(f"unknown job {job}")
        st.add_timing(job, event, what, None if seconds is None else float(seconds), actor, ts)
        total = review_seconds(st.timing(job), what)
        return dict(ok=True, job=job, event=event, what=what, seconds=seconds, total_s=total,
                    **({"review_s": total} if what == "review" else {}))
    finally:
        st.close()


# --------------------------------------------------------------------------- per batch
def _job_events(st):
    out = {}
    for e in st.q("SELECT * FROM events WHERE job IS NOT NULL ORDER BY ts"):
        out.setdefault(e["job"], []).append(e)
    return out


def batch_metrics(batch_dir):
    st = Store(batch_dir)
    try:
        spec = st.spec
        jobs = st.jobs()
        evs = _job_events(st)
        tim = {}
        for t in st.timing():
            tim.setdefault(t["job"], []).append(t)
        eds = {}
        for e in st.edits(include_undone=False):
            eds[e["job"]] = eds.get(e["job"], 0) + 1
        dels = st.deliveries()
        rows_all = st.all_stage_rows()
        first = st.q("SELECT MIN(ts) AS t FROM events")[0]["t"]
    finally:
        st.close()
    delivered_jobs = set()
    for d in dels:
        delivered_jobs |= set((d.get("sources") or {}).get("jobs") or []) if isinstance(d.get("sources"), dict) else set()
    rows = []
    for j in jobs:
        if j["state"] == "dropped":
            continue
        je = evs.get(j["id"]) or []
        reruns = sum(1 for e in je if e["kind"] == "rerun")
        rejected = j["state"] == "needs-replan" or j.get("review") == "rejected"
        rs = review_seconds(tim.get(j["id"]))
        last_review = max([t["ts"] for t in tim.get(j["id"]) or [] if t["event"] in ("stop", "add")] or [0]) or None
        done_ts = max([e["ts"] for e in je if e["kind"] == "job" and str(e["msg"]).startswith("done")] or [0]) or None
        cm = ((rows_all.get(j["id"]) or {}).get("compose") or {}).get("out") or {}
        n_ed = eds.get(j["id"], 0)
        rows.append(dict(id=j["id"], title=(j["params"] or {}).get("title") or "", state=j["state"], qc=j["qc"],
                         review=j.get("review"), review_s=rs, edits=n_ed, reruns=reruns, rejected=rejected,
                         rework=bool(n_ed or reruns or rejected), cost=round(float(j["cost"] or 0), 4),
                         duration=cm.get("duration"), last_review_ts=last_review, done_ts=done_ts,
                         delivered=j["id"] in delivered_jobs or j["state"] == "packaged" and bool(dels)))
    s = summarize(rows, dels)
    s["turnaround_h"] = round((dels[0]["ts"] - first) / 3600, 2) if dels and first else None
    return dict(scope="batch", batch=spec.get("name"), dir=os.path.abspath(batch_dir),
                client=(spec.get("_client") or {}).get("slug"), created=first, summary=s, jobs=rows,
                batches=[dict(batch=spec.get("name"), dir=os.path.abspath(batch_dir),
                              client=(spec.get("_client") or {}).get("slug"),
                              **{k: s.get(k) for k in ("jobs", "review_s_median", "rework_rate", "red_rate",
                                                       "cost_per_clip", "delivered_clips", "turnaround_h")})],
                deliveries=[dict(at=d["ts"], dir=d["dir"], zip=d["zip"], code=d["code"], items=d["items"],
                                 jobs=d["jobs"], cleanup_due=d["cleanup_due"], cleaned=d["cleaned"]) for d in dels])


def summarize(rows, deliveries=()):
    reviewed = [r for r in rows if r["review_s"] > 0 or r["state"] in ("approved", "packaged", "needs-replan")]
    qcd = [r for r in rows if r["qc"] in ("green", "red")]
    done = [r for r in rows if r["state"] in ("done", "approved", "packaged", "needs-replan")]
    return dict(jobs=len(rows), done=len(done), approved=sum(r["state"] in ("approved", "packaged") for r in rows),
                reviewed=len(reviewed), review_s_total=round(sum(r["review_s"] for r in rows), 1),
                review_s_median=_median([r["review_s"] for r in rows if r["review_s"] > 0]),
                rework_rate=_rate(sum(1 for r in reviewed if r["rework"]), len(reviewed)),
                red_rate=_rate(sum(1 for r in qcd if r["qc"] == "red"), len(qcd)),
                cost_total=round(sum(r["cost"] for r in rows), 4),
                cost_per_clip=round(sum(r["cost"] for r in done) / len(done), 4) if done else None,
                edits=sum(r["edits"] for r in rows), reruns=sum(r["reruns"] for r in rows),
                deliveries=len(deliveries), delivered_items=sum(int(d["items"] or 0) for d in deliveries),
                delivered_clips=sum(int(d["jobs"] or 0) for d in deliveries))


# --------------------------------------------------------------------------- client / all
def _many(dirs):
    per = []
    for d in dirs:
        try:
            per.append(batch_metrics(d))
        except (FileNotFoundError, OSError, ValueError):
            continue
    return per


def _rollup(per):
    rows = [r for p in per for r in p["jobs"]]
    dels = [d for p in per for d in p["deliveries"]]
    s = summarize(rows, [dict(items=d["items"], jobs=d["jobs"]) for d in dels])
    return s, [dict(batch=p["batch"], dir=p["dir"], client=p["client"],
                    **{k: p["summary"][k] for k in ("jobs", "review_s_median", "rework_rate", "red_rate",
                                                    "cost_per_clip", "delivered_clips", "turnaround_h")})
               for p in per]


def client_metrics(cdir):
    from . import clients as CL
    per = _many([b["dir"] for b in CL.batches(cdir)])
    s, bl = _rollup(per)
    cfg = CL.load(cdir) if os.path.exists(CL.yaml_path(cdir)) else {}
    return dict(scope="client", client=os.path.basename(cdir), dir=cdir, name=cfg.get("name"), summary=s, batches=bl,
                jobs=[dict(r, batch=p["batch"]) for p in per for r in p["jobs"]], crm=cfg.get("crm") or {},
                _per=per, _clients=[cfg])


def all_metrics():
    from . import clients as CL
    dirs = [b["dir"] for b in CL.batches()]
    for c in CL.list_clients():
        dirs += [b["dir"] for b in CL.batches(c["dir"]) if b["dir"] not in dirs]
    per = _many(dirs)
    s, bl = _rollup(per)
    cl = []
    for c in CL.list_clients():
        try:
            cl.append(CL.load(c["dir"]))
        except Exception:  # noqa: BLE001
            pass
    return dict(scope="all", summary=s, batches=bl, jobs=[dict(r, batch=p["batch"]) for p in per for r in p["jobs"]],
                clients=[dict(slug=c["slug"], name=c["name"]) for c in CL.list_clients()], _per=per, _clients=cl)


# --------------------------------------------------------------------------- weekly CSV
def week_of(ts, week0=None):
    week0 = week0 or _week0()
    d = dt.date.fromtimestamp(ts) if isinstance(ts, (int, float)) else dt.date.fromisoformat(str(ts)[:10])
    return (d - week0).days // 7 + 1


def week_label(n, week0=None):
    week0 = week0 or _week0()
    a = week0 + dt.timedelta(days=7 * (n - 1))
    b = a + dt.timedelta(days=6)
    return f"W{n}({a.month}/{a.day}-{b.month}/{b.day})"


def weekly_rows(per, clients=(), week0=None, today=None):
    week0 = week0 or _week0()
    today = today or dt.date.today()
    last = max(4, week_of(today.isoformat(), week0))
    out = []
    for n in range(1, last + 1):
        row = {c: "" for c in WEEKLY_COLUMNS}
        row["周"] = week_label(n, week0)
        counts = {s: 0 for s in FUNNEL}
        revenue, have_crm = 0.0, False
        for c in clients or []:
            crm = c.get("crm") or {}
            for h in crm.get("history") or []:
                have_crm = True
                if h.get("stage") in counts and h.get("at") and week_of(h["at"], week0) == n:
                    counts[h["stage"]] += 1
            for r in crm.get("revenue") or []:
                have_crm = True
                if r.get("at") and week_of(r["at"], week0) == n:
                    revenue += float(r.get("amount") or 0)
        if have_crm:
            for s, col in FUNNEL_COL.items():
                row[col] = counts[s]
            row["收入(¥)"] = round(revenue, 2)
        dels = [d for p in per for d in p["deliveries"] if week_of(d["at"], week0) == n]
        jobs_rev = [r for p in per for r in p["jobs"] if r["last_review_ts"] and week_of(r["last_review_ts"], week0) == n]
        jobs_done = [r for p in per for r in p["jobs"] if r["done_ts"] and week_of(r["done_ts"], week0) == n]
        if dels or per:
            row["交付数"] = len(dels)
            row["交付条数"] = sum(int(d["jobs"] or 0) for d in dels)
        if jobs_rev:
            row["人审秒数中位数/条"] = _median([r["review_s"] for r in jobs_rev])
            row["返工率"] = _rate(sum(1 for r in jobs_rev if r["rework"]), len(jobs_rev))
        qcd = [r for r in jobs_done if r["qc"] in ("green", "red")]
        if qcd:
            row["质检红灯率"] = _rate(sum(1 for r in qcd if r["qc"] == "red"), len(qcd))
        if jobs_done:
            row["每条成本($)"] = round(sum(r["cost"] for r in jobs_done) / len(jobs_done), 4)
        out.append(row)
    return out


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=WEEKLY_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in WEEKLY_COLUMNS})
    return buf.getvalue()


def metrics(batch=None, client=None, all_=False, csv_=False, today=None):
    """-> the metrics document (``csv_``: plus ``csv`` text + ``rows`` of the weekly table for that scope)."""
    if batch:
        doc = batch_metrics(batch)
        per, cl = [doc], []
        if doc.get("client"):
            from . import clients as CL
            try:
                st = Store(batch)
                cdir = CL.batch_client_dir(st.spec)
                st.close()
                cl = [CL.load(cdir)] if cdir and os.path.exists(CL.yaml_path(cdir)) else []
            except Exception:  # noqa: BLE001
                cl = []
    elif client:
        doc = client_metrics(client)
        per, cl = doc.pop("_per"), doc.pop("_clients")
    else:
        doc = all_metrics()
        per, cl = doc.pop("_per"), doc.pop("_clients")
    if csv_:
        rows = weekly_rows(per, cl, today=today)
        doc.update(columns=WEEKLY_COLUMNS, rows=rows, csv=to_csv(rows))
    return doc
