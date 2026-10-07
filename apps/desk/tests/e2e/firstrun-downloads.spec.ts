// Regression: first-run downloads must never close the window, reload the page or leave the wizard step.
// Creator report: the app quit / jumped to the main page after one model finished downloading. Here three asset
// groups (a large throttled file, a zip that is extracted, a group with engine env -> engine restart) are queued
// from the wizard's download step against a local server; the wizard must stay on that step until the explicit
// finish button, the window must stay open, and the engine restart for the new assets must not reload the page.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

const ROOT = path.resolve(import.meta.dirname, '../..');
const tmp = (p: string) => fs.mkdtempSync(path.join(os.tmpdir(), p));
const sha = (b: Buffer) => crypto.createHash('sha256').update(b).digest('hex');

let server: http.Server;
let app: ElectronApplication;
let page: Page;
const files: Record<string, Buffer> = {};
let closed = false;
let requests = 0;
let launchEnv: Record<string, string> = {};

/** A fake bundled runtime: the system Python (mock engine) + the folder layout findBundledRuntime() checks. */
function fakeRuntime(): string {
  const rt = tmp('vsdesk-rt-');
  fs.mkdirSync(path.join(rt, 'python', 'bin'), { recursive: true });
  fs.mkdirSync(path.join(rt, 'vstudio', 'lib', 'vstudio'), { recursive: true });
  fs.mkdirSync(path.join(rt, 'ffmpeg', 'bin'), { recursive: true });
  const py = execFileSync('python3', ['-c', 'import sys; print(sys.executable)']).toString().trim();
  fs.symlinkSync(py, path.join(rt, 'python', 'bin', 'python3'));
  fs.writeFileSync(
    path.join(rt, 'runtime.json'),
    JSON.stringify({ target: `${process.platform}-${process.arch}`, python: '3', vstudioCommit: 'test', ffmpeg: 'x', h264Encoder: 'libx264', asr: 'x', builtAt: '' }),
  );
  return rt;
}

