"""Check that every package the engine's requirements.txt names is installed and imports (run with the runtime's python).

The runtime is pip-installed --no-deps from packaging/requirements/<target>.txt, so a package added to the engine's
requirements.txt but not re-locked (node scripts/runtime/lock.mjs --only=requirements) is silently missing from the app.
Markers are evaluated for this interpreter; extras (fonttools[woff]) must have their dependencies installed too.
Usage: python check_requirements.py <requirements.txt>   -> one JSON list on stdout; exit 1 when anything is missing.
"""
import importlib
import importlib.metadata as md
import json
import sys

from packaging.requirements import Requirement

IMPORTS = {"opencv-python": "cv2", "pillow": "PIL", "pyyaml": "yaml", "fonttools": "fontTools"}


def check(text):
    rows = []
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        r = Requirement(line)
        if r.marker and not r.marker.evaluate():
            continue
        name = r.name.lower()
        row = dict(req=line, name=name)
        try:
            row["version"] = md.version(name)
            importlib.import_module(IMPORTS.get(name, name.replace("-", "_")))
            for extra in sorted(r.extras):
                for dep in md.requires(name) or []:
                    d = Requirement(dep)
                    if d.marker and d.marker.evaluate({"extra": extra}) and not d.marker.evaluate({"extra": ""}):
                        md.version(d.name)
        except Exception as e:  # noqa: BLE001 - reported per package
            row["error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as f:
        rows = check(f.read())
    print(json.dumps(rows))
    bad = [f"{r['req']}: {r['error']}" for r in rows if "error" in r]
    if bad:
        print("missing from the runtime (re-lock packaging/requirements):\n  " + "\n  ".join(bad), file=sys.stderr)
        sys.exit(1)
