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
    ("promo", r"promo|宣传|recut|launch"),
    ("slides", r"slides|deck|幻灯"),
    ("script", r"script|脚本|口播稿"),
]


def recipe_type(recipe):
    """A batch / project recipe name -> the desk type key."""
    r = (recipe or "").lower()
    if r.startswith("project:"):
        r = r.split(":", 1)[1].split("@")[0]
    if r.startswith("launch-kit"):                  # a product launch kit is filed with the promos
        return "promo"
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
    final_videos = any(_files(d, s_, VIDEO, 1) for s_ in ("final", "exports", "export"))
    for sub in OUT_DIRS:
        if not os.path.isdir(os.path.join(d, sub)):
            continue
        if final_videos and sub in ("out", "output"):          # intermediate renders when a final/ exists
            covers += [p for p in _files(d, sub, IMAGE) if re.search(r"cover|封面", os.path.basename(p), re.I)]
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
                status="done" if found["outputs"] else "in-progress", thumb=thumb,
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


# ------------------------------------------------------------------ clips: one card per output (not per file)
ASPECT_SUFFIX = re.compile(r"(?:[_.-](?:9x16|916|3x4|34|16x9|169|1x1|vertical|horizontal|full|portrait|landscape))+$", re.I)
CLIP_ID_RE = re.compile(r"^[\w一-鿿][\w一-鿿 .()+-]{0,119}$")


PLATFORM_SUFFIX = re.compile(r"[_.-](xiaohongshu|xhs|rednote|douyin|tiktok|youtube[_-]?shorts|shorts|bilibili|youtube|"
                             r"shipinhao|channels|instagram|reels)$", re.I)
DIMS_SUFFIX = re.compile(r"[_.-]\d{3,4}x\d{3,4}$", re.I)
COVER_SUFFIX = re.compile(r"[_.-]?(cover|封面)(\.feed)?$", re.I)


PLATFORM_ONLY = re.compile(r"^(xiaohongshu|xhs|rednote|douyin|tiktok|youtube([_-]?shorts)?|shorts|bilibili|shipinhao|"
                           r"channels|instagram|reels|final|output|export|cover)$", re.I)
MAIN_KEY = "main"


def clip_key(rel):
    """``final/A_换圈子_9x16.mp4`` -> ``A_换圈子``; ``ep1_xiaohongshu_3x4`` / ``ep1_cover_9x16`` -> ``ep1``: the
    versions (aspect, platform, size) and the cover of one clip share a key."""
    stem = os.path.splitext(os.path.basename(rel))[0]
    for _ in range(4):
        before = stem
        for rx in (ASPECT_SUFFIX, DIMS_SUFFIX, COVER_SUFFIX, PLATFORM_SUFFIX):
            stem = rx.sub("", stem) or stem
        if stem == before:
            break
    if PLATFORM_ONLY.match(stem):                       # douyin.mp4 / xhs_3x4.mp4: versions of the folder's clip
        return MAIN_KEY
    return stem


def aspect_of(w, h):
    if not w or not h:
        return None
    r = w / h
    for name, v in (("9:16", 9 / 16), ("3:4", 3 / 4), ("1:1", 1.0), ("4:3", 4 / 3), ("16:9", 16 / 9)):
        if abs(r - v) < 0.04:
            return name
    return f"{w}:{h}"


def aspect_from_name(rel):
    n = os.path.basename(rel).lower()
    if re.search(r"9x16|916|vertical|full|portrait", n):
        return "9:16" if "xiaohongshu-vertical" not in n else "3:4"
    if re.search(r"3x4|34\b", n):
        return "3:4"
    if re.search(r"16x9|169|horizontal|landscape", n):
        return "16:9"
    return None


def parse_posts(text):
    """post.md with ``## <file> · 封面 <cover>`` sections -> {clip key: {title, body, tags, file, cover}}."""
    out = {}
    parts = re.split(r"^##\s+", text or "", flags=re.M)
    for part in parts[1:]:
        head, _, rest = part.partition("\n")
        m = re.match(r"\s*([^\s·|]+\.(?:mp4|mov|m4v))", head)
        if not m:
            continue
        cover = re.search(r"([^\s·|]+\.(?:jpg|jpeg|png|webp))", head)
        lines = [ln.rstrip() for ln in rest.strip().splitlines()]
        title = next((ln.strip() for ln in lines if ln.strip()), "")
        tags = []
        body = []
        for ln in lines[1:]:
            if re.fullmatch(r"\s*(#\S+\s*)+", ln or "x"):
                tags += [t.lstrip("#") for t in ln.split()]
            else:
                body.append(ln)
        out[clip_key(m.group(1))] = dict(title=title, body="\n".join(body).strip(), tags=tags, file=m.group(1),
                                         cover=cover.group(1) if cover else None)
    return out


