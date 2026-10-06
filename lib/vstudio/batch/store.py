"""Durable batch state: one SQLite database (WAL) per batch folder.

Tables
  meta       key -> JSON (spec, batch state, pause reason, package code, ...)
  jobs       one row per job (variant): params JSON, state, QC light + reasons, review decision
  stages     (job, stage) -> state pending|running|done|failed|skipped, input-hash key, outputs JSON,
             attempts, timings, cached flag; the scheduler resumes from these rows after a crash
  artifacts  (stage, key) -> shared outputs (e.g. one ASR per source, reused by every job of that source)
  events     append-only log
  bench      measured seconds / bytes per unit per stage (feeds ``estimate``)
  edits      in-review job edits (``job edit``): op, args, the value before, which stages it made stale
  timing     review timing events (``timing``): job, start / stop, active seconds
  deliveries client delivery packages (``deliver``): folder, zip, manifest hash, source cleanup due date

Only the scheduler's dispatcher thread writes while a run is going; readers (``status``) use their own
connection (WAL lets them read while the run writes).
"""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager

from .util import now

DB_NAME = "batch.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, ord INTEGER, recipe TEXT, item TEXT, variant TEXT, params TEXT,
  state TEXT DEFAULT 'planned', qc TEXT, qc_reasons TEXT, sample INTEGER DEFAULT 0,
  review TEXT, review_reason TEXT, pilot INTEGER DEFAULT 0, cost REAL DEFAULT 0,
  created REAL, updated REAL);
CREATE TABLE IF NOT EXISTS stages (
  job TEXT, stage TEXT, state TEXT, key TEXT, attempts INTEGER DEFAULT 0, not_before REAL DEFAULT 0,
  started REAL, finished REAL, seconds REAL, out TEXT, error TEXT, cached INTEGER DEFAULT 0,
  PRIMARY KEY (job, stage));
CREATE TABLE IF NOT EXISTS artifacts (
  stage TEXT, key TEXT, state TEXT, dir TEXT, out TEXT, owner TEXT, updated REAL,
  PRIMARY KEY (stage, key));
CREATE TABLE IF NOT EXISTS events (ts REAL, job TEXT, stage TEXT, kind TEXT, msg TEXT);
CREATE TABLE IF NOT EXISTS bench (
  stage TEXT PRIMARY KEY, resource TEXT, sec_per_unit REAL, bytes_per_unit REAL, n INTEGER, updated REAL);
