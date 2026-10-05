import fs from 'node:fs';
import path from 'node:path';

export interface Settings {
  enginePath?: string;
  python?: string;
  lang: 'zh' | 'en';
  theme: 'studio-dark' | 'notebook-light';
  /** adapterId -> account labels (only labels; sessions live in Electron partitions, never exported). */
  accounts: Record<string, string[]>;
}

const DEFAULTS: Settings = { lang: 'zh', theme: 'studio-dark', accounts: {} };

export class SettingsStore {
  private file: string;
  private data: Settings;

  constructor(dir: string) {
    this.file = path.join(dir, 'settings.json');
    this.data = { ...DEFAULTS };
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (raw && typeof raw === 'object') this.data = { ...DEFAULTS, ...raw, accounts: { ...(raw.accounts ?? {}) } };
    } catch {
      /* first launch */
    }
  }

  get(): Settings {
    return structuredClone(this.data);
  }

  set(patch: Partial<Settings>): Settings {
    this.data = { ...this.data, ...patch };
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const tmp = this.file + '.tmp';
    fs.writeFileSync(tmp, JSON.stringify(this.data, null, 1));
    fs.renameSync(tmp, this.file);
    return this.get();
  }
}
