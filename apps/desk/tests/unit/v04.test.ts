// v0.4 renderer logic: routes, the four status words, player math (frames, J/K/L, loop, timecode), timeline math
// (word snapping, effect move / resize, rows), the preview fold of proposed edits, calendar slots, QC reasons, and
// the theme contrast (WCAG AA for text pairs).
import { describe, expect, it } from 'vitest';
import type { HistoryItem } from '../../src/shared/v02';
import type { OutputDoc } from '../../src/shared/v04';
import { previewDoc, keptLength } from '../../src/renderer/src/lib/outputs';
import { clamp, frameIndex, frameTime, loopTime, safeAreas, shuttle, step, timecode } from '../../src/renderer/src/lib/player';
import { href, parseRoute } from '../../src/renderer/src/lib/router';
import { clipStatus, itemStatus } from '../../src/renderer/src/lib/status';
import { isCut, moveEffect, resizeEffect, snapEdge, snapRange, stackRows, wordAt } from '../../src/renderer/src/lib/timeline';
import { contrast, tokens } from '../../src/renderer/src/theme/tokens';

const words = [
  { w: '你在', t: 0, te: 0.5 },
  { w: '副业', t: 0.5, te: 1.0 },
  { w: '当中', t: 1.0, te: 1.4 },
  { w: '其实', t: 2.4, te: 2.8 },
];

describe('routes', () => {
  it('parses the v0.4 routes and lands old links on the new pages', () => {
    expect(parseRoute('')).toEqual({ name: 'home' });
    expect(parseRoute('#/batches')).toEqual({ name: 'projects' });
    expect(parseRoute('#/work/0123456789ab')).toEqual({ name: 'project', id: '0123456789ab' });
    expect(parseRoute('#/p/0123456789ab/files')).toEqual({ name: 'project', id: '0123456789ab', tab: 'files' });
    expect(parseRoute(href({ name: 'clip', id: '0123456789ab', clip: 'A_换圈子' }))).toEqual({ name: 'clip', id: '0123456789ab', clip: 'A_换圈子' });
    expect(parseRoute('#/p/0123456789ab/focus')).toEqual({ name: 'focus', id: '0123456789ab' });
    expect(parseRoute('#/publish')).toEqual({ name: 'calendar' });
    expect(parseRoute('#/nonsense')).toEqual({ name: 'home' });
  });
});

describe('four status words', () => {
  const base = { kind: 'work', status: 'done', counts: { total: 4, green: 0, red: 0, approved: 0, done: 4, failed: 0 }, updated: 0, live: null } as unknown as HistoryItem;
  it('maps live runs, finished work, review needs and errors', () => {
    expect(itemStatus(base)).toBe('done');
    expect(itemStatus({ ...base, live: { state: 'running' } as HistoryItem['live'] })).toBe('run');
    expect(itemStatus({ ...base, live: { state: 'waiting', needs_you: true } as HistoryItem['live'] })).toBe('you');
    expect(itemStatus({ ...base, live: { state: 'interrupted', heartbeat: Date.now() / 1000 - 60 } as HistoryItem['live'] })).toBe('error');
    expect(itemStatus({ ...base, kind: 'batch', counts: { ...base.counts, red: 3, approved: 0 } })).toBe('you');
    expect(itemStatus({ ...base, kind: 'batch', status: 'delivered' })).toBe('done');
    expect(itemStatus({ ...base, status: 'unreadable' })).toBe('error');
    expect(itemStatus({ ...base, status: 'planned' })).toBeNull();
  });
  it('clips: queued shows no pill, red QC needs you until approved', () => {
    expect(clipStatus({ state: 'queued' })).toBeNull();
    expect(clipStatus({ state: 'running' })).toBe('run');
    expect(clipStatus({ state: 'done', qc: 'red' })).toBe('you');
    expect(clipStatus({ state: 'approved', qc: 'red', review: 'approve' })).toBe('done');
  });
});

