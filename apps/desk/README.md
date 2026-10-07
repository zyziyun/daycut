# Daycut (日剪) desk app

Electron desktop workbench for the [video-studio](../../README.md) skill's engine (`python -m vstudio.batch`,
`vstudio.project`), in `apps/desk/` of the video-studio monorepo. MIT, like the rest of the repo (see `LICENSE`).
Formerly the separate `video-studio-desk` repo (history kept via git subtree).
Batches → board → review → job detail (transcript edits) → publish (built-in browser with assisted fill).

```bash
npm install          # here or at the repo root: one npm workspace install (node_modules at the repo root)
npm run dev          # Vite + Electron; engine sidecar starts automatically, using this repo's lib/ (../..)
                     # macOS: runs as "Daycut" from a cached Daycut.app copy of Electron (build/.cache/dev-app)
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

Engine: `engine/server.py` (stdlib HTTP, 127.0.0.1, random port, per-launch token). It finds the engine repo via
Settings → `VSTUDIO_ENGINE_PATH` → the monorepo root (`../..`) → a sibling `../video-studio` (old layout), and Python via Settings → `DESK_PYTHON` → miniconda/Homebrew.
`DESK_ENGINE_MOCK=1` forces the in-memory mock engine (also used when `vstudio` cannot be imported).

AI accounts & models (Settings → AI accounts & models, `#/settings/ai`): provider status from the engine
(`python -m vstudio.llm auth status --json`; Claude Code is checked with a one-line round-trip, so an expired login
shows as expired), CLI logins in an in-app terminal (xterm.js + node-pty, else a Python PTY, else `script`; the command
comes from `vstudio.llm auth login`, API keys / base URLs are removed from its environment), API keys in the OS
keychain, and which provider each task uses (default + per-task override + ordered fallbacks). The choices are saved
in the desk settings and written to `<userData>/llm-routes.json` (`VSTUDIO_LLM_ROUTES_FILE`, read by the engine on
every call); the persona's `llm:` routes are the starting values. `DESK_AI_MOCK=<dir>` (status.json, login.json,
routes.json, test.json) stands in for the engine in tests; `DESK_NO_PTY=1` forces the fallback terminal.

Publish adapters: `adapters/*.json` (schema: `src/shared/publish/adapterSchema.ts`). Override or add adapters
without rebuilding in `~/Library/Application Support/Daycut/adapters/` (`video-studio desk/adapters/` for installs
from before the rename). Selectors marked
`"status": "unverified"` were written without a live session — verify them, then set `verified` + `lastVerified`.
The app never clicks publish; there is no way to express a click in an adapter.
