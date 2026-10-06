// Electron main process: window + security, engine sidecar, media protocol, IPC, publish browser.
import fs from 'node:fs';
import { createServer as createNetServer, type AddressInfo } from 'node:net';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { app, BrowserWindow, clipboard, dialog, ipcMain, net, Notification, protocol, session, shell, type IpcMainInvokeEvent } from 'electron';
import { EngineClient } from '../shared/engineClient';
import { validateIpc, type IpcChannel, type IpcPayload } from '../shared/ipc';
import { hostAllowed, type Adapter } from '../shared/publish/adapterSchema';
import { resolveInside } from '../shared/publish/gating';
import { parsePostCopy } from '../shared/publish/postCopy';
import type { EngineInfo } from '../shared/types';
import type { AssetManifest } from '../shared/assets';
import { AssetManager, defaultHfHub, sharedEngineCache } from './assets';
import { defaultEnginePath, EngineProcess, findPython } from './engine';
import { isAllowedMediaPath, pathFromMediaUrl } from './media';
import { loadAdapters } from './publish/adapters';
import { PublishBrowser } from './publish/browser';
import { assistedFill } from './publish/fill';
import { PublishStore } from './publish/store';
import { findBundledRuntime, runtimeEnv, type BundledRuntime } from './runtime';
import { buildCsp, isAppUrl, isSafeExternal } from './security';
import { SettingsStore } from './settings';
import { HistoryWatcher } from './historyWatch';
import { checkForUpdates, initUpdater, installUpdate } from './updater';
import { registerCleanupIpc, registerV02Ipc, v02EngineEnv } from './v02';

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
  { scheme: 'vsmedia', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

const DEV_URL = !app.isPackaged ? process.env.VITE_DEV_SERVER_URL : undefined;
const IS_DEV = Boolean(DEV_URL);
const APP_ORIGIN = IS_DEV ? new URL(DEV_URL!).origin : 'app://desk';
const RENDERER_DIR = path.join(__dirname, '../renderer');
const RES = app.isPackaged ? process.resourcesPath : app.getAppPath();

if (process.env.DESK_USER_DATA) app.setPath('userData', process.env.DESK_USER_DATA); // tests: isolated profile

// ---------------------------------------------------------------- diagnostics: the main process must never die
/** Append to <userData>/logs/main.log (and the console). Never throws. */
function mainLog(msg: string) {
  const line = `${new Date().toISOString()} ${msg}`;
  console.error(line);
  try {
    const dir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, 'main.log'), line + '\n');
  } catch {
    /* logging must not throw */
  }
}
process.on('unhandledRejection', (e) => mainLog(`[main] unhandled rejection: ${(e as Error)?.stack ?? String(e)}`));
process.on('uncaughtException', (e) => mainLog(`[main] uncaught exception: ${e?.stack ?? String(e)}`));

let win: BrowserWindow | null = null;
let engine: EngineProcess | null = null;
let client: EngineClient | null = null;
let browser: PublishBrowser | null = null;
let settings: SettingsStore;
let pstore: PublishStore;
let adapters: { adapters: Adapter[]; errors: { file: string; error: string }[] } = { adapters: [], errors: [] };
let enginePromise: Promise<EngineInfo> | null = null;
let runtime: BundledRuntime | null = null;
let assets: AssetManager;

function dataDir() {
  return path.join(app.getPath('userData'), 'engine-data');
}

/** Downloads, partial files and the installed-manifest. Stable: <userData>/assets (tests override userData only). */
function assetsDir() {
  return path.join(app.getPath('userData'), 'assets');
}

/** The engine's cache, shared with the CLI skill (fonts + MediaPipe models live there). DESK_SHARED_CACHE: tests. */
function engineCacheDir() {
  return process.env.DESK_SHARED_CACHE || sharedEngineCache();
}

/** The Hugging Face hub cache (Whisper is reused from it). DESK_HF_HUB: tests ('' = none). */
function hfHubDir(): string | null {
  return process.env.DESK_HF_HUB !== undefined ? process.env.DESK_HF_HUB || null : defaultHfHub();
}

