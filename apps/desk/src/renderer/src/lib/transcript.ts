// Pure transcript helpers for text-based editing (ux/text-edit): paragraphs, word spacing, the word at a time,
// pending cuts (word indices + tightened pauses) -> engine ops and seconds, applied cuts -> collapsed markers, the
// kept ranges -> the player's skip list. Word indices are into OutputDoc.words; the engine re-checks them with
// `sig` (stale-words).
import type { EditOp, OutputDoc, Word } from '../../../shared/v04';
import type { LowerTab } from './useSplit';

export type CutWhy = 'transcript' | 'filler' | 'pause';

/** Pending cuts: words (index -> why) and pauses tightened (gap after word i). */
export interface Drafts {
  words: Record<number, CutWhy>;
  gaps: number[];
}

export const EMPTY_DRAFTS: Drafts = { words: {}, gaps: [] };
export const PAUSE_KEEP = 0.25;
export const PARA_GAP = 1.5;

const END = /[。！？!?.…]$/;
// a Latin word, or a Latin word with its punctuation ("posts." "everyone," "it's)"); never CJK punctuation
const LATIN_END = /[A-Za-z0-9%]$|[A-Za-z0-9%][.,!?;:)\]"'”’]+$/;
const LATIN_START = /^["“‘(]?[A-Za-z0-9]/;

/** A space goes between two Latin / number words, also after Latin punctuation ("posts. Hi"); Chinese runs together. */
export function spaceBefore(prev: Word | undefined, cur: Word): boolean {
  if (!prev || !LATIN_END.test(prev.w) || !LATIN_START.test(cur.w)) return false;
  return !/\d[.,]$/.test(prev.w) || !/^\d/.test(cur.w); // "3." "5" / "1," "000" stay one number
}

/** Paragraphs: a new one after a pause over 1.5 s, or at a sentence end once the paragraph is long enough. */
export function paragraphs(words: Word[], maxChars = 90): { i0: number; i1: number; t: number }[] {
  const out: { i0: number; i1: number; t: number }[] = [];
  let i0 = 0;
  let chars = 0;
  for (let i = 0; i < words.length; i++) {
    chars += words[i].w.length;
    const next = words[i + 1];
    const gap = next ? next.t - words[i].te : 0;
    if (!next || gap > PARA_GAP || (END.test(words[i].w) && chars >= maxChars)) {
      out.push({ i0, i1: i, t: words[i0].t });
      i0 = i + 1;
      chars = 0;
    }
  }
  return out;
}

/** The word being said at `t` (or the last one before it), -1 before the first. */
export function wordIndexAt(words: Word[], t: number): number {
  let lo = 0;
  let hi = words.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const m = (lo + hi) >> 1;
    if (words[m].t <= t + 1e-3) {
      ans = m;
      lo = m + 1;
    } else hi = m - 1;
  }
  return ans;
}

export function hasDrafts(d: Drafts): boolean {
  return Object.keys(d.words).length > 0 || d.gaps.length > 0;
}

/** Runs of consecutive pending word indices -> [[i0, i1, why]] (a run is "filler" only when every word in it is). */
export function wordRuns(d: Drafts): [number, number, CutWhy][] {
  const idx = Object.keys(d.words)
    .map(Number)
    .sort((a, b) => a - b);
  const out: [number, number, CutWhy][] = [];
  for (const i of idx) {
    const last = out[out.length - 1];
    if (last && i === last[1] + 1) {
      last[1] = i;
      if (d.words[i] !== last[2]) last[2] = 'transcript';
    } else out.push([i, i, d.words[i]]);
  }
  return out;
}

/** Toggle a selection: all of it pending -> restore it, else mark it all pending (whole words). */
export function toggleRange(d: Drafts, i0: number, i1: number, why: CutWhy = 'transcript'): Drafts {
  const [a, b] = i0 <= i1 ? [i0, i1] : [i1, i0];
  const all = Array.from({ length: b - a + 1 }, (_, k) => a + k);
  const words = { ...d.words };
  if (all.every((i) => i in words)) for (const i of all) delete words[i];
  else for (const i of all) words[i] = words[i] ?? why;
  // a pause inside a cut is gone with it
  const gaps = d.gaps.filter((g) => !(g >= a && g < b && all.every((i) => i in words)));
  return { words, gaps };
}

export function addWords(d: Drafts, idx: number[], why: CutWhy): Drafts {
  const words = { ...d.words };
  for (const i of idx) words[i] = words[i] ?? why;
  return { words, gaps: d.gaps };
}

export function toggleGap(d: Drafts, i: number): Drafts {
  return { words: d.words, gaps: d.gaps.includes(i) ? d.gaps.filter((g) => g !== i) : [...d.gaps, i].sort((a, b) => a - b) };
}

export function addGaps(d: Drafts, idx: number[]): Drafts {
  return { words: d.words, gaps: [...new Set([...d.gaps, ...idx])].sort((a, b) => a - b) };
}

/** Seconds of one pending word run (word edges, the same as the engine before its snapping). */
export function runSpan(words: Word[], i0: number, i1: number): [number, number] {
  const lo = i0 > 0 ? words[i0 - 1].te + 0.01 : 0;
  const hi = i1 + 1 < words.length ? words[i1 + 1].t - 0.01 : words[i1].te + 0.3;
  return [Math.max(lo, words[i0].t - 0.03), Math.min(hi, words[i1].te + 0.03)];
}

export function gapSpan(words: Word[], i: number, keep = PAUSE_KEEP): [number, number] | null {
  if (i < 0 || i + 1 >= words.length) return null;
  const a = words[i].te + keep / 2;
  const b = words[i + 1].t - keep / 2;
  return b - a >= 0.05 ? [a, b] : null;
}

