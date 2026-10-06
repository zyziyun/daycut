import fs from 'node:fs';
import path from 'node:path';

export interface Settings {
  enginePath?: string;
  python?: string;
  lang: 'zh' | 'en';
  theme: 'studio-dark' | 'notebook-light';
  /** adapterId -> account labels (only labels; sessions live in Electron partitions, never exported). */
  accounts: Record<string, string[]>;
  /** v0.2 first-run wizard */
  firstRunDone?: boolean;
  defaultPlatforms?: string[];
  /** imported persona (copied into userData; passed to the engine as VSTUDIO_PERSONA) */
  personaPath?: string;
  /** days after delivery before source footage goes to the Trash (0 = never) */
  cleanupDays?: number;
  /** the old 30-day default was reset to 0 (never) once */
  cleanupMigrated?: boolean;
}

const DEFAULTS: Settings = { lang: 'zh', theme: 'studio-dark', accounts: {}, defaultPlatforms: ['xiaohongshu:full'], cleanupDays: 0 };

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
    // Safety: source recordings are never deleted unless the creator turns it on. Profiles written while the
    // default was "30 days" get "never" once; a value set after this stays.
    if (!this.data.cleanupMigrated) {
      this.data = { ...this.data, cleanupDays: 0, cleanupMigrated: true };
      try {
        if (fs.existsSync(this.file)) this.set({});
      } catch {
        /* read-only profile: the in-memory value still applies */
      }
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
