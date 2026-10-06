"""preproduction: seed SCRIPT.md, lint it with workflows/preproduction/scripts/lint_script.py (unchanged, parsed
from its stdout), lock checkpoint (digest = the script's hash: an edit after the lock asks again)."""
import os
import re
import shutil

from vstudio.batch.util import read_json, write_json

from ..build import file_sha

SKELETON = """# {title}

## HOOK
    (you-statement -> surprising claim -> anchoring number)

## BODY
    (spoken prose; one idea per paragraph)

## INSIGHT
    (the one signposted reframe)

## CLOSE
    (pattern A/B/C/D; last line screenshot-worthy)
"""


def draft(env):
    path = env.item_path("SCRIPT.md")
    if not os.path.exists(path):
        src = (env.params.get("_inputs") or {}).get("script")
        src = src[0] if isinstance(src, list) else src
        if src and os.path.exists(src):
            shutil.copy(src, path)
        else:
            topic = (env.params.get("_inputs") or {}).get("topic") or env.params.get("title") or env.job
            with open(path, "w", encoding="utf-8") as f:
                f.write(SKELETON.format(title=topic))
    return dict(script=path, files=[path], digest=file_sha(path))


_STATS = re.compile(r"^(?P<n>\d+) (?P<unit>words|字) ≈ (?P<secs>\d+)s")


def parse_lint(stdout):
    errs, warns, stats, notes = [], [], {}, []
    for ln in (stdout or "").splitlines():
        if ln.startswith("ERROR "):
            errs.append(ln[6:].strip())
        elif ln.startswith("warn  "):
            warns.append(ln[6:].strip())
        elif ln.startswith("note:"):
            notes.append(ln[5:].strip())
        else:
            mo = _STATS.match(ln.strip())
            if mo:
                stats = dict(count=int(mo["n"]), unit=mo["unit"], seconds=int(mo["secs"]), line=ln.strip())
    return dict(errors=errs, warnings=warns, stats=stats, notes=notes, clean=not errs and not warns)


def lint(env):
    script = env.inputs["draft"]["script"]
    p = env.params
    argv = [env.fmt("{python}"), os.path.join(env.workflow_dir, "scripts", "lint_script.py"), script,
            "--lang", p.get("lang") or "auto"]
    plats = p.get("platforms") or []
    if plats:
        argv += ["--platform", plats[0]]
    elif p.get("format"):
        argv += ["--format", p["format"]]
    r = env.run(argv, log="lint.log")
    res = dict(parse_lint(r.stdout), script=script, platform=plats[0] if plats else None, sha=file_sha(script))
    path = write_json(env.item_path("lint.json"), res)
    write_json(env.path("lint.json"), res)
    return dict(report=path, errors=len(res["errors"]), warnings=len(res["warnings"]), files=[path],
                digest=res["sha"])


def lock_payload(env, cp):
    out = env.inputs.get("lint") or {}
    rep = read_json(out.get("report"), {}) or {}
    script = rep.get("script") or env.item_path("SCRIPT.md")
    with open(script, encoding="utf-8") as f:
        text = f.read()
    blocked = bool(env.params.get("strict")) and bool(rep.get("errors"))
    return dict(options=[dict(file=script, sha=file_sha(script))], digest=file_sha(script), file=script,
                content=text, lint=rep, blocked=blocked,
                default=dict(lock=True) if not rep.get("errors") else None,
                previews=[dict(kind="markdown", path=script), dict(kind="json", path=out.get("report"))])


def lock_apply(a):
    v = a.value or {}
    script = a.payload.get("file") or os.path.join(a.params.get("_item_dir") or "", "SCRIPT.md")
    if v.get("content") is not None:
        with open(script, "w", encoding="utf-8") as f:
            f.write(v["content"])
    if not v.get("lock"):
        return dict(params={}, digest="unlocked")
    if a.payload.get("blocked") and v.get("content") is None:
        raise ValueError("lock refused: lint errors with strict on - fix the script first")
    return dict(params={}, digest=file_sha(script))
