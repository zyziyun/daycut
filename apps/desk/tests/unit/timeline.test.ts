// Timeline v2 math: time <-> px at a zoom, zoom anchored at the cursor, adaptive ruler ticks, word virtualisation,
// sprite tiles, waveform columns, word-snapped selection, the scrub preview box.
import { describe, expect, it } from 'vitest';
import {
  MAX_PPS,
  clampPps,
  clock,
  fitText,
  firstWordFrom,
  fitPps,
  listenEstimate,
  mergeWords,
  peakColumns,
  rulerLabel,
  rulerTicks,
  snapRange,
  tileAt,
  tileOffset,
  toT,
  toX,
  wordAt,
  wordsIn,
  zoomAt,
} from '../../src/renderer/src/lib/timeline';
import { previewBox } from '../../src/renderer/src/v4/Scrubber';

const words = [
  { w: '你在', t: 0.2, te: 0.6 },
  { w: '副业', t: 0.6, te: 1.1 },
  { w: '当中', t: 1.1, te: 1.5 },
  { w: '其实', t: 2.4, te: 2.9 },
  { w: '底气', t: 2.9, te: 3.5 },
];

describe('time <-> px', () => {
  it('maps both ways and clamps', () => {
    expect(toX(30, 90, 900)).toBe(300);
    expect(toT(300, 90, 900)).toBe(30);
    expect(toT(-10, 90, 900)).toBe(0);
    expect(toT(2000, 90, 900)).toBe(90);
    expect(toT(toX(12.34, 97.9, 777), 97.9, 777)).toBeCloseTo(12.34, 6);
  });
  it('fit and clamp keep the zoom between "whole clip" and MAX_PPS', () => {
    expect(fitPps(100, 800)).toBe(8);
    expect(clampPps(1, 100, 800)).toBe(8);
    expect(clampPps(1e6, 100, 800)).toBe(MAX_PPS);
    expect(clampPps(1e6, 1, 800)).toBe(800); // a 1 s clip: fit is already above the cap
  });
  it('zoomAt keeps the time under the cursor in place', () => {
    const z = zoomAt(10, 2, 100, 250, 600, 800); // t under the cursor = (100 + 250) / 10 = 35 s
    expect(z.pps).toBe(20);
    expect((z.scrollLeft + 250) / z.pps).toBeCloseTo(35, 6);
    const back = zoomAt(20, 0.01, z.scrollLeft, 250, 600, 800);
    expect(back.pps).toBeCloseTo(fitPps(600, 800), 6);
    expect(back.scrollLeft).toBe(0);
  });
});

describe('ruler ticks', () => {
  it('adapts the step to the zoom (labelled majors >= 72 px apart)', () => {
    expect(rulerTicks(8, 0, 97.9).step).toBe(10); // a fitted 98 s clip: every 10 s
    expect(rulerTicks(100, 0, 8).step).toBe(1);
    expect(rulerTicks(400, 0, 2).step).toBe(0.2);
    expect(rulerTicks(0.5, 0, 1800).step).toBe(300); // 30 min fitted: every 5 min
    for (const pps of [0.3, 2, 8, 37, 120, 400]) {
      const r = rulerTicks(pps, 0, 1000 / pps);
      expect(r.step * pps).toBeGreaterThanOrEqual(72);
      const gaps = r.major.slice(1).map((m, i) => m.t - r.major[i].t);
      gaps.forEach((g) => expect(g).toBeCloseTo(r.step, 6));
    }
  });
  it('minor ticks sit between majors, never on them', () => {
    const r = rulerTicks(8, 0, 60);
    expect(r.major.map((m) => m.t)).toEqual([0, 10, 20, 30, 40, 50, 60]);
    expect(r.minor.length).toBeGreaterThan(0);
    r.minor.forEach((m) => expect(m % 10).not.toBe(0));
  });
  it('only covers the visible window', () => {
    const r = rulerTicks(8, 200, 300);
    expect(r.major[0].t).toBeGreaterThanOrEqual(200);
    expect(r.major[r.major.length - 1].t).toBeLessThanOrEqual(300);
  });
  it('labels: m:ss, h:mm:ss, tenths below a second', () => {
    expect(rulerLabel(0)).toBe('0:00');
    expect(rulerLabel(65)).toBe('1:05');
    expect(rulerLabel(3725)).toBe('1:02:05');
    expect(rulerLabel(1.5, 0.5)).toBe('0:01.5');
    expect(rulerLabel(2, 0.5)).toBe('0:02');
    expect(rulerTicks(200, 0, 2).major.map((m) => m.label)).toEqual(['0:00', '0:00.5', '0:01', '0:01.5', '0:02']);
    expect(clock(23.44, true)).toBe('0:23.4');
    expect(clock(59.97, true)).toBe('1:00.0');
    expect(clock(3599.4)).toBe('59:59');
    expect(rulerTicks(8, 0, 30).major.map((m) => m.label)).toEqual(['0:00', '0:10', '0:20', '0:30']);
  });
});

