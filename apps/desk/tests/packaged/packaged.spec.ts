// Packaged-app check: launches the built .app / .exe (not the dev tree), with an isolated profile and a scrubbed
// environment, and verifies the engine runs from the bundled runtime — first the mock engine, then the real one.
//   npm run dist:mac:unsigned && npm run test:packaged
// The build has its Electron fuses set (no --inspect, no ELECTRON_RUN_AS_NODE), so Playwright's _electron.launch
// (which drives the main process through the Node inspector) cannot attach: the app is started with Chromium's
// --remote-debugging-port and driven over CDP instead (renderer only, which is all these checks need).
import { chromium, expect, test, type Browser, type Page } from '@playwright/test';
import { spawn, spawnSync, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '../..');

function appExecutable(): string {
  if (process.env.DESK_APP_PATH) return process.env.DESK_APP_PATH;
  if (process.platform === 'darwin') {
    const dir = path.join(ROOT, 'dist', process.arch === 'arm64' ? 'mac-arm64' : 'mac');
    return path.join(dir, 'Daycut.app', 'Contents', 'MacOS', 'Daycut');
  }
  return path.join(ROOT, 'dist', 'win-unpacked', 'Daycut.exe');
}

function resourcesDir(exe: string) {
  return process.platform === 'darwin' ? path.resolve(path.dirname(exe), '..', 'Resources') : path.join(path.dirname(exe), 'resources');
}

/** The parent environment minus anything that could point the app at a dev checkout or another Python. */
function cleanEnv(extra: Record<string, string>) {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v === undefined || /^(VSTUDIO_|DESK_|PYTHON|VIRTUAL_ENV|CONDA|ELECTRON_|NODE_OPTIONS)/.test(k)) continue;
    env[k] = v;
  }
  return { ...env, DESK_DISABLE_UPDATES: '1', ...extra };
}

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

interface App {
  proc: ChildProcess;
  browser: Browser;
  page: Page;
  env: Record<string, string>;
  close(): Promise<void>;
}

async function launch(extra: Record<string, string>, args: string[] = []): Promise<App> {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-packaged-'));
  // hidden window; the engine cache and Hugging Face cache point at temp folders so a test never writes the user's
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-packaged-cache-'));
  const env = cleanEnv({ DESK_USER_DATA: userData, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: cache, DESK_HF_HUB: '', ...extra });
  const port = await freePort();
  const proc = spawn(appExecutable(), [`--remote-debugging-port=${port}`, ...args], { env, stdio: 'ignore' });
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
    throw new Error('packaged app did not open a CDP endpoint');
  }
  let page: Page | undefined;
  for (let i = 0; i < 120 && !page; i++) {
    page = browser.contexts().flatMap((c) => c.pages()).find((p) => p.url().startsWith('app://desk/'));
    if (!page) await new Promise((r) => setTimeout(r, 500));
  }
  if (!page) throw new Error('no app://desk/ window');
  await page.waitForURL(/^app:\/\/desk\//, { timeout: 60000 });
  const close = async () => {
    await browser!.close().catch(() => undefined);
    proc.kill('SIGTERM');
    await new Promise((r) => setTimeout(r, 1500));
    if (proc.exitCode === null) proc.kill('SIGKILL');
  };
  return { proc, browser, page, env, close };
}

async function health(app: App) {
  const page = app.page;
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
    const page = app.page;
    await expect(page.getByTestId('engine-status')).toContainText(/mock|demo|演示/i, { timeout: 30000 });
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
    const page = app.page;
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
    const page = app.page;
    await page.evaluate(() => window.desk.assets.install(['core']));
    await expect
      .poll(async () => page.evaluate(async () => (await window.desk.assets.status()).groups.find((g) => g.id === 'core')?.installed), { timeout: 600000, intervals: [2000] })
      .toBe(true);
    const st = await page.evaluate(() => window.desk.assets.status());
    // the core group lives in the engine cache shared with the CLI (here the test's temp DESK_SHARED_CACHE)
    const cache = app.env.DESK_SHARED_CACHE;
    expect(fs.existsSync(path.join(cache, 'fonts', 'NotoSansSC-Regular.otf'))).toBe(true);
    expect(fs.existsSync(path.join(cache, 'models', 'face_landmarker.task'))).toBe(true);
    expect(fs.existsSync(path.join(st.dir, 'installed.json'))).toBe(true);
  } finally {
    await app.close();
  }
});

