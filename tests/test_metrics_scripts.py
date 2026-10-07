"""scripts/metrics: the weekly GitHub snapshot and the app-usage summary (no network: fixtures + a local server)."""
import csv
import datetime as dt
import importlib.util
import json
import pathlib
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "metrics" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gh = load("github_stats")
usage = load("usage")

TODAY = dt.date(2026, 10, 12)


def series(key, days):
    return {"count": sum(c for _, c, _ in days), "uniques": max((u for *_, u in days), default=0),
            key: [{"timestamp": f"{d}T00:00:00Z", "count": c, "uniques": u} for d, c, u in days]}


def test_github_summary_counts_assets_and_traffic(tmp_path):
    releases = [
        {"tag_name": "v0.2.0", "draft": False, "assets": [
            {"name": "Reelfold-0.2.0-arm64.dmg", "download_count": 9},
            {"name": "Reelfold-0.2.0-arm64-mac.zip", "download_count": 30},
            {"name": "latest-mac.yml", "download_count": 50},
            {"name": "Reelfold-Setup-0.2.0.exe", "download_count": 2}]},
        {"tag_name": "v0.3.0", "draft": True, "assets": [{"name": "x.dmg", "download_count": 99}]},
    ]
    views = series("views", [("2026-10-01", 10, 3), ("2026-10-06", 4, 2), ("2026-10-12", 6, 1)])
    clones = series("clones", [("2026-10-11", 20, 5)])
    s = gh.summarize({"stargazers_count": 3, "forks_count": 1, "subscribers_count": 2, "open_issues_count": 0}, releases, views, clones,
                     [{"referrer": "xiaohongshu.com", "count": 7, "uniques": 4}], TODAY)
    assert (s["dmg_downloads"], s["win_downloads"], s["update_downloads"], s["all_downloads"]) == (9, 2, 80, 91)
    assert (s["views_7d"], s["visitors_7d"]) == (10, 3)  # 2026-10-06 .. 10-12
    assert (s["clones_7d"], s["cloners_7d"]) == (20, 5)
    assert s["top_referrers"] == "xiaohongshu.com:7"
    out = tmp_path / "gh.csv"
    gh.append_csv(out, s)
    gh.append_csv(out, s)
    rows = list(csv.DictReader(out.open()))
    assert len(rows) == 2 and rows[0]["stars"] == "3" and rows[0]["dmg_downloads"] == "9"
    md = gh.render(s, "o/r", markdown=True)
    assert "Mac installers (.dmg) 9" in md and "| v0.2.0 | Reelfold-0.2.0-arm64.dmg | 9 |" in md


def test_github_summary_without_traffic_access():
    s = gh.summarize({"stargazers_count": 0}, [], None, None, None, TODAY)
    assert s["traffic"] is False and "views_7d" not in s
    assert "not available" in gh.render(s, "o/r", markdown=False)


STATS = {
    "day": "2026-10-12", "definitions": {}, "installs_ever": 14, "dau": 3, "wau": 6, "mau": 11, "real_users": 7,
    "active_real_users_7d": 4, "retained_users": 2, "internal_installs": 1,
    "weekly": [{"week": "2026-10-05", "active": 5, "new_installs": 3, "batch_users": 3, "batches": 4, "clips_made": 40, "exports": 2,
                "clips_exported": 12, "packages": 1}],
    "by_version": [{"version": "0.2.0", "installs": 10}], "by_locale": [{"locale": "zh-CN", "installs": 9}],
    "by_os": [{"os": "darwin", "arch": "arm64", "installs": 11}],
}


def test_usage_render_says_how_far_from_the_target():
    txt = usage.render(STATS, markdown=False)
    assert "REAL USERS" in txt and "3 more to reach 10" in txt
    assert "enough for interviews" in usage.render({**STATS, "real_users": 12}, markdown=True)


def test_usage_needs_the_token(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("STATS_TOKEN", raising=False)
    monkeypatch.setattr(usage, "TOKEN_FILE", tmp_path / "none")
    assert usage.main([]) == 2
    assert "STATS_TOKEN" in capsys.readouterr().err


@pytest.fixture
def server():
    seen = []

    class H(BaseHTTPRequestHandler):
        def _reply(self, body):
            n = int(self.headers.get("content-length") or 0)
            seen.append((self.command, self.path, self.headers.get("authorization"), json.loads(self.rfile.read(n)) if n else None))
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self._reply(STATS)

        def do_POST(self):
            self._reply({"ok": True, "internal": [{"install_id": "x"}]})

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/api/v1", seen
    srv.shutdown()


def test_usage_reads_the_endpoint_and_appends_csv(server, monkeypatch, tmp_path, capsys):
    url, seen = server
    monkeypatch.setenv("REELFOLD_STATS_URL", url)
    monkeypatch.setenv("STATS_TOKEN", "t" * 32)
    out = tmp_path / "u.csv"
    assert usage.main(["--csv", str(out)]) == 0
    assert seen[0][:3] == ("GET", "/api/v1/stats", "Bearer " + "t" * 32)
    row = next(csv.DictReader(out.open()))
    assert row["real_users"] == "7" and row["clips_made_week"] == "40"
    assert "REAL USERS" in capsys.readouterr().out
    assert usage.main(["mark-internal", "33333333-3333-4333-A333-333333333333", "--note", "my mac"]) == 0
    assert seen[-1][0:2] == ("POST", "/api/v1/internal")
    assert seen[-1][3] == {"install_id": "33333333-3333-4333-a333-333333333333", "internal": True, "note": "my mac"}
