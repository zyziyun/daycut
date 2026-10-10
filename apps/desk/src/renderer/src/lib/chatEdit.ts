// Card logic of the chat-first editor (pure, unit-tested): what state a change card is in (derived from the clip's
// history, so undo / redo / revert elsewhere stay in sync), how undoing an OLDER card works (selective revert, never
// "undo everything after it"), the one primary button, timeline markers, the empty-state suggestions from this
// clip's analysis, the slash menu.
import type { AskContext, CardKind, ChatDoc, ChatTurn } from '../../../shared/chatEdit';
import type { EditOp, OutputDoc } from '../../../shared/v04';
import { keptLength, previewDoc } from './outputs';

export type CardState = 'draft' | 'applied' | 'undone' | 'reverted' | 'discarded' | 'note';

/** A card's state from the transcript + the clip's history (the history wins: ⌘Z elsewhere moves the card). */
export function cardState(turn: ChatTurn, doc: Pick<ChatDoc, 'steps'>): CardState {
  if (turn.status === 'discarded') return 'discarded';
  if (turn.status === 'draft') return 'draft';
  if (turn.applied_step) {
    const s = doc.steps.find((x) => x.id === turn.applied_step);
    if (!s) return 'undone';
    return s.reverted ? 'reverted' : 'applied';
  }
  return turn.status === 'reverted' ? 'reverted' : 'note';
}

export type UndoPlan = { kind: 'undo' } | { kind: 'revert'; step: string } | { kind: 'none' };

/** Undo of an applied card: the newest step is a plain undo; an older one is reverted ON ITS OWN (the steps after
 * it stay). */
export function undoPlan(turn: ChatTurn, doc: Pick<ChatDoc, 'steps'>): UndoPlan {
  if (cardState(turn, doc) !== 'applied' || !turn.applied_step) return { kind: 'none' };
  const last = doc.steps[doc.steps.length - 1];
  return last?.id === turn.applied_step ? { kind: 'undo' } : { kind: 'revert', step: turn.applied_step };
}

/** 「回到这一步」: how many undo steps remove this step (and everything after it). */
export function undoToCount(doc: Pick<ChatDoc, 'steps'>, step: string): number {
  const i = doc.steps.findIndex((s) => s.id === step);
  return i < 0 ? 0 : doc.steps.length - i;
}

/** The newest draft card (⌘↵ applies it; its 应用 is the one primary). */
export function latestDraft(turns: ChatTurn[], doc: Pick<ChatDoc, 'steps'>, open?: { id: string } | null): string | null {
  if (open) return open.id;
  for (let i = turns.length - 1; i >= 0; i--) if (cardState(turns[i], doc) === 'draft' && turns[i].proposals.length) return turns[i].id;
  return null;
}

export type Primary = 'apply' | 'export' | 'connect' | 'none';

/** Exactly one filled button on screen. */
export function primaryAction(s: { draft: boolean; exporting: boolean; offline: boolean }): Primary {
  if (s.exporting) return 'none';
  if (s.draft) return 'apply';
  if (s.offline) return 'connect';
  return 'export';
}

/** Where an op sits on the original timeline (for markers and the context chip). */
export function opRange(op: EditOp, doc: Pick<OutputDoc, 'duration' | 'effects'>): [number, number] | null {
  switch (op.op) {
    case 'cut':
      return [op.start, op.end];
    case 'trim':
      return [op.start ?? 0, op.end ?? doc.duration];
    case 'effect_add':
      return [op.start, op.end ?? op.start + 1.2];
    case 'effect_update': {
      const e = doc.effects.find((x) => x.id === op.id);
      return e ? [op.start ?? e.start, op.end ?? e.end] : null;
    }
    case 'caption_add':
      return [op.start, op.end];
    case 'cover':
      return op.t != null ? [op.t, op.t] : null;
    default:
      return null;
  }
}

export interface Marker {
  id: string;
  a: number;
  b: number;
  tone: 'draft' | 'applied';
  turn?: string;
  kind: 'cut' | 'fx' | 'trim' | 'point';
}

/** Timeline markers: amber for draft ops (with the card they belong to), teal for what is applied. */
export function markers(doc: OutputDoc, drafts: { turn: string; ops: EditOp[] }[]): Marker[] {
  const out: Marker[] = [];
  for (const c of doc.cuts) out.push({ id: `cut${c.index}`, a: c.start, b: c.end, tone: 'applied', kind: 'cut' });
  for (const e of doc.effects) if (e.end - e.start <= doc.duration * 0.6) out.push({ id: e.id, a: e.start, b: e.end, tone: 'applied', kind: 'fx' }); // a progress bar / grade is not a place
  for (const d of drafts)
    d.ops.forEach((op, i) => {
      const r = opRange(op, doc);
      if (!r || (op.op !== 'trim' && r[1] - r[0] > doc.duration * 0.6)) return; // whole-clip things are not a place
      const kind = op.op === 'cut' ? 'cut' : op.op === 'trim' ? 'trim' : op.op.startsWith('effect') ? 'fx' : 'point';
      out.push({ id: `${d.turn}:${i}`, a: r[0], b: Math.max(r[0], r[1]), tone: 'draft', turn: d.turn, kind });
    });
  return out;
}

