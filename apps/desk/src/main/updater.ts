// Auto-update via electron-updater from the public releases repo (electron-builder `publish` config -> app-update.yml).
// Off in development, in Microsoft Store / Mac App Store builds (the store updates the app) and when
// DESK_DISABLE_UPDATES=1. Checks 10 s after launch and every 4 hours (and when she asks in Settings), downloads in
// the background, then the window offers "Restart to update" (shared/update.ts holds the state machine). An update
// that is not installed by a restart installs itself when she quits.
//
// DESK_UPDATE_FEED (development builds only, see testHooks.devOnly): a generic electron-updater feed URL (a folder with
// latest-mac.yml / latest.yml and the files they list), written as the dev build's app-update.yml (downloads cache in
// <OS cache dir>/reelfold-dev-updater). The e2e test serves a real feed from a local server.
import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';
import electronUpdater from 'electron-updater';
import { CAPS } from '../shared/edition';
import { notesText, reduceUpdate, shouldCheck, type UpdateEvent, type UpdateStateMsg } from '../shared/update';
import { devOnly } from './testHooks';

const { autoUpdater } = electronUpdater;
const EVERY = 4 * 60 * 60 * 1000;
/** macOS: quitAndInstall waits until Squirrel.Mac has staged the update; nothing quit after this long = say so */
const INSTALL_GRACE = 60_000;

let state: UpdateStateMsg = { state: 'disabled' };
let send: (s: UpdateStateMsg) => void = () => {};
let log: (line: string) => void = () => {};
let sent = '';

function emit() {
  const j = JSON.stringify(state);
  if (j === sent) return; // download-progress fires many times per percent
  sent = j;
  send(state);
}

function apply(e: UpdateEvent) {
  const before = state.state;
  state = reduceUpdate(state, e);
  if (state.state !== before) {
    if (state.state === 'available') log(`[update] ${state.version} available (running ${state.current})`);
    else if (state.state === 'ready') log(`[update] ${state.version} downloaded: ready to install`);
    else if (state.state === 'error') log(`[update] ${state.errorStage} failed: ${state.error}`);
  }
  emit();
}

function testFeed(): string | undefined {
  const f = devOnly('DESK_UPDATE_FEED');
  return f && /^https?:\/\/[^\s]+$/.test(f) ? f : undefined;
}

export function updatesEnabled(): boolean {
  return (
    (app.isPackaged || !!testFeed()) &&
    CAPS.autoUpdate && // the Lite build (BUILD_EDITION=mas) is updated by the App Store only
    process.env.DESK_DISABLE_UPDATES !== '1' &&
    !process.windowsStore &&
    !process.mas &&
    (process.platform === 'darwin' || process.platform === 'win32')
  );
}

export function initUpdater(onState: (s: UpdateStateMsg) => void = () => {}, onLog: (line: string) => void = () => {}) {
  send = onState;
  log = onLog;
  state = { state: 'disabled', current: app.getVersion() };
  if (!updatesEnabled()) return;
  const feed = testFeed();
  if (feed) {
    // what a packaged app reads from Resources/app-update.yml, for the dev build: the same file format
    const file = path.join(app.getPath('userData'), 'dev-app-update.yml');
    fs.writeFileSync(file, `provider: generic\nurl: ${JSON.stringify(feed)}\nupdaterCacheDirName: reelfold-dev-updater\n`);
    autoUpdater.forceDevUpdateConfig = true;
    autoUpdater.updateConfigPath = file;
  }
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowPrerelease = app.getVersion().includes('-');
  // its own console logging stays out of the way; failures reach main.log through apply()
  autoUpdater.logger = { info: () => {}, warn: (m: unknown) => log(`[update] ${String(m)}`), error: () => {}, debug: () => {} };
  autoUpdater.on('checking-for-update', () => apply({ type: 'checking' }));
  autoUpdater.on('update-available', (i) => apply({ type: 'available', version: i.version, notes: notesText(i.releaseNotes), at: Date.now() }));
  autoUpdater.on('update-not-available', () => apply({ type: 'none', at: Date.now() }));
  autoUpdater.on('download-progress', (p) => apply({ type: 'progress', percent: p.percent }));
  autoUpdater.on('update-downloaded', (i) => apply({ type: 'downloaded', version: i.version, notes: notesText(i.releaseNotes) || undefined, at: Date.now() }));
  autoUpdater.on('error', (e) => apply({ type: 'error', message: String(e?.message ?? e), at: Date.now() }));
  state = { ...state, state: 'idle' };
  emit();
  setTimeout(() => void checkForUpdates(false), 10_000).unref?.();
  setInterval(() => void checkForUpdates(false), EVERY).unref();
}

/** Check now. `manual` (Settings): also when an update was offered but not downloaded yet. */
export async function checkForUpdates(manual = true): Promise<UpdateStateMsg> {
  if (!updatesEnabled() || !shouldCheck(state, manual)) return state;
  try {
    await autoUpdater.checkForUpdates();
  } catch (e) {
    // usually already reported through the 'error' event; never a silent failure either way
    if (state.state !== 'error') apply({ type: 'error', message: String((e as Error)?.message ?? e), at: Date.now() });
  }
  return state;
}

let installTimer: NodeJS.Timeout | null = null;

/** Quit, install the downloaded update and relaunch right away. */
export function installUpdate(): UpdateStateMsg {
  if (state.state !== 'ready') return state;
  log(`[update] restarting to install ${state.version}`);
  try {
    autoUpdater.quitAndInstall(false, true);
  } catch (e) {
    apply({ type: 'install-failed', message: String((e as Error)?.message ?? e) });
    return state;
  }
  if (installTimer) clearTimeout(installTimer);
  installTimer = setTimeout(() => {
    installTimer = null;
    if (state.state === 'ready') apply({ type: 'install-failed', message: `Reelfold did not restart within ${INSTALL_GRACE / 1000} s` });
  }, INSTALL_GRACE);
  installTimer.unref?.();
  return state;
}

export function updateState(): UpdateStateMsg {
  return state;
}
