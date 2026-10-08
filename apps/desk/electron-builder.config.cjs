// electron-builder configuration (JS so signing can switch on/off from the environment; no secrets live here).
//
//   macOS  signing:   CSC_LINK (base64 .p12 or path) + CSC_KEY_PASSWORD, or a "Developer ID Application" identity
//                     in the login keychain (auto-discovered). Unsigned when neither exists / CSC_IDENTITY_AUTO_DISCOVERY=false.
//          notarize:  APPLE_ID + APPLE_APP_SPECIFIC_PASSWORD + APPLE_TEAM_ID
//                     or APPLE_KEYCHAIN + APPLE_KEYCHAIN_PROFILE (xcrun notarytool store-credentials)
//                     or APPLE_API_KEY + APPLE_API_KEY_ID + APPLE_API_ISSUER. Skipped when none is set.
//   Windows signing:  Azure Trusted Signing when AZURE_TENANT_ID/AZURE_CLIENT_ID/AZURE_CLIENT_SECRET and
//                     AZURE_SIGNING_ENDPOINT/AZURE_SIGNING_ACCOUNT/AZURE_SIGNING_PROFILE/AZURE_SIGNING_PUBLISHER are set;
//                     else a PFX via WIN_CSC_LINK + WIN_CSC_KEY_PASSWORD; else unsigned.
//   Store:            appx identity from MS_STORE_IDENTITY_NAME / MS_STORE_PUBLISHER / MS_STORE_PUBLISHER_NAME
//                     (Partner Center -> Product identity). Placeholders otherwise.
//   Mac App Store:    target `mas` (scripts/release-mas.sh, built with BUILD_EDITION=mas): signed with "Apple Distribution"
//                     (or "3rd Party Mac Developer Application"), the .pkg with "3rd Party Mac Developer Installer";
//                     profile from MAS_PROVISIONING_PROFILE (default packaging/mac/Reelfold_Mac_App_Store.provisionprofile,
//                     git-ignored). See docs/MAS.md.
// See docs/RELEASING.md.
const env = process.env;

// Installers + the electron-updater feed are GitHub Releases on the source repo itself (zyziyun/reelfold); the
// website's download button links to its /releases/latest. Override for a fork / test feed:
//   DESK_RELEASES_OWNER=<owner> DESK_RELEASES_REPO=<repo>
const RELEASES_OWNER = env.DESK_RELEASES_OWNER || 'zyziyun';
const RELEASES_REPO = env.DESK_RELEASES_REPO || 'reelfold';

const azure =
  env.AZURE_TENANT_ID && env.AZURE_CLIENT_ID && env.AZURE_CLIENT_SECRET && env.AZURE_SIGNING_ENDPOINT && env.AZURE_SIGNING_ACCOUNT && env.AZURE_SIGNING_PROFILE
    ? {
        publisherName: env.AZURE_SIGNING_PUBLISHER || 'video-studio',
        endpoint: env.AZURE_SIGNING_ENDPOINT,
        codeSigningAccountName: env.AZURE_SIGNING_ACCOUNT,
        certificateProfileName: env.AZURE_SIGNING_PROFILE,
      }
    : null;

// Under resources/runtime only Mach-O code is signed (*.so, *.dylib, python3.x, ffmpeg, ffprobe); everything else
// (.py/.pyc, models, data) is sealed by the app signature instead of being codesigned one by one.
// scripts/runtime/bundle.mjs fails the build if a Mach-O file outside this pattern appears.
const RUNTIME_NON_CODE = String.raw`/Contents/Resources/runtime/(?!.*\.(so|dylib)$)(?!python/bin/python3\.\d+$)(?!ffmpeg/bin/ff(mpeg|probe)$)`;

// npm workspaces hoist electron to the monorepo's node_modules, where electron-builder cannot read the installed
// version from apps/desk: give it the exact one that is installed (resolved from here).
// eslint-disable-next-line @typescript-eslint/no-require-imports -- CommonJS config file
const electronVersion = require(require.resolve('electron/package.json', { paths: [__dirname] })).version;

// Mac App Store provisioning profile (developer.apple.com -> Profiles -> Mac App Store Connect, app.reelfold.desk)
const fs = require('node:fs'); // eslint-disable-line @typescript-eslint/no-require-imports -- CommonJS config file
const path = require('node:path'); // eslint-disable-line @typescript-eslint/no-require-imports -- CommonJS config file
const MAS_PROFILE = env.MAS_PROVISIONING_PROFILE || path.join(__dirname, 'packaging/mac/Reelfold_Mac_App_Store.provisionprofile');

