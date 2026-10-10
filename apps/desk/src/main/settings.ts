import fs from 'node:fs';
import path from 'node:path';
import type { AiRoutes } from '../shared/aiRoutes';
import type { ChannelPrefs } from '../shared/channels';

export interface Settings {
  enginePath?: string;
  python?: string;
  /** UI language (v0.4: 'en' default; 'zh' from older profiles reads as 'zh-CN') */
  lang: 'en' | 'zh-CN' | 'fr';
  /** brand accent: calm teal (default) or 小红书 red */
  accent?: 'teal' | 'red';
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
  /** AI accounts & models: default provider, per-task overrides, fallback lists (unset: the persona's routes) */
  aiRoutes?: AiRoutes;
  /** publishing accounts: "<adapterId>/<label>" -> display name, default post times, last seen login state */
  channels?: Record<string, ChannelPrefs>;
  /** 「我在帮别人做视频」: shows clients (filter in 全部项目, client field, delivery). Off: everything is her own. */
  agencyMode?: boolean;
  /** the clip editor's chat: AI edits wait for her Apply (default off: they apply at once, with Undo) */
  askAiEdits?: boolean;
  /** new projects from Home run on autopilot (the engine plans, decides and finishes them; default) - false: the
   * plan waits for her Start and a pilot of one comes first ("Ask me first") */
  autopilot?: boolean;
  /** Create page (创作): nav item, /api/create calls, recorder permissions. Off = the app as before. */
  createPage?: boolean;
  /** Create: local draft generation on this Mac (second flag, on top of createPage) */
  createLocalGen?: boolean;
  /** the Studio: every video in one list, one page per video (unset = shared/recIpc STUDIO_DEFAULT) */
  studio?: boolean;
  /** anonymous usage counts (main/usage.ts): 'on' only after she chose it; unset (never asked) = off */
  usagePings?: 'on' | 'off';
  /** start hidden at login, with a menu-bar icon, so scheduled posts get their "Time to post" notification */
  openAtLogin?: boolean;
  /** official posting APIs she connected: post scheduled rows of that platform through the API at their time */
  publishApi?: Partial<Record<'youtube' | 'tiktok' | 'x' | 'instagram', { auto: boolean }>>;
  /** Help: send redacted crash reports automatically (default off; only with a crash-report endpoint) */
  crashReportsAuto?: boolean;
}

const DEFAULTS: Settings = { lang: 'en', accent: 'teal', theme: 'studio-dark', accounts: {}, channels: {}, agencyMode: false, autopilot: true, createPage: true, createLocalGen: false, defaultPlatforms: ['tiktok', 'youtube-shorts'], cleanupDays: 0 };

export class SettingsStore {
  private file: string;
  private data: Settings;

  constructor(dir: string) {
    this.file = path.join(dir, 'settings.json');
    this.data = { ...DEFAULTS };
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (raw && typeof raw === 'object') this.data = { ...DEFAULTS, ...raw, accounts: { ...(raw.accounts ?? {}) }, channels: { ...(raw.channels ?? {}) } };
      if ((this.data.lang as string) === 'zh') this.data.lang = 'zh-CN'; // pre-v0.4 code
      if (/^fr([-_]|$)/.test(this.data.lang as string)) this.data.lang = 'fr';
      if (!['en', 'zh-CN', 'fr'].includes(this.data.lang)) this.data.lang = 'en';
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