/** Settings override everything; then env vars; then the runtime bundled in the app; then a dev checkout. */
function resolvedConfig() {
  const s = settings.get();
  const python = s.python || process.env.DESK_PYTHON || runtime?.python || findPython();
  const bundled = Boolean(runtime && python === runtime.python);
  return {
    enginePath: defaultEnginePath(app.getAppPath(), s.enginePath, bundled ? runtime!.vstudio : undefined),
    python,
    dataDir: dataDir(),
    runtime: bundled ? `bundled · Python ${runtime!.manifest.python} · video-studio@${runtime!.manifest.vstudioCommit.slice(0, 7)}` : 'system',
  };
}

function engineEnv(bundled: boolean) {
  if (!bundled || !runtime) return { env: assets.env() };
  const r = runtimeEnv(runtime);
  return {
    ...r,
    isolatePython: true,
    env: {
      ...r.env,
      // one cache with the CLI skill: fonts / models the user already has are used, nothing is fetched twice
      VSTUDIO_CACHE: engineCacheDir(),
      ...assets.env(),
    },
  };
}

/** v0.2: API keys from the OS keychain + imported persona, for the sidecar only. */
function withV02Env<T extends { env?: Record<string, string> }>(e: T): T {
  return { ...e, env: { ...e.env, ...v02EngineEnv(app.getPath('userData'), settings.get()) } };
}

function settingsMsg() {
  const s = settings.get();
  return { ...s, firstRunDone: s.firstRunDone || process.env.DESK_SKIP_FIRST_RUN === '1', resolved: resolvedConfig() };
}

/** One engine port per app session, chosen before the first start and reused by every restart (also when the
 * previous engine never became ready), so the page's CSP and the renderer's base URL stay valid. */
let sessionPort: number | null = null;
async function pickSessionPort(): Promise<number | null> {
  if (sessionPort) return sessionPort;
  sessionPort = await new Promise<number | null>((resolve) => {
    const srv = createNetServer();
    srv.once('error', () => resolve(null));
    srv.listen(0, '127.0.0.1', () => {
      const port = (srv.address() as AddressInfo).port;
      srv.close(() => resolve(port));
    });
  });
  return sessionPort;
}

let engineGen = 0;
function startEngine(): Promise<EngineInfo> {
  const gen = ++engineGen;
  const old = engine;
  engine = null;
  client = null;
  restartWhenIdle = false;
  // assets already on disk (CLI cache, Hugging Face cache) are found BEFORE the engine's env is computed, so the
  // first engine already has them - no restart at start-up
  const p = Promise.all([old ? old.stop() : Promise.resolve(), assets.scan(), pickSessionPort()]).then(([, , port]) => {
    if (gen !== engineGen) throw new SupersededError();
    const cfg = resolvedConfig();
    const next = new EngineProcess({
      engineDir: path.join(RES, 'engine'),
      enginePath: cfg.enginePath,
      python: cfg.python,
      dataDir: cfg.dataDir,
      allowedOrigins: [APP_ORIGIN],
      mock: process.env.DESK_ENGINE_MOCK === '1',
      port: enginePort() ?? port ?? undefined,
      ...withV02Env(engineEnv(cfg.runtime !== 'system')),
    });
    engine = next;
    assets.markEngineStarted();
    return next.start();
  });
  enginePromise = p.then((info) => {
    if (gen !== engineGen) throw new SupersededError();
    client = new EngineClient(info.baseUrl, info.token);
    rootsCache = { at: 0, roots: [] };
    win?.webContents.send('engine:status', { ok: true, mode: info.mode, note: info.note });
    // the page's CSP pins the engine port: reload only when it was served before any engine was up (first launch,
    // slow cold start) or the session port could not be used. The URL (hash route) survives a reload.
    if (!IS_DEV && win && servedPort !== undefined && servedPort !== enginePort()) {
      mainLog(`[engine] port ${servedPort} -> ${enginePort()}: reloading the window for its CSP`);
      win.reload();
    }
    return info;
  });
  enginePromise.catch((e) => {
    // an engine stopped on purpose (restart / quit) or superseded by a newer start is not a failure
    if (gen !== engineGen || e instanceof SupersededError || (e as { stopped?: boolean })?.stopped) return;
    client = null;
    mainLog(`[engine] start failed: ${String(e?.message ?? e)}`);
    win?.webContents.send('engine:status', { ok: false, error: String(e?.message ?? e) });
  });
  return enginePromise;
}

class SupersededError extends Error {
  constructor() {
    super('engine restart superseded');
  }
}