test('fuses are set in the built binary', async () => {
  const { getCurrentFuseWire, FuseV1Options } = await import('@electron/fuses');
  const DISABLE = 48;
  const ENABLE = 49;
  const wire = (await getCurrentFuseWire(appExecutable())) as unknown as Record<number, number>;
  expect(wire[FuseV1Options.RunAsNode]).toBe(DISABLE);
  expect(wire[FuseV1Options.EnableNodeOptionsEnvironmentVariable]).toBe(DISABLE);
  expect(wire[FuseV1Options.EnableNodeCliInspectArguments]).toBe(DISABLE);
  expect(wire[FuseV1Options.EnableEmbeddedAsarIntegrityValidation]).toBe(ENABLE);
  expect(wire[FuseV1Options.OnlyLoadAppFromAsar]).toBe(ENABLE);
  expect(wire[FuseV1Options.EnableCookieEncryption]).toBe(ENABLE);
  expect(wire[FuseV1Options.GrantFileProtocolExtraPrivileges]).toBe(DISABLE);
  // ELECTRON_RUN_AS_NODE is ignored: the binary starts the app instead of a Node REPL evaluating our script
  const r = spawnSync(appExecutable(), ['-e', 'console.log("ran-as-node")'], {
    env: { ...cleanEnv({}), ELECTRON_RUN_AS_NODE: '1', DESK_HIDE_WINDOW: '1', DESK_USER_DATA: fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-fuse-')) },
    timeout: 8000,
    encoding: 'utf8',
  });
  expect(r.stdout ?? '').not.toContain('ran-as-node');
});

test('the bundled engine is this repository’s engine (llm / project / intake, output chat + --context)', async () => {
  const res = resourcesDir(appExecutable());
  const rt = path.join(res, 'runtime');
  const py = process.platform === 'win32' ? path.join(rt, 'python', 'python.exe') : path.join(rt, 'python', 'bin', 'python3');
  const env = { ...cleanEnv({}), PYTHONPATH: path.join(rt, 'vstudio', 'lib'), PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1' };
  const imp = spawnSync(py, ['-c', 'import vstudio.llm, vstudio.project, vstudio.intake, vstudio.project.outputs; print("ok")'], { env, encoding: 'utf8', timeout: 120000 });
  expect(imp.stdout.trim(), imp.stderr).toBe('ok');
  const help = spawnSync(py, ['-m', 'vstudio.project', 'output', '--help'], { env, encoding: 'utf8', timeout: 120000 });
  expect(help.status, help.stderr).toBe(0);
  for (const w of ['show', 'edit', 'render', 'revert', 'chat', '--context', '--with-ops']) expect(help.stdout).toContain(w);
  // built from this checkout, not a pinned older commit
  const commit = fs.readFileSync(path.join(rt, 'vstudio', 'COMMIT'), 'utf8').trim();
  const head = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).stdout.trim();
  if (head) expect(commit.replace(/-dirty$/, '')).toBe(head);
});

test('AI accounts never show raw engine errors (paths, Python tracebacks)', async () => {
  const app = await launch({ DESK_SKIP_FIRST_RUN: '1' });
  try {
    const page = app.page;
    const st = await page.evaluate(() => window.desk.ai.status({ refresh: true, probe: false }));
    expect(st.error === undefined || ['engine', 'timeout', 'failed'].includes(st.error), JSON.stringify(st.error)).toBe(true);
    expect(st.error, 'the bundled engine has vstudio.llm').not.toBe('engine');
    await page.evaluate(() => (location.hash = '#/settings/ai'));
    await expect(page.getByTestId('ai-accounts')).toBeVisible({ timeout: 30000 });
    await page.waitForTimeout(1500);
    const text = await page.getByTestId('ai-accounts').innerText();
    expect(text).not.toMatch(/No module named|Traceback|\/Users\/|\/Applications\/|vstudio\.llm/);
  } finally {
    await app.close();
  }
});
