#!/usr/bin/env python3
"""App Store lint: what App Review rejected (or is known to reject) in a Mac App Store build, checked before upload.

    python3 scripts/appstore/appstore_lint.py <Reelfold.app>               # the signed store build (release-mas.sh)
    python3 scripts/appstore/appstore_lint.py <Reelfold.app> --unsigned    # CI: unsigned build, entitlement files
    python3 scripts/appstore/appstore_lint.py build/runtime/darwin-arm64   # the engine runtime alone

Checks (each failure names the file and the reason; exit 1 if any):
  symbols       every Mach-O's undefined symbols (`nm -m -u`) against denylist.txt (Tcl/Tk, the Accelerate BLAS names
                Apple listed, Electron's private API) and the Accelerate rule: a BLAS / LAPACK-shaped import from
                Accelerate must be a new-LAPACK entry point ($NEWLAPACK) or a documented legacy one (cblas_* /
                clapack_* / name_). Tcl/Tk files (_tkinter*.so, libtcl*, libtk*) are refused by name.   [2.5.1]
  strings       "itms-services" in bundled Python files (CPython <= 3.12's urllib.parse lists that scheme; App Review
                rejects binaries containing it - CPython 3.13 added --with-app-store-compliance for this).
  entitlements  signed: every executable Mach-O, every architecture slice (`codesign -d --entitlements - --arch`) is
                sandboxed: the app has app-sandbox and only allowed keys (never network.server), nested executables
                exactly app-sandbox + inherit, the login helper app-sandbox (+ the identifiers signing adds).
                --unsigned: the same rules on packaging/mac/entitlements.mas*.plist.                    [2.4.5]
  quarantine    no com.apple.quarantine extended attribute anywhere (upload error ITMS-91109).
Needs the Xcode command line tools (nm, codesign, lipo) for the Mach-O checks; the pure parts are unit-tested on
any OS (test_appstore_lint.py).
"""
import argparse
import fnmatch
import os
import plistlib
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DESK = os.path.dirname(os.path.dirname(HERE))
MAGICS = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"}

# ---------------------------------------------------------------------------------------------------------- symbols
ACCELERATE = {"Accelerate", "vecLib", "libBLAS", "libLAPACK", "libLinearAlgebra", "libSparse"}
# lowercase Accelerate families that are not BLAS / LAPACK (vForce, LinearAlgebra, Sparse Solvers, vecLib vector ops)
ACCEL_OTHER = re.compile(r"^_(vv|la_|sparse_|_sparse|vec|appleblas_)")
BLAS_SHAPED = re.compile(r"^_[a-z][a-z0-9_]*$")                     # vDSP_*, vImage*, BNNS* ... have capitals
LEGACY_PUBLIC = re.compile(r"^_((cblas|catlas|clapack)_[a-z0-9_]+|[a-z][a-z0-9]*_)$")
TCL_FILE = re.compile(r"^(_tkinter.*\.so|libtcl.*|libtk.*)$")


def load_denylist(path=os.path.join(HERE, "denylist.txt")):
    """-> [(pattern, library or None)]"""
    out = []
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        lib = next((p[5:] for p in parts[1:] if p.startswith("from=")), None)
        out.append((parts[0], lib))
    return out


def parse_nm(text):
    """`nm -m -u` output -> [(symbol, library or '')]"""
    out = []
    for line in text.splitlines():
        m = re.search(r"external (\S+)(?: \((?:from|dynamically looked up)\s*([^)]*)\))?", line)
        if m:
            lib = (m.group(2) or "").strip()
            out.append((m.group(1), lib))
    return out


def accelerate_kind(sym, lib):
    """-> 'bad' (non-public), 'legacy' (documented, deprecated since macOS 13.3) or None (not BLAS / LAPACK)."""
    if lib not in ACCELERATE or "$NEWLAPACK" in sym or not BLAS_SHAPED.match(sym) or ACCEL_OTHER.match(sym):
        return None
    return "legacy" if LEGACY_PUBLIC.match(sym) else "bad"


def symbol_problems(symbols, deny):
    """Undefined symbols of one file -> (problems, documented legacy BLAS/LAPACK imports)."""
    bad, legacy = [], []
    for sym, lib in symbols:
        hit = next((p for p, plib in deny if (plib is None or plib == lib) and
                    (fnmatch.fnmatchcase(sym, p) if p.endswith("*") else sym == p)), None)
        if hit:
            bad.append(f"{sym}{f' (from {lib})' if lib else ''} [denylist {hit}]")
            continue
        kind = accelerate_kind(sym, lib)
        if kind == "bad":
            bad.append(f"{sym} (from {lib}) [non-public BLAS/LAPACK]")
        elif kind == "legacy":
            legacy.append(sym)
    return bad, legacy