/** The current engine, following restarts: a start that was superseded resolves with its successor. */
async function currentEngine(): Promise<EngineInfo> {
  for (;;) {
    const p = enginePromise ?? startEngine();
    try {
      return await p;
    } catch (e) {
      if (p !== enginePromise) continue; // restarted meanwhile: wait for the new one
      throw e;
    }
  }
}

// ---------------------------------------------------------------- engine restart after downloads
/** New assets change the engine's environment. Restart only the engine sidecar (the window and its state stay), and
 * only when no batch is running - a restart would stop it. Checked again every 30 s until idle. */
let restartWhenIdle = false;
let idleTimer: NodeJS.Timeout | null = null;
async function engineBusy(): Promise<boolean> {
  if (!client) return false;
  try {
    const list = (await client.batches()) as { running?: boolean }[];
    return list.some((b) => b.running);
  } catch {
    return false;
  }
}
async function restartForAssets() {
  if (!assets.status().restartNeeded) return;
  if (assets.busy || (await engineBusy())) {
    restartWhenIdle = true;
    sendAssets();
    if (!idleTimer) {
      idleTimer = setTimeout(() => {
        idleTimer = null;
        void restartForAssets();
      }, 30000);
    }
    return;
  }
  mainLog('[assets] new assets installed: restarting the engine sidecar (window kept)');
  await startEngine().catch(() => undefined);
  sendAssets();
}
function sendAssets() {
  try {
    win?.webContents.send('assets:progress', { ...assets.status(), restartWhenIdle });
  } catch {
    /* window gone */
  }
}

// ---------------------------------------------------------------- media roots (from the engine)
let rootsCache = { at: 0, roots: [] as string[] };
let historyWatcher: HistoryWatcher | null = null;
async function mediaRoots(): Promise<string[]> {
  if (!client) return [];
  if (Date.now() - rootsCache.at < 5000) return rootsCache.roots;
  try {
    const roots = (await client.roots()).flatMap((r) => {
      try {
        return [r, fs.realpathSync(r)];
      } catch {
        return [r];
      }
    });
    rootsCache = { at: Date.now(), roots };
  } catch {
    /* keep the old list */
  }
  return rootsCache.roots;
}

function enginePort(): number | null {
  return engine?.info ? Number(new URL(engine.info.baseUrl).port) : null;
}

function currentCsp(): string {
  return buildCsp({ dev: IS_DEV, enginePort: enginePort(), devServerUrl: DEV_URL });
}

/** Engine port baked into the CSP of the page the window last loaded (undefined: nothing loaded yet). */
let servedPort: number | null | undefined;

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
  '.json': 'application/json',
};

function registerProtocols() {
  protocol.handle('app', async (req) => {
    const u = new URL(req.url);
    if (u.host !== 'desk') return new Response('not found', { status: 404 });
    const rel = decodeURIComponent(u.pathname).replace(/^\/+/, '') || 'index.html';
    if (rel.split('/').includes('..')) return new Response('forbidden', { status: 403 });
    let file = path.join(RENDERER_DIR, rel);
    if (!fs.existsSync(file)) file = path.join(RENDERER_DIR, 'index.html');
    const body = await fs.promises.readFile(file);
    if (file.endsWith('.html')) servedPort = enginePort();
    return new Response(body, {
      headers: {
        'content-type': MIME[path.extname(file)] ?? 'application/octet-stream',
        'content-security-policy': currentCsp(),
        'x-content-type-options': 'nosniff',
      },
    });
  });
  protocol.handle('vsmedia', async (req) => {
    const p = pathFromMediaUrl(req.url);
    const roots = await mediaRoots();
    if (!p || !isAllowedMediaPath(p, roots)) return new Response('forbidden', { status: 403 });
    let real: string;
    try {
      real = await fs.promises.realpath(p);
    } catch {
      return new Response('not found', { status: 404 });
    }
    if (!isAllowedMediaPath(real, roots)) return new Response('forbidden', { status: 403 });
    const headers: Record<string, string> = {};
    const range = req.headers.get('range');
    if (range) headers.range = range;
    return net.fetch(pathToFileURL(real).toString(), { headers });
  });
}

