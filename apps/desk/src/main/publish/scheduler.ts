// The publish loop's clock. Every tick (30 s while the app runs, and once at launch): reads the 发布 calendar,
// finds the posts whose time has come, and
//   - assisted platforms (the default, her standing rule): one notification per post ("Time to post: … → 小红书");
//     clicking it opens the built-in browser with the form filled - she presses Publish herself;
//   - a platform she connected an official API for (YouTube, opt-in): uploads it `leadMs` before the time with the
//     platform's own scheduled publishing (publishAt), or right away when the app was closed at the time (up to
//     `apiGraceMs` late; later than that it falls back to the notification - she decides).
// Posts that came due while the app was closed show as overdue on launch (Publish / Home banner). No electron
// import: the clock, the calendar and the notifier are injected (tests drive it with a fake clock).
import fs from 'node:fs';
import path from 'node:path';
import type { CalendarPost } from '../../shared/v04';
import { duePosts, localDate, upcomingPosts } from '../../shared/publish/postNow';

export interface ApiAttempt {
  at: string;
  status: 'uploading' | 'done' | 'failed';
  tries: number;
  detail?: string;
  url?: string;
  lastTry: number;
}

interface State {
  /** post id -> the `at` it was announced for (moving a post re-announces it) */
  notified: Record<string, string>;
  api: Record<string, ApiAttempt>;
}

export interface ApiPoster {
  /** this post goes through an official API (connected + switched on for its platform) */
  wants(p: CalendarPost): boolean;
  publish(p: CalendarPost, publishAt: Date | null): Promise<{ ok: true; url: string | null } | { ok: false; error: string }>;
}

export interface SchedulerDeps {
  load(): Promise<CalendarPost[]>;
  now(): Date;
  /** posts that just came due (each announced once) */
  notify(fresh: CalendarPost[]): void;
  /** the due list changed (the renderer's banner) */
  onChange?(due: CalendarPost[]): void;
  markPosted(p: CalendarPost, url: string | null, via: 'api'): Promise<void>;
  api?: ApiPoster;
  stateFile: string;
  log?(msg: string): void;
  /** upload this long before the time with publishAt (default 60 min) */
  leadMs?: number;
  /** after the time, still auto-post through an API for this long (default 6 h); later: ask her */
  apiGraceMs?: number;
}

const MAX_TRIES = 3;
const RETRY_MS = 10 * 60_000;

export class PublishScheduler {
  private state: State;
  private timer: ReturnType<typeof setInterval> | null = null;
  private busy = false;
  private last: CalendarPost[] = [];

  constructor(private deps: SchedulerDeps) {
    this.state = this.read();
  }

  private read(): State {
    try {
      const s = JSON.parse(fs.readFileSync(this.deps.stateFile, 'utf8')) as State;
      return { notified: s.notified ?? {}, api: s.api ?? {} };
    } catch {
      return { notified: {}, api: {} };
    }
  }

  private write() {
    try {
      fs.mkdirSync(path.dirname(this.deps.stateFile), { recursive: true });
      const tmp = this.deps.stateFile + '.tmp';
      fs.writeFileSync(tmp, JSON.stringify(this.state, null, 1));
      fs.renameSync(tmp, this.deps.stateFile);
    } catch (e) {
      this.deps.log?.(`[scheduler] could not save state: ${(e as Error).message}`);
    }
  }

  /** Due posts she still has to publish (API posts in progress or done are not hers to do). */
  get due(): CalendarPost[] {
    return this.last;
  }

  apiState(id: string): ApiAttempt | undefined {
    return this.state.api[id];
  }

  start(intervalMs = 30_000) {
    this.stop();
    void this.tick();
    this.timer = setInterval(() => void this.tick(), intervalMs);
    (this.timer as { unref?: () => void }).unref?.();
  }

  stop() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
  }

  async tick(): Promise<{ due: CalendarPost[]; fresh: CalendarPost[]; api: string[] }> {
    if (this.busy) return { due: this.last, fresh: [], api: [] };
    this.busy = true;
    try {
      let posts: CalendarPost[];
      try {
        posts = await this.deps.load();
      } catch (e) {
        this.deps.log?.(`[scheduler] calendar not readable: ${(e as Error).message}`);
        return { due: this.last, fresh: [], api: [] };
      }
      const now = this.deps.now();
      const apiRan = await this.runApi(posts, now);
      const byApi = (p: CalendarPost) => {
        const a = this.state.api[p.id];
        return a && a.at === p.at && (a.status === 'uploading' || a.status === 'done' || (a.status === 'failed' && a.tries < MAX_TRIES && this.deps.api?.wants(p)));
      };
      const due = duePosts(posts, now).filter((p) => !byApi(p));
      const fresh = due.filter((p) => this.state.notified[p.id] !== p.at);
      for (const p of fresh) this.state.notified[p.id] = p.at;
      // forget posts that are gone or posted
      const live = new Set(posts.filter((p) => p.state !== 'posted').map((p) => p.id));
      for (const id of Object.keys(this.state.notified)) if (!live.has(id)) delete this.state.notified[id];
      if (fresh.length || apiRan.length) this.write();
      if (fresh.length) this.deps.notify(fresh);
      const changed = due.map((p) => `${p.id}@${p.at}`).join() !== this.last.map((p) => `${p.id}@${p.at}`).join();
      this.last = due;
      if (changed) this.deps.onChange?.(due);
      return { due, fresh, api: apiRan };
    } finally {
      this.busy = false;
    }
  }

  private async runApi(posts: CalendarPost[], now: Date): Promise<string[]> {
    const api = this.deps.api;
    if (!api) return [];
    const lead = this.deps.leadMs ?? 60 * 60_000;
    const grace = this.deps.apiGraceMs ?? 6 * 3600_000;
    const t = now.getTime();
    const candidates = [
      ...upcomingPosts(posts, now, lead),
      ...duePosts(posts, now).filter((p) => t - localDate(p.at).getTime() <= grace),
    ].filter((p) => api.wants(p));
    const ran: string[] = [];
    for (const p of candidates) {
      const prev = this.state.api[p.id];
      if (prev && prev.at === p.at) {
        if (prev.status !== 'failed' || prev.tries >= MAX_TRIES || t - prev.lastTry < RETRY_MS) continue;
      }
      const at = localDate(p.at);
      // YouTube refuses a publishAt in the past or too close: schedule only when it is comfortably ahead
      const publishAt = at.getTime() - t > 15 * 60_000 ? at : null;
      const rec: ApiAttempt = { at: p.at, status: 'uploading', tries: (prev?.at === p.at ? prev.tries : 0) + 1, lastTry: t };
      this.state.api[p.id] = rec;
      this.write();
      ran.push(p.id);
      try {
        const r = await api.publish(p, publishAt);
        if (r.ok) {
          this.state.api[p.id] = { ...rec, status: 'done', ...(r.url ? { url: r.url } : {}) };
          await this.deps.markPosted(p, r.url, 'api');
        } else {
          this.state.api[p.id] = { ...rec, status: 'failed', detail: r.error };
          this.deps.log?.(`[scheduler] API post ${p.id} failed: ${r.error}`);
        }
      } catch (e) {
        this.state.api[p.id] = { ...rec, status: 'failed', detail: (e as Error).message };
        this.deps.log?.(`[scheduler] API post ${p.id} failed: ${(e as Error).message}`);
      }
      this.write();
    }
    return ran;
  }
}
