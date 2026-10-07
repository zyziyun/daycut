// Build edition: the full download (Developer ID, GitHub Releases) or the Mac App Store "Lite" build.
// Chosen at build time: BUILD_EDITION=mas npm run build (scripts/build.mjs and vite.config.ts define
// __REELFOLD_EDITION__). Unset, or anything else, is the full edition. The Lite build runs inside the App Sandbox:
//   - AI through API keys or local model servers only (no Claude Code / Codex subscription login: a sandboxed app
//     cannot run the CLIs the user installed, and has no terminal);
//   - only folders the user picked (security-scoped bookmarks) are read, watched or kept across launches;
//   - no in-app updater (the App Store updates the app), no anonymous usage counts;
//   - first-run downloads are data only (speech models, fonts): no Chromium download; HTML covers render in the
//     app's own Chromium instead (main/htmlRender.ts).
// Pure: shared by main, preload, renderer and tests.
declare const __REELFOLD_EDITION__: string | undefined;

export type Edition = 'full' | 'mas';

export function editionFrom(v: string | undefined | null): Edition {
  return v === 'mas' ? 'mas' : 'full';
}

export const EDITION: Edition = editionFrom(typeof __REELFOLD_EDITION__ === 'string' ? __REELFOLD_EDITION__ : undefined);

/** The Mac App Store build (sandboxed). */
export const IS_LITE = EDITION === 'mas';

/** Where the full edition is downloaded (the website's download button). */
export const FULL_DOWNLOAD_URL = 'https://reelfold.com';

/** What the edition can do. The full edition can do everything. */
export interface EditionCaps {
  /** sign in with the Claude Code / Codex CLI subscription (in-app terminal) */
  cliLogins: boolean;
  /** read / watch any folder by path (Lite: only folders the user picked) */
  anyFolder: boolean;
  /** electron-updater from GitHub Releases */
  autoUpdate: boolean;
  /** opt-in anonymous usage counts */
  usageCounts: boolean;
  /** download a headless Chromium on first run (Lite: the app's own Chromium renders HTML) */
  chromiumDownload: boolean;
}

export function capsFor(e: Edition): EditionCaps {
  const full = e === 'full';
  return { cliLogins: full, anyFolder: full, autoUpdate: full, usageCounts: full, chromiumDownload: full };
}

export const CAPS: EditionCaps = capsFor(EDITION);
