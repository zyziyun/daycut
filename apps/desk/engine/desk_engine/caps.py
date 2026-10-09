"""Capability probing for the v0.2 engine commands (PRODUCT_V02.md section 3) + a JSON CLI runner.

The v0.2 commands (plan-segments, client, job edit / job rerun, deliver, metrics, timing) are added to
``python -m vstudio.batch`` by the engine repo over time. The desk never assumes them: at start it probes

  1. ``python -m vstudio.batch recipes --json`` - if the document is an object with a ``capabilities`` list
     (e.g. ``{"recipes": [...], "capabilities": ["plan-segments", "job-edit", ...]}``) that list wins;
  2. otherwise ``python -m vstudio.batch --help`` (argparse prints the sub-command set ``{plan,estimate,...}``)
     plus ``job --help`` / ``client --help`` for the nested verbs.

Capability names (stable, used by the adapter): plan-segments, client, job-edit, job-rerun, deliver, metrics,
timing. A missing capability means the adapter uses its own faithful implementation (the test engine) or reports
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
    """``doc``: the engine's JSON refusal ({ok: false, code, params, message, message_zh}) when it printed one."""

    def __init__(self, msg, doc=None):
        super().__init__(msg)
        self.doc = doc


class CliRunner:
    """Runs ``python -m vstudio.batch <args>`` and returns the JSON document printed on stdout."""

    def __init__(self, python, env, timeout=600, module="vstudio.batch"):
        self.python, self.env, self.timeout, self.module = python, env, timeout, module

    def sibling(self, module):
        """The same Python + env for another engine module (vstudio.project, vstudio.intake)."""
        return CliRunner(self.python, self.env, self.timeout, module)

    def _run(self, args, timeout=None, cwd=None, track=None):
        """``track``: a list the child is appended to while it runs (its own process group, so a stop can kill it
        together with the model CLI it started: :func:`kill_tracked`)."""
        cmd = [self.python, "-m", self.module, *args]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env,
                                 cwd=cwd, stdin=subprocess.DEVNULL, start_new_session=track is not None)
        except OSError as e:
            raise CliError(f"{self.module} {args[0]}: {e}") from e
        if track is not None:
            track.append(p)
        try:
            out, err = p.communicate(timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired as e:
            kill_tracked([p])
            p.communicate()
            raise CliError(f"{self.module} {args[0]}: timed out after {e.timeout:.0f} s") from e
        finally:
            if track is not None and p in track:
                track.remove(p)
        return subprocess.CompletedProcess(cmd, p.returncode, out, err)

    def text(self, args, timeout=30):
        p = self._run(args, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")

    def json(self, args, timeout=None, cwd=None, track=None):
        p = self._run(args, timeout=timeout, cwd=cwd, track=track)
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
            raise CliError(f"{self.module} {args[0]} exited {p.returncode}: {' | '.join(tail) or 'no JSON output'}")
        if isinstance(doc, dict) and doc.get("ok") is False and p.returncode != 0:
            raise CliError(str(doc.get("error") or doc.get("message") or doc.get("reason") or f"{args[0]} failed"), doc)
        return doc

    def events(self, args, on_event, timeout=None, track=None):
        """``args`` with ``--json-events``: every {event: ...} line goes to ``on_event`` as it arrives; -> the final
        {event: done} line. A child that ends without one raises ``CliError`` (its error event, else stderr's tail)."""
        cmd = [self.python, "-m", self.module, *args]
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=self.env,
                                 stdin=subprocess.DEVNULL, start_new_session=track is not None, bufsize=1)
        except OSError as e:
            raise CliError(f"{self.module} {args[0]}: {e}") from e
        if track is not None:
            track.append(p)
        tail = []

        def drain():                                       # stderr is the log: kept short, never blocks the child
            for line in p.stderr:
                tail.append(line.rstrip())
                del tail[:-20]
        t_err = threading.Thread(target=drain, daemon=True)
        t_err.start()
        expired = threading.Event()

        def expire():
            expired.set()
            kill_tracked([p])
        timer = threading.Timer(timeout or self.timeout, expire)
        timer.daemon = True
        timer.start()
        done = failed = None
        try:
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(ev, dict) or not ev.get("event"):
                    continue
                if ev["event"] == "done":
                    done = ev
                elif ev["event"] == "error":
                    failed = ev
                else:
                    try:
                        on_event(ev)
                    except Exception:  # noqa: BLE001 - the consumer's problem never stops the run
                        pass
            p.wait()
        finally:
            timer.cancel()
            t_err.join(timeout=2)
            if track is not None and p in track:
                track.remove(p)
        if expired.is_set():
            raise CliError(f"{self.module} {args[0]}: timed out after {timeout or self.timeout:.0f} s")
        if done is None or p.returncode != 0:
            why = (failed or {}).get("error") or " | ".join(tail[-3:]) or "no done event"
            raise CliError(f"{self.module} {args[0]} exited {p.returncode}: {why}")
        return done


def kill_tracked(procs):
    """Ends each child and its process group (the engine + any model CLI it started). -> how many were running."""
    import signal
    n = 0
    for p in list(procs):
        if p.poll() is not None:
            continue
        n += 1
        try:
            from .proc import kill_tree
            kill_tree(p, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                p.kill()
            except OSError:
                pass
    return n


def node_health(refresh=False):
    """The Node.js HyperFrames renders on (vstudio.node): {ok, version, path, error, fix, checked}. ``fix`` is plain
    text; ok None when the engine is too old to tell."""
    try:
        from vstudio import node
    except ImportError:
        return dict(ok=None, version=None, path=None, error="engine too old to check Node.js", fix=None, checked=[])
    try:
        d = node.health(refresh=refresh)
    except Exception as e:  # noqa: BLE001  (a probe never breaks the capabilities document)
        return dict(ok=False, version=None, path=None, error=f"node check failed: {e}", fix=None, checked=[])
    return {k: d.get(k) for k in ("ok", "version", "path", "error", "fix", "checked")}


def ffmpeg_health():
    """The ffmpeg / ffprobe the engine uses (vstudio.media): {ok, path, ffprobe, version, error}."""
    try:
        from vstudio import media
    except ImportError:
        return dict(ok=None, path=None, ffprobe=None, version=None, error="engine too old to check ffmpeg")
    try:
        ff, fp = media.ffmpeg_bin(), media.ffprobe_bin()
        r = subprocess.run([ff, "-hide_banner", "-version"], capture_output=True, text=True, timeout=20,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            first = next((ln for ln in (r.stderr or r.stdout or "").splitlines() if ln.strip()), f"exit {r.returncode}")
            return dict(ok=False, path=ff, ffprobe=fp, version=None, error=f"ffmpeg does not run: {first.strip()}")
        ver = (r.stdout or "").split("\n", 1)[0].replace("ffmpeg version ", "").split(" ")[0] or None
        return dict(ok=True, path=ff, ffprobe=fp, version=ver, error=None)
    except Exception as e:  # noqa: BLE001
        return dict(ok=False, path=None, ffprobe=None, version=None, error=str(e).splitlines()[0][:300])


def tools_health(refresh=False):
    """{node: node_health(), ffmpeg: ffmpeg_health()} - what a render needs outside Python, so the app can warn
    before a render (tool-node / tool-ffmpeg failures, see desk_engine.pilot)."""
    return dict(node=node_health(refresh), ffmpeg=ffmpeg_health())


class Capabilities:
    """Lazily probed, cached capability set. ``fixed`` skips probing (the test engine / tests)."""

    def __init__(self, runner=None, fixed=None):
        self.runner = runner
        self._caps = set(fixed) if fixed is not None else None
        self._lock = threading.Lock()
        self.source = "fixed" if fixed is not None else None
        self._tools = None

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
            self._tools = None

    def tools(self, refresh=False):
        """tools_health(), cached (real mode only: the fixed / test engine renders nothing)."""
        if self.runner is None:
            return None
        if self._tools is None or refresh:
            self._tools = tools_health(refresh)
        return self._tools

    def info(self):
        caps = self.probe()
        out = dict(source=self.source, commands={c: c in caps for c in V02})
        tools = self.tools()
        if tools is not None:
            out["tools"] = tools
        return out


def runner_env(engine_path=None):
    env = dict(os.environ)
    if engine_path:
        lib = os.path.join(engine_path, "lib")
        env["PYTHONPATH"] = lib + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("DESK_TOKEN", None)
    return env
