"""Find a Node.js that actually runs, for ``npx hyperframes`` and other Node tools.

The first ``node`` on PATH is not always usable: a Homebrew node whose dylibs were upgraded away dies with
``dyld: Library not loaded: .../libsimdjson.29.dylib`` while an nvm / volta / fnm node next to it works. And a
Finder-launched app never sees the nvm folders on PATH at all. :func:`resolve` probes the candidates in order

  $VSTUDIO_NODE (an explicit binary), PATH order, /opt/homebrew/bin, /usr/local/bin,
  ~/.nvm/versions/node/* (newest first), ~/.volta/bin, fnm installs (newest first)

and picks the first whose ``node -v`` exits 0 with a version >= :data:`MIN_MAJOR`. Its folder goes in front of
PATH for the child (:func:`child_env`), so ``npx`` and every ``#!/usr/bin/env node`` script below it run on that
node too. The answer is cached per process (per PATH / home). When nothing works :class:`NodeError` explains
which node is broken, its first stderr line and the fix.

    from vstudio import node
    subprocess.run(node.npx("hyperframes", "render", ...), env=node.child_env())
    node.health()  # {"ok": bool, "version", "path", "error", "fix", "checked": [...]} - never raises
"""
import glob
import os
import re
import subprocess
import sys

MIN_MAJOR = 18
CODE = "tool-node"                      # the failure code the desk shows its own words for (desk_engine.pilot)
SYSTEM_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")     # Homebrew / installer nodes a Finder-launched app misses
_EXE = ".exe" if sys.platform == "win32" else ""
_VER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")
_cache = {}


class NodeError(RuntimeError):
    """No usable Node.js. ``info``: the :func:`health` document (broken / too old candidates, fix text)."""
    code = CODE

    def __init__(self, msg, info=None):
        super().__init__(msg)
        self.info = info or {}


def _vkey(name):
    m = _VER.search(os.path.basename(str(name)))
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def candidate_dirs(env=None, home=None):
    """Folders that may hold a ``node`` binary, in probe order (duplicates removed, existence not checked)."""
    env = os.environ if env is None else env
    home = home or os.path.expanduser("~")
    dirs = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]
    dirs += list(SYSTEM_DIRS)
    nvm = env.get("NVM_DIR") or os.path.join(home, ".nvm")
    dirs += [os.path.join(d, "bin") for d in sorted(glob.glob(os.path.join(nvm, "versions", "node", "*")),
                                                    key=_vkey, reverse=True)]
    dirs.append(os.path.join(env.get("VOLTA_HOME") or os.path.join(home, ".volta"), "bin"))
    fnm_roots = [env.get("FNM_DIR") or "", os.path.join(home, "Library", "Application Support", "fnm"),
                 os.path.join(home, ".local", "share", "fnm"), os.path.join(home, ".fnm")]
    fnm = []
    for root in filter(None, fnm_roots):
        fnm += glob.glob(os.path.join(root, "node-versions", "*", "installation", "bin"))
    dirs += sorted(fnm, key=lambda p: _vkey(os.path.basename(os.path.dirname(os.path.dirname(p)))), reverse=True)
    if env.get("FNM_MULTISHELL_PATH"):
        dirs.append(os.path.join(env["FNM_MULTISHELL_PATH"], "bin"))
    out, seen = [], set()
    for d in dirs:
        k = os.path.normcase(os.path.abspath(os.path.expanduser(d)))
        if k not in seen:
            seen.add(k)
            out.append(os.path.expanduser(d))
    return out


