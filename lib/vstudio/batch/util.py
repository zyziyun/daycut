"""Small helpers shared by the batch modules (hashing, time parsing, sizes, dotted imports)."""
import hashlib
import importlib
import json
import os
import re
import time


def now():
    return time.time()


def sha1_json(obj, n=None):
    h = hashlib.sha1(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return h[:n] if n else h


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path, obj):
    """Atomic JSON write (tmp + replace)."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)
    return path


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def parse_time(s):
    """"1:02:03.5" / "62.5" / 62.5 -> seconds."""
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    v = 0.0
    for p in s.split(":"):
        v = v * 60 + float(p)
    return v


def parse_range(r):
    """[a, b] / (a, b) / "12.5-70" / "1:10-2:05" / {"start":..,"end":..} -> (a, b) floats, or None."""
    if r is None or r == "":
        return None
    if isinstance(r, dict):
        return parse_time(r.get("start", r.get("t0"))), parse_time(r.get("end", r.get("t1")))
    if isinstance(r, (list, tuple)):
        a, b = r[:2]
        return parse_time(a), parse_time(b)
    a, b = re.split(r"(?<=\d)\s*-\s*(?=\d)", str(r).strip(), maxsplit=1)
    return parse_time(a), parse_time(b)


def split_list(v, sep=None):
    """"a|b" / "a,b" / [a, b] / None -> list of stripped strings."""
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    seps = sep or ("|" if "|" in str(v) else ",")
    return [x.strip() for x in str(v).split(seps) if x.strip()]


def slug(s, n=40):
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", str(s)).strip("-")
    return s[:n] or "x"


def du(path):
    """Bytes under ``path`` (file or tree); hard links counted once."""
    if not os.path.exists(path):
        return 0
    if os.path.isfile(path):
        return os.path.getsize(path)
    seen, total = set(), 0
    for root, _, files in os.walk(path):
        for f in files:
            p = os.path.join(root, f)
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if (st.st_dev, st.st_ino) in seen:
                continue
            seen.add((st.st_dev, st.st_ino))
            total += st.st_size
    return total


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024.0


def hms(s):
    s = int(round(s or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def import_ref(ref):
    """"pkg.mod:attr" (or "pkg.mod.attr") -> the object."""
    if callable(ref):
        return ref
    mod, _, attr = ref.partition(":") if ":" in ref else ref.rpartition(".")
    return getattr(importlib.import_module(mod), attr)


def pid_alive(pid):
    """True while ``pid`` exists (never signals it: ``os.kill(pid, 0)`` terminates the process on Windows)."""
    from ..oscompat import pid_alive as alive
    return alive(pid)
