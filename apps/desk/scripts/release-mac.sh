#!/usr/bin/env bash
# macOS release build: arm64, signed with the Developer ID identity from the keychain, notarized, stapled, verified.
# Runs on this Mac (login keychain + notarytool keychain profile) and in CI (.github/workflows/desk-release.yml:
# a temporary keychain + an App Store Connect API key). Produces dist/Reelfold-<version>-mac-arm64.dmg (+ .zip for electron-updater).
#
#   npm run release:mac                 # from apps/desk
#   SKIP_TESTS=1 npm run release:mac    # skip lint / unit / packaged checks
#   DRY_RUN=1 npm run release:mac       # preflight only (identity, notary profile, arch, tools), then print the plan
#
# Needs (checked first, nothing is built when one is missing):
#   - the signing identity  MAC_SIGN_IDENTITY   (default "Developer ID Application: YUN ZI (ZH47R7RVKB)")
#   - notarization, one of:
#       local (default)  a notarytool profile APPLE_KEYCHAIN_PROFILE (default "vstudio-notary"; create it once with
#                        xcrun notarytool store-credentials vstudio-notary --apple-id … --team-id ZH47R7RVKB)
#       CI / API key     APPLE_API_KEY (path to AuthKey_<id>.p8) + APPLE_API_KEY_ID + APPLE_API_ISSUER; used when all
#                        three are set (the keychain profile is then ignored)
# Nothing is published: upload the DMG / zip / latest-mac.yml to a GitHub Release on zyziyun/reelfold by hand (docs/RELEASING.md).
set -euo pipefail
cd "$(dirname "$0")/.."

IDENTITY="${MAC_SIGN_IDENTITY:-Developer ID Application: YUN ZI (ZH47R7RVKB)}"
# electron-builder picks notarization credentials from the environment: keep exactly one kind in it
unset APPLE_ID APPLE_APP_SPECIFIC_PASSWORD APPLE_TEAM_ID CSC_LINK CSC_KEY_PASSWORD
if [ -n "${APPLE_API_KEY:-}" ] && [ -n "${APPLE_API_KEY_ID:-}" ] && [ -n "${APPLE_API_ISSUER:-}" ]; then
  NOTARY_MODE="API key $APPLE_API_KEY_ID"
  NOTARY_ARGS=(--key "$APPLE_API_KEY" --key-id "$APPLE_API_KEY_ID" --issuer "$APPLE_API_ISSUER")
  export APPLE_API_KEY APPLE_API_KEY_ID APPLE_API_ISSUER
  unset APPLE_KEYCHAIN_PROFILE APPLE_KEYCHAIN
else
  export APPLE_KEYCHAIN_PROFILE="${APPLE_KEYCHAIN_PROFILE:-vstudio-notary}"
  NOTARY_MODE="keychain profile $APPLE_KEYCHAIN_PROFILE"
  NOTARY_ARGS=(--keychain-profile "$APPLE_KEYCHAIN_PROFILE")
  unset APPLE_API_KEY APPLE_API_KEY_ID APPLE_API_ISSUER