function hardenDefaultSession() {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((_wc, _perm, cb) => cb(false));
  ses.setPermissionCheckHandler(() => false);
  ses.on('will-download', (e) => e.preventDefault());
  if (IS_DEV) {
    ses.webRequest.onHeadersReceived((d, cb) => {
      const headers = { ...d.responseHeaders };
      if (isAppUrl(d.url, APP_ORIGIN)) headers['Content-Security-Policy'] = [currentCsp()];
      cb({ responseHeaders: headers });
    });
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#0E1113',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: false,
      spellcheck: false,
      backgroundThrottling: process.env.DESK_HIDE_WINDOW !== '1',
    },
  });
  // DESK_HIDE_WINDOW=1: automated tests drive the app without putting windows on the user's screen
  if (process.env.DESK_HIDE_WINDOW !== '1') win.once('ready-to-show', () => win?.show());
  const wc = win.webContents;
  wc.setWindowOpenHandler(({ url }) => {
    if (isSafeExternal(url)) void shell.openExternal(url);
    return { action: 'deny' };
  });
  wc.on('will-navigate', (e, url) => {
    if (!isAppUrl(url, APP_ORIGIN)) {
      e.preventDefault();
      if (isSafeExternal(url)) void shell.openExternal(url);
    }
  });
  browser = new PublishBrowser(win, (s) => win?.webContents.send('publish:state', s));
  // Load once the engine is up (or failed / is slow) so the page's CSP already carries the engine port;
  // startEngine() reloads the page if the port changes later.
  const url = IS_DEV ? DEV_URL! : 'app://desk/index.html';
  const engineSettled = currentEngine().then(() => {}, () => {});
  void Promise.race([engineSettled, new Promise((r) => setTimeout(r, 15000))]).then(() => win?.loadURL(url));
  win.on('closed', () => {
    browser?.destroy();
    browser = null;
    win = null;
  });
}

// ---------------------------------------------------------------- IPC
function handle<C extends IpcChannel>(channel: C, fn: (p: IpcPayload<C>, e: IpcMainInvokeEvent) => unknown) {
  ipcMain.handle(channel, async (e, payload) => {
    // only our own UI, top frame, may call
    if (!win || e.sender !== win.webContents || !e.senderFrame || !isAppUrl(e.senderFrame.url, APP_ORIGIN)) {
      throw new Error('forbidden sender');
    }
    return fn(validateIpc(channel, payload), e);
  });
}

function needClient(): EngineClient {
  if (!client) throw new Error('engine not running');
  return client;
}

function adapterById(id: string): Adapter {
  const a = adapters.adapters.find((x) => x.id === id);
  if (!a) throw new Error(`unknown adapter ${id}`);
  return a;
}

