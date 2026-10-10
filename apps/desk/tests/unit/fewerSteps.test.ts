// Fewer steps (ux/fewer-steps): transcript deletes save themselves - one save per burst (coalesced), one at a time,
// edits made during a save are saved right after it, a failure is shown and not retried by itself for the same
// edits, flush() saves now; the drafts reducer drops what was saved; which AI changes still wait for Apply.
import { describe, expect, it } from 'vitest';
import { askFirstReason } from '../../src/renderer/src/lib/chatEdit';
import { clipDecisions, flipAnswer, locateCut, pickAnswer } from '../../src/renderer/src/lib/decided';
import { AutoCommit, draftsKey, step, storeCommitted, subtractDrafts } from '../../src/renderer/src/lib/textCuts';
import type { Drafts } from '../../src/renderer/src/lib/transcript';
import type { AutopilotDecision, InboxOption, OutputDoc } from '../../src/shared/v04';

/** Fake timers: run() fires every armed timer whose time has come. */
function clock() {
  let now = 0;
  let seq = 0;
  const timers = new Map<number, { at: number; f: () => void }>();
  return {
    timers: {
      set: (f: () => void, ms: number) => {
        const id = ++seq;
        timers.set(id, { at: now + ms, f });
        return id;
      },
      clear: (h: unknown) => void timers.delete(h as number),
    },
    armed: () => timers.size,
    async advance(ms: number) {
      now += ms;
      for (const [id, x] of [...timers.entries()].sort((a, b) => a[1].at - b[1].at)) {
        if (x.at <= now) {
          timers.delete(id);
          x.f();
        }
      }
      for (let i = 0; i < 10; i++) await Promise.resolve();
    },
  };
}

const D = (words: number[], gaps: number[] = []): Drafts => ({ words: Object.fromEntries(words.map((i) => [i, 'transcript'])), gaps });

/** A clip's drafts + an engine that records each save; `fail` makes the next saves fail. */
function rig(delay = 1000) {
  const c = clock();
  const st = { cur: D([]), saves: [] as Drafts[], fail: 0, gate: null as null | (() => void) };
  const ac = new AutoCommit<Drafts>({
    get: () => st.cur,
    empty: (v) => !Object.keys(v.words).length && !v.gaps.length,
    key: draftsKey,
    delay,
    timers: c.timers,
    commit: async (v) => {
      if (st.gate) await new Promise<void>((r) => (st.gate = r));
      if (st.fail > 0) {
        st.fail--;
        return false;
      }
      st.saves.push(v);
      st.cur = subtractDrafts(st.cur, v); // the caller drops the saved drafts before resolving
      return true;
    },
  });
  const edit = (d: Drafts) => {
    st.cur = d;
    ac.changed();
  };
  return { c, st, ac, edit };
}

