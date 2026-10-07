"""Release notes -> a feature list for a launch / update video.

    from vstudio.launch import features as FE
    FE.from_changelog("CHANGELOG.md")                 # the newest section (or version="0.2.0" / "Unreleased")
    FE.from_git(".", "v0.1.0..v0.2.0")                # Conventional Commits in a git range
    FE.from_notes("- Plan from one sentence\\n- ...") # any bullet list (release notes pasted from a site)

Every function returns ``[{id, title, kind, scope, detail, source}]``: ``kind`` is feat | fix | perf | change |
security, ``title`` is one short line a caption can start from. Chores (ci, docs, test, build, style, refactor,
chore) never become features. The list is a draft: the creator picks 4-6 and writes the on-screen captions.
"""
import re
import subprocess

CC_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s*(?P<desc>.+)$")
KEEP = {"feat": "feat", "fix": "fix", "perf": "perf", "revert": "change", "security": "security"}
SECTION_KIND = {"added": "feat", "changed": "change", "fixed": "fix", "security": "security", "performance": "perf",
                "deprecated": "change", "removed": "change", "features": "feat", "bug fixes": "fix"}
ORDER = {"feat": 0, "perf": 1, "change": 2, "fix": 3, "security": 4}
BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")


def slug(text, n=32):
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    if len(s) > n:
        s = s[:n + 1].rsplit("-", 1)[0] if "-" in s[:n + 1] else s[:n]
    return s.strip("-") or "feature"


def _plain(md):
    """Markdown inline -> plain text (links, bold, code)."""
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", md or "")
    t = re.sub(r"\*\*([^*]+)\*\*|__([^_]+)__", lambda m: m.group(1) or m.group(2), t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _title(text, n=72):
    """First clause of a sentence, short enough for a caption draft."""
    t = _plain(text)
    head = re.split(r"(?<=[.;:])\s|\s[-–—]\s|:\s", t, maxsplit=1)[0].rstrip(".;:")
    if len(head) > n:
        head = head[:n].rsplit(" ", 1)[0] + "…"
    return head


def _unique(items):
    out, seen = [], set()
    for it in items:
        base, k = it["id"], 2
        while it["id"] in seen:
            it["id"] = f"{base}-{k}"
            k += 1
        seen.add(it["id"])
        out.append(it)
    return out


def parse_commit(subject):
    """'feat(desk): add X' -> {type, scope, desc, breaking} or None for a non-conventional subject."""
    m = CC_RE.match((subject or "").strip())
    if not m:
        return None
    return dict(type=m["type"], scope=m["scope"], desc=m["desc"].strip(), breaking=bool(m["bang"]))


def from_commits(subjects):
    """Conventional Commit subjects -> features (feat / fix / perf / revert / breaking; chores dropped)."""
    out = []
    for s in subjects:
        c = parse_commit(s)
        if not c:
            continue
        kind = "change" if c["breaking"] and c["type"] not in KEEP else KEEP.get(c["type"])
        if not kind:
            continue
        desc = c["desc"][0].upper() + c["desc"][1:]
        out.append(dict(id=slug(desc), title=_title(desc), kind=kind, scope=c["scope"], detail=desc, source=s))
    out.sort(key=lambda f: ORDER[f["kind"]])
    return _unique(out)


def from_git(repo=".", rev_range=None, first_parent=True):
    """``git log --format=%s <range>`` -> features. rev_range e.g. "v0.1.0..v0.2.0" (None = the whole history)."""
    cmd = ["git", "-C", str(repo), "log", "--format=%s"] + (["--first-parent"] if first_parent else [])
    if rev_range:
        cmd.append(rev_range)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"git log {rev_range or ''} failed: {r.stderr.strip()}")
    return from_commits([ln for ln in r.stdout.splitlines() if ln.strip()])


def changelog_sections(text):
    """Keep-a-Changelog text -> [(version, body)] in file order ("Unreleased" included)."""
    parts = re.split(r"^##\s+", text, flags=re.M)[1:]
    out = []
    for p in parts:
        head, _, body = p.partition("\n")
        m = re.match(r"\[?([^\]\s]+)\]?", head.strip())
        out.append((m.group(1) if m else head.strip(), body))
    return out


def from_markdown(body, source="notes"):
    """A markdown release-notes body -> features: top-level bullets under ### Added / Fixed / ... headings
    (no heading = feat). A top-level bullet that only introduces nested bullets ("Mac app:") contributes its
    nested bullets instead, each prefixed by nothing - the nested line is the feature."""
    kind, out, intro = "feat", [], False
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        h = re.match(r"^#{3,4}\s+(.+)$", ln)
        if h:
            kind = SECTION_KIND.get(h.group(1).strip().lower(), "change")
            continue
        m = BULLET_RE.match(ln)
        if not m:
            continue
        indent, text = len(m.group(1)), m.group(2)
        if indent == 0:
            nxt = BULLET_RE.match(lines[i + 1]) if i + 1 < len(lines) else None
            intro = bool(nxt and len(nxt.group(1)) > 0 and _plain(text).rstrip().endswith(":"))
            if intro:
                continue                                 # "Mac app (X), MIT:" -> its children are the features
        elif not intro:
            continue                                     # details of a feature bullet, not features themselves
        full = text
        j = i + 1                                         # wrapped continuation lines of the same bullet
        while j < len(lines) and lines[j].strip() and not BULLET_RE.match(lines[j]) and not lines[j].startswith("#"):
            full += " " + lines[j].strip()
            j += 1
        out.append(dict(id=slug(_title(full)), title=_title(full), kind=kind, scope=None, detail=_plain(full),
                        source=source))
    out.sort(key=lambda f: ORDER.get(f["kind"], 9))
    return _unique(out)


def from_changelog(path, version=None):
    """CHANGELOG.md -> features of one version (default: the first section, usually "Unreleased" or the newest)."""
    with open(path, encoding="utf-8") as f:
        secs = changelog_sections(f.read())
    if not secs:
        raise ValueError(f"{path}: no '## [version]' sections")
    if version:
        want = str(version).lstrip("v").lower()
        hit = [b for v, b in secs if v.lstrip("v").lower() == want]
        if not hit:
            raise ValueError(f"{path}: no section for {version}; have {', '.join(v for v, _ in secs)}")
        body = hit[0]
    else:
        body = secs[0][1]
    return from_markdown(body, source=f"{path}#{version or secs[0][0]}")


def from_notes(text):
    """Pasted release notes (bullets, or one feature per line) -> features."""
    if any(BULLET_RE.match(ln) for ln in text.splitlines()):
        return from_markdown(text)
    return _unique([dict(id=slug(_title(ln)), title=_title(ln), kind="feat", scope=None, detail=_plain(ln),
                         source="notes") for ln in text.splitlines() if ln.strip()])


def load(release):
    """The config's ``release`` block -> features: {changelog: path, version?} | {git: {repo, range}} | {notes}."""
    if not release:
        return []
    if release.get("changelog"):
        return from_changelog(release["changelog"], release.get("version"))
    if release.get("git"):
        g = release["git"]
        return from_git(g.get("repo", "."), g.get("range"))
    if release.get("notes"):
        return from_notes(release["notes"])
    raise ValueError("release: give changelog, git {repo, range} or notes")
