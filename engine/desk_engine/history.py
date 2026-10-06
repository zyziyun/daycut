"""History: every past batch / project the creator made, found without a manual import.

Sources (deduplicated by real path):
  * the desk registry (``<DESK_DATA_DIR>/batches.json``);
  * the engine's batch registry (``$VSTUDIO_HOME/batches.json``, written by ``vstudio.batch plan``);
  * the engine's projects + series (``$VSTUDIO_HOME/projects.json`` / ``series/``, i.e. ``vstudio.project list``);
  * watched folders (default ``~/Desktop/video-studio-demos``; ``DESK_HISTORY_WATCH`` = ``os.pathsep`` list
    overrides the default, empty = none): the folder and up to 2 levels below it are scanned for ``batch.db``
    (a batch) or ``project.yaml`` (a project, whose batch store is ``<project>/state``).

Every batch store is read with sqlite in read-only mode - nothing in a found folder is ever written. "Remove from
list" only hides the folder (``<DESK_DATA_DIR>/history.json``) and drops it from the desk registry; files stay.
Registry hygiene: entries pointing to missing folders or into temp dirs (``/tmp``, ``/var/folders/*/T``: test
junk) are pruned from the desk registry and from the engine's registries (unless that registry is itself in a
temp dir, as in tests).
"""
import glob
import json
import os
import re
import sqlite3
import threading
import time

from .common import batch_id, is_temp_path, need, prune_json_registry, read_json, write_json

DEFAULT_WATCH = ["~/Desktop/video-studio-demos"]
SKIP_DIRS = {"node_modules", ".git", "jobs", "cache", "delivery", "package", "review", "__pycache__", "state"}
MAX_ENTRIES = 500


def vstudio_home():
    return os.path.abspath(os.path.expanduser(os.environ.get("VSTUDIO_HOME") or "~/.config/vstudio"))


# ------------------------------------------------------------------ reading a found folder
def _ro(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)


def _first_sheet(bdir, job_ids):
    for jid in job_ids:
        p = os.path.join(bdir, "jobs", jid, "preview", "sheet.jpg")
        if os.path.exists(p):
            return p
    hits = sorted(glob.glob(os.path.join(bdir, "jobs", "*", "preview", "sheet.jpg")))
    return hits[0] if hits else None


def summarize_batch(bdir):
    """Read-only summary of a batch folder: name, recipe, client, dates, counts, status, thumbnail."""
    db = os.path.join(bdir, "batch.db")
    out = dict(name=os.path.basename(bdir.rstrip(os.sep)), recipe=None, client=None, created=None, updated=None,
               counts=dict(total=0, green=0, red=0, approved=0, done=0, failed=0), status="unknown", thumb=None,
               deliveries=0)
    try:
        st = os.stat(db)
        out["updated"] = st.st_mtime
        con = _ro(db)
        try:
            meta = {k: v for k, v in con.execute("SELECT k, v FROM meta")}
            spec = json.loads(meta.get("spec") or "{}") or {}
            out["name"] = spec.get("name") or out["name"]
            out["recipe"] = spec.get("recipe")
            cl = spec.get("client") or ((spec.get("_client") or {}).get("slug"))
            if isinstance(cl, str) and cl:
                out["client"] = ((spec.get("_client") or {}).get("name")) or os.path.basename(cl.rstrip(os.sep))
            rows = con.execute("SELECT id, state, qc, review, created, updated FROM jobs ORDER BY ord, id").fetchall()
            c = out["counts"]
            c["total"] = len(rows)
            for _id, state, qc, review, created, updated in rows:
                c["green"] += qc == "green"
                c["red"] += qc == "red"
                c["approved"] += state in ("approved", "packaged") or review in ("approve", "approved")
                c["done"] += state in ("done", "approved", "packaged")
                c["failed"] += state == "failed"
            times = [r[4] for r in rows if r[4]] + [r[5] for r in rows if r[5]]
            if times:
                out["created"] = min(times)
                out["updated"] = max(max(times), out["updated"] or 0)
            try:
                dl = con.execute("SELECT client FROM deliveries ORDER BY n").fetchall()
                out["deliveries"] = len(dl)
                if dl and not out["client"] and dl[-1][0]:
                    out["client"] = dl[-1][0]
            except sqlite3.Error:
                pass
            pk = meta.get("package")
            packaged = bool(pk and pk != "null")
            if out["deliveries"]:
                out["status"] = "delivered"
            elif packaged:
                out["status"] = "packaged"
            elif c["total"] and c["done"] == c["total"]:
                out["status"] = "done"
            elif c["done"] or c["failed"]:
                out["status"] = "in-progress"
            else:
                out["status"] = "planned"
            out["thumb"] = _first_sheet(bdir, [r[0] for r in rows])
        finally:
            con.close()
    except (OSError, sqlite3.Error, ValueError) as e:
        out.update(status="unreadable", error=str(e)[:200])
    return out