COUNT_NOTE = re.compile(r"\s*[(（][^()（）]*\d+(?:\.\d+)?\s*/\s*\d+[)）]\s*$")


def parse_post_single(text):
    """A per-clip post file -> {title, body, tags}. Understands ``**标题**：…`` / ``## 标题`` + next line,
    ``**正文**：`` / ``## 正文`` sections, #tag lines, and drops length notes like ``(15.0/20)``."""
    title, body, tags = None, [], []
    mode = None
    for ln in (text or "").splitlines():
        s_ = ln.strip()
        m = re.match(r"^\*\*(标题|title)\*\*\s*[:：]\s*(.*)$", s_, re.I)
        if m:
            title = COUNT_NOTE.sub("", m.group(2)).strip() or title
            mode = "title" if not m.group(2).strip() else None
            continue
        m = re.match(r"^\*\*(正文|body)\*\*\s*[:：]\s*(.*)$", s_, re.I)
        if m:
            mode = "body"
            if m.group(2).strip():
                body.append(m.group(2))
            continue
        m = re.match(r"^#{1,6}\s*(.*)$", s_)
        if m and not re.fullmatch(r"(#\S+\s*)+", s_):
            h = m.group(1)
            mode = "title" if re.match(r"^(标题|title)", h, re.I) else "body" if re.match(r"^(正文|body|文案)", h, re.I) \
                else ("skip" if mode else None)
            continue
        if re.match(r"^(视频|封面|video|cover|备选|alternatives?)\s*[:：]", s_, re.I):
            continue
        if s_ and re.fullmatch(r"(#\S+\s*)+", s_):
            tags += [x.lstrip("#") for x in s_.split()]
            continue
        if mode == "skip":
            continue
        if mode == "title" and s_:
            title = COUNT_NOTE.sub("", s_).strip()
            mode = None
            continue
        if title is None and s_ and mode != "body":
            title = COUNT_NOTE.sub("", s_).strip()
            continue
        body.append(ln)
    return dict(title=title or "", body="\n".join(body).strip(), tags=tags)


def parse_picks(text):
    """PICKS.md: the pick table (id -> title) and the 'creator should confirm' bullets (id -> [text])."""
    titles, confirm = {}, []
    for ln in (text or "").splitlines():
        m = re.match(r"^\|\s*([A-Z0-9]{1,3})\b[^|]*\|[^|]*\|[^|]*\|\s*([^|]+?)\s*\|", ln)
        if m and not set(m.group(2)) <= set("-: "):
            titles[m.group(1)] = re.sub(r"\s*\(\d+\)\s*$", "", m.group(2)).strip()
    sec = re.search(r"^##[^\n]*(creator should confirm|需要你确认|请确认)[^\n]*\n(.*?)(?=^##\s|\Z)", text or "",
                    flags=re.M | re.S | re.I)
    if sec:
        for ln in sec.group(2).splitlines():
            m = re.match(r"^\s*[-*]\s+(?:\*\*([A-Z0-9]{1,3})\*\*\s*)?(.+)$", ln)
            if m and not re.match(r"^\s*skipped\b", m.group(2), re.I):
                confirm.append(dict(clip=m.group(1), text=m.group(2).strip()))
    return dict(titles=titles, confirm=confirm)


def _mtime(p):
    try:
        return os.path.getmtime(p)
    except OSError:
        return 0.0


def _clip_state(cdir):
    """work/clips/<X>/: done (an export exists) | running (a log written in the last 10 min) | queued."""
    exp = [p for sub in ("exports", "exports916", "out", "final") for p in _files(cdir, sub, VIDEO)]
    newest = 0.0
    for dp, _dns, fns in os.walk(cdir):
        for fn in fns:
            if fn.endswith((".log", ".mov", ".mp4", ".json")):
                try:
                    newest = max(newest, os.path.getmtime(os.path.join(dp, fn)))
                except OSError:
                    pass
        break
    if exp:
        return "done", [os.path.join(cdir, p) for p in exp]
    if newest and time.time() - newest < 600:
        return "running", []
    return "queued", []