/** Pauses longer than `min` seconds between words (the engine / desk rules cut these). */
export function pauses(words: { t: number; te: number }[], min = 0.6): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = [];
  for (let i = 1; i < words.length; i++) if (words[i].t - words[i - 1].te > min) out.push({ start: words[i - 1].te, end: words[i].t });
  return out;
}

export type Suggestion =
  | { kind: 'pauses'; n: number; secs: number }
  | { kind: 'pop'; words: { w: string; t: number }[] }
  | { kind: 'platform'; target: '9:16' }
  | { kind: 'cover' };

/** 3-4 suggestions from THIS clip: its pauses, words worth popping, a missing 9:16 version, the cover. */
export function suggestions(doc: OutputDoc): Suggestion[] {
  const out: Suggestion[] = [];
  const ps = pauses(doc.words).filter((p) => !doc.cuts.some((c) => c.start <= p.start + 0.1 && c.end >= p.end - 0.1));
  if (ps.length && doc.caps.cut !== false) out.push({ kind: 'pauses', n: ps.length, secs: Math.round(ps.reduce((s, p) => s + p.end - p.start - 0.16, 0) * 10) / 10 });
  const pop = keyWords(doc);
  if (pop.length && doc.caps.effects !== false) out.push({ kind: 'pop', words: pop });
  const have = new Set([...doc.files.map((f) => f.aspect), ...doc.exports.map((e) => e.target)]);
  if (![...have].some((a) => a === '9:16' || /:vertical$/.test(a) && !/^xiaohongshu/.test(a)) && doc.caps.export !== false) out.push({ kind: 'platform', target: '9:16' });
  if (!doc.cover_edit && doc.caps.cover !== false) out.push({ kind: 'cover' });
  return out.slice(0, 4);
}

const CJK = /[\u4e00-\u9fff]/;
const STOP = new Set(['你在', '我在', '我觉得', '觉得', '不同', '知道', '应该', '需要', '一下', '东西', '事情', '比较', '现在', '之后', '时间', '我们', '你们', '他们', '就是', '然后', '这个', '那个', '一个', '因为', '所以', '但是', '其实', '可能', '什么', '自己', '没有', '还是', '如果', '的话', '这样', '时候', '大家']);

// function characters: a "word" that starts / ends with one is an ASR fragment, not a key word
const FUNC_HEAD = /^[的了是在有也都就和而与或这那些个一吗呢吧啊么着过很太]/;
const FUNC_TAIL = /[的了吗呢吧啊么着过们]$/;

/** Words worth popping: CJK words (2-4 characters) that are in the title first, then the most repeated ones;
 * the transcript's own words only (never invented), each once, not already popped. */
export function keyWords(doc: Pick<OutputDoc, 'words' | 'effects' | 'title' | 'post'>, n = 2): { w: string; t: number }[] {
  const used = new Set(doc.effects.map((e) => String(e.params?.text ?? '')));
  const title = `${doc.title ?? ''} ${doc.post?.title ?? ''}`;
  const freq = new Map<string, { n: number; t: number }>();
  for (const w of doc.words) {
    const s = w.w.trim();
    if (s.length < 2 || s.length > 4 || !CJK.test(s) || STOP.has(s) || used.has(s) || FUNC_HEAD.test(s) || FUNC_TAIL.test(s)) continue;
    const f = freq.get(s);
    if (f) f.n++;
    else freq.set(s, { n: 1, t: w.t });
  }
  return [...freq.entries()]
    .map(([w, f]) => ({ w, t: f.t, score: (title.includes(w) ? 10 : 0) + f.n }))
    .sort((a, b) => b.score - a.score || a.t - b.t)
    .slice(0, n)
    .sort((a, b) => a.t - b.t)
    .map(({ w, t }) => ({ w, t }));
}

export const SLASH: { kind: CardKind; en: string; zh: string }[] = [
  { kind: 'captions', en: 'captions', zh: '字幕' },
  { kind: 'effect', en: 'effect', zh: '效果' },
  { kind: 'trim', en: 'trim', zh: '裁剪' },
  { kind: 'cover', en: 'cover', zh: '封面' },
  { kind: 'export', en: 'export', zh: '导出' },
];

/** `/xx` typed in the composer -> the tools it matches (either language). */
export function slashMatches(text: string): CardKind[] {
  const m = /^\/(\S*)$/.exec(text.trim());
  if (!m) return [];
  const q = m[1].toLowerCase();
  return SLASH.filter((s) => !q || s.en.startsWith(q) || s.zh.startsWith(q)).map((s) => s.kind);
}