def summarize_project(pdir):
    out = dict(name=os.path.basename(pdir.rstrip(os.sep)), recipe=None, client=None, series=None)
    try:
        import yaml  # the bundled runtime and the engine have PyYAML; plain-text fallback otherwise
        with open(os.path.join(pdir, "project.yaml"), encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001
        data = {}
        try:
            with open(os.path.join(pdir, "project.yaml"), encoding="utf-8") as f:
                for ln in f:
                    m = re.match(r"^(name|recipe|client|series):\s*(.+?)\s*$", ln)
                    if m:
                        data[m.group(1)] = m.group(2).strip("'\"")
        except OSError:
            pass
    if isinstance(data, dict):
        for k in ("name", "recipe", "client", "series"):
            if isinstance(data.get(k), str) and data[k]:
                out[k] = data[k]
    sdir = os.path.join(pdir, "state")
    if os.path.exists(os.path.join(sdir, "batch.db")):
        b = summarize_batch(sdir)
        for k in ("counts", "status", "thumb", "created", "updated", "deliveries", "error"):
            if k in b:
                out[k] = b[k]
        out["recipe"] = out["recipe"] or b.get("recipe")
        out["client"] = out["client"] or b.get("client")
    else:
        out.update(counts=dict(total=0, green=0, red=0, approved=0, done=0, failed=0), status="planned", thumb=None,
                   deliveries=0)
        try:
            out["updated"] = os.stat(os.path.join(pdir, "project.yaml")).st_mtime
        except OSError:
            pass
    return out


# ------------------------------------------------------------------ discovery
def scan_folder(root, depth=2):
    """The folder and up to ``depth`` levels below it: -> [(kind, dir)] for batch.db / project.yaml."""
    root = os.path.abspath(os.path.expanduser(root))
    found = []

    def visit(d, level):
        if os.path.exists(os.path.join(d, "project.yaml")):
            found.append(("project", d))
            return
        if os.path.exists(os.path.join(d, "batch.db")):
            found.append(("batch", d))
            return
        if level >= depth:
            return
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return
        for n in names:
            if n.startswith(".") or n in SKIP_DIRS:
                continue
            p = os.path.join(d, n)
            if os.path.isdir(p) and not os.path.islink(p):
                visit(p, level + 1)
            if len(found) >= MAX_ENTRIES:
                return

    if os.path.isdir(root):
        visit(root, 0)
    return found


class History:
    def __init__(self, data_dir, registry, engine=None):
        self.path = os.path.join(data_dir, "history.json")
        self.reg = registry
        self.engine = engine
        self._lock = threading.Lock()
        self._thumbs = set()

    # ---------------------------------------------------------- config (watched folders, hidden)
    def _cfg(self):
        c = read_json(self.path, {}) or {}
        return c if isinstance(c, dict) else {}

    def default_watch(self):
        env = os.environ.get("DESK_HISTORY_WATCH")
        if env is not None:
            return [p for p in env.split(os.pathsep) if p.strip()]
        return list(DEFAULT_WATCH)

    def watch(self):
        w = self._cfg().get("watch")
        return list(w) if isinstance(w, list) else self.default_watch()

    def config(self):
        c = self._cfg()
        return dict(watch=self.watch(), hidden=len(c.get("hidden") or []), default_watch=self.default_watch())

    def set_watch(self, folders):
        need(isinstance(folders, list) and len(folders) <= 20, "watch: up to 20 folders")
        out = []
        for f in folders:
            need(isinstance(f, str) and 0 < len(f) < 4096 and "\0" not in f, "watch: folder paths")
            f = f.strip()
            need(os.path.isabs(os.path.expanduser(f)), f"watch: {f} must be an absolute path")
            if f not in out:
                out.append(f)
        with self._lock:
            c = self._cfg()
            c["watch"] = out
            write_json(self.path, c)
        return self.config()

    def hide(self, path):
        rp = os.path.realpath(path)
        with self._lock:
            c = self._cfg()
            hidden = [h for h in c.get("hidden") or [] if h != rp] + [rp]
            c["hidden"] = hidden[-2000:]
            write_json(self.path, c)
        for d in (path, os.path.join(path, "state")):
            self.reg.remove(batch_id(d))
        return dict(ok=True, hidden=rp, deleted=False)

    def unhide_all(self):
        with self._lock:
            c = self._cfg()
            c["hidden"] = []
            write_json(self.path, c)
        return self.config()

    # ---------------------------------------------------------- hygiene
    def prune(self):
        """Missing / temp-dir entries out of the desk registry and the engine registries. -> counts."""
        removed = dict(desk=self.reg.prune(), engine_batches=0, engine_projects=0)
        home = vstudio_home()
        try:
            from vstudio.batch import clients as CL
            if hasattr(CL, "prune_batches"):
                removed["engine_batches"] = len(CL.prune_batches())
            else:
                removed["engine_batches"] = len(prune_json_registry(os.path.join(home, "batches.json")))
        except ImportError:
            removed["engine_batches"] = len(prune_json_registry(os.path.join(home, "batches.json")))
        try:
            from vstudio.project import home as H
            if hasattr(H, "prune"):
                removed["engine_projects"] = len(H.prune())
            else:
                removed["engine_projects"] = len(prune_json_registry(os.path.join(home, "projects.json"),
                                                                     "project.yaml"))
        except ImportError:
            removed["engine_projects"] = len(prune_json_registry(os.path.join(home, "projects.json"),
                                                                 "project.yaml"))
        return removed

    # ---------------------------------------------------------- listing
    def _candidates(self):
        """-> [(kind, dir, source, extra)] from every source, in priority order."""
        out = []
        for b in self.reg.all():
            out.append(("batch", b["dir"], "desk", dict(name=b.get("name"))))
        home = vstudio_home()
        for r in read_json(os.path.join(home, "batches.json"), []) or []:
            if isinstance(r, dict) and r.get("dir"):
                out.append(("batch", r["dir"], "engine", dict(name=r.get("name"))))
        series = {}
        try:
            from vstudio.project import home as H
            for s in H.list_series():
                for d in s.get("projects") or []:
                    series[os.path.realpath(d)] = s.get("name") or s.get("id")
        except Exception:  # noqa: BLE001  (no engine / older engine / broken series.yaml)
            pass
        for r in read_json(os.path.join(home, "projects.json"), []) or []:
            if isinstance(r, dict) and r.get("dir"):
                out.append(("project", r["dir"], "engine", dict(name=r.get("name"), recipe=r.get("recipe"),
                                                               client=r.get("client"), series=r.get("series"))))
        for w in self.watch():
            for kind, d in scan_folder(w):
                out.append((kind, d, "watch", {}))
        return out, series

    def list(self, q=None, status=None, kind=None):
        self.prune()
        hidden = set(self._cfg().get("hidden") or [])
        cands, series = self._candidates()
        seen, rows = set(), []
        reg_ids = {b["id"] for b in self.reg.all()}
        for kind_, d, src, extra in cands:
            d = os.path.abspath(os.path.expanduser(d))
            rp = os.path.realpath(d)
            if rp in seen:
                for r in rows:
                    if r["real"] == rp and src not in r["sources"]:
                        r["sources"].append(src)
                continue
            seen.add(rp)
            if rp in hidden or is_temp_path(d) and not is_temp_path(self.path):
                continue
            marker = "project.yaml" if kind_ == "project" else "batch.db"
            if not os.path.exists(os.path.join(d, marker)):
                if kind_ == "batch" and os.path.exists(os.path.join(d, "project.yaml")):
                    kind_ = "project"
                else:
                    continue
            info = summarize_project(d) if kind_ == "project" else summarize_batch(d)
            for k, v in extra.items():
                if v and not info.get(k):
                    info[k] = v
            store_dir = os.path.join(d, "state") if kind_ == "project" else d
            bid = batch_id(store_dir)
            row = dict(info, kind=kind_, dir=d, real=rp, sources=[src], id=bid,
                       opened=bid in reg_ids, openable=os.path.exists(os.path.join(store_dir, "batch.db")),
                       series=info.get("series") or series.get(rp))
            rows.append(row)
        if q:
            ql = q.lower()
            rows = [r for r in rows if any(ql in str(r.get(k) or "").lower()
                                           for k in ("name", "recipe", "client", "dir", "series"))]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if kind:
            rows = [r for r in rows if r["kind"] == kind]
        rows.sort(key=lambda r: -(r.get("updated") or r.get("created") or 0))
        for r in rows:
            r.pop("real", None)
        self._thumbs = {r["thumb"] for r in rows if r.get("thumb")}
        return dict(items=rows[:MAX_ENTRIES], watch=self.watch(), at=time.time())

    def open(self, path):
        """Put a found batch (or a project's state batch) in the desk registry -> {id, dir} for the board."""
        d = os.path.abspath(path)
        store_dir = os.path.join(d, "state") if os.path.exists(os.path.join(d, "project.yaml")) else d
        need(os.path.exists(os.path.join(store_dir, "batch.db")), f"no batch.db in {store_dir} (not run yet)")
        if os.path.realpath(d) in set(self._cfg().get("hidden") or []):
            with self._lock:
                c = self._cfg()
                c["hidden"] = [h for h in c.get("hidden") or [] if h != os.path.realpath(d)]
                write_json(self.path, c)
        name = (summarize_project(d) if store_dir != d else summarize_batch(d)).get("name")
        ent = self.reg.add(store_dir, name)
        return dict(id=ent["id"], dir=store_dir, name=name)

    def roots(self):
        """``jobs/`` folders of the last listed entries with a thumbnail (the media protocol allow-list)."""
        return sorted({os.path.dirname(os.path.dirname(os.path.dirname(t))) for t in self._thumbs})
