// The in-app update against a real electron-updater feed (latest-mac.yml + a zip with its sha512, from a local
// server; DESK_UPDATE_FEED writes it as the dev build's app-update.yml). Real: the launch check, the feed parsing,
// the download with its progress, the checksum, the release notes. Faked in this test only: Squirrel.Mac (Electron's
// native autoUpdater), which cannot stage an update for an unsigned dev Electron - its setFeedURL / checkForUpdates /
// quitAndInstall are replaced from the test, and its "update-downloaded" is emitted by the test.
//   - checked on launch; the sidebar pill shows the download progress, then "Update ready · Restart"
//   - a one-time card "Reelfold 0.2.5 is ready" with What's new (the notes from the feed) and Later
//   - a project running: Restart asks; "Restart when done" waits and restarts once it finishes
//   - Settings › General › Updates: version, last checked, up-to-date / failure in plain words
// macOS only (the feed and Squirrel are macOS's; Windows would run the downloaded "installer" on quit).
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

test.skip(process.platform !== 'darwin', 'macOS update feed (latest-mac.yml / Squirrel.Mac)');
test.describe.configure({ mode: 'serial' });

const ROOT = path.resolve(import.meta.dirname, '../..');
const NEXT = '0.2.99';
const SHOTS = process.env.UPDATE_SHOTS; // folder for the screenshots (ux/update)
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-update-'));
const watch = path.join(tmp, 'work');
const statusFile = path.join(watch, 'clip-run', '.vstudio', 'status.json');
const ZIP = `Reelfold-${NEXT}-${process.arch === 'arm64' ? 'arm64-' : ''}mac.zip`;
const zipBytes = crypto.randomBytes(3 * 1024 * 1024);
const sha512 = crypto.createHash('sha512').update(zipBytes).digest('base64');
const NOTES = '## Reelfold 0.2.99\n\n- **Update prompt**: restart to update in one click\n- Fixes: the engine keeps running when another app pokes it\n';

let server: http.Server;
let feed = '';
let feedMode: 'update' | 'none' | 'broken' = 'update';
let releaseRest: () => void = () => {};
const rest = new Promise<void>((r) => (releaseRest = r));
let app: ElectronApplication;
let page: Page;

async function launch(profile: string): Promise<ElectronApplication> {
  const a = await electron.launch({
    args: [ROOT],
    env: {
      ...(process.env as Record<string, string>),
      DESK_ENGINE_MOCK: '1',
      DESK_USER_DATA: path.join(tmp, profile),
      VSTUDIO_HOME: path.join(tmp, 'vhome'),
      DESK_SHARED_CACHE: path.join(tmp, 'cache'),
      DESK_HF_HUB: '',
      DESK_HISTORY_WATCH: watch,
      DESK_HIDE_WINDOW: '1',
      DESK_SKIP_FIRST_RUN: '1',
      DESK_DISABLE_UPDATES: '',
      DESK_UPDATE_FEED: feed,
      VITE_DEV_SERVER_URL: '',
    },
  });
  // Squirrel.Mac stand-in (test only): record what the app asks of it
  await a.evaluate(({ autoUpdater }) => {
    const g = globalThis as unknown as { __squirrel: { feed: number; check: number; install: number } };
    g.__squirrel = { feed: 0, check: 0, install: 0 };
    autoUpdater.setFeedURL = () => void g.__squirrel.feed++;
    autoUpdater.checkForUpdates = () => void g.__squirrel.check++;
    autoUpdater.quitAndInstall = () => void g.__squirrel.install++;
  });
  return a;
}

