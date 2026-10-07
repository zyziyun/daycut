#!/usr/bin/env python3
"""Weekly GitHub snapshot for Reelfold: stars / forks / watchers, release downloads per asset, repo traffic.

    python3 scripts/metrics/github_stats.py                       # print the snapshot
    python3 scripts/metrics/github_stats.py metrics/github.csv    # ... and append one row to that CSV
    python3 scripts/metrics/github_stats.py --markdown            # Markdown (the weekly workflow's run summary)
    python3 scripts/metrics/github_stats.py --json

Token: GH_TOKEN / GITHUB_TOKEN, else `gh auth token`. Traffic (views, clones, referrers) needs push access to the
repo (a maintainer's `gh` login, or a fine-grained token with "Administration: read"); without it those columns
stay empty and the snapshot says so. GitHub keeps only the last 14 days of traffic, so run this at least weekly.

No user-level data: GitHub only gives totals and unique counts.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
DEFAULT_REPO = "zyziyun/reelfold"
CSV_FIELDS = [
    "date", "stars", "forks", "watchers", "open_issues",
    "dmg_downloads", "win_downloads", "update_downloads", "all_downloads",
    "views_7d", "visitors_7d", "clones_7d", "cloners_7d",
    "views_14d", "visitors_14d", "clones_14d", "cloners_14d",
    "top_referrers",
]


def token() -> str | None:
    for k in ("GH_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(k):
            return os.environ[k]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def get(path: str, tok: str | None):
    """-> (json, None) or (None, 'HTTP 403' / error text)"""
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json", "User-Agent": "reelfold-metrics",
                                                     **({"Authorization": f"Bearer {tok}"} if tok else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError) as e:
        return None, str(e)


def asset_kind(name: str) -> str:
    """dmg = a new Mac install; win = a Windows installer; update = electron-updater files (zip, blockmap, yml)."""
    n = name.lower()
    if n.endswith(".dmg"):
        return "dmg"
    if n.endswith((".exe", ".msi", ".appx", ".msix")):
        return "win"
    return "update"


def last_days(series: list[dict], days: int, today: dt.date) -> tuple[int, int]:
    """Sum count / uniques of GitHub's daily traffic series over the last `days` days (today included). The uniques
    are per day, so their sum counts a person once per day ("visitor-days"), not once."""
    since = today - dt.timedelta(days=days - 1)
    c = u = 0
    for d in series or []:
        day = dt.date.fromisoformat(d["timestamp"][:10])
        if since <= day <= today:
            c += int(d.get("count", 0))
            u += int(d.get("uniques", 0))
    return c, u


def summarize(repo: dict, releases: list | None, views: dict | None, clones: dict | None, referrers: list | None, today: dt.date) -> dict:
    assets = []
    for rel in releases or []:
        if rel.get("draft"):
            continue
        for a in rel.get("assets", []):
            assets.append({"release": rel.get("tag_name", ""), "name": a["name"], "kind": asset_kind(a["name"]), "downloads": int(a.get("download_count", 0))})
    by = {k: sum(a["downloads"] for a in assets if a["kind"] == k) for k in ("dmg", "win", "update")}
    s = {
        "date": today.isoformat(),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "watchers": repo.get("subscribers_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "dmg_downloads": by["dmg"],
        "win_downloads": by["win"],
        "update_downloads": by["update"],
        "all_downloads": sum(by.values()),
        "assets": assets,
        "traffic": views is not None,
    }
    if views is not None:
        s["views_7d"], s["visitors_7d"] = last_days(views.get("views", []), 7, today)
        s["views_14d"], s["visitors_14d"] = views.get("count", 0), views.get("uniques", 0)
    if clones is not None:
        s["clones_7d"], s["cloners_7d"] = last_days(clones.get("clones", []), 7, today)
        s["clones_14d"], s["cloners_14d"] = clones.get("count", 0), clones.get("uniques", 0)
    s["referrers"] = [{"referrer": r["referrer"], "count": r["count"], "uniques": r["uniques"]} for r in (referrers or [])[:8]]
    s["top_referrers"] = ";".join(f'{r["referrer"]}:{r["count"]}' for r in s["referrers"][:5])
    return s


def append_csv(path: pathlib.Path, s: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow({k: s.get(k, "") for k in CSV_FIELDS})


def render(s: dict, repo: str, markdown: bool) -> str:
    v = lambda k: s.get(k, "-")  # noqa: E731
    lines = []
    h = (lambda t: f"### {t}") if markdown else (lambda t: f"\n{t}\n" + "-" * len(t))
    lines.append(h(f"GitHub: {repo} ({s['date']})"))
    lines.append(f"- Stars {v('stars')} · forks {v('forks')} · watchers {v('watchers')} · open issues {v('open_issues')}")
    lines.append(f"- Downloads (all time): Mac installers (.dmg) {v('dmg_downloads')} · Windows {v('win_downloads')} · "
                 f"auto-update files {v('update_downloads')}")
    if s["traffic"]:
        lines.append(f"- Repo traffic, last 7 days: {v('views_7d')} views ({v('visitors_7d')} visitor-days) · {v('clones_7d')} clones "
                     f"({v('cloners_7d')} cloner-days). 14 days: {v('views_14d')} views by {v('visitors_14d')} unique visitors · "
                     f"{v('clones_14d')} clones by {v('cloners_14d')} unique cloners")
        lines.append("  (clones include this repo's own CI checkouts, so they overstate skill installs)")
        if s["referrers"]:
            lines.append("- Top referrers (14 days): " + ", ".join(f"{r['referrer']} {r['count']} ({r['uniques']} unique)" for r in s["referrers"]))
    else:
        lines.append("- Repo traffic: not available (needs a token with push access: a maintainer's `gh` login, or the "
                     "METRICS_GH_TOKEN secret in the weekly workflow)")
    if s["assets"]:
        lines.append("")
        lines.append("| Release | Asset | Downloads |" if markdown else "Release assets:")
        if markdown:
            lines.append("|---|---|---:|")
        for a in sorted(s["assets"], key=lambda a: (-a["downloads"], a["name"]))[:20]:
            lines.append(f"| {a['release']} | {a['name']} | {a['downloads']} |" if markdown else f"  {a['release']:<10} {a['name']:<48} {a['downloads']:>6}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="append one row to this CSV (header written when new)")
    ap.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPO)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    tok = token()
    repo, err = get(f"/repos/{a.repo}", tok)
    if repo is None:
        print(f"github_stats: cannot read {a.repo}: {err}", file=sys.stderr)
        return 1
    releases, _ = get(f"/repos/{a.repo}/releases?per_page=100", tok)
    views, verr = get(f"/repos/{a.repo}/traffic/views", tok)
    clones, _ = get(f"/repos/{a.repo}/traffic/clones", tok)
    referrers, _ = get(f"/repos/{a.repo}/traffic/popular/referrers", tok)
    s = summarize(repo, releases, views, clones, referrers, dt.datetime.now(dt.timezone.utc).date())
    if a.csv:
        append_csv(pathlib.Path(a.csv), s)
    print(json.dumps(s, indent=1) if a.json else render(s, a.repo, a.markdown))
    if views is None and not a.json:
        print(f"(traffic: {verr})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