function registerIpc() {
  handle('engine:info', async () => {
    try {
      return await currentEngine();
    } catch (e) {
      throw new Error(`${(e as Error).message}\n${engine?.recentLog().slice(-20).join('\n') ?? ''}`, { cause: e });
    }
  });
  handle('engine:restart', async () => {
    return startEngine(); // reloads the window for the new port's CSP
  });
  handle('dialog:openFile', async (p) => {
    const filters =
      p.kind === 'video'
        ? [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'mkv', 'webm'] }]
        : p.kind === 'persona'
          ? [{ name: 'Persona', extensions: ['yaml', 'yml'] }]
          : [{ name: 'Segments', extensions: ['yaml', 'yml', 'csv', 'json'] }];
    const r = await dialog.showOpenDialog(win!, { properties: ['openFile'], filters });
    return r.canceled ? null : r.filePaths[0];
  });
  handle('notify:show', async (p) => {
    if (!Notification.isSupported() || win?.isFocused() || process.env.DESK_HIDE_WINDOW === '1') return;
    const n = new Notification({ title: p.title, body: p.body, silent: false });
    n.on('click', () => {
      if (!win) return;
      win.show();
      win.focus();
      if (p.route) win.webContents.send('notify:open', { route: p.route });
    });
    n.show();
  });
  handle('dialog:openFolder', async () => {
    const r = await dialog.showOpenDialog(win!, { properties: ['openDirectory'] });
    return r.canceled ? null : r.filePaths[0];
  });
  handle('shell:openExternal', async (p) => {
    if (isSafeExternal(p.url)) await shell.openExternal(p.url);
  });
  handle('shell:showItem', async (p) => {
    if (fs.existsSync(p.path)) shell.showItemInFolder(p.path);
  });
  handle('clipboard:write', async (p) => clipboard.writeText(p.text));
  handle('settings:get', async () => settingsMsg());
  handle('settings:set', async (p) => {
    if (p.enginePath && !fs.existsSync(path.join(p.enginePath, 'lib', 'vstudio'))) {
      throw new Error('enginePath must be the video-studio repo (with lib/vstudio)');
    }
    if (p.python && !fs.existsSync(p.python)) throw new Error('python not found');
    const before = settings.get();
    const next = settings.set(p);
    if (next.enginePath !== before.enginePath || next.python !== before.python) {
      void startEngine();
    }
    return { ...settingsMsg(), ...next, firstRunDone: settingsMsg().firstRunDone, resolved: resolvedConfig() };
  });

  // ---------------- publish
  handle('publish:adapters', async () => adapters);
  handle('publish:accounts', async () => settings.get().accounts);
  handle('publish:addAccount', async (p) => {
    adapterById(p.adapterId);
    const acc = settings.get().accounts;
    const list = new Set(acc[p.adapterId] ?? []);
    list.add(p.account);
    acc[p.adapterId] = [...list];
    return settings.set({ accounts: acc }).accounts;
  });
  handle('publish:open', async (p) => {
    const acc = settings.get().accounts[p.adapterId] ?? [];
    if (!acc.includes(p.account)) throw new Error('add the account first');
    browser!.open(adapterById(p.adapterId), p.account, p.page);
  });
  handle('publish:setBounds', async (p) => browser?.setBounds(p));
  handle('publish:hide', async () => browser?.hide());
  handle('publish:navigate', async (p) => browser?.navigate(p.action));
  handle('publish:confirmPackage', async (p) => {
    const m = await needClient().manifest(p.batchId);
    if (!m.manifest || !m.verify.ok || m.manifest.confirmation_code !== p.code) {
      throw new Error('the package changed or is not valid: package again and re-check the list');
    }
    return pstore.confirm({ batchId: p.batchId, code: p.code, items: m.manifest.items.length });
  });
  handle('publish:confirmations', async (p) => pstore.confirmations(p.batchId));
  handle('publish:fill', async (p) => {
    const acc = settings.get().accounts[p.adapterId] ?? [];
    if (!acc.includes(p.account)) throw new Error('unknown account');
    return assistedFill(
      {
        client: needClient(),
        store: pstore,
        adapters: adapters.adapters,
        browser: browser!,
        onStep: (r) => win?.webContents.send('publish:fillStep', r),
      },
      p,
    );
  });
  handle('publish:markPosted', async (p) => {
    const m = await needClient().manifest(p.batchId);
    const confirmed = pstore.confirmations(p.batchId).some((c) => c.code === p.code);
    const inList = m.manifest?.confirmation_code === p.code && m.manifest.items.some((i) => i.job === p.job && i.platform === p.platform);
    if (!confirmed || !inList) throw new Error('only items of a confirmed package can be marked posted');
    const a = adapterById(p.adapterId);
    if (p.url && !hostAllowed(new URL(p.url).hostname, a.allowedHosts)) throw new Error(`post URL must be on ${a.name}`);
    return pstore.markPosted({ batchId: p.batchId, code: p.code, job: p.job, platform: p.platform, adapterId: p.adapterId, account: p.account, url: p.url ?? null });
  });
  handle('publish:caption', async (p) => {
    const m = await needClient().manifest(p.batchId);
    const item = m.manifest?.items.find((i) => i.job === p.job && i.platform === p.platform);
    if (!item || !m.dir) throw new Error('item not in the package');
    const video = resolveInside(m.dir, item.files.video, path.sep);
    const post = item.files.post ? resolveInside(m.dir, item.files.post, path.sep) : null;
    const md = post && fs.existsSync(post) ? fs.readFileSync(post, 'utf8') : '';
    return { ...parsePostCopy(md, item.title), video: video ?? '' };
  });
  handle('publish:postedLog', async (p) => pstore.posted(p.batchId));

  // ---------------- first-run assets
  handle('assets:status', async () => ({ ...assets.status(), restartWhenIdle, bundled: resolvedConfig().runtime !== 'system' }));
  handle('assets:install', async (p) => {
    // queue only: downloads run in the background; nothing here may reload, navigate or quit
    void assets.install(p.ids).catch((e) => mainLog(`[assets] ${(e as Error)?.stack ?? e}`));
    return { ...assets.status(), restartWhenIdle };
  });
  handle('assets:cancel', async (p) => assets.cancel(p?.id));
  handle('update:check', async () => checkForUpdates());
  handle('update:install', async () => installUpdate());
  handle('history:watch', async (p) => {
    historyWatcher ??= new HistoryWatcher(() => win?.webContents.send('history:changed', { at: Date.now() }));
    rootsCache = { at: 0, roots: [] }; // new thumbnails / outputs become viewable at once
    return historyWatcher.set(p.roots);
  });
  registerV02Ipc(handle, { userData: app.getPath('userData'), settings: () => settings, win: () => win, client: () => client, settingsMsg });
  registerCleanupIpc(handle, { win: () => win, client: () => client, lang: () => (settings.get().lang === 'zh-CN' ? 'zh' : 'en') });
}

