// Timeline math for the output editor: word-snapped selections, trims and cuts; effect move / resize; pixel <-> time.
import type { EffectInstance, Word } from '../../../shared/v04';

export function toX(t: number, duration: number, width: number): number {
  return duration > 0 ? (t / duration) * width : 0;
}

export function toT(x: number, duration: number, width: number): number {
  return width > 0 ? Math.min(duration, Math.max(0, (x / width) * duration)) : 0;
}

/** Index of the word at time t (nearest when t is in a gap). */
export function wordAt(words: Word[], t: number): number {
  if (!words.length) return -1;
  let best = 0;
  let bd = Infinity;
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    if (t >= w.t && t <= w.te) return i;
    const d = Math.min(Math.abs(t - w.t), Math.abs(t - w.te));
    if (d < bd) {
      bd = d;
      best = i;
    }
  }
  return best;
}

/** A drag from time a to b -> the selection snapped outward to whole words. */
export function snapRange(words: Word[], a: number, b: number): { a: number; b: number; i0: number; i1: number } | null {
  if (!words.length) return null;
  const [x, y] = a <= b ? [a, b] : [b, a];
  const i0 = wordAt(words, x);
  const i1 = Math.max(i0, wordAt(words, y));
  return { a: words[i0].t, b: words[i1].te, i0, i1 };
}

/** Snap one edge (trim handle) to the nearest word boundary within `tol` seconds. */
export function snapEdge(words: Word[], t: number, tol = 0.25): number {
  let best = t;
  let bd = tol;
  for (const w of words) {
    for (const e of [w.t, w.te]) {
      const d = Math.abs(e - t);
      if (d < bd) {
        bd = d;
        best = e;
      }
    }
  }
  return best;
}

export function isCut(t0: number, t1: number, cuts: { start: number; end: number }[]): boolean {
  return cuts.some((c) => t0 >= c.start - 0.02 && t1 <= c.end + 0.02);
}

/** Move an effect by dt, keeping its length and the clip bounds. */
export function moveEffect(e: Pick<EffectInstance, 'start' | 'end'>, dt: number, duration: number): { start: number; end: number } {
  const len = e.end - e.start;
  const start = Math.min(Math.max(0, e.start + dt), Math.max(0, duration - len));
  return { start: round(start), end: round(start + len) };
}

/** Resize from the left or right edge; at least `min` seconds long. */
export function resizeEffect(e: Pick<EffectInstance, 'start' | 'end'>, edge: 'l' | 'r', t: number, duration: number, min = 0.2): { start: number; end: number } {
  if (edge === 'l') return { start: round(Math.min(Math.max(0, t), e.end - min)), end: e.end };
  return { start: e.start, end: round(Math.max(Math.min(duration, t), e.start + min)) };
}

export function round(x: number): number {
  return Math.round(x * 1000) / 1000;
}

/** Overlapping effects go to separate rows. */
export function stackRows<T extends { start: number; end: number }>(items: T[]): (T & { row: number })[] {
  const ends: number[] = [];
  return [...items]
    .sort((a, b) => a.start - b.start)
    .map((e) => {
      let r = ends.findIndex((x) => x <= e.start);
      if (r < 0) r = ends.push(0) - 1;
      ends[r] = e.end;
      return { ...e, row: r };
    });
}
