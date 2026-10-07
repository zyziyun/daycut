// Auto-update via electron-updater from the public releases repo (electron-builder `publish` config -> app-update.yml).
// Off in development, in Microsoft Store / Mac App Store builds (the store updates the app) and when
// DESK_DISABLE_UPDATES=1. Downloads in the background; the UI offers "restart to update" once it is ready.
import { app } from 'electron';
import electronUpdater from 'electron-updater';
import type { UpdateStateMsg } from '../shared/deskApi';

const { autoUpdater } = electronUpdater;
const SIX_HOURS = 6 * 60 * 60 * 1000;

let state: UpdateStateMsg = { state: 'disabled' };
let send: (s: UpdateStateMsg) => void = () => {};

function set(s: UpdateStateMsg) {
  state = s;
  send(s);
}

export function updatesEnabled(): boolean {
  return (
    app.isPackaged &&
    process.env.DESK_DISABLE_UPDATES !== '1' &&
    !process.windowsStore &&
    !process.mas &&
    (process.platform === 'darwin' || process.platform === 'win32')
  );
}

export function initUpdater(onState: (s: UpdateStateMsg) => void = () => {}) {
  send = onState;
  if (!updatesEnabled()) return;
  autoUpdater.autoDownload = true;
  autoUpdater.autoInstallOnAppQuit = true;
  autoUpdater.allowPrerelease = app.getVersion().includes('-');
  autoUpdater.on('checking-for-update', () => set({ state: 'checking' }));
  autoUpdater.on('update-available', (i) => set({ state: 'available', version: i.version }));
  autoUpdater.on('update-not-available', () => set({ state: 'none' }));
  autoUpdater.on('download-progress', (p) => set({ state: 'downloading', version: state.version, percent: Math.round(p.percent) }));
  autoUpdater.on('update-downloaded', (i) => set({ state: 'ready', version: i.version }));
  autoUpdater.on('error', (e) => set({ state: 'error', error: String(e?.message ?? e).split('\n')[0] }));
  set({ state: 'idle' });
  const check = () => autoUpdater.checkForUpdates().catch(() => {});
  setTimeout(check, 10_000);
  setInterval(check, SIX_HOURS).unref();
}

export async function checkForUpdates(): Promise<UpdateStateMsg> {
  if (!updatesEnabled()) return state;
  await autoUpdater.checkForUpdates().catch(() => {});
  return state;
}

export function installUpdate() {
  if (state.state === 'ready') autoUpdater.quitAndInstall();
}

export function updateState(): UpdateStateMsg {
  return state;
}
