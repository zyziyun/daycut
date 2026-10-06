"""Text materials: pdf / docx / pptx / md / txt / srt / vtt / json -> a compact fact sheet (never a raw dump).

    facts = docs.analyze("brief.pdf")     # {chars, pages, title, headings [..10], excerpt (<= 300 chars),
                                          #  lang, shape (script | slides | subtitles | notes | article | outline),
                                          #  episodes, urls [..20], note}

Extractors are optional and imported lazily: pypdf (or PyMuPDF), python-docx, python-pptx. A missing extractor
is not an error: the file is listed with ``note: "... not installed"`` and no text facts.
"""
import json
import os
import re

TEXT_EXT = {".md", ".markdown", ".txt", ".text", ".rst"}
SUB_EXT = {".srt", ".vtt", ".ass"}
DOC_EXT = {".pdf", ".docx", ".pptx", ".json", ".csv", ".yaml", ".yml"} | TEXT_EXT | SUB_EXT
MAX_CHARS = 400_000            # stop extracting after this (a book-length PDF does not need more for a plan)
EXCERPT = 300
URL_RE = re.compile(r"https?://[^\s<>\"'）)\]】，。]+", re.I)
HEAD_RE = re.compile(r"^\s{0,3}(#{1,4})\s+(.+?)\s*#*\s*$")
NUM_HEAD_RE = re.compile(r"^\s*(第[一二三四五六七八九十百\d]+[章节课讲部分集场幕]|[一二三四五六七八九十]+、|\d{1,2}[.、)]\s|Chapter\s+\d+|Part\s+\d+)", re.I)
EPISODE_RE = re.compile(r"第\s*([一二三四五六七八九十百\d]+)\s*集|Episode\s*(\d+)|EP\s*(\d+)", re.I)
SCENE_RE = re.compile(r"(^|\n)\s*(第[一二三四五六七八九十\d]+场|场景\s*\d+|Scene\s+\d+|INT\.|EXT\.|镜头\s*\d+|【.{1,12}】)", re.I)
DIALOG_RE = re.compile(r"(^|\n)\s*[一-鿿A-Za-z]{1,8}\s*[（(][^）)]{0,12}[）)]?\s*[:：]|(^|\n)\s*[一-鿿]{1,6}[:：]\s*\S")
SRT_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


class Missing(RuntimeError):
    pass