async function open(a: ElectronApplication): Promise<Page> {
  const p = await a.firstWindow();
  await p.setViewportSize({ width: 1280, height: 800 });
  await p.waitForURL(/^app:\/\/desk\//);
  return p;
}

function yml(version: string) {
  return [
    `version: ${version}`,
    'files:',
    `  - url: ${ZIP}`,
    `    sha512: ${sha512}`,
    `    size: ${zipBytes.length}`,
    `path: ${ZIP}`,
    `sha512: ${sha512}`,
    "releaseDate: '2026-10-10T12:00:00.000Z'",
    'releaseNotes: |',
    ...NOTES.trimEnd().split('\n').map((l) => `  ${l}`),
    '',
  ].join('\n');
}

/** a work folder an external run (Claude Code + the skill) is rendering: vstudio.batch.livestatus */
function heartbeat(status: string) {
  fs.mkdirSync(path.dirname(statusFile), { recursive: true });
  fs.mkdirSync(path.join(watch, 'clip-run', 'work'), { recursive: true });
  fs.writeFileSync(path.join(watch, 'clip-run', 'work', 'compose.py'), '');
  fs.writeFileSync(path.join(watch, 'clip-run', 'work', 'render.log'), 'rendering clip B');
  const now = Date.now() / 1000;
  fs.writeFileSync(statusFile, JSON.stringify({ status, stage: 'render', progress: 0.4, message: 'clip B', eta: 120, started: now - 90, heartbeat: now, pid: process.pid, host: os.hostname(), updated_by: 'workflow' }));
}

async function shot(name: string, scrollTo?: string) {
  if (!SHOTS) return;
  fs.mkdirSync(SHOTS, { recursive: true });
  if (scrollTo) await page.getByTestId(scrollTo).evaluate((el) => el.scrollIntoView({ block: 'center' }));
  await page.waitForTimeout(400); // entry animations
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

test.beforeAll(async () => {
  server = http.createServer((req, res) => {
    const url = (req.url ?? '').split('?')[0];
    if (url === '/latest-mac.yml') {
      if (feedMode === 'broken') return res.writeHead(500).end('feed down');
      return res.writeHead(200, { 'content-type': 'text/yaml' }).end(yml(feedMode === 'none' ? '0.0.1' : NEXT));
    }
    if (url === `/${ZIP}`) {
      // 40 % at once, then a trickle (the updater reports progress about once a second while bytes flow) up to
      // 60 %, the rest once the test has seen the progress
      res.writeHead(200, { 'content-type': 'application/zip', 'content-length': String(zipBytes.length) });
      let sent = Math.floor(zipBytes.length * 0.4);
      res.write(zipBytes.subarray(0, sent));
      const step = Math.floor(zipBytes.length * 0.01);
      const trickle = setInterval(() => {
        if (sent + step > zipBytes.length * 0.6) return;
        res.write(zipBytes.subarray(sent, sent + step));
        sent += step;
      }, 250);
      void rest.then(() => {
        clearInterval(trickle);
        res.end(zipBytes.subarray(sent));
      });
      return;
    }
    res.writeHead(404).end();
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  feed = `http://127.0.0.1:${(server.address() as AddressInfo).port}/`;
  // a download cached by an earlier run would skip the progress
  fs.rmSync(path.join(os.homedir(), 'Library', 'Caches', 'reelfold-dev-updater'), { recursive: true, force: true });
  heartbeat('running');
  app = await launch('profile');
  page = await open(app);
});

test.afterAll(async () => {
  await closeApp(app);
  server?.close();
});

const squirrel = () => app.evaluate(() => (globalThis as unknown as { __squirrel: { feed: number; check: number; install: number } }).__squirrel);

test('found on launch: the pill shows the download, then the one-time card offers the restart', async () => {
  test.setTimeout(90000);
  await expect(page.getByTestId('running-badge')).toHaveText('1', { timeout: 20000 });
  const pill = page.getByTestId('update-pill');
  await expect(pill).toHaveAttribute('data-state', 'downloading', { timeout: 30000 }); // the launch check (10 s)
  await expect(pill).toContainText('Downloading update');
  await expect(pill.getByTestId('update-percent')).toHaveText(/^[1-9]\d?%$/, { timeout: 10000 }); // 40 % arrived, the rest is held
  await shot('1-pill-downloading');
  releaseRest();
  await expect(pill).toHaveAttribute('data-state', 'ready', { timeout: 30000 });
  await expect(pill).toContainText('Update ready');
  await expect(pill).toContainText(`Reelfold ${NEXT}`);
  const card = page.getByTestId('update-card');
  await expect(card).toBeVisible();
  await expect(card).toContainText(`Reelfold ${NEXT} is ready`);
  await expect(card.getByTestId('update-card-restart')).toHaveText('Restart to update');
  await shot('2-ready-card');
  expect((await squirrel()).feed).toBe(1); // the verified zip was handed to Squirrel to stage
});

test("What's new shows the feed's release notes as text", async () => {
  await page.getByTestId('update-card-notes').click();
  const notes = page.getByTestId('update-notes');
  await expect(notes).toContainText('Update prompt: restart to update in one click');
  await expect(notes.locator('li')).toHaveCount(2);
  await expect(notes).not.toContainText('**');
  await shot('3-whats-new');
  await page.getByTestId('update-notes-close').click();
  await expect(notes).toHaveCount(0);
});

test('Later hides the card for this launch; the pill stays', async () => {
  await page.getByTestId('update-card-later').click();
  await expect(page.getByTestId('update-card')).toHaveCount(0);
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('nav-home').click();
  await expect(page.getByTestId('update-card')).toHaveCount(0);
  await expect(page.getByTestId('update-pill')).toHaveAttribute('data-state', 'ready');
});

test('Settings › General › Updates: version, last checked, ready to install', async () => {
  await page.getByTestId('nav-settings').click();
  const g = page.getByTestId('settings-updates');
  await expect(g).toBeVisible();
  await expect(g.getByTestId('update-version')).toContainText(/Reelfold \d+\.\d+\.\d+/);
  await expect(g.getByTestId('update-checked')).toContainText(/Last checked (now|just now|\d+ (min|minute)|.*ago)/i);
  await expect(g.getByTestId('update-status')).toContainText(`Reelfold ${NEXT} is downloaded and ready to install.`);
  await expect(g.getByTestId('update-settings-restart')).toBeVisible();
  await shot('4-settings-ready', 'settings-updates');
  if (SHOTS) {
    // the same in 简体中文 (the pill on Home, Settings › 更新)
    await page.getByTestId('lang-zh-CN').click();
    await expect(g.getByTestId('update-status')).toContainText(`千剪 ${NEXT} 已下载，可以安装。`);
    await shot('4b-settings-ready-zh', 'settings-updates');
    await page.evaluate(() => (location.hash = '#/'));
    await expect(page.getByTestId('update-pill')).toContainText('更新已就绪');
    await shot('4c-pill-ready-zh');
    await page.evaluate(() => (location.hash = '#/settings/general'));
    await page.getByTestId('lang-en').click();
    await expect(g.getByTestId('update-status')).toContainText('ready to install');
  }
  await page.evaluate(() => (location.hash = '#/'));
});

test('a project running: Restart asks; "Restart when done" waits, then restarts once it finishes', async () => {
  await page.getByTestId('update-ready').click();
  const ask = page.getByTestId('update-running');
  await expect(ask).toBeVisible();
  await expect(page.getByRole('dialog', { name: '1 project is running' })).toBeVisible();
  await shot('5-running-ask');
  await page.getByTestId('update-running-later').click();
  const pill = page.getByTestId('update-pill');
  await expect(pill).toHaveAttribute('data-state', 'waiting');
  await expect(pill).toContainText('Restarts when 1 project finishes');
  await shot('6-pill-waiting');
  expect((await squirrel()).install).toBe(0);
  heartbeat('done'); // the run finishes
  await expect(page.getByTestId('running-badge')).toHaveCount(0, { timeout: 15000 });
  // the app asked electron-updater to quit and install; it waits for Squirrel to have the update staged
  await expect.poll(() => fs.readFileSync(path.join(tmp, 'profile', 'logs', 'main.log'), 'utf8'), { timeout: 10000 }).toContain(`[update] restarting to install ${NEXT}`);
  await expect(pill).toContainText('Restarting…');
  await app.evaluate(({ autoUpdater }) => autoUpdater.emit('update-downloaded'));
  await expect.poll(async () => (await squirrel()).install, { timeout: 10000 }).toBe(1); // Squirrel: quit, install, relaunch
});

test('a failed check says so in plain words in Settings (no pill for an offline check); Try again -> up to date', async () => {
  test.setTimeout(90000);
  await closeApp(app);
  feedMode = 'broken';
  heartbeat('done');
  app = await launch('profile-2');
  page = await open(app);
  await page.evaluate(() => (location.hash = '#/settings/general'));
  const g = page.getByTestId('settings-updates');
  const status = g.getByTestId('update-status');
  await expect(status).toHaveAttribute('data-state', 'error', { timeout: 30000 }); // the launch check failed
  await expect(status).toContainText('Couldn’t check for updates. Check your internet connection, then try again.');
  await expect(status).toContainText('500'); // the updater's own line, smaller
  await expect(g.getByTestId('update-checked')).toContainText('Last checked');
  await shot('7-settings-check-failed', 'settings-updates');
  await page.evaluate(() => (location.hash = '#/'));
  await expect(page.getByTestId('nav-home')).toBeVisible();
  await expect(page.getByTestId('update-pill')).toHaveCount(0);
  await page.evaluate(() => (location.hash = '#/settings/general'));
  feedMode = 'none';
  await page.getByTestId('update-retry').click();
  await expect(status).toHaveAttribute('data-state', 'none', { timeout: 20000 });
  await expect(status).toContainText('You’re up to date.');
  await page.getByTestId('update-check').click(); // the button works again and again
  await expect(status).toContainText('You’re up to date.', { timeout: 20000 });
  await shot('8-settings-up-to-date', 'settings-updates');
});
