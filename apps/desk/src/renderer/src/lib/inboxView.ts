// The Inbox in words (pure, unit-tested): titles from the engine's codes, the one-line "what it is about", option
// labels, "−6 s", money, and the answer an item sends from her ticks and choices.
import type { InboxItem, InboxOption } from '../../../shared/v04';
import { fmtList, getLang, has, intlLocale, t, tk } from '../i18n';
import { failureReason } from '../v4/Failure';
import { emsg } from '../v4/msg';

/** The card's title from the engine's code + params (UI language); the engine's own text otherwise. */
export function inboxTitle(x: InboxItem): string {
  if (x.code === 'inbox.spend' && typeof x.params.amount === 'number') return t('inbox.spend', { amount: money(x.params.amount, String(x.params.currency ?? 'USD')) });
  if (x.source === 'feedback' && x.code && has(x.code)) return tk(x.code, { ...x.params, who: x.params.who || t('inbox.reviewer') });
  if (x.author) return authorTitle(x);
  if (x.code && has(x.code)) return tk(x.code, x.params);
  if (x.kind === 'failed') return t('inbox.failed.unknown'); // a failure code this desk has no title for yet
  if (x.kind && has(`checkpoint.${x.kind}`)) return tk(`checkpoint.${x.kind}`);
  return x.text ?? t('inbox.checkpoint');
}

/** An author checkpoint's own label in the UI language ("Keep spans" / "保留片段"), else "Write your part". */
export function authorTitle(x: Pick<InboxItem, 'labels' | 'author' | 'text'>): string {
  const l = x.labels ?? x.author?.labels ?? {};
  const own = getLang() === 'zh-CN' ? l.zh || l.en : l.en || l.zh;
  return own || x.text || t('checkpoint.author');
}

/** What to do, in the UI language: the checkpoint's help ("Write cut.body / cut.outro KEEP spans ..."). */
export function authorHelp(x: Pick<InboxItem, 'author'>): string {
  const h = x.author?.help ?? {};
  const own = getLang() === 'zh-CN' ? h.zh || h.en : h.en || h.zh;
  return own || t('inbox.author.lead');
}

/** "…/items/AIGC/promo.config.yaml": the end of a long path (the folder layout above it means nothing to her). */
export function shortPath(p: string | null | undefined, keep = 3): string {
  if (!p) return '';
  const parts = p.split(/[\\/]/).filter(Boolean);
  return parts.length > keep ? `…/${parts.slice(-keep).join('/')}` : p;
}

export function issueText(code: string, vars: Record<string, string | number> = {}): string {
  const k = `issue.${code}`;
  return has(k) ? tk(k, vars) : has('issue.qc') ? t('issue.qc') : code;
}

export function money(amount: number, currency: string): string {
  try {
    return new Intl.NumberFormat(intlLocale(), { style: 'currency', currency, maximumFractionDigits: amount < 10 ? 2 : 0 }).format(amount);
  } catch {
    return `${amount} ${currency}`;
  }
}

/** The second line of a row: what it is about, in a few words. */
export function inboxSub(x: InboxItem): string {
  if (x.failure) return failureReason(x.failure);
  if (x.author) return x.author.file ? (x.author.file.split(/[\\/]/).pop() ?? '') : '';
  if (x.kind === 'review') {
    const r = x.reasons ?? [];
    return r.length ? fmtList(r.slice(0, 2).map((y) => issueText(y.code))) : x.params.total ? t('inbox.passed', { passed: x.params.passed, total: x.params.total }) : '';
  }
  if (x.kind === 'confirm') {
    const clips = [...new Set((x.options ?? []).map((o) => o.clip_id ?? o.clip).filter(Boolean))];
    return clips.length === 1 ? clipName(x.options?.[0]) : t('inbox.inClips', { n: clips.length });
  }
  if (x.code === 'inbox.spend') return x.params.n ? t('inbox.spendSub', { n: x.params.n }) : '';
  return x.kind === 'checkpoint' && x.text ? x.text : '';
}

export function clipName(o: InboxOption | undefined | null): string {
  if (!o) return '';
  const letter = o.clip ? t('inbox.clipLetter', { c: o.clip }) : '';
  return [letter, o.clip_title].filter(Boolean).join(' · ');
}

export function optionLabel(o: InboxOption): string {
  return o.label ? emsg(o.label) : o.text;
}

/** "−6 s" (an estimate from the quoted words says so in the tooltip) */
export function secsLabel(o: Pick<InboxOption, 'secs' | 'approx'>): string {
  if (o.secs == null) return '';
  return `${o.secs < 0 ? '−' : '+'}${Math.max(1, Math.round(Math.abs(o.secs)))} s`;
}

/** The answer for an item from the creator's ticks and choices. */
export function answerOf(x: InboxItem, picked?: Set<string>, choices?: Record<string, string>) {
  const opts = x.options ?? [];
  const on = picked ?? new Set(opts.filter((o) => o.checked !== false).map((o) => o.id));
  const ch: Record<string, string> = {};
  for (const o of opts) if (o.choices?.length) ch[o.id] = choices?.[o.id] ?? o.choice ?? o.choices[0].id;
  return { approve: opts.filter((o) => on.has(o.id)).map((o) => o.id), keep: opts.filter((o) => !on.has(o.id)).map((o) => o.id), ...(Object.keys(ch).length ? { choices: ch } : {}) };
}