def _read_text(path):
    with open(path, "rb") as f:
        raw = f.read(MAX_CHARS * 4)
    for enc in ("utf-8-sig", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _pdf(path):
    pages, parts, size = 0, [], 0
    try:
        import pypdf
        r = pypdf.PdfReader(path)
        pages = len(r.pages)
        for pg in r.pages:
            t = pg.extract_text() or ""
            parts.append(t)
            size += len(t)
            if size > MAX_CHARS:
                break
        return "\n".join(parts), dict(pages=pages)
    except ImportError:
        pass
    try:
        import fitz  # PyMuPDF
        with fitz.open(path) as d:
            pages = d.page_count
            for pg in d:
                t = pg.get_text() or ""
                parts.append(t)
                size += len(t)
                if size > MAX_CHARS:
                    break
        return "\n".join(parts), dict(pages=pages)
    except ImportError:
        raise Missing("pdf text: pypdf (pip install pypdf) or PyMuPDF not installed") from None


def _docx(path):
    try:
        import docx
    except ImportError:
        raise Missing("docx text: python-docx not installed (pip install python-docx)") from None
    d = docx.Document(path)
    lines = []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        sty = (getattr(p.style, "name", "") or "").lower()
        if sty.startswith("heading") or sty.startswith("title") or sty.startswith("标题"):
            lvl = re.findall(r"\d", sty)
            t = "#" * (int(lvl[0]) if lvl else 1) + " " + t
        lines.append(t)
    for tb in d.tables[:20]:
        for row in tb.rows[:60]:
            lines.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(lines), dict(paragraphs=len(d.paragraphs), tables=len(d.tables))


def _pptx(path):
    try:
        import pptx
    except ImportError:
        raise Missing("pptx text: python-pptx not installed (pip install python-pptx)") from None
    prs = pptx.Presentation(path)
    lines, n = [], 0
    for k, slide in enumerate(prs.slides):
        n += 1
        title = None
        for sh in slide.shapes:
            if not getattr(sh, "has_text_frame", False):
                continue
            t = sh.text_frame.text.strip()
            if not t:
                continue
            if title is None and getattr(sh, "is_placeholder", False) and "title" in str(
                    getattr(sh.placeholder_format, "type", "")).lower():
                title = t
                lines.append(f"# {t}")
            else:
                lines.append(t)
        if title is None:
            lines.append(f"# slide {k + 1}")
    return "\n".join(lines), dict(slides=n)


def _subs(path):
    text = _read_text(path)
    end = 0.0
    for m in SRT_TIME.finditer(text):
        h, mi, s, ms = int(m.group(5)), int(m.group(6)), int(m.group(7)), int(m.group(8).ljust(3, "0"))
        end = max(end, h * 3600 + mi * 60 + s + ms / 1000)
    body = []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.isdigit() or SRT_TIME.search(ln) or ln.upper().startswith("WEBVTT"):
            continue
        if ln.startswith("Dialogue:"):                   # .ass
            ln = ln.split(",", 9)[-1]
        body.append(re.sub(r"\{[^}]*\}|<[^>]+>", "", ln))
    return "\n".join(body), dict(duration=round(end, 1), cues=len(SRT_TIME.findall(text)))


def extract(path):
    """-> (text, extra facts). Raises Missing when the extractor is not installed."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _pdf(path)
    if ext == ".docx":
        return _docx(path)
    if ext == ".pptx":
        return _pptx(path)
    if ext in SUB_EXT:
        return _subs(path)
    if ext == ".json":
        t = _read_text(path)
        try:
            d = json.loads(t)
            return json.dumps(d, ensure_ascii=False)[:MAX_CHARS], dict(json_type=type(d).__name__)
        except ValueError:
            return t, {}
    return _read_text(path)[:MAX_CHARS], {}


def lang_of(text):
    s = text[:20000]
    cjk = len(re.findall(r"[一-鿿]", s))
    lat = len(re.findall(r"[A-Za-z]", s))
    if not cjk and not lat:
        return None
    return "zh" if cjk >= lat * 0.25 else "en"


def headings(text, limit=12):
    out = []
    for ln in text.splitlines():
        m = HEAD_RE.match(ln)
        t = m.group(2) if m else (ln.strip() if NUM_HEAD_RE.match(ln) and len(ln.strip()) <= 40 else None)
        if t and not t.startswith("slide "):
            t = re.sub(r"\s+", " ", t).strip()[:60]
            if t and t not in out:
                out.append(t)
        if len(out) >= limit:
            break
    return out


def urls(text, limit=20):
    out = []
    for u in URL_RE.findall(text):
        u = u.rstrip(".,;:")
        if u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def shape_of(text, ext, extra):
    """What kind of text this is: script (剧本: scenes + dialogue), subtitles, slides, outline, notes, article."""
    if ext in SUB_EXT:
        return "subtitles"
    if ext == ".pptx":
        return "slides"
    scenes = len(SCENE_RE.findall(text))
    dialog = len(DIALOG_RE.findall(text))
    eps = len(set(m.group(0) for m in EPISODE_RE.finditer(text)))
    if (scenes >= 3 and dialog >= 5) or (eps >= 2 and dialog >= 5) or re.search(r"剧本|分镜|台词|screenplay", text[:3000], re.I) \
            and dialog >= 3:
        return "script"
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return "empty"
    bullets = sum(1 for ln in lines if re.match(r"^\s*([-*•·]|\d+[.、)])\s*", ln))
    avg = sum(len(ln) for ln in lines) / len(lines)
    if bullets >= max(4, len(lines) * 0.4) or (avg < 30 and len(lines) >= 8):
        return "outline" if len(headings(text)) >= 3 else "notes"
    if ext == ".pdf" and extra.get("pages", 0) >= 6 and avg < 45:
        return "slides"                                 # exported decks: many short lines per page
    return "article"


def excerpt(text, n=EXCERPT):
    s = re.sub(r"[ \t]+", " ", re.sub(r"\n{2,}", "\n", text)).strip()
    s = URL_RE.sub("[url]", s)
    return s[:n] + ("…" if len(s) > n else "")


def analyze(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        text, extra = extract(path)
    except Missing as e:
        return dict(note=str(e), chars=None)
    except Exception as e:  # noqa: BLE001 - a broken file must not stop the inventory
        return dict(note=f"text extraction failed: {type(e).__name__}: {str(e)[:120]}", chars=None)
    eps = sorted({int(m.group(2) or m.group(3)) if (m.group(2) or m.group(3)) else _cn_num(m.group(1))
                  for m in EPISODE_RE.finditer(text)} - {None})
    out = dict(chars=len(text), lang=lang_of(text), title=_title(text, path), headings=headings(text),
               excerpt=excerpt(text), shape=shape_of(text, ext, extra), urls=urls(text), **extra)
    if eps:
        out["episodes"] = len(eps)
    if not text.strip():
        out["note"] = "no extractable text (scanned PDF / image-only?)"
    return out


def _title(text, path):
    for ln in text.splitlines()[:30]:
        m = HEAD_RE.match(ln)
        if m:
            return m.group(2).strip()[:60]
    for ln in text.splitlines()[:10]:
        if 2 <= len(ln.strip()) <= 40:
            return ln.strip()
    return os.path.splitext(os.path.basename(path))[0][:60]


_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "两": 2}


def _cn_num(s):
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + _CN.get(s[1:], 0)
    if "十" in s:
        a, _, b = s.partition("十")
        return _CN.get(a, 1) * 10 + (_CN.get(b, 0) if b else 0)
    return _CN.get(s)


def cn_num(s):
    """'六' -> 6, '12' -> 12, '二十' -> 20 (for counts in prompts)."""
    return _cn_num(s)
