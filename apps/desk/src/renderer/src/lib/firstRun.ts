// First ten minutes, in words and numbers (pure, unit-tested): how far the one-time downloads are and how long they
// still take, the default platforms for her UI language, the plan sentence when no AI planned it, and the sample
// project's name.
import type { AssetsStatusMsg } from '../../../shared/assets';
import type { IntakePlan } from '../../../shared/v04';
import type { EngineMsg } from '../../../shared/v04';
import { fmtList, t, tk } from '../i18n';
import { emsg } from '../v4/msg';
import { FIRST_PLATFORMS, OLD_FACTORY_PLATFORMS } from '../../../shared/platforms';

export interface DownloadSummary {
  /** nothing to download (installed, or not the bundled runtime) */
  state: 'done' | 'downloading' | 'waiting' | 'failed';
  done: number;
  total: number;
  /** 0..1 */
  pct: number;
  error?: string;
  /** ids of the required groups still missing (for a retry) */
  missing: string[];
}

/** The required downloads as one bar: installed groups count in full, the running one by its bytes so far. */
export function downloadSummary(s: Pick<AssetsStatusMsg, 'groups' | 'busy'> | null | undefined): DownloadSummary {
  const req = (s?.groups ?? []).filter((g) => g.required);
  const total = req.reduce((a, g) => a + g.bytes, 0);
  const done = req.reduce((a, g) => a + (g.installed ? g.bytes : g.progress ? Math.min(g.bytes, g.progress.received) : 0), 0);
  const missing = req.filter((g) => !g.installed).map((g) => g.id);
  const error = req.find((g) => !g.installed && g.error)?.error;
  const active = req.some((g) => !g.installed && (g.progress || g.queued));
  const state: DownloadSummary['state'] = !missing.length ? 'done' : active ? 'downloading' : error ? 'failed' : 'waiting';
  return { state, done, total, pct: total ? done / total : 1, error, missing };
}

/** Bytes per second over the last samples ([ms, bytes] pairs, oldest first); null until there is a trend. */
export function speedOf(samples: [number, number][]): number | null {
  if (samples.length < 2) return null;
  const [t0, b0] = samples[0];
  const [t1, b1] = samples[samples.length - 1];
  if (t1 - t0 < 1500 || b1 <= b0) return null;
  return ((b1 - b0) / (t1 - t0)) * 1000;
}

/** " · about 3 min left" / " · less than a minute left" / '' (no estimate yet). */
export function etaText(remaining: number, bytesPerSec: number | null): string {
  if (!bytesPerSec || remaining <= 0) return '';
  const s = remaining / bytesPerSec;
  return s < 60 ? t('dl.etaSoon') : t('dl.eta', { min: Math.ceil(s / 60) });
}

export function fmtBytes(n: number): string {
  return n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n <= 0 ? '0 MB' : `${Math.max(1, Math.round(n / 1e6))} MB`;
}

const same = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** Default platforms for a new profile: TikTok + YouTube Shorts (international first, everywhere), and for a Chinese UI
 * Xiaohongshu after them. A choice she already made is kept. */
export function defaultPlatformsFor(lang: string, current?: string[] | null): string[] {
  const untouched = !current?.length || same(current, OLD_FACTORY_PLATFORMS) || same(current, FIRST_PLATFORMS);
  if (!untouched) return current!;
  return lang === 'zh-CN' ? [...FIRST_PLATFORMS, 'xiaohongshu:full'] : [...FIRST_PLATFORMS];
}

const base = (p: string) => p.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? p;

/** The plan in one sentence of the UI language, from its structure (used when no AI planned it: the engine's own
 * summary is a Chinese template). */
export function planSentence(plan: IntakePlan, platformName: (id: string) => string): string {
  const one = (p: IntakePlan['projects'][number]) => {
    const pr = p.params ?? {};
    const n = p.items?.count ?? p.items?.rows?.length ?? 1;
    const label = (p as { recipe_info?: EngineMsg }).recipe_info;
    const what = p.recipe === 'talkinghead' && n <= 1 ? t('plan.sum.talkinghead') : `${label ? emsg(label) : p.recipe_label ?? p.recipe} · ${t('plan.sum.clips', { n })}`;
    const settings: string[] = [];
    const cleanup = pr.cleanup_profile as string | undefined;
    if (cleanup && cleanup !== 'off') settings.push(tk(`plan.sum.cleanup.${cleanup}`));
    if (typeof pr.speed === 'number' && pr.speed !== 1) settings.push(t('plan.sum.speed', { v: pr.speed }));
    if (pr.captions !== false) settings.push(t('plan.sum.captions'));
    const plats = [...new Set((pr.platforms ?? []).map(platformName))];
    if (plats.length) settings.push(t('plan.sum.for', { platforms: fmtList(plats) }));
    const srcs = plan.materials.map((m) => m.name || base(m.path)).slice(0, 2);
    return { what, src: srcs.length ? fmtList(srcs) : '—', settings: fmtList(settings) };
  };
  const ps = plan.projects ?? [];
  if (ps.length === 1) {
    const x = one(ps[0]);
    return `${t('plan.sumOne', x)} ${t('plan.sum.review')}.`;
  }
  return t('plan.sumMany', { n: ps.length, list: ps.map((p) => one(p).what).join('; ') });
}

/** The sample's plan, with every project named as the sample (so the project list says what it is). */
export function nameAsSample(plan: IntakePlan, name: string): IntakePlan {
  return { ...plan, projects: plan.projects.map((p, i) => ({ ...p, name: plan.projects.length > 1 ? `${name} ${i + 1}` : name })) };
}
