// macOS dev identity. The bold app menu in the menu bar, the Dock tooltip and Cmd-Tab take the name from the bundle's
// Info.plist (CFBundleName), which app.setName() cannot change: launched from node_modules/electron, the app says
// "Electron" with the atom icon. `npm run dev` therefore launches a copy of Electron.app renamed to Daycut.app
// (CFBundleName / CFBundleDisplayName "Daycut", bundle id com.vstudio.desk.dev, the Daycut icon.icns), made once
// under build/.cache/dev-app and rebuilt when the Electron version, the icon or this recipe changes. The original
// bundle in node_modules is never modified. Other platforms (and any failure here) use the stock binary.
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';

const RECIPE = 1; // bump when the steps below change
export const DEV_BUNDLE_ID = 'com.vstudio.desk.dev';
export const DEV_APP_NAME = 'Daycut';

/** What the cached copy was built from; any change rebuilds it. */
export function devAppStamp({ electronVersion, iconBytes }) {
  const icon = crypto.createHash('sha1').update(iconBytes).digest('hex').slice(0, 12);
  return JSON.stringify({ recipe: RECIPE, electron: electronVersion, icon, name: DEV_APP_NAME, id: DEV_BUNDLE_ID });
}

/** Info.plist keys set on the copy. */
export function devPlistEdits() {
  return { CFBundleName: DEV_APP_NAME, CFBundleDisplayName: DEV_APP_NAME, CFBundleIdentifier: DEV_BUNDLE_ID, CFBundleIconFile: 'daycut.icns' };
}

function plistSet(plist, key, value) {
  try {
    execFileSync('plutil', ['-replace', key, '-string', value, plist]);
  } catch {
    execFileSync('plutil', ['-insert', key, '-string', value, plist]);
  }
}

/**
 * Path of the Electron binary `npm run dev` should launch: <cache>/Daycut.app/Contents/MacOS/Electron on macOS
 * (built if missing or stale), else `electronPath`.
 */
export function devElectronBinary({ root, electronPath, log = console.log }) {
  if (process.platform !== 'darwin') return electronPath;
  try {
    const require = createRequire(path.join(root, 'package.json'));
    const electronVersion = require('electron/package.json').version;
    const srcApp = path.resolve(electronPath, '../../..'); // .../Electron.app/Contents/MacOS/Electron -> .../Electron.app
    const icns = path.join(root, 'packaging/resources/icon.icns');
    const cacheDir = path.join(root, 'build/.cache/dev-app');
    const app = path.join(cacheDir, `${DEV_APP_NAME}.app`);
    const bin = path.join(app, 'Contents/MacOS', path.basename(electronPath));
    const stampFile = path.join(cacheDir, 'stamp.json');
    const stamp = devAppStamp({ electronVersion, iconBytes: fs.readFileSync(icns) });
    if (fs.existsSync(bin) && fs.existsSync(stampFile) && fs.readFileSync(stampFile, 'utf8') === stamp) return bin;

    log(`[dev] building ${path.relative(root, app)} (Electron ${electronVersion}, named ${DEV_APP_NAME})`);
    fs.rmSync(cacheDir, { recursive: true, force: true });
    fs.mkdirSync(cacheDir, { recursive: true });
    try {
      execFileSync('cp', ['-cR', srcApp, app]); // APFS clone: instant, no extra disk
    } catch {
      fs.rmSync(app, { recursive: true, force: true });
      execFileSync('ditto', [srcApp, app]);
    }
    const plist = path.join(app, 'Contents/Info.plist');
    for (const [k, v] of Object.entries(devPlistEdits())) plistSet(plist, k, v);
    fs.copyFileSync(icns, path.join(app, 'Contents/Resources/daycut.icns'));
    // the edited Info.plist breaks the stock ad-hoc seal: re-seal the outer bundle (the helpers are untouched)
    execFileSync('codesign', ['--force', '--sign', '-', app], { stdio: 'ignore' });
    fs.writeFileSync(stampFile, stamp);
    return bin;
  } catch (e) {
    log(`[dev] could not make the Daycut dev app (${e.message.split('\n')[0]}); using the stock Electron.app`);
    return electronPath;
  }
}
