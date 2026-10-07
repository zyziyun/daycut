// UI language adapter. One file per language under ./locales (en is the source of truth and the fallback); a
// locale is added by writing locales/<code>.ts (typed Record<MessageKey, string>, so a missing key is a build
// error) and registering it below. The UI language is separate from the content language (captions, post copy and
// plan summaries are shown as the engine wrote them).
import { formatMessage, type Vars } from './icu';
import { en, type MessageKey } from './locales/en';
import { fr } from './locales/fr';
import { zhCN } from './locales/zh-CN';

export type { MessageKey };
export type Lang = 'en' | 'zh-CN' | 'fr';

export const LOCALES: Record<Lang, { label: string; intl: string; messages: Record<MessageKey, string> }> = {
  en: { label: 'English', intl: 'en', messages: en },
  'zh-CN': { label: '简体中文', intl: 'zh-CN', messages: zhCN },
  fr: { label: 'Français', intl: 'fr', messages: fr },
};
export const LANGS = Object.keys(LOCALES) as Lang[];
export const DEFAULT_LANG: Lang = 'en';

let lang: Lang = DEFAULT_LANG;
/** In tests a missing key renders as ⟦key⟧ so screen checks can find it. */
let strict = false;
try {
  strict = typeof localStorage !== 'undefined' && localStorage.getItem('i18n.strict') === '1';
} catch {
  strict = false;
}

/** Settings value -> a registered locale ('zh' is the pre-v0.4 code for zh-CN; any fr-* region maps to fr). */
export function normalizeLang(l: string | null | undefined): Lang {
  if (l === 'zh' || l === 'zh-CN' || l === 'zh-Hans') return 'zh-CN';
  if (l === 'fr' || /^fr[-_]/i.test(l ?? '')) return 'fr';
  return (LANGS as string[]).includes(l ?? '') ? (l as Lang) : DEFAULT_LANG;
}

export function setLang(l: string) {
  lang = normalizeLang(l);
  if (typeof document !== 'undefined') document.documentElement.lang = LOCALES[lang].intl;
}

export function getLang(): Lang {
  return lang;
}

export function intlLocale(): string {
  return LOCALES[lang].intl;
}

export function setStrict(on: boolean) {
  strict = on;
}

function lookup(key: string): string | undefined {
  const own = (LOCALES[lang].messages as Record<string, string>)[key];
  if (own !== undefined) return own;
  return (en as Record<string, string>)[key];
}

/** Typed lookup: the key must exist in en (and therefore in every locale). */
export function t(key: MessageKey, vars?: Vars): string {
  const s = lookup(key);
  if (s === undefined) return strict ? `⟦${key}⟧` : key;
  return formatMessage(s, LOCALES[lang].intl, vars);
}

/** Dynamic keys (built from engine codes): returns the key itself when there is no message, so callers can fall
 * back to the engine's own text. */
export function tk(key: string, vars?: Vars): string {
  const s = lookup(key);
  return s === undefined ? key : formatMessage(s, LOCALES[lang].intl, vars);
}

export function has(key: string): boolean {
  return lookup(key) !== undefined;
}

// ---------------------------------------------------------------- formatting with the active locale
export function fmtNumber(n: number, opts?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(intlLocale(), opts).format(n);
}

export function fmtList(xs: string[]): string {
  return new Intl.ListFormat(intlLocale(), { style: 'short', type: 'unit' }).format(xs);
}

export function fmtMoney(usd: number): string {
  return new Intl.NumberFormat(intlLocale(), { style: 'currency', currency: 'USD', maximumFractionDigits: usd < 10 ? 2 : 0 }).format(usd);
}

/** Clip length / timecode: 1:24, 12:03, 1:02:03 (tabular numerals in CSS). */
export function fmtClock(s: number | null | undefined, frac = false): string {
  if (s == null || !Number.isFinite(s) || s < 0) return '–';
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const ss = frac ? sec.toFixed(1).padStart(4, '0') : String(Math.floor(sec)).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** Durations in words: "25 min", "约 2 小时". */
export function fmtMinutes(min: number | null | undefined): string {
  if (min == null || !Number.isFinite(min)) return '–';
  if (min < 1) return t('time.underMinute');
  if (min < 90) return t('time.minutes', { n: Math.round(min) });
  return t('time.hours', { n: Math.round((min / 60) * 10) / 10 });
}

export function fmtDate(ts: number | string | Date, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }): string {
  const d = ts instanceof Date ? ts : typeof ts === 'number' ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
  return new Intl.DateTimeFormat(intlLocale(), opts).format(d);
}

export function fmtTime(ts: number | string | Date): string {
  return fmtDate(ts, { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function fmtWeekday(d: Date): string {
  return fmtDate(d, { weekday: 'short' });
}

/** "just now", "5 min ago", "yesterday", or a date. */
export function fmtAgo(ts: number | null | undefined, now = Date.now() / 1000): string {
  if (!ts) return '–';
  const s = now - (ts > 1e12 ? ts / 1000 : ts);
  const rtf = new Intl.RelativeTimeFormat(intlLocale(), { numeric: 'auto' });
  if (s < 60) return t('time.justNow');
  if (s < 3600) return rtf.format(-Math.round(s / 60), 'minute');
  const d0 = new Date();
  d0.setHours(0, 0, 0, 0);
  const tsMs = (ts > 1e12 ? ts : ts * 1000);
  if (tsMs >= d0.getTime()) return t('time.today');
  if (tsMs >= d0.getTime() - 86400000) return rtf.format(-1, 'day');
  if (s < 7 * 86400) return rtf.format(-Math.round(s / 86400), 'day');
  return fmtDate(tsMs);
}

// ---------------------------------------------------------------- legacy helpers (pre-v0.4 screens)
const STATE_KEYS: Record<string, MessageKey> = {
  planned: 'state.planned',
  running: 'state.running',
  done: 'state.done',
  failed: 'state.failed',
  approved: 'state.approved',
  'needs-replan': 'state.needs-replan',
  packaged: 'state.packaged',
  dropped: 'state.dropped',
  'pilot-review': 'state.pilot-review',
  paused: 'state.paused',
  ran: 'state.ran',
  missing: 'state.missing',
};

export function tState(s: string): string {
  return STATE_KEYS[s] ? t(STATE_KEYS[s]) : s;
}

/** Stage rows use the same words except "done" (a finished stage is not "to review"). */
export function tStage(s: string): string {
  if (s === 'done') return t('stage.done');
  if (s === 'running' || s === 'failed' || s === 'pending' || s === 'skipped') return tk(`state.${s}`);
  return s;
}
