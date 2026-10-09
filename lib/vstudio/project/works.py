"""Plain work folders made with the skill (no ``project.yaml`` / ``batch.db``): a lightweight record so the desk
app and ``project list`` see every job, not only batches and recipe projects.

    <dir>/.vstudio/work.json     {kind: "work", title, recipe, type, outputs [rel paths], covers, posts, notes,
                                  sources [abs paths], created, updated}
    $VSTUDIO_HOME/projects.json  the same registry as projects (row ``kind: "work"``)

    python -m vstudio.project adopt <dir> [--recipe guess|NAME] [--title T] --json   # existing folder -> record
    from vstudio.project import works; works.touch(dir, recipe, title, outputs)    # workflows: at the end of a job

Nothing in the folder except ``.vstudio/work.json`` is written; outputs are listed, never moved or deleted.
"""
import os
import re
import time

from vstudio.batch.util import read_json, write_json
from ..oscompat import relpath as _relpath

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
OUT_DIRS = ("final", "exports", "export", "out", "output", "delivery")
NOTE_FILES = ("REPORT.md", "PICKS.md", "NOTES.md", "SEGMENTS.md", "BRIEF.md", "SCRIPT.md")
SRC_DIRS = ("raw", "src", "footage", "recordings", "photos", "source", "sources", "input", "inputs")
# skill workflow types (desk filter keys) -> the recipe manifest id when one exists
TYPES = {"talkinghead": "talkinghead", "slices": "longform-to-short", "explainer": "explainer",
         "photo-story": "photo-story", "vlog": "vlog", "podcast": "call-clips", "aigc": "ai-video",
         "script": "preproduction", "batch": "batch", "promo": "promo-recut", "slides": "slides", "other": None}
_GUESS = [  # (type, name / report keywords)
    ("talkinghead", r"talking.?head|口播|精剪"),
    ("slices", r"lecture|slice|切片|分集|course|课程|longform"),
    ("podcast", r"podcast|播客|call|interview|访谈|clip"),
    ("explainer", r"explainer|讲解|3b1b|manim|hyperframes"),
    ("photo-story", r"story|photo|文艺|照片"),
    ("vlog", r"vlog|travel|旅行|disney"),
    ("aigc", r"aigc|ai.?video|kling|seedance|veo"),
    ("promo", r"promo|宣传|recut|launch"),
    ("slides", r"slides|deck|幻灯"),
    ("script", r"script|脚本|口播稿"),
]


def record_path(d):
    return os.path.join(d, ".vstudio", "work.json")


def is_work(d):
    return os.path.exists(record_path(d))


def _rel_files(d, sub, exts, limit=200):
    root = os.path.join(d, sub) if sub else d
    out = []
    if not os.path.isdir(root):
        return out
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in dns if not x.startswith(".")]
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() in exts and not fn.startswith("."):
                out.append(_relpath(os.path.join(dp, fn), d))
                if len(out) >= limit:
                    return out
        if dp.count(os.sep) - root.count(os.sep) >= 2:
            dns[:] = []
    return out


def scan(d):
    """What a work folder holds: outputs (videos), covers, post copy, notes, sources, contact sheet."""
    d = os.path.abspath(d)
    outs, covers, posts = [], [], []
    for sub in OUT_DIRS:
        outs += _rel_files(d, sub, VIDEO)
        covers += [p for p in _rel_files(d, sub, IMAGE) if re.search(r"cover|封面", os.path.basename(p), re.I)]
        posts += _rel_files(d, sub, {".md"}) if os.path.isdir(os.path.join(d, sub)) else []
    posts = [p for p in posts if re.search(r"post|文案|发布", os.path.basename(p), re.I)]
    if os.path.exists(os.path.join(d, "post.md")):
        posts.insert(0, "post.md")
    sheets = [p for p in (_rel_files(d, "", IMAGE, 50) + _rel_files(d, "final", IMAGE))
              if re.search(r"contact_sheet|^sheet\.", os.path.basename(p))]
    notes = [n for n in NOTE_FILES if os.path.exists(os.path.join(d, n))]
    sources = []
    for sub in SRC_DIRS:
        sources += [os.path.normpath(os.path.join(d, p))
                    for p in _rel_files(d, sub, VIDEO | {".wav", ".mp3", ".m4a"} | IMAGE, 50)]
    return dict(outputs=outs, covers=covers, posts=posts, sheets=sheets, notes=notes, sources=sources[:50])


def looks_like_work(d):
    """A folder the skill worked in: final/ exports, a REPORT / PICKS / NOTES, post copy, a contact sheet, or a
    work/ folder with skill scripts or media."""
    if not os.path.isdir(d) or os.path.exists(os.path.join(d, "batch.db")) or \
            os.path.exists(os.path.join(d, "project.yaml")):
        return False
    if is_work(d) or any(os.path.exists(os.path.join(d, n)) for n in NOTE_FILES + ("post.md",)):
        return True
    if any(os.path.isdir(os.path.join(d, s)) and _rel_files(d, s, VIDEO, 1) for s in OUT_DIRS):
        return True
    if any(os.path.exists(os.path.join(d, n)) for n in ("contact_sheet.jpg", "sheet.jpg")):
        return True
    w = os.path.join(d, "work")
    if os.path.isdir(w):
        try:
            names = os.listdir(w)
        except OSError:
            return False
        return any(n.endswith((".py", ".asr.json", ".wav", ".mp4")) for n in names)
    return False


