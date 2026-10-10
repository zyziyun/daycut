// Runs the app with the Studio off (DESK_STUDIO=0): the pages before the Studio (2026-10 review step 7) stay
// supported behind its flag, and this spec covers them.
// The Reelfold rename, end to end with real Electron safeStorage: an old profile (written under the old app name, so
// its API key and cookies are encrypted with the old "<name> Safe Storage" keychain item) is copied into
// <appData>/Reelfold on the first launch; settings, the encrypted key and a platform login cookie still read; the old
// folder is left as it was; a second launch reuses the copy. DESK_APP_DATA / DESK_LEGACY_NAMES point the app at a
// temp appData and a test-only legacy name, so the real profile and keychain items are never touched.
// Playwright's Electron launcher switches Chromium to a mock keychain (--use-mock-keychain), which would make every
// key "readable": the first launch is therefore a plain child process on the real keychain, checked through the
// counts the app logs for a migrated profile (identity line in main.log); the second launch uses Playwright.
import { _electron as electron, expect, test } from '@playwright/test';
import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

const LEGACY = 'Reelfold E2E Legacy';
const ROOT = path.resolve(import.meta.dirname, '../..');
const appData = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-migrate-'));
const oldDir = path.join(appData, LEGACY);
const newDir = path.join(appData, 'Reelfold');

test.describe.configure({ mode: 'serial' });

const ENV = {
  ...process.env,
  DESK_ENGINE_MOCK: '1',
  DESK_APP_DATA: appData,
  DESK_LEGACY_NAMES: LEGACY,
  DESK_USER_DATA: '',
  VSTUDIO_HOME: path.join(appData, 'vhome'),
  DESK_HISTORY_WATCH: '',
  DESK_STUDIO: '0', DESK_HIDE_WINDOW: '1',
  DESK_SHARED_CACHE: path.join(appData, 'cache'),
  DESK_HF_HUB: '',
  DESK_SKIP_FIRST_RUN: '1',
  VITE_DEV_SERVER_URL: '',
};
const electronBin = createRequire(path.join(ROOT, 'package.json'))('electron') as unknown as string;
const launch = () => electron.launch({ args: [ROOT], env: ENV });
const mainLog = () => {
  try {
    return fs.readFileSync(path.join(newDir, 'logs/main.log'), 'utf8');
  } catch {
    return '';
  }
};

/** Run the app as a plain process (real keychain) until its migrated-profile report is logged. */
async function runUntilReport(): Promise<string> {
  const child = spawn(electronBin, [ROOT], { env: ENV, stdio: 'ignore' });
  try {
    await expect.poll(() => /\[identity\] migrated profile/.test(mainLog()), { timeout: 45000 }).toBe(true);
  } finally {
    child.kill('SIGTERM');
    await new Promise((r) => child.once('exit', r));
  }
  return mainLog().split('\n').find((l) => l.includes('[identity] migrated profile')) ?? '';
}

async function readBack(app: Awaited<ReturnType<typeof launch>>) {
  const page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//);
  const main = await app.evaluate(({ app: a }) => ({ name: a.getName(), userData: a.getPath('userData') }));
  const settings = await page.evaluate(() => window.desk.getSettings());
  return { main, settings };
}

test('an old profile is copied into Reelfold once and its encrypted data still reads (real keychain)', async () => {
  const out = execFileSync(electronBin, [path.join(ROOT, 'tests/e2e/fixture/legacyProfile.mjs'), appData, LEGACY], { encoding: 'utf8' });
  expect(out).toContain('LEGACY_PROFILE_OK');
  const before = fs.readFileSync(path.join(oldDir, 'settings.json'), 'utf8');

  const report = await runUntilReport();
  expect(report).toContain(`keychain key "${LEGACY} Safe Storage"`);
  expect(report).toContain('API keys readable 1/1'); // secrets.json decrypts with the old keychain item
  expect(report).toContain('sessions with readable cookies 1/1'); // the publish browser login survives
  expect(mainLog().match(/copied the profile/g)?.length).toBe(1);

  const rec = JSON.parse(fs.readFileSync(path.join(newDir, 'migrated-from.json'), 'utf8'));
  expect(rec.safeStorageName).toBe(LEGACY);
  expect(JSON.parse(fs.readFileSync(path.join(newDir, 'settings.json'), 'utf8'))).toMatchObject({ lang: 'fr', accent: 'red' });
  // paths inside JSON strings (Windows backslashes are escaped there)
  const inJson = (p: string) => JSON.stringify(p).slice(1, -1);
  expect(fs.readFileSync(path.join(newDir, 'assets/installed.json'), 'utf8')).toContain(inJson(path.join(newDir, 'assets')));
  // the old folder is kept, unchanged
  expect(fs.readFileSync(path.join(oldDir, 'settings.json'), 'utf8')).toBe(before);
  expect(fs.readFileSync(path.join(oldDir, 'assets/installed.json'), 'utf8')).toContain(inJson(path.join(oldDir, 'assets')));
});

test('the second launch reuses the copy (no new migration) and still decrypts', async () => {
  const rec = fs.readFileSync(path.join(newDir, 'migrated-from.json'), 'utf8');
  fs.writeFileSync(path.join(oldDir, 'settings.json'), JSON.stringify({ lang: 'en', firstRunDone: true }));
  const app = await launch();
  try {
    const r = await readBack(app);
    expect(r.main.name).toBe('Reelfold');
    expect(fs.realpathSync(r.main.userData)).toBe(fs.realpathSync(newDir));
    expect(r.settings.lang).toBe('fr'); // the Reelfold copy, not the old folder
    expect(r.settings.accent).toBe('red');
  } finally {
    await closeApp(app);
  }
  expect(fs.readFileSync(path.join(newDir, 'migrated-from.json'), 'utf8')).toBe(rec);
  expect(mainLog().match(/copied the profile/g)?.length).toBe(1);
});

// macOS / Linux: the key lives in a keychain item named after the app. Windows' DPAPI key sits in the profile's own
// Local State (copied with it), so the app name does not matter there and this control does not apply.
test('control: with the wrong keychain key the same data does not read (and the app says so)', async () => {
  test.skip(process.platform === 'win32', 'DPAPI: the key travels with the profile');
  const rec = path.join(newDir, 'migrated-from.json');
  const saved = fs.readFileSync(rec, 'utf8');
  fs.writeFileSync(rec, JSON.stringify({ ...JSON.parse(saved), safeStorageName: 'Reelfold E2E Other' }));
  fs.writeFileSync(path.join(newDir, 'logs/main.log'), '');
  try {
    const report = await runUntilReport();
    expect(report).toContain('keychain key "Reelfold E2E Other Safe Storage"');
    expect(report).toContain('API keys readable 0/1');
    // (cookies are only encrypted with the keychain key in packaged builds, by the enableCookieEncryption fuse:
    // tests/packaged covers them)
  } finally {
    fs.writeFileSync(rec, saved);
  }
});
