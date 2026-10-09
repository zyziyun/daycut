#!/usr/bin/env bash
# Mac App Store (Lite) release build: arm64, BUILD_EDITION=mas, App Sandbox, signed with the Apple Distribution
# identity + the Mac App Store provisioning profile, packaged as a .pkg signed with the installer identity, verified,
# then validated with App Store Connect. Uploading is a separate, explicit step (UPLOAD=1). Nothing is submitted for
# review: she picks the build in App Store Connect and presses Submit herself. docs/MAS.md has the one-time setup.
#
#   npm run release:mas                       # build + sign + verify + validate
#   UPLOAD=1 npm run release:mas              # ... then upload the .pkg (App Store Connect -> TestFlight / builds)
#   DRY_RUN=1 npm run release:mas             # preflight only: identities, profile, API key, tools
#   SKIP_TESTS=1 npm run release:mas          # skip lint / unit tests
#   BUILD_NUMBER=20261007.2140.0 npm run release:mas   # CFBundleVersion (default: date.time.0 - must grow with every upload)
#   MAS_VERSION=0.2.1 npm run release:mas     # CFBundleShortVersionString + app version (default: package.json): a new
#                                             # build for an App Store version that is still open (e.g. after a rejection)
#
# Needs (checked first; nothing is built when one is missing):
#   MAS_APP_IDENTITY        default "Apple Distribution: YUN ZI (ZH47R7RVKB)"
#                           ("3rd Party Mac Developer Application: YUN ZI (ZH47R7RVKB)" works too)
#   MAS_INSTALLER_IDENTITY  default "3rd Party Mac Developer Installer: YUN ZI (ZH47R7RVKB)" (the "Mac Installer
#                           Distribution" certificate shows under this name in the keychain)
#   MAS_PROVISIONING_PROFILE default packaging/mac/Reelfold_Mac_App_Store.provisionprofile (git-ignored): a
#                           "Mac App Store Connect" distribution profile for app.reelfold.desk
#   App Store Connect API key (validate / upload): APPLE_API_KEY (path to AuthKey_<id>.p8) + APPLE_API_KEY_ID +
#                           APPLE_API_ISSUER - the same key the GitHub release workflow uses
set -euo pipefail
cd "$(dirname "$0")/.."

