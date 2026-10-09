# Reelfold (千剪) desk app

The Reelfold desktop app: an Electron workbench on the open-source engine (`python -m vstudio.batch`,
`vstudio.project`; the Claude Code skill is still called `video-studio`), in `apps/desk/` of the
[Reelfold monorepo](../../README.md). MIT, like the rest of the repo (see `LICENSE`).
Formerly "Daycut" and, before that, the separate `video-studio-desk` repo (history kept via git subtree).
Batches → board → review → job detail (transcript edits) → publish (built-in browser with assisted fill).

```bash
npm install          # here or at the repo root: one npm workspace install (node_modules at the repo root)
npm run dev          # Vite + Electron; engine sidecar starts automatically, using this repo's lib/ (../..)
                     # macOS: runs as "Reelfold" from a cached Reelfold.app copy of Electron (build/.cache/dev-app)
npm run test         # vitest (unit) + python unittest (engine/tests)
npm run test:e2e     # builds, then Playwright Electron smoke + CDP fill fixture
npm run lint         # eslint + tsc
npm run build:mac    # .app in dist/ (uses build/runtime if present)
npm run runtime      # bundled engine runtime for this machine -> build/runtime/<platform>-<arch>
npm run dist:mac:unsigned && npm run test:packaged   # DMG with the bundled engine + packaged-app check
```

Distribution (signed/notarized DMG, Windows installer, auto-update, store plans): [docs/RELEASING.md](docs/RELEASING.md).
Installed builds run the engine from the bundled runtime (`resources/runtime`: Python, LGPL ffmpeg, and the engine
copied from this checkout's root at build time — no separate engine checkout or pinned commit) and download fonts/models on first run; Settings → Python / video-studio repo still override it.

Engine: `engine/server.py` (stdlib HTTP on a Unix domain socket in the app's temp folder - Windows: 127.0.0.1, random port - per-launch token; the UI reaches it through `app://desk/api`, forwarded by main: `src/main/engineTransport.ts`). It finds the engine repo via
Settings → `VSTUDIO_ENGINE_PATH` → the monorepo root (`../..`) → a sibling `../video-studio` (old layout), and Python via Settings → `DESK_PYTHON` → miniconda/Homebrew.
Tests only: `DESK_ENGINE_MOCK=1` starts the in-memory test engine from `engine/tests/fixtures/desk_mock` (fake
batches, rule plans, simulated pilots, fake Create services and AI). A dev build only: a packaged app ignores it and does
not ship `engine/tests`. A `vstudio` that cannot be imported fails the start with the reason; nothing fake stands in.

AI accounts & models (Settings → AI accounts & models, `#/settings/ai`): provider status from the engine
(`python -m vstudio.llm auth status --json`; Claude Code is checked with a one-line round-trip, so an expired login
shows as expired), CLI logins in an in-app terminal (xterm.js + node-pty, else a Python PTY, else `script`; the command
comes from `vstudio.llm auth login`, API keys / base URLs are removed from its environment), API keys in the OS
keychain, and which provider each task uses (default + per-task override + ordered fallbacks). The choices are saved
in the desk settings and written to `<userData>/llm-routes.json` (`VSTUDIO_LLM_ROUTES_FILE`, read by the engine on
every call); the persona's `llm:` routes are the starting values. `DESK_AI_MOCK=<dir>` (status.json, login.json,
routes.json, test.json) stands in for the engine in tests; `DESK_NO_PTY=1` forces the fallback terminal.

Publish adapters: `adapters/*.json` (schema: `src/shared/publish/adapterSchema.ts`). Override or add adapters
without rebuilding in `~/Library/Application Support/Reelfold/adapters/` (an older `Daycut` / `video-studio desk` profile,
adapters included, is copied there on the first Reelfold launch). Selectors marked
`"status": "unverified"` were written without a live session — verify them, then set `verified` + `lastVerified`.
The app never clicks publish; there is no way to express a click in an adapter.
Adapters may name `session.cookies` (signed in = one of them is set in the account's own partition
`persist:<adapter>-<account>`, the one the browser panel uses; names only, values never read out) and `success`
(URL / text regexes that show her publish click worked, plus `postUrl` for the new post's link). Selectors are CSS or
`css:has-text(…)` / `css:near-text(…)` (text or `/regex/`) for pages with hashed class names (小红书, 抖音).
"Capture this page" (browser bar) writes a redacted DOM snapshot to `<userData>/captures/` for tuning selectors.

Publish loop (`src/main/publish/scheduler.ts`): every 30 s (and at launch) due calendar rows get one "Time to post"
notification; clicking opens `#/publish/post/<id>?go=1`, which fills the upload page (`postFill.ts`) and watches for
the adapter's success signal -> `posted` (`via: assisted`). Overdue rows show as a banner on Publish / Home.
Settings › Publishing: Open at login (menu-bar icon, `tray.ts`) and official APIs (`api/youtube.ts`: her own Google
OAuth client, PKCE + loopback in the system browser, refresh token in safeStorage via `api/vault.ts`; uploads ahead
with `publishAt`). TikTok / X / Instagram are documented as not available (`shared/publish/apiPlatforms.ts`).
