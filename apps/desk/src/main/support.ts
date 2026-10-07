// Feedback + problem reports (main side): the problem log, what crashes / exits are recorded, the Help menu item,
// and the support:* IPC. See shared/support.ts for what a report contains and where it opens.
import os from 'node:os';
import path from 'node:path';
import { app, type BrowserWindow } from 'electron';
import type { IpcChannel, IpcPayload } from '../shared/ipc';
import type { SupportEnv } from '../shared/support';
import { crashSenderAvailable, ProblemLog } from './problems';
import type { SettingsStore } from './settings';

type Handle = <C extends IpcChannel>(channel: C, fn: (p: IpcPayload<C>) => unknown) => void;

export interface SupportDeps {
  settings: () => SettingsStore;
  win: () => BrowserWindow | null;
  engineMode: () => string | null;
}

let log: ProblemLog | null = null;
let deps: SupportDeps | null = null;

export function supportEnv(): SupportEnv {
  const s = deps?.settings().get();
  return {
    app: app.getVersion(),
    electron: process.versions.electron ?? '-',
    chrome: process.versions.chrome ?? '-',
    node: process.versions.node,
    os: `${process.platform === 'darwin' ? 'macOS' : process.platform === 'win32' ? 'Windows' : process.platform} ${process.platform === 'darwin' ? (process as NodeJS.Process & { getSystemVersion?: () => string }).getSystemVersion?.() ?? os.release() : os.release()}`,
    arch: process.arch,
    packaged: app.isPackaged,
    lang: s?.lang ?? 'en',
    engine: deps?.engineMode() ?? null,
    home: os.homedir(),
    autoAvailable: crashSenderAvailable(),
    autoSend: Boolean(s?.crashReportsAuto),
  };
}

/** The problem log, created on first use (before app ready: under userData/logs, like main.log). */
export function problems(): ProblemLog {
  if (!log) {
    log = new ProblemLog(
      path.join(app.getPath('userData'), 'logs'),
      (p) => deps?.win()?.webContents.send('support:problem', p),
      () => (deps ? supportEnv() : null),
      () => Boolean(deps?.settings().get().crashReportsAuto),
    );
  }
  return log;
}

/** Record a problem; never throws (used from crash handlers). */
export function recordProblem(kind: 'main' | 'renderer' | 'sidecar' | 'job', code: string, message: string, stack?: string) {
  try {
    problems().record(kind, code, message, stack);
  } catch {
    /* never throw from a crash handler */
  }
}

/** Help › Send feedback… and Settings › Help: the renderer opens its feedback sheet. */
export function openFeedback(win: BrowserWindow | null) {
  win?.webContents.send('support:open', { what: 'feedback' });
}

export function registerSupportIpc(handle: Handle, d: SupportDeps) {
  deps = d;
  handle('support:env', async () => supportEnv());
  handle('support:problems', async () => ({ items: problems().list(), recent: problems().recent() }));
  handle('support:dismiss', async (p) => problems().dismiss(p.id));
  handle('support:report', async (p) => void problems().record(p.kind, p.code, p.message, p.stack));
  handle('support:setAuto', async (p) => {
    d.settings().set({ crashReportsAuto: p.on });
    return supportEnv();
  });
}
