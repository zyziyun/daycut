"""Metrics (PRODUCT_V02.md P0-5) computed from desk-local data when the engine has no ``metrics`` command.

Per job: review seconds (sum of active review time sent by the desk), rework (re-renders after edits +
rejections), QC, cost. Per batch / client / all: counts, median review s per clip, rework rate, red rate,
cost per clip, deliveries, turnaround. Clients also carry the manual funnel (lead -> contacted -> sample ->
pilot -> delivered -> data -> paid) and 7-day post data. ``weekly_csv`` matches the gtm weekly metrics sheet (header kept in tests/fixtures/weekly_metrics.csv).
"""
import csv
import datetime as dt
import io
import statistics

FUNNEL = ("lead", "contacted", "sample", "pilot", "delivered", "data", "paid")
WEEKLY_COLUMNS = ["周", "线索数", "沟通数", "样片数", "确认试点数", "交付数", "回传数据数", "付费数", "收入(¥)", "交付条数",
                  "人审秒数中位数/条", "返工率", "质检红灯率", "每条成本($)", "内容号播放中位数", "内容号收藏率", "内容号涨粉",
                  "千剪号有效线索", "Release下载数", "跑完一批的外部用户数", "带价LOI数", "B2B对话数"]
# columns renamed in the gtm sheet: values saved under the old name still show (and export) under the new one
RENAMED_COLUMNS = {"工作室号有效线索": "千剪号有效线索"}
MANUAL_COLUMNS = WEEKLY_COLUMNS[14:]
WEEK0 = dt.date(2026, 10, 6)                # W1 starts 10/6 (the gtm weekly metrics sheet)


def median(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 1) if xs else None


def rate(n, d):
    return round(n / d, 3) if d else None


def job_rows(status, review_s, edits):
    """status (engine batch status) + {job: seconds} + {job: {reruns}} -> per-job metric rows."""
    rows = []
    for j in status.get("jobs") or []:
        e = edits.get(j["id"]) or {}
        rejected = j.get("review") == "rejected" or bool(j.get("review_reason")) or j.get("state") == "needs-replan"
        rows.append(dict(id=j["id"], title=j.get("title") or "", state=j.get("state"), qc=j.get("qc"),
                         cost=float(j.get("cost") or 0), review_s=round(review_s.get(j["id"], 0.0), 1),
                         reruns=int(e.get("reruns") or 0), edits=int(e.get("count") or 0), rejected=rejected,
                         rework=int(e.get("reruns") or 0) + (1 if rejected else 0)))
    return rows


def summarize(rows, deliveries=()):
    reviewed = [r for r in rows if r["review_s"] > 0 or r["state"] in ("approved", "packaged", "needs-replan")]
    qcd = [r for r in rows if r["qc"] in ("green", "red")]
    done = [r for r in rows if r["state"] in ("done", "approved", "packaged", "needs-replan")]
    return dict(
        jobs=len(rows), reviewed=len(reviewed),
        review_s_total=round(sum(r["review_s"] for r in rows), 1),
        review_s_median=median([r["review_s"] for r in rows if r["review_s"] > 0]),
        rework_rate=rate(sum(1 for r in reviewed if r["rework"] > 0), len(reviewed)),
        red_rate=rate(sum(1 for r in qcd if r["qc"] == "red"), len(qcd)),
        cost_total=round(sum(r["cost"] for r in rows), 4),
        cost_per_clip=round(sum(r["cost"] for r in done) / len(done), 4) if done else None,
        deliveries=len(deliveries), delivered_items=sum(int(d.get("items") or 0) for d in deliveries),
        delivered_clips=sum(int(d.get("jobs") or 0) for d in deliveries))


def week_of(ts, week0=WEEK0):
    d = dt.date.fromtimestamp(ts) if isinstance(ts, (int, float)) else dt.date.fromisoformat(str(ts)[:10])
    return (d - week0).days // 7 + 1


def week_label(n, week0=WEEK0):
    a = week0 + dt.timedelta(days=7 * (n - 1))
    b = a + dt.timedelta(days=6)
    return f"W{n}({a.month}/{a.day}-{b.month}/{b.day})"


def manual_values(week_values):
    """{column: value} as saved, with renamed columns mapped to their current name (the current name wins)."""
    out = {}
    for c, v in (week_values or {}).items():
        n = RENAMED_COLUMNS.get(c, c)
        if n not in out or c == n:
            out[n] = v
    return out


def weekly_rows(crm, deliveries, timing_jobs, manual, weeks=None, week0=WEEK0, today=None):
    """crm: {client: {history: [{stage, at}], revenue: [{at, amount}], posts: [...]}};
    deliveries: [{at, items, jobs}]; timing_jobs: [{at, review_s, rework, qc, cost}] (one per reviewed job,
    ``at`` = last review); manual: {"W1": {column: value}}. -> list of dicts keyed by WEEKLY_COLUMNS."""
    today = today or dt.date.today()
    last = max(4, week_of(today.isoformat(), week0))
    weeks = weeks or list(range(1, last + 1))
    out = []
    for n in weeks:
        row = {c: "" for c in WEEKLY_COLUMNS}
        row["周"] = week_label(n, week0)
        counts = {s: 0 for s in FUNNEL}
        revenue = 0.0
        for c in (crm or {}).values():
            for h in c.get("history") or []:
                if h.get("stage") in counts and week_of(h["at"], week0) == n:
                    counts[h["stage"]] += 1
            for r in c.get("revenue") or []:
                if week_of(r["at"], week0) == n:
                    revenue += float(r.get("amount") or 0)
        dels = [d for d in deliveries or [] if week_of(d["at"], week0) == n]
        tj = [t for t in timing_jobs or [] if week_of(t["at"], week0) == n]
        qcd = [t for t in tj if t.get("qc") in ("green", "red")]
        row.update({"线索数": counts["lead"], "沟通数": counts["contacted"], "样片数": counts["sample"],
                    "确认试点数": counts["pilot"], "交付数": len(dels), "回传数据数": counts["data"],
                    "付费数": counts["paid"], "收入(¥)": round(revenue, 2) if revenue else 0,
                    "交付条数": sum(int(d.get("jobs") or 0) for d in dels)})
        if tj:
            row["人审秒数中位数/条"] = median([t["review_s"] for t in tj])
            row["返工率"] = rate(sum(1 for t in tj if t.get("rework")), len(tj))
            row["每条成本($)"] = round(sum(float(t.get("cost") or 0) for t in tj) / len(tj), 4)
        if qcd:
            row["质检红灯率"] = rate(sum(1 for t in qcd if t["qc"] == "red"), len(qcd))
        for c in MANUAL_COLUMNS:
            v = manual_values((manual or {}).get(f"W{n}")).get(c)
            if v not in (None, ""):
                row[c] = v
        out.append(row)
    return out


def to_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=WEEKLY_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in WEEKLY_COLUMNS})
    return buf.getvalue()
