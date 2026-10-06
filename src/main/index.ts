// Electron main process: window + security, engine sidecar, media protocol, IPC, publish browser.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { app, BrowserWindow, clipboard, dialog, ipcMain, net, protocol, session, shell, type IpcMainInvokeEvent } from 'electron';
import { EngineClient } from '../shared/engineClient';
import { validateIpc, type IpcChannel, type IpcPayload } from '../shared/ipc';
import { hostAllowed, type Adapter } from '../shared/publish/adapterSchema';
import { resolveInside } from '../shared/publish/gating';
import { parsePostCopy } from '../shared/publish/postCopy';
import type { EngineInfo } from '../shared/types';
import type { AssetManifest } from '../shared/assets';
import { AssetManager } from './assets';
import { defaultEnginePath, EngineProcess, findPython } from './engine';
import { isAllowedMediaPath, pathFromMediaUrl } from './media';
import { loadAdapters } from './publish/adapters';
import { PublishBrowser } from './publish/browser';
import { assistedFill } from './publish/fill';
import { PublishStore } from './publish/store';
import { findBundledRuntime, runtimeEnv, type BundledRuntime } from './runtime';
import { buildCsp, isAppUrl, isSafeExternal } from './security';
import { SettingsStore } from './settings';
import { checkForUpdates, initUpdater, installUpdate } from './updater';

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

function assetsDir() {
  return path.join(app.getPath('userData'), 'assets');
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
  const r = runtimeEnv(runtime, path.join(RES, 'engine', 'runtime_shim'));
  return {
    ...r,
    isolatePython: true,
    env: {
      ...r.env,
      VSTUDIO_CACHE: path.join(assetsDir(), 'vstudio-cache'),
      HF_HOME: path.join(assetsDir(), 'hf'),
      ...assets.env(),
    },
  };
}

function startEngine(): Promise<EngineInfo> {
  engine?.stop();
  const cfg = resolvedConfig();
  engine = new EngineProcess({
    engineDir: path.join(RES, 'engine'),
    enginePath: cfg.enginePath,
    python: cfg.python,
    dataDir: cfg.dataDir,
    allowedOrigins: [APP_ORIGIN],
    mock: process.env.DESK_ENGINE_MOCK === '1',
    ...engineEnv(cfg.runtime !== 'system'),
  });
  assets.markEngineStarted();
  enginePromise = engine.start().then((info) => {
    client = new EngineClient(info.baseUrl, info.token);
    rootsCache = { at: 0, roots: [] };
    win?.webContents.send('engine:status', { ok: true, mode: info.mode, note: info.note });
    return info;
  });
  enginePromise.catch((e) => {
    client = null;
    win?.webContents.send('engine:status', { ok: false, error: String(e.message ?? e) });
  });
  return enginePromise;
}

// ---------------------------------------------------------------- media roots (from the engine)
let rootsCache = { at: 0, roots: [] as string[] };
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

function currentCsp(): string {
  const port = engine?.info ? Number(new URL(engine.info.baseUrl).port) : null;
  return buildCsp({ dev: IS_DEV, enginePort: port, devServerUrl: DEV_URL });
}

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
    },
  });
  win.once('ready-to-show', () => win?.show());
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
  void win.loadURL(IS_DEV ? DEV_URL! : 'app://desk/index.html');
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
      return await (enginePromise ?? startEngine());
    } catch (e) {
      throw new Error(`${(e as Error).message}\n${engine?.recentLog().slice(-20).join('\n') ?? ''}`, { cause: e });
    }
  });
  handle('engine:restart', async () => {
    const info = await startEngine();
    if (!IS_DEV) setTimeout(() => win?.reload(), 50); // new port -> new CSP
    return info;
  });
  handle('dialog:openFile', async (p) => {
    const filters =
      p.kind === 'video'
        ? [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'mkv', 'webm'] }]
        : [{ name: 'Segments', extensions: ['yaml', 'yml', 'csv', 'json'] }];
    const r = await dialog.showOpenDialog(win!, { properties: ['openFile'], filters });
    return r.canceled ? null : r.filePaths[0];
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
  handle('settings:get', async () => ({ ...settings.get(), resolved: resolvedConfig() }));
  handle('settings:set', async (p) => {
    if (p.enginePath && !fs.existsSync(path.join(p.enginePath, 'lib', 'vstudio'))) {
      throw new Error('enginePath must be the video-studio repo (with lib/vstudio)');
    }
    if (p.python && !fs.existsSync(p.python)) throw new Error('python not found');
    const before = settings.get();
    const next = settings.set(p);
    if (next.enginePath !== before.enginePath || next.python !== before.python) {
      void startEngine().then(() => !IS_DEV && win?.reload());
    }
    return { ...next, resolved: resolvedConfig() };
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
  handle('assets:status', async () => ({ ...assets.status(), bundled: resolvedConfig().runtime !== 'system' }));
  handle('assets:install', async (p) => {
    void assets.install(p.ids).catch((e) => console.error('[assets]', e));
    return assets.status();
  });
  handle('assets:cancel', async () => assets.cancel());
  handle('update:check', async () => checkForUpdates());
  handle('update:install', async () => installUpdate());
}

function loadAssetManifest(): AssetManifest {
  try {
    return JSON.parse(fs.readFileSync(path.join(RES, 'packaging', 'assets.json'), 'utf8')) as AssetManifest;
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
    settings = new SettingsStore(app.getPath('userData'));
    runtime = findBundledRuntime(RES, app.isPackaged);
    assets = new AssetManager({ manifest: loadAssetManifest(), dir: assetsDir(), onChange: (s) => win?.webContents.send('assets:progress', s) });
    pstore = new PublishStore(path.join(app.getPath('userData'), 'publish'));
    adapters = loadAdapters([path.join(RES, 'adapters'), path.join(app.getPath('userData'), 'adapters')]);
    for (const e of adapters.errors) console.warn(`[adapters] ${e.file}: ${e.error}`);
    hardenDefaultSession();
    registerProtocols();
    registerIpc();
    void startEngine().catch((e) => console.error('[engine]', e.message));
    createWindow();
    initUpdater((u) => win?.webContents.send('update:state', u));
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });
  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit();
  });
  app.on('before-quit', () => {
    engine?.stop();
  });
}
