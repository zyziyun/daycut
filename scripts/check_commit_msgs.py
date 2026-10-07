#!/usr/bin/env python3
"""Check commit subjects against the Reelfold commit convention.

Usage:
  scripts/check_commit_msgs.py <base>..<head>   # check a range (CI)
  scripts/check_commit_msgs.py --file .git/COMMIT_EDITMSG   # commit-msg hook

Rule: one line, `type(scope): summary`, English (ASCII), <= 72 chars.
Merge commits and git's own fixup!/squash! subjects are skipped.
"""
import re, subprocess, sys

TYPES = "feat|fix|refactor|docs|test|chore|ci|build|perf|style"
PATTERN = re.compile(rf"^({TYPES})(\([a-z0-9-]+\))?!?: \S.{{0,70}}$")
SKIP = re.compile(r"^(Merge |Revert \"|fixup! |squash! |amend! )")


def problems(subject: str) -> list[str]:
    out = []
    if SKIP.match(subject):
        return out
    if len(subject) > 72:
        out.append(f"longer than 72 chars ({len(subject)})")
    if not subject.isascii():
        out.append("non-ASCII characters (write subjects in English)")
    if not PATTERN.match(subject):
        out.append(f"not `type(scope): summary` with type in {TYPES.replace('|', ', ')}")
    elif subject.endswith("."):
        out.append("trailing period")
    return out


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "--file":
        lines = [l for l in open(argv[1], encoding="utf-8").read().splitlines()
                 if l and not l.startswith("#")]
        items = [("(new commit)", lines[0] if lines else "")]
    else:
        rng = argv[0] if argv else "origin/main..HEAD"
        raw = subprocess.check_output(
            ["git", "log", "--no-merges", "--format=%h%x00%s", rng], text=True)
        items = [l.split("\0", 1) for l in raw.splitlines() if l]
    bad = 0
    for sha, subject in items:
        for p in problems(subject):
            bad += 1
            print(f"::error::{sha} {subject!r}: {p}")
    if bad:
        print("\nSee CONTRIBUTING.md > Commit messages. Fix with `git commit --amend` "
              "or `git rebase -i` + reword.")
        return 1
    print(f"{len(items)} commit subject(s) OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
