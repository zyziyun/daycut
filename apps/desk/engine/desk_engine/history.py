"""History: every past batch / project the creator made, found without a manual import.

Sources (deduplicated by real path):
  * the desk registry (``<DESK_DATA_DIR>/batches.json``);
  * the engine's batch registry (``$VSTUDIO_HOME/batches.json``, written by ``vstudio.batch plan``);
  * the engine's projects + series (``$VSTUDIO_HOME/projects.json`` / ``series/``, i.e. ``vstudio.project list``);
  * watched folders (default ``~/Desktop/video-studio-demos``; ``DESK_HISTORY_WATCH`` = ``os.pathsep`` list  (check-skill: allow)
    overrides the default, empty = none): the folder and up to 2 levels below it are scanned for ``batch.db``
    (a batch) or ``project.yaml`` (a project, whose batch store is ``<project>/state``).

Every batch store is read with sqlite in read-only mode - nothing in a found folder is ever written. "Archive" only
hides the folder (``<DESK_DATA_DIR>/history.json`` ``hidden`` + ``archived_at``) and parks its desk registry row
(``archived_reg``) until "Restore" puts it back; files stay. A project with a run going is never archived.
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

from . import works as WK
from .pilot import failure as pilot_failure, running as pilot_running
from .common import (batch_id, is_temp_path, keep_entry, live_status, need, prune_json_registry, read_json,
                     write_json)

DEFAULT_WATCH = ["~/Desktop/video-studio-demos"]  # check-skill: allow (documented default; DESK_HISTORY_WATCH overrides)
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
        if level > 0 and WK.looks_like_work(d):          # a plain folder made with the skill
            found.append(("work", d))
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


def log_tail(d, lines=40, max_bytes=16384):
    """The last lines of the newest *.log in the folder or its work/ (a terminal / agent run's progress)."""
    cands = []
    for sub in ("", "work", "state"):
        for p in glob.glob(os.path.join(d, sub, "*.log")):
            try:
                cands.append((os.path.getmtime(p), p))
            except OSError:
                pass
    if not cands:
        return None
    _, p = max(cands)
    try:
        with open(p, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - max_bytes))
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return None
    return dict(path=p, text="\n".join(text.splitlines()[-lines:]))


def _prune_projects(path):
    """projects.json: keep recipe projects (project.yaml) and adopted work folders (.vstudio/work.json)."""
    rows = read_json(path, None)
    if not isinstance(rows, list):
        return []

    def ok(r):
        d = r.get("dir") or ""
        live = os.path.exists(os.path.join(d, ".vstudio", "work.json") if r.get("kind") == "work"
                              else os.path.join(d, "project.yaml"))
        return live and keep_entry(d, path)
    keep = [r for r in rows if isinstance(r, dict) and ok(r)]
    gone = [r for r in rows if r not in keep]
    if gone:
        try:
            write_json(path, keep)
        except OSError:
            pass
    return gone


