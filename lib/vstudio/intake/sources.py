"""Sources a request names besides the files she dropped: pages she pasted as links (a web page, a public Notion
page) and her notes in Notion when she only names them ("read my Notion ...").

    got = sources.resolve(prompt, inputs)    # {inputs: [.md files read from the links], needs: [...], read: [...]}

* A link in the request is fetched once (plain HTTP GET, 2 MB / 20 s at most) and kept as Markdown in the intake
  cache (``<cache>/sources/<sha>.md``, first line ``# <title>``, second ``Source: <url>``): from then on it is a
  text material like a dropped .md (``docs.analyze`` reads it, the planner sees its headings and excerpt).
* A public Notion page (``notion.so`` / ``*.notion.site``) is read through Notion's public page endpoint
  (``/api/v3/loadPageChunk``, the one the page itself calls; no login, no key). A private page answers with nothing
  readable: that is said plainly (``intake.need.notion-private``), never guessed around.
* A request that names Notion with no Notion link and no exported notes among the files gets ``intake.need.notion``:
  she pastes the page links or drops an export (Notion > ... > Export > Markdown & CSV, unzipped). Nothing is
  planned from notes that were not read.

Every ``need`` is ``{code, params, message, message_zh}`` (vstudio.messages); the desk shows it as a question with a
drop target / a paste box, and "plan without it" (``--ignore-needs``).
No AI connector (MCP) is used here: a request is planned from what was read on this machine.
"""
import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from vstudio import messages as MSG

URL_RE = re.compile(r"https?://[^\s<>\"'）)\]】，。；;、]+", re.I)
NOTION_HOST = re.compile(r"(^|\.)notion\.(so|site)$", re.I)
NOTION_WORD = re.compile(r"notion", re.I)
MAX_BYTES = 2_000_000
TIMEOUT = 20.0
MIN_CHARS = 80                       # less readable text than this: the page was not really read
NOTE_EXT = (".md", ".markdown", ".txt", ".html", ".htm")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) Reelfold/1 (+https://github.com/zyziyun/reelfold)"


class SourceError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def urls_in(prompt):
    out = []
    for u in URL_RE.findall(prompt or ""):
        u = u.rstrip(".,!?")
        if u not in out:
            out.append(u)
    return out[:12]


def is_notion(url):
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return False
    return bool(NOTION_HOST.search(host))


def cache_dir():
    from . import inventory as I
    d = os.path.join(I.cache_root(), "sources")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------- fetching
def _http(url, data=None, timeout=TIMEOUT):
    """-> (bytes, content-type). ``data``: a JSON body (POST)."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "*/*",
                                                          **({"Content-Type": "application/json"} if body else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:      # noqa: S310 (a link she pasted herself)
            raw = r.read(MAX_BYTES + 1)
            return raw[:MAX_BYTES], r.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as e:
        raise SourceError("http", f"{url}: HTTP {e.code}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise SourceError("network", f"{url}: {getattr(e, 'reason', e)}") from e


_DROP = re.compile(r"<(script|style|noscript|svg|nav|footer|header|form)\b.*?</\1\s*>", re.I | re.S)
_BLOCK = re.compile(r"</?(p|div|section|article|li|ul|ol|br|tr|table|blockquote|pre|h[1-6])\b[^>]*>", re.I)
_HEAD = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1\s*>", re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def html_text(raw):
    """HTML -> (title, Markdown-ish text): headings kept as ``#`` lines, scripts / styles / navigation dropped."""
    s = raw if isinstance(raw, str) else raw.decode("utf-8", "replace")
    m = re.search(r"<title\b[^>]*>(.*?)</title>", s, re.I | re.S)
    title = html.unescape(_TAG.sub("", m.group(1))).strip() if m else ""
    s = _DROP.sub(" ", s)
    s = re.sub(r"<head\b.*?</head\s*>", " ", s, flags=re.I | re.S)
    s = _HEAD.sub(lambda h: f"\n{'#' * int(h.group(1))} {_TAG.sub('', h.group(2)).strip()}\n", s)
    s = _BLOCK.sub("\n", s)
    s = html.unescape(_TAG.sub("", s))
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in s.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return title, re.sub(r"\n{3,}", "\n\n", text)


def _notion_id(url):
    """The page id in a Notion link (the 32 hex digits at the end of the path, or ``?p=``) -> its dashed form."""
    parts = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qs(parts.query).get("p") or []
    for cand in q + [parts.path.rstrip("/").split("/")[-1]]:
        m = re.search(r"([0-9a-f]{32})$", cand.replace("-", ""), re.I)
        if m:
            raw = m.group(1).lower()
            return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return None


def _rich(prop):
    """Notion rich text ([[text, [[annotation]]], ...]) -> plain text."""
    out = []
    for seg in prop or []:
        if isinstance(seg, list) and seg and isinstance(seg[0], str):
            out.append(seg[0])
    return "".join(out).replace("‣", "").strip()


_N_PREFIX = {"header": "# ", "sub_header": "## ", "sub_sub_header": "### ", "bulleted_list": "- ",
             "numbered_list": "1. ", "to_do": "- [ ] ", "quote": "> ", "callout": "> ", "toggle": "- "}


def notion_page(url, http=None):
    """A public Notion page -> (title, text). Raises SourceError(notion-private) when nothing readable came back."""
    http = http or _http
    pid = _notion_id(url)
    if not pid:
        raise SourceError("notion-link", f"{url}: no Notion page id in the link")
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.hostname}"
    blocks, cursor = {}, {"stack": []}
    for chunk in range(6):                                   # long pages come in chunks of 100 blocks
        raw, _ct = http(f"{origin}/api/v3/loadPageChunk", data=dict(pageId=pid, limit=100, cursor=cursor,
                                                                   chunkNumber=chunk, verticalColumns=False))
        try:
            doc = json.loads(raw.decode("utf-8", "replace"))
        except ValueError as e:
            raise SourceError("notion-private", f"{url}: Notion did not answer with the page") from e
        for bid, rec in ((doc.get("recordMap") or {}).get("block") or {}).items():
            v = (rec or {}).get("value") or {}
            if isinstance(v.get("value"), dict):              # newer responses nest the block once more
                v = v["value"]
            if v:
                blocks[bid] = v
        cursor = doc.get("cursor") or {}
        if not cursor.get("stack"):
            break
    root = blocks.get(pid)
    if not root:
        raise SourceError("notion-private", f"{url}: the page is not public (or Notion refused to share it)")
    title = _rich((root.get("properties") or {}).get("title"))
    lines = []

    def walk(bid, depth=0):
        b = blocks.get(bid)
        if not b or depth > 6:
            return
        if bid != pid:
            t = _rich((b.get("properties") or {}).get("title"))
            kind = b.get("type") or ""
            if kind == "page":
                if t:
                    lines.append(f"## {t}")
                return                                         # a sub-page: its title only
            if t:
                lines.append(("  " * max(0, depth - 1)) + _N_PREFIX.get(kind, "") + t)
        for c in b.get("content") or []:
            walk(c, depth + 1)
    walk(pid)
    text = "\n".join(lines).strip()
    if len(text) < MIN_CHARS // 2:
        raise SourceError("notion-private", f"{url}: nothing readable on the page (private, or empty)")
    return title, text


