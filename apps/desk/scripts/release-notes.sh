#!/usr/bin/env bash
# Release notes for a desk tag, as Markdown on stdout (used by .github/workflows/desk-release.yml for the draft).
#
#   bash scripts/release-notes.sh v0.2.1        # from apps/desk (or anywhere in the repo)
#
# First match wins:
#   1. apps/desk/release-notes/<tag>.md                      (hand-written, used as is)
#   2. the "## … <version> …" section of apps/desk/CHANGELOG.md or CHANGELOG.md at the repo root
#   3. generated from the Conventional Commits since the previous v* tag that touch the app or the engine it ships
#      (apps/desk, lib, workflows, requirements.txt): feat / fix / perf (+ other non-chore commits)
set -euo pipefail
TAG="${1:?usage: release-notes.sh <tag, e.g. v0.2.1>}"
VERSION="${TAG#v}"
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cd "$ROOT"
REPO_URL="https://github.com/zyziyun/reelfold"

if [ -f "apps/desk/release-notes/$TAG.md" ]; then
  cat "apps/desk/release-notes/$TAG.md"
  exit 0
fi

for cl in apps/desk/CHANGELOG.md CHANGELOG.md; do
  [ -f "$cl" ] || continue
  # a "## " heading that names this version exactly (v0.2.1, [0.2.1], 0.2.1 ...), up to the next "## "
  section=$(awk -v ver="$VERSION" '
    /^## / { if (found) exit; s = $0; gsub(/[][()v]/, " ", s); n = split(s, w, /[ \t]+/);
             for (i = 1; i <= n; i++) if (w[i] == ver) { found = 1; next } }
    found { print }' "$cl")
  if [ -n "$(printf '%s' "$section" | tr -d '[:space:]')" ]; then
    printf '%s\n' "$section"
    exit 0
  fi
done

# ---- generated from commits
end="$TAG"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null || end=HEAD
prev=$(git describe --tags --abbrev=0 --match 'v*' "$end^" 2>/dev/null || true)
range="${prev:+$prev..}$end"
paths=(apps/desk lib workflows requirements.txt)

feat=() fix=() perf=() other=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  sha="${line%% *}"; subject="${line#* }"
  if [[ "$subject" =~ ^([a-z]+)(\(([^\)]*)\))?(!)?:[[:space:]]*(.*)$ ]]; then
    type="${BASH_REMATCH[1]}"; scope="${BASH_REMATCH[3]}"; text="${BASH_REMATCH[5]}"
  else
    type=other; scope=""; text="$subject"
  fi
  item="- ${scope:+**$scope**: }$text ($sha)"
  case "$type" in
    feat) feat+=("$item") ;;
    fix) fix+=("$item") ;;
    perf) perf+=("$item") ;;
    docs|chore|ci|test|style|build) ;;
    *) other+=("$item") ;;
  esac
done < <(git log --no-merges --format='%h %s' "$range" -- "${paths[@]}")

section() { # title, items...
  local title="$1"; shift
  [ "$#" -gt 0 ] || return 0
  printf '### %s\n\n' "$title"
  printf '%s\n' "${@:1:60}"
  [ "$#" -le 60 ] || printf -- '- … and %d more\n' "$(($# - 60))"
  printf '\n'
}

echo "## Reelfold $VERSION"
echo
section "New" ${feat[@]+"${feat[@]}"}
section "Fixes" ${fix[@]+"${fix[@]}"}
section "Faster" ${perf[@]+"${perf[@]}"}
section "Other changes" ${other[@]+"${other[@]}"}
if [ ${#feat[@]} -eq 0 ] && [ ${#fix[@]} -eq 0 ] && [ ${#perf[@]} -eq 0 ] && [ ${#other[@]} -eq 0 ]; then
  echo "Maintenance release."
  echo
fi
echo "**Install:** download \`Reelfold-$VERSION-mac-arm64.dmg\` below (Apple silicon, macOS 14+), open it and drag Reelfold to Applications. Installed copies update themselves."
if [ -n "$prev" ]; then
  echo
  echo "**Full changelog:** $REPO_URL/compare/$prev...$TAG"
fi
