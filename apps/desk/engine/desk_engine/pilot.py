"""The pilot run the desk starts after 「开始」 (``python -m vstudio.project run --pilot 1 --json-events``), and how
it ended.

The child runs in its own session (it outlives the desk); stdout + stderr go to ``<project>/desk-pilot.log`` and
``<project>/desk-pilot.json`` records {pid, started, offset (log size at the start), exit, finished, provider}.
:func:`failure` reads both and answers None (running / fine / needs you) or a plain failure:

    (+ stage: the step that failed; a stage-fail event's own ``code`` / ``params`` win, e.g. tool-broken {tool,
    path, fix}; a Python crash inside a step is ``stage``, not ``engine``, which means the engine did not start)
    {state: "failed", code: tool-node | tool-ffmpeg | ai-login | ai-quota | ai-timeout | ai-missing | engine | disk
     | media | unknown, provider: claude-code | codex | anthropic | openai | None, error: short text without paths,
     at, + for tool-*: tool: "node" | "ffmpeg", fix: "brew-reinstall-node" | "install-node" | "reinstall-app" |
     "install-ffmpeg"}

tool-node: the Node.js that renders HyperFrames is missing, too old or broken (a Homebrew node whose dylibs were
upgraded away: ``dyld: Library not loaded ... Referenced from: .../node``). tool-ffmpeg: ffmpeg / ffprobe is missing,
broken or lacks a filter / bitstream filter the step needs.

The UI never shows ``error`` as the reason: it maps ``code`` to its own words (P0-3).
"""
import json
import os
import re
import subprocess
import threading
import time

from .common import _pid_alive, read_json, write_json

LOG = "desk-pilot.log"
REC = "desk-pilot.json"
# vstudio.project exit codes that are not failures: done, refused (over budget), paused, pilot review, busy, waiting
OK_EXIT = {0, 2, 3, 4, 6, 7}
# tasks the engine routes to a model during a run (vstudio.llm): a retry with another provider overrides each one
# (vstudio.llm.TASKS without "test")
TASKS = ("SEGMENT_PLAN", "PROOFREAD", "GLOSSARY", "COPY", "SCRIPT", "PLANNER", "INTAKE", "OUTPUT_EDIT")
PROVIDERS = ("claude-code", "codex", "anthropic", "openai")

_CODES = (
    ("tool-node", r"node unavailable|referenced from:\s*\S*/node\b|library not loaded\S*.*\bnode\b|"
                  r"npx \(node\) not found|env: node: no such file|node(\.js)? \S* ?is too old"),
    ("tool-ffmpeg", r"ffmpeg not found|ffprobe not found|vstudio_ff(mpeg|probe)=\S* does not exist|"
                    r"ffmpeg lacks filter|lacks filter\(s\)|unknown bitstream filter|no such filter|"
                    r"referenced from:\s*\S*/ff(mpeg|probe)\b|ff(mpeg|probe): (command )?not found"),
    ("ai-login", r"\b401\b|auth-expired|not-logged-in|authenticat|not logged in|"
                 r"log ?in (again|required|expired)|session expired|token expired|"
                 r"unauthori[sz]ed|invalid (api )?key|invalid x-api-key|credential"),
    ("ai-quota", r"\b429\b|rate.?limit|rate-limited|quota|usage limit|credit balance|insufficient_quota|overloaded"),
    ("ai-timeout", r"timed? ?out|timeout"),
    ("ai-missing", r"(claude|codex)\b.*(not found|no such file|not installed)|command not found"),
    ("disk", r"no space left|disk full"),
    ("engine", r"no module named|importerror|modulenotfounderror"),
    ("media", r"ffmpeg|invalid data found|moov atom|could not open|no such file"),
    ("engine", r"traceback \(most recent"),                  # any other Python crash
)
_CODES_ENGINE_START = r"no module named|importerror|modulenotfounderror"
# an error code a stage-fail event may carry (vstudio's runner: tool-missing, tool-broken, ...)
_ENGINE_CODE = re.compile(r"^(tool|stage|media|disk|ai)-[a-z0-9-]{2,40}$")
_PATH_RE = re.compile(r"(?:/(?:Users|home|private|var|tmp|Volumes|opt|Applications)/|[A-Za-z]:\\)[^\s'\"]*")


