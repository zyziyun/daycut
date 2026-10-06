# video-studio desk

Electron desktop workbench for the [video-studio](../video-studio) skill's batch engine (`python -m vstudio.batch`).
Batches → board → review → job detail (transcript edits) → publish (built-in browser with assisted fill).

```bash
npm install
npm run dev          # Vite + Electron; engine sidecar starts automatically
npm run test         # vitest (unit) + python unittest (engine/tests)
npm run test:e2e     # builds, then Playwright Electron smoke + CDP fill fixture
npm run lint         # eslint + tsc
npm run build:mac    # .app in dist/ (uses build/runtime if present)
npm run runtime      # bundled engine runtime for this machine -> build/runtime/<platform>-<arch>
npm run dist:mac:unsigned && npm run test:packaged   # DMG with the bundled engine + packaged-app check
```

Distribution (signed/notarized DMG, Windows installer, auto-update, store plans): [docs/RELEASING.md](docs/RELEASING.md).
Installed builds run the engine from the bundled runtime (`resources/runtime`: Python, LGPL ffmpeg, video-studio at a
pinned commit) and download fonts/models on first run; Settings → Python / video-studio repo still override it.

Engine: `engine/server.py` (stdlib HTTP, 127.0.0.1, random port, per-launch token). It finds the engine repo via
Settings → `VSTUDIO_ENGINE_PATH` → `../video-studio`, and Python via Settings → `DESK_PYTHON` → miniconda/Homebrew.
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
without rebuilding in `~/Library/Application Support/video-studio-desk/adapters/`. Selectors marked
`"status": "unverified"` were written without a live session — verify them, then set `verified` + `lastVerified`.
The app never clicks publish; there is no way to express a click in an adapter.
