// Opt-in, anonymous usage counts (Settings › General › Privacy, and the first-run choice). OFF until the creator
// turns it on; off = nothing is queued or sent, ever. What one event holds is exactly UsageEvent below (docs page
// "Privacy: what Reelfold sends", apps/docs/src/content/docs/concepts/usage-counts.md; the server's schema is
// apps/telemetry/src/schema.ts): a random install id made on this computer (resettable), app version, OS + arch,
// the app's UI language, the event name, its day (no time), and a few small integers. Never file names, paths,
// text, transcripts, prompts, keys or anything about the footage.
//
// Transport: fire-and-forget HTTPS POST from the main process with a timeout; events wait in <userData>/usage.json
// while offline and go with the next one; nothing ever blocks the UI. Development builds, tests and CI send nothing
// unless REELFOLD_USAGE=1 (usageAllowedByEnv).
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export const USAGE_EVENTS = ['app_open', 'first_batch_done', 'batch_done', 'export_done', 'publish_package'] as const;
export type UsageEventName = (typeof USAGE_EVENTS)[number];
export const USAGE_NUMBERS = { app_open: [], first_batch_done: [], batch_done: ['clips', 'formats', 'minutes_in'], export_done: ['count'], publish_package: ['platform_count'] } as const;
export type UsageNumbers = Partial<Record<'clips' | 'formats' | 'minutes_in' | 'count' | 'platform_count', number>>;

export interface UsageEvent {
  id: string;
  v: string;
  os: 'darwin' | 'win32' | 'linux';
  arch: 'arm64' | 'x64' | 'ia32' | 'arm';
  locale: 'en' | 'zh-CN' | 'fr' | 'es';
  ev: UsageEventName;
  day: string;
  n?: UsageNumbers;
}

export const USAGE_BASE = 'https://t.reelfold.com/api/v1';
export const USAGE_DOCS = 'https://reelfold.com/docs/concepts/usage-counts/';
/** queued events older than this are dropped (the server takes 14 days) */
const MAX_QUEUE_AGE_DAYS = 13;
const MAX_QUEUE = 200;
const PER_REQUEST = 50;

/**
 * May this build send at all? Only installed (packaged) builds, outside tests and CI. REELFOLD_USAGE=1 turns it on
 * anywhere (and is the only way in a dev build or a test); REELFOLD_USAGE=0 turns it off everywhere. The creator's
 * own choice (consent) applies on top of this.
 */
export function usageAllowedByEnv(env: NodeJS.ProcessEnv, packaged: boolean): boolean {
  const flag = (env.REELFOLD_USAGE ?? '').trim();
  if (flag === '0') return false;
  if (flag === '1') return true;
  if (!packaged) return false;
  if (env.CI || env.GITHUB_ACTIONS || env.VITEST || env.NODE_ENV === 'test' || env.DESK_USER_DATA || env.DESK_HIDE_WINDOW === '1' || env.DESK_ENGINE_MOCK === '1') return false;
  return true;
}

const clampInt = (v: unknown, max: number) => (typeof v === 'number' && Number.isFinite(v) ? Math.max(0, Math.min(max, Math.round(v))) : undefined);
const osOf = (p: string): UsageEvent['os'] => (p === 'win32' ? 'win32' : p === 'linux' ? 'linux' : 'darwin');
const archOf = (a: string): UsageEvent['arch'] => (a === 'x64' || a === 'ia32' || a === 'arm' ? a : 'arm64');
const localeOf = (l: string): UsageEvent['locale'] => (l === 'zh-CN' || l === 'fr' || l === 'es' ? l : 'en');
const VERSION = /^\d{1,3}\.\d{1,3}\.\d{1,4}(-[0-9A-Za-z.]{1,20})?$/;

