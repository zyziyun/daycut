"""Capability probing for the v0.2 engine commands (PRODUCT_V02.md section 3) + a JSON CLI runner.

The v0.2 commands (plan-segments, client, job edit / job rerun, deliver, metrics, timing) are added to
``python -m vstudio.batch`` by the engine repo over time. The desk never assumes them: at start it probes

  1. ``python -m vstudio.batch recipes --json`` - if the document is an object with a ``capabilities`` list
     (e.g. ``{"recipes": [...], "capabilities": ["plan-segments", "job-edit", ...]}``) that list wins;
  2. otherwise ``python -m vstudio.batch --help`` (argparse prints the sub-command set ``{plan,estimate,...}``)
     plus ``job --help`` / ``client --help`` for the nested verbs.

Capability names (stable, used by the adapter): plan-segments, client, job-edit, job-rerun, deliver, metrics,
timing. A missing capability means the adapter uses its own faithful implementation (mock mode) or reports
"engine too old" (real mode, for operations that need media processing).
"""
import json
import os
import re
import subprocess
import threading

V02 = ("plan-segments", "client", "job-edit", "job-rerun", "deliver", "metrics", "timing")


def parse_help(top, job_help="", client_help=""):
    """argparse --help texts -> set of capability names."""
    caps = set()
    m = re.search(r"\{([a-z0-9_,-]+)\}", top or "")
    cmds = set(m.group(1).split(",")) if m else set()
    if "plan-segments" in cmds:
        caps.add("plan-segments")
    if "deliver" in cmds:
        caps.add("deliver")
    if "metrics" in cmds:
        caps.add("metrics")
    if "timing" in cmds:
        caps.add("timing")
    if "client" in cmds and re.search(r"\binit\b", client_help or "") and re.search(r"\bupdate\b", client_help or ""):
        caps.add("client")
    if "job" in cmds:
        jm = re.search(r"\{([a-z0-9_,-]+)\}", job_help or "")
        verbs = set(jm.group(1).split(",")) if jm else set()
        if "edit" in verbs:
            caps.add("job-edit")
        if "rerun" in verbs:
            caps.add("job-rerun")
    return caps


def parse_recipes_doc(doc):
    """``recipes --json`` document -> capability set, or None when it carries no capability list."""
    if isinstance(doc, dict) and isinstance(doc.get("capabilities"), list):
        return {c for c in doc["capabilities"] if isinstance(c, str) and c in V02}
    return None


class CliError(RuntimeError):
    pass


class CliRunner:
    """Runs ``python -m vstudio.batch <args>`` and returns the JSON document printed on stdout."""

    def __init__(self, python, env, timeout=600):
        self.python, self.env, self.timeout = python, env, timeout

    def _run(self, args, timeout=None, cwd=None):
        try:
            p = subprocess.run([self.python, "-m", "vstudio.batch", *args], capture_output=True, text=True,
                               env=self.env, timeout=timeout or self.timeout, cwd=cwd, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError) as e:
            raise CliError(f"vstudio.batch {args[0]}: {e}") from e
        return p

    def text(self, args, timeout=30):
        p = self._run(args, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")

    def json(self, args, timeout=None, cwd=None):
        p = self._run(args, timeout=timeout, cwd=cwd)
        out = (p.stdout or "").strip()
        try:
            doc = json.loads(out) if out else None
        except ValueError:
            # tolerate a human line before the JSON document
            i = out.find("{") if "{" in out else out.find("[")
            try:
                doc = json.loads(out[i:]) if i >= 0 else None
            except ValueError:
                doc = None
        if doc is None:
            tail = (p.stderr or "").strip().splitlines()[-3:]
            raise CliError(f"vstudio.batch {args[0]} exited {p.returncode}: {' | '.join(tail) or 'no JSON output'}")
        if isinstance(doc, dict) and doc.get("ok") is False and p.returncode != 0:
            raise CliError(str(doc.get("error") or doc.get("reason") or f"{args[0]} failed"))
        return doc


class Capabilities:
    """Lazily probed, cached capability set. ``fixed`` skips probing (mock mode / tests)."""

    def __init__(self, runner=None, fixed=None):
        self.runner = runner
        self._caps = set(fixed) if fixed is not None else None
        self._lock = threading.Lock()
        self.source = "fixed" if fixed is not None else None

    def probe(self):
        with self._lock:
            if self._caps is not None:
                return self._caps
            caps = None
            try:
                caps = parse_recipes_doc(self.runner.json(["recipes", "--json"], timeout=60))
                if caps is not None:
                    self.source = "recipes --json"
            except Exception:  # noqa: BLE001
                caps = None
            if caps is None:
                try:
                    top = self.runner.text(["--help"])
                    job = self.runner.text(["job", "--help"]) if re.search(r"[{,]job[,}]", top) else ""
                    cl = self.runner.text(["client", "--help"]) if re.search(r"[{,]client[,}]", top) else ""
                    caps = parse_help(top, job, cl)
                    self.source = "--help"
                except Exception:  # noqa: BLE001
                    caps = set()
                    self.source = "probe failed"
            self._caps = caps
            return caps

    def has(self, name):
        return name in self.probe()

    def reset(self):
        with self._lock:
            self._caps = None

    def info(self):
        caps = self.probe()
        return dict(source=self.source, commands={c: c in caps for c in V02})


def runner_env(engine_path=None):
    env = dict(os.environ)
    if engine_path:
        lib = os.path.join(engine_path, "lib")
        env["PYTHONPATH"] = lib + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("DESK_TOKEN", None)
    return env