test.beforeAll(async () => {
  // payloads: a 24 MB "model", a zip with a small tree, a tiny file whose group sets engine env
  files.big = crypto.randomBytes(24 * 1024 * 1024);
  const zsrc = tmp('vsdesk-zsrc-');
  fs.mkdirSync(path.join(zsrc, 'tool', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(zsrc, 'tool', 'bin', 'run'), '#!/bin/sh\necho ok\n', { mode: 0o755 });
  const zip = path.join(tmp('vsdesk-zip-'), 'tool.zip');
  execFileSync('ditto', ['-c', '-k', zsrc, zip]);
  files.zip = fs.readFileSync(zip);
  files.small = Buffer.from('weights');

  server = http.createServer((req, res) => {
    requests++;
    const b = files[(req.url ?? '/').slice(1)];
    if (!b) return void res.writeHead(404).end();
    res.writeHead(200, { 'content-length': b.length });
    let at = 0;
    const tick = () => {
      if (at >= b.length) return void res.end();
      const n = Math.min(512 * 1024, b.length - at);
      const ok = res.write(b.subarray(at, at + n));
      at += n;
      if (ok) setTimeout(tick, 40);
      else res.once('drain', () => setTimeout(tick, 40));
    };
    tick();
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  const manifest = {
    groups: [
      { id: 'core', required: true, root: 'vstudio-cache', licence: 'test', files: [{ url: `${base}/big`, dest: 'models/big.bin', sha256: sha(files.big), size: files.big.length }] },
      { id: 'chromium', required: false, root: 'tool', extract: true, licence: 'test', files: [{ url: `${base}/zip`, dest: 'tool.zip', sha256: sha(files.zip), size: files.zip.length }] },
      { id: 'asr-mlx', required: true, root: 'models/asr', env: { VSTUDIO_WHISPER_MLX: '' }, licence: 'test', files: [{ url: `${base}/small`, dest: 'w.bin', sha256: sha(files.small), size: files.small.length }] },
    ],
  };
  const mf = path.join(tmp('vsdesk-mf-'), 'assets.json');
  fs.writeFileSync(mf, JSON.stringify(manifest));

  const work = tmp('vsdesk-e2e-dl-');
  launchEnv = {
    ...(process.env as Record<string, string>),
    DESK_ENGINE_MOCK: '1',
    DESK_MOCK_STEP: '0.02',
    DESK_USER_DATA: path.join(work, 'profile'),
    DESK_SHARED_CACHE: path.join(work, 'engine-cache'), // never the user's ~/.cache/video-studio
    DESK_HF_HUB: '', // never the user's Hugging Face cache
    VSTUDIO_HOME: path.join(work, 'vhome'), // never the user's engine registries
    DESK_HISTORY_WATCH: '', // never scan the user's folders
    DESK_HIDE_WINDOW: '1', // never on the user's screen
    DESK_RUNTIME_DIR: fakeRuntime(),
    // CI exports DESK_PYTHON; it outranks the runtime, which would make the app "system" and drop the downloads step
    DESK_PYTHON: '',
    DESK_ASSETS_MANIFEST: mf,
    DESK_DISABLE_UPDATES: '1',
    DESK_SKIP_FIRST_RUN: '',
    VITE_DEV_SERVER_URL: '',
  };
  app = await electron.launch({ args: [ROOT], env: launchEnv });
  page = await app.firstWindow();
  page.on('close', () => (closed = true));
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await closeApp(app);
  server?.close();
});

test('queued downloads keep the wizard on its step, the window open and the page alive', async () => {
  test.setTimeout(120000);
  await expect(page.getByTestId('first-run')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('fr-next').click(); // welcome -> AI
  await page.getByTestId('fr-next').click(); // AI -> downloads
  await expect(page.getByTestId('assets-card')).toBeVisible();
  // the download button is not a second primary next to Next, and no raw folder path is shown
  await expect(page.locator('[data-testid="first-run"] .btn.primary')).toHaveCount(1);
  await expect(page.getByTestId('assets-card')).not.toContainText(/\/Users\/|\/var\/|\/tmp\//);
  const tokenBefore = await page.evaluate(async () => (await window.desk.engineInfo()).token);
  // a marker that only survives if the page is never reloaded
  await page.evaluate(() => ((window as unknown as { __marker: number }).__marker = 42));

  // required groups are pre-ticked; add the optional one and queue all three at once
  await page.getByTestId('asset-pick-chromium').check();
  await page.getByTestId('assets-download-selected').click();
  await expect(page.getByTestId('asset-state-chromium')).toHaveText(/排队|Queued/);

  // while the queue runs and after each group finishes: still the wizard, still the models step
  const steps = page.locator('.steps .on');
  for (const id of ['core', 'chromium', 'asr-mlx']) {
    await expect(page.getByTestId(`asset-state-${id}`)).toHaveText(/已安装|Installed/, { timeout: 60000 });
    await expect(page.getByTestId('first-run')).toBeVisible();
    await expect(steps).toHaveText(/下载|Downloads/);
  }

  // the env group triggers an engine-sidecar restart: new token, same page (marker kept), same step, window open
  await expect.poll(async () => page.evaluate(async () => (await window.desk.engineInfo()).token), { timeout: 30000 }).not.toBe(tokenBefore);
  expect(await page.evaluate(() => (window as unknown as { __marker?: number }).__marker)).toBe(42);
  const st = await page.evaluate(() => window.desk.assets.status());
  expect(st.busy).toBe(false);
  expect(st.restartNeeded).toBe(false);
  await expect(steps).toHaveText(/下载|Downloads/);
  expect(closed).toBe(false);
  expect(app.windows().length).toBe(1);

  // only the explicit buttons leave the wizard
  await page.getByTestId('fr-next').click(); // -> platforms
  await page.getByTestId('fr-next').click(); // finish
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 15000 });
  expect(closed).toBe(false);
});

test('a restart finds everything installed: zero network requests, nothing offered for download', async () => {
  await closeApp(app);
  const before = requests;
  app = await electron.launch({ args: [ROOT], env: launchEnv });
  page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//);
  const st = await page.evaluate(() => window.desk.assets.status());
  expect(st.groups.map((g) => [g.id, g.installed])).toEqual([['core', true], ['chromium', true], ['asr-mlx', true]]);
  expect(st.dir).toBe(path.join(launchEnv.DESK_USER_DATA, 'assets'));
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 15000 }); // first run done, no banner work
  await expect(page.getByTestId('assets-banner')).toHaveCount(0);
  expect(requests).toBe(before);
});

test('assets already on disk at start: in the first engine env, zero engine restarts, first API call succeeds', async () => {
  await closeApp(app);
  // Whisper "already in the Hugging Face cache" (content-addressed blob) - found by the start-up scan
  const hub = tmp('vsdesk-hub-');
  const snap = path.join(hub, 'models--org--whisper', 'snapshots', 'rev1');
  fs.mkdirSync(snap, { recursive: true });
  fs.mkdirSync(path.join(hub, 'models--org--whisper', 'blobs'));
  fs.writeFileSync(path.join(hub, 'models--org--whisper', 'blobs', sha(files.small)), files.small);
  fs.symlinkSync(path.join('..', '..', 'blobs', sha(files.small)), path.join(snap, 'w.bin'));
  const mf = path.join(tmp('vsdesk-mf2-'), 'assets.json');
  fs.writeFileSync(
    mf,
    JSON.stringify({
      groups: [
        { id: 'asr-mlx', required: true, root: 'models/asr', env: { VSTUDIO_WHISPER_MLX: '' }, licence: 't', files: [{ url: 'https://huggingface.co/org/whisper/resolve/rev1/w.bin', dest: 'w.bin', sha256: sha(files.small), size: files.small.length }] },
      ],
    }),
  );
  const userData = tmp('vsdesk-e2e-pre-');
  app = await electron.launch({ args: [ROOT], env: { ...launchEnv, DESK_USER_DATA: userData, DESK_ASSETS_MANIFEST: mf, DESK_HF_HUB: hub, DESK_SKIP_FIRST_RUN: '1' } });
  page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//);
  // the very first API call works (no engine swapped underneath it)
  const first = await page.evaluate(async () => {
    const i = await window.desk.engineInfo();
    const r = await fetch(i.baseUrl + '/api/health', { headers: { Authorization: `Bearer ${i.token}` } });
    return { status: r.status, token: i.token };
  });
  expect(first.status).toBe(200);
  const st = await page.evaluate(() => window.desk.assets.status());
  expect(st.groups[0].installed).toBe(true);
  expect(st.restartNeeded).toBe(false); // the first engine already got VSTUDIO_WHISPER_MLX
  await page.waitForTimeout(2000);
  expect(await page.evaluate(async () => (await window.desk.engineInfo()).token)).toBe(first.token);
  const log = fs.readFileSync(path.join(userData, 'logs', 'main.log'), 'utf8');
  expect(log).toContain('[assets] asr-mlx already on disk');
  expect(log).not.toContain('restarting the engine sidecar');
  expect(log).not.toContain('start failed');
});

test('an engine restart while it is still starting: same port, the UI keeps working without a reload', async () => {
  await page.evaluate(() => ((window as unknown as { __marker: number }).__marker = 7));
  const before = await page.evaluate(async () => (await window.desk.engineInfo()).baseUrl);
  const r = await page.evaluate(async () => {
    void window.desk.restartEngine(); // do not wait: ask for the engine while the new one is cold-starting
    const i = await window.desk.engineInfo();
    const res = await fetch(i.baseUrl + '/api/batches', { headers: { Authorization: `Bearer ${i.token}` } });
    return { status: res.status, baseUrl: i.baseUrl };
  });
  expect(r.status).toBe(200);
  expect(r.baseUrl).toBe(before); // session port kept: CSP + renderer URL stay valid
  expect(await page.evaluate(() => (window as unknown as { __marker?: number }).__marker)).toBe(7);
  await expect(page.getByTestId('engine-status')).toHaveAttribute('data-mode', 'mock', { timeout: 15000 });
});
