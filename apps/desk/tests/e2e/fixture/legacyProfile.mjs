/* global process, console */
// Stands in for an old install (Daycut / video-studio desk) in tests/e2e/migration.spec.ts: under the old app name
// (= the old keychain key "<name> Safe Storage"), writes a profile with settings, an API key encrypted by
// safeStorage and a login cookie in a persistent publish partition, then quits.
//   electron legacyProfile.mjs <appData> <legacy name>
import { app, safeStorage, session } from 'electron';
import fs from 'node:fs';
import path from 'node:path';

const [appData, name] = process.argv.slice(-2);
const dir = path.join(appData, name);
app.setName(name);
app.setPath('userData', dir);
app.whenReady().then(async () => {
  try {
    fs.mkdirSync(path.join(dir, 'assets', 'chromium', '1'), { recursive: true });
    fs.writeFileSync(path.join(dir, 'settings.json'), JSON.stringify({ lang: 'fr', accent: 'red', firstRunDone: true, accounts: [{ platform: 'douyin', name: 'main' }] }));
    fs.writeFileSync(path.join(dir, 'secrets.json'), JSON.stringify({ openai: safeStorage.encryptString('legacy-test-key-0123456789').toString('base64') }));
    fs.writeFileSync(path.join(dir, 'assets', 'installed.json'), JSON.stringify({ chromium: { root: path.join(dir, 'assets', 'chromium', '1'), sha256: [] } }));
    const ses = session.fromPartition('persist:douyin-main');
    await ses.cookies.set({ url: 'https://creator.douyin.com', name: 'sessionid', value: 'legacy-cookie-value', expirationDate: Date.now() / 1000 + 86400 });
    await ses.cookies.flushStore();
    console.log('LEGACY_PROFILE_OK');
  } catch (e) {
    console.error('LEGACY_PROFILE_FAIL', e);
    process.exitCode = 1;
  }
  app.quit();
});
