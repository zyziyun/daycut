"""Publish calendar (发布): scheduled posts per day + the clips not scheduled yet.

Desk store ``<DESK_DATA_DIR>/calendar.json`` [{id, item, clip, title, platform, at "YYYY-MM-DDTHH:MM", state
planned|ready|posted, cover}]. ``vstudio.project calendar`` (pubcal) is the engine's own planner; the desk keeps
this store until the two are joined (the desk never posts: the assisted-fill browser stops before 发布).
"""
import hashlib
import os
import re
import threading
import time

from .common import need, read_json, write_json

AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
STATES = ("planned", "ready", "posted")
PLATFORM_RE = re.compile(r"^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$")


class Calendar:
    def __init__(self, data_dir, history, outputs, bus=None):
        self.path = os.path.join(data_dir, "calendar.json")
        self.history, self.outputs, self.bus = history, outputs, bus
        self._lock = threading.Lock()

    def _rows(self):
        r = read_json(self.path, []) or []
        return [x for x in r if isinstance(x, dict) and x.get("id")]

    def list(self, start=None, days=7):
        rows = self._rows()
        if start:
            need(re.match(r"^\d{4}-\d{2}-\d{2}$", start), "start: YYYY-MM-DD")
            t0 = time.mktime(time.strptime(start, "%Y-%m-%d"))
            ends = time.strftime("%Y-%m-%d", time.localtime(t0 + days * 86400))
            rows = [r for r in rows if start <= r["at"][:10] < ends]
        scheduled = {(r["item"], r["clip"]) for r in self._rows()}
        queue = []
        for e in self.history.list()["items"]:
            if (e.get("live") or {}).get("state") in ("running", "waiting") or e.get("status") not in (
                    "done", "delivered", "packaged"):
                continue
            try:
                cl = self.outputs.clips(e["id"])["clips"]
            except Exception:  # noqa: BLE001
                continue
            for c in cl:
                if c["state"] in ("done", "approved", "packaged") and not c.get("extra") and \
                        (e["id"], c["id"]) not in scheduled and c.get("files"):
                    queue.append(dict(item=e["id"], clip=c["id"], title=c["title"], project=e.get("name"),
                                      cover=c.get("cover"), aspects=[f["aspect"] for f in c["files"]]))
                if len(queue) >= 60:
                    break
        return dict(posts=sorted(rows, key=lambda r: r["at"]), queue=queue, at=time.time())

    def add(self, b):
        need(isinstance(b, dict), "body must be an object")
        need(isinstance(b.get("item"), str) and re.match(r"^[0-9a-f]{12}$", b["item"]), "item: project id")
        need(isinstance(b.get("clip"), str) and 0 < len(b["clip"]) <= 120, "clip: id")
        need(isinstance(b.get("at"), str) and AT_RE.match(b["at"]), "at: YYYY-MM-DDTHH:MM")
        pl = b.get("platform") or "xiaohongshu"
        need(isinstance(pl, str) and PLATFORM_RE.match(pl), "platform: id")
        clip = next((c for c in self.outputs.clips(b["item"])["clips"] if c["id"] == b["clip"]), None)
        need(clip is not None, "no such clip")
        row = dict(id=hashlib.sha1(f"{b['item']}{b['clip']}{pl}{time.time()}".encode()).hexdigest()[:12],
                   item=b["item"], clip=b["clip"], title=clip["title"], cover=clip.get("cover"), platform=pl,
                   at=b["at"], state="planned")
        with self._lock:
            rows = self._rows()
            rows.append(row)
            write_json(self.path, rows)
        self._pub()
        return row

    def update(self, pid, b):
        need(isinstance(b, dict), "body must be an object")
        with self._lock:
            rows = self._rows()
            row = next((r for r in rows if r["id"] == pid), None)
            if row is None:
                raise KeyError(f"no post {pid}")
            if b.get("remove"):
                rows = [r for r in rows if r["id"] != pid]
            else:
                if b.get("at") is not None:
                    need(isinstance(b["at"], str) and AT_RE.match(b["at"]), "at: YYYY-MM-DDTHH:MM")
                    row["at"] = b["at"]
                if b.get("state") is not None:
                    need(b["state"] in STATES, "state: planned | ready | posted")
                    row["state"] = b["state"]
            write_json(self.path, rows)
        self._pub()
        return dict(ok=True, post=row)

    def confirm_week(self, start):
        """确认本周排期: every planned post of the week becomes ready."""
        need(isinstance(start, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", start), "start: YYYY-MM-DD")
        t0 = time.mktime(time.strptime(start, "%Y-%m-%d"))
        end = time.strftime("%Y-%m-%d", time.localtime(t0 + 7 * 86400))
        n = 0
        with self._lock:
            rows = self._rows()
            for r in rows:
                if start <= r["at"][:10] < end and r["state"] == "planned":
                    r["state"] = "ready"
                    n += 1
            write_json(self.path, rows)
        self._pub()
        return dict(ok=True, ready=n)

    def _pub(self):
        if self.bus:
            self.bus.publish("calendar")