TEAM=ZH47R7RVKB
BUNDLE_ID=app.reelfold.desk
ASC_APP_ID=6820016757
APP_IDENTITY="${MAS_APP_IDENTITY:-Apple Distribution: YUN ZI ($TEAM)}"
INSTALLER_IDENTITY="${MAS_INSTALLER_IDENTITY:-3rd Party Mac Developer Installer: YUN ZI ($TEAM)}"
PROFILE="${MAS_PROVISIONING_PROFILE:-$PWD/packaging/mac/Reelfold_Mac_App_Store.provisionprofile}"
VERSION="${MAS_VERSION:-$(node -p "require('./package.json').version")}"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "[release:mas] bad version $VERSION"; exit 1; }
BUILD_NUMBER="${BUILD_NUMBER:-$(date +%Y%m%d).$((10#$(date +%H%M))).0}"
# three parts: electron-builder's CLI parses "20261007.2140" as a number and drops the trailing zero (-> .214)
[[ "$BUILD_NUMBER" == *.*.* ]] || BUILD_NUMBER="$BUILD_NUMBER.0"
say() { printf '\n\033[1m[release:mas]\033[0m %s\n' "$*"; }
die() { printf '\n\033[31m[release:mas] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "macOS only"
[ "$(uname -m)" = "arm64" ] || die "build on an Apple silicon Mac (the bundled runtime is arm64)"
say "Reelfold Lite $VERSION ($BUILD_NUMBER) · app: $APP_IDENTITY · pkg: $INSTALLER_IDENTITY"

# ---------------------------------------------------------------- preflight
for tool in node npx codesign xcrun pkgutil security productbuild; do command -v "$tool" >/dev/null || die "missing tool: $tool"; done
security find-identity -v -p codesigning | grep -Fq "\"$APP_IDENTITY\"" ||
  die "app signing identity not in the keychain: $APP_IDENTITY
  create it: Xcode > Settings > Accounts > (team $TEAM) > Manage Certificates > + > Apple Distribution"
security find-identity -v | grep -Fq "\"$INSTALLER_IDENTITY\"" ||
  die "installer identity not in the keychain: $INSTALLER_IDENTITY
  create it: Xcode > Settings > Accounts > Manage Certificates > + > Mac Installer Distribution"
[ -f "$PROFILE" ] || die "no provisioning profile at $PROFILE
  developer.apple.com > Profiles > + > Mac App Store Connect > App ID $BUNDLE_ID > certificate: Apple Distribution;
  download it to that path (or set MAS_PROVISIONING_PROFILE)"
PROFILE_PLIST=$(mktemp -t reelfold-profile).plist
security cms -D -i "$PROFILE" > "$PROFILE_PLIST" 2>/dev/null || die "cannot read the provisioning profile $PROFILE"
pb() { /usr/libexec/PlistBuddy -c "Print :$1" "$PROFILE_PLIST" 2>/dev/null || true; }
[ "$(pb Entitlements:com.apple.application-identifier)" = "$TEAM.$BUNDLE_ID" ] ||
  die "the profile is for $(pb Entitlements:com.apple.application-identifier), not $TEAM.$BUNDLE_ID"
[ -z "$(pb ProvisionedDevices)" ] || die "this is a development profile (it lists devices): make a Mac App Store Connect profile"
[ "$(pb Entitlements:com.apple.developer.team-identifier)" = "$TEAM" ] || die "the profile is not for team $TEAM"
EXPIRES=$(pb ExpirationDate)
say "profile: $(pb Name) (expires $EXPIRES)"
if [ -n "${APPLE_API_KEY:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ]; then
  [ -f "$APPLE_API_KEY" ] || die "APPLE_API_KEY is not a file: $APPLE_API_KEY"
  # altool looks for AuthKey_<id>.p8 in API_PRIVATE_KEYS_DIR (or ~/.appstoreconnect/private_keys)
  KEYDIR=$(mktemp -d -t reelfold-asc)
  cp "$APPLE_API_KEY" "$KEYDIR/AuthKey_$APPLE_API_KEY_ID.p8"
  export API_PRIVATE_KEYS_DIR="$KEYDIR"
  trap 'rm -rf "$KEYDIR"' EXIT
  ASC=(--apiKey "$APPLE_API_KEY_ID" --apiIssuer "$APPLE_API_ISSUER")
else
  [ "${UPLOAD:-0}" = "1" ] && die "UPLOAD=1 needs APPLE_API_KEY + APPLE_API_KEY_ID + APPLE_API_ISSUER"
  echo "[release:mas] no App Store Connect API key: the build is checked locally but not validated with Apple"
  ASC=()
fi
if [ -n "$(git status --porcelain -- . ../../lib ../../workflows 2>/dev/null)" ]; then
  echo "[release:mas] warning: uncommitted changes in the app or engine"
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
  say "dry run: preflight passed; a real run would now"
  [ "${SKIP_TESTS:-0}" != "1" ] && echo "  - npm run lint && npm run test:unit"
  echo "  - node scripts/runtime/bundle.mjs --target=darwin-arm64; strip quarantine flags"
  echo "  - BUILD_EDITION=mas npm run build"
  echo "  - electron-builder --mac mas --arm64 (sign: $APP_IDENTITY + profile; pkg: $INSTALLER_IDENTITY)"
  echo "  - verify signatures / sandbox entitlements of every executable, the pkg signature"
  [ ${#ASC[@]} -gt 0 ] && echo "  - xcrun altool --validate-app"
  [ "${UPLOAD:-0}" = "1" ] && echo "  - xcrun altool --upload-package (app $ASC_APP_ID)"
  exit 0
fi

# ---------------------------------------------------------------- build
if [ "${SKIP_TESTS:-0}" != "1" ]; then
  say "lint + unit tests"
  npm run lint
  npm run test:unit
fi
say "engine runtime"
node scripts/runtime/bundle.mjs --target=darwin-arm64
xattr -cr build/runtime/darwin-arm64 # downloaded files keep com.apple.quarantine (upload error ITMS-91109)
say "app (BUILD_EDITION=mas)"
BUILD_EDITION=mas npm run build
say "electron-builder: mas target (sign app + nested code, pkg)"
rm -rf dist/mas-arm64 dist/*.pkg
CSC_IDENTITY_AUTO_DISCOVERY=true MAS_PROVISIONING_PROFILE="$PROFILE" \
  npx electron-builder --config electron-builder.config.cjs --mac mas --arm64 --publish never \
  -c.buildVersion="$BUILD_NUMBER" \
  -c.extraMetadata.version="$VERSION" \
  -c.mas.identity="${APP_IDENTITY#*: }" \
  -c.mas.provisioningProfile="$PROFILE"

APP="dist/mas-arm64/Reelfold.app"
PKG=$(ls -t dist/*.pkg dist/mas-arm64/*.pkg 2>/dev/null | head -1 || true)
[ -d "$APP" ] || die "no $APP"
[ -n "$PKG" ] || die "no .pkg in dist/ (installer identity?)"

# ---------------------------------------------------------------- verify
say "verify"
codesign --verify --deep --strict --verbose=2 "$APP"
codesign -dv --verbose=2 "$APP" 2>&1 | grep -E "Authority=(Apple Distribution|3rd Party Mac Developer Application)|TeamIdentifier=$TEAM" ||
  die "the app is not signed with the distribution identity"
[ -f "$APP/Contents/embedded.provisionprofile" ] || die "no embedded provisioning profile"
ENT=$(codesign -d --entitlements - --xml "$APP" 2>/dev/null)
for k in com.apple.security.app-sandbox com.apple.application-identifier com.apple.developer.team-identifier com.apple.security.application-groups; do
  grep -q "$k" <<<"$ENT" || die "the app's entitlements lack $k"
done
# nothing listens on a network port (engine + HTML renderer: Unix sockets); App Review 2.4.5 rejected network.server
! grep -q com.apple.security.network.server <<<"$ENT" || die "the app has com.apple.security.network.server"
# every Mach-O inside: sandboxed child (app-sandbox + inherit), else App Store Connect rejects it (ITMS-90296)
bad=0
while IFS= read -r -d '' f; do
  file -b "$f" | grep -q 'Mach-O' || continue
  case "$f" in *.dylib|*.so|*/Frameworks/*.framework/*) continue ;; esac # libraries carry no entitlements
  e=$(codesign -d --entitlements - --xml "$f" 2>/dev/null || true)
  if ! grep -q com.apple.security.inherit <<<"$e" && [ "$f" != "$APP/Contents/MacOS/Reelfold" ] && [[ "$f" != *LoginItems* ]]; then
    echo "  not sandbox-inherit: ${f#$APP/}"; bad=1
  fi
done < <(find "$APP/Contents" -type f -perm -u+x -print0)
[ "$bad" = 0 ] || die "nested executables without app-sandbox + inherit (see above)"
# what App Review rejected or is known to reject: Tcl/Tk and non-public Accelerate BLAS symbols in any Mach-O (2.5.1),
# "itms-services" in Python files, entitlements of every executable and architecture slice, quarantine flags
say "App Store lint"
python3 scripts/appstore/appstore_lint.py "$APP" || die "App Store lint failed (see above): App Review would reject this build"
pkgutil --check-signature "$PKG" | grep -E "3rd Party Mac Developer Installer|Mac Installer Distribution" ||
  die "the pkg is not signed with the installer identity"
plutil -p "$APP/Contents/Info.plist" | grep -E 'CFBundleVersion|CFBundleShortVersionString|ITSAppUsesNonExemptEncryption|LSMinimumSystemVersion'

if [ ${#ASC[@]} -gt 0 ]; then
  say "validate with App Store Connect"
  xcrun altool --validate-app -f "$PKG" -t macos "${ASC[@]}" --output-format normal
fi

if [ "${UPLOAD:-0}" = "1" ]; then
  say "upload $PKG to App Store Connect (app $ASC_APP_ID)"
  xcrun altool --upload-package "$PKG" -t macos --apple-id "$ASC_APP_ID" --bundle-id "$BUNDLE_ID" \
    --bundle-short-version-string "$VERSION" --bundle-version "$BUILD_NUMBER" "${ASC[@]}" --output-format normal
  echo "Uploaded. App Store Connect > Reelfold > macOS > the build appears after processing (~15-30 min)."
else
  echo "Not uploaded. Upload with UPLOAD=1 npm run release:mas, or drag $PKG into Transporter."
fi
say "done: $PKG"
