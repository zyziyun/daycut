// Packaged-app check: launches the built .app / .exe (not the dev tree), with an isolated profile and a scrubbed
// environment, and verifies the engine runs from the bundled runtime — first the mock engine, then the real one.
//   npm run dist:mac:unsigned && npm run test:packaged
import { _electron as electron, expect, test, type ElectronApplication } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '../..');

function appExecutable(): string {
  if (process.env.DESK_APP_PATH) return process.env.DESK_APP_PATH;
  if (process.platform === 'darwin') {
    const dir = path.join(ROOT, 'dist', process.arch === 'arm64' ? 'mac-arm64' : 'mac');
    return path.join(dir, 'video-studio desk.app', 'Contents', 'MacOS', 'video-studio desk');
  }
  return path.join(ROOT, 'dist', 'win-unpacked', 'video-studio desk.exe');
}

function resourcesDir(exe: string) {
  return process.platform === 'darwin' ? path.resolve(path.dirname(exe), '..', 'Resources') : path.join(path.dirname(exe), 'resources');
}

/** The parent environment minus anything that could point the app at a dev checkout or another Python. */
function cleanEnv(extra: Record<string, string>) {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined || /^(VSTUDIO_|DESK_|PYTHON|VIRTUAL_ENV|CONDA)/.test(k)) continue;
    env[k] = v;
  }
  return { ...env, DESK_DISABLE_UPDATES: '1', ...extra };
}

async function launch(extra: Record<string, string>): Promise<ElectronApplication> {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-packaged-'));
  // hidden window; the engine cache and Hugging Face cache point at temp folders so a test never writes the user's
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-packaged-cache-'));
  const env = cleanEnv({ DESK_USER_DATA: userData, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: cache, DESK_HF_HUB: '', ...extra });
  const app = await electron.launch({ executablePath: appExecutable(), env });
  await (await app.firstWindow()).waitForURL(/^app:\/\/desk\//, { timeout: 60000 });
  return app;
}

async function health(app: ElectronApplication) {
  const page = await app.firstWindow();
  return page.evaluate(async () => {
    const info = await window.desk.engineInfo();
    const res = await fetch(info.baseUrl + '/api/health', { headers: { Authorization: `Bearer ${info.token}` } });
    return { mode: info.mode, note: info.note, health: await res.json() };
  });
}

test.skip(!fs.existsSync(appExecutable()), `no packaged app at ${appExecutable()}`);

test('mock engine runs on the bundled Python', async () => {
  // the v0.2 first-run wizard would cover the main window; this test is about the engine + assets banner
  const app = await launch({ DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_SKIP_FIRST_RUN: '1' });
  try {
    const res = resourcesDir(appExecutable());
    const h = await health(app);
    expect(h.mode).toBe('mock');
    expect(h.health.ok).toBe(true);
    expect(fs.realpathSync(h.health.python).startsWith(fs.realpathSync(path.join(res, 'runtime', 'python')))).toBe(true);
    const page = await app.firstWindow();
    await expect(page.getByTestId('engine-status')).toContainText(/mock|演示/i, { timeout: 30000 });
    // bundled runtime + empty profile -> the first-run download banner is offered
    await expect(page.getByTestId('assets-banner')).toBeVisible({ timeout: 15000 });
  } finally {
    await app.close();
  }
});

test('real engine starts from the bundle (vstudio, Python and ffmpeg inside the app)', async () => {
  const app = await launch({});
  try {
    const res = fs.realpathSync(resourcesDir(appExecutable()));
    const h = await health(app);
    console.log('[packaged] health', JSON.stringify(h.health));
    expect(h.mode, h.note ?? '').toBe('real');
    const inside = (p: string) => fs.realpathSync(p).startsWith(path.join(res, 'runtime') + path.sep);
    expect(inside(h.health.python)).toBe(true);
    expect(inside(h.health.engine_path)).toBe(true);
    expect(inside(h.health.vstudio)).toBe(true);
    expect(inside(h.health.ffmpeg)).toBe(true);
    expect(h.health.h264_encoder).toBe(process.platform === 'darwin' ? 'h264_videotoolbox' : 'h264_mf');
    // the engine's own encoder setting (no desk shim): its 0.1 s probe encode ran through the bundled LGPL ffmpeg
    // (VSTUDIO_FFMPEG); on macOS VideoToolbox must work, else every export silently falls back to libx264 (absent)
    if (process.platform === 'darwin') expect(h.health.h264_effective).toBe('h264_videotoolbox');
    expect(fs.existsSync(path.join(res, 'engine', 'runtime_shim'))).toBe(false);
    const page = await app.firstWindow();
    const recipes = await page.evaluate(async () => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + '/api/recipes', { headers: { Authorization: `Bearer ${info.token}` } });
      return r.ok ? ((await r.json()) as unknown[]).length : -r.status;
    });
    expect(recipes).toBeGreaterThan(0);
  } finally {
    await app.close();
  }
});

test('first-run download: the core group (fonts + MediaPipe models) installs and verifies', async () => {
  test.skip(process.env.DESK_TEST_DOWNLOADS !== '1', 'set DESK_TEST_DOWNLOADS=1 (downloads ~62 MB)');
  const app = await launch({ DESK_ENGINE_MOCK: '1' });
  try {
    const page = await app.firstWindow();
    await page.evaluate(() => window.desk.assets.install(['core']));
    await expect
      .poll(async () => page.evaluate(async () => (await window.desk.assets.status()).groups.find((g) => g.id === 'core')?.installed), { timeout: 600000, intervals: [2000] })
      .toBe(true);
    const st = await page.evaluate(() => window.desk.assets.status());
    // the core group lives in the engine cache shared with the CLI (here the test's temp DESK_SHARED_CACHE)
    const cache = await app.evaluate(() => process.env.DESK_SHARED_CACHE as string);
    expect(fs.existsSync(path.join(cache, 'fonts', 'NotoSansSC-Regular.otf'))).toBe(true);
    expect(fs.existsSync(path.join(cache, 'models', 'face_landmarker.task'))).toBe(true);
    expect(fs.existsSync(path.join(st.dir, 'installed.json'))).toBe(true);
  } finally {
    await app.close();
  }
});
