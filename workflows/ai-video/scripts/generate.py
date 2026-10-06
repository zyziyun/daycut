#!/usr/bin/env python3
"""Plan, (optionally) submit, collect and import AI video generations for a project file.

    python3 generate.py plan    work/ai/project.yaml                 # DEFAULT: dry run, prompts + estimated credits
    python3 generate.py sheets  work/ai/project.yaml                 # prompt sheets for web UIs (manual provider)
    python3 generate.py prep-refs refs/*.jpg --out refs/upload        # <=1024 px JPEGs (upload limits)
    python3 generate.py run     work/ai/project.yaml --only u04,u13 --budget 300 --yes   # spends credits
    python3 generate.py collect work/ai/project.yaml                 # resume: poll + download pending tasks
    python3 generate.py import  work/ai/project.yaml downloads/u04_*.mp4               # manual downloads
    python3 generate.py status  work/ai/project.yaml

Spending rules (never relaxed by a flag combination):
  - `run` refuses without BOTH --yes and --budget; refuses when the estimate exceeds the budget, when the
    estimate is unknown (unless --allow-unknown-cost, which still needs --budget), and when the provider
    reports a balance lower than the estimate.
  - task ids are written to state.json the moment a submit returns, so a crash never leads to a re-submit.
  - a failed generation is reported, never resubmitted automatically - change the prompt or ask the user.
Run from the project (video) folder; takes land in work/ai/takes/<unit>_vN.mp4.
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plan as PL  # noqa: E402
from providers import ProviderError, get_provider  # noqa: E402


class SpendRefused(RuntimeError):
    pass


def check_spend(estimate, budget, yes, balance=None, allow_unknown=False):
    """Gate before any paid call. Returns the amount authorised; raises SpendRefused otherwise."""
    if not yes:
        raise SpendRefused("dry run: nothing submitted. Re-run with --yes --budget N after the user approved the plan.")
    if budget is None:
        raise SpendRefused("--budget is required (credits you are willing to spend on this run).")
    if estimate is None:
        if not allow_unknown:
            raise SpendRefused("cost estimate unknown for at least one unit - check the price in the provider UI, "
                               "add `rates:` to the project, or pass --allow-unknown-cost.")
    elif estimate > budget:
        raise SpendRefused(f"estimate {estimate:g} credits > budget {budget:g}. Trim units (--only) or raise the budget.")
    if balance is not None and estimate is not None and balance < estimate:
        raise SpendRefused(f"provider balance {balance:g} < estimate {estimate:g}.")
    return budget if estimate is None else estimate


def state_path(cfg):
    return os.path.join(cfg.get("work_dir") or os.path.join(cfg["_dir"]), "state.json")


def load_state(cfg):
    p = state_path(cfg)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"pending": {}, "takes": {}, "spent_estimate": 0.0, "failed": {}}


def save_state(cfg, st):
    p = state_path(cfg)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def takes_dir(cfg):
    d = cfg.get("takes_dir") or os.path.join(cfg["_dir"], "takes")
    os.makedirs(d, exist_ok=True)
    return d


def _select(units, jobs, ests, only):
    if not only:
        return list(zip(units, jobs, ests))
    want = set(only.split(","))
    return [(u, j, e) for u, j, e in zip(units, jobs, ests) if u.id in want]


def run(cfg, only=None, budget=None, yes=False, allow_unknown=False, provider=None, out=print):
    units, jobs, ests, _, warns = PL.build(cfg)
    sel = _select(units, jobs, ests, only)
    est = None if any(e is None for _, _, e in sel) else round(sum(e for _, _, e in sel), 2)
    prov = provider or get_provider(cfg["provider"])
    if prov.name == "manual":
        raise SpendRefused("provider is manual: use `sheets`, generate in the web UI, then `import`.")
    out(PL.format_plan(cfg, [u for u, _, _ in sel], [j for _, j, _ in sel], [e for _, _, e in sel], est, warns,
                       show_prompts=not yes))
    bal = None
    if yes:
        try:
            bal = prov.balance()
        except ProviderError as e:
            out(f"(balance unavailable: {e})")
    check_spend(est, budget, yes, bal, allow_unknown)
    st = load_state(cfg)
    for u, j, e in sel:
        try:
            tid = prov.submit(j)
        except ProviderError as ex:
            out(f"{u.id}: submit failed - {ex}. Not retried; check the provider task list before trying again.")
            st["failed"][u.id] = str(ex)
            save_state(cfg, st)
            continue
        st["pending"][tid] = {"unit": u.id, "provider": prov.name, "est": e, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        st["spent_estimate"] = round(st.get("spent_estimate", 0) + (e or 0), 2)
        save_state(cfg, st)                    # persist before anything else can fail
        out(f"{u.id}: submitted {tid} (~{e if e is not None else '?'} credits)")
    return collect(cfg, provider=prov, out=out)


def collect(cfg, provider=None, out=print, wait=True):
    st = load_state(cfg)
    prov = provider or get_provider(cfg["provider"])
    d = takes_dir(cfg)
    for tid, info in list(st["pending"].items()):
        u = info["unit"]
        try:
            from vstudio.batch.livestatus import heartbeat
            heartbeat("generate", message=f"{u} ({tid})")
        except ImportError:
            pass
        r = prov.wait(tid) if wait else prov.poll(tid)
        if r["status"] == "pending":
            out(f"{u}: still pending ({tid})")
            continue
        if r["status"] == "failed":
            st["failed"][u] = f"task {tid} failed: {str(r.get('raw'))[:200]}"
            out(f"{u}: FAILED - not resubmitted. Rewrite the prompt or pick another set-up, then `run --only {u}`.")
        n0 = len(glob.glob(os.path.join(d, f"{u}_v*.*")))
        for i, url in enumerate(r["urls"]):
            ext = ".png" if any(url.lower().split("?")[0].endswith(x) for x in (".png", ".jpg", ".jpeg", ".webp")) else ".mp4"
            path = os.path.join(d, f"{u}_v{n0 + i + 1}{ext}")
            prov.download(url, path)
            st["takes"].setdefault(u, []).append({"file": os.path.basename(path), "task": tid})
            out(f"{u}: saved {path}")
        del st["pending"][tid]
        save_state(cfg, st)
    return st


def import_files(cfg, files, out=print):
    """Copy manual downloads named <unit>_*.ext into takes/ as <unit>_vN.ext."""
    st = load_state(cfg)
    ids = {u.id for u in PL.compile_units(cfg)}
    d = takes_dir(cfg)
    for f in files:
        base = os.path.basename(f)
        unit = next((i for i in sorted(ids, key=len, reverse=True) if base.startswith(i + "_") or base.startswith(i + ".")), None)
        if not unit:
            out(f"skip {base}: name it <unit>_anything{os.path.splitext(base)[1]} (units: {', '.join(sorted(ids))})")
            continue
        n = len(glob.glob(os.path.join(d, f"{unit}_v*.*"))) + 1
        dst = os.path.join(d, f"{unit}_v{n}{os.path.splitext(base)[1].lower()}")
        shutil.copy2(f, dst)
        st["takes"].setdefault(unit, []).append({"file": os.path.basename(dst), "source": "manual"})
        out(f"{unit}: {base} -> {dst}")
    save_state(cfg, st)
    return st


def write_sheets(cfg, out_dir=None, out=print):
    units, jobs, ests, total, warns = PL.build(cfg)
    prov = get_provider(cfg["provider"] if cfg["provider"].startswith("manual") else "manual")
    out_dir = out_dir or os.path.join(cfg["_dir"], "sheets")
    os.makedirs(out_dir, exist_ok=True)
    body = [PL.format_plan(cfg, units, jobs, ests, total, warns, show_prompts=False), ""]
    body += [prov.sheet(j) for j in jobs]
    path = os.path.join(out_dir, "PROMPTS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    out(f"wrote {path}")
    return path


def prep_refs(files, out_dir, max_edge=1024, quality=90):
    from PIL import Image, ImageOps
    os.makedirs(out_dir, exist_ok=True)
    res = []
    for f in files:
        im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
        im.thumbnail((max_edge, max_edge), Image.LANCZOS)
        dst = os.path.join(out_dir, os.path.splitext(os.path.basename(f))[0] + ".jpg")
        im.save(dst, "JPEG", quality=quality, optimize=True)
        res.append(dst)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n\n", 1)[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "sheets", "run", "collect", "status", "import"):
        s = sub.add_parser(name)
        s.add_argument("project")
        if name == "plan":
            s.add_argument("--no-prompts", action="store_true")
        if name == "run":
            s.add_argument("--only", help="comma list of unit ids (do the hardest shots first)")
            s.add_argument("--budget", type=float, help="max credits for this run (required with --yes)")
            s.add_argument("--yes", action="store_true", help="the user approved this plan and spend")
            s.add_argument("--allow-unknown-cost", action="store_true")
        if name == "import":
            s.add_argument("files", nargs="+")
        if name == "sheets":
            s.add_argument("--out")
    s = sub.add_parser("prep-refs")
    s.add_argument("files", nargs="+")
    s.add_argument("--out", required=True)
    s.add_argument("--max-edge", type=int, default=1024)
    a = ap.parse_args(argv)
    if a.cmd == "prep-refs":
        for p in prep_refs(a.files, a.out, a.max_edge):
            print(p)
        return 0
    cfg = PL.load(a.project)
    if a.cmd == "plan":
        print(PL.format_plan(cfg, *PL.build(cfg), show_prompts=not a.no_prompts))
        print("\nDry run - nothing was submitted.")
    elif a.cmd == "sheets":
        write_sheets(cfg, a.out)
    elif a.cmd == "run":
        try:
            run(cfg, a.only, a.budget, a.yes, a.allow_unknown_cost)
        except SpendRefused as e:
            print(f"\nREFUSED: {e}")
            return 2
    elif a.cmd == "collect":
        collect(cfg)
    elif a.cmd == "import":
        import_files(cfg, a.files)
    elif a.cmd == "status":
        print(json.dumps(load_state(cfg), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