export function utcDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** One event, exactly the documented fields (numbers only those of that event, rounded, capped). */
export function buildEvent(f: { id: string; version: string; platform: string; arch: string; lang: string; ev: UsageEventName; now: Date; n?: UsageNumbers }): UsageEvent {
  const e: UsageEvent = {
    id: f.id,
    v: VERSION.test(f.version) ? f.version : '0.0.0',
    os: osOf(f.platform),
    arch: archOf(f.arch),
    locale: localeOf(f.lang),
    ev: f.ev,
    day: utcDay(f.now),
  };
  const keys = USAGE_NUMBERS[f.ev] as readonly (keyof UsageNumbers)[];
  if (f.n && keys.length) {
    const n: UsageNumbers = {};
    for (const k of keys) {
      const v = clampInt(f.n[k], k === 'formats' || k === 'platform_count' ? 50 : 10_000);
      if (v !== undefined) n[k] = v;
    }
    if (Object.keys(n).length) e.n = n;
  }
  return e;
}

interface State {
  id?: string;
  lastOpenDay?: string;
  firstBatchSent?: boolean;
  queue: UsageEvent[];
  lastSentDay?: string;
}

export interface UsageDeps {
  /** <userData> */
  dir: string;
  /** the creator's choice: true only when she turned sharing on */
  consent: () => boolean;
  /** usageAllowedByEnv(process.env, app.isPackaged) */
  allowed: boolean;
  version: string;
  platform: string;
  arch: string;
  lang: () => string;
  /** the engine is the demo (mock) engine: batches there are not her footage, never counted */
  demo?: () => boolean;
  base?: string;
  fetch?: typeof fetch;
  now?: () => Date;
  timeoutMs?: number;
  log?: (s: string) => void;
}

export interface UsageStatus {
  /** sharing is on (her choice) */
  on: boolean;
  /** this build may send (installed app; off in dev / tests / CI) */
  allowed: boolean;
  /** the random install id (only exists once sharing was turned on) */
  installId: string | null;
  queued: number;
  lastSentDay: string | null;
  docs: string;
}

export class UsageReporter {
  private file: string;
  private st: State;
  private inflight: Promise<void> | null = null;

