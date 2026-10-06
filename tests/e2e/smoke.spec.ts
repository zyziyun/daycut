// Electron smoke test: launches the built app with the mock engine and an isolated profile.
// Run: npm run test:e2e   (builds first). Never touches a real platform: the only publish call made here is
// refused by the confirmation gate before any page is opened.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;

test.beforeAll(async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-e2e-'));
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_USER_DATA: userData, VSTUDIO_HOME: path.join(userData, 'vhome'), DESK_HISTORY_WATCH: '', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(userData, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//); // the window loads once the engine is up
});

test.afterAll(async () => {
  await app?.close();
});

test('window is locked down', async () => {
  const prefs = await app.evaluate(({ BrowserWindow }) => {
    // getLastWebPreferences is runtime API not in the typings
    const wc = BrowserWindow.getAllWindows()[0].webContents as unknown as { getLastWebPreferences(): Record<string, boolean> | null };
    const p = wc.getLastWebPreferences();
    return { contextIsolation: p?.contextIsolation, sandbox: p?.sandbox, nodeIntegration: p?.nodeIntegration, webviewTag: p?.webviewTag };
  });
  expect(prefs).toEqual({ contextIsolation: true, sandbox: true, nodeIntegration: false, webviewTag: false });
  const g = await page.evaluate(() => ({ require: typeof (window as unknown as { require?: unknown }).require, process: typeof (window as unknown as { process?: unknown }).process, desk: typeof window.desk }));
  expect(g).toEqual({ require: 'undefined', process: 'undefined', desk: 'object' });
  expect(page.url()).toMatch(/^app:\/\/desk\//);
});

test('engine starts (mock) and the batch list renders', async () => {
  await expect(page.getByTestId('engine-status')).toContainText(/mock|演示/i, { timeout: 30000 });
  await expect(page.getByText('demo-course', { exact: true })).toBeVisible({ timeout: 15000 });
});

test('engine refuses requests without the token', async () => {
  const r = await page.evaluate(async () => {
    const info = await window.desk.engineInfo();
    const res = await fetch(info.baseUrl + '/api/batches');
    return res.status;
  });
  expect(r).toBe(401);
});

test('board, review and job detail render', async () => {
  await page.getByText('demo-course', { exact: true }).click();
  await expect(page.locator('.lane').first()).toBeVisible();
  await expect(page.locator('.jcard').first()).toBeVisible();
  await page.locator('.side a', { hasText: /审片|Review/ }).click();
  await expect(page.locator('.rcard').first()).toBeVisible();
  await page.locator('.rcard').first().dblclick();
  await expect(page.locator('.transcript').first()).toBeVisible();
});

test('publish: fill is refused until the package list is confirmed', async () => {
  const res = await page.evaluate(async () => {
    const info = await window.desk.engineInfo();
    const h = { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' };
    const batches = await (await fetch(info.baseUrl + '/api/batches', { headers: h })).json();
    const id = batches.find((b: { name: string }) => b.name === 'demo-course').id;
    const pkg = await (await fetch(`${info.baseUrl}/api/batches/${id}/package`, { method: 'POST', headers: h, body: '{}' })).json();
    const man = await (await fetch(`${info.baseUrl}/api/batches/${id}/package`, { headers: h })).json();
    const item = man.manifest.items.find((i: { platform: string }) => i.platform.startsWith('tiktok'));
    await window.desk.publish.addAccount('tiktok', 'e2e');
    const fill = await window.desk.publish.fill({ batchId: id, code: pkg.code, job: item.job, platform: item.platform, adapterId: 'tiktok', account: 'e2e' });
    let posted = 'allowed';
    try {
      await window.desk.publish.markPosted({ batchId: id, code: pkg.code, job: item.job, platform: item.platform, adapterId: 'tiktok', account: 'e2e' });
    } catch {
      posted = 'refused';
    }
    let badIpc = 'allowed';
    try {
      await window.desk.publish.fill({ batchId: '../../x', code: pkg.code, job: item.job, platform: item.platform, adapterId: 'tiktok', account: 'e2e' });
    } catch {
      badIpc = 'refused';
    }
    return { fill, posted, badIpc, verified: man.verify.ok };
  });
  expect(res.verified).toBe(true);
  expect(res.fill).toMatchObject({ ok: false, reason: 'not-confirmed' });
  expect(res.posted).toBe('refused');
  expect(res.badIpc).toBe('refused');
});
