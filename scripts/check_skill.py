#!/usr/bin/env python3
"""Pre-publish checks for this skill repo (run before a commit / release).

    python3 scripts/check_skill.py            # whole repo, exit 1 on any error
    python3 scripts/check_skill.py --all-md   # also scan every .md for decorative emoji

Checks:
  1. SKILL.md frontmatter: opens with ---, has `name` (lowercase-hyphen, <= 64 chars) and `description`
     (<= 1024 chars, the limit skill loaders enforce; warning above 900).
  2. Every workflows/<name>/WORKFLOW.md exists, starts with a "# " title and says "Use when".
  3. No decorative emoji in SKILL.md / WORKFLOW.md (functional symbols such as -> x arrows, the play glyph and
     check marks stay allowed). Spoken-copy defaults in references or templates are not scanned unless --all-md.
  4. No absolute personal paths: /Users/<name>/ and /home/<name>/ are errors everywhere; ~/Desktop, ~/Downloads,
     ~/Movies are errors in code / config and warnings in .md prose ("~/Desktop/..." placeholders are fine).
     persona.local.yaml and caches are excluded. Placeholder homes (/Users/me/, /Users/you/) are fine.
     Covers the apps too (apps/desk, apps/site: .ts/.tsx/.cjs/.astro ...), skipping node_modules / dist / out /
     build output. A line that must keep such a path on purpose (a documented product default) carries the
     marker `check-skill: allow`.
  5. Relative markdown links in SKILL.md / WORKFLOW.md point at files that exist (warning only).
  6. No committed secrets anywhere (API keys / tokens / private keys by their well-known shapes) and no secret
     files (.env, .p12, .pfx, .pem, .key, cookies) in the tree.
"""
import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Decorative emoji: explicit list plus the pictograph blocks. Functional symbols (arrows, x, play glyph,
# check / ballot marks used in checklists) are deliberately not in here.
BANNED = set("❌✅⭐★🔥💡📝📌🎬🎥👋📊📈📉🚀🎯💯🙌👍👎✨🎉👇👉😀")
PICTO = [(0x1F300, 0x1F5FF), (0x1F600, 0x1F64F), (0x1F680, 0x1F6FF), (0x1F900, 0x1F9FF), (0x1FA70, 0x1FAFF)]
DESC_MAX, DESC_WARN = 1024, 900
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# Hard: a concrete user home. Soft: a home-relative personal folder (an error in code / config, a warning in prose
# docs, which sometimes have to say what a port replaced). "~/Desktop/..." with a literal ellipsis is a placeholder.
PERSONAL = re.compile(r"/Users/(?!\.\.\.|<|\$|(?:me|you)/)[A-Za-z0-9._-]+/|/home/(?!<|\$|(?:me|you)/)[A-Za-z0-9._-]+/")
PERSONAL_SOFT = re.compile(r"~/(Desktop|Downloads|Movies)\b(?!/\.\.\.)")
TEXT_EXT = {".md", ".py", ".sh", ".html", ".json", ".yaml", ".yml", ".toml", ".txt", ".js", ".mjs", ".css", ".ass", ".srt",
            ".ts", ".tsx", ".jsx", ".cjs", ".astro", ".ps1", ".plist", ".xml", ".svg", ".webmanifest"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", ".venv", "venv", "cache", ".cache",
             # app build output / test artifacts (apps/desk, apps/site)
             "dist", "out", "build", ".astro", "test-results", "playwright-report"}
ALLOW_MARK = "check-skill: allow"
# Well-known secret shapes: OpenAI / Anthropic keys, GitHub tokens, AWS access keys, Slack tokens, Google API keys,
# PEM private keys. Placeholders (sk-..., xxxx) do not match.
SECRET = re.compile(r"\b(sk-(?:ant-|proj-)?[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}"
                    r"|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})\b"
                    r"|-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----")
SECRET_FILES = re.compile(r"(^\.env(\..+)?$|\.(p12|pfx|pem|key|keychain|mobileprovision)$|^cookies?(\.[a-z]+)?$)", re.I)
SECRET_FILES_OK = {".env.example", ".env.sample"}
SKIP_FILES = {"persona.local.yaml"}
# Files that quote the forbidden patterns on purpose (rule text, this checker).
ALLOW_PATH_MENTIONS = {"references/PORTING.md", "scripts/check_skill.py"}


def frontmatter(text):
    """-> dict of top-level `key: value` lines, or None when there is no --- block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    out = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            return out
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return None                                          # unterminated


def check_frontmatter(text, errs, warns, label="SKILL.md"):
    fm = frontmatter(text)
    if fm is None:
        errs.append(f"{label}: missing or unterminated YAML frontmatter (--- ... ---)")
        return
    name, desc = fm.get("name"), fm.get("description")
    if not name:
        errs.append(f"{label}: frontmatter has no `name`")
    elif not NAME_RE.match(name):
        errs.append(f"{label}: name {name!r} must be lowercase letters, digits and hyphens, <= 64 chars")
    if not desc:
        errs.append(f"{label}: frontmatter has no `description`")
    elif len(desc) > DESC_MAX:
        errs.append(f"{label}: description is {len(desc)} chars (max {DESC_MAX})")
    elif len(desc) > DESC_WARN:
        warns.append(f"{label}: description is {len(desc)} chars (close to the {DESC_MAX} limit)")


def emoji_hits(text):
    """-> [(line_no, char, line excerpt)] for decorative emoji."""
    hits = []
    for i, ln in enumerate(text.splitlines(), 1):
        for c in ln:
            o = ord(c)
            if c in BANNED or any(a <= o <= b for a, b in PICTO):
                hits.append((i, c, ln.strip()[:70]))
    return hits


def personal_path_hits(text, soft=False):
    rx = PERSONAL_SOFT if soft else PERSONAL
    return [(i, m.group(0)) for i, ln in enumerate(text.splitlines(), 1) if ALLOW_MARK not in ln for m in rx.finditer(ln)]


def secret_hits(text):
    """-> [(line_no, redacted match)] for strings shaped like real credentials."""
    return [(i, m.group(0)[:8] + "...") for i, ln in enumerate(text.splitlines(), 1) for m in SECRET.finditer(ln)]


def tracked_files(root):
    """-> the git-tracked files under root (ignored local files such as a .env are not "in the tree"), or None."""
    try:
        r = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return [root / f for f in r.stdout.split("\0") if f] if r.returncode == 0 and r.stdout else None


def secret_files(root):
    files = tracked_files(root)
    for p in (files if files is not None else root.rglob("*")):
        if p.is_file() and SECRET_FILES.search(p.name) and p.name not in SECRET_FILES_OK \
                and p.name not in SKIP_FILES and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            yield p


def md_links(text):
    for m in re.finditer(r"\]\(([^)\s]+)\)", text):
        tgt = m.group(1).split("#")[0]
        if tgt and not re.match(r"^[a-z]+:", tgt):
            yield tgt


def iter_text_files(root):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in TEXT_EXT and p.name not in SKIP_FILES \
                and not any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            yield p


def run(root=ROOT, all_md=False):
    errs, warns = [], []
    skill = root / "SKILL.md"
    docs = [skill] if skill.exists() else []
    if not skill.exists():
        errs.append("SKILL.md missing at the repo root")
    else:
        check_frontmatter(skill.read_text(encoding="utf-8"), errs, warns)

    for wf in sorted(p for p in (root / "workflows").glob("*") if p.is_dir() and not p.name.startswith(("_", "."))):
        md = wf / "WORKFLOW.md"
        rel = md.relative_to(root)
        if not md.exists():
            errs.append(f"{rel}: missing")
            continue
        t = md.read_text(encoding="utf-8")
        if not t.lstrip().startswith("# "):
            errs.append(f"{rel}: should start with a '# <name>' title")
        if "use when" not in t.lower():
            errs.append(f"{rel}: no 'Use when' paragraph")
        docs.append(md)

    scan = docs + ([p for p in iter_text_files(root) if p.suffix == ".md" and p not in docs] if all_md else [])
    for p in scan:
        for i, c, ex in emoji_hits(p.read_text(encoding="utf-8")):
            errs.append(f"{p.relative_to(root)}:{i}: decorative emoji {c!r}: {ex}")

    for p in docs:
        for tgt in md_links(p.read_text(encoding="utf-8")):
            if not (p.parent / tgt).exists():
                warns.append(f"{p.relative_to(root)}: broken relative link {tgt}")

    for p in iter_text_files(root):
        rel = p.relative_to(root).as_posix()
        if rel in ALLOW_PATH_MENTIONS:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for i, hit in personal_path_hits(text):
            errs.append(f"{rel}:{i}: personal absolute path {hit!r}")
        for i, hit in personal_path_hits(text, soft=True):
            (warns if p.suffix == ".md" else errs).append(f"{rel}:{i}: personal folder path {hit!r}")
        for i, hit in secret_hits(text):
            errs.append(f"{rel}:{i}: looks like a secret {hit!r}")
    for p in secret_files(root):
        errs.append(f"{p.relative_to(root).as_posix()}: secret-like file in the tree (.env / certificate / key / cookies)")
    return errs, warns


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    ap.add_argument("--all-md", action="store_true", help="scan every .md for decorative emoji, not only SKILL/WORKFLOW")
    a = ap.parse_args()
    errs, warns = run(pathlib.Path(a.root), all_md=a.all_md)
    for e in errs:
        print("ERROR", e)
    for w in warns:
        print("warn ", w)
    print("ok" if not errs else f"{len(errs)} error(s), {len(warns)} warning(s)")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