CREATE TABLE IF NOT EXISTS edits (
  n INTEGER PRIMARY KEY AUTOINCREMENT, job TEXT, op TEXT, args TEXT, before TEXT, result TEXT, rerun TEXT,
  ts REAL, undone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS timing (ts REAL, job TEXT, event TEXT, what TEXT, seconds REAL, actor TEXT);
CREATE TABLE IF NOT EXISTS deliveries (
  n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, client TEXT, dir TEXT, zip TEXT, code TEXT, items INTEGER,
  jobs INTEGER, duration REAL, cleanup_due REAL, cleaned REAL, sources TEXT);
"""

JSON_COLS = {"params", "qc_reasons", "out", "args", "before", "result", "rerun", "sources"}


def _row(cur, r):
    d = {c[0]: r[i] for i, c in enumerate(cur.description)}
    for k in JSON_COLS & d.keys():
        if d[k] is not None:
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                pass
    return d


class Store:
    def __init__(self, batch_dir, create=False):
        self.dir = os.path.abspath(batch_dir)
        self.path = os.path.join(self.dir, DB_NAME)
        if not create and not os.path.exists(self.path):
            raise FileNotFoundError(f"no batch at {self.dir} ({DB_NAME} missing) - run `plan` first")
        os.makedirs(self.dir, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = _row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(SCHEMA)
        self._lock = threading.RLock()

    def close(self):
        self.conn.close()

    def journal_mode(self):
        return self.conn.execute("PRAGMA journal_mode").fetchone()["journal_mode"]

    @contextmanager
    def tx(self):
        with self._lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def q(self, sql, args=()):
        with self._lock:
            return self.conn.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        with self._lock:
            self.conn.execute(sql, args)

    # ------------------------------------------------------------- meta
    def meta(self, k, default=None):
        r = self.q("SELECT v FROM meta WHERE k=?", (k,))
        return json.loads(r[0]["v"]) if r else default

    def set_meta(self, k, v):
        self.x("INSERT INTO meta(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
               (k, json.dumps(v, ensure_ascii=False, default=str)))

    @property
    def spec(self):
        return self.meta("spec", {})

    def state(self):
        return self.meta("state", "planned")

    # ------------------------------------------------------------- jobs
    def upsert_job(self, job):
        t = now()
        self.x("""INSERT INTO jobs(id, ord, recipe, item, variant, params, state, created, updated)
                  VALUES(?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET ord=excluded.ord, recipe=excluded.recipe, item=excluded.item,
                  variant=excluded.variant, params=excluded.params, updated=excluded.updated""",
               (job["id"], job.get("ord", 0), job["recipe"], job.get("item"), job.get("variant", ""),
                json.dumps(job.get("params") or {}, ensure_ascii=False, sort_keys=True), job.get("state", "planned"),
                t, t))

    def job(self, jid):
        r = self.q("SELECT * FROM jobs WHERE id=?", (jid,))
        return r[0] if r else None

    def jobs(self, states=None):
        if states:
            qs = ",".join("?" * len(states))
            return self.q(f"SELECT * FROM jobs WHERE state IN ({qs}) ORDER BY ord, id", tuple(states))
        return self.q("SELECT * FROM jobs ORDER BY ord, id")

    def set_job(self, jid, **f):
        if not f:
            return
        f["updated"] = now()
        cols = ", ".join(f"{k}=?" for k in f)
        vals = [json.dumps(v, ensure_ascii=False, sort_keys=True) if k in JSON_COLS and v is not None else v
                for k, v in f.items()]
        self.x(f"UPDATE jobs SET {cols} WHERE id=?", (*vals, jid))

    # ------------------------------------------------------------- stages
    def stage(self, jid, st):
        r = self.q("SELECT * FROM stages WHERE job=? AND stage=?", (jid, st))
        return r[0] if r else None

    def stage_rows(self, jid):
        return {r["stage"]: r for r in self.q("SELECT * FROM stages WHERE job=?", (jid,))}

    def all_stage_rows(self):
        out = {}
        for r in self.q("SELECT * FROM stages"):
            out.setdefault(r["job"], {})[r["stage"]] = r
        return out

    def set_stage(self, jid, st, **f):
        cur = self.stage(jid, st)
        vals = {k: (json.dumps(v, ensure_ascii=False, default=str) if k in JSON_COLS and v is not None else v)
                for k, v in f.items()}
        if cur is None:
            vals.setdefault("state", "pending")
            cols = ["job", "stage", *vals]
            self.x(f"INSERT INTO stages({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                   (jid, st, *vals.values()))
        elif vals:
            self.x(f"UPDATE stages SET {', '.join(f'{k}=?' for k in vals)} WHERE job=? AND stage=?",
                   (*vals.values(), jid, st))

    def reset_job_stages(self, jid):
        self.x("DELETE FROM stages WHERE job=?", (jid,))

    # ------------------------------------------------------------- shared artifacts
    def art(self, st, key):
        r = self.q("SELECT * FROM artifacts WHERE stage=? AND key=?", (st, key))
        return r[0] if r else None

    def set_art(self, st, key, **f):
        f["updated"] = now()
        if "out" in f and f["out"] is not None:
            f["out"] = json.dumps(f["out"], ensure_ascii=False, default=str)
        if self.art(st, key) is None:
            cols = ["stage", "key", *f]
            self.x(f"INSERT INTO artifacts({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", (st, key, *f.values()))
        else:
            self.x(f"UPDATE artifacts SET {', '.join(f'{k}=?' for k in f)} WHERE stage=? AND key=?",
                   (*f.values(), st, key))

    def drop_art(self, st, key):
        self.x("DELETE FROM artifacts WHERE stage=? AND key=?", (st, key))

    def arts(self):
        return self.q("SELECT * FROM artifacts")

    # ------------------------------------------------------------- events / bench
    def log(self, kind, msg, job=None, stage=None):
        self.x("INSERT INTO events(ts, job, stage, kind, msg) VALUES(?,?,?,?,?)", (now(), job, stage, kind, str(msg)))

    def events(self, n=20, job=None):
        if job:
            return self.q("SELECT * FROM events WHERE job=? ORDER BY ts DESC LIMIT ?", (job, n))
        return self.q("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (n,))

    # ------------------------------------------------------------- v0.2: edits / timing / deliveries
    def add_edit(self, job, op, args, before, result, rerun):
        d = lambda v: json.dumps(v, ensure_ascii=False, default=str)  # noqa: E731
        with self._lock:
            cur = self.conn.execute("INSERT INTO edits(job, op, args, before, result, rerun, ts) VALUES(?,?,?,?,?,?,?)",
                                    (job, op, d(args), d(before), d(result), d(rerun), now()))
            return cur.lastrowid

    def edits(self, job=None, include_undone=False):
        q, a = "SELECT * FROM edits", []
        cond = []
        if job:
            cond.append("job=?")
            a.append(job)
        if not include_undone:
            cond.append("undone=0")
        if cond:
            q += " WHERE " + " AND ".join(cond)
        return self.q(q + " ORDER BY n", tuple(a))

    def set_edit(self, n, **f):
        cols = ", ".join(f"{k}=?" for k in f)
        vals = [json.dumps(v, ensure_ascii=False, default=str) if k in JSON_COLS and v is not None else v
                for k, v in f.items()]
        self.x(f"UPDATE edits SET {cols} WHERE n=?", (*vals, n))

    def add_timing(self, job, event, what="review", seconds=None, actor=None, ts=None):
        self.x("INSERT INTO timing(ts, job, event, what, seconds, actor) VALUES(?,?,?,?,?,?)",
               (ts if ts is not None else now(), job, event, what, seconds, actor))

    def timing(self, job=None, what=None):
        q, cond, a = "SELECT * FROM timing", [], []
        if job:
            cond.append("job=?")
            a.append(job)
        if what:
            cond.append("what=?")
            a.append(what)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        return self.q(q + " ORDER BY ts", tuple(a))

    def add_delivery(self, **f):
        if "sources" in f:
            f["sources"] = json.dumps(f["sources"], ensure_ascii=False)
        f.setdefault("ts", now())
        cols = list(f)
        with self._lock:
            cur = self.conn.execute(f"INSERT INTO deliveries({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                                    tuple(f.values()))
            return cur.lastrowid

    def deliveries(self):
        return self.q("SELECT * FROM deliveries ORDER BY n")

    def set_delivery(self, n, **f):
        cols = ", ".join(f"{k}=?" for k in f)
        vals = [json.dumps(v, ensure_ascii=False) if k in JSON_COLS and v is not None else v for k, v in f.items()]
        self.x(f"UPDATE deliveries SET {cols} WHERE n=?", (*vals, n))

    def bench(self):
        return {r["stage"]: r for r in self.q("SELECT * FROM bench")}

    def set_bench(self, st, resource, sec_per_unit, bytes_per_unit, n):
        self.x("""INSERT INTO bench(stage, resource, sec_per_unit, bytes_per_unit, n, updated) VALUES(?,?,?,?,?,?)
                  ON CONFLICT(stage) DO UPDATE SET resource=excluded.resource, sec_per_unit=excluded.sec_per_unit,
                  bytes_per_unit=excluded.bytes_per_unit, n=excluded.n, updated=excluded.updated""",
               (st, resource, sec_per_unit, bytes_per_unit, n, now()))
