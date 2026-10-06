"""Plain work folders made with the video-studio skill (no batch.db / project.yaml): final/ exports, REPORT.md,
PICKS.md, NOTES.md, post.md, contact sheets, a work/ folder of skill scripts. Mirrors
``vstudio.project.works`` (the engine's own module is preferred when importable); used for discovery, the work
detail page, and ``adopt`` in mock mode / with an older engine. Read-only except ``adopt`` (``.vstudio/work.json``).
"""
import os
import re
import time

from .common import read_json, write_json

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
IMAGE = {".jpg", ".jpeg", ".png", ".webp"}
OUT_DIRS = ("final", "exports", "export", "out", "output", "delivery")
NOTE_FILES = ("REPORT.md", "PICKS.md", "NOTES.md", "SEGMENTS.md", "BRIEF.md", "SCRIPT.md")
SRC_DIRS = ("raw", "src", "footage", "recordings", "photos", "source", "sources", "input", "inputs")
TYPES = {"talkinghead": "talkinghead", "slices": "longform-to-short", "explainer": "explainer",
         "photo-story": "photo-story", "vlog": "vlog", "podcast": "call-clips", "aigc": "ai-video",
         "script": "preproduction", "batch": "batch", "promo": "promo-recut", "slides": "slides", "other": None}
_GUESS = [
    ("talkinghead", r"talking.?head|口播|精剪"),
    ("slices", r"lecture|slice|切片|分集|course|课程|longform"),
    ("podcast", r"podcast|播客|call|interview|访谈|clip"),
    ("explainer", r"explainer|讲解|3b1b|manim|hyperframes"),
    ("photo-story", r"story|photo|文艺|照片"),
    ("vlog", r"vlog|travel|旅行|disney"),
    ("aigc", r"aigc|ai.?video|kling|seedance|veo"),
    ("promo", r"promo|宣传|recut"),
    ("slides", r"slides|deck|幻灯"),
    ("script", r"script|脚本|口播稿"),
]


def recipe_type(recipe):
    """A batch / project recipe name -> the desk type key."""
    r = (recipe or "").lower()
    if r.startswith("project:"):
        r = r.split(":", 1)[1].split("@")[0]
    for t, rid in TYPES.items():
        if rid and (r == rid or r.startswith(rid)):
            return t
    if "split" in r or "longform" in r or "slice" in r:
        return "slices"
    if "talkinghead" in r:
        return "talkinghead"
    if "podcast" in r or "call" in r:
        return "podcast"
    return "other"


def record_path(d):
    return os.path.join(d, ".vstudio", "work.json")


def _files(d, sub, exts, limit=200):
    root = os.path.join(d, sub) if sub else d
    out = []
    if not os.path.isdir(root):
        return out
    base = root.count(os.sep)
    for dp, dns, fns in os.walk(root):
        dns[:] = [x for x in sorted(dns) if not x.startswith(".")]
        for fn in sorted(fns):
            if os.path.splitext(fn)[1].lower() in exts and not fn.startswith("."):
                out.append(os.path.relpath(os.path.join(dp, fn), d))
                if len(out) >= limit:
                    return out
        if not sub or dp.count(os.sep) - base >= 2:
            dns[:] = []
    return out


def scan(d):
    outs, covers, posts = [], [], []
    for sub in OUT_DIRS:
        if not os.path.isdir(os.path.join(d, sub)):
            continue
        outs += _files(d, sub, VIDEO)
        covers += [p for p in _files(d, sub, IMAGE) if re.search(r"cover|封面", os.path.basename(p), re.I)]
        posts += [p for p in _files(d, sub, {".md"}) if re.search(r"post|文案|发布", os.path.basename(p), re.I)]
    if os.path.exists(os.path.join(d, "post.md")):
        posts.insert(0, "post.md")
    sheets = [p for p in _files(d, "", IMAGE, 50) + _files(d, "final", IMAGE)
              if re.search(r"contact_sheet|^sheet\.", os.path.basename(p))]
    notes = [n for n in NOTE_FILES if os.path.exists(os.path.join(d, n))]
    sources = []
    for sub in SRC_DIRS:
        sources += [os.path.join(d, p) for p in _files(d, sub, VIDEO | {".wav", ".mp3", ".m4a"} | IMAGE, 50)]
    return dict(outputs=outs, covers=covers, posts=posts, sheets=sheets, notes=notes, sources=sources[:50])