describe('AutoCommit (deletes save themselves)', () => {
  it('a burst of deletes becomes ONE save after the quiet period', async () => {
    const { c, st, edit } = rig();
    edit(D([3]));
    await c.advance(400);
    edit(D([3, 4]));
    await c.advance(400);
    edit(D([3, 4, 5]));
    await c.advance(999);
    expect(st.saves).toEqual([]);
    await c.advance(1);
    expect(st.saves).toEqual([D([3, 4, 5])]);
    expect(st.cur).toEqual(D([]));
    await c.advance(5000);
    expect(st.saves.length).toBe(1);
  });

  it('nothing to save: no timer, no save', async () => {
    const { c, st, ac } = rig();
    ac.changed();
    expect(c.armed()).toBe(0);
    await c.advance(5000);
    expect(st.saves).toEqual([]);
  });

  it('one save at a time: edits made while a save runs are saved right after it (never twice)', async () => {
    const { c, st, ac, edit } = rig();
    st.gate = () => undefined; // the first save waits
    edit(D([1]));
    await c.advance(1000);
    expect(ac.busy).toBe(true);
    edit(D([1, 9])); // deleted while it saves
    await c.advance(1000); // the timer fires during the save: no second save in parallel
    expect(st.saves).toEqual([]);
    const open = st.gate;
    st.gate = null;
    open?.();
    await c.advance(0);
    expect(st.saves).toEqual([D([1])]);
    expect(st.cur).toEqual(D([9]));
    await c.advance(1000);
    expect(st.saves).toEqual([D([1]), D([9])]);
    expect(st.cur).toEqual(D([]));
  });

  it('a failed save is shown, not retried by itself for the same edits; Retry or another delete saves', async () => {
    const { c, st, ac, edit } = rig();
    st.fail = 1;
    edit(D([2]));
    await c.advance(1000);
    expect(st.saves).toEqual([]);
    await c.advance(10_000);
    expect(st.saves).toEqual([]); // no retry loop
    ac.changed(); // the same edits again: still no retry
    await c.advance(1000);
    expect(st.saves).toEqual([]);
    expect(await ac.retry()).toBe(true);
    expect(st.saves).toEqual([D([2])]);
    st.fail = 1;
    edit(D([6]));
    await c.advance(1000);
    expect(st.saves.length).toBe(1);
    edit(D([6, 7])); // another delete: tried again with everything
    await c.advance(1000);
    expect(st.saves).toEqual([D([2]), D([6, 7])]);
  });

  it('flush saves now (Export, ⌘↵, leaving the clip) and waits for a running save first', async () => {
    const { c, st, ac, edit } = rig();
    edit(D([4]));
    expect(await ac.flush()).toBe(true);
    expect(st.saves).toEqual([D([4])]);
    expect(c.armed()).toBe(0);
    st.gate = () => undefined;
    edit(D([8]));
    await c.advance(1000);
    edit(D([8, 10]));
    const done = ac.flush();
    const open = st.gate;
    st.gate = null;
    open?.();
    expect(await done).toBe(true);
    expect(st.saves).toEqual([D([4]), D([8]), D([10])]);
    expect(await ac.flush()).toBe(true); // nothing left
  });

  it('not ready (less than a second would be left): no save until the edits change', async () => {
    const c = clock();
    let cur = D([1, 2, 3]);
    const saves: Drafts[] = [];
    const ac = new AutoCommit<Drafts>({ get: () => cur, empty: (v) => !Object.keys(v.words).length, key: draftsKey, delay: 100, timers: c.timers, ready: (v) => Object.keys(v.words).length < 3, commit: async (v) => (saves.push(v), (cur = D([])), true) });
    ac.changed();
    await c.advance(500);
    expect(saves).toEqual([]);
    expect(await ac.flush()).toBe(false);
    cur = D([1]);
    ac.changed();
    await c.advance(100);
    expect(saves).toEqual([D([1])]);
  });

  it('hold: no save mid-gesture; released -> saved after the quiet period', async () => {
    const { c, st, ac, edit } = rig();
    ac.hold(true);
    edit(D([5]));
    await c.advance(3000);
    expect(st.saves).toEqual([]);
    ac.hold(false);
    await c.advance(1000);
    expect(st.saves).toEqual([D([5])]);
  });
});

