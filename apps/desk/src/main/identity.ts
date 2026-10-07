// App identity across the video-studio desk -> Daycut rename.
//
// Electron derives two things from the app name: the default userData folder (<appData>/<name>) and, on macOS /
// Linux, the safeStorage key ("<name> Safe Storage" in the Keychain / libsecret) that encrypts secrets.json and the
// publish browser's cookies. Renaming the app outright would orphan both: settings, API keys and platform logins
// would silently disappear. So an existing install keeps running under its old internal name and folder (nothing is
// copied or re-encrypted), and only a fresh install uses "Daycut". Everything the creator sees (bundle name, menus,
// About, window title, notifications) says Daycut either way.
// Electron reads the name for the keychain / libsecret key once, before 'ready' (PostCreateMainMessageLoop), so a
// legacy install is renamed back to "Daycut" as soon as 'ready' fires: app.getName() is "Daycut" for everything after
// that, and safeStorage keeps the old key (checked: a rename at 'ready' still encrypts with "<old> Safe Storage").
// Kept in step with electron-builder.config.cjs: appId stays com.vstudio.desk.
import fs from 'node:fs';
import path from 'node:path';

export const APP_NAME = 'Daycut';
export const APP_NAME_ZH = '日剪';
export const APP_ID = 'com.vstudio.desk';
/** productName before the rename: the userData folder and safeStorage key of every existing install. */
export const LEGACY_NAME = 'video-studio desk';
/** the open-source monorepo (engine + this app) */
export const REPO_URL = 'https://github.com/zyziyun/daycut';

export interface Identity {
  /** the name handed to app.setName() before 'ready' (keychain / libsecret key); "Daycut" from 'ready' on */
  internalName: string;
  userData: string;
  legacy: boolean;
}

/**
 * Pick the profile: an explicit override (tests), else the old "video-studio desk" folder when it holds a profile
 * and no Daycut profile exists yet, else <appData>/Daycut.
 */
export function resolveIdentity(appData: string, override?: string, exists: (p: string) => boolean = fs.existsSync): Identity {
  if (override) return { internalName: APP_NAME, userData: override, legacy: false };
  const legacyDir = path.join(appData, LEGACY_NAME);
  const newDir = path.join(appData, APP_NAME);
  const hasProfile = (d: string) => exists(path.join(d, 'settings.json')) || exists(path.join(d, 'Local State'));
  if (!hasProfile(newDir) && exists(legacyDir)) return { internalName: LEGACY_NAME, userData: legacyDir, legacy: true };
  return { internalName: APP_NAME, userData: newDir, legacy: false };
}

/** Must run at the top of the main process, before app 'ready' and before any safeStorage / session use. */
export function applyIdentity(app: Electron.App, override = process.env.DESK_USER_DATA): Identity {
  const id = resolveIdentity(app.getPath('appData'), override);
  app.setName(id.internalName);
  if (id.internalName !== APP_NAME) app.once('ready', () => app.setName(APP_NAME)); // runs before whenReady() callbacks
  app.setPath('userData', id.userData);
  if (process.platform === 'win32') app.setAppUserModelId(APP_ID); // toasts + taskbar match the installer shortcut
  return id;
}
