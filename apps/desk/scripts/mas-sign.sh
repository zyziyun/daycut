#!/usr/bin/env bash
# Sign a packaged Mac App Store (Lite) Reelfold.app inside-out with the MAS entitlements:
#   every nested Mach-O (bundled python / ffmpeg / *.so / *.dylib, Electron helpers)  app-sandbox + inherit
#   the login helper                                                                    app-sandbox
#   the app                                                                             entitlements.mas.plist
#   bash scripts/mas-sign.sh <Reelfold.app> <identity|-> [--no-groups]
# Used by scripts/mas-local.sh with "-" (ad hoc: local sandbox checks). The store build is signed by electron-builder
# (@electron/osx-sign) with the same entitlement files; scripts/release-mas.sh verifies the result with mas-verify.sh.
set -euo pipefail
APP="$1"
ID="$2"
NO_GROUPS="${3:-}"
cd "$(dirname "$0")/.."
ENT_APP=packaging/mac/entitlements.mas.plist
ENT_CHILD=packaging/mac/entitlements.mas.inherit.plist
ENT_LOGIN=packaging/mac/entitlements.mas.loginhelper.plist
if [ "$NO_GROUPS" = "--no-groups" ]; then
  # an ad-hoc signature has no Team ID: drop the TEAMID-prefixed app group (the store build keeps it)
  ENT_APP=$(mktemp -t reelfold-mas-ent).plist
  cp packaging/mac/entitlements.mas.plist "$ENT_APP"
  /usr/libexec/PlistBuddy -c 'Delete :com.apple.security.application-groups' "$ENT_APP"
fi
sign() { codesign --force --sign "$ID" --timestamp=none "$@"; }

# files downloaded with the build tools can carry com.apple.quarantine (upload error ITMS-91109)
xattr -cr "$APP"

echo "[mas-sign] nested code (inherit)"
find "$APP/Contents" -type f \( -name '*.so' -o -name '*.dylib' -o -perm -u+x \) \
  -not -path '*/Contents/MacOS/*' -not -path '*.framework/Versions/A/*Framework' -print0 |
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then printf '%s\0' "$f"; fi
  done | xargs -0 -n 16 -P 8 codesign --force --sign "$ID" --timestamp=none --entitlements "$ENT_CHILD"

echo "[mas-sign] frameworks, helpers, login helper, app"
for fw in "$APP"/Contents/Frameworks/*.framework; do sign "$fw"; done
for h in "$APP"/Contents/Frameworks/*.app; do sign --entitlements "$ENT_CHILD" "$h"; done
for h in "$APP"/Contents/Library/LoginItems/*.app; do sign --entitlements "$ENT_LOGIN" "$h"; done
sign --entitlements "$ENT_APP" "$APP"
codesign --verify --deep --strict "$APP"
echo "[mas-sign] signed: $APP ($ID)"