describe('drafts after a save', () => {
  it('subtractDrafts keeps what was deleted while the save ran', () => {
    expect(subtractDrafts(D([1, 2, 3], [7, 8]), D([1, 2], [7]))).toEqual(D([3], [8]));
    expect(subtractDrafts(D([1]), D([]))).toEqual(D([1]));
  });

  it('step committed: the saved drafts go and the local undo stack resets (⌘Z = the engine step now)', () => {
    const s0 = { cur: D([]), undo: [], redo: [] };
    const s1 = step(s0, { kind: 'set', next: D([1]) });
    const s2 = step(s1, { kind: 'set', next: D([1, 2]) });
    expect(s2.undo.length).toBe(2);
    const s3 = step(s2, { kind: 'committed', done: D([1]) });
    expect(s3).toEqual({ cur: D([2]), undo: [], redo: [] });
  });

  it('storeCommitted: an editor left mid-save cleans its stored drafts (a reopened clip never cuts twice)', () => {
    const m = new Map<string, string>();
    const store = { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
    store.setItem('k', JSON.stringify({ cur: D([1, 2]), undo: [D([1])], redo: [] }));
    storeCommitted('k', D([1]), store);
    expect(JSON.parse(m.get('k')!).cur).toEqual(D([2]));
    storeCommitted('k', D([2]), store);
    expect(m.has('k')).toBe(false);
  });

  it('draftsKey ignores order and the reason', () => {
    expect(draftsKey({ words: { 3: 'filler', 1: 'transcript' }, gaps: [5, 2] })).toBe(draftsKey({ words: { 1: 'x' as never, 3: 'y' as never }, gaps: [2, 5] }));
  });
});

describe('which AI changes still ask first', () => {
  const doc = { duration: 20, cuts: [], trim: null, speed: 1, words: [], effects: [] } as unknown as OutputDoc;
  it('plain changes apply at once', () => {
    expect(askFirstReason([{ op: 'effect_add', effect: 'vlog-grade', start: 0 }], doc)).toBeNull();
    expect(askFirstReason([{ op: 'speed', value: 1.1 }], doc)).toBeNull();
    expect(askFirstReason([{ op: 'cut', start: 2, end: 4 }], doc)).toBeNull();
  });
  it('starting over, dropping an export or removing most of the clip waits', () => {
    expect(askFirstReason([{ op: 'reset' }], doc)).toBe('reset');
    expect(askFirstReason([{ op: 'export_remove', target: '9:16' }], doc)).toBe('export-remove');
    expect(askFirstReason([{ op: 'trim', start: 0, end: 6 }], doc)).toBe('most-of-clip');
    expect(askFirstReason([{ op: 'cut', start: 1, end: 12 }], doc)).toBe('most-of-clip');
  });
});

describe('decisions the AI already made on a clip', () => {
  // 大家好今天我们讲一个方法 | 然后 | 来看第二个例子 (the engine's sentence around an unsure filler)
  const W = ['大家', '好', '今天', '我们', '讲', '一个', '方法，', '然后', '来', '看', '第二', '个', '例子'].map((w, i) => ({ w, t: i, te: i + 0.8 }));
  const ctx = { before: '大家好今天我们讲一个方法', after: '来看第二个例子也很重要' };
  it('finds a kept filler word by the words around it (punctuation and spaces ignored)', () => {
    expect(locateCut(W, '然后', ctx)).toEqual({ present: true, t: 7, te: 7.8, i0: 7, i1: 7 });
  });
  it('picks the occurrence whose context matches, not the first one', () => {
    const w2 = [{ w: '然后', t: 0, te: 0.5 }, ...W.map((x) => ({ ...x, t: x.t + 1, te: x.te + 1 }))];
    expect(locateCut(w2, '然后', ctx)?.t).toBe(8);
  });
  it('a cut word is gone: the joint of its context', () => {
    const cut = W.filter((x) => x.w !== '然后');
    expect(locateCut(cut, '然后', ctx)).toEqual({ present: false, t: 8, te: 8 });
  });
  it('not in this clip: null', () => {
    expect(locateCut(W, '其实', ctx)).toBeNull();
    expect(locateCut([], '然后', ctx)).toBeNull();
  });
  const o = (id: string, checked: boolean) => ({ id, text: id, checked }) as InboxOption;
  it('Undo / Cut it flips one option, the others stay as decided', () => {
    expect(flipAnswer([o('1', true), o('2', false), o('3', true)], '1')).toEqual({ approve: ['3'], keep: ['1', '2'] });
    expect(flipAnswer([o('1', true), o('2', false)], '2')).toEqual({ approve: ['1', '2'], keep: [] });
  });
  it('another opening, or none (-1)', () => {
    expect(pickAnswer([o('0', false), o('1', false)], '1')).toEqual({ approve: ['1'], keep: ['0'] });
    expect(pickAnswer([o('0', true)], null)).toEqual({ approve: ['-1'], keep: ['0'] });
  });
  it('only this clip\'s taste calls with options', () => {
    const d = (x: Partial<AutopilotDecision>) => ({ checkpoint: 'filler', item: 'talk', kind: 'filler-confirm', options: [o('3', false)], ...x }) as AutopilotDecision;
    const list = [d({}), d({ item: 'other' }), d({ checkpoint: 'cover', kind: 'cover-pick' }), d({ checkpoint: 'hook', kind: 'hook-pick' }), d({ asked: true }), d({ checkpoint: 'x', options: [] })];
    expect(clipDecisions(list, 'talk').map((x) => x.checkpoint)).toEqual(['filler', 'hook']);
  });
});

describe('Before / after of an applied change', () => {
  it('looks the live player cannot draw are rendered once; text, captions, cuts and speed are live', async () => {
    const { needsRenderedCompare } = await import('../../src/renderer/src/lib/chatEdit');
    expect(needsRenderedCompare([{ op: 'effect_add', effect: 'portrait-retouch', start: 0, params: { strength: 0.5 } }])).toBe(true);
    expect(needsRenderedCompare([{ op: 'effect_add', effect: 'vlog-grade', start: 0 }])).toBe(true);
    expect(needsRenderedCompare([{ op: 'effect_add', effect: 'pop-words', start: 1, params: { text: '底气' } }])).toBe(false);
    expect(needsRenderedCompare([{ op: 'cut', start: 1, end: 2 }, { op: 'speed', value: 1.1 }, { op: 'caption_style', style: { size: 1.2 } }])).toBe(false);
  });
});
