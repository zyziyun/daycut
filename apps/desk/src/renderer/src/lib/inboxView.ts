// The Inbox in words (pure, unit-tested): titles from the engine's codes, the one-line "what it is about", option
// labels, "−6 s", money, and the answer an item sends from her ticks and choices.
import type { DraftMsg, DraftSegment, InboxItem, InboxOption } from '../../../shared/v04';
import { fmtList, getLang, has, intlLocale, t, tk } from '../i18n';
import { failureReason } from '../v4/Failure';
import { emsg } from '../v4/msg';

/** The items that count as "needs you": not an archived project's (its own page still lists those). */
export function activeItems(items: InboxItem[]): InboxItem[] {
  return items.some((x) => x.archived) ? items.filter((x) => !x.archived) : items;
}

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

/** An author checkpoint's title in plain words: the desk's own for the recipe's step ("Check what's kept"), else the
 * checkpoint's label in the UI language, else "Check the AI's draft". */
export function authorTitle(x: Pick<InboxItem, 'labels' | 'author' | 'text'>): string {
  const a = x.author;
  const own = a?.recipe && a.checkpoint ? `draft.title.${a.recipe}.${a.checkpoint}` : '';
  if (own && has(own)) return tk(own);
  const l = x.labels ?? a?.labels ?? {};
  const lab = getLang() === 'zh-CN' ? l.zh || l.en : l.en || l.zh;
  return lab || t('draft.titleAny');
}

/** What the step asks of her, in plain words (never the engine's "write cut.body ..." help). */
export function authorHelp(x: Pick<InboxItem, 'author'>): string {
  const a = x.author;
  if (!a) return t('draft.lead.any');
  if (a.drafting) return t('draft.lead.drafting');
  if (a.state === 'missing' || a.state === 'template' || !a.review) return t('draft.lead.none');
  if (a.review.kind === 'keep-spans') return a.review.by === 'rules' ? t('draft.lead.keepRules') : t('draft.lead.keep');
  if (a.review.kind === 'package') return t('draft.lead.package');
  return t('draft.lead.any');
}

/** m:ss of a length in seconds ("9:40"), for the keep summary. */
export function mmss(s: number | null | undefined): string {
  const v = Math.max(0, Math.round(Number(s) || 0));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, '0')}`;
}

/** A draft's summary in the UI language (``code`` + ``params`` from the engine). */
export function draftSummary(m: DraftMsg | null | undefined): string {
  if (!m) return '';
  const p = (m.params ?? {}) as Record<string, unknown>;
  const vars: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(p)) {
    if (v === null || v === undefined) continue;
    if ((k === 'kept' || k === 'total') && typeof v === 'number') vars[k] = mmss(v);
    else if (Array.isArray(v)) vars[k] = k === 'at' ? v.map((x) => mmss(Number(x))).join(', ') : fmtList(v.map(String));
    else vars[k] = typeof v === 'number' || typeof v === 'string' ? v : String(v);
  }
  if (m.code === 'draft.keep' && !vars.cuts) return t('draft.keepShort', { kept: vars.kept ?? '', total: vars.total ?? '' });
  const key = m.code;
  if (has(key)) return tk(key, vars);
  return typeof vars.text === 'string' ? vars.text : '';
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
  if (x.author) return x.author.drafting ? t('draft.drafting') : x.author.review ? draftSummary(x.author.review.summary) : t('draft.lead.none');
  if (x.kind === 'needs' && x.need) return emsg(x.need);
  if (x.kind === 'review') {
    const r = x.reasons ?? [];
    return r.length ? fmtList(r.slice(0, 2).map((y) => issueText(y.code))) : x.params.total ? t('inbox.passed', { passed: x.params.passed, total: x.params.total }) : '';
  }
  if (x.kind === 'confirm') {
    const clips = [...new Set((x.options ?? []).map((o) => o.clip_id ?? o.clip).filter(Boolean))];
    return clips.length === 1 ? clipName(x.options?.[0]) : t('inbox.inClips', { n: clips.length });
  }
  if (x.code === 'inbox.spend') return x.params.n ? t('inbox.spendSub', { n: x.params.n }) : '';
  if (x.clip) return inboxClip(x);
  return x.kind === 'checkpoint' && x.text ? x.text : '';
}

/** Which clip an engine question is about: 「一次录完」, else 第 2 条 ('' when it is about the whole project). */
export function inboxClip(x: Pick<InboxItem, 'clip'>): string {
  if (!x.clip) return '';
  return x.clip.title ? t('hub.clipNamed', { title: x.clip.title }) : t('hub.clipN', { n: x.clip.n });
}

export function clipName(o: InboxOption | undefined | null): string {
  if (!o) return '';
  const letter = o.clip ? t('inbox.clipLetter', { c: o.clip }) : '';
  return [letter, o.clip_title].filter(Boolean).join(' · ');
}

export function optionLabel(o: InboxOption): string {
  // a publish option: the platform's name in the UI language and the frame shape (「小红书 · 3:4」)
  if (o.platform) return [tk(`pf.${o.platform}`), o.aspect].filter(Boolean).join(' · ');
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


/** A keep-spans review with her clicks applied: which sentences are kept (``edits``: sentence id -> keep). */
export function keptOf(segs: DraftSegment[], edits: Record<number, boolean> | null | undefined): Set<number> {
  return new Set(segs.filter((s) => (edits && s.i in edits ? edits[s.i] : s.keep)).map((s) => s.i));
}

/** Kept sentences -> the KEEP spans the engine writes into the cut (raw seconds; neighbours < 0.8 s apart merge),
 * the same rule as the engine's own draft (vstudio.project.adapters.promo._spans). */
export function keptSpans(segs: DraftSegment[], kept: Set<number>): [number, number][] {
  const out: [number, number][] = [];
  for (const s of segs) {
    if (!kept.has(s.i)) continue;
    const a = Math.max(0, s.t - 0.05);
    const b = s.te + 0.05;
    const last = out[out.length - 1];
    if (last && a - last[1] < 0.8) last[1] = Math.round(b * 100) / 100;
    else out.push([Math.round(a * 100) / 100, Math.round(b * 100) / 100]);
  }
  return out;
}

export function keptSeconds(segs: DraftSegment[], kept: Set<number>): number {
  return segs.reduce((n, s) => n + (kept.has(s.i) ? s.te - s.t : 0), 0);
}

/** Her clicks changed what the AI kept. */
export function keptChanged(segs: DraftSegment[], edits: Record<number, boolean> | null | undefined): boolean {
  return !!edits && segs.some((s) => s.i in edits && edits[s.i] !== s.keep);
}
