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
// See docs/RELEASING.md.
const env = process.env;

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

/** @type {import('electron-builder').Configuration} */
module.exports = {
  appId: 'com.vstudio.desk',
  productName: 'video-studio desk',
  copyright: 'Copyright © 2026 zyziyun',
  artifactName: 'video-studio-desk-${version}-${os}-${arch}.${ext}',
  directories: { output: 'dist', buildResources: 'packaging/resources' },
  files: ['out/**', 'package.json', '!**/*.map'],
  npmRebuild: false,
  asar: true,
  extraResources: [
    { from: 'engine', to: 'engine', filter: ['**/*.py', '!tests/**', '!**/__pycache__/**'] },
    { from: 'adapters', to: 'adapters' },
    { from: 'packaging/assets.json', to: 'packaging/assets.json' },
    { from: 'THIRD_PARTY_LICENSES.md', to: 'THIRD_PARTY_LICENSES.md' },
    // built by `npm run runtime` (scripts/runtime/bundle.mjs) for the target being packaged
    { from: 'build/runtime/${platform}-${arch}', to: 'runtime' },
  ],
  publish: [{ provider: 'github', owner: 'zyziyun', repo: 'video-studio-desk-releases', releaseType: 'draft' }],

  mac: {
    target: ['dmg', 'zip'], // zip: electron-updater; arch from the CLI (--arm64 / --x64)
    category: 'public.app-category.video',
    minimumSystemVersion: '14.0', // MLX wheels; the x64 build overrides this (see release.yml)
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements: 'packaging/mac/entitlements.mac.plist',
    entitlementsInherit: 'packaging/mac/entitlements.mac.inherit.plist',
    signIgnore: [RUNTIME_NON_CODE],
    notarize: true, // only acts when the APPLE_* variables above are present
    extendInfo: {
      NSCameraUsageDescription: 'Not used.',
      NSMicrophoneUsageDescription: 'Not used.',
    },
  },
  dmg: { sign: false, writeUpdateInfo: false },

  win: {
    target: ['nsis'],
    // sign the bundled python.exe / ffmpeg.exe too (Defender SmartScreen looks at launched executables);
    // *.pyd/*.dll are left alone to keep the signature count (and Azure cost) low
    signExts: ['.exe'],
    ...(azure ? { azureSignOptions: azure } : {}),
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowToChangeInstallationDirectory: true,
    differentialPackage: true,
    deleteAppDataOnUninstall: false,
  },
  appx: {
    // Microsoft Store (MSIX). Values come from Partner Center; the Store re-signs the package.
    identityName: env.MS_STORE_IDENTITY_NAME || 'PLACEHOLDER.VideoStudioDesk',
    publisher: env.MS_STORE_PUBLISHER || 'CN=00000000-0000-0000-0000-000000000000',
    publisherDisplayName: env.MS_STORE_PUBLISHER_NAME || 'PLACEHOLDER',
    applicationId: 'VideoStudioDesk',
    displayName: 'video-studio desk',
    languages: ['zh-CN', 'en-US'],
    backgroundColor: '#0E1113',
    showNameOnTiles: true,
  },
};