/** @type {import('electron-builder').Configuration} */
module.exports = {
  electronVersion,
  // New bundle id / AppUserModelID for Reelfold (nothing was released under the old com.vstudio.desk). The profile
  // of an earlier dev / test install is copied over once and keeps its keychain key (src/main/identity.ts APP_ID).
  appId: 'app.reelfold.desk',
  productName: 'Reelfold',
  copyright: 'Copyright © 2026 zyziyun',
  artifactName: 'Reelfold-${version}-${os}-${arch}.${ext}',
  directories: { output: 'dist', buildResources: 'packaging/resources' },
  files: ['out/**', 'package.json', '!**/*.map'],
  npmRebuild: false,
  asar: true,
  // node-pty (in-app login terminal) loads a native .node + spawn-helper: they must live outside the asar
  asarUnpack: ['**/node_modules/node-pty/**'],
  extraResources: [
    { from: 'engine', to: 'engine', filter: ['**/*.py', '!tests/**', '!**/__pycache__/**'] },
    { from: 'adapters', to: 'adapters' },
    { from: 'packaging/assets.json', to: 'packaging/assets.json' },
    // "Try with a sample": the CC0 sample recording (~1 MB, engine/desk_engine/sample.py)
    { from: 'packaging/sample', to: 'packaging/sample', filter: ['reelfold-sample.mp4', 'script.json', 'LICENSE.txt'] },
    { from: 'THIRD_PARTY_LICENSES.md', to: 'THIRD_PARTY_LICENSES.md' },
    { from: 'packaging/resources/icons', to: 'packaging/resources/icons' }, // About panel icon (Linux)
    // built by `npm run runtime` (scripts/runtime/bundle.mjs) for the target being packaged
    { from: 'build/runtime/${platform}-${arch}', to: 'runtime' },
  ],
  publish: [{ provider: 'github', owner: RELEASES_OWNER, repo: RELEASES_REPO, releaseType: 'draft' }],
  // Electron fuses (flipped in the binary, then signed): no "run as node", no NODE_OPTIONS / --inspect, the app code
  // only from an integrity-checked app.asar, encrypted cookies, no extra file:// privileges. Without these any local
  // process could run code as the signed Reelfold and read its keychain item (the stored API keys).
  // Packaged tests attach over CDP (--remote-debugging-port), not the Node inspector (tests/packaged).
  electronFuses: {
    runAsNode: false,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false,
    enableEmbeddedAsarIntegrityValidation: true,
    onlyLoadAppFromAsar: true,
    enableCookieEncryption: true,
    grantFileProtocolExtraPrivileges: false,
    loadBrowserProcessSpecificV8Snapshot: false,
    resetAdHocDarwinSignature: true, // unsigned arm64 test builds must still launch
  },

  mac: {
    icon: 'packaging/resources/icon.icns', // scripts/brand/icons.mjs
    target: ['dmg', 'zip'], // zip: electron-updater; arch from the CLI (--arm64 / --x64)
    category: 'public.app-category.video',
    minimumSystemVersion: '14.0', // MLX wheels; the x64 build overrides this (see release.yml)
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements: 'packaging/mac/entitlements.mac.plist',
    entitlementsInherit: 'packaging/mac/entitlements.mac.inherit.plist',
    signIgnore: [RUNTIME_NON_CODE],
    notarize: true, // only acts when the APPLE_* variables above are present
    // 千剪 for Finder / Dock / menu bar under a Chinese system language (the in-app About follows the app's language)
    // Create page recorder: macOS asks for camera / mic only when the creator presses "Allow" in Create (flag on)
    extendInfo: {
      CFBundleIconName: 'AppIcon', // Assets.car (scripts/brand/icons.mjs); icon.icns stays for older readers
      LSHasLocalizedDisplayName: true,
      NSCameraUsageDescription: 'Reelfold uses the camera only while you record in Create.',
      NSMicrophoneUsageDescription: 'Reelfold uses the microphone only while you record in Create.',
    },
    extraResources: [
      { from: 'packaging/resources/Assets.car', to: 'Assets.car' },
      { from: 'packaging/mac/zh_CN.lproj/InfoPlist.strings', to: 'zh_CN.lproj/InfoPlist.strings' },
      { from: 'packaging/mac/zh_CN.lproj/InfoPlist.strings', to: 'zh-Hans.lproj/InfoPlist.strings' },
    ],
  },
  // Mac App Store (Lite) build: App Sandbox, every nested binary with app-sandbox + inherit only, no hardened runtime
  // (not required by the Mac App Store; the sandboxed children could not carry its extra entitlements), no updater
  // (src/main/updater.ts), no node-pty (no in-app terminal: the Lite build has no CLI sign-in). The app itself must be
  // built with BUILD_EDITION=mas (src/shared/edition.ts); scripts/release-mas.sh does both.
  mas: {
    type: 'distribution',
    hardenedRuntime: false,
    entitlements: 'packaging/mac/entitlements.mas.plist',
    entitlementsInherit: 'packaging/mac/entitlements.mas.inherit.plist',
    entitlementsLoginHelper: 'packaging/mac/entitlements.mas.loginhelper.plist',
    ...(fs.existsSync(MAS_PROFILE) ? { provisioningProfile: MAS_PROFILE } : {}),
    files: ['!**/node_modules/node-pty/**'],
    extendInfo: {
      ElectronTeamID: 'ZH47R7RVKB',
      // HTTPS / TLS only (standard protocols, no proprietary encryption): exempt, no export compliance documents
      ITSAppUsesNonExemptEncryption: false,
      CFBundleIconName: 'AppIcon',
      LSHasLocalizedDisplayName: true,
      NSCameraUsageDescription: 'Reelfold uses the camera only while you record in Create.',
      NSMicrophoneUsageDescription: 'Reelfold uses the microphone only while you record in Create.',
    },
    extraResources: [
      { from: 'packaging/resources/Assets.car', to: 'Assets.car' },
      { from: 'packaging/mac/zh_CN.lproj/InfoPlist.strings', to: 'zh_CN.lproj/InfoPlist.strings' },
      { from: 'packaging/mac/zh_CN.lproj/InfoPlist.strings', to: 'zh-Hans.lproj/InfoPlist.strings' },
      { from: 'packaging/mac/PrivacyInfo.xcprivacy', to: 'PrivacyInfo.xcprivacy' },
    ],
  },
  dmg: {
    sign: false,
    writeUpdateInfo: false,
    title: 'Reelfold', // volume name
    background: 'packaging/resources/background.png', // + background@2x.png
    window: { width: 540, height: 380 },
    contents: [
      { x: 140, y: 200, type: 'file' },
      { x: 400, y: 200, type: 'link', path: '/Applications' },
    ],
  },

  win: {
    icon: 'packaging/resources/icon.ico',
    target: ['nsis'],
    // sign the bundled python.exe / ffmpeg.exe too (Defender SmartScreen looks at launched executables);
    // *.pyd/*.dll are left alone to keep the signature count (and Azure cost) low
    signExts: ['.exe'],
    ...(azure ? { azureSignOptions: azure } : {}),
  },
  nsis: {
    // Reelfold-<v>-win-x64-setup.exe (+ .blockmap; latest.yml points at it), attached to the GitHub Release next to the
    // macOS files. "-setup" keeps it apart from the portable / Store names and reads as an installer on the release page.
    artifactName: 'Reelfold-${version}-win-${arch}-setup.${ext}',
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    differentialPackage: true,
    deleteAppDataOnUninstall: false,
    shortcutName: 'Reelfold',
    uninstallDisplayName: 'Reelfold',
    installerIcon: 'packaging/resources/icon.ico',
    uninstallerIcon: 'packaging/resources/icon.ico',
  },
  linux: {
    icon: 'packaging/resources/icons',
    category: 'AudioVideo',
    executableName: 'reelfold',
    synopsis: 'One recording, folded out into every cut for every platform',
  },
  appx: {
    // Microsoft Store (MSIX). Values come from Partner Center; the Store re-signs the package.
    identityName: env.MS_STORE_IDENTITY_NAME || 'PLACEHOLDER.VideoStudioDesk',
    publisher: env.MS_STORE_PUBLISHER || 'CN=00000000-0000-0000-0000-000000000000',
    publisherDisplayName: env.MS_STORE_PUBLISHER_NAME || 'PLACEHOLDER',
    applicationId: 'VideoStudioDesk',
    displayName: 'Reelfold',
    languages: ['zh-CN', 'en-US'],
    backgroundColor: '#0E1113',
    showNameOnTiles: true,
  },
};
