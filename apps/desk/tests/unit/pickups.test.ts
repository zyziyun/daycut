// Pickups in the clip editor (ux/record/pickups): where a pickup goes from the transcript selection, which words are a
// pickup's, the recording's automatic cuts by kind and bringing them back in one step; the recorder's takes of one
// Record visit (groups) for Takes.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ shell: { trashItem: vi.fn() }, systemPreferences: {}, desktopCapturer: {} }));

import { autoKinds, pickupWords, restoreOps, spotBody, spotOf } from '../../src/renderer/src/v4/pickup/pickupModel';
import { gapCuts } from '../../src/renderer/src/lib/transcript';
import { Recorder } from '../../src/main/recorder';
import { validateIpc } from '../../src/shared/ipc';

const W = ['Hi', 'there,', 'today', 'we', 'cut', 'words'].map((w, i) => ({ w, t: i * 0.5, te: i * 0.5 + 0.4 }));

describe('pickups', () => {
  it('a selection becomes a spot: replace those words, or insert after them', () => {
    const r = spotOf(W, { a: 4, b: 2 }, 'replace');
    expect(r).toEqual({ kind: 'replace', a: 2, b: 4, text: 'today we cut' });
    expect(spotBody(r)).toEqual({ replace: [2, 4] });
    expect(spotBody(spotOf(W, { a: 1, b: 1 }, 'insert'))).toEqual({ at_word: 2 });
    expect(spotBody(spotOf(W, { a: 5, b: 9 }, 'insert'))).toEqual({ at_word: 6 }); // after the last word = the end
  });

  it('the words inside a pickup are numbered in timeline order', () => {
    const m = pickupWords(W, [
      { id: 'p2', start: 2.0, end: 2.95, text: '', replaced: '' },
      { id: 'p1', start: 0.0, end: 0.45, text: '', replaced: '' },
    ]);
    expect([...m.entries()]).toEqual([
      [0, 1],
      [4, 2],
      [5, 2],
    ]);
    expect(pickupWords(W, undefined).size).toBe(0);
  });

  it('automatic cuts by kind, only while the automatic step is in; restore in one step, highest index first', () => {
    const cuts = [
      { start: 0, end: 0.2, index: 0, why: 'pause' },
      { start: 1, end: 2, index: 1, why: 'retake' },
      { start: 2.2, end: 2.3, index: 2, why: 'filler' },
      { start: 3, end: 3.1, index: 3, why: 'transcript' },
    ];
    const steps = [{ id: 's1', by: 'auto', describe: [] }];
    expect(autoKinds({ steps, cuts })).toEqual({ retake: [1], filler: [2], pause: [0] });
    expect(autoKinds({ steps: [{ ...steps[0], reverted: true }], cuts })).toBeNull();
    expect(autoKinds({ steps: [{ id: 's1', by: 'you', describe: [] }], cuts })).toBeNull();
    expect(autoKinds({ steps, cuts: cuts.slice(3) })).toBeNull();
    expect(restoreOps([0, 2, 2, 1])).toEqual([
      { op: 'cut_remove', index: 2 },
      { op: 'cut_remove', index: 1 },
      { op: 'cut_remove', index: 0 },
    ]);
  });

  it('a cut that only shortens a pause belongs to that gap', () => {
    const g = gapCuts(W, [
      { start: 0.42, end: 0.48, index: 0, why: 'pause' },
      { start: 1.0, end: 1.9, index: 1, why: 'retake' },
    ]);
    expect([...g.keys()]).toEqual([0]);
    expect(g.get(0)?.why).toBe('pause');
  });

  it('takes of one Record visit: newest first, not pickups, not live', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'rec-group-'));
    const r = new Recorder(root);
    const a = r.begin({ slug: 'recording', script: [], tracks: ['camera'], group: 'abc12345' });
    r.end({ sessionId: a.sessionId, secs: 12.34 });
    const p = r.begin({ slug: 'pickup', script: [], tracks: ['camera'], group: 'abc12345', pickup: true });
    r.end({ sessionId: p.sessionId });
    const other = r.begin({ slug: 'recording', script: [], tracks: ['camera'], group: 'zzz99999' });
    r.end({ sessionId: other.sessionId });
    const live = r.begin({ slug: 'recording', script: [], tracks: ['camera'], group: 'abc12345' });
    const list = r.list('abc12345');
    expect(list.map((x) => x.id)).toEqual([a.sessionId]);
    expect(list[0]).toMatchObject({ secs: 12.3, edited: false });
    fs.mkdirSync(path.join(a.dir, 'final'));
    fs.writeFileSync(path.join(a.dir, 'final', 'recording.mp4'), '');
    expect(r.list('abc12345')[0].edited).toBe(true);
    r.end({ sessionId: live.sessionId });
    expect(r.list('abc12345')).toHaveLength(2);
    expect(() => validateIpc('rec:list', { group: '../x' })).toThrow();
    expect(() => validateIpc('rec:begin', { slug: 'a', script: [], tracks: ['camera'], group: 'NOPE' })).toThrow();
  });
});