  constructor(private d: UsageDeps) {
    this.file = path.join(d.dir, 'usage.json');
    this.st = { queue: [] };
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8')) as Partial<State>;
      this.st = {
        id: typeof raw.id === 'string' && /^[0-9a-f-]{36}$/.test(raw.id) ? raw.id : undefined,
        lastOpenDay: typeof raw.lastOpenDay === 'string' ? raw.lastOpenDay : undefined,
        firstBatchSent: raw.firstBatchSent === true,
        lastSentDay: typeof raw.lastSentDay === 'string' ? raw.lastSentDay : undefined,
        queue: Array.isArray(raw.queue) ? raw.queue.slice(-MAX_QUEUE) : [],
      };
    } catch {
      /* no file yet */
    }
  }

  private now() {
    return this.d.now?.() ?? new Date();
  }

  private save() {
    try {
      fs.mkdirSync(path.dirname(this.file), { recursive: true });
      const tmp = this.file + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(this.st));
      fs.renameSync(tmp, this.file);
    } catch {
      /* read-only profile: in memory only */
    }
  }

  /** sharing on AND this build may send */
  enabled(): boolean {
    return this.d.allowed && this.d.consent();
  }

  status(): UsageStatus {
    return { on: this.d.consent(), allowed: this.d.allowed, installId: this.st.id ?? null, queued: this.st.queue.length, lastSentDay: this.st.lastSentDay ?? null, docs: USAGE_DOCS };
  }

  private ensureId(): string {
    if (!this.st.id) {
      this.st.id = crypto.randomUUID();
      this.save();
    }
    return this.st.id;
  }

  /** Record one event. Does nothing at all while sharing is off. Never throws, never waits for the network. */
  track(ev: UsageEventName, n?: UsageNumbers): void {
    try {
      if (!this.enabled()) return;
      if ((ev === 'batch_done' || ev === 'first_batch_done') && this.d.demo?.()) return;
      const now = this.now();
      const day = utcDay(now);
      if (ev === 'app_open') {
        if (this.st.lastOpenDay === day) return;
        this.st.lastOpenDay = day;
      }
      const id = this.ensureId();
      const mk = (name: UsageEventName, nums?: UsageNumbers) => buildEvent({ id, version: this.d.version, platform: this.d.platform, arch: this.d.arch, lang: this.d.lang(), ev: name, now, n: nums });
      if (ev === 'batch_done' && !this.st.firstBatchSent) {
        this.st.firstBatchSent = true;
        this.st.queue.push(mk('first_batch_done'));
      }
      if (ev !== 'first_batch_done') this.st.queue.push(mk(ev, n));
      this.st.queue = this.st.queue.slice(-MAX_QUEUE);
      this.save();
      void this.flush();
    } catch (e) {
      this.d.log?.(`[usage] ${(e as Error).message}`);
    }
  }

  /** Send what is queued (also called at start-up and when sharing is turned on). */
  flush(): Promise<void> {
    if (this.inflight) return this.inflight;
    if (!this.enabled() || !this.st.queue.length) return Promise.resolve();
    this.inflight = this.send().finally(() => {
      this.inflight = null;
    });
    return this.inflight;
  }

  private async send() {
    const oldest = utcDay(new Date(this.now().getTime() - MAX_QUEUE_AGE_DAYS * 86400_000));
    this.st.queue = this.st.queue.filter((e) => e.day >= oldest && e.id === this.st.id);
    while (this.enabled() && this.st.queue.length) {
      const chunk = this.st.queue.slice(0, PER_REQUEST);
      let status = 0;
      try {
        const res = await (this.d.fetch ?? fetch)(`${this.d.base ?? USAGE_BASE}/ping`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ events: chunk }),
          signal: AbortSignal.timeout(this.d.timeoutMs ?? 8000),
        });
        status = res.status;
      } catch {
        // offline / timeout: status stays 0, the queue is kept for next time
      }
      // 2xx: sent. 400 / 413: the server will never take these (dropped, not retried). Else: try again later.
      if ((status >= 200 && status < 300) || status === 400 || status === 413) {
        this.st.queue = this.st.queue.slice(chunk.length);
        if (status < 300) this.st.lastSentDay = utcDay(this.now());
        this.save();
      } else {
        this.save();
        return;
      }
    }
  }

  /** Sharing was turned on: count today's open. Turned off: the queue is emptied (nothing left to send). */
  consentChanged(on: boolean) {
    if (on) this.track('app_open');
    else {
      this.st.queue = [];
      this.save();
    }
  }

  /** A new random id; what is queued is dropped; first-batch is counted again for the new id. */
  resetId(): UsageStatus {
    this.st = { queue: [], id: this.st.id ? crypto.randomUUID() : undefined };
    this.save();
    return this.status();
  }

  /** "Delete my usage data": the server deletes every row of this install id; then the id is replaced. */
  async deleteData(): Promise<{ ok: boolean; deleted?: number; error?: string; status: UsageStatus }> {
    const id = this.st.id;
    this.st.queue = [];
    this.save();
    if (!id) return { ok: true, deleted: 0, status: this.status() };
    try {
      const res = await (this.d.fetch ?? fetch)(`${this.d.base ?? USAGE_BASE}/installs/${id}`, { method: 'DELETE', signal: AbortSignal.timeout(this.d.timeoutMs ?? 8000) });
      if (!res.ok) return { ok: false, error: `HTTP ${res.status}`, status: this.status() };
      const body = (await res.json().catch(() => ({}))) as { deleted?: number };
      this.resetId();
      return { ok: true, deleted: Number(body.deleted ?? 0), status: this.status() };
    } catch (e) {
      return { ok: false, error: (e as Error).name === 'TimeoutError' ? 'timeout' : 'offline', status: this.status() };
    }
  }
}