def classify(text):
    t = (text or "").lower()
    for code, rx in _CODES:
        if re.search(rx, t):
            return code
    return "unknown"


def tool_fix(code, text):
    """For a tool-* code: {tool, fix} (fix: a stable key the UI words; see the module doc), else {}."""
    t = (text or "").lower()
    if code == "tool-node":
        brew = "homebrew" in t or "/cellar/" in t or "brew" in t
        return dict(tool="node", fix="brew-reinstall-node" if brew and "too old" not in t else "install-node")
    if code == "tool-ffmpeg":
        bundled = "reelfold.app" in t or "/runtime/ffmpeg" in t or "vstudio_ff" in t
        return dict(tool="ffmpeg", fix="reinstall-app" if bundled else "install-ffmpeg")
    return {}


def provider_of(text):
    t = (text or "").lower()
    for k, p in (("claude", "claude-code"), ("codex", "codex"), ("anthropic", "anthropic"), ("openai", "openai")):
        if k in t:
            return p
    return None


def scrub(text, n=300):
    """One line, no absolute paths (they mean nothing to her and leak the folder layout)."""
    t = _PATH_RE.sub("…", " ".join(str(text or "").split()))
    return t[:n]


def _tail(path, offset=0, max_bytes=65536):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(offset, size - max_bytes))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _events(lines):
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                ev = json.loads(s)
            except ValueError:
                continue
            if isinstance(ev, dict):
                out.append(ev)
    return out


def failure(d, now=None):
    """How the last pilot of project folder ``d`` ended: None, or the failure document above."""
    rec = read_json(os.path.join(d, REC), None)
    log = os.path.join(d, LOG)
    if not isinstance(rec, dict) and not os.path.exists(log):
        return None
    rec = rec if isinstance(rec, dict) else {}
    if rec.get("queued") and not rec.get("pid"):
        return None                                           # waiting in line: an older run's end is history
    code = rec.get("exit")
    if code is None and rec.get("pid") and _pid_alive(rec.get("pid")):
        return None                                           # still running
    lines = _tail(log, int(rec.get("offset") or 0))
    evs = _events(lines)
    end = next((e for e in reversed(evs) if e.get("event") == "project-end" or e.get("ok") is False), None)
    if code is None and end is not None:
        code = end.get("exit_code") if end.get("event") == "project-end" else 5
    if code is None:
        if not rec.get("pid") or not lines:
            return None                                       # no record of a run: nothing to say
        code = -1                                             # the child is gone without a word: it crashed
    if code in OK_EXIT:
        return None
    err, bad = None, None
    for e in reversed(evs):
        if e.get("ok") is False or e.get("error"):
            err = e.get("error") or e.get("message") or e.get("reason")
            if err:
                bad = e
                break
    if not err:                                               # a traceback / CLI line on stderr
        err = next((ln.strip() for ln in reversed(lines) if ln.strip() and not ln.strip().startswith("{")), "")
    c = classify(err)
    extra = tool_fix(c, err)
    stage = (bad or {}).get("stage")
    ecode = (bad or {}).get("code") or ((bad or {}).get("error_info") or {}).get("code")
    if isinstance(ecode, str) and _ENGINE_CODE.match(ecode):
        # the engine said what failed (e.g. tool-missing / tool-broken {tool, path, fix}): its code wins
        c = ecode
        params = (bad or {}).get("params") or ((bad or {}).get("error_info") or {}).get("params")
        if isinstance(params, dict):
            extra = dict(extra, params={k: v for k, v in params.items() if isinstance(v, (str, int, float))})
    elif c == "engine" and stage and not re.search(_CODES_ENGINE_START, (err or "").lower()):
        c = "stage"            # a step crashed: the engine itself started fine ("Part of Reelfold didn't start" lies)
    out = dict(state="failed", code=c, provider=rec.get("provider") or provider_of(err),
               error=scrub(err), exit=code, at=rec.get("finished") or rec.get("started") or now or time.time(),
               **extra)
    if stage:
        out["stage"] = str(stage)
    return out


