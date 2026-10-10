"""Live status of a job / batch / project folder, readable by the desk app while work runs anywhere (the desk, a
terminal ``vstudio.batch run``, Claude Code + the skill, an agent).

    <dir>/.vstudio/status.json  {status running|waiting|done|failed, stage, progress 0..1, message, eta (s),
                                 needs_you, started, heartbeat, pid, host, updated_by, jobs_done, jobs_total,
                                 live_code + live_params (the batch / project line as a code the desk words:
                                 jobs {done, total} | deciding {kind} | checkpoint {ids, kinds})}

Writers: the batch runner (a heartbeat thread while ``run`` holds the lock; a project's ``state/`` batch writes to
the project folder), ``Project.run`` (``waiting`` + ``needs_you`` at a checkpoint), ``vstudio.project touch`` /
``works.touch(..., status=...)`` and ``heartbeat()`` from the long workflow stages (ASR, cleanup, export, AIGC
polling) - those only write where a ``.vstudio/`` folder already exists (a registered job) or ``VSTUDIO_WORK_DIR``
says where. Reader: ``read()`` -> the effective status: a ``running`` record whose heartbeat is older than
``STALE_S`` (and whose process is gone) or older than ``HARD_S`` is ``interrupted`` - never "running forever".
Writing never raises.
"""
import json
import os
import socket
import threading
import time

STALE_S = 600          # no heartbeat for 10 min and the writer process is gone -> interrupted
HARD_S = 7200          # no heartbeat for 2 h -> interrupted even if a process with that pid exists
THROTTLE_S = 5.0
STATES = ("running", "waiting", "done", "failed")
_last = {}
_lock = threading.Lock()


def status_path(d):
    return os.path.join(os.path.abspath(d), ".vstudio", "status.json")


def owner_dir(batch_dir):
    """A project's batch lives in <project>/state: its status belongs to the project folder."""
    d = os.path.abspath(batch_dir)
    parent = os.path.dirname(d)
    if os.path.basename(d) == "state" and os.path.exists(os.path.join(parent, "project.yaml")):
        return parent
    return d


def _read_raw(d):
    try:
        with open(status_path(d), encoding="utf-8") as f:
            v = json.load(f)
        return v if isinstance(v, dict) else None
    except (OSError, ValueError):
        return None


def write(d, status, stage=None, progress=None, message=None, eta=None, needs_you=None, by=None, **extra):
    """Merge + write the status record (heartbeat = now). -> the record, or None when it could not be written."""
    if status not in STATES:
        raise ValueError(f"status: {' | '.join(STATES)}")
    try:
        old = _read_raw(d) or {}
        now = time.time()
        rec = dict(old)
        if status == "running" and old.get("status") != "running":
            rec["started"] = now
        rec.update(status=status, heartbeat=now, pid=os.getpid(), host=socket.gethostname(),
                   updated_by=by or old.get("updated_by"))
        for k, v in (("stage", stage), ("message", message), ("eta", eta)):
            if v is not None:
                rec[k] = v
        if message is not None and not extra.get("live_code"):
            rec.pop("live_code", None)          # a new free-text message: the old coded line no longer applies
            rec.pop("live_params", None)
        if status != "running":
            rec.pop("eta", None)                # time left only while it runs
        if progress is not None:
            rec["progress"] = max(0.0, min(1.0, float(progress)))
        rec["needs_you"] = bool(needs_you) if needs_you is not None else (status == "waiting" and old.get("needs_you", False))
        if status in ("done", "failed"):
            rec["finished"] = now
            rec["needs_you"] = False
            if status == "done":
                rec["progress"] = 1.0
        rec.update({k: v for k, v in extra.items() if v is not None})
        try:                                    # code + params for the desk (references/MESSAGES.md)
            from vstudio import messages as MSG
            rec["status_info"] = MSG.state("status", status)
            if rec.get("stage"):
                rec["stage_info"] = MSG.stage(rec["stage"])
            if message is not None or extra.get("message_code"):
                mc = extra.get("message_code")
                rec["message_info"] = MSG.msg(mc, None, None, **(extra.get("message_params") or {})) if mc \
                    else MSG.coded("status-text", str(message))
        except Exception:  # noqa: BLE001 - a status write never fails on its labels
            pass
        p = status_path(d)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = f"{p}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, p)
        return rec
    except (OSError, TypeError, ValueError):
        return None


