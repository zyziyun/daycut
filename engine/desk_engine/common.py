"""Shared helpers for the desk engine: event bus (SSE), batch registry, hashing, small validators."""
import hashlib
import json
import os
import queue
import re
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


NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
JOB_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class BadRequest(ValueError):
    pass


def need(cond, msg):
    if not cond:
        raise BadRequest(msg)


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

    def remove(self, bid):
        with self._lock:
            write_json(self.path, [b for b in self.all() if b["id"] != bid])
