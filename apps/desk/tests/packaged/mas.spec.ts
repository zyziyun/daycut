// Packaged checks for the Mac App Store (Lite) build, run inside the real App Sandbox:
//   npm run mas:local      (builds with BUILD_EDITION=mas, signs ad hoc with the MAS entitlements, runs this file)
// A sandboxed app can only use its container, so every test profile lives in
// ~/Library/Containers/app.reelfold.desk/Data/tmp (and TMPDIR points there, which also makes it a "test profile" for
// the app's test switches). Driven over CDP like tests/packaged/packaged.spec.ts (fuses: no Node inspector).
import { chromium, expect, test, type Browser, type Page } from '@playwright/test';
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '../..');
const EXE = process.env.DESK_APP_PATH || path.join(ROOT, 'dist', 'mas-arm64', 'Reelfold.app', 'Contents', 'MacOS', 'Reelfold');
const APP = path.resolve(path.dirname(EXE), '..', '..');
const RES = path.join(APP, 'Contents', 'Resources');
const CONTAINER = path.join(os.homedir(), 'Library', 'Containers', 'app.reelfold.desk', 'Data');
const CTMP = path.join(CONTAINER, 'tmp');

test.skip(process.platform !== 'darwin' || !fs.existsSync(EXE), `no Mac App Store build at ${EXE} (npm run mas:local)`);

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const port = (srv.address() as net.AddressInfo).port;
      srv.close(() => resolve(port));
    });
  });
}

/** The Lite copy names no other download and the Lite notes link nowhere (App Review 3.1.1 / 2.3). */
async function expectNoUpsell(page: Page) {
  const text = await page.evaluate(() => document.body.innerText);
  expect(text).not.toMatch(/reelfold\.com|full version|get the full|完整版|version complète/i);
  await expect(page.getByTestId('lite-full')).toHaveCount(0);
  await expect(page.locator('[data-testid="lite-card"] a, [data-testid="lite-card"] button, [data-testid="lite-ai"] a, [data-testid="lite-ai"] button')).toHaveCount(0);
}

/** The container exists after the app's first launch: start it once (it quits when the window is closed). */
async function ensureContainer() {
  if (fs.existsSync(CONTAINER)) return;
  const p = spawn(EXE, ['--use-mock-keychain'], { stdio: 'ignore', env: { HOME: os.homedir(), PATH: '/usr/bin:/bin' } });
  for (let i = 0; i < 60 && !fs.existsSync(CONTAINER); i++) await new Promise((r) => setTimeout(r, 500));
  p.kill('SIGTERM');
  await new Promise((r) => setTimeout(r, 2000));
}

interface App {
  proc: ChildProcess;
  browser: Browser;
  page: Page;
  userData: string;
  close(): Promise<void>;
}

