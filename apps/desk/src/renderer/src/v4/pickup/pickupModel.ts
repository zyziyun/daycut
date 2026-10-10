// Pickups (补录) in the clip editor: the plain logic - where a pickup goes (from the transcript selection), which
// words are a pickup's, and what the recording's automatic first pass cut.
import type { OutputDoc, Pickup, Word } from '../../../../shared/v04';
import { joinWords } from '../../lib/transcript';

export type AutoKind = 'retake' | 'filler' | 'pause';

/** Where she records: in place of the selected words, or right after them. */
export interface Spot {
  kind: 'replace' | 'insert';
  /** first / last selected word */
  a: number;
  b: number;
  /** the selected words (the teleprompter shows them when re-recording) */
  text: string;
}

export function spotOf(words: Word[], sel: { a: number; b: number }, kind: Spot['kind']): Spot {
  const a = Math.max(0, Math.min(sel.a, sel.b));
  const b = Math.min(words.length - 1, Math.max(sel.a, sel.b));
  return { kind, a, b, text: joinWords(words, a, b) };
}

/** The request body for POST .../pickup: replace [a, b], or insert before the word after b. */
export function spotBody(s: Spot): { replace: [number, number] } | { at_word: number } {
  return s.kind === 'replace' ? { replace: [s.a, s.b] } : { at_word: s.b + 1 };
}

/** word index -> pickup number (1, 2, ... in timeline order) for the words a pickup said. */
export function pickupWords(words: Word[], pickups: Pickup[] | undefined): Map<number, number> {
  const out = new Map<number, number>();
  const ps = [...(pickups ?? [])].sort((x, y) => x.start - y.start);
  ps.forEach((p, k) => {
    words.forEach((w, i) => {
      const mid = (w.t + w.te) / 2;
      if (mid >= p.start - 1e-3 && mid <= p.end + 1e-3) out.set(i, k + 1);
    });
  });
  return out;
}

/** The cuts of a recording's automatic first pass still in the clip, by kind (cut indexes), or null when it had none
 * (or nothing of it is left). */
export function autoKinds(doc: Pick<OutputDoc, 'steps' | 'cuts'>): Record<AutoKind, number[]> | null {
  if (!doc.steps.some((s) => s.by === 'auto' && !s.reverted)) return null;
  const out: Record<AutoKind, number[]> = { retake: [], filler: [], pause: [] };
  for (const c of doc.cuts) if (c.why === 'retake' || c.why === 'filler' || c.why === 'pause') out[c.why].push(c.index);
  return out.retake.length + out.filler.length + out.pause.length ? out : null;
}

/** cut_remove ops for these cut indexes in one step (highest first: each removal shifts the ones after it). */
export function restoreOps(indexes: number[]): { op: 'cut_remove'; index: number }[] {
  return [...new Set(indexes)].sort((a, b) => b - a).map((index) => ({ op: 'cut_remove' as const, index }));
}