def looks_like_work(d):
    if not os.path.isdir(d) or os.path.exists(os.path.join(d, "batch.db")) or \
            os.path.exists(os.path.join(d, "project.yaml")):
        return False
    if os.path.exists(record_path(d)) or any(os.path.exists(os.path.join(d, n)) for n in NOTE_FILES + ("post.md",)):
        return True
    if any(os.path.isdir(os.path.join(d, s)) and _files(d, s, VIDEO, 1) for s in OUT_DIRS):
        return True
    if any(os.path.exists(os.path.join(d, n)) for n in ("contact_sheet.jpg", "sheet.jpg")):
        return True
    w = os.path.join(d, "work")
    if os.path.isdir(w):
        try:
            return any(n.endswith((".py", ".asr.json", ".wav", ".mp4")) for n in os.listdir(w))
        except OSError:
            return False
    return False


def guess_type(d, found=None):
    text = os.path.basename(d.rstrip(os.sep)).lower()
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
    if has("SCRIPT.md") and not (found or scan(d))["outputs"]:
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


def summarize(d):
    rec = read_json(record_path(d), None)
    rec = rec if isinstance(rec, dict) else None
    found = scan(d)
    typ = (rec or {}).get("type") or guess_type(d, found)
    newest = 0.0
    for p in found["outputs"] + found["notes"] + found["posts"]:
        try:
            newest = max(newest, os.path.getmtime(os.path.join(d, p)))
        except OSError:
            pass
    try:
        newest = newest or os.path.getmtime(d)
        created = os.stat(d).st_birthtime if hasattr(os.stat(d), "st_birthtime") else None
    except OSError:
        created = None
    thumb = next((os.path.join(d, p) for p in found["sheets"] + found["covers"]), None)
    return dict(name=(rec or {}).get("title") or _title(d), recipe=(rec or {}).get("recipe") or TYPES.get(typ),
                client=(rec or {}).get("client"), type=typ, created=created, updated=newest or None,
                counts=dict(total=len(found["outputs"]), green=0, red=0, approved=0, done=len(found["outputs"]),
                            failed=0),
                status="adopted" if rec else ("done" if found["outputs"] else "in-progress"), thumb=thumb,
                deliveries=0, adopted=bool(rec))


def detail(d, max_text=40000):
    """Everything the work page shows: outputs (videos), covers, sheets, post copy and notes (text)."""
    found = scan(d)
    rec = read_json(record_path(d), None)
    if isinstance(rec, dict) and rec.get("outputs"):
        found["outputs"] = [p for p in rec["outputs"] if os.path.exists(os.path.join(d, p))] or found["outputs"]

    def text(rel):
        try:
            with open(os.path.join(d, rel), encoding="utf-8", errors="replace") as f:
                return f.read(max_text)
        except OSError:
            return ""
    return dict(outputs=[os.path.join(d, p) for p in found["outputs"]],
                covers=[os.path.join(d, p) for p in found["covers"]],
                sheets=[os.path.join(d, p) for p in found["sheets"]],
                posts=[dict(path=os.path.join(d, p), text=text(p)) for p in found["posts"][:10]],
                notes=[dict(path=os.path.join(d, p), text=text(p)) for p in found["notes"]],
                sources=found["sources"], record=rec if isinstance(rec, dict) else None)


def adopt(d, recipe="guess", title=None, client=None, home=None):
    """Desk fallback of ``vstudio.project adopt`` (mock mode / older engine): same record + registry row."""
    try:
        from vstudio.project import works as W
        if hasattr(W, "adopt"):
            return W.adopt(d, recipe=recipe, title=title, client=client)
    except ImportError:
        pass
    d = os.path.abspath(d)
    found = scan(d)
    typ = guess_type(d, found) if recipe in (None, "guess") else recipe
    old = read_json(record_path(d), {}) or {}
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec = dict(old, kind="work", title=title or old.get("title") or _title(d), recipe=TYPES.get(typ, typ), type=typ,
               outputs=found["outputs"], covers=found["covers"], posts=found["posts"], sheets=found["sheets"],
               notes=found["notes"], sources=found["sources"], client=client or old.get("client"),
               created=old.get("created") or now, updated=now)
    write_json(record_path(d), rec)
    if home:
        reg = os.path.join(home, "projects.json")
        rows = [r for r in read_json(reg, []) or [] if isinstance(r, dict) and os.path.abspath(r.get("dir") or "") != d]
        rows.append(dict(dir=d, name=rec["title"], recipe=rec["recipe"], series=None, client=rec["client"],
                         created=now, kind="work"))
        write_json(reg, rows)
    return dict(ok=True, dir=d, record=record_path(d), **rec)