/** The pending cuts as seconds (local, instant: the engine's preview-edl refines them). */
export function draftSpans(words: Word[], d: Drafts): [number, number][] {
  const spans: [number, number][] = wordRuns(d).map(([a, b]) => runSpan(words, a, b));
  for (const g of d.gaps) {
    const s = gapSpan(words, g);
    if (s) spans.push(s);
  }
  return spans.sort((x, y) => x[0] - y[0]);
}

/** One Apply = one step: every run / pause as a cut op with its words, the words signature and why. */
export function draftOps(words: Word[], d: Drafts, sig?: string | null): EditOp[] {
  const ops: EditOp[] = [];
  for (const [a, b, why] of wordRuns(d)) {
    const [s, e] = runSpan(words, a, b);
    ops.push({ op: 'cut', start: round3(s), end: round3(e), words: [a, b], why, ...(sig ? { sig } : {}) });
  }
  for (const g of d.gaps) {
    const s = gapSpan(words, g);
    if (s && !(g in d.words) && !(g + 1 in d.words)) ops.push({ op: 'cut', start: round3(s[0]), end: round3(s[1]), gap: g, keep: PAUSE_KEEP, why: 'pause', ...(sig ? { sig } : {}) });
  }
  return ops.sort((x, y) => (x as { start: number }).start - (y as { start: number }).start);
}

/** How many separate cuts are pending (a run of words or a pause each). */
export function draftCount(d: Drafts): number {
  return wordRuns(d).length + d.gaps.filter((g) => !(g in d.words) && !(g + 1 in d.words)).length;
}

const round3 = (x: number) => Math.round(x * 1000) / 1000;

/** Kept ranges -> what the player skips (the complement inside [0, dur]). */
export function keepToCuts(keep: [number, number][], dur: number): { start: number; end: number }[] {
  const out: { start: number; end: number }[] = [];
  let t = 0;
  for (const [a, b] of [...keep].sort((x, y) => x[0] - y[0])) {
    if (a - t > 0.02) out.push({ start: t, end: a });
    t = Math.max(t, b);
  }
  if (dur - t > 0.02) out.push({ start: t, end: dur });
  return out;
}

/** Trim + cuts -> kept ranges (the engine's `segments`: pieces under 40 ms dropped). */
export function segments(dur: number, cuts: { start: number; end: number }[], trim?: { start: number; end: number } | null): [number, number][] {
  let segs: [number, number][] = [[trim?.start ?? 0, trim?.end ?? dur]];
  for (const c of [...cuts].sort((x, y) => x.start - y.start)) {
    const next: [number, number][] = [];
    for (const [x, y] of segs) {
      if (c.end <= x || c.start >= y) {
        next.push([x, y]);
        continue;
      }
      if (c.start > x) next.push([x, c.start]);
      if (c.end < y) next.push([c.end, y]);
    }
    segs = next;
  }
  return segs.filter(([x, y]) => y - x > 0.04);
}

export function keptSeconds(keep: [number, number][]): number {
  return keep.reduce((s, [a, b]) => s + (b - a), 0);
}

/** Words inside an applied cut collapse to one "✂ cut 2.7 s" marker: index of the first word -> the cut. */
export function appliedRuns(words: Word[], cuts: { start: number; end: number; index: number }[]): Map<number, { i0: number; i1: number; cut: { start: number; end: number; index: number } }> {
  const out = new Map<number, { i0: number; i1: number; cut: { start: number; end: number; index: number } }>();
  for (const c of cuts) {
    let i0 = -1;
    let i1 = -1;
    for (let i = 0; i < words.length; i++) {
      const mid = (words[i].t + words[i].te) / 2;
      if (mid >= c.start && mid <= c.end) {
        if (i0 < 0) i0 = i;
        i1 = i;
      } else if (i0 >= 0) break;
    }
    if (i0 >= 0) out.set(i0, { i0, i1, cut: c });
  }
  return out;
}

/** Selected words: how many and how long. */
export function selectionInfo(words: Word[], i0: number, i1: number): { n: number; secs: number } {
  const [a, b] = i0 <= i1 ? [i0, i1] : [i1, i0];
  if (!words[a] || !words[b]) return { n: 0, secs: 0 };
  return { n: b - a + 1, secs: Math.max(0, words[b].te - words[a].t) };
}

/** Plain text of words a..b (spacing rules of the transcript). */
export function joinWords(words: Word[], a: number, b: number): string {
  let s = '';
  for (let i = a; i <= b && i < words.length; i++) s += (spaceBefore(words[i - 1], words[i]) && i > a ? ' ' : '') + words[i].w;
  return s;
}

/** Plain text of a list of words (same spacing rules). */
export function wordsText(words: Word[]): string {
  return joinWords(words, 0, words.length - 1);
}

/** Replace one word inside a caption line (the first match after the words before it), for a caption-only fix. */
export function fixInCue(cueText: string, word: string, next: string): string | null {
  const i = cueText.indexOf(word);
  if (i < 0) return null;
  return cueText.slice(0, i) + next + cueText.slice(i + word.length);
}

/** Talking-head clips open on the transcript: words cover most of the clip. */
export function defaultTab(doc: Pick<OutputDoc, 'words' | 'duration'>): LowerTab {
  if (doc.words.length < 8 || !doc.duration) return 'timeline';
  const spoken = doc.words.reduce((s, w) => s + Math.max(0, w.te - w.t), 0);
  return spoken / doc.duration >= 0.35 ? 'transcript' : 'timeline';
}

