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


SKELETON_MARK = "(you-statement -> surprising claim -> anchoring number)"


def is_skeleton(path):
    try:
        with open(path, encoding="utf-8") as f:
            return SKELETON_MARK in f.read()
    except OSError:
        return False


def draft(env):
    """SCRIPT.md: her own script when she gave one, else the AI writes it from the topic and her request
    (``drafts.generic``: hook / body / insight / close, in her language); with no model the skeleton, which the
    lock never takes for a script (no default: the Inbox asks her)."""
    path = env.item_path("SCRIPT.md")
    if not os.path.exists(path) or is_skeleton(path):
        src = (env.params.get("_inputs") or {}).get("script")
        src = src[0] if isinstance(src, list) else src
        if src and os.path.exists(src):
            shutil.copy(src, path)
        else:
            topic = (env.params.get("_inputs") or {}).get("topic") or env.params.get("title") or env.job
            topic = topic[0] if isinstance(topic, list) and topic else topic
            from .. import drafts as DR
            rec = None
            try:
                rec = draft_script(DR.Ctx.of_env(env), dict(id="lock"), path)
            except Exception as e:  # noqa: BLE001  (no model / a failed call: the skeleton, her Inbox asks)
                env.log(f"script draft: {e}")
            if rec:
                DR.write_side(path, "lock", rec)
            elif not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(SKELETON.format(title=topic))
    return dict(script=path, files=[path], digest=file_sha(path))


def draft_script(ctx, cp, path, template=None, instruction=None, complete=None):
    """The AI writes SCRIPT.md for the topic (and her request / her instruction) in the skeleton's shape."""
    from .. import drafts as DR
    topic = ctx.inputs.get("topic") or ctx.params.get("title") or ctx.item
    topic = topic[0] if isinstance(topic, list) and topic else topic
    c = dict(cp, labels=dict(en="Spoken script"), author=dict(file=path, format="spoken script, Markdown with ## HOOK "
             "/ ## BODY / ## INSIGHT / ## CLOSE, each an indented block of what she says"),
             help=dict(en=f"A short-video script she reads to camera about: {topic}"))
    return DR.generic(ctx, c, path, instruction=instruction, complete=complete,
                      template_text=SKELETON.format(title=topic))


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
    from .. import drafts as DR
    skeleton = SKELETON_MARK in text                    # never locked as if it were her script
    side = DR.read_side(script, "lock")
    st = "template" if skeleton else ("drafted" if side and side.get("sha") == DR.sha(script) else "hers")
    return dict(options=[dict(file=script, sha=file_sha(script))], digest=file_sha(script), file=script,
                content=None if skeleton else text, lint=rep, blocked=blocked, draft_state=st,
                draft_by=(side or {}).get("by") if st == "drafted" else None,
                review=None if skeleton else DR.outline_review(script, side if st == "drafted" else None),
                default=dict(lock=True) if not rep.get("errors") and not skeleton else None,
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
