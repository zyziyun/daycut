#!/usr/bin/env bash
# Local check of the Mac App Store (Lite) build WITHOUT Apple certificates: build the app with BUILD_EDITION=mas,
# package the `mas` target unsigned, then sign it ad hoc ("-") with the real MAS entitlements so it runs inside the
# App Sandbox exactly like the store build (every nested binary: app-sandbox + inherit). Then run the packaged checks
# against it and collect sandbox violations from the unified log.
#
#   npm run mas:local                 # from apps/desk: build + package + ad-hoc sign + packaged tests
#   SKIP_BUILD=1 npm run mas:local    # re-sign + test the existing dist/mas-arm64/Reelfold.app
#   SKIP_TESTS=1 npm run mas:local    # build + sign only
#
# Not for upload: ad-hoc signatures and no provisioning profile (the store build is scripts/release-mas.sh). The
# TEAMID application group stays in: Electron's MAS build registers its Mach port rendezvous service under it and
# aborts at launch without it (macOS 26 accepts it on an ad-hoc signature for a local run).
# Must run outside any tool sandbox (a process that is already sandboxed cannot start an App Sandbox app).
set -euo pipefail
cd "$(dirname "$0")/.."
APP="dist/mas-arm64/Reelfold.app"
say() { printf '\n\033[1m[mas-local]\033[0m %s\n' "$*"; }

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  [ -d build/runtime/darwin-arm64 ] || node scripts/runtime/bundle.mjs --target=darwin-arm64
  say "app (BUILD_EDITION=mas)"
  BUILD_EDITION=mas npm run build
  say "package the mas target (unsigned)"
  rm -rf dist/mas-arm64
  # electron-builder stops at the signing step without an Apple Distribution identity; the .app is complete by then
  CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --config electron-builder.config.cjs --mac mas --arm64 --publish never -c.mas.identity=null || true
fi
[ -d "$APP" ] || { echo "no $APP"; exit 1; }

say "ad-hoc sign with the MAS entitlements"
bash scripts/mas-sign.sh "$APP" -
say "App Store lint (symbols, strings, entitlements, quarantine)"
python3 scripts/appstore/appstore_lint.py "$APP"

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  say "packaged checks against the sandboxed build"
  since=$(date '+%Y-%m-%d %H:%M:%S')
  DESK_APP_PATH="$PWD/$APP/Contents/MacOS/Reelfold" DESK_EDITION=mas npx playwright test -c playwright.packaged.config.ts || status=$?
  say "sandbox violations since $since (Reelfold and its children)"
  /usr/bin/log show --start "$since" --style compact --predicate 'process == "kernel" AND eventMessage CONTAINS "Sandbox:"' 2>/dev/null |
    grep -E 'Sandbox: (Reelfold|python3|ffmpeg|ffprobe)' | grep -oE '(Reelfold[^(]*|python3[^(]*|ffmpeg|ffprobe)\([0-9]+\) deny\([0-9]+\) [a-z*-]+ [^ ]+' |
    sed -E 's/\([0-9]+\) deny\([0-9]+\)/ deny/' | sort | uniq -c | sort -rn | head -40 || true
  echo "(nothing listed = no sandbox violations)"
  exit "${status:-0}"
fi