def clips(d, probe=None):
    """Every output of a plain work folder as one clip: versions (aspect), cover, post copy, in-progress clips from
    ``work/clips/*`` (B2). -> [{id, title, state, files [{path, aspect, w, h}], cover, post, duration, source}]"""
    found = scan(d)
    posts = {}
    unsectioned = None
    mt = lambda rel: _mtime(os.path.join(d, rel))  # noqa: E731
    for rel in sorted(found["posts"], key=mt):            # newer files win (final/v2 over final/)
        try:
            with open(os.path.join(d, rel), encoding="utf-8", errors="replace") as f:
                text = f.read(200000)
        except OSError:
            continue
        sections = parse_posts(text)
        if sections:
            posts.update(sections)
        elif re.match(r"^(post|文案|发布)", os.path.basename(rel), re.I):
            unsectioned = parse_post_single(text)
        elif re.search(r"[_-](post|文案)$", os.path.splitext(os.path.basename(rel))[0], re.I):
            key = clip_key(re.sub(r"[_-](post|文案)$", "", os.path.splitext(os.path.basename(rel))[0], flags=re.I) + ".mp4")
            posts[key] = dict(parse_post_single(text), file=None, cover=None)
    picks = {}
    if os.path.exists(os.path.join(d, "PICKS.md")):
        try:
            with open(os.path.join(d, "PICKS.md"), encoding="utf-8", errors="replace") as f:
                picks = parse_picks(f.read(200000))["titles"]
        except OSError:
            pass
    groups = {}
    for rel in found["outputs"]:
        groups.setdefault(clip_key(rel), []).append(rel)
    others = [k for k in groups if k != MAIN_KEY]
    if MAIN_KEY in groups and len(others) == 1:          # cuda-explainer.mp4 + douyin.mp4 + youtube.mp4 = one clip
        groups[others[0]] += groups.pop(MAIN_KEY)
    covers = {}
    for rel in sorted(found["covers"], key=mt):
        covers[clip_key(rel)] = rel
    keys = list(groups)
    if unsectioned and len(groups) == 1 and not posts:      # one clip + one plain post.md: they belong together
        posts[keys[0]] = dict(unsectioned, file=None, cover=None)
    if posts:                                   # post.md names the real clips; other files are extras
        keys = [k for k in posts if k in groups] + [k for k in groups if k not in posts]
    out = []
    for k in keys:
        files = []
        for rel in sorted(groups[k], key=lambda r: (-mt(r), len(r), r)):
            p = os.path.join(d, rel)
            info = (probe or (lambda _p: {}))(p) or {}
            asp = aspect_of(info.get("w"), info.get("h")) or aspect_from_name(rel) or "原尺寸"
            if any(f["aspect"] == asp for f in files):
                continue
            files.append(dict(path=p, aspect=asp, w=info.get("w"), h=info.get("h"), fps=info.get("fps"),
                              duration=info.get("duration")))
        files.sort(key=lambda f: (0 if f["aspect"] in ("3:4", "原尺寸") else 1 if f["aspect"] == "9:16" else 2))
        post = posts.get(k)
        cov = (post or {}).get("cover")
        cover = os.path.join(d, covers[k]) if k in covers else \
            (os.path.join(d, covers[MAIN_KEY]) if MAIN_KEY in covers and len(groups) == 1 else None)
        if cov and not cover and os.path.exists(os.path.join(d, os.path.dirname(groups[k][0]), cov)):
            cover = os.path.join(d, os.path.dirname(groups[k][0]), cov)
        letter = re.match(r"^([A-Z0-9]{1,3})[_ -]", k)
        title = (post or {}).get("title") or (picks.get(letter.group(1)) if letter else None) or \
            re.sub(r"^[A-Z0-9]{1,3}[_-]", "", k).replace("_", " ")
        out.append(dict(id=k, title=title, state="done", files=files, cover=cover, post=post,
                        duration=next((f["duration"] for f in files if f.get("duration")), None),
                        extra=bool(posts) and k not in posts, letter=letter.group(1) if letter else None))
    done_letters = {c["letter"] for c in out if c.get("letter")}
    cdir = os.path.join(d, "work", "clips")
    if os.path.isdir(cdir):
        for name in sorted(os.listdir(cdir)):
            p = os.path.join(cdir, name)
            if not os.path.isdir(p) or name.startswith(".") or name in done_letters:
                continue
            state, exp = _clip_state(p)
            files = []
            for e in exp:
                info = (probe or (lambda _p: {}))(e) or {}
                asp = aspect_of(info.get("w"), info.get("h")) or aspect_from_name(e) or "原尺寸"
                if not any(f["aspect"] == asp for f in files):
                    files.append(dict(path=e, aspect=asp, w=info.get("w"), h=info.get("h"), fps=info.get("fps"),
                                      duration=info.get("duration")))
            cov = next((os.path.join(p, c) for c in ("cover_3x4.jpg", "cover.jpg") if os.path.exists(os.path.join(p, c))),
                       None)
            out.append(dict(id=name, title=picks.get(name) or name, state=state, files=files, cover=cov, post=None,
                            duration=next((f["duration"] for f in files if f.get("duration")), None), extra=False,
                            letter=name, workdir=p))
    order = lambda c: (c.get("extra", False), c.get("letter") or "~", c["id"])  # noqa: E731
    return sorted(out, key=order)


def confirmations(d):
    """The 'creator should confirm' bullets of PICKS.md / NOTES.md (the 需要你 card of a work folder)."""
    out = []
    for n in ("PICKS.md", "NOTES.md"):
        p = os.path.join(d, n)
        if os.path.exists(p):
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    out += [dict(c, source=n) for c in parse_picks(f.read(200000))["confirm"]]
            except OSError:
                pass
    return out
