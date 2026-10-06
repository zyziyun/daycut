"""Shared helpers for the desk engine: event bus (SSE), batch registry, hashing, small validators."""
import hashlib
import json
import os
import queue
import re
import tempfile
import threading
import time


def sha1_json(obj, n=None):
    """Same algorithm as vstudio.batch.util.sha1_json (used for the package confirmation code)."""
    h = hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return h[:n] if n else h


def batch_id(path):
    return hashlib.sha1(os.path.abspath(path).encode()).hexdigest()[:12]


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)


# ------------------------------------------------------------------ temp / junk (registry hygiene)
def _temp_roots():
    roots = {tempfile.gettempdir(), "/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp"}
    return {os.path.realpath(r) for r in roots} | {os.path.abspath(r) for r in roots}


_VARF = re.compile(r"^(/private)?/var/folders/[^/]+/[^/]+/T(/|$)")


def is_temp_path(path):
    p = os.path.abspath(path or "")
    rp = os.path.realpath(p)
    if _VARF.match(p) or _VARF.match(rp):
        return True
    return any(x == r or x.startswith(r.rstrip(os.sep) + os.sep) for r in _temp_roots() for x in (p, rp))


def keep_entry(entry_dir, registry_path, marker=None):
    d = entry_dir or ""
    if not d or not os.path.isdir(d) or (marker and not os.path.exists(os.path.join(d, marker))):
        return False
    return is_temp_path(registry_path) or not is_temp_path(d)


def prune_json_registry(path, marker=None):
    """Drop missing / temp-dir entries from a ``[{dir, ...}]`` JSON registry. -> removed entries."""
    rows = read_json(path, None)
    if not isinstance(rows, list):
        return []
    keep = [r for r in rows if isinstance(r, dict) and keep_entry(r.get("dir"), path, marker)]
    gone = [r for r in rows if r not in keep]
    if gone:
        try:
            write_json(path, keep)
        except OSError:
            pass
    return gone



# Display names may be Chinese (B5): any letters / digits / CJK plus space . _ - ( ); folders use safe_name().
NAME_RE = re.compile(r"^[^\W_][\w .()（）·-]{0,63}$")


def safe_name(name):
    """A display name -> a folder / file-safe ASCII slug (a short hash keeps Chinese names unique)."""
    import hashlib
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    if s == name:
        return s
    return f"{s[:40]}-{hashlib.sha1(name.encode()).hexdigest()[:8]}".lstrip("-")
JOB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class BadRequest(ValueError):
    pass


def need(cond, msg):
    if not cond:
        raise BadRequest(msg)


# ------------------------------------------------------------------ live status (.vstudio/status.json)
# Mirrors vstudio.batch.livestatus (written by the batch runner, project runs, `vstudio.project touch` and the skill's
# long stages, inside or outside the desk). A running record whose heartbeat is old and whose process is gone is
# "interrupted" - never running forever.
LIVE_STALE_S = 600
LIVE_HARD_S = 7200


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False


def live_status(d, now=None):
    rec = read_json(os.path.join(d, ".vstudio", "status.json"), None)
    if not isinstance(rec, dict) or rec.get("status") not in ("running", "waiting", "done", "failed"):
        return None
    import socket
    now = now or time.time()
    try:
        age = max(0.0, now - float(rec.get("heartbeat") or 0))
    except (TypeError, ValueError):
        age = float("inf")
    state = rec["status"]
    if state == "running":
        gone = rec.get("host") != socket.gethostname() or not _pid_alive(rec.get("pid"))
        if age > LIVE_HARD_S or (age > LIVE_STALE_S and gone):
            state = "interrupted"
    out = {k: rec.get(k) for k in ("status", "stage", "progress", "message", "eta", "started", "heartbeat",
                                   "finished", "updated_by")}
    out.update(state=state, age=round(age, 1) if age != float("inf") else None, needs_you=bool(rec.get("needs_you"))
               and state == "waiting")
    return out


class EventBus:
    """Fan-out of engine events to every SSE subscriber (bounded queues; slow readers drop events)."""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self._lock:
            self._subs.add(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs.discard(q)

    def publish(self, kind, **data):
        ev = dict(type=kind, ts=time.time(), **data)
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass


class Registry:
    """The desk's list of known batch folders: <data>/batches.json [{id, dir, name, added}]."""

    def __init__(self, data_dir):
        self.path = os.path.join(data_dir, "batches.json")
        self._lock = threading.Lock()

    def all(self):
        return [b for b in (read_json(self.path, []) or []) if isinstance(b, dict) and b.get("dir")]

    def get(self, bid):
        return next((b for b in self.all() if b["id"] == bid), None)

    def add(self, path, name):
        path = os.path.abspath(path)
        with self._lock:
            items = [b for b in self.all() if b["id"] != batch_id(path)]
            ent = dict(id=batch_id(path), dir=path, name=name, added=time.time())
            items.append(ent)
            write_json(self.path, items)
        return ent

    def prune(self):
        """Drop entries whose folder is gone or that point into temp dirs (test junk). -> number removed."""
        with self._lock:
            return len(prune_json_registry(self.path, "batch.db"))

    def remove(self, bid):
        with self._lock:
            write_json(self.path, [b for b in self.all() if b["id"] != bid])
