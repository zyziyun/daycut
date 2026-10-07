// App identity: Reelfold (千剪), formerly "video-studio desk" and then "Daycut".
//
// Electron derives two things from the app name: the default userData folder (<appData>/<name>) and, on macOS /
// Linux, the safeStorage key ("<name> Safe Storage" in the Keychain / libsecret) that encrypts secrets.json and the
// cookies of every session (the publish browser's platform logins).
//
// The profile moves to <appData>/Reelfold once: on the first Reelfold launch, the newest old profile ("Daycut" or
// "video-studio desk") is copied (APFS clones where possible, so models cost no extra disk) into a staging folder,
// absolute paths to the old folder inside the app's own JSON files are rewritten, and the staging folder is renamed
// into place. The old folder is never modified or deleted (it stays as a backup; an older build can still open it).
//
// The encryption key cannot be moved: Chromium's cookie stores and secrets.json are encrypted with the old app's
// keychain item and cannot be re-encrypted from the inside. So the migrated profile records the old key name in
// migrated-from.json, and every launch hands that name to app.setName() before 'ready' (when Electron reads it for the
// keychain / libsecret key), then renames the app to "Reelfold" at 'ready': app.getName() is "Reelfold" for
// everything after that, while safeStorage keeps the old key (checked: a rename at 'ready' still encrypts with
// "<old> Safe Storage"). A fresh install uses "Reelfold Safe Storage". If the old key cannot be read (macOS asks once
// whether Reelfold may use it; "Deny" makes the key unreadable), stored API keys show as not set and the creator
// enters them again (SecretStore.status), and platform logins ask to sign in again.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { isPackagedBuild } from './testHooks';

export const APP_NAME = 'Reelfold';
export const APP_NAME_ZH = '千剪';
export const APP_ID = 'app.reelfold.desk';
/** productNames before the rename, newest first: their userData folders and safeStorage keys. */
export const LEGACY_NAMES = ['Daycut', 'video-studio desk'] as const;
/** the open-source monorepo (engine + this app) */
export const REPO_URL = 'https://github.com/zyziyun/reelfold';
/** written into a migrated profile: where it came from and which keychain key its encrypted data needs */
export const MIGRATION_FILE = 'migrated-from.json';

export interface Migration {
  from: string;
  /** the old app name = the safeStorage key ("<name> Safe Storage") the copied data is encrypted with */
  safeStorageName: string;
  at: string;
}

export interface Identity {
  /** the name handed to app.setName() before 'ready' (keychain / libsecret key); "Reelfold" from 'ready' on */
  internalName: string;
  userData: string;
  /** set when this launch has to copy an old profile into userData first */
  migrateFrom?: string;
  /** the profile was copied from an old install (this launch or an earlier one) */
  migrated: boolean;
}

export interface IdentityFs {
  exists(p: string): boolean;
  mtime(p: string): number;
  readText(p: string): string | null;
}

const realFs: IdentityFs = {
  exists: fs.existsSync,
  mtime: (p) => {
    try {
      return fs.statSync(p).mtimeMs;
    } catch {
      return 0;
    }
  },
  readText: (p) => {
    try {
      return fs.readFileSync(p, 'utf8');
    } catch {
      return null;
    }
  },
};

const PROFILE_MARKERS = ['settings.json', 'Local State'];
const hasProfile = (f: IdentityFs, d: string) => PROFILE_MARKERS.some((m) => f.exists(path.join(d, m)));
const profileAge = (f: IdentityFs, d: string) => Math.max(...PROFILE_MARKERS.map((m) => f.mtime(path.join(d, m))));

export function readMigration(dir: string, f: IdentityFs = realFs): Migration | null {
  const raw = f.readText(path.join(dir, MIGRATION_FILE));
  if (!raw) return null;
  try {
    const m = JSON.parse(raw) as Partial<Migration>;
    return typeof m.safeStorageName === 'string' && m.safeStorageName ? (m as Migration) : null;
  } catch {
    return null;
  }
}

/**
 * Pick the profile: an explicit override (tests), else <appData>/Reelfold when it holds a profile (with the keychain
 * name its migration recorded), else the newest old profile to migrate into <appData>/Reelfold, else a fresh one.
 */
export function resolveIdentity(
  appData: string,
  override?: string,
  f: IdentityFs = realFs,
  legacyNames: readonly string[] = LEGACY_NAMES,
): Identity {
  if (override) return { internalName: APP_NAME, userData: override, migrated: false };
  const userData = path.join(appData, APP_NAME);
  if (hasProfile(f, userData)) {
    const m = readMigration(userData, f);
    return { internalName: m?.safeStorageName ?? APP_NAME, userData, migrated: Boolean(m) };
  }
  const old = legacyNames
    .map((name) => ({ name, dir: path.join(appData, name) }))
    .filter((c) => hasProfile(f, c.dir))
    .sort((a, b) => profileAge(f, b.dir) - profileAge(f, a.dir))[0];
  if (old) return { internalName: old.name, userData, migrateFrom: old.dir, migrated: true };
  return { internalName: APP_NAME, userData, migrated: false };
}

