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
    if (t >= w.t && (t < w.te || (t === w.te && words[i + 1]?.t !== t))) return i; // a shared edge belongs to the next word
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

// ------------------------------------------------------------------ zoom, ruler, virtualisation (timeline v2)
/** Most pixels per second the timeline zooms to (a frame at 30 fps is ~13 px). */
export const MAX_PPS = 400;

/** Pixels per second that fit the whole clip into `width`. */
export function fitPps(duration: number, width: number): number {
  return duration > 0 && width > 0 ? width / duration : 1;
}

/** Keep a zoom between "fit" and MAX_PPS. */
export function clampPps(pps: number, duration: number, width: number): number {
  const lo = fitPps(duration, width);
  return Math.min(Math.max(lo, MAX_PPS), Math.max(lo, pps));
}

/** Zoom by `factor` keeping the time under `anchorPx` (px from the viewport's left edge) where it is. */
export function zoomAt(pps: number, factor: number, scrollLeft: number, anchorPx: number, duration: number, width: number): { pps: number; scrollLeft: number } {
  const next = clampPps(pps * factor, duration, width);
  const t = (scrollLeft + anchorPx) / pps;
  const maxScroll = Math.max(0, duration * next - width);
  return { pps: next, scrollLeft: Math.min(maxScroll, Math.max(0, t * next - anchorPx)) };
}

const STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];

/** Ruler ticks for [t0, t1] at `pps`: labelled majors at least `minPx` apart, minors between (>= 6 px). */
export function rulerTicks(pps: number, t0: number, t1: number, minPx = 72): { step: number; major: { t: number; label: string }[]; minor: number[] } {
  const step = STEPS.find((s) => s * pps >= minPx) ?? 7200;
  const div = [10, 5, 4, 2].find((d) => (step / d) * pps >= 6 && Number.isInteger(Math.round((step / d) * 1000))) ?? 1;
  const minorStep = step / div;
  const major: { t: number; label: string }[] = [];
  const minor: number[] = [];
  const a = Math.max(0, Math.floor(t0 / minorStep) * minorStep);
  for (let k = Math.round(a / minorStep); k * minorStep <= t1 + 1e-9; k++) {
    const t = round(k * minorStep);
    if (k % div === 0) major.push({ t, label: rulerLabel(t, step) });
    else minor.push(t);
  }
  return { step, major, minor };
}

/** 0:05 · 1:30 · 1:02:00 — sub-second ticks show tenths (0:01.5) but whole seconds stay 0:02. */
export function rulerLabel(t: number, step = 1): string {
  const d = Math.round(Math.abs(t) * 10);
  return clock(t, step < 1 && d % 10 !== 0);
}

/** m:ss (h:mm:ss past an hour), optionally with tenths: 0:23.4 */
export function clock(t: number, tenths = false): string {
  const neg = t < 0;
  const x = tenths ? Math.round(Math.abs(t) * 10) / 10 : Math.floor(Math.abs(t) + 1e-6);
  const h = Math.floor(x / 3600);
  const m = Math.floor((x % 3600) / 60);
  const sec = x - h * 3600 - m * 60;
  const ss = tenths ? sec.toFixed(1).padStart(4, '0') : String(Math.round(sec)).padStart(2, '0');
  return `${neg ? '−' : ''}${h ? `${h}:${String(m).padStart(2, '0')}` : m}:${ss}`;
}

/** First index whose word ends at or after t (binary search; words sorted by start). */
export function firstWordFrom(words: Word[], t: number): number {
  let lo = 0;
  let hi = words.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].te < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The words that touch [t0, t1] (virtualised rendering of long transcripts). */
export function wordsIn(words: Word[], t0: number, t1: number): { i: number; w: Word }[] {
  const out: { i: number; w: Word }[] = [];
  for (let i = firstWordFrom(words, t0); i < words.length && words[i].t <= t1; i++) out.push({ i, w: words[i] });
  return out;
}

export interface SpriteLayout {
  n: number;
  interval: number;
  cols: number;
  tile: [number, number];
}

/** Sprite tile index for time t (tile i is the frame at i * interval). */
export function tileAt(t: number, s: SpriteLayout): number {
  return Math.max(0, Math.min(s.n - 1, Math.floor((t + 1e-6) / s.interval)));
}

/** Background offset (sprite px) of tile i. */
export function tileOffset(i: number, s: SpriteLayout): { x: number; y: number } {
  return { x: (i % s.cols) * s.tile[0], y: Math.floor(i / s.cols) * s.tile[1] };
}

/** One peak per pixel column for [t0, t0 + cols / pps] (max of the buckets under each column). */
export function peakColumns(peaks: number[], rate: number, t0: number, pps: number, cols: number): Float32Array {
  const out = new Float32Array(Math.max(0, cols));
  if (!peaks.length || rate <= 0) return out;
  for (let c = 0; c < cols; c++) {
    const a = Math.floor((t0 + c / pps) * rate);
    const b = Math.max(a + 1, Math.floor((t0 + (c + 1) / pps) * rate));
    let m = 0;
    for (let k = Math.max(0, a); k < Math.min(peaks.length, b); k++) if (peaks[k] > m) m = peaks[k];
    out[c] = m;
  }
  return out;
}

/** Fitted to a narrow strip, single words are too small to read: neighbouring words merge into phrases of at least
 * `minPx` (each still starts at its first word, so a click seeks there). */
export function mergeWords(words: Word[], pps: number, minPx = 56): Word[] {
  const min = minPx / pps;
  const out: Word[] = [];
  for (const x of words) {
    const last = out[out.length - 1];
    if (last && (x.te - last.t < min || last.w.length < 2) && x.t - last.te < 0.6) out[out.length - 1] = { w: last.w + (/[A-Za-z0-9]$/.test(last.w) && /^[A-Za-z0-9]/.test(x.w) ? ' ' : '') + x.w, t: last.t, te: x.te };
    else out.push({ ...x });
  }
  return out;
}

/** About how long 「听一遍」 takes for a clip (seconds, rounded to 5). */
export function listenEstimate(duration: number): number {
  return Math.max(10, Math.min(900, Math.round((duration * 0.2) / 5) * 5));
}

/** The longest prefix of `s` that fits `px` at 12 px type (CJK ~12 px, Latin ~6.8 px a character): words are cut at a
 * character, never through a glyph. */
export function fitText(s: string, px: number): string {
  let w = 0;
  let i = 0;
  for (const ch of s) {
    w += /[⺀-￿]/.test(ch) ? 12 : 6.8;
    if (w > px) break;
    i += ch.length;
  }
  return s.slice(0, i);
}
