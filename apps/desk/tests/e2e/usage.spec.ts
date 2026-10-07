// Opt-in anonymous usage counts, window hidden, mock engine, isolated profile, a local server in place of
// t.reelfold.com (REELFOLD_USAGE=1 lets this test build send at all; REELFOLD_USAGE_BASE points it here):
//   - first run shows the choice unchecked; nothing reaches the server before she opts in
//   - checking it persists at once (across a skip, a quit and a relaunch) and sends app_open with only the
//     documented fields
//   - Settings › General › Privacy shows it on, with the same anonymous ID; "Delete my usage data" sends DELETE
//     for that ID and gives a new one; turning it off persists and nothing more is sent
//   - a profile that never opts in sends nothing at all
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

const ROOT = path.resolve(import.meta.dirname, '../..');
type Hit = { method: string; url: string; body: { events?: Record<string, unknown>[] } | null };
const hits: Hit[] = [];
let server: http.Server;
let base = '';

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  server = http.createServer((req, res) => {
    let data = '';
    req.on('data', (c) => (data += c));
    req.on('end', () => {
      hits.push({ method: req.method ?? '', url: req.url ?? '', body: data ? JSON.parse(data) : null });
      res.writeHead(req.method === 'DELETE' ? 200 : 202, { 'content-type': 'application/json' }).end(JSON.stringify({ ok: true, deleted: 1 }));
    });
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}/api/v1`;
});

test.afterAll(() => server?.close());

function launch(profile: string, extra: Record<string, string> = {}) {
  return electron.launch({
    args: [ROOT],
    env: {
      ...(process.env as Record<string, string>),
      DESK_ENGINE_MOCK: '1',
      DESK_USER_DATA: path.join(profile, 'profile'),
      VSTUDIO_HOME: path.join(profile, 'vhome'),
      DESK_SHARED_CACHE: path.join(profile, 'cache'),
      DESK_HF_HUB: '',
      DESK_HISTORY_WATCH: '',
      DESK_HIDE_WINDOW: '1',
      DESK_DISABLE_UPDATES: '1',
      DESK_SKIP_FIRST_RUN: '',
      VITE_DEV_SERVER_URL: '',
      REELFOLD_USAGE: '1',
      REELFOLD_USAGE_BASE: base,
      ...extra,
    },
  });
}

async function open(app: ElectronApplication): Promise<Page> {
  const page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  return page;
}

test('first run: the choice is off by default, persists, and only then is anything sent', async () => {
  test.setTimeout(120000);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-usage-'));
  let app = await launch(dir);
  let page = await open(app);
  await expect(page.getByTestId('first-run')).toBeVisible({ timeout: 30000 });
  const box = page.getByTestId('fr-usage-toggle');
  await expect(box).not.toBeChecked();
  await expect(page.getByTestId('fr-usage')).toContainText(/never file names|绝不发送文件名|jamais de noms de fichiers/);
  await page.waitForTimeout(1500);
  expect(hits).toHaveLength(0); // off: not even app_open

  await box.check();
  await expect.poll(async () => (await page.evaluate(() => window.desk.getSettings())).usagePings).toBe('on');
  await expect.poll(() => hits.length, { timeout: 15000 }).toBeGreaterThan(0);
  const first = hits[0];
  expect(first).toMatchObject({ method: 'POST', url: '/api/v1/ping' });
  const ev = first.body!.events![0];
  expect(Object.keys(ev).sort()).toEqual(['arch', 'day', 'ev', 'id', 'locale', 'os', 'v']);
  expect(ev).toMatchObject({ ev: 'app_open', v: '0.2.0', locale: 'en' });
  expect(ev.day).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  const id = ev.id as string;

  // skip the rest of the wizard, quit, relaunch: still on, same id
  await page.getByTestId('fr-skip').click();
  await closeApp(app);
  app = await launch(dir);
  page = await open(app);
  await page.evaluate(() => (location.hash = '#/settings/general'));
  await expect(page.getByTestId('usage-toggle')).toBeChecked({ timeout: 30000 });
  await expect(page.getByTestId('usage-id')).toHaveText(id);

  // delete my usage data: DELETE for that id, then a new id
  await page.getByTestId('usage-delete').click();
  await expect(page.getByTestId('usage-delete-msg')).toBeVisible();
  expect(hits.some((h) => h.method === 'DELETE' && h.url === `/api/v1/installs/${id}`)).toBe(true);
  await expect(page.getByTestId('usage-id')).not.toHaveText(id);

  // off: persists, nothing more is sent
  await page.getByTestId('usage-toggle').uncheck();
  await expect.poll(async () => (await page.evaluate(() => window.desk.getSettings())).usagePings).toBe('off');
  const n = hits.length;
  await page.evaluate(() => window.desk.usage.track('export_done', { count: 3 }));
  await page.waitForTimeout(1000);
  expect(hits.length).toBe(n);
  await closeApp(app);
  app = await launch(dir);
  page = await open(app);
  await page.evaluate(() => (location.hash = '#/settings/general'));
  await expect(page.getByTestId('usage-toggle')).not.toBeChecked({ timeout: 30000 });
  await page.waitForTimeout(1000);
  expect(hits.length).toBe(n);
  await closeApp(app);
});

test('a profile that never opts in sends nothing', async () => {
  test.setTimeout(90000);
  hits.length = 0;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-usage-'));
  const app = await launch(dir);
  const page = await open(app);
  await expect(page.getByTestId('first-run')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('fr-skip').click();
  await page.evaluate(() => window.desk.usage.track('batch_done', { clips: 4 }));
  await page.evaluate(() => (location.hash = '#/settings/general'));
  await expect(page.getByTestId('usage-toggle')).not.toBeChecked({ timeout: 30000 });
  await expect(page.getByTestId('usage-id-row')).toHaveCount(0); // no id is ever made
  await page.waitForTimeout(1500);
  expect(hits).toHaveLength(0);
  expect(fs.existsSync(path.join(dir, 'profile', 'usage.json'))).toBe(false);
  await closeApp(app);
});