def running(d):
    """The pilot child the desk started is still going -> {started, provider}, else None."""
    rec = read_json(os.path.join(d, REC), None)
    if isinstance(rec, dict) and rec.get("exit") is None and rec.get("pid") and _pid_alive(rec.get("pid")):
        return dict(started=rec.get("started"), provider=rec.get("provider"))
    return None


def retry_env(env, provider):
    """The run's environment with every model task pinned to ``provider`` (「换 Codex 重试」)."""
    out = dict(env)
    if provider:
        out["VSTUDIO_LLM_PROVIDER"] = provider
        for t in TASKS:
            out[f"VSTUDIO_LLM_{t}_PROVIDER"] = provider
            out.pop(f"VSTUDIO_LLM_{t}_MODEL", None)
            out[f"VSTUDIO_LLM_{t}_FALLBACK"] = ""
    return out


class RunQueue:
    """How many project runs the desk starts at once (each run already uses the machine's cores / ASR / renderer to
    its own limits): ``DESK_MAX_RUNS`` (default 2 on 8+ cores, else 1). A run asked for while the slots are taken
    waits in line (``position``: 1 = next) and starts when one ends; the desk shows it as queued."""

    def __init__(self):
        self._lock = threading.Lock()
        self.active = set()
        self.waiting = []                      # [(dir, start)] in order

    def limit(self):
        try:
            n = int(os.environ.get("DESK_MAX_RUNS") or 0)
        except ValueError:
            n = 0
        return n if n > 0 else (2 if (os.cpu_count() or 1) >= 8 else 1)

    def submit(self, d, start):
        """``start(done)`` starts the run and calls ``done()`` when it ends. -> True when it started now, False when
        it waits in line (a project already running or waiting is not added twice)."""
        rd = os.path.realpath(d)
        with self._lock:
            if rd in self.active or any(w == rd for w, _s in self.waiting):
                return rd in self.active
            if len(self.active) >= self.limit():
                self.waiting.append((rd, start))
                return False
            self.active.add(rd)
        self._go(rd, start)
        return True

    def _go(self, rd, start):
        try:
            start(lambda: self.done(rd))
        except Exception:
            self.done(rd)
            raise

    def done(self, rd):
        nxt = None
        with self._lock:
            self.active.discard(rd)
            if self.waiting and len(self.active) < self.limit():
                nxt = self.waiting.pop(0)
                self.active.add(nxt[0])
        if nxt:
            try:
                self._go(*nxt)
            except Exception:  # noqa: BLE001  (its record says it never started; the next one goes)
                pass

    def position(self, d):
        rd = os.path.realpath(d)
        with self._lock:
            for k, (w, _s) in enumerate(self.waiting):
                if w == rd:
                    return k + 1
        return None

    def cancel(self, d):
        rd = os.path.realpath(d)
        with self._lock:
            n = len(self.waiting)
            self.waiting = [(w, s) for w, s in self.waiting if w != rd]
            return n != len(self.waiting)


QUEUE = RunQueue()


def queued(d):
    """The run of project ``d`` waits for a free slot -> its place in line (1 = next), else None."""
    return QUEUE.position(d)


def run_args(python, d, autopilot=False, lang=None):
    """The desk's run of a new project: a pilot of one (ask me first) or the whole project on autopilot."""
    how = ["--autopilot"] + (["--lang", lang] if lang in ("en", "zh", "fr") else []) if autopilot else ["--pilot", "1"]
    return [python, "-m", "vstudio.project", "run", "--dir", d, *how, "--json-events"]


def spawn(python, env, d, provider=None, bus=None, args=None):
    """Start the pilot of project ``d`` in the background (or ``args`` instead of the default run command), or put it
    in line when the desk's run slots are taken (``RunQueue``): its record says ``queued`` until it starts."""
    holder = {}

    def start(done):
        holder["rec"] = _start(python, env, d, provider, bus, args, done)
    if QUEUE.submit(d, start):
        return holder.get("rec") or dict(pid=None, started=None, running=True)
    rec = dict(pid=None, started=None, offset=None, exit=None, finished=None, provider=provider, queued=True,
               queued_at=time.time(), args=(args or [])[1:] or None)
    write_json(os.path.join(d, REC), rec)
    if bus:
        bus.publish("batches")
    return rec


