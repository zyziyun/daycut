"""Desk-local JSON store for the v0.2 features (clients, plans, edits, timing, deliveries, CRM, weekly entries).

Everything lives under ``<DESK_DATA_DIR>/v02``. Each file is small JSON written atomically; one lock per store.
YAML (client.yaml, segments.yaml) uses PyYAML when present, else JSON text (valid YAML 1.2).
"""
import json
import os
import re
import threading
import time

from .common import read_json, write_json

CLIENT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def dump_yaml(obj):
    try:
        import yaml
        return yaml.safe_dump(obj, allow_unicode=True, sort_keys=False, default_flow_style=False)
    except ImportError:
        return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def load_yaml(text):
    try:
        import yaml
        return yaml.safe_load(text)
    except ImportError:
        return json.loads(text)


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


class V02Store:
    def __init__(self, data_dir):
        self.root = os.path.join(data_dir, "v02")
        os.makedirs(self.root, exist_ok=True)
        self._lock = threading.RLock()

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    # ---------------------------------------------------------------- generic JSON docs
    def get(self, name, default=None):
        with self._lock:
            v = read_json(self.path(name + ".json"), None)
            return default if v is None else v

    def put(self, name, value):
        with self._lock:
            write_json(self.path(name + ".json"), value)
        return value

    def update(self, name, fn, default=None):
        """Read-modify-write under the lock: fn(doc) mutates or returns a new doc."""
        with self._lock:
            doc = self.get(name, default if default is not None else {})
            r = fn(doc)
            doc = doc if r is None else r
            self.put(name, doc)
            return doc

    # ---------------------------------------------------------------- batch -> client / source
    def batch_meta(self, bid):
        return (self.get("batches", {}) or {}).get(bid) or {}

    def set_batch_meta(self, bid, **kw):
        def f(d):
            d.setdefault(bid, {}).update({k: v for k, v in kw.items() if v is not None})
        return self.update("batches", f)[bid]

    # ---------------------------------------------------------------- timing
    def add_timing(self, rec):
        def f(d):
            d.setdefault("events", []).append(rec)
            del d["events"][:-20000]
        self.update("timing", f)

    def timing_events(self):
        return (self.get("timing", {}) or {}).get("events") or []

    def review_seconds(self, bid=None):
        """{(batch, job): active seconds} summed over stop events of what=review."""
        out = {}
        for e in self.timing_events():
            if e.get("event") != "stop" or e.get("what") != "review" or (bid and e.get("batch") != bid):
                continue
            k = (e["batch"], e["job"])
            out[k] = out.get(k, 0.0) + float(e.get("active_s") or 0)
        return out


def now():
    return time.time()