// ---------------------------------------------------------------- the one-time copy
/** Chromium caches and per-process locks: rebuilt on demand, never copied (a copied SingletonLock blocks launch). */
const SKIP = new Set([
  'Cache',
  'Code Cache',
  'GPUCache',
  'GPUPersistentCache',
  'DawnGraphiteCache',
  'DawnWebGPUCache',
  'GraphiteDawnCache',
  'ShaderCache',
  'GrShaderCache',
  'Crashpad',
  'SingletonLock',
  'SingletonCookie',
  'SingletonSocket',
  'RunningChromeVersion',
]);
/** The app's own JSON files that may hold absolute paths into the profile (asset roots, strips, publish records). */
const REWRITE_DIRS = ['', 'assets', 'engine-data', 'publish', 'adapters'];

function rewritePaths(dir: string, from: string, to: string) {
  const needles: [string, string][] = [
    [JSON.stringify(from).slice(1, -1), JSON.stringify(to).slice(1, -1)], // as written inside a JSON string
  ];
  const walk = (d: string, depth: number) => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(d, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      const p = path.join(d, e.name);
      if (e.isDirectory() && depth > 0) walk(p, depth - 1);
      else if (e.isFile() && e.name.endsWith('.json')) {
        try {
          const s = fs.readFileSync(p, 'utf8');
          let out = s;
          for (const [a, b] of needles) out = out.split(a + '/').join(b + '/').split(a + '"').join(b + '"').split(a + '\\\\').join(b + '\\\\');
          if (out !== s) fs.writeFileSync(p, out);
        } catch {
          /* unreadable: left as copied */
        }
      }
    }
  };
  for (const sub of REWRITE_DIRS) walk(path.join(dir, sub), sub === '' ? 0 : 8);
}

/**
 * Copy the old profile `from` to `to` (which must not hold a profile yet). Staged in a sibling folder and renamed into
 * place, so a crash halfway leaves no half profile (the next launch starts over). `from` is only read.
 */
export function migrateProfile(from: string, to: string, safeStorageName: string, log: (s: string) => void = () => {}): boolean {
  const staging = `${to}.migrating-${process.pid}`;
  try {
    fs.rmSync(staging, { recursive: true, force: true });
    const t0 = Date.now();
    fs.cpSync(from, staging, {
      recursive: true,
      verbatimSymlinks: true,
      preserveTimestamps: true,
      mode: fs.constants.COPYFILE_FICLONE, // APFS / btrfs clone when possible, a plain copy otherwise
      filter: (src) => !SKIP.has(path.basename(src)) && !path.basename(src).endsWith('.tmp'),
    });
    rewritePaths(staging, from, to);
    const m: Migration = { from, safeStorageName, at: new Date().toISOString() };
    fs.writeFileSync(path.join(staging, MIGRATION_FILE), JSON.stringify(m, null, 2) + '\n');
    if (fs.existsSync(to)) {
      // an empty / profile-less folder (e.g. created by a crash reporter): keep whatever is in it beside the copy
      for (const e of fs.readdirSync(to)) {
        if (!fs.existsSync(path.join(staging, e))) fs.renameSync(path.join(to, e), path.join(staging, e));
      }
      fs.rmdirSync(to);
    }
    fs.renameSync(staging, to);
    log(`[identity] copied the profile ${from} -> ${to} in ${Date.now() - t0} ms (the old folder is kept as is)`);
    return true;
  } catch (e) {
    log(`[identity] could not copy the profile ${from} -> ${to}: ${(e as Error).message}`);
    fs.rmSync(staging, { recursive: true, force: true });
    return false;
  }
}

// ---------------------------------------------------------------- test hooks
/**
 * DESK_APP_DATA: a stand-in for <appData> (migration tests); DESK_LEGACY_NAMES ("a|b"): other old names to look for.
 * A packaged build accepts them only for a folder inside the system temp dir (see testHooks.ts).
 */
export function appDataOverride(env: NodeJS.ProcessEnv = process.env, packaged = isPackagedBuild(), tmp = os.tmpdir()): { appData?: string; legacyNames?: string[] } {
  const v = env.DESK_APP_DATA;
  if (!v) return {};
  if (packaged) {
    const real = (p: string) => {
      try {
        return fs.realpathSync(p);
      } catch {
        return path.resolve(p);
      }
    };
    const rel = path.relative(real(tmp), real(v));
    if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) return {};
  }
  const names = env.DESK_LEGACY_NAMES?.split('|').filter(Boolean);
  return { appData: v, ...(names?.length ? { legacyNames: names } : {}) };
}

/** Must run at the top of the main process, before app 'ready' and before any safeStorage / session use. */
export function applyIdentity(app: Electron.App, override = process.env.DESK_USER_DATA, log: (s: string) => void = console.error): Identity {
  const o = appDataOverride();
  const appData = o.appData ?? app.getPath('appData');
  let id = resolveIdentity(appData, override, realFs, o.legacyNames ?? LEGACY_NAMES);
  const lines: string[] = []; // logged once userData is set (the log file lives in it)
  if (id.migrateFrom && !migrateProfile(id.migrateFrom, id.userData, id.internalName, (s) => lines.push(s))) {
    // the copy failed (disk full, permissions): run on the old profile in place rather than start empty
    id = { internalName: id.internalName, userData: id.migrateFrom, migrated: false };
  }
  app.setName(id.internalName);
  if (id.internalName !== APP_NAME) app.once('ready', () => app.setName(APP_NAME)); // runs before whenReady() callbacks
  app.setPath('userData', id.userData);
  lines.forEach(log);
  if (process.platform === 'win32') app.setAppUserModelId(APP_ID); // toasts + taskbar match the installer shortcut
  return id;
}