def _start(python, env, d, provider=None, bus=None, args=None, done=None):
    log_path = os.path.join(d, LOG)
    try:
        offset = os.path.getsize(log_path)
    except OSError:
        offset = 0
    log = open(log_path, "ab")  # noqa: SIM115  (handed to the child)
    cmd = args or [python, "-m", "vstudio.project", "run", "--dir", d, "--pilot", "1", "--json-events"]
    p = subprocess.Popen(cmd, stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=retry_env(env, provider),
                         start_new_session=True)
    log.close()
    rec = dict(pid=p.pid, started=time.time(), offset=offset, exit=None, finished=None, provider=provider)
    write_json(os.path.join(d, REC), rec)

    def wait():
        code = p.wait()
        cur = read_json(os.path.join(d, REC), None) or rec
        if cur.get("pid") == p.pid:
            cur.update(exit=code, finished=time.time())
            write_json(os.path.join(d, REC), cur)
        if done:
            done()
        if bus:
            bus.publish("batches")
            bus.publish("inbox")
    threading.Thread(target=wait, daemon=True).start()
    return rec


_RESUME_LOCK = threading.Lock()   # two answers in a row: one run goes on, the second sees it running


def requeue(python, env, dirs, bus=None):
    """At start: runs that were waiting in line when the desk quit are put back in line (their record keeps the
    command), so a queued project never sits unstarted. -> the folders put back."""
    out = []
    for d in dirs:
        rec = read_json(os.path.join(d, REC), None)
        if isinstance(rec, dict) and rec.get("queued") and not rec.get("pid") and rec.get("exit") is None:
            a = rec.get("args")
            spawn(python, env, d, provider=rec.get("provider"), bus=bus,
                  args=[python, *a] if isinstance(a, list) and a else None)
            out.append(d)
    return out


def resume_after_answer(runner, d, bus=None, spawner=None):
    with _RESUME_LOCK:
        return _resume_after_answer(runner, d, bus, spawner)


def _resume_after_answer(runner, d, bus=None, spawner=None):
    """She answered a project's question in the Inbox (e.g. the per-clip review): answering records the decision but
    runs nothing, so the project sat paused until something restarted it (only the week plan did). When nothing in
    the project waits for her any more, no run is going and items are unfinished, continue it in the background:
    ``vstudio.project resume --dir d --json-events``. -> the run record, or None when there is nothing to do."""
    if runner is None or not d or not os.path.isfile(os.path.join(d, "project.yaml")) or running(d):
        return None
    cli = runner.sibling("vstudio.project")
    rd = os.path.realpath(d)
    st = cli.json(["status", "--dir", d, "--json"], timeout=120)
    items = (st.get("items") or []) if isinstance(st, dict) else []
    if not items or any(it.get("state") == "running" for it in items):
        return None
    if all(it.get("state") in ("done", "failed", "dropped") for it in items):
        return None
    pend = cli.json(["inbox", "--json"], timeout=120)
    entries = (pend.get("entries") or pend.get("items") or []) if isinstance(pend, dict) else []
    if any(os.path.realpath(e.get("project") or e.get("dir") or "") == rd for e in entries if isinstance(e, dict)):
        return None                                           # another question still waits for her
    py = runner.python
    args = [py, "-m", "vstudio.project", "resume", "--dir", d, "--json-events"]
    if isinstance(st, dict) and st.get("batch_state") == "pilot-review":
        # the desk's pilot (every new project starts as one) stops in "pilot-review", where `resume` alone ends at
        # once: she answered every question it asked, which is her look at it, so the whole project goes on (each
        # item still stops at its own questions, e.g. the review before publishing)
        args.append("--confirm-pilot")
    return (spawner or spawn)(py, runner.env, d, bus=bus, args=args)
