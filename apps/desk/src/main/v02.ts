// v0.2 main-process features: first-run wizard state, API keys (OS keychain), persona import, text exports,
// and the post-delivery source cleanup (only through a confirmation dialog listing the exact files). Registered from index.ts through its validated `handle`.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { dialog, safeStorage, shell, type BrowserWindow, type OpenDialogOptions, type OpenDialogReturnValue } from 'electron';
import type { EngineClient } from '../shared/engineClient';
import type { IpcChannel, IpcPayload } from '../shared/ipc';
import { cleanupPathOk } from './cleanupPolicy';
import { routesFilePath } from './aiAccounts';
import { SecretStore } from './secrets';
import type { Settings, SettingsStore } from './settings';

type Handle = <C extends IpcChannel>(channel: C, fn: (p: IpcPayload<C>) => unknown) => void;

export interface V02Deps {
  userData: string;
  settings: () => SettingsStore;
  win: () => BrowserWindow | null;
  client: () => EngineClient | null;
  /** settings + resolved config, as settings:get returns it */
  settingsMsg: () => unknown;
  /** the open panel (main/index.ts pick: the Lite build also keeps a security-scoped bookmark of the pick) */
  pick?: (opts: OpenDialogOptions) => Promise<OpenDialogReturnValue>;
}

let secrets: SecretStore | null = null;

export function secretStore(userData: string): SecretStore {
  secrets ??= new SecretStore(userData, safeStorage);
  return secrets;
}

/** Extra engine environment: decrypted API keys + the imported persona. Merged into the sidecar env only. */
export function v02EngineEnv(userData: string, s: Settings): Record<string, string> {
  const env: Record<string, string> = {};
  try {
    Object.assign(env, secretStore(userData).env());
  } catch {
    /* keychain locked: run without keys */
  }
  if (s.personaPath && fs.existsSync(s.personaPath)) env.VSTUDIO_PERSONA = s.personaPath;
  // the creator's AI routes (Settings -> AI accounts & models); read by the engine on every call, so edits apply
  // without a restart. Absent file = the persona's routes.
  env.VSTUDIO_LLM_ROUTES_FILE = routesFilePath(userData);
  return env;
}

const MAX_PERSONA = 256 * 1024;

export function registerV02Ipc(handle: Handle, d: V02Deps) {
  const store = () => secretStore(d.userData);
  handle('dialog:openFiles', async (p) => {
    const w = d.win();
    // 'any': the composer takes any material (video, audio, photos, pdf / docx / pptx / md, subtitles)
    const filters = p.kind === 'any' ? [] : [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'mkv', 'webm'] }];
    const opts = { properties: ['openFile', 'multiSelections'] as ('openFile' | 'multiSelections')[], filters };
    const r = d.pick ? await d.pick(opts) : w ? await dialog.showOpenDialog(w, opts) : await dialog.showOpenDialog(opts);
    return r.canceled ? [] : r.filePaths.slice(0, p.kind === 'any' ? 200 : 20);
  });
  handle('file:saveText', async (p) => {
    const w = d.win();
    const opts = { defaultPath: path.join(os.homedir(), 'Downloads', p.defaultName) };
    const r = w ? await dialog.showSaveDialog(w, opts) : await dialog.showSaveDialog(opts);
    if (r.canceled || !r.filePath) return null;
    fs.writeFileSync(r.filePath, p.text, 'utf8');
    return r.filePath;
  });
  handle('firstRun:complete', async (p) => {
    d.settings().set({ firstRunDone: true, defaultPlatforms: p.defaultPlatforms });
    return d.settingsMsg();
  });
  handle('secrets:status', async () => store().status());
  handle('secrets:set', async (p) => store().set(p.name, p.value));
  handle('secrets:clear', async (p) => store().clear(p.name));
  handle('persona:import', async (p) => {
    const st = fs.statSync(p.path);
    if (!st.isFile() || st.size > MAX_PERSONA) throw new Error('persona must be a YAML file under 256 KB');
    const text = fs.readFileSync(p.path, 'utf8');
    if (text.includes('\0')) throw new Error('not a text file');
    const dest = path.join(d.userData, 'persona.yaml');
    fs.writeFileSync(dest, text, 'utf8');
    d.settings().set({ personaPath: dest });
    return d.settingsMsg();
  });
  handle('persona:clear', async () => {
    const s = d.settings();
    const cur = s.get().personaPath;
    if (cur && cur === path.join(d.userData, 'persona.yaml') && fs.existsSync(cur)) fs.rmSync(cur);
    s.set({ personaPath: undefined });
    return d.settingsMsg();
  });
}

export interface DueCleanup {
  batch: string;
  paths: string[];
  outside?: string[];
}

/** The exact confirmation text for a cleanup: every file, its size; outside-the-batch sources only reported. */
export function cleanupDialogText(item: DueCleanup, sizes: Record<string, number>, lang: 'zh' | 'en') {
  const mb = (n: number) => `${(n / 1e6).toFixed(1)} MB`;
  const list = item.paths.map((p) => `• ${p}  (${mb(sizes[p] ?? 0)})`).join('\n');
  const out = (item.outside ?? []).map((p) => `• ${p}`).join('\n');
  const zh = lang === 'zh';
  return {
    message: zh ? `把这 ${item.paths.length} 个原始素材移到废纸篓？` : `Move these ${item.paths.length} source file(s) to the Trash?`,
    detail:
      list +
      (out ? (zh ? `\n\n不会删除（在批次文件夹之外，是你自己的录像）：\n${out}` : `\n\nNot deleted (outside the batch folder, your own recordings):\n${out}`) : '') +
      (zh ? '\n\n可以在废纸篓里恢复。' : '\n\nThey can be restored from the Trash.'),
    buttons: zh ? ['取消', '移到废纸篓'] : ['Cancel', 'Move to Trash'],
  };
}

/** Source cleanup only through an explicit confirmation listing the exact files (never on a timer). */
export function registerCleanupIpc(handle: Handle, d: { win: () => BrowserWindow | null; client: () => EngineClient | null; lang: () => 'zh' | 'en' }) {
  handle('cleanup:confirm', async (p) => {
    const c = d.client();
    if (!c) throw new Error('engine not running');
    const item = (await c.cleanupDue()).find((x) => x.batch === p.batchId) as DueCleanup | undefined;
    const outside = item?.outside ?? [];
    if (!item || !item.paths.length) return { confirmed: false, trashed: [], failed: [], outside };
    const sizes: Record<string, number> = {};
    for (const f of item.paths) {
      try {
        sizes[f] = fs.statSync(f).size;
      } catch {
        sizes[f] = 0;
      }
    }
    const txt = cleanupDialogText(item, sizes, d.lang());
    const w = d.win();
    const opts = { type: 'warning' as const, message: txt.message, detail: txt.detail, buttons: txt.buttons, defaultId: 0, cancelId: 0, noLink: true };
    const r = w ? await dialog.showMessageBox(w, opts) : await dialog.showMessageBox(opts);
    if (r.response !== 1) return { confirmed: false, trashed: [], failed: [], outside };
    const trashed: string[] = [];
    const failed: string[] = [];
    for (const f of item.paths) {
      try {
        const st = fs.statSync(f);
        if (!cleanupPathOk(f, st.isDirectory(), os.homedir())) {
          failed.push(f);
          continue;
        }
        await shell.trashItem(f);
        trashed.push(f);
      } catch {
        failed.push(f);
      }
    }
    if (trashed.length) await c.cleanupDone(p.batchId, trashed).catch(() => undefined);
    return { confirmed: true, trashed, failed, outside };
  });
}
