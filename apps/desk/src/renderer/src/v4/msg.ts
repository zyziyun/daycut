// Engine messages ({code, params, message, message_zh}) in the UI language: our own words when we know the code,
// the engine's text in the matching language otherwise.
import type { EffectDef, EngineMsg } from '../../../shared/v04';
import { EngineError } from '../../../shared/engineClient';
import { fmtClock, getLang, has, tk } from '../i18n';

const effectLabels = new Map<string, { en: string; zh: string }>();

export function setEffectLabels(defs: EffectDef[]) {
  for (const d of defs) effectLabels.set(d.id, d.label);
}

export function effectLabel(id: string, label?: { en: string; zh: string } | string | null): string {
  const l = (typeof label === 'object' && label) || effectLabels.get(id);
  if (l) return getLang() === 'zh-CN' ? l.zh || l.en : l.en || l.zh;
  return typeof label === 'string' ? label : id;
}

const TIME_KEYS = new Set(['start', 'end', 't', 'at']);

export function emsg(m: EngineMsg | string | null | undefined): string {
  if (!m) return '';
  if (typeof m === 'string') return m;
  const key = `em.${m.code}`;
  if (has(key)) {
    const vars: Record<string, string | number> = {};
    for (const [k, v] of Object.entries(m.params ?? {})) {
      if (v === null || v === undefined) continue;
      if (TIME_KEYS.has(k) && typeof v === 'number') vars[k] = fmtClock(v, true);
      else if (k === 'effect' && typeof v === 'string') vars[k] = effectLabel(v);
      else vars[k] = typeof v === 'boolean' ? String(v) : v;
    }
    const s = tk(key, vars);
    if (!/\{\w+\}/.test(s)) return s;
  }
  return (getLang() === 'zh-CN' ? m.message_zh || m.message : m.message || m.message_zh) || m.code;
}

export function errText(e: unknown): string {
  if (e instanceof EngineError && e.code) return emsg({ code: e.code, params: e.params as EngineMsg['params'], message: e.message, message_zh: e.messageZh });
  return e instanceof Error ? e.message : String(e);
}

/** An effect parameter the UI has no label for ("music_lufs"): readable words instead of the raw snake_case id. */
export function humanizeParam(key: string): string {
  const s = key.replace(/[_-]+/g, ' ').trim();
  return s ? s[0].toUpperCase() + s.slice(1) : key;
}