def fetch(url, http=None):
    """One link -> {url, path, title, chars, notion}: the page as Markdown in the intake cache (fetched once)."""
    key = hashlib.sha1(url.encode()).hexdigest()[:16]
    path = os.path.join(cache_dir(), f"{key}.md")
    notion = is_notion(url)
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, encoding="utf-8") as f:
            first = f.readline()
        return dict(url=url, path=path, title=first.lstrip("# ").strip(), chars=os.path.getsize(path), notion=notion,
                    cached=True)
    if notion:
        title, text = notion_page(url, http=http)
    else:
        raw, ct = (http or _http)(url)
        if "html" in ct.lower() or raw.lstrip()[:1] == b"<":
            title, text = html_text(raw)
        elif ct.lower().startswith("text/") or not ct:
            title, text = "", raw.decode("utf-8", "replace")
        else:
            raise SourceError("not-text", f"{url}: not a page with text ({ct.split(';')[0]})")
        if len(text) < MIN_CHARS:
            raise SourceError("empty", f"{url}: almost no readable text on the page")
    title = (title or urllib.parse.urlsplit(url).path.rstrip("/").split("/")[-1] or url)[:120]
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\nSource: {url}\n\n{text}\n")
    return dict(url=url, path=path, title=title, chars=len(text), notion=notion, cached=False)


# --------------------------------------------------------------------------- the request
def _has_notes(inputs):
    """Exported notes among the dropped files (a .md / .html file, or a folder holding some)."""
    for p in inputs or []:
        p = str(p)
        if p.lower().endswith(NOTE_EXT):
            return True
        if os.path.isdir(p):
            for _dp, _dn, fns in os.walk(p):
                if any(f.lower().endswith(NOTE_EXT) for f in fns):
                    return True
    return False


def need(code, **params):
    return MSG.msg(code, **params)


def resolve(prompt, inputs=None, http=None, echo=None):
    """-> {inputs: [paths read from the links], read: [{url, title, chars, notion}], needs: [message dicts]}."""
    got, read, needs = [], [], []
    urls = urls_in(prompt)
    for u in urls:
        try:
            r = fetch(u, http=http)
        except SourceError as e:
            if echo:
                echo(f"intake: could not read {u}: {e}")
            if is_notion(u):
                needs.append(need("intake.need.notion-private", url=u))
            else:
                needs.append(need("intake.need.page-unreadable", url=u, reason=e.code))
            continue
        got.append(r["path"])
        read.append({k: r[k] for k in ("url", "title", "chars", "notion")})
    named = bool(NOTION_WORD.search(prompt or ""))
    if named and not any(is_notion(u) for u in urls) and not _has_notes(inputs):
        needs.append(need("intake.need.notion"))
    return dict(inputs=got, read=read, needs=needs)
