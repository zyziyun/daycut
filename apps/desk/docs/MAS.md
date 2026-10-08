# Mac App Store ("Lite") build

Reelfold ships twice on macOS: the full app (Developer ID, notarized DMG, GitHub Releases, electron-updater) and a
sandboxed **Reelfold Lite** on the Mac App Store. Same code; the edition is chosen at build time:

```bash
BUILD_EDITION=mas npm run build          # the app itself (src/shared/edition.ts: __REELFOLD_EDITION__)
npm run mas:local                        # local check: build, package, ad-hoc sign with the MAS entitlements, test
npm run release:mas                      # store build: sign, .pkg, verify, validate (UPLOAD=1 to upload)
```

App Store Connect: app "Reelfold", bundle id `app.reelfold.desk`, SKU `reelfold-mac`, Apple ID 6820016757, team
ZH47R7RVKB. Store texts, review notes and screenshots for the listing are kept outside the repository.

## What Lite leaves out (and why)

| | Full | Lite | Why |
|---|---|---|---|
| AI | Claude Code / Codex subscription (CLI sign-in in an in-app terminal), API keys, local models | API keys, local models (Ollama, LM Studio, vLLM) | A sandboxed app cannot run CLIs the user installed; no terminal (node-pty is not packaged) |
| Folders | any path; watched folders by path | only folders / files she picked; kept with security-scoped bookmarks | App Sandbox |
| Updates | electron-updater (GitHub Releases) | the Mac App Store | Guideline 2.4.5(vii) |
| First-run downloads | speech models, fonts, face models, optional Chromium | the same minus Chromium (data only) | Guideline 2.4.5(iv) / 2.5.2: no downloaded executables |
| HTML covers / slides | headless Chrome (installed or downloaded) | rendered by the app's own Chromium (offscreen window) | no second browser binary in the sandbox |
| Usage counts (opt-in) | yes | none ("Data Not Collected") | simpler privacy label |
| Publishing | built-in browser (assisted fill, she presses Publish), YouTube API | same | allowed; see review notes |

Everything else (projects, ASR, cleanup, captions, renders, review, calendar, Create recorder) is the same code. The
Lite build says what it does once, neutrally (Settings › General, first run, Settings › AI: "This edition uses API keys
or local models"). It names no other download and links nowhere - no "get the full version", no reelfold.com
(Guidelines 3.1.1 / 2.3); `tests/unit/editionLite.test.ts` checks that in every language. The full build is unchanged.

## How it works

- `src/shared/edition.ts` - `EDITION`, `CAPS` (what the edition can do). Everything gates on
  `CAPS`, never on scattered checks.
- `src/main/access.ts` - every open panel (`pick()` in `main/index.ts`) asks for a security-scoped bookmark in the
  MAS build; bookmarks are kept in `<userData>/access.json` and started at launch, before the engine. Files dropped on
  the window are readable for this launch; the app asks once ("Allow") for their folder so they stay readable.
  Watched folders are limited to granted folders.
- Engine (the Python sidecar, a child process in the app's sandbox) gets `VSTUDIO_LLM_NO_CLI=1` (claude-code / codex
  report `unavailable` and are skipped in fallback chains), `VSTUDIO_NO_CHROME=1`, `DESK_HISTORY_WATCH=` (no default
  watched folder) and `VSTUDIO_HTML_RENDER_URL` + token (`src/main/htmlRender.ts`: HTML -> PNG in an offscreen
  window, local files only, no network, 127.0.0.1 + per-launch token).
- The workflow scripts' `python3` / `ffmpeg` resolve to the bundled ones (`runtime.ts` puts both bin folders first
  on PATH): `/usr/bin/python3` is an xcrun shim that refuses to run in a sandbox.
- `electron-builder.config.cjs` `mas`: `hardenedRuntime: false`, entitlements in `packaging/mac/`:
  `entitlements.mas.plist` (app), `entitlements.mas.inherit.plist` (every nested executable: exactly app-sandbox +
  inherit), `entitlements.mas.loginhelper.plist`; `PrivacyInfo.xcprivacy`; `ITSAppUsesNonExemptEncryption = NO`;
  node-pty excluded. @electron/osx-sign adds `com.apple.application-identifier` / `team-identifier` from the profile.

## Sandbox checks (2026-10-07, macOS 26, Apple silicon, Electron 44.5.1 MAS build)

Run with `npm run mas:local` (ad-hoc signature, real MAS entitlements, real App Sandbox):