async function launch(extra: Record<string, string> = {}): Promise<App> {
  await ensureContainer();
  fs.mkdirSync(CTMP, { recursive: true });
  const userData = fs.mkdtempSync(path.join(CTMP, 'mas-test-'));
  // a scrubbed environment: nothing from this shell may point the app elsewhere
  const env = { HOME: os.homedir(), PATH: '/usr/bin:/bin', TMPDIR: CTMP + '/', DESK_USER_DATA: userData, DESK_HIDE_WINDOW: '1', DESK_SKIP_FIRST_RUN: '1', DESK_DISABLE_UPDATES: '1', ...extra };
  const port = await freePort();
  const proc = spawn(EXE, ['--use-mock-keychain', `--remote-debugging-port=${port}`], { env, stdio: 'ignore' });
  let browser: Browser | null = null;
  for (let i = 0; i < 120 && !browser; i++) {
    try {
      browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, { timeout: 2000 });
    } catch {
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  if (!browser) {
    proc.kill();
    throw new Error('the sandboxed app did not open a CDP endpoint (Console: look for "Sandbox" / secinit crashes)');
  }
  let page: Page | undefined;
  for (let i = 0; i < 120 && !page; i++) {
    page = browser.contexts().flatMap((c) => c.pages()).find((p) => p.url().startsWith('app://desk/'));
    if (!page) await new Promise((r) => setTimeout(r, 500));
  }
  if (!page) throw new Error('no app://desk/ window');
  const close = async () => {
    await browser!.close().catch(() => undefined);
    const exited = new Promise((r) => proc.once('exit', r));
    proc.kill('SIGTERM');
    await Promise.race([exited, new Promise((r) => setTimeout(r, 10000))]);
    if (proc.exitCode === null && proc.signalCode === null) proc.kill('SIGKILL');
    // the MAS Chromium keeps its single-instance socket in <container>/tmp/S; a killed instance (a quit that waits on a
    // dialog, e.g. "downloads are still running") leaves it behind and the next launch would quit at once
    for (let i = 0; i < 40 && fs.existsSync(path.join(CTMP, 'S')); i++) await new Promise((r) => setTimeout(r, 250));
    fs.rmSync(path.join(CTMP, 'S'), { recursive: true, force: true });
    fs.rmSync(userData, { recursive: true, force: true });
  };
  return { proc, browser, page, userData, close };
}

function entitlements(file: string): string {
  const r = spawnSync('codesign', ['-d', '--entitlements', '-', '--xml', file], { encoding: 'utf8' });
  return r.stdout + r.stderr;
}

test('every executable in the bundle runs in the sandbox: the app with the MAS entitlements, children inherit only', () => {
  const app = entitlements(APP);
  for (const k of ['app-sandbox', 'files.user-selected.read-write', 'files.bookmarks.app-scope', 'network.client', 'network.server', 'device.camera', 'device.microphone']) {
    expect(app, k).toContain(`com.apple.security.${k}`);
  }
  expect(app).toContain('com.apple.security.application-groups');
  const nested = [
    path.join(RES, 'runtime', 'python', 'bin', 'python3.12'),
    path.join(RES, 'runtime', 'ffmpeg', 'bin', 'ffmpeg'),
    path.join(RES, 'runtime', 'ffmpeg', 'bin', 'ffprobe'),
    ...fs.readdirSync(path.join(APP, 'Contents', 'Frameworks')).filter((f) => f.endsWith('.app')).map((f) => path.join(APP, 'Contents', 'Frameworks', f)),
  ];
  for (const f of nested) {
    const e = entitlements(f);
    expect(e, f).toContain('com.apple.security.app-sandbox');
    expect(e, f).toContain('com.apple.security.inherit');
    expect(e.match(/<key>/g)?.length, `${f}: exactly app-sandbox + inherit`).toBe(2);
  }
});

test('the bundle is the store build: MAS Electron, no updater feed use, no terminal, privacy manifest, export flag', () => {
  const plist = JSON.parse(spawnSync('plutil', ['-convert', 'json', '-o', '-', path.join(APP, 'Contents', 'Info.plist')], { encoding: 'utf8' }).stdout) as Record<string, unknown>;
  expect(plist.CFBundleIdentifier).toBe('app.reelfold.desk');
  expect(plist.ITSAppUsesNonExemptEncryption).toBe(false);
  expect(plist.ElectronTeamID).toBe('ZH47R7RVKB');
  expect(plist.NSCameraUsageDescription).toBeTruthy();
  expect(plist.NSMicrophoneUsageDescription).toBeTruthy();
  expect(fs.existsSync(path.join(RES, 'PrivacyInfo.xcprivacy'))).toBe(true);
  // the non-MAS Electron ships Squirrel (auto-update) and uses private APIs; the MAS build has neither
  expect(fs.existsSync(path.join(APP, 'Contents', 'Frameworks', 'Squirrel.framework'))).toBe(false);
  expect(fs.existsSync(path.join(APP, 'Contents', 'Library', 'LoginItems'))).toBe(true);
  // no in-app terminal (node-pty spawns a shell): the Lite build has no CLI sign-in
  const asarList = spawnSync('npx', ['--yes', '@electron/asar', 'list', path.join(RES, 'app.asar')], { encoding: 'utf8', cwd: ROOT }).stdout;
  expect(asarList).not.toContain('node-pty');
});

test('the real engine runs sandboxed from the bundle; Lite AI, downloads and updates', async () => {
  const app = await launch();
  try {
    const page = app.page;
    const h = await page.evaluate(async () => {
      const info = await window.desk.engineInfo();
      const res = await fetch(info.baseUrl + '/api/health', { headers: { Authorization: `Bearer ${info.token}` } });
      return { mode: info.mode, note: info.note, health: await res.json() };
    });
    expect(h.mode, h.note ?? '').toBe('real');
    expect(fs.realpathSync(h.health.python).startsWith(fs.realpathSync(path.join(RES, 'runtime')))).toBe(true);
    expect(h.health.h264_effective).toBe('h264_videotoolbox'); // VideoToolbox works inside the sandbox
    // the profile is in the container
    expect(app.userData.startsWith(CONTAINER)).toBe(true);
    expect(fs.existsSync(path.join(app.userData, 'logs', 'main.log'))).toBe(true);

    const s = await page.evaluate(() => window.desk.getSettings());
    expect(s.edition).toBe('mas');
    // subscription CLIs: reported, never run
    const ai = await page.evaluate(() => window.desk.ai.status({ refresh: true, probe: false }));
    const state = Object.fromEntries(ai.providers.map((r) => [r.provider, r.state]));
    expect(state['claude-code']).toBe('unavailable');
    expect(state.codex).toBe('unavailable');
    expect(state.anthropic).toBe('not-configured');
    const routes = await page.evaluate(() => window.desk.ai.routes());
    expect(routes.routes.default.provider).toBe('anthropic');
    await expect(page.evaluate(() => window.desk.ai.terminal({ provider: 'claude-code', action: 'login', cols: 80, rows: 24 }))).rejects.toThrow(/not available in this edition/);
    // first-run downloads are data only: no Chromium
    const assets = await page.evaluate(() => window.desk.assets.status());
    expect(assets.groups.map((g) => g.id).some((id) => id.startsWith('chromium'))).toBe(false);
    expect(assets.groups.map((g) => g.id)).toContain('asr-mlx-fast');
    // no updater: the App Store updates the app
    expect((await page.evaluate(() => window.desk.update.check())).state).toBe('disabled');
    // no usage counts
    expect((await page.evaluate(() => window.desk.usage.status())).allowed).toBe(false);

    // Settings › General / AI say what Lite does, neutrally: no other download, no link out (App Review 3.1.1 / 2.3)
    await page.evaluate(() => (location.hash = '#/settings/general'));
    await expect(page.getByTestId('lite-card')).toBeVisible({ timeout: 15000 });
    await expectNoUpsell(page);
    await page.evaluate(() => (location.hash = '#/settings/ai'));
    await expect(page.getByTestId('lite-ai')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('provider-claude-code')).toHaveCount(0);
    await expectNoUpsell(page);
  } finally {
    await app.close();
  }
});

test('first run in Lite: API keys and local models, no subscription sign-in', async () => {
  const app = await launch({ DESK_SKIP_FIRST_RUN: '0' });
  try {
    const page = app.page;
    await expect(page.getByTestId('first-run')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('lite-card')).toBeVisible();
    await expectNoUpsell(page);
    await page.getByTestId('fr-next').click();
    await expect(page.getByTestId('fr-ai')).toBeVisible();
    await expect(page.getByTestId('lite-ai')).toBeVisible();
    await expectNoUpsell(page);
    await expect(page.getByTestId('fr-sub-claude-code')).toHaveCount(0);
    await expect(page.getByTestId('fr-sub-codex')).toHaveCount(0);
  } finally {
    await app.close();
  }
});

test('the sample, end to end in the sandbox (speech model download, ASR, cleanup, render, QC)', async () => {
  test.skip(process.env.DESK_TEST_SAMPLE !== '1', 'set DESK_TEST_SAMPLE=1 (downloads ~0.5 GB of models, ~5 min)');
  test.setTimeout(20 * 60_000);
  const app = await launch();
  try {
    const page = app.page;
    await page.evaluate(() => window.desk.assets.install(['core', 'asr-mlx-fast']));
    await expect
      .poll(async () => (await page.evaluate(() => window.desk.assets.status())).groups.filter((g) => ['core', 'asr-mlx-fast'].includes(g.id) && g.installed).length, { timeout: 10 * 60_000, intervals: [5000] })
      .toBe(2);
    await page.evaluate(() => (location.hash = '#/'));
    await page.getByText('Try with a sample').first().click({ timeout: 60000 });
    await page.getByText(/^Start/).first().click({ timeout: 120000 });
    // the pilot clip is rendered and waits for her review (the publish checkpoint)
    const projects = path.join(CONTAINER, '.config', 'vstudio', 'projects');
    await expect
      .poll(
        () => {
          const logs = fs.existsSync(projects) ? fs.readdirSync(projects).flatMap((d) => fs.readdirSync(path.join(projects, d)).map((p) => path.join(projects, d, p, 'desk-pilot.log'))).filter((f) => fs.existsSync(f)) : [];
          const text = logs.map((f) => fs.readFileSync(f, 'utf8')).join('\n');
          if (/"stage-fail"/.test(text)) return `failed: ${text.match(/"stage-fail".*$/m)?.[0].slice(0, 400)}`;
          return /"stage": "export"[^\n]*\n[^\n]*/.test(text) && /"event": "stage-done"[^\n]*"stage": "qc"/.test(text) ? 'rendered' : 'running';
        },
        { timeout: 12 * 60_000, intervals: [10000] },
      )
      .toBe('rendered');
  } finally {
    await app.close();
  }
});