function loadAssetManifest(): AssetManifest {
  try {
    // DESK_ASSETS_MANIFEST: tests point the downloader at a local server
    const file = process.env.DESK_ASSETS_MANIFEST || path.join(RES, 'packaging', 'assets.json');
    return JSON.parse(fs.readFileSync(file, 'utf8')) as AssetManifest;
  } catch (e) {
    console.warn('[assets] no manifest:', (e as Error).message);
    return { groups: [] };
  }
}

// ---------------------------------------------------------------- lifecycle
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
  app.on('web-contents-created', (_e, contents) => {
    contents.on('will-attach-webview', (ev) => ev.preventDefault());
  });
  app.whenReady().then(() => {
    if (process.env.DESK_HIDE_WINDOW === '1') app.dock?.hide();
    settings = new SettingsStore(app.getPath('userData'));
    runtime = findBundledRuntime(RES, app.isPackaged);
    assets = new AssetManager({
      manifest: loadAssetManifest(),
      dir: assetsDir(),
      onChange: (s) => win?.webContents.send('assets:progress', { ...s, restartWhenIdle }),
      onIdle: () => void restartForAssets(),
      log: mainLog,
      roots: { core: engineCacheDir() },
      hfHub: hfHubDir(),
    });
    mainLog(`[assets] dir ${assetsDir()} · engine cache ${engineCacheDir()} · hf hub ${hfHubDir() ?? '-'}`);
    // already on disk (CLI install.sh, Hugging Face cache)? startEngine() scans first, so the first engine has them
    pstore = new PublishStore(path.join(app.getPath('userData'), 'publish'));
    adapters = loadAdapters([path.join(RES, 'adapters'), path.join(app.getPath('userData'), 'adapters')]);
    for (const e of adapters.errors) console.warn(`[adapters] ${e.file}: ${e.error}`);
    hardenDefaultSession();
    registerProtocols();
    registerIpc();
    void startEngine().catch(() => undefined); // failures are reported through engine:status
    createWindow();
    initUpdater((u) => win?.webContents.send('update:state', u));
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
  app.on('render-process-gone', (_e, wc, details) => {
    mainLog(`[main] renderer gone: ${details.reason} (${details.exitCode})`);
    if (win && wc === win.webContents && details.reason !== 'clean-exit') win.reload();
  });
  app.on('child-process-gone', (_e, details) => mainLog(`[main] child process gone: ${details.type} ${details.reason}`));
  app.on('window-all-closed', () => {
    // a download in progress keeps the app alive (the downloads finish in the background; reopen from the dock /
    // taskbar); otherwise quit, except on macOS
    if (process.platform !== 'darwin' && !assets?.busy) app.quit();
  });
  let quitConfirmed = false;
  app.on('before-quit', (e) => {
    if (assets?.busy && !quitConfirmed) {
      const choice = dialog.showMessageBoxSync({
        type: 'question',
        buttons: [settings?.get().lang === 'en' ? 'Keep downloading' : '继续下载', settings?.get().lang === 'en' ? 'Stop and quit' : '停止下载并退出'],
        defaultId: 0,
        cancelId: 0,
        message: settings?.get().lang === 'en' ? 'Downloads are still running.' : '模型还在下载。',
        detail: settings?.get().lang === 'en' ? 'Quitting stops them; they resume next time.' : '退出会中断下载，下次打开会接着下载。',
      });
      if (choice === 0) {
        e.preventDefault();
        return;
      }
      quitConfirmed = true;
      assets.cancel();
    }
    void engine?.stop();
  });
}
