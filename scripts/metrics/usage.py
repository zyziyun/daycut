#!/usr/bin/env python3
"""How many real people use the Reelfold app? Reads the opt-in usage counts from the stats endpoint.

    python3 scripts/metrics/usage.py                         # the summary
    python3 scripts/metrics/usage.py --markdown              # Markdown (the weekly workflow's run summary)
    python3 scripts/metrics/usage.py --json
    python3 scripts/metrics/usage.py --csv metrics/usage.csv # ... and append one row to that CSV
    python3 scripts/metrics/usage.py mark-internal <install-id> [--note "my mac"]   # leave an install out of every number
    python3 scripts/metrics/usage.py unmark-internal <install-id>

Auth: the STATS_TOKEN secret (env STATS_TOKEN, or the first line of ~/.config/reelfold/stats_token). It is never
public; without it the endpoint answers 401. REELFOLD_STATS_URL overrides the endpoint (default
https://t.reelfold.com/api/v1).

Definitions (computed on the server, apps/telemetry/src/stats.ts; installs marked internal are always left out):
  real user          an install that finished at least one batch (on its own footage: the demo engine never counts)
  active real user   a real user with a finished batch in the last 7 days
  retained           finished batches in at least 2 different weeks
  installs           installs that turned "Share anonymous usage counts" on (the app sends nothing otherwise, so
                     these are a lower bound: people who never opt in are not counted anywhere)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://t.reelfold.com/api/v1"
TOKEN_FILE = pathlib.Path.home() / ".config" / "reelfold" / "stats_token"
CSV_FIELDS = ["day", "real_users", "active_real_users_7d", "retained_users", "installs_ever", "dau", "wau", "mau",
              "clips_made_week", "clips_exported_week", "internal_installs"]
TARGET = (10, 20)


def stats_token() -> str | None:
    t = os.environ.get("STATS_TOKEN", "").strip()
    if t:
        return t
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").splitlines()[0].strip() or None
    except (OSError, IndexError):
        return None


def call(method: str, path: str, tok: str, body: dict | None = None) -> dict:
    url = os.environ.get("REELFOLD_STATS_URL", DEFAULT_URL).rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}", "User-Agent": "reelfold-metrics/1", "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise SystemExit(f"usage.py: {method} {path} -> HTTP {e.code} {detail}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit(f"usage.py: cannot reach {url}: {e}")


def this_week(s: dict) -> dict:
    return s["weekly"][-1] if s.get("weekly") else {}


def render(s: dict, markdown: bool) -> str:
    lo, hi = TARGET
    real = s["real_users"]
    verdict = ("enough for interviews" if real >= lo else f"{lo - real} more to reach {lo}")
    out = []
    if markdown:
        out.append(f"### Reelfold app usage ({s['day']}, UTC)")
        out.append(f"**Real users (finished at least one batch): {real}** of the {lo}-{hi} needed for interviews ({verdict})")
        out.append("")
        out.append("| | |\n|---|---:|")
        rows = [("Active real users (a batch in the last 7 days)", s["active_real_users_7d"]),
                ("Retained (batches in 2+ different weeks)", s["retained_users"]),
                ("Installs sharing counts (ever)", s["installs_ever"]),
                ("DAU (yesterday) / WAU / MAU", f"{s['dau']} / {s['wau']} / {s['mau']}"),
                ("Internal installs left out", s["internal_installs"])]
        out += [f"| {k} | {v} |" for k, v in rows]
    else:
        out.append(f"Reelfold app usage ({s['day']}, UTC; {s['internal_installs']} internal install(s) left out)")
        out.append("")
        out.append(f"  REAL USERS (finished >= 1 batch)      {real:>5}   target {lo}-{hi}: {verdict}")
        out.append(f"  active real users (batch, last 7 d)   {s['active_real_users_7d']:>5}")
        out.append(f"  retained (batches in 2+ weeks)        {s['retained_users']:>5}")
        out.append(f"  installs sharing counts (ever)        {s['installs_ever']:>5}")
        out.append(f"  DAU (yesterday) / WAU / MAU           {s['dau']} / {s['wau']} / {s['mau']}")
    weekly = s.get("weekly", [])
    if weekly:
        out.append("")
        if markdown:
            out.append("| Week of | Active | New | Batch users | Batches | Clips made | Clips exported | Packages |\n|---|---:|---:|---:|---:|---:|---:|---:|")
            out += [f"| {w['week']} | {w['active']} | {w['new_installs']} | {w['batch_users']} | {w['batches']} | {w['clips_made']} | {w['clips_exported']} | {w['packages']} |" for w in weekly]
        else:
            out.append("  week of     active  new  batch-users  batches  clips-made  clips-exported  packages")
            out += [f"  {w['week']}  {w['active']:>6} {w['new_installs']:>4} {w['batch_users']:>12} {w['batches']:>8} {w['clips_made']:>11} {w['clips_exported']:>15} {w['packages']:>9}" for w in weekly]
    for key, label, fmt in (("by_version", "version", lambda r: r["version"]), ("by_locale", "language", lambda r: r["locale"]),
                            ("by_os", "system", lambda r: f"{r['os']}-{r['arch']}")):
        if s.get(key):
            out.append("")
            out.append(f"{'**' if markdown else '  '}Installs by {label} (last 30 days){'**' if markdown else ''}: " + ", ".join(f"{fmt(r)} {r['installs']}" for r in s[key]))
    return "\n".join(out)


def append_csv(path: pathlib.Path, s: dict) -> None:
    w = this_week(s)
    row = {k: s.get(k, "") for k in CSV_FIELDS}
    row["clips_made_week"], row["clips_exported_week"] = w.get("clips_made", 0), w.get("clips_exported", 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            wr.writeheader()
        wr.writerow(row)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="summary", choices=["summary", "mark-internal", "unmark-internal"])
    ap.add_argument("install_id", nargs="?")
    ap.add_argument("--note", default=None)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--csv", help="append one row to this CSV")
    a = ap.parse_args(argv)
    tok = stats_token()
    if not tok:
        print("usage.py: no STATS_TOKEN (env STATS_TOKEN or ~/.config/reelfold/stats_token); the app-usage numbers are "
              "not available until it is set (docs/CI_CD.md, Usage counts)", file=sys.stderr)
        return 2
    if a.command != "summary":
        if not a.install_id:
            ap.error("give the install id shown in the app (Settings > General > Privacy > Anonymous ID)")
        r = call("POST", "/internal", tok, {"install_id": a.install_id.strip().lower(), "internal": a.command == "mark-internal",
                                             **({"note": a.note} if a.note else {})})
        print(f"internal installs: {len(r.get('internal', []))}")
        return 0
    s = call("GET", "/stats", tok)
    if a.csv:
        append_csv(pathlib.Path(a.csv), s)
    print(json.dumps(s, indent=1) if a.json else render(s, a.markdown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