def guess_type(d, files=None):
    """-> one of TYPES (desk filter key)."""
    d = os.path.abspath(d)
    if os.path.exists(os.path.join(d, "batch.db")):
        return "batch"
    text = os.path.basename(d).lower()
    rp = os.path.join(d, "REPORT.md")
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                text += " " + f.readline().lower()
        except OSError:
            pass
    for t, pat in _GUESS:
        if re.search(pat, text, re.I):
            return t
    has = lambda *p: any(os.path.exists(os.path.join(d, x)) for x in p)  # noqa: E731
    if has("project/hyperframes.json", "hyperframes.json", "project/compositions"):
        return "explainer"
    if has("clips.json", "recordings"):
        return "podcast"
    if has("footage") and has("music"):
        return "vlog"
    if has("photos"):
        return "photo-story"
    if has("SCRIPT.md") and not (files or scan(d))["outputs"]:
        return "script"
    if os.path.isdir(os.path.join(d, "work", "clips")):
        return "slices"
    return "other"


def _title(d):
    rp = os.path.join(d, "REPORT.md")
    if os.path.exists(rp):
        try:
            with open(rp, encoding="utf-8") as f:
                ln = f.readline().strip().lstrip("# ").strip()
            if ln and not re.search(r"\breport\b", ln, re.I):        # "02-x — REPORT" -> the folder name
                return ln[:120]
        except OSError:
            pass
    return os.path.basename(d.rstrip(os.sep))


def is_project(d):
    """``d`` is a recipe project: it holds ``project.yaml`` or is registered as one (a projects.json row whose
    ``kind`` is not ``work``). Such a folder never gets a work record."""
    from . import home as H
    d = os.path.abspath(d)
    if os.path.exists(os.path.join(d, "project.yaml")):
        return True
    real = os.path.realpath(d)
    return any(os.path.realpath(p["dir"]) == real and p.get("kind") != "work" for p in H.projects())


def touch(d, recipe=None, title=None, outputs=None, client=None, sources=None, register=True, status=None,
          stage=None, progress=None, message=None, eta=None, needs_you=None):
    """Create / update the work record of folder ``d`` (+ register it) and, with ``status`` (running | waiting |
    done | failed), its live status (``.vstudio/status.json``, heartbeat = now; see vstudio.batch.livestatus).
    ``outputs``: paths (abs or relative to ``d``); default = the videos found in final/ exports/ out/. Call it at
    the start (status="running"), from long steps (stage / progress / message / eta) and at the end (status="done").

    A recipe project folder (``is_project``: project.yaml, or registered as a project) only gets its live status:
    its registry row is left as it is and no ``.vstudio/work.json`` is written (turning it into a ``work`` row
    made the desk drop the project)."""
    from vstudio.batch import livestatus as LS

    from . import home as H
    d = os.path.abspath(d)
    if os.path.isdir(d) and is_project(d):
        live = None
        if status:
            live = LS.write(d, status, stage=stage, progress=progress, message=message, eta=eta,
                            needs_you=needs_you, by="workflow")
        return dict(ok=True, dir=d, kind="project", record=None, status=live)
    os.makedirs(d, exist_ok=True)
    old = read_json(record_path(d), {}) or {}
    live = None
    if status:
        live = LS.write(d, status, stage=stage, progress=progress, message=message, eta=eta, needs_you=needs_you,
                        by="workflow")
    quick = old and status == "running" and not (recipe or title or outputs or client or sources)
    if quick:                                       # a heartbeat: the record exists, nothing else changed
        return dict(ok=True, dir=d, record=record_path(d), status=live, **old)
    found = scan(d)
    typ = guess_type(d, found)
    if recipe and recipe != "guess":
        rec_type = next((k for k, v in TYPES.items() if v == recipe or k == recipe), None)
        typ = rec_type or typ
        recipe_id = TYPES.get(recipe, recipe) if recipe in TYPES else recipe
    else:
        recipe_id = old.get("recipe") or TYPES.get(typ)
    outs = [_relpath(os.path.abspath(os.path.join(d, p)), d) for p in outputs] if outputs else found["outputs"]
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec = dict(old, kind="work", title=title or old.get("title") or _title(d), recipe=recipe_id, type=typ,
               outputs=outs, covers=found["covers"], posts=found["posts"], sheets=found["sheets"],
               notes=found["notes"], sources=list(sources or old.get("sources") or found["sources"]),
               client=client or old.get("client"), created=old.get("created") or now, updated=now)
    write_json(record_path(d), rec)
    if register:
        H.register(d, rec["title"], recipe_id, None, rec["client"], kind="work")
    return dict(ok=True, dir=d, record=record_path(d), status=live, **rec)


def adopt(d, recipe="guess", title=None, client=None):
    """An existing folder made with the skill -> a work record + registry entry (nothing else is written)."""
    d = os.path.abspath(d)
    if not os.path.isdir(d):
        raise FileNotFoundError(f"no folder {d}")
    if is_project(d):
        raise ValueError(f"{d} is already a project (project.yaml / registered as a project)")
    return touch(d, recipe=recipe, title=title, client=client)


def show(d):
    rec = read_json(record_path(d), None)
    return dict(rec, dir=os.path.abspath(d)) if isinstance(rec, dict) else None