- The MAS Electron starts sandboxed (no V8 crash, cf. electron#51351). Without the `TEAMID.app.reelfold.desk`
  application group it aborts at launch (`bootstrap_check_in ...MachPortRendezvousServer: Permission denied`), so
  the group stays even in the ad-hoc test build.
- The real engine starts from the bundle; VideoToolbox H.264 works; ASR (MLX Whisper + numba) runs without the
  hardened-runtime JIT entitlements; downloads (models, fonts) work; a local Ollama on localhost answers.
- **Grants reach the running engine.** A child started before the parent consumes a security-scoped bookmark can
  read the file afterwards (tested with a minimal sandboxed app: child denied before
  `startAccessingSecurityScopedResource`, allowed after). Apple's forum answers describe `inherit` as passing only
  static rights, so this was checked rather than assumed; the engine is restarted anyway whenever assets change.
- The built-in sample, end to end (download, ASR, glossary, cleanup, face, compose, cover frames, export, QC,
  preview), finished inside the sandbox with no sandbox violations in the unified log.
- Found and fixed on the way: scripts calling `python3` hit the xcrun shim; the bundled LGPL ffmpeg has no `hqdn3d` /
  `eq` (GPL), which failed every talking-head render in **both** editions - `vstudio.media` now passes those two
  polish filters through when the ffmpeg lacks them; the Anthropic provider needed the `anthropic` package, which the
  bundled runtime lacks - it now falls back to the Messages API over plain HTTPS; with no usable AI at all (no key
  yet - the reviewer's case) the glossary step failed the whole job - it now falls back to rules and logs why.
- Known: the MAS Chromium keeps its single-instance socket in `<container>/tmp/S`. After a force-quit / crash the
  next launch can quit at once (`Failed to create .../S/SingletonCookie: File exists`); the launch after that works.
  The packaged tests clear it between launches.
- `tests/packaged/mas.spec.ts` (run by `npm run mas:local`): entitlements of every executable, Info.plist / privacy
  manifest / no Squirrel / no node-pty, the sandboxed engine, Lite AI rows and routes, no Chromium group, updater and
  usage off, Lite copy in Settings and first run (no upsell text, no link out); `DESK_TEST_SAMPLE=1` adds the sample run.

Not checkable without her certificates: TestFlight / store signature, the provisioning profile, `altool` validation,
and the open panel itself (a real click; the bookmark path is unit-tested and the grant mechanism was tested above).

## Review risks

- **Built-in publishing browser** (Guidelines 2.5.6, 5.1.1, 5.2): it loads platform sites in embedded Chromium
  sessions and fills the upload form; she presses Publish. Say so in the review notes; no credentials pass through
  the app. Navigation is limited to each adapter's `allowedHosts`, but the platforms show user content - answer the
  age-rating "Unrestricted Web Access" question **Yes** unless the browser is locked further (see age rating notes).
- **Local server**: engine and HTML renderer listen on 127.0.0.1 with per-launch tokens (`network.server`). Explain
  in the notes ("internal processing service, not reachable from other devices").
- **AI**: needs her own API key or a local model; give the reviewer a path that works without one (the sample uses
  rules when no AI is connected).
- **Size**: ~3.4 GB installed (Python + MLX + ffmpeg). Allowed; mention first-run downloads (~0.5 GB, data only).

## Research (sources)

- Electron MAS guide: app-sandbox + `application-groups` TEAMID.bundleid; use the `mas` Electron build; Transporter
  upload - https://www.electronjs.org/docs/latest/tutorial/mac-app-store-submission-guide
- Helper tools: sign with exactly app-sandbox + inherit -
  https://developer.apple.com/documentation/xcode/embedding-a-helper-tool-in-a-sandboxed-app ;
  `inherit` and dynamic (PowerBox) rights - https://developer.apple.com/forums/thread/111125
- `network.server` for listening sockets -
  https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.network.server
- Microphone key in the sandbox: `device.microphone` (hardened runtime: `device.audio-input`) -
  https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.device.microphone
- Hardened runtime not required for MAS - https://developer.apple.com/forums/thread/111145
- electron-builder `mas` options (entitlements, entitlementsInherit, entitlementsLoginHelper, provisioningProfile,
  hardenedRuntime default true in v26) - https://www.electron.build/docs/mas/ ,
  https://www.electron.build/v26/docs/api/app-builder-lib.interface.masconfiguration/
- Certificates: Apple Distribution (or 3rd Party Mac Developer Application) for the app, 3rd Party Mac Developer
  Installer for the pkg - https://www.electron.build/docs/features/code-signing/code-signing-mac/
- altool: `--validate-app`, `--upload-package` (replaces `--upload-app`), API key in `private_keys` /
  `API_PRIVATE_KEYS_DIR` - https://keith.github.io/xcode-man-pages/altool.7.html
- App Review Guidelines 2.4.5 (sandbox, self-contained, no downloaded code, updates only through the store) and 2.5.2
  - https://developer.apple.com/app-store/review/guidelines/ ; ML models as data -
  https://developer.apple.com/forums/thread/793131
- Required-reason APIs (privacy manifest enforcement names iOS/iPadOS/tvOS/visionOS/watchOS; the manifest is shipped
  anyway) - https://developer.apple.com/documentation/bundleresources/describing-use-of-required-reason-api ;
  Electron has none of its own yet - https://github.com/electron/electron/issues/54617
- Export compliance (`ITSAppUsesNonExemptEncryption`) -
  https://developer.apple.com/documentation/security/complying-with-encryption-export-regulations
- Quarantine flags block uploads (ITMS-91109): `xattr -cr` before signing - https://developer.apple.com/forums/thread/772398
- TestFlight entitlements (application-identifier / team-identifier in the main app only) -
  https://developer.apple.com/forums/thread/733942
- Screenshots: 16:10, 1280×800 / 1440×900 / 2560×1600 / 2880×1800, 1-10 -
  https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications
- Age ratings (4+/9+/13+/16+/18+, Unrestricted Web Access) - https://developer.apple.com/news/?id=ks775ehf ,
  https://developer.apple.com/help/app-store-connect/reference/app-information/age-ratings-values-and-definitions