class History:
    def __init__(self, data_dir, registry, engine=None):
        self.path = os.path.join(data_dir, "history.json")
        self.reg = registry
        self.engine = engine
        self._lock = threading.Lock()
        self._thumbs = set()
        self._thumbs_archived = set()
        self._media = set()

    # ---------------------------------------------------------- config (watched folders, hidden)
    def _cfg(self):
        c = read_json(self.path, {}) or {}
        return c if isinstance(c, dict) else {}

    def default_watch(self):
        env = os.environ.get("DESK_HISTORY_WATCH")
        if env is not None:
            return [p for p in env.split(os.pathsep) if p.strip()]
        # the built-in default is the maintainer's demo folder: only where it exists, so a new user's Settings does
        # not list a watched folder they never had
        return [p for p in DEFAULT_WATCH if os.path.isdir(os.path.expanduser(p))]

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

    # ---------------------------------------------------------- archive (stored as ``hidden`` for older desks)
    def _busy(self, path):
        """Why ``path`` cannot be archived now (a run is going) -> a short reason, else None. Never stops a run."""
        d = os.path.abspath(path)
        store = os.path.join(d, "state") if os.path.exists(os.path.join(d, "project.yaml")) else d
        for x in dict.fromkeys((d, store)):
            live = live_status(x)
            if live and live.get("state") == "running":
                return live.get("message") or live.get("stage") or "running"
        if pilot_running(d):
            return "pilot running"
        run = getattr(self.engine, "running", None)
        if callable(run):
            try:
                if run(batch_id(store)):
                    return "batch running"
            except Exception:  # noqa: BLE001  (an engine that does not know this batch)
                pass
        return None

    def _label(self, path, cfg):
        rp = os.path.realpath(path)
        names = cfg.get("names") if isinstance(cfg.get("names"), dict) else {}
        return names.get(rp) or os.path.basename(rp.rstrip(os.sep)) or rp

    def archived_dirs(self):
        """The archived projects' real paths (history.json ``hidden``): cheap, no folder is read."""
        return set(self._cfg().get("hidden") or [])

    def archive(self, paths):
        """Archive projects: out of All projects into the Archived tab; nothing on disk is touched. A project with a
        run going is refused (the whole request: nothing is archived), never stopped. -> {ok, archived[], at}"""
        need(isinstance(paths, list) and 0 < len(paths) <= 500, "dirs: 1-500 folders")
        cfg = self._cfg()
        busy = [self._label(p, cfg) for p in paths if self._busy(p)]
        need(not busy, f"still running: {', '.join(busy[:5])}{' …' if len(busy) > 5 else ''} - wait until it "
                       f"finishes (or stop it) before archiving. Nothing was archived.")
        now = time.time()
        rps = list(dict.fromkeys(os.path.realpath(p) for p in paths))
        drop = []
        with self._lock:
            c = self._cfg()
            hidden = [h for h in c.get("hidden") or [] if h not in rps] + rps
            c["hidden"] = hidden[-2000:]
            at = c.get("archived_at") if isinstance(c.get("archived_at"), dict) else {}
            regs = c.get("archived_reg") if isinstance(c.get("archived_reg"), dict) else {}
            reg_rows = self.reg.all()
            for p in paths:
                rp = os.path.realpath(p)
                at[rp] = now
                ids = {batch_id(p), batch_id(os.path.join(p, "state")), batch_id(rp), batch_id(os.path.join(rp, "state"))}
                mine = [dict(dir=b["dir"], name=b.get("name")) for b in reg_rows if b["id"] in ids]
                if mine:                            # the desk list row comes back on restore (the board opens again)
                    regs[rp] = mine
                drop += [b["id"] for b in reg_rows if b["id"] in ids]
            keep = set(c["hidden"])
            c["archived_at"] = {k: v for k, v in at.items() if k in keep}
            c["archived_reg"] = {k: v for k, v in regs.items() if k in keep}
            write_json(self.path, c)
        for bid in dict.fromkeys(drop):
            self.reg.remove(bid)
        self._last = self._last_archived = None   # find() must not answer from the list before this
        return dict(ok=True, archived=rps, at=now, deleted=False)

    def restore(self, paths=None):
        """Archived projects back into All projects, as they were (the desk list row too). ``None`` = all."""
        need(paths is None or (isinstance(paths, list) and len(paths) <= 2000), "dirs: up to 2000 folders")
        with self._lock:
            c = self._cfg()
            hidden = c.get("hidden") or []
            rps = set(hidden) if paths is None else {os.path.realpath(p) for p in paths}
            c["hidden"] = [h for h in hidden if h not in rps]
            at = c.get("archived_at") if isinstance(c.get("archived_at"), dict) else {}
            regs = c.get("archived_reg") if isinstance(c.get("archived_reg"), dict) else {}
            back = [r for rp in rps for r in regs.get(rp) or [] if isinstance(r, dict) and r.get("dir")]
            c["archived_at"] = {k: v for k, v in at.items() if k not in rps}
            c["archived_reg"] = {k: v for k, v in regs.items() if k not in rps}
            write_json(self.path, c)
        self._last = self._last_archived = None
        have = {b["id"] for b in self.reg.all()}
        for r in back:
            if batch_id(r["dir"]) not in have and os.path.exists(os.path.join(r["dir"], "batch.db")):
                self.reg.add(r["dir"], r.get("name"))
        return dict(ok=True, restored=sorted(rps))

    def hide(self, path):
        """The old 「remove from list」: archive one folder."""
        r = self.archive([path])
        return dict(ok=True, hidden=r["archived"][0], deleted=False)

    def unhide(self, path):
        """Undo one archive (the undo toast; the old /unhide-one route)."""
        r = self.restore([path])
        return dict(ok=True, dir=r["restored"][0])

    def rename(self, path, name):
        """Inline rename (any language): a display name kept by the desk; nothing in the folder changes."""
        need(isinstance(name, str) and 0 < len(name.strip()) <= 80 and "\0" not in name, "name: 1-80 chars")
        rp = os.path.realpath(path)
        with self._lock:
            c = self._cfg()
            names = c.get("names") if isinstance(c.get("names"), dict) else {}
            names[rp] = name.strip()
            c["names"] = names
            write_json(self.path, c)
        return dict(ok=True, dir=rp, name=name.strip())

    def set_client(self, path, client):
        """Agency mode: which client a project is for (a desk-side label; '' / None = her own). Nothing in the
        folder changes; an explicit '' also hides a client the folder itself names."""
        need(client is None or (isinstance(client, str) and len(client) <= 80 and "\0" not in client), "client: max 80 chars")
        rp = os.path.realpath(path)
        with self._lock:
            c = self._cfg()
            cl = c.get("clients") if isinstance(c.get("clients"), dict) else {}
            cl[rp] = (client or "").strip()
            c["clients"] = cl
            write_json(self.path, c)
        return dict(ok=True, dir=rp, client=(client or "").strip() or None)

    def unhide_all(self):
        self.restore(None)
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
                removed["engine_projects"] = len(_prune_projects(os.path.join(home, "projects.json")))
        except ImportError:
            removed["engine_projects"] = len(_prune_projects(os.path.join(home, "projects.json")))
        return removed

    # ---------------------------------------------------------- listing
    def _candidates(self):
        """-> [(kind, dir, source, extra)] from every source, in priority order."""
        out = []
        for b in self.reg.all():
            out.append(("batch", b["dir"], "desk", dict(name=b.get("name"))))
        regs = self._cfg().get("archived_reg")
        for rows in (regs.values() if isinstance(regs, dict) else []):   # archived: the desk row is parked here
            for b in rows if isinstance(rows, list) else []:
                if isinstance(b, dict) and b.get("dir"):
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
                out.append(("work" if r.get("kind") == "work" else "project", r["dir"], "engine", dict(name=r.get("name"), recipe=r.get("recipe"),
                                                               client=r.get("client"), series=r.get("series"))))
        for w in self.watch():
            for kind, d in scan_folder(w):
                out.append((kind, d, "watch", {}))
        return out, series

    def stamp(self):
        """A short token that changes whenever a registry the list reads changes (the desk's batches / history, the
        engine's batches.json / projects.json): another process (an agent's ``vstudio.project register`` / ``touch``)
        added or re-registered a project and All projects reloads without waiting for her to navigate away."""
        import hashlib
        home = vstudio_home()
        h = hashlib.sha1()
        for f in (self.reg.path, self.path, os.path.join(home, "batches.json"), os.path.join(home, "projects.json")):
            try:
                st = os.stat(f)
                h.update(f"{f}\0{st.st_mtime_ns}\0{st.st_size}\n".encode())
            except OSError:
                h.update(f"{f}\0-\n".encode())
        return dict(stamp=h.hexdigest()[:16])

    def list(self, q=None, status=None, kind=None, type_=None, client=None, archived=False):
        """All projects (``archived=False``: the archived ones left out, counted in ``archived``) or only the archived
        ones (``archived=True``: same rows + ``archived: true, archived_at``)."""
        self.prune()
        cfg = self._cfg()
        hidden = set(cfg.get("hidden") or [])
        at = cfg.get("archived_at") if isinstance(cfg.get("archived_at"), dict) else {}
        n_archived = 0
        names = cfg.get("names") if isinstance(cfg.get("names"), dict) else {}
        clients = cfg.get("clients") if isinstance(cfg.get("clients"), dict) else {}
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
            if is_temp_path(d) and not is_temp_path(self.path):
                continue
            if (rp in hidden) != archived:
                n_archived += rp in hidden
                continue
            if kind_ == "batch" and os.path.basename(rp) == "state" and \
                    os.path.exists(os.path.join(os.path.dirname(rp), "project.yaml")):
                continue                            # a project's own run store: the project row stands for it
            if kind_ == "work":
                if not os.path.isdir(d) or not (WK.looks_like_work(d) or os.path.exists(WK.record_path(d))):
                    continue
            else:
                marker = "project.yaml" if kind_ == "project" else "batch.db"
                if not os.path.exists(os.path.join(d, marker)):
                    if kind_ == "batch" and os.path.exists(os.path.join(d, "project.yaml")):
                        kind_ = "project"
                    else:
                        continue
            info = (summarize_project(d) if kind_ == "project" else WK.summarize(d) if kind_ == "work"
                    else summarize_batch(d))
            if kind_ == "batch":
                info["type"] = "batch"
            elif kind_ == "project":
                info["type"] = WK.recipe_type(info.get("recipe"))
            for k, v in extra.items():
                if v and not info.get(k):
                    info[k] = v
            store_dir = os.path.join(d, "state") if kind_ == "project" else d
            bid = batch_id(store_dir)
            live = live_status(d) or (live_status(store_dir) if store_dir != d else None)
            if live and live.get("updated_by") == "output-edit" and live.get("state") in ("interrupted", "failed"):
                # a clip edit that was cut off (or failed) is a note on that edit, never the project's state: the
                # project's own clips and pilot decide whether it is done / failed
                info["edit_note"] = dict(state=live["state"], stage=live.get("stage"), message=live.get("message"),
                                         at=live.get("heartbeat"))
                live = None
            fail = None if kind_ == "batch" else pilot_failure(d)
            if fail and live and live.get("state") in ("running", "waiting") and \
                    (live.get("heartbeat") or 0) > (fail.get("at") or 0) + 5:
                fail = None                         # a newer run is going: the old failure is history
            run = None if kind_ == "batch" or fail else pilot_running(d)
            if run:
                info["pilot"] = run
            if fail:
                info["status"] = "failed"
                info["failure"] = fail
                if live and live.get("state") in ("running", "interrupted"):
                    live = dict(live, state="failed")
            if os.path.isfile(os.path.join(d, ".vstudio", "sample.json")):
                info["sample"] = True               # made from the built-in sample (sample.py): labelled, deletable
            if names.get(rp):
                info["name"] = names[rp]
            if archived:
                info.update(archived=True, archived_at=at.get(rp))
            if rp in clients:
                info["client"] = clients[rp] or None
            row = dict(info, kind=kind_, dir=d, real=rp, sources=[src], id=bid, live=live,
                       opened=bid in reg_ids,
                       openable=kind_ != "work" and os.path.exists(os.path.join(store_dir, "batch.db")),
                       series=info.get("series") or series.get(rp))
            rows.append(row)
        for r in self._more_rows({r["id"] for r in rows}):
            rr = os.path.realpath(r.get("real") or r.get("dir") or "")
            if (rr in hidden) != archived:
                n_archived += rr in hidden
                continue
            if archived:
                r = dict(r, archived=True, archived_at=at.get(rr))
            rows.append(r)
        if q:
            ql = q.lower()
            rows = [r for r in rows if any(ql in str(r.get(k) or "").lower()
                                           for k in ("name", "recipe", "client", "dir", "series"))]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        if kind:
            rows = [r for r in rows if r["kind"] == kind]
        if type_:
            rows = [r for r in rows if r.get("type") == type_]
        if client:
            rows = [r for r in rows if (r.get("client") or "") == client]
        for r in rows:                              # a live heartbeat is the freshest date
            hb = (r.get("live") or {}).get("heartbeat")
            if hb and hb > (r.get("updated") or 0):
                r["updated"] = hb
        rows.sort(key=lambda r: -(r.get("updated") or r.get("created") or 0))
        running = sum(1 for r in rows if (r.get("live") or {}).get("state") in ("running", "waiting"))
        for r in rows:
            r.pop("real", None)
        thumbs = {r["thumb"] for r in rows if r.get("thumb")}
        snap = (time.time(), [dict(r) for r in rows[:MAX_ENTRIES]])
        if archived:
            self._thumbs_archived, self._last_archived = thumbs, snap
            return dict(items=rows[:MAX_ENTRIES], watch=self.watch(), at=time.time(), running=running, archived=True)
        self._thumbs = thumbs
        self._last = snap
        return dict(items=rows[:MAX_ENTRIES], watch=self.watch(), at=time.time(), running=running,
                    archived=n_archived)

    def _more_rows(self, have):
        """Rows that have no folder to find (none here; the in-memory test engine lists its batches)."""
        return []

    def open(self, path):
        """Put a found batch (or a project's state batch) in the desk registry -> {id, dir} for the board."""
        d = os.path.abspath(path)
        store_dir = os.path.join(d, "state") if os.path.exists(os.path.join(d, "project.yaml")) else d
        need(os.path.exists(os.path.join(store_dir, "batch.db")), f"no batch.db in {store_dir} (not run yet)")
        name = (summarize_project(d) if store_dir != d else summarize_batch(d)).get("name")
        ent = self.reg.add(store_dir, name)
        return dict(id=ent["id"], dir=store_dir, name=name)

    def find(self, item_id, max_age=3.0):
        """One entry; the listing is reused for a few seconds (the output editor looks entries up per request)."""
        for archived in (False, True):              # an archived project still opens
            cached = getattr(self, "_last_archived" if archived else "_last", None)
            rows = cached[1] if cached and time.time() - cached[0] < max_age else None
            if rows is None or not any(r["id"] == item_id for r in rows):
                rows = self.list(archived=archived)["items"]
            for r in rows:
                if r["id"] == item_id:
                    return dict(r)
        raise KeyError(f"no history item {item_id}")

    def allow_media(self, paths):
        """Folders of files the UI was handed (clips, covers) become viewable through the media protocol."""
        self._media |= {os.path.dirname(p) for p in paths if isinstance(p, str) and os.path.isabs(p)}

    def item(self, item_id):
        """One entry + (work folders) its outputs, covers, sheets, post copy and notes for the work page."""
        r = self.find(item_id)
        r["log"] = log_tail(r["dir"])
        if r["kind"] == "work":
            r = dict(r, detail=WK.detail(r["dir"]))
            det = r["detail"]
            self._media |= {os.path.dirname(p) for p in det["outputs"] + det["covers"] + det["sheets"]}
        return r

    def adopt(self, item_id, recipe="guess", title=None):
        r = self.find(item_id)
        need(r["kind"] == "work", "only a plain work folder can be adopted (batches / projects already are)")
        out = WK.adopt(r["dir"], recipe=recipe, title=title, home=vstudio_home())
        return dict(out, id=item_id)

    def roots(self):
        """``jobs/`` folders of the last listed entries with a thumbnail (the media protocol allow-list)."""
        return sorted({os.path.dirname(os.path.dirname(os.path.dirname(t))) if os.sep + "jobs" + os.sep in t
                       else os.path.dirname(t) for t in self._thumbs | self._thumbs_archived} | self._media)