def probe(path, timeout=15):
    """Run ``<path> -v``: {path, ok, version, major, error} (error: first stderr line when it does not run)."""
    try:
        r = subprocess.run([path, "-v"], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        return dict(path=path, ok=False, version=None, major=None, error=str(e).strip().splitlines()[0][:300])
    m = _VER.search(r.stdout or "")
    if r.returncode != 0 or not m:
        err = next((ln.strip() for ln in ((r.stderr or "") + "\n" + (r.stdout or "")).splitlines() if ln.strip()),
                   f"exit {r.returncode}")
        return dict(path=path, ok=False, version=None, major=None, error=err[:300])
    major = int(m.group(1))
    v = "v" + ".".join(m.groups())
    if major < MIN_MAJOR:
        return dict(path=path, ok=False, version=v, major=major, error=f"{v} is too old (need {MIN_MAJOR}+)")
    return dict(path=path, ok=True, version=v, major=major, error=None)


def _fix(bad):
    p = (bad or {}).get("path") or ""
    if "homebrew" in p or "/Cellar/" in p or (p.startswith("/usr/local/") and os.path.islink(p)):
        return "Run `brew reinstall node` in Terminal (or install Node 22 from nodejs.org), then try again."
    return "Install Node 22 (nodejs.org, or `nvm install 22`), then try again."


def _scan(env, home):
    checked = []
    real_seen = set()
    for d in candidate_dirs(env, home):
        exe = os.path.join(d, "node" + _EXE)
        if not (os.path.isfile(exe) and os.access(exe, os.X_OK)):
            continue
        real = os.path.realpath(exe)
        if real in real_seen:
            continue
        real_seen.add(real)
        r = probe(exe)
        r["bin"] = d
        checked.append(r)
        if r["ok"]:
            return r, checked
    return None, checked


def _key(env, home):
    return (env.get("VSTUDIO_NODE") or "", env.get("PATH") or "", home or os.path.expanduser("~"))


def health(env=None, home=None, refresh=False):
    """Never raises: {ok, version, path, bin, error, fix, checked: [{path, ok, version, error}]}."""
    env = os.environ if env is None else env
    k = _key(env, home)
    if not refresh and k in _cache:
        return _cache[k]
    explicit = env.get("VSTUDIO_NODE")
    if explicit:
        r = probe(explicit)
        r["bin"] = os.path.dirname(explicit)
        good, checked = (r if r["ok"] else None), [r]
    else:
        good, checked = _scan(env, home)
    if good:
        doc = dict(ok=True, version=good["version"], path=good["path"], bin=good["bin"], error=None, fix=None,
                   checked=[{x: c[x] for x in ("path", "ok", "version", "error")} for c in checked])
    else:
        broken = next((c for c in checked if c["major"] is None), None)
        old = next((c for c in checked if c["major"] is not None), None)
        if broken:
            err = f"node unavailable: the Node.js at {broken['path']} is broken ({broken['error']})"
        elif old:
            err = f"node unavailable: the Node.js at {old['path']} is {old['version']}; HyperFrames needs {MIN_MAJOR}+"
        else:
            err = f"node unavailable: Node.js {MIN_MAJOR}+ is not installed (HyperFrames renders need it)"
        fix = _fix(broken) if broken else "Install Node 22 (nodejs.org, or `nvm install 22`), then try again."
        doc = dict(ok=False, version=None, path=(broken or old or {}).get("path"), bin=None, error=err, fix=fix,
                   checked=[{x: c[x] for x in ("path", "ok", "version", "error")} for c in checked])
    _cache[k] = doc
    return doc


def resolve(env=None, home=None, refresh=False):
    """The working node: {path, bin, version, ...}. Raises :class:`NodeError` (message + fix) when none works."""
    doc = health(env, home, refresh)
    if not doc["ok"]:
        raise NodeError(f"{doc['error']}. {doc['fix']}", doc)
    return doc


def child_env(base=None, home=None, extra_dirs=()):
    """A copy of ``base`` (default os.environ) with the working node's folder (and ``extra_dirs``) in front of
    PATH. Raises :class:`NodeError`."""
    env = dict(os.environ if base is None else base)
    doc = resolve(env, home)
    front = [d for d in (*extra_dirs, doc["bin"]) if d]
    env["PATH"] = os.pathsep.join(front + [p for p in (env.get("PATH") or "").split(os.pathsep) if p and p not in front])
    return env


def npx(*args, env=None, home=None):
    """argv for ``npx <args>`` from the working node's folder (falls back to plain ``npx`` on PATH)."""
    doc = resolve(env, home)
    exe = os.path.join(doc["bin"], "npx" + (".cmd" if sys.platform == "win32" else ""))
    return [exe if os.path.exists(exe) else "npx", *args]


def clear_cache():
    _cache.clear()