def is_macho(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) in MAGICS and not path.endswith(".class")
    except OSError:
        return False


def walk_files(root):
    if os.path.isfile(root):
        yield root
        return
    for d, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            if not os.path.islink(p):
                yield p


def check_symbols(root, deny, log):
    files = [p for p in walk_files(root) if is_macho(p)]

    def one(p):
        r = subprocess.run(["nm", "-m", "-u", p], capture_output=True, text=True)
        return (p,) + symbol_problems(parse_nm(r.stdout), deny)
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 4) as ex:
        scanned = list(ex.map(one, files))
    problems = [(p, b) for p, b, _ in scanned if b]
    for p in walk_files(root):
        if TCL_FILE.match(os.path.basename(p)):
            problems.append((p, ["Tcl/Tk file (nothing uses tkinter; bundle.mjs removes it)"]))
    for p, _, legacy in scanned:
        if legacy:
            log(f"  note: {rel(p, root)} uses the documented legacy BLAS/LAPACK interface ({len(legacy)}: "
                f"{', '.join(legacy[:4])}{', ...' if len(legacy) > 4 else ''})")
    log(f"[symbols] {len(files)} Mach-O files")
    return problems


# ---------------------------------------------------------------------------------------------------------- strings
FORBIDDEN_STRINGS = [b"itms-services"]