/** Exact slash command (`/trim`, `/裁剪`) -> its card; anything else goes to the model. */
export function slashCommand(text: string): CardKind | null {
  const m = /^\/(\S+)\s*$/.exec(text.trim());
  if (!m) return null;
  const q = m[1].toLowerCase();
  return SLASH.find((s) => s.en === q || s.zh === q)?.kind ?? null;
}

/** Which adjust card an op opens. */
export function cardFor(op: EditOp): CardKind | null {
  if (op.op === 'cut' || op.op === 'trim' || op.op === 'cut_remove') return 'trim';
  if (op.op.startsWith('effect')) return 'effect';
  if (op.op.startsWith('caption')) return 'captions';
  if (op.op === 'cover') return 'cover';
  if (op.op.startsWith('export')) return 'export';
  return null;
}

/** Length before -> after the ops (trim / cuts / speed). */
export function lengthChange(doc: OutputDoc, ops: EditOp[]): { before: number; after: number } {
  const speed = (d: number, s: number) => d / (s || 1);
  const before = speed(keptLength(doc), doc.speed);
  const v = previewDoc(doc, ops);
  const sp = [...ops].reverse().find((o) => o.op === 'speed') as { value: number } | undefined;
  return { before, after: speed(keptLength(v), sp?.value ?? doc.speed) };
}

/** Ops whose "after" the player cannot fake (cuts, trims, speed): compare needs a preview render. */
export function needsRender(ops: EditOp[]): boolean {
  return ops.some((o) => o.op === 'cut' || o.op === 'trim' || o.op === 'speed' || o.op === 'cut_remove');
}

/** The context sent with a message: the selection and / or the open effect. */
export function contextOf(sel: { a: number; b: number } | null, fx: string | null, doc: Pick<OutputDoc, 'captions'>): AskContext | null {
  const ctx: AskContext = {};
  if (sel) {
    ctx.range = [Math.round(sel.a * 1000) / 1000, Math.round(sel.b * 1000) / 1000];
    const cues = doc.captions.filter((c) => !c.removed && c.end > sel.a && c.start < sel.b).map((c) => c.id);
    if (cues.length) ctx.cues = cues.slice(0, 50);
  }
  if (fx) ctx.effect = fx;
  return ctx.range || ctx.effect ? ctx : null;
}

/** Model · cost · seconds under an AI reply. */
export function costLine(t: Pick<ChatTurn, 'provider' | 'model' | 'cost_usd' | 'seconds'>, name: (p: string) => string): string {
  const parts: string[] = [];
  if (t.provider) parts.push(t.model && t.provider !== 'rules' ? `${name(t.provider)} · ${t.model}` : name(t.provider));
  if (t.cost_usd != null) parts.push(`$${t.cost_usd.toFixed(2)}`);
  if (t.seconds != null) parts.push(`${Math.max(1, Math.round(t.seconds))} s`);
  return parts.join(' · ');
}

/** No usable model: the fallback card (and the red chip) appear. */
export function offlineFrom(r: { provider?: string | null; warnings?: { code: string }[] | null; failed?: unknown }): 'no-model' | 'llm-failed' | null {
  const codes = (r.warnings ?? []).map((w) => w.code);
  if (codes.includes('llm-failed') || codes.includes('llm-bad-json') || r.failed) return 'llm-failed';
  if (codes.includes('no-model')) return 'no-model';
  return null;
}

export type AskReason = 'reset' | 'export-remove' | 'most-of-clip';

/** Why an AI change waits for her Apply although AI edits apply at once (ux/fewer-steps): starting the clip over
 * (every edit goes), dropping a version she exports, or a cut / trim that takes more than half of what is left.
 * Everything else is applied straight away with Undo. (None of the clip edits costs money; a paid op would wait
 * here too.) */
export function askFirstReason(ops: EditOp[], doc: OutputDoc): AskReason | null {
  if (ops.some((o) => o.op === 'reset')) return 'reset';
  if (ops.some((o) => o.op === 'export_remove')) return 'export-remove';
  if (ops.some((o) => o.op === 'cut' || o.op === 'trim')) {
    const l = lengthChange(doc, ops);
    if (l.before > 0 && l.after < l.before * 0.5) return 'most-of-clip';
  }
  return null;
}

/** Changes the live player cannot draw (a whole-clip look such as skin smoothing or a grade, a zoom, a transition,
 * sound): their Before / after renders the clip once and plays that against the live view. Text overlays, captions,
 * cuts, trims and speed are shown live. */
export function needsRenderedCompare(ops: EditOp[]): boolean {
  // (theme / loudness ops come from the engine's model too; EditOp does not list them)
  return ops.some((o) => ['theme', 'loudness'].includes(o.op as string) || (o.op === 'effect_add' && typeof o.params?.text !== 'string'));
}
