"""The pilot run the desk starts after 「开始」 (``python -m vstudio.project run --pilot 1 --json-events``), and how
it ended.

The child runs in its own session (it outlives the desk); stdout + stderr go to ``<project>/desk-pilot.log`` and
``<project>/desk-pilot.json`` records {pid, started, offset (log size at the start), exit, finished, provider}.
:func:`failure` reads both and answers None (running / fine / needs you) or a plain failure:

    {state: "failed", code: ai-login | ai-quota | ai-timeout | ai-missing | engine | disk | media | unknown,
     provider: claude-code | codex | anthropic | openai | None, error: short text without paths, at}

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
    ("ai-login", r"\b401\b|auth-expired|not-logged-in|authenticat|not logged in|"
                 r"log ?in (again|required|expired)|session expired|token expired|"
                 r"unauthori[sz]ed|invalid (api )?key|invalid x-api-key|credential"),
    ("ai-quota", r"\b429\b|rate.?limit|rate-limited|quota|usage limit|credit balance|insufficient_quota|overloaded"),
    ("ai-timeout", r"timed? ?out|timeout"),
    ("ai-missing", r"(claude|codex)\b.*(not found|no such file|not installed)|command not found"),
    ("disk", r"no space left|disk full"),
    ("engine", r"no module named|importerror|modulenotfounderror|traceback \(most recent"),
    ("media", r"ffmpeg|invalid data found|moov atom|could not open|no such file"),
)
_PATH_RE = re.compile(r"(?:/(?:Users|home|private|var|tmp|Volumes|opt|Applications)/|[A-Za-z]:\\)[^\s'\"]*")


def classify(text):
    t = (text or "").lower()
    for code, rx in _CODES:
        if re.search(rx, t):
            return code
    return "unknown"


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
    err = None
    for e in reversed(evs):
        if e.get("ok") is False or e.get("error"):
            err = e.get("error") or e.get("message") or e.get("reason")
            if err:
                break
    if not err:                                               # a traceback / CLI line on stderr
        err = next((ln.strip() for ln in reversed(lines) if ln.strip() and not ln.strip().startswith("{")), "")
    return dict(state="failed", code=classify(err), provider=rec.get("provider") or provider_of(err),
                error=scrub(err), exit=code, at=rec.get("finished") or rec.get("started") or now or time.time())


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


def spawn(python, env, d, provider=None, bus=None, args=None):
    """Start the pilot of project ``d`` in the background (or ``args`` instead of the default run command)."""
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
        if bus:
            bus.publish("batches")
            bus.publish("inbox")
    threading.Thread(target=wait, daemon=True).start()
    return rec


def resume_after_answer(runner, d, bus=None, spawner=None):
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
    py = runner.python
    if isinstance(st, dict) and st.get("batch_state") == "pilot-review":
        # the desk's pilot (every new project starts as one): `resume` would stop at once ("pilot-review"), and the
        # question she just answered stays listed until its stage runs again - so carry on with the same pilot run
        # (finished stages are cached; it stops again at any question still open)
        return (spawner or spawn)(py, runner.env, d, bus=bus)
    pend = cli.json(["inbox", "--json"], timeout=120)
    entries = (pend.get("entries") or pend.get("items") or []) if isinstance(pend, dict) else []
    if any(os.path.realpath(e.get("project") or e.get("dir") or "") == rd for e in entries if isinstance(e, dict)):
        return None                                           # another question still waits for her
    return (spawner or spawn)(py, runner.env, d, bus=bus,
                              args=[py, "-m", "vstudio.project", "resume", "--dir", d, "--json-events"])