fi
VERSION=$(node -p "require('./package.json').version")
say() { printf '\n\033[1m[release]\033[0m %s\n' "$*"; }
die() { printf '\n\033[31m[release] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = "Darwin" ] || die "macOS only"
[ "$(uname -m)" = "arm64" ] || die "build on an Apple silicon Mac (the bundled runtime is arm64)"
say "Reelfold $VERSION · identity: $IDENTITY · notarization: $NOTARY_MODE"

# ---------------------------------------------------------------- preflight
security find-identity -v -p codesigning | grep -Fq "\"$IDENTITY\"" ||
  die "signing identity not in the keychain: $IDENTITY (security find-identity -v -p codesigning)"
if [ -n "${APPLE_API_KEY:-}" ]; then
  [ -f "$APPLE_API_KEY" ] || die "APPLE_API_KEY is not a file: $APPLE_API_KEY (path to AuthKey_<id>.p8)"
  xcrun notarytool history "${NOTARY_ARGS[@]}" >/dev/null 2>&1 ||
    die "notarytool rejects the App Store Connect API key $APPLE_API_KEY_ID (check APPLE_API_KEY_ID / APPLE_API_ISSUER and the .p8)"
else
  xcrun notarytool history "${NOTARY_ARGS[@]}" >/dev/null 2>&1 ||
    die "notarytool profile '$APPLE_KEYCHAIN_PROFILE' does not work (xcrun notarytool store-credentials $APPLE_KEYCHAIN_PROFILE …)"
fi
if [ -n "$(git status --porcelain -- . ../../lib ../../workflows 2>/dev/null)" ]; then
  echo "[release] warning: uncommitted changes in the app or engine — the build records the commit as -dirty"
fi
for tool in node npx codesign xcrun spctl; do command -v "$tool" >/dev/null || die "missing tool: $tool"; done

if [ "${DRY_RUN:-0}" = "1" ]; then
  say "dry run: preflight passed; a real run would now"
  [ "${SKIP_TESTS:-0}" != "1" ] && echo "  - npm run lint && npm run test:unit"
  echo "  - node scripts/runtime/bundle.mjs --target=darwin-arm64"
  echo "  - npm run build"
  echo "  - electron-builder --mac --arm64 (sign: $IDENTITY; fuses; notarize + staple the app: $NOTARY_MODE)"
  echo "  - codesign + notarize + staple dist/Reelfold-$VERSION-mac-arm64.dmg"
  echo "  - verify with codesign / spctl / stapler"
  [ "${SKIP_TESTS:-0}" != "1" ] && echo "  - packaged-app checks (playwright.packaged.config.ts)"
  exit 0
fi

# ---------------------------------------------------------------- build
if [ "${SKIP_TESTS:-0}" != "1" ]; then
  say "lint + unit tests"
  npm run lint
  npm run test:unit
fi
say "engine runtime (python + ffmpeg + this repository's engine)"
node scripts/runtime/bundle.mjs --target=darwin-arm64
say "app (typecheck + bundle)"
npm run build
say "electron-builder: sign + notarize + staple the app"
rm -rf dist/mac-arm64 "dist/Reelfold-$VERSION-mac-arm64.dmg" "dist/Reelfold-$VERSION-mac-arm64.zip"
# CSC_NAME: the identity without its "Developer ID Application: " prefix, as electron-builder expects
CSC_IDENTITY_AUTO_DISCOVERY=true CSC_NAME="${IDENTITY#Developer ID Application: }" \
  npx electron-builder --config electron-builder.config.cjs --mac --arm64 --publish never

APP="dist/mac-arm64/Reelfold.app"
DMG="dist/Reelfold-$VERSION-mac-arm64.dmg"
[ -d "$APP" ] || die "no $APP"
[ -f "$DMG" ] || die "no $DMG"

say "sign + notarize + staple the DMG"
codesign --force --timestamp --sign "$IDENTITY" "$DMG"
xcrun notarytool submit "$DMG" "${NOTARY_ARGS[@]}" --wait
xcrun stapler staple "$DMG"

# ---------------------------------------------------------------- verify
say "verify"
codesign --verify --deep --strict --verbose=2 "$APP"
codesign -dv --verbose=2 "$APP" 2>&1 | grep -E "Authority=Developer ID Application|TeamIdentifier|Runtime Version|flags=" || true
spctl --assess --type execute --verbose=4 "$APP"
xcrun stapler validate "$APP"
spctl --assess --type open --context context:primary-signature --verbose=4 "$DMG"
xcrun stapler validate "$DMG"
codesign --verify --strict --verbose=2 "$DMG"

if [ "${SKIP_TESTS:-0}" != "1" ]; then
  say "packaged-app checks (fuses, bundled engine, mock + real engine)"
  npx playwright test -c playwright.packaged.config.ts
fi

say "done"
ls -lh "$DMG" "dist/Reelfold-$VERSION-mac-arm64.zip" dist/latest-mac.yml 2>/dev/null || true
echo "Smoke test on a second macOS account: install from the DMG -> first run -> transcribe -> render -> plan."
