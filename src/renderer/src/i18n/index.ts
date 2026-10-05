// Chinese UI copy with English fallbacks (sentence case). t(key) -> current language, else English, else key.
import { en } from './en';
import { zh } from './zh';

export type Lang = 'zh' | 'en';
let lang: Lang = 'zh';

export function setLang(l: Lang) {
  lang = l;
  document.documentElement.lang = l === 'zh' ? 'zh-CN' : 'en';
}

export function getLang(): Lang {
  return lang;
}

export function t(key: string, vars?: Record<string, string | number>): string {
  const s = (lang === 'zh' ? zh[key] : undefined) ?? en[key] ?? key;
  return vars ? s.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? '')) : s;
}

const STATE_KEYS: Record<string, string> = {
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
  if (s === 'running' || s === 'failed' || s === 'pending' || s === 'skipped') return t(`state.${s}`);
  return s;
}
