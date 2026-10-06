// v0.2 main-process features: first-run wizard state, API keys (OS keychain), persona import, text exports,
// and the post-delivery source cleanup loop. Registered from index.ts through its validated `handle`.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { dialog, safeStorage, shell, type BrowserWindow } from 'electron';
import type { EngineClient } from '../shared/engineClient';
import type { IpcChannel, IpcPayload } from '../shared/ipc';
import { cleanupPathOk } from './cleanupPolicy';
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
  return env;
}

const MAX_PERSONA = 256 * 1024;

export function registerV02Ipc(handle: Handle, d: V02Deps) {
  const store = () => secretStore(d.userData);
  handle('dialog:openFiles', async () => {
    const w = d.win();
    const opts = { properties: ['openFile', 'multiSelections'] as ('openFile' | 'multiSelections')[], filters: [{ name: 'Video', extensions: ['mp4', 'mov', 'm4v', 'mkv', 'webm'] }] };
    const r = w ? await dialog.showOpenDialog(w, opts) : await dialog.showOpenDialog(opts);
    return r.canceled ? [] : r.filePaths.slice(0, 20);
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

/** Every hour (and shortly after start): move due sources to the Trash and tell the engine. */
export function startCleanupLoop(client: () => EngineClient | null): () => void {
  let stopped = false;
  const run = async () => {
    const c = client();
    if (!c || stopped) return;
    let due: { batch: string; paths: string[] }[];
    try {
      due = await c.cleanupDue();
    } catch {
      return;
    }
    for (const item of due) {
      const done: string[] = [];
      for (const p of item.paths) {
        try {
          const st = fs.statSync(p);
          if (!cleanupPathOk(p, st.isDirectory(), os.homedir())) continue;
          await shell.trashItem(p);
          done.push(p);
        } catch {
          /* already gone / refused: retried next round */
        }
      }
      if (done.length || !item.paths.length) await c.cleanupDone(item.batch, done).catch(() => undefined);
    }
  };
  const first = setTimeout(run, 60_000);
  const timer = setInterval(run, 3_600_000);
  first.unref?.();
  timer.unref?.();
  return () => {
    stopped = true;
    clearTimeout(first);
    clearInterval(timer);
  };
}
