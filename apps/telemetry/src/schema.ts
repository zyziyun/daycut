// The ONLY shape the usage endpoint accepts. Anything else in a request is dropped: unknown keys are never read or
// stored, an event with a bad or missing field is dropped whole. Keep in sync with apps/desk/src/main/usage.ts and
// the docs page apps/docs/src/content/docs/concepts/usage-counts.md.

export const EVENTS = ['app_open', 'first_batch_done', 'batch_done', 'export_done', 'publish_package'] as const;
export type EventName = (typeof EVENTS)[number];

/** the small integers each event may carry */
export const EVENT_PROPS: Record<EventName, readonly NumField[]> = {
  app_open: [],
  first_batch_done: [],
  batch_done: ['clips', 'formats', 'minutes_in'],
  export_done: ['count'],
  publish_package: ['platform_count'],
};
export const NUM_FIELDS = ['clips', 'formats', 'minutes_in', 'count', 'platform_count'] as const;
export type NumField = (typeof NUM_FIELDS)[number];
/** caps: a batch of 10 000 clips or a 10 000-minute recording is not a real event */
const NUM_MAX: Record<NumField, number> = { clips: 10_000, formats: 50, minutes_in: 10_000, count: 10_000, platform_count: 50 };

export const OSES = ['darwin', 'win32', 'linux'] as const;
export const ARCHES = ['arm64', 'x64', 'ia32', 'arm'] as const;
export const LOCALES = ['en', 'zh-CN', 'fr', 'es'] as const;

export interface CleanEvent {
  install_id: string;
  day: string;
  event: EventName;
  version: string;
  os: (typeof OSES)[number];
  arch: (typeof ARCHES)[number];
  locale: (typeof LOCALES)[number];
  clips: number | null;
  formats: number | null;
  minutes_in: number | null;
  count: number | null;
  platform_count: number | null;
}

export const MAX_BODY_BYTES = 16 * 1024;
export const MAX_EVENTS_PER_REQUEST = 50;
/** events are queued on the computer while offline: accept days up to this far back (and one day ahead: clocks) */
export const MAX_AGE_DAYS = 14;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const VERSION = /^\d{1,3}\.\d{1,3}\.\d{1,4}(-[0-9A-Za-z.]{1,20})?$/;
const DAY = /^\d{4}-\d{2}-\d{2}$/;

export const isInstallId = (s: unknown): s is string => typeof s === 'string' && UUID.test(s);

export function utcDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return utcDay(d);
}

const oneOf = <T extends string>(list: readonly T[], v: unknown): v is T => typeof v === 'string' && (list as readonly string[]).includes(v);

/** One event as sent by the app -> a clean row, or null (dropped). `today` is the server's UTC day. */
export function cleanEvent(raw: unknown, today: string): CleanEvent | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;
  if (!isInstallId(r.id)) return null;
  if (!oneOf(EVENTS, r.ev)) return null;
  if (typeof r.v !== 'string' || !VERSION.test(r.v)) return null;
  if (!oneOf(OSES, r.os) || !oneOf(ARCHES, r.arch) || !oneOf(LOCALES, r.locale)) return null;
  if (typeof r.day !== 'string' || !DAY.test(r.day) || Number.isNaN(Date.parse(`${r.day}T00:00:00Z`))) return null;
  if (r.day < addDays(today, -MAX_AGE_DAYS) || r.day > addDays(today, 1)) return null;
  const out: CleanEvent = {
    install_id: r.id,
    day: r.day,
    event: r.ev,
    version: r.v,
    os: r.os,
    arch: r.arch,
    locale: r.locale,
    clips: null,
    formats: null,
    minutes_in: null,
    count: null,
    platform_count: null,
  };
  const n = r.n;
  if (n !== undefined) {
    if (!n || typeof n !== 'object' || Array.isArray(n)) return null;
    const allowed = EVENT_PROPS[out.event];
    for (const k of allowed) {
      const v = (n as Record<string, unknown>)[k];
      if (v === undefined) continue;
      if (typeof v !== 'number' || !Number.isInteger(v) || v < 0 || v > NUM_MAX[k]) return null;
      out[k] = v;
    }
    // keys that are not this event's numbers are simply not read
  }
  return out;
}

/** The request body: { events: [...] } (or one bare event). -> clean rows + how many were dropped. */
export function cleanBody(body: unknown, today: string): { rows: CleanEvent[]; dropped: number } {
  const list = body && typeof body === 'object' && Array.isArray((body as { events?: unknown }).events) ? (body as { events: unknown[] }).events : [body];
  const rows: CleanEvent[] = [];
  let dropped = 0;
  for (const e of list.slice(0, MAX_EVENTS_PER_REQUEST)) {
    const c = cleanEvent(e, today);
    if (c) rows.push(c);
    else dropped++;
  }
  dropped += Math.max(0, list.length - MAX_EVENTS_PER_REQUEST);
  return { rows, dropped };
}