describe('player math', () => {
  it('steps one frame (Shift: one second) and stays in range', () => {
    expect(frameIndex(step(1.0, 1, 30, 10), 30)).toBe(31);
    expect(frameIndex(step(1.0, -1, 30, 10), 30)).toBe(29);
    expect(step(9.9, 1, 30, 10, true)).toBe(10);
    expect(step(0, -1, 30, 10)).toBeGreaterThanOrEqual(0);
    expect(frameTime(1.01, 30)).toBeCloseTo(30.5 / 30);
    expect(clamp(5, 0, 3)).toBe(3);
  });
  it('J/K/L shuttle doubles up to 4x and K stops', () => {
    expect(shuttle(0, 'l')).toBe(1);
    expect(shuttle(1, 'l')).toBe(2);
    expect(shuttle(4, 'l')).toBe(4);
    expect(shuttle(2, 'j')).toBe(-1);
    expect(shuttle(-1, 'j')).toBe(-2);
    expect(shuttle(-2, 'k')).toBe(0);
  });
  it('loops the selection and formats timecode', () => {
    expect(loopTime(5.1, { a: 2, b: 5 }, true)).toBe(2);
    expect(loopTime(3, { a: 2, b: 5 }, true)).toBeNull();
    expect(loopTime(5.1, { a: 2, b: 5 }, false)).toBeNull();
    expect(timecode(62.5, 30)).toBe('00:01:02:15');
    expect(safeAreas('9:16')).not.toBeNull();
    expect(safeAreas('16:9')).toBeNull();
  });
});

describe('timeline math', () => {
  it('snaps drags to whole words and edges to word boundaries', () => {
    expect(wordAt(words, 1.2)).toBe(2);
    expect(wordAt(words, 1.9)).toBe(2);
    expect(snapRange(words, 0.7, 1.1)).toMatchObject({ a: 0.5, b: 1.4, i0: 1, i1: 2 });
    expect(snapEdge(words, 2.35)).toBe(2.4);
    expect(snapEdge(words, 1.9)).toBe(1.9);
    expect(isCut(0.5, 1.0, [{ start: 0.5, end: 1.4 }])).toBe(true);
  });
  it('moves and resizes effects inside the clip and stacks overlaps', () => {
    expect(moveEffect({ start: 1, end: 2 }, 9, 5)).toEqual({ start: 4, end: 5 });
    expect(moveEffect({ start: 1, end: 2 }, -3, 5)).toEqual({ start: 0, end: 1 });
    expect(resizeEffect({ start: 1, end: 2 }, 'r', 1.05, 5)).toEqual({ start: 1, end: 1.2 });
    expect(resizeEffect({ start: 1, end: 2 }, 'l', 0.5, 5)).toEqual({ start: 0.5, end: 2 });
    const rows = stackRows([{ start: 0, end: 2 }, { start: 1, end: 3 }, { start: 2.5, end: 4 }]);
    expect(rows.map((r) => r.row)).toEqual([0, 1, 0]);
  });
  it('previews a proposal (trim, cut, effect) without applying it', () => {
    const doc = { duration: 10, trim: null, cuts: [], effects: [] } as unknown as OutputDoc;
    const p = previewDoc(doc, [{ op: 'trim', start: 2.4, end: 9 }, { op: 'cut', start: 4, end: 5 }, { op: 'effect_add', effect: 'pop-words', start: 3, params: { text: '底气' } }]);
    expect(p.trim).toEqual({ start: 2.4, end: 9 });
    expect(p.cuts).toHaveLength(1);
    expect(p.effects[0]).toMatchObject({ effect: 'pop-words', start: 3, end: 4.2 });
    expect(keptLength(p)).toBeCloseTo(5.6);
    expect(doc.cuts).toHaveLength(0);
    expect(previewDoc(doc, null)).toBe(doc);
  });
});

describe('theme', () => {
  it('text pairs meet WCAG AA in both themes and both accents', () => {
    for (const th of ['studio-dark', 'notebook-light'] as const) {
      for (const ac of ['teal', 'red'] as const) {
        const k = tokens(th, ac);
        expect(contrast(k.text, k.bg), `${th} text`).toBeGreaterThanOrEqual(7);
        expect(contrast(k.textMuted, k.bg), `${th} muted`).toBeGreaterThanOrEqual(4.5);
        expect(contrast(k.textMuted, k.surface), `${th} muted on surface`).toBeGreaterThanOrEqual(4.5);
        expect(contrast(k.accentText, k.accent), `${th}/${ac} primary button`).toBeGreaterThanOrEqual(4.5);
        for (const s of [k.run, k.you, k.ok, k.danger]) expect(contrast(s, k.bg), `${th} status ${s}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