describe('selection + virtualisation', () => {
  it('a drag snaps outward to whole words; a shared edge belongs to the next word', () => {
    expect(snapRange(words, 0.7, 3.2)).toEqual({ a: 0.6, b: 3.5, i0: 1, i1: 4 });
    expect(snapRange(words, 3.2, 0.7)).toEqual({ a: 0.6, b: 3.5, i0: 1, i1: 4 });
    expect(wordAt(words, 0.6)).toBe(1);
    expect(wordAt(words, 3.5)).toBe(4); // the last edge stays with its word
    expect(wordAt(words, 1.8)).toBe(2); // a gap: the nearest word
    expect(snapRange([], 0, 1)).toBeNull();
  });
  it('only the words touching the window are drawn', () => {
    expect(firstWordFrom(words, 1.2)).toBe(2);
    expect(wordsIn(words, 1.2, 2.5).map((x) => x.w.w)).toEqual(['当中', '其实']);
    const many = Array.from({ length: 20000 }, (_, i) => ({ w: 'x', t: i * 0.3, te: i * 0.3 + 0.25 }));
    const vis = wordsIn(many, 3000, 3010);
    expect(vis.length).toBeLessThan(40);
    expect(vis[0].i).toBe(10000);
  });
  it('fitted strips merge neighbours into readable phrases that still start at their first word', () => {
    const m = mergeWords(words, 20);
    expect(m.length).toBeLessThan(words.length);
    expect(m[0].t).toBe(0.2);
    expect(m.map((x) => x.w).join('')).toBe('你在副业当中其实底气');
    expect(mergeWords(words, 400)).toHaveLength(words.length);
  });
});

describe('words fit their box', () => {
  it('cuts at a character, CJK ~12 px, Latin ~7 px', () => {
    expect(fitText('一万六千个核心', 50)).toBe('一万六千');
    expect(fitText('kernel', 30)).toBe('kern');
    expect(fitText('副业', 10)).toBe('');
    expect(fitText('副业', 100)).toBe('副业');
  });
});

describe('filmstrip + waveform', () => {
  const s = { n: 196, interval: 0.5, cols: 12, tile: [54, 96] as [number, number] };
  it('tile for a time, and its offset in the sprite', () => {
    expect(tileAt(0, s)).toBe(0);
    expect(tileAt(23.4, s)).toBe(46);
    expect(tileAt(1e6, s)).toBe(195);
    expect(tileOffset(46, s)).toEqual({ x: 10 * 54, y: 3 * 96 });
  });
  it('one peak per column = the max of the buckets under it', () => {
    const peaks = [0.1, 0.9, 0.2, 0.3, 0.5, 0.4, 0, 0];
    expect(Array.from(peakColumns(peaks, 4, 0, 2, 4))).toEqual([0.9, 0.3, 0.5, 0].map(Math.fround));
    expect(Array.from(peakColumns(peaks, 4, 1, 4, 2))).toEqual([0.5, 0.4].map(Math.fround));
    expect(peakColumns([], 50, 0, 10, 5)).toHaveLength(5);
  });
  it('scrub preview keeps the frame aspect within 168 x 120', () => {
    expect(previewBox({ tile: [54, 96] })).toMatchObject({ w: 68, h: 120 });
    expect(previewBox({ tile: [170, 96] })).toMatchObject({ w: 168, h: 95 });
  });
  it('「听一遍」 estimate: about a fifth of the clip, rounded to 5 s', () => {
    expect(listenEstimate(97.9)).toBe(20);
    expect(listenEstimate(8)).toBe(10);
    expect(listenEstimate(600)).toBe(120);
  });
});