def check_strings(root, log):
    problems, n = [], 0
    for p in walk_files(root):
        if not p.endswith((".py", ".pyc")):
            continue
        n += 1
        try:
            with open(p, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        for s in FORBIDDEN_STRINGS:
            if s in data:
                problems.append((p, [f'contains "{s.decode()}" (App Review rejects it; bundle.mjs patches urllib.parse)']))
    log(f"[strings] {n} Python files")
    return problems


# ----------------------------------------------------------------------------------------------------- entitlements
APP_ALLOWED = {
    "com.apple.security.app-sandbox", "com.apple.security.application-groups",
    "com.apple.security.files.user-selected.read-write", "com.apple.security.files.bookmarks.app-scope",
    "com.apple.security.network.client", "com.apple.security.device.camera", "com.apple.security.device.microphone",
    "com.apple.security.device.audio-input", "com.apple.security.cs.allow-jit",
    # added by @electron/osx-sign from the provisioning profile
    "com.apple.application-identifier", "com.apple.developer.team-identifier",
}
CHILD_EXACT = {"com.apple.security.app-sandbox", "com.apple.security.inherit"}
LOGIN_ALLOWED = {"com.apple.security.app-sandbox", "com.apple.security.application-groups",
                 "com.apple.application-identifier", "com.apple.developer.team-identifier"}
NEVER = {"com.apple.security.network.server": "listening sockets (App Review 2.4.5: no matching functionality)"}


def entitlement_problems(ent, role):
    """`ent` (a dict) of an executable in `role` 'app' | 'child' | 'login' -> list of problems."""
    out = []
    if ent.get("com.apple.security.app-sandbox") is not True:
        out.append("not sandboxed (com.apple.security.app-sandbox is not true)")
    for k, why in NEVER.items():
        if k in ent:
            out.append(f"has {k}: {why}")
    if role == "child":
        if set(ent) != CHILD_EXACT or ent.get("com.apple.security.inherit") is not True:
            out.append(f"a nested executable must have exactly app-sandbox + inherit, has {sorted(ent)}")
    else:
        extra = set(ent) - (APP_ALLOWED if role == "app" else LOGIN_ALLOWED) - set(NEVER)
        if extra:
            out.append(f"unexpected entitlements {sorted(extra)} (allow-list in appstore_lint.py)")
    return out


def role_of(path, app):
    """'app' (Contents/MacOS/*), 'login' (the login helper) or 'child' (helpers, the bundled python / ffmpeg)."""
    if os.path.dirname(os.path.abspath(path)) == os.path.join(os.path.abspath(app), "Contents", "MacOS"):
        return "app"
    return "login" if "/Contents/Library/LoginItems/" in path else "child"


def signed_entitlements(path, arch=None):
    cmd = ["codesign", "-d", "--entitlements", "-", "--xml"] + (["--arch", arch] if arch else []) + [path]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        return None, r.stderr.decode(errors="replace").strip()
    xml = r.stdout.strip()
    return (plistlib.loads(xml) if xml else {}), None


def archs(path):
    r = subprocess.run(["lipo", "-archs", path], capture_output=True, text=True)
    return r.stdout.split() if r.returncode == 0 else [None]


def check_signed_entitlements(app, log):
    problems, n = [], 0
    for p in walk_files(app):
        # executables only: libraries (.so / .dylib, frameworks) carry no entitlements
        if not (os.access(p, os.X_OK) and is_macho(p)) or p.endswith((".so", ".dylib")) or ".framework/" in p:
            continue
        n += 1
        role = role_of(p, app)
        for arch in archs(p):
            ent, err = signed_entitlements(p, arch)
            if ent is None:
                problems.append((p, [f"{arch or ''} unsigned or unreadable signature: {err}"]))
                continue
            for msg in entitlement_problems(ent, role):
                problems.append((p, [f"[{arch}] {msg}" if arch else msg]))
    log(f"[entitlements] {n} executables (every architecture slice)")
    return problems


def check_entitlement_files(mac_dir, log):
    roles = {"entitlements.mas.plist": "app", "entitlements.mas.inherit.plist": "child",
             "entitlements.mas.loginhelper.plist": "login"}
    problems = []
    for f, role in roles.items():
        p = os.path.join(mac_dir, f)
        if not os.path.exists(p):
            problems.append((p, ["missing"]))
            continue
        with open(p, "rb") as fh:
            ent = plistlib.load(fh)
        problems += [(p, [m]) for m in entitlement_problems(ent, role)]
    log(f"[entitlements] {len(roles)} entitlement files in {mac_dir} (unsigned build)")
    return problems


# ------------------------------------------------------------------------------------------------------- quarantine
def check_quarantine(root, log):
    if sys.platform != "darwin":
        log("[quarantine] skipped (not macOS)")
        return []
    # BSD find: files carrying the attribute (symlinks too)
    r = subprocess.run(["find", root, "-xattrname", "com.apple.quarantine"], capture_output=True, text=True, errors="replace")
    hits = sorted(line for line in r.stdout.splitlines() if line)
    log(f"[quarantine] {len(hits)} quarantined files")
    return [(h, ["com.apple.quarantine extended attribute (xattr -cr before signing; ITMS-91109)"]) for h in hits]


# ---------------------------------------------------------------------------------------------------------------- main
def rel(p, root):
    try:
        return os.path.relpath(p, root)
    except ValueError:
        return p


def lint(root, unsigned=False, mac_dir=os.path.join(DESK, "packaging", "mac"), checks=None, log=print):
    checks = checks or {"symbols", "strings", "entitlements", "quarantine"}
    deny = load_denylist()
    problems = []
    if "symbols" in checks:
        problems += check_symbols(root, deny, log)
    if "strings" in checks:
        problems += check_strings(root, log)
    if "entitlements" in checks:
        if root.rstrip("/").endswith(".app") and not unsigned:
            problems += check_signed_entitlements(root, log)
        else:
            problems += check_entitlement_files(mac_dir, log)
    if "quarantine" in checks:
        problems += check_quarantine(root, log)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description="App Store lint for the Mac App Store (Lite) build")
    ap.add_argument("path", help="Reelfold.app or a runtime folder")
    ap.add_argument("--unsigned", action="store_true", help="check packaging/mac/entitlements.mas*.plist, not signatures")
    ap.add_argument("--only", default="", help="comma list of checks: symbols,strings,entitlements,quarantine")
    ap.add_argument("--entitlements-dir", default=os.path.join(DESK, "packaging", "mac"))
    a = ap.parse_args(argv)
    if not os.path.exists(a.path):
        print(f"[appstore-lint] no such path: {a.path}")
        return 2
    checks = {c for c in a.only.split(",") if c} or None
    problems = lint(a.path, unsigned=a.unsigned, mac_dir=a.entitlements_dir, checks=checks)
    if not problems:
        print(f"[appstore-lint] {a.path}: clean")
        return 0
    for p, msgs in problems:
        shown = "; ".join(msgs[:6]) + (f"; ... ({len(msgs)} in all)" if len(msgs) > 6 else "")
        print(f"  {rel(p, a.path)}: {shown}")
    print(f"[appstore-lint] {len(problems)} problem(s) in {a.path} - App Review would reject this build")
    return 1


if __name__ == "__main__":
    sys.exit(main())