def _pid_alive(pid):
    """True while ``pid`` exists (never signals it: ``os.kill(pid, 0)`` terminates the process on Windows)."""
    from ..oscompat import pid_alive as alive
    return alive(pid)


def effective(rec, now=None):
    """The record + ``state`` (running|waiting|done|failed|interrupted), ``age`` (s since the heartbeat), ``stale``."""
    if not isinstance(rec, dict) or rec.get("status") not in STATES:
        return None
    now = now or time.time()
    age = max(0.0, now - float(rec.get("heartbeat") or 0))
    state = rec["status"]
    stale = False
    if state == "running":
        here = rec.get("host") == socket.gethostname()
        gone = not here or not _pid_alive(rec.get("pid"))
        if age > HARD_S or (age > STALE_S and gone):
            state, stale = "interrupted", True
    return dict(rec, state=state, age=round(age, 1), stale=stale)


def read(d, now=None):
    return effective(_read_raw(d), now)


def _target(d=None):
    """Where a workflow heartbeat goes: ``d``, $VSTUDIO_WORK_DIR, or the nearest cwd ancestor holding .vstudio/."""
    if d:
        return os.path.abspath(d)
    env = os.environ.get("VSTUDIO_WORK_DIR")
    if env:
        return os.path.abspath(env)
    cur = os.getcwd()
    home = os.path.expanduser("~")
    for _ in range(3):                              # the job folder, or work/ / a sub-step folder inside it
        if cur in (home, os.sep):
            break
        if os.path.isfile(os.path.join(cur, ".vstudio", "work.json")) or \
                os.path.isfile(os.path.join(cur, ".vstudio", "status.json")):
            return cur
        nxt = os.path.dirname(cur)
        if nxt == cur:
            break
        cur = nxt
    return None


def heartbeat(stage=None, progress=None, message=None, eta=None, d=None, status="running", force=False):
    """Cheap, throttled, never raises; a no-op outside a registered job folder. Call it from long stages."""
    try:
        t = _target(d)
        if not t:
            return None
        now = time.time()
        with _lock:
            key = (t, stage)
            if not force and now - _last.get(key, 0) < THROTTLE_S:
                return None
            _last[key] = now
        return write(t, status, stage=stage, progress=progress, message=message, eta=eta, by="workflow")
    except Exception:  # noqa: BLE001  (status reporting must never break the work)
        return None


class Pulse:
    """Background heartbeat while a long operation runs: ``with Pulse(dir, fields_fn): ...``. ``fields_fn()`` returns
    the current {stage, progress, message, eta}; written every ``every`` s, and once at exit with ``final``."""

    def __init__(self, d, fields_fn, every=20.0, by="batch"):
        self.d, self.fields_fn, self.every, self.by = d, fields_fn, every, by
        self._stop = threading.Event()
        self._t = None
        self.final = None

    def beat(self, status="running", **kw):
        try:
            f = dict(self.fields_fn() or {})
        except Exception:  # noqa: BLE001
            f = {}
        if kw.get("message") is not None and "live_code" not in kw:
            f.pop("live_code", None)            # the final line says it in its own words
            f.pop("live_params", None)
        f.update({k: v for k, v in kw.items() if v is not None})
        return write(self.d, status, by=self.by, **{k: f.get(k) for k in ("stage", "progress", "message", "eta",
                                                                            "needs_you", "jobs_done", "jobs_total",
                                                                            "live_code", "live_params")})

    def _loop(self):
        while not self._stop.wait(self.every):
            self.beat()

    def __enter__(self):
        self.beat()
        self._t = threading.Thread(target=self._loop, daemon=True, name="vstudio-status")
        self._t.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._t:
            self._t.join(timeout=2)
        if exc_type is not None:
            self.beat("failed", message=f"{exc_type.__name__}: {exc}"[:300])
        elif self.final:
            self.beat(**self.final)
        return False
