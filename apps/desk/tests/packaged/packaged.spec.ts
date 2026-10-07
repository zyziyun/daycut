// Packaged-app check: launches the built .app / .exe (not the dev tree), with an isolated profile and a scrubbed
// environment, and verifies the real engine runs from the bundled runtime. The test engine (engine/tests) is not in the
// bundle and DESK_ENGINE_MOCK is ignored by a packaged build: every check here runs on the real engine.
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
    return path.join(dir, 'Reelfold.app', 'Contents', 'MacOS', 'Reelfold');
  }
  return path.join(ROOT, 'dist', 'win-unpacked', 'Reelfold.exe');
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

async function launch(extra: Record<string, string>, args: string[] = [], opts: { realKeychain?: boolean } = {}): Promise<App> {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-packaged-'));
  // hidden window; the engine cache and Hugging Face cache point at temp folders so a test never writes the user's
  const cache = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-packaged-cache-'));
  // DESK_SKIP_FIRST_RUN by default: the wizard starts the required downloads (~0.5 GB) by itself, and a quit during
  // a download asks first (a modal that a test's SIGTERM never answers)
  const env = cleanEnv({ DESK_USER_DATA: userData, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: cache, DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', ...extra });
  const port = await freePort();
  // --use-mock-keychain: a rebuilt (re-signed) binary must never raise a keychain prompt on the developer's screen
  // (the migration test opts into the real keychain with an item of its own)
  const proc = spawn(appExecutable(), [...(opts.realKeychain ? [] : ['--use-mock-keychain']), `--remote-debugging-port=${port}`, ...args], { env, stdio: 'ignore' });
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

test('a packaged app never starts the test engine: DESK_ENGINE_MOCK is ignored, the real engine runs', async () => {
  // the v0.2 first-run wizard would cover the main window; this test is about the engine + assets banner
  const res = resourcesDir(appExecutable());
  expect(fs.existsSync(path.join(res, 'engine', 'tests'))).toBe(false); // the test engine is not shipped
  expect(fs.existsSync(path.join(res, 'engine', 'desk_engine', 'mock.py'))).toBe(false);
  const app = await launch({ DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_SKIP_FIRST_RUN: '1' });
  try {
    const h = await health(app);
    expect(h.mode, h.note ?? '').toBe('real');
    expect(fs.realpathSync(h.health.python).startsWith(fs.realpathSync(path.join(res, 'runtime', 'python')))).toBe(true);
    const page = app.page;
    await expect(page.getByTestId('engine-status')).toHaveAttribute('data-mode', 'real', { timeout: 30000 });
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
    // Windows: Media Foundation, or OpenH264 where MF has no H.264 encoder (Windows N, CI VMs); never the absent libx264
    if (process.platform === 'win32') expect(['h264_mf', 'libopenh264']).toContain(h.health.h264_effective);
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

test('the sample recording ships in the app and the real engine offers it (copied out of the bundle)', async () => {
  const res = resourcesDir(appExecutable());
  const dir = path.join(res, 'packaging', 'sample');
  expect(fs.statSync(path.join(dir, 'reelfold-sample.mp4')).size).toBeGreaterThan(100_000);
  expect(fs.readFileSync(path.join(dir, 'LICENSE.txt'), 'utf8')).toContain('CC0');
  const app = await launch({});
  try {
    const info = await app.page.evaluate(async () => {
      const i = await window.desk.engineInfo();
      return (await fetch(i.baseUrl + '/api/sample', { headers: { Authorization: `Bearer ${i.token}` } })).json();
    });
    expect(info.available).toBe(true);
    expect(fs.realpathSync(info.path).startsWith(fs.realpathSync(app.env.DESK_USER_DATA))).toBe(true);
  } finally {
    await app.close();
  }
});

test('first-run download: the core group (fonts + MediaPipe models) installs and verifies', async () => {
  test.skip(process.env.DESK_TEST_DOWNLOADS !== '1', 'set DESK_TEST_DOWNLOADS=1 (downloads ~62 MB)');
  const app = await launch({});
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

test('real speech recognition on the bundled runtime (a real recording, the smallest Whisper model)', async () => {
  test.skip(process.env.DESK_TEST_ASR !== '1', 'set DESK_TEST_ASR=1 (downloads a ~75 MB Whisper model + a 1 MB recording)');
  test.setTimeout(600000);
  const rt = path.join(resourcesDir(appExecutable()), 'runtime');
  const win = process.platform === 'win32';
  const py = win ? path.join(rt, 'python', 'python.exe') : path.join(rt, 'python', 'bin', 'python3');
  const exe = win ? '.exe' : '';
  // JFK's inaugural address excerpt, the sample faster-whisper's own tests use (public domain recording)
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-asr 语音 '));
  const audio = path.join(dir, 'jfk 片段.flac');
  const r = await fetch('https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.1.1/tests/data/jfk.flac');
  expect(r.ok).toBe(true);
  fs.writeFileSync(audio, Buffer.from(await r.arrayBuffer()));
  const env = {
    ...cleanEnv({}),
    PYTHONPATH: path.join(rt, 'vstudio', 'lib'),
    PYTHONNOUSERSITE: '1',
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONUTF8: '1',
    HF_HOME: path.join(dir, 'hf'),
    VSTUDIO_CACHE: path.join(dir, 'cache'),
    VSTUDIO_FFMPEG: path.join(rt, 'ffmpeg', 'bin', `ffmpeg${exe}`),
    VSTUDIO_FFPROBE: path.join(rt, 'ffmpeg', 'bin', `ffprobe${exe}`),
  };
  const model = win || process.arch !== 'arm64' ? 'tiny' : 'mlx-community/whisper-tiny';
  const code = 'import json, sys; from vstudio import asr; t = asr.transcribe(sys.argv[1], language="en", model=sys.argv[2], cache=False); ' + 'print(json.dumps(dict(backend=t["backend"], text=t["text"], words=len(t["words"]))))';
  const out = spawnSync(py, ['-c', code, audio, model], { env, encoding: 'utf8', timeout: 540000 });
  expect(out.status, out.stderr).toBe(0);
  const res = JSON.parse(out.stdout.trim().split('\n').pop()!) as { backend: string; text: string; words: number };
  console.log('[packaged] asr', JSON.stringify(res));
  expect(res.backend).toBe(win || process.arch !== 'arm64' ? 'faster' : 'mlx');
  expect(res.text.toLowerCase()).toContain('country');
  expect(res.words).toBeGreaterThan(10);
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
  const r = spawnSync(appExecutable(), ['--use-mock-keychain', '-e', 'console.log("ran-as-node")'], {
    env: { ...cleanEnv({}), ELECTRON_RUN_AS_NODE: '1', DESK_HIDE_WINDOW: '1', DESK_SKIP_FIRST_RUN: '1', DESK_USER_DATA: fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-fuse-')) },
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

// Every package the engine's requirements.txt names (markers evaluated for this platform) is installed in the bundled
// runtime and imports, extras included (scripts/runtime/check_requirements.py, also run by bundle.mjs): a package added
// to the engine but not re-locked is otherwise silently missing from the app (babel / pypinyin / jsonschema before 0.2.0).
function bundledPython() {
  const rt = path.join(resourcesDir(appExecutable()), 'runtime');
  const py = process.platform === 'win32' ? path.join(rt, 'python', 'python.exe') : path.join(rt, 'python', 'bin', 'python3');
  const env = { ...cleanEnv({}), PYTHONPATH: path.join(rt, 'vstudio', 'lib'), PYTHONNOUSERSITE: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONUTF8: '1' };
  return { py, env };
}

test('every package in the engine requirements.txt is in the bundled runtime and imports', async () => {
  test.setTimeout(300000);
  const { py, env } = bundledPython();
  const reqs = path.resolve(ROOT, '..', '..', 'requirements.txt');
  const out = spawnSync(py, [path.join(ROOT, 'scripts', 'runtime', 'check_requirements.py'), reqs], { env, encoding: 'utf8', timeout: 240000 });
  expect(out.status, out.stderr).toBe(0);
  const rows = JSON.parse(out.stdout.trim().split('\n').pop()!) as { req: string; name: string; version?: string; error?: string }[];
  console.log('[packaged] requirements', rows.map((r) => `${r.name}==${r.version ?? '?'}`).join(' '));
  expect(rows.filter((r) => r.error).map((r) => `${r.req}: ${r.error}`)).toEqual([]);
  for (const n of ['babel', 'pypinyin', 'jsonschema', 'numpy', 'mediapipe', 'openai']) expect(rows.map((r) => r.name)).toContain(n);
});

// the CLDR entity check really runs: 宏都拉斯 -> 洪都拉斯 needs babel (CLDR names) + pypinyin (sound-alike)
test('the named-entity check runs on the bundled engine (宏都拉斯 -> 洪都拉斯 from CLDR)', async () => {
  const { py, env } = bundledPython();
  const code = 'import json; import babel, pypinyin, jsonschema; from vstudio import entities as E; ' +
    'r = E.verify("这次去了宏都拉斯，宏都拉斯的咖啡很好喝", locale="zh_Hans"); ' +
    'print(json.dumps(dict(fixes=[(f["from"], f["to"], f["source"], f["guess"]) for f in r["fixes"]], fixed=E.fix_text("宏都拉斯的咖啡", r["fixes"])), ensure_ascii=False))';
  const out = spawnSync(py, ['-c', code], { env, encoding: 'utf8', timeout: 120000 });
  expect(out.status, out.stderr).toBe(0);
  const res = JSON.parse(out.stdout.trim().split('\n').pop()!) as { fixes: [string, string, string, boolean][]; fixed: string };
  expect(res.fixes).toContainEqual(['宏都拉斯', '洪都拉斯', 'cldr', false]);
  expect(res.fixed).toBe('洪都拉斯的咖啡');
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

test('the bundle is Reelfold (bundle id, names, 千剪 under a Chinese system language)', async () => {
  test.skip(process.platform !== 'darwin', 'macOS bundle');
  const contents = path.resolve(path.dirname(appExecutable()), '..');
  const plist = (k: string) => spawnSync('plutil', ['-extract', k, 'raw', path.join(contents, 'Info.plist')], { encoding: 'utf8' }).stdout.trim();
  expect(plist('CFBundleIdentifier')).toBe('app.reelfold.desk');
  expect(plist('CFBundleName')).toBe('Reelfold');
  expect(plist('LSHasLocalizedDisplayName')).toBe('true');
  for (const l of ['zh_CN.lproj', 'zh-Hans.lproj']) expect(fs.readFileSync(path.join(contents, 'Resources', l, 'InfoPlist.strings'), 'utf8')).toContain('"CFBundleDisplayName" = "千剪";');
  const feed = fs.readFileSync(path.join(contents, 'Resources', 'app-update.yml'), 'utf8');
  expect(feed).toMatch(/owner: zyziyun/);
  expect(feed).toMatch(/repo: reelfold\n/);
});

test('an old profile migrates into Reelfold and its API keys still decrypt with the old keychain item', async () => {
  // A unique keychain name per run: the item is created by this (ad-hoc signed) build itself, so macOS never asks
  // for access; it is deleted at the end. Run 1 plays the old app (a profile whose recorded key is NAME), run 2 finds
  // it as an old "NAME" install, copies it and must still read the key.
  test.skip(process.platform !== 'darwin', 'keychain');
  const NAME = `Reelfold Packaged Test ${Date.now()}`;
  const appData = fs.mkdtempSync(path.join(os.tmpdir(), 'reelfold-pkg-migrate-'));
  const cur = path.join(appData, 'Reelfold');
  fs.mkdirSync(cur);
  fs.writeFileSync(path.join(cur, 'settings.json'), JSON.stringify({ lang: 'fr', firstRunDone: true }));
  fs.writeFileSync(path.join(cur, 'migrated-from.json'), JSON.stringify({ from: 'seed', safeStorageName: NAME, at: 'seed' }));
  const env = { DESK_APP_DATA: appData, DESK_LEGACY_NAMES: NAME, DESK_USER_DATA: '', DESK_SKIP_FIRST_RUN: '1' };
  try {
    const a = await launch(env, [], { realKeychain: true });
    try {
      const st = await a.page.evaluate(() => window.desk.secrets.set('openai', 'packaged-test-key-0123456789'));
      expect(st.keys.openai).toBe(true);
    } finally {
      await a.close();
    }
    // turn it into an old install named NAME
    const old = path.join(appData, NAME);
    fs.renameSync(cur, old);
    fs.rmSync(path.join(old, 'migrated-from.json'));
    fs.rmSync(path.join(old, 'logs'), { recursive: true, force: true });
    const b = await launch(env, [], { realKeychain: true });
    try {
      expect((await b.page.evaluate(() => window.desk.getSettings())).lang).toBe('fr');
      expect((await b.page.evaluate(() => window.desk.secrets.status())).keys.openai).toBe(true);
      await expect.poll(() => fs.readFileSync(path.join(cur, 'logs', 'main.log'), 'utf8'), { timeout: 20000 }).toContain('API keys readable 1/1');
    } finally {
      await b.close();
    }
    expect(JSON.parse(fs.readFileSync(path.join(cur, 'migrated-from.json'), 'utf8')).safeStorageName).toBe(NAME);
    expect(fs.existsSync(path.join(old, 'settings.json'))).toBe(true); // the old folder stays
  } finally {
    spawnSync('security', ['delete-generic-password', '-s', `${NAME} Safe Storage`], { stdio: 'ignore' });
  }
});
