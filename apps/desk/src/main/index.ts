// Electron main process: window + security, engine sidecar, media protocol, IPC, publish browser.
import fs from 'node:fs';
import os from 'node:os';
import { createServer as createNetServer, type AddressInfo } from 'node:net';
import path from 'node:path';
import { Readable } from 'node:stream';
import { app, BrowserWindow, clipboard, dialog, ipcMain, Notification, protocol, safeStorage, session, shell, type IpcMainInvokeEvent } from 'electron';
import { EngineClient } from '../shared/engineClient';
import { channelKey, listChannels } from '../shared/channels';
import { partitionFor, validateIpc, type IpcChannel, type IpcPayload } from '../shared/ipc';
import { hostAllowed, type Adapter } from '../shared/publish/adapterSchema';
import { resolveInside } from '../shared/publish/gating';
import { parsePostCopy } from '../shared/publish/postCopy';
import type { EngineInfo } from '../shared/types';
import type { AssetManifest } from '../shared/assets';
import { AssetManager, defaultHfHub, sharedEngineCache } from './assets';
import { registerAiIpc, syncRoutesFile } from './aiAccounts';
import { APP_MIME, resolveAppFile } from './appProtocol';
import { installAppMenu } from './appMenu';
import { defaultEnginePath, EngineProcess, engineProcessEnv, findPython } from './engine';
import { allowedMedia, mediaMime, parseRange, pathFromMediaUrl } from './media';
import { loadAdapters } from './publish/adapters';
import { PublishBrowser } from './publish/browser';
import { assistedFill } from './publish/fill';
import { PublishStore } from './publish/store';
import { ApiVault } from './publish/api/vault';
import { YouTubeApi } from './publish/api/youtube';
import { CAPTURE_JS, saveCapture, type CaptureResult } from './publish/capture';
import { probeLogin } from './publish/loginProbe';
import { fillScheduledPost } from './publish/postFill';
import { PublishScheduler } from './publish/scheduler';
import { AppTray, applyLoginItem, startedHidden } from './tray';
import { copyForPost, pickFile } from '../shared/publish/postNow';
import { API_PLATFORMS, type ApiStatusMsg } from '../shared/publish/apiPlatforms';
import { PLATFORMS } from '../shared/platforms';
import type { CalendarPost } from '../shared/v04';
import { findBundledRuntime, runtimeEnv, type BundledRuntime } from './runtime';
import { buildCsp, isAppUrl, isSafeExternal } from './security';
import { installMediaPermissions, registerRecorderIpc, type Recorder } from './recorder';
import { createFlagFrom } from '../shared/recIpc';
import { SettingsStore } from './settings';
import { HistoryWatcher } from './historyWatch';
import { UsageReporter, usageAllowedByEnv } from './usage';
import { APP_NAME, applyIdentity } from './identity';
import { SecretStore } from './secrets';
import { checkForUpdates, initUpdater, installUpdate } from './updater';
import { registerCleanupIpc, registerV02Ipc, v02EngineEnv } from './v02';
import { devOnly, setPackaged, tempOnly, testSwitch } from './testHooks';
import { openFeedback, recordProblem, registerSupportIpc } from './support';

