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

Publish adapters: `adapters/*.json` (schema: `src/shared/publish/adapterSchema.ts`). Override or add adapters
without rebuilding in `~/Library/Application Support/video-studio-desk/adapters/`. Selectors marked
`"status": "unverified"` were written without a live session — verify them, then set `verified` + `lastVerified`.
The app never clicks publish; there is no way to express a click in an adapter.