protocol.registerSchemesAsPrivileged([
  { scheme: 'app', privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
  { scheme: 'vsmedia', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

const DEV_URL = !app.isPackaged ? process.env.VITE_DEV_SERVER_URL : undefined;
const IS_DEV = Boolean(DEV_URL);
const APP_ORIGIN = IS_DEV ? new URL(DEV_URL!).origin : 'app://desk';
const RENDERER_DIR = path.join(__dirname, '../renderer');
setPackaged(app.isPackaged);
// Create recorder e2e: Chromium's fake camera / mic and auto-accepted prompts (dev and test builds only)
const FAKE_MEDIA = !app.isPackaged && process.env.DESK_E2E_FAKE_MEDIA === '1';
if (FAKE_MEDIA) {
  app.commandLine.appendSwitch('use-fake-device-for-media-stream');
  app.commandLine.appendSwitch('use-fake-ui-for-media-stream');
}
const RES = app.isPackaged ? process.resourcesPath : app.getAppPath();
/** Reelfold brand icons (scripts/brand/icons.mjs): 256 px for windows / About on Windows + Linux, 1024 px for the dev Dock. */
const ICON_256 = path.join(RES, 'packaging/resources/icons/256x256.png');
const ICON_DOCK = path.join(RES, 'packaging/resources/icon.png');
const brandIcon = (f: string) => (fs.existsSync(f) ? f : undefined);

// Reelfold name + profile folder (an old Daycut / video-studio desk profile is copied over once) + the keychain key
// its encrypted data needs; DESK_USER_DATA: tests, isolated profile
const IDENTITY = applyIdentity(app, process.env.DESK_USER_DATA, (s) => mainLog(s));
// Chromium's own widgets (date / time inputs) follow the UI language: read it before 'ready' (a change applies on
// the next launch); the app's copy itself switches live through the i18n adapter
try {
  const saved = JSON.parse(fs.readFileSync(path.join(app.getPath('userData'), 'settings.json'), 'utf8')) as { lang?: string };
  const l = saved.lang === 'zh' || saved.lang === 'zh-CN' ? 'zh-CN' : saved.lang?.startsWith('fr') ? 'fr' : 'en-US';
  app.commandLine.appendSwitch('lang', l);
} catch {
  /* first launch: the system language */
}

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
process.on('unhandledRejection', (e) => {
  mainLog(`[main] unhandled rejection: ${(e as Error)?.stack ?? String(e)}`);
  recordProblem('main', 'unhandled-rejection', (e as Error)?.message ?? String(e), (e as Error)?.stack);
});
process.on('uncaughtException', (e) => {
  mainLog(`[main] uncaught exception: ${e?.stack ?? String(e)}`);
  recordProblem('main', 'uncaught-exception', e?.message ?? String(e), e?.stack);
});

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
let recorder: Recorder | null = null;
let scheduler: PublishScheduler | null = null;
let vault: ApiVault;
let youtube: YouTubeApi;
let tray: AppTray | null = null;
/** started by the OS at login: stay in the menu bar until she opens the window */
const HIDDEN_START = startedHidden();

function dataDir() {
  return path.join(app.getPath('userData'), 'engine-data');
}

/** Downloads, partial files and the installed-manifest. Stable: <userData>/assets (tests override userData only). */
function assetsDir() {
  return path.join(app.getPath('userData'), 'assets');
}

/** The engine's cache, shared with the CLI skill (fonts + MediaPipe models live there). DESK_SHARED_CACHE: tests. */
function engineCacheDir() {
  return tempOnly('DESK_SHARED_CACHE') || sharedEngineCache();
}

/** The Hugging Face hub cache (Whisper is reused from it). DESK_HF_HUB: tests ('' = none). */
function hfHubDir(): string | null {
  const hub = tempOnly('DESK_HF_HUB');
  return hub !== undefined ? hub || null : defaultHfHub();
}

/** Settings override everything; then env vars; then the runtime bundled in the app; then a dev checkout. */
function resolvedConfig() {
  const s = settings.get();
  // packaged: the bundled runtime only (a renderer-set Python / engine path would run another binary as Reelfold)
  const python = (!app.isPackaged && s.python) || devOnly('DESK_PYTHON') || runtime?.python || findPython();
  const bundled = Boolean(runtime && python === runtime.python);
  return {
    enginePath: defaultEnginePath(app.getAppPath(), app.isPackaged ? undefined : s.enginePath, bundled ? runtime!.vstudio : undefined),
    python,
    dataDir: dataDir(),
    runtime: bundled ? `bundled · Python ${runtime!.manifest.python} · video-studio@${runtime!.manifest.vstudioCommit.slice(0, 7)}` : 'system',
  };
}

/** Create: local draft generation (second flag) is passed to the engine as VSTUDIO_CREATE_LOCAL=1. */
function createEnv(): Record<string, string> {
  return createOn() && settings?.get().createLocalGen ? { VSTUDIO_CREATE_LOCAL: '1' } : {};
}

function engineEnv(bundled: boolean) {
  if (!bundled || !runtime) return { env: { ...assets.env(), ...createEnv() } };
  const r = runtimeEnv(runtime);
  return {
    ...r,
    isolatePython: true,
    env: {
      ...r.env,
      // one cache with the CLI skill: fonts / models the user already has are used, nothing is fetched twice
      VSTUDIO_CACHE: engineCacheDir(),
      ...assets.env(),
      ...createEnv(),
    },
  };
}

/** v0.2: API keys from the OS keychain + imported persona, for the sidecar only. */
function withV02Env<T extends { env?: Record<string, string> }>(e: T): T {
  return { ...e, env: { ...e.env, ...v02EngineEnv(app.getPath('userData'), settings.get()) } };
}

/** Create page flag: the saved setting; DESK_CREATE=1/0 overrides it in dev / test builds only. */
function createOn(): boolean {
  return createFlagFrom(settings?.get().createPage, app.isPackaged ? undefined : process.env.DESK_CREATE);
}

function settingsMsg() {
  const s = settings.get();
  return { ...s, createPage: createOn(), firstRunDone: s.firstRunDone || testSwitch('DESK_SKIP_FIRST_RUN'), resolved: resolvedConfig(), packaged: app.isPackaged, platform: process.platform };
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
/** the running engine's mode: batches in the demo (mock) engine are never counted as usage */
let engineMode: EngineInfo['mode'] | null = null;
let usage: UsageReporter | null = null;
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
      mock: testSwitch('DESK_ENGINE_MOCK'),
      onCrash: (code, tail) => recordProblem('sidecar', `exit ${code}`, `engine exited (${code})`, tail.join('\n')),
      port: enginePort() ?? port ?? undefined,
      onDied: (detail) => onEngineCrash(gen, detail),
      ...withV02Env(engineEnv(cfg.runtime !== 'system')),
    });
    engine = next;
    assets.markEngineStarted();
    return next.start();
  });
  enginePromise = p.then((info) => {
    if (gen !== engineGen) throw new SupersededError();
    engineMode = info.mode;
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

/** The engine died after it was up: say so at once (the status dot / banner), then start a new one - at most 3 times
 * in 2 minutes, so a engine that dies at start-up does not loop; after that the banner's "Fix" link stays. */
const crashes: number[] = [];
function onEngineCrash(gen: number, detail: string) {
  if (gen !== engineGen) return;
  mainLog(`[engine] crashed: ${detail}`);
  client = null;
  const now = Date.now();
  while (crashes.length && now - crashes[0] > 120_000) crashes.shift();
  crashes.push(now);
  const retry = crashes.length <= 3;
  win?.webContents.send('engine:status', { ok: false, error: detail, restarting: retry });
  if (retry) setTimeout(() => void startEngine().catch(() => undefined), 500 * crashes.length);
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
  return buildCsp({ dev: IS_DEV, enginePort: enginePort(), devServerUrl: DEV_URL, create: createOn() });
}

/** Engine port baked into the CSP of the page the window last loaded (undefined: nothing loaded yet). */
let servedPort: number | null | undefined;

const MIME = APP_MIME;

function registerProtocols() {
  protocol.handle('app', async (req) => {
    const u = new URL(req.url);
    if (u.host !== 'desk') return new Response('not found', { status: 404 });
    const hit = resolveAppFile(RENDERER_DIR, u.pathname);
    if (hit === null) return new Response('forbidden', { status: 403 });
    let file = hit === 'index' ? path.join(RENDERER_DIR, 'index.html') : hit;
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
    let roots = await mediaRoots();
    if (!p) return new Response('forbidden', { status: 403 });
    // judged on the real path (roots carry their real form too): see allowedMedia
    let real: string;
    try {
      real = await fs.promises.realpath(p);
    } catch {
      return new Response('not found', { status: 404 });
    }
    const ok = () => allowedMedia(p, real, roots);
    if (!ok()) {
      // allowed a moment ago (a timeline sprite made by the request just before this one): ask the engine again -
      // also when the cached list is only milliseconds old, or the picture stays a 403 for good
      rootsCache.at = 0;
      roots = await mediaRoots();
    }
    if (!ok()) return new Response('forbidden', { status: 403 });
    // ranges answered here (206): file:// fetches ignore Range, and without it a video can only seek inside what is
    // already buffered (long outputs could not be scrubbed)
    const size = await fs.promises.stat(real).then((st) => st.size, () => -1);
    if (size < 0) return new Response('not found', { status: 404 });
    const type = mediaMime(real);
    const r = parseRange(req.headers.get('range'), size);
    if (r === 'invalid') return new Response(null, { status: 416, headers: { 'content-range': `bytes */${size}` } });
    const span = r ?? { start: 0, end: size - 1 };
    const body = size ? (Readable.toWeb(fs.createReadStream(real, { start: span.start, end: span.end })) as unknown as ReadableStream) : null;
    return new Response(body, {
      status: r ? 206 : 200,
      headers: {
        'content-type': type,
        'accept-ranges': 'bytes',
        'content-length': String(size ? span.end - span.start + 1 : 0),
        ...(r ? { 'content-range': `bytes ${span.start}-${span.end}/${size}` } : {}),
      },
    });
  });
}

function hardenDefaultSession() {
  const ses = session.defaultSession;
  // deny by default; the one exception is camera / mic for the Create recorder in our own window (flag on)
  installMediaPermissions(ses, { flag: createOn, mainWebContents: () => win?.webContents ?? null, isApp: (u) => isAppUrl(u, APP_ORIGIN) });
  if (createOn() && process.platform === 'darwin' && Number(os.release().split('.')[0]) >= 24) {
    // screen recording: the macOS system picker (15+); nothing is captured unless the creator picks a screen
    ses.setDisplayMediaRequestHandler((_req, cb) => cb({}), { useSystemPicker: true });
  }
  ses.on('will-download', (e) => e.preventDefault());
  if (IS_DEV) {
    ses.webRequest.onHeadersReceived((d, cb) => {
      const headers = { ...d.responseHeaders };
      if (isAppUrl(d.url, APP_ORIGIN)) headers['Content-Security-Policy'] = [currentCsp()];
      cb({ responseHeaders: headers });
    });
  }
}

function createWindow(route?: string, show = true) {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#0E1113',
    title: APP_NAME,
    ...(process.platform !== 'darwin' && brandIcon(ICON_256) ? { icon: ICON_256 } : {}), // macOS: the bundle icon
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    show: false,
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.cjs'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: false,
      spellcheck: false,
      backgroundThrottling: !testSwitch('DESK_HIDE_WINDOW'),
    },
  });
  // DESK_HIDE_WINDOW=1: automated tests drive the app without putting windows on the user's screen
  if (!testSwitch('DESK_HIDE_WINDOW') && show) win.once('ready-to-show', () => win?.show());
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
  browser = new PublishBrowser(win, (s) => win?.webContents.send('publish:state', s), noteLogin);
  // Load once the engine is up (or failed / is slow) so the page's CSP already carries the engine port;
  // startEngine() reloads the page if the port changes later.
  const url = (IS_DEV ? DEV_URL! : 'app://desk/index.html') + (route && /^#\/[A-Za-z0-9/_.%?=&-]{0,200}$/.test(route) ? route : '');
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

/** Show the window on a route (a notification / the menu-bar item was clicked); recreate it when it was closed. */
function openRoute(route?: string) {
  if (!win) {
    createWindow(route);
    return;
  }
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  if (route) win.webContents.send('notify:open', { route });
}

const MAIN_COPY = {
  en: { time: (t: string, pf: string) => `Time to post: ${t} → ${pf}`, body: 'Click to open the upload page with everything filled in. You press Publish.', many: (n: number) => `${n} posts are due`, manyBody: (l: string) => l, open: 'Open Reelfold', quit: 'Quit Reelfold', none: 'Nothing due', due: (n: number) => (n === 1 ? '1 post is due' : `${n} posts are due`) },
  'zh-CN': { time: (t: string, pf: string) => `该发了：${t} → ${pf}`, body: '点击打开上传页，内容都会填好，最后由你点发布。', many: (n: number) => `有 ${n} 条该发了`, manyBody: (l: string) => l, open: '打开千剪', quit: '退出千剪', none: '暂时没有要发的', due: (n: number) => `有 ${n} 条该发了` },
  fr: { time: (t: string, pf: string) => `C’est l’heure de publier : ${t} → ${pf}`, body: 'Cliquez pour ouvrir la page d’envoi déjà remplie. C’est vous qui publiez.', many: (n: number) => `${n} publications à faire`, manyBody: (l: string) => l, open: 'Ouvrir Reelfold', quit: 'Quitter Reelfold', none: 'Rien à publier', due: (n: number) => (n === 1 ? '1 publication à faire' : `${n} publications à faire`) },
};
const mainCopy = () => MAIN_COPY[settings?.get().lang ?? 'en'] ?? MAIN_COPY.en;
const pfLabel = (platform: string) => {
  const p = PLATFORMS.find((x) => x.id === platform.split(':')[0]);
  const l = settings?.get().lang ?? 'en';
  return p ? (l === 'zh-CN' ? p.labels.zh : l === 'fr' ? p.labels.fr : p.labels.en) : platform;
};

function notifyDue(due: CalendarPost[]) {
  if (!Notification.isSupported()) return;
  const rank = (p: CalendarPost) => PLATFORMS.findIndex((x) => x.id === p.platform.split(':')[0]);
  const fresh = [...due].sort((a, b) => a.at.localeCompare(b.at) || rank(a) - rank(b));
  const c = mainCopy();
  const one = fresh.length === 1 ? fresh[0] : null;
  const n = new Notification({
    title: one ? c.time(one.title, pfLabel(one.platform)) : c.many(fresh.length),
    body: one ? c.body : c.manyBody(fresh.slice(0, 4).map((p) => `${p.title} → ${pfLabel(p.platform)}`).join('\n')),
    silent: false,
  });
  n.on('click', () => openRoute(one ? `#/publish/post/${one.id}?go=1` : '#/publish'));
  n.show();
  mainLog(`[scheduler] due: ${fresh.map((p) => `${p.id} ${p.platform} ${p.at}`).join(', ')}`);
}

function apiStatus(): ApiStatusMsg[] {
  const st = settings.get();
  return API_PLATFORMS.map((a) => {
    const yt = a.id === 'youtube' ? youtube.status() : { hasClient: false, connected: false, connectedAt: null };
    return { id: a.id, availability: a.availability, platforms: a.platforms, scopes: a.scopes, ...yt, auto: !!st.publishApi?.[a.id]?.auto && yt.connected, keychain: vault.keychain() };
  });
}

/** Rendered file + copy of a calendar row, for an API upload. */
async function apiPublish(p: CalendarPost, publishAt: Date | null): Promise<{ ok: true; url: string | null } | { ok: false; error: string }> {
  try {
    const doc = await needClient().clips(p.item);
    const clip = doc.clips.find((c) => c.id === p.clip);
    const file = clip ? pickFile(clip.files, p.platform) : null;
    if (!clip || !file || !fs.existsSync(file.path)) return { ok: false, error: 'the rendered video is missing' };
    const copy = copyForPost(p, true, [clip.title, clip.post?.title ?? ''].filter(Boolean));
    const r = await youtube.upload({ file: file.path, title: copy.title, description: copy.description, tags: copy.tags, publishAt });
    return { ok: true, url: r.url };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
}

function startScheduler() {
  scheduler = new PublishScheduler({
    load: async () => {
      await currentEngine();
      return (await needClient().calendar(undefined, { queue: false })).posts;
    },
    now: () => new Date(),
    notify: notifyDue,
    onChange: (due) => {
      win?.webContents.send('publish:due', { ids: due.map((p) => p.id) });
      tray?.update(due);
    },
    markPosted: async (p, url, via) => {
      await needClient().updatePost(p.id, { state: 'posted', via, ...(url ? { url } : {}) });
      win?.webContents.send('publish:posted', { postId: p.id, url });
    },
    api: {
      wants: (p) => ['youtube', 'youtube-shorts'].includes(p.platform.split(':')[0]) && !!settings.get().publishApi?.youtube?.auto && youtube.status().connected,
      publish: apiPublish,
    },
    stateFile: path.join(app.getPath('userData'), 'publish', 'scheduler.json'),
    log: mainLog,
  });
  scheduler.start();
}

/** Every publishing account's login state from its own partition's session cookies (the partition the built-in
 * browser panel uses: persist:<adapter>-<account>). */
let loginsAt = 0;
async function refreshLogins(force = false) {
  if (!force && Date.now() - loginsAt < 5000) return;
  loginsAt = Date.now();
  const st = settings.get();
  await Promise.all(
    Object.entries(st.accounts).flatMap(([adapterId, list]) =>
      list.map(async (account) => {
        const a = adapters.adapters.find((x) => x.id === adapterId);
        if (!a) return;
        const state = await probeLogin(session.fromPartition(partitionFor(adapterId, account)), a);
        if (state) noteLogin(adapterId, account, state);
      }),
    ),
  );
}

function channelList() {
  const st = settings.get();
  // international platforms first, then Chinese, then other languages (the shared registry order)
  const rank = (a: Adapter) => {
    const i = PLATFORMS.findIndex((p) => p.id === a.packagePlatforms[0]);
    return i < 0 ? 1e6 : i;
  };
  return listChannels(st.accounts, st.channels, [...adapters.adapters].sort((a, b) => rank(a) - rank(b)).map((a) => a.id));
}

/** The built-in browser saw an account's page: remember signed in / signed out (no cookies, only the state). */
function noteLogin(adapterId: string, account: string, state: 'in' | 'out') {
  const st = settings.get();
  if (!(st.accounts[adapterId] ?? []).includes(account)) return;
  const key = channelKey(adapterId, account);
  const cur = st.channels?.[key] ?? {};
  if (cur.login?.state === state && Date.now() - Date.parse(cur.login.at) < 60_000) return;
  settings.set({ channels: { ...(st.channels ?? {}), [key]: { ...cur, login: { state, at: new Date().toISOString() } } } });
  if (cur.login?.state !== state) win?.webContents.send('publish:channels', { adapterId, account, state });
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
          : p.kind === 'python'
            ? []
            : [{ name: 'Segments', extensions: ['yaml', 'yml', 'csv', 'json'] }];
    if (p.kind === 'board') {
      // a board file or a project folder (HyperFrames): both selectable on macOS
      const props: ('openFile' | 'openDirectory')[] = process.platform === 'darwin' ? ['openFile', 'openDirectory'] : ['openFile'];
      const r = await dialog.showOpenDialog(win!, { properties: props, filters: [{ name: 'Board', extensions: ['md', 'markdown', 'json', 'csv', 'tsv', 'txt', 'edl', 'otio', 'xml', 'fcpxml', 'html'] }] });
      return r.canceled ? null : r.filePaths[0];
    }
    const r = await dialog.showOpenDialog(win!, { properties: ['openFile', ...(p.kind === 'python' ? (['showHiddenFiles'] as const) : [])], filters });
    return r.canceled ? null : r.filePaths[0];
  });
  handle('notify:show', async (p) => {
    if (!Notification.isSupported() || win?.isFocused() || testSwitch('DESK_HIDE_WINDOW')) return;
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
  handle('shell:openLogs', async () => {
    const dir = path.join(app.getPath('userData'), 'logs');
    fs.mkdirSync(dir, { recursive: true });
    await shell.openPath(dir);
  });
  handle('clipboard:write', async (p) => clipboard.writeText(p.text));
  // ---------------- opt-in anonymous usage counts (main/usage.ts); no-ops while sharing is off
  handle('usage:status', async () => usage!.status());
  handle('usage:track', async (p) => usage?.track(p.ev, p.n));
  handle('usage:resetId', async () => usage!.resetId());
  handle('usage:delete', async () => usage!.deleteData());
  handle('settings:get', async () => settingsMsg());
  handle('settings:set', async (p) => {
    if (app.isPackaged && (p.enginePath !== undefined || p.python !== undefined)) throw new Error('engine path and Python are fixed in this build');
    if (p.enginePath && !fs.existsSync(path.join(p.enginePath, 'lib', 'vstudio'))) {
      throw new Error('enginePath must be the video-studio repo (with lib/vstudio)');
    }
    if (p.python && !fs.existsSync(p.python)) throw new Error('python not found');
    const before = settings.get();
    const next = settings.set(p);
    if (next.lang !== before.lang) menu();
    if (p.usagePings !== undefined && p.usagePings !== before.usagePings) usage?.consentChanged(p.usagePings === 'on');
    if (p.openAtLogin !== undefined && p.openAtLogin !== before.openAtLogin) {
      applyLoginItem(p.openAtLogin);
      tray?.set(p.openAtLogin);
    }
    // engine path / Python apply on the next engine start: Settings shows "Restart to apply" (one click)
    return { ...settingsMsg(), ...next, createPage: createOn(), firstRunDone: settingsMsg().firstRunDone, resolved: resolvedConfig(), packaged: app.isPackaged, platform: process.platform };
  });

  // ---------------- publish
  handle('publish:adapters', async () => adapters);
  handle('publish:accounts', async () => settings.get().accounts);
  handle('publish:addAccount', async (p) => {
    const adapter = adapterById(p.adapterId);
    const st = settings.get();
    const acc = st.accounts;
    const list = new Set(acc[p.adapterId] ?? []);
    list.add(p.account);
    acc[p.adapterId] = [...list];
    // adding an account = "I post here": the platform joins her platforms (Settings › General), so it shows on the
    // board and in a post's Where; an account added earlier for a platform she then dropped stays out of the way
    const pf = adapter.packagePlatforms[0];
    const mine = st.defaultPlatforms ?? [];
    const defaultPlatforms = mine.some((x) => x.split(':')[0] === pf) || mine.length >= 8 ? mine : [...mine, pf];
    const out = settings.set({ accounts: acc, defaultPlatforms }).accounts;
    await refreshLogins(true); // a session already signed in (the same label added again) counts at once
    return out;
  });
  handle('publish:channels', async () => {
    await refreshLogins();
    return channelList();
  });
  handle('publish:updateChannel', async (p) => {
    adapterById(p.adapterId);
    const st = settings.get();
    if (!(st.accounts[p.adapterId] ?? []).includes(p.account)) throw new Error('unknown account');
    const key = channelKey(p.adapterId, p.account);
    const cur = st.channels?.[key] ?? {};
    const next = { ...cur, ...(p.name !== undefined ? { name: p.name.trim() || undefined } : {}), ...(p.times ? { times: [...new Set(p.times)].sort() } : {}) };
    settings.set({ channels: { ...(st.channels ?? {}), [key]: next } });
    return channelList();
  });
  handle('publish:removeAccount', async (p) => {
    const st = settings.get();
    const acc = { ...st.accounts, [p.adapterId]: (st.accounts[p.adapterId] ?? []).filter((x) => x !== p.account) };
    if (!acc[p.adapterId].length) delete acc[p.adapterId];
    const ch = { ...(st.channels ?? {}) };
    delete ch[channelKey(p.adapterId, p.account)];
    settings.set({ accounts: acc, channels: ch });
    // sign out = forget this account's built-in browser session (its own partition only)
    if (p.signOut) {
      browser?.forget(p.adapterId, p.account);
      await session.fromPartition(partitionFor(p.adapterId, p.account)).clearStorageData().catch(() => undefined);
    }
    return channelList();
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
  // ---------------- the publish loop: due posts, fill one scheduled post, page capture, official APIs
  handle('publish:due', async () => {
    const r = scheduler ? await scheduler.tick() : { due: [] };
    return { ids: r.due.map((p) => p.id), api: Object.fromEntries(r.due.map((p) => [p.id, scheduler?.apiState(p.id) ?? null])) };
  });
  handle('publish:fillPost', async (p) => {
    const out = await fillScheduledPost(
      {
        client: needClient(),
        adapters: adapters.adapters,
        browser: browser!,
        accounts: settings.get().accounts,
        onStep: (r) => win?.webContents.send('publish:fillStep', r),
        onPosted: (postId, url) => {
          win?.webContents.send('publish:posted', { postId, url });
          void scheduler?.tick();
        },
        log: mainLog,
      },
      p,
    );
    if (!out.ok) mainLog(`[publish] fill ${p.postId}: ${out.reason}${out.detail ? ` (${out.detail})` : ''}`);
    return out;
  });
  handle('publish:capture', async () => {
    const e = browser?.active;
    if (!e) throw new Error('open a platform page first');
    const c = (await e.view.webContents.executeJavaScriptInIsolatedWorld(1003, [{ code: CAPTURE_JS }])) as CaptureResult;
    const file = saveCapture(path.join(app.getPath('userData'), 'captures'), e.adapter.id, c);
    mainLog(`[publish] page capture ${e.adapter.id}: ${file} (${c.nodes} nodes)`);
    return { file, nodes: c.nodes };
  });
  handle('publish:apiStatus', async () => apiStatus());
  handle('publish:apiClient', async (p) => {
    youtube.setClient(p.clientId.trim(), p.clientSecret.trim());
    return apiStatus();
  });
  handle('publish:apiConnect', async () => {
    await youtube.connect();
    return apiStatus();
  });
  handle('publish:apiDisconnect', async (p) => {
    await youtube.disconnect();
    if (p.forgetClient) vault.set('youtube', null);
    settings.set({ publishApi: { ...(settings.get().publishApi ?? {}), youtube: { auto: false } } });
    return apiStatus();
  });
  handle('publish:apiAuto', async (p) => {
    if (p.auto && !youtube.status().connected) throw new Error('connect YouTube first');
    settings.set({ publishApi: { ...(settings.get().publishApi ?? {}), [p.id]: { auto: p.auto } } });
    void scheduler?.tick();
    return apiStatus();
  });

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
  registerSupportIpc(handle, { settings: () => settings, win: () => win, engineMode: () => engine?.info?.mode ?? null });
  registerV02Ipc(handle, { userData: app.getPath('userData'), settings: () => settings, win: () => win, client: () => client, settingsMsg });
  primeAiRoutes = registerAiIpc(handle, {
    userData: app.getPath('userData'),
    settings: () => settings,
    win: () => win,
    log: mainLog,
    python: () => {
      const cfg = resolvedConfig();
      const e = withV02Env(engineEnv(cfg.runtime !== 'system')) as { env?: Record<string, string>; path?: string[]; pythonPath?: string[]; isolatePython?: boolean };
      return { python: cfg.python, env: engineProcessEnv({ ...e, enginePath: cfg.enginePath }) };
    },
  });
  recorder = registerRecorderIpc(handle, { flag: createOn, fakeMedia: FAKE_MEDIA });
  registerCleanupIpc(handle, { win: () => win, client: () => client, lang: () => (settings.get().lang === 'zh-CN' ? 'zh' : 'en') });
}

let primeAiRoutes: { primeRoutes: () => Promise<void> } | null = null;

function loadAssetManifest(): AssetManifest {
  try {
    // DESK_ASSETS_MANIFEST: tests point the downloader at a local server
    const file = devOnly('DESK_ASSETS_MANIFEST') || path.join(RES, 'packaging', 'assets.json');
    return JSON.parse(fs.readFileSync(file, 'utf8')) as AssetManifest;
  } catch (e) {
    console.warn('[assets] no manifest:', (e as Error).message);
    return { groups: [] };
  }
}

// ---------------------------------------------------------------- lifecycle
/**
 * A profile copied from Daycut / video-studio desk keeps its old keychain key (identity.ts): log whether its encrypted
 * data still reads (API keys in secrets.json, cookies of the publish browser's signed-in sessions), so a denied
 * keychain prompt shows up in main.log instead of as silently missing logins. Counts only, never values.
 */
async function reportMigratedProfile() {
  try {
    const ud = app.getPath('userData');
    const keys = Object.values(new SecretStore(ud, safeStorage).status().keys);
    const stored = (() => {
      try {
        return Object.values(JSON.parse(fs.readFileSync(path.join(ud, 'secrets.json'), 'utf8')) as Record<string, string>).filter(Boolean).length;
      } catch {
        return 0;
      }
    })();
    const parts = fs.existsSync(path.join(ud, 'Partitions')) ? fs.readdirSync(path.join(ud, 'Partitions')) : [];
    let signedIn = 0;
    for (const p of parts) if ((await session.fromPartition(`persist:${p}`).cookies.get({})).some((c) => c.value !== '')) signedIn++;
    mainLog(`[identity] migrated profile, keychain key "${IDENTITY.internalName} Safe Storage": API keys readable ${keys.filter(Boolean).length}/${stored}; sessions with readable cookies ${signedIn}/${parts.length}`);
  } catch (e) {
    mainLog(`[identity] could not check the migrated profile: ${(e as Error).message}`);
  }
}

function menu() {
  installAppMenu({ lang: settings?.get().lang ?? 'en', res: RES, win: () => win, iconPath: brandIcon(ICON_256), onFeedback: () => openFeedback(win) });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => openRoute());
  app.on('web-contents-created', (_e, contents) => {
    contents.on('will-attach-webview', (ev) => ev.preventDefault());
  });
  app.whenReady().then(() => {
    if (testSwitch('DESK_HIDE_WINDOW')) app.dock?.hide();
    settings = new SettingsStore(app.getPath('userData'));
    usage = new UsageReporter({
      dir: app.getPath('userData'),
      consent: () => settings.get().usagePings === 'on',
      allowed: usageAllowedByEnv(process.env, app.isPackaged),
      version: app.getVersion(),
      platform: process.platform,
      arch: process.arch,
      lang: () => settings.get().lang,
      demo: () => testSwitch('DESK_ENGINE_MOCK') || engineMode === 'mock',
      base: devOnly('REELFOLD_USAGE_BASE'),
      log: mainLog,
    });
    // at most one app_open per day (also when the app stays open past midnight); sends what waited offline
    usage.track('app_open');
    void usage.flush();
    setInterval(() => {
      usage?.track('app_open');
      void usage?.flush();
    }, 3600_000).unref();
    mainLog(`[main] ${APP_NAME} ${app.getVersion()} · profile ${app.getPath('userData')}${IDENTITY.migrated ? ` (migrated; keychain key "${IDENTITY.internalName} Safe Storage")` : ''}`);
    menu();
    // dev: the Dock (and the About panel, which uses the same NSApp icon) shows Reelfold, not the Electron atom. The
    // packaged app and the dev Reelfold.app copy (scripts/devApp.mjs) carry icon.icns already; this covers `electron .`.
    if (!app.isPackaged && process.platform === 'darwin' && brandIcon(ICON_DOCK)) app.dock?.setIcon(ICON_DOCK);
    syncRoutesFile(app.getPath('userData'), settings.get().aiRoutes);
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
    vault = new ApiVault(app.getPath('userData'), safeStorage);
    youtube = new YouTubeApi({ vault, openExternal: (u) => shell.openExternal(u), log: mainLog });
    adapters = loadAdapters([path.join(RES, 'adapters'), path.join(app.getPath('userData'), 'adapters')]);
    for (const e of adapters.errors) console.warn(`[adapters] ${e.file}: ${e.error}`);
    hardenDefaultSession();
    registerProtocols();
    registerIpc();
    void startEngine().catch(() => undefined); // failures are reported through engine:status
    void primeAiRoutes?.primeRoutes().catch(() => undefined);
    createWindow(undefined, !HIDDEN_START);
    void refreshLogins(true).catch(() => undefined);
    startScheduler();
    if (!testSwitch('DESK_HIDE_WINDOW')) {
      tray = new AppTray(
        brandIcon(ICON_256),
        () => {
          const c = mainCopy();
          return { open: c.open, quit: c.quit, nothingDue: c.none, due: c.due, item: (p: CalendarPost) => `${p.at.slice(11, 16)} ${p.title} → ${pfLabel(p.platform)}` };
        },
        { open: (route) => openRoute(route), quit: () => app.quit() },
      );
      tray.set(!!settings.get().openAtLogin);
    }
    if (IDENTITY.migrated) void reportMigratedProfile();
    initUpdater((u) => win?.webContents.send('update:state', u));
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
      else if (win && !win.isVisible()) openRoute(); // started hidden at login: the Dock icon shows it
    });
  });
  app.on('render-process-gone', (_e, wc, details) => {
    mainLog(`[main] renderer gone: ${details.reason} (${details.exitCode})`);
    if (details.reason !== 'clean-exit') recordProblem('renderer', details.reason, `window process gone: ${details.reason} (${details.exitCode})`);
    if (win && wc === win.webContents && details.reason !== 'clean-exit') win.reload();
  });
  app.on('child-process-gone', (_e, details) => {
    mainLog(`[main] child process gone: ${details.type} ${details.reason}`);
    if (details.reason === 'crashed' || details.reason === 'oom' || details.reason === 'launch-failed') recordProblem('main', `${details.type}:${details.reason}`, `${details.type} process ${details.reason} (${details.exitCode})`);
  });
  app.on('window-all-closed', () => {
    // a download in progress keeps the app alive (the downloads finish in the background; reopen from the dock /
    // taskbar); otherwise quit, except on macOS
    // the menu-bar icon (Open at login) keeps it running too, so scheduled posts still get their notification
    if (process.platform !== 'darwin' && !assets?.busy && !tray?.active) app.quit();
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
    recorder?.closeAll();
    scheduler?.stop();
    void engine?.stop();
  });
}
