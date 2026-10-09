// The chat-first editor's card logic (ux/CHAT_EDIT.md §5): card states derived from the clip's history, undo of an
// OLDER card = selective revert (never "undo everything after it"), the one primary button, markers, the empty-state
// suggestions from the clip, the slash menu, context, the cost line, the offline trigger; and the client calls.
import { describe, expect, it, vi } from 'vitest';
import type { ChatDoc, ChatTurn } from '../../src/shared/chatEdit';
import { EngineClient } from '../../src/shared/engineClient';
import type { OutputDoc } from '../../src/shared/v04';
import {
  cardFor,
  cardState,
  contextOf,
  costLine,
  keyWords,
  latestDraft,
  lengthChange,
  markers,
  needsRender,
  offlineFrom,
  pauses,
  primaryAction,
  slashCommand,
  slashMatches,
  suggestions,
  undoPlan,
  undoToCount,
} from '../../src/renderer/src/lib/chatEdit';

const words = [
  { w: '你在', t: 0, te: 0.5 },
  { w: '副业', t: 0.5, te: 1.0 },
  { w: '当中', t: 1.0, te: 1.4 },
  { w: '其实', t: 2.4, te: 2.8 },
  { w: '底气', t: 2.8, te: 3.3 },
  { w: '底气', t: 4.0, te: 4.4 },
];

function doc(over: Partial<OutputDoc> = {}): OutputDoc {
  return {
    id: 'A', item: 'abcdefabcdef', title: '副业给我的是底气', state: 'done', output_id: null, file: '/x.mp4', files: [{ path: '/x.mp4', aspect: '3:4' }], cover: null, post: null,
    duration: 10, fps: 30, mode: 'flattened', caps: { trim: true, cut: true, effects: true, cover: true, export: true }, caps_notes: [], words, waveform: [],
    captions: [{ id: 'c1', start: 0, end: 1.4, text: '你在副业当中' }, { id: 'c2', start: 2.4, end: 3.3, text: '其实底气' }], caption_style: {}, effects: [], trim: null, cuts: [], speed: 1,
    title_band: null, cover_edit: null, exports: [], steps: [], undo: 0, redo: 0, renders: [], warnings: [], engine: 'desk', ...over,
  } as OutputDoc;
}

const turn = (over: Partial<ChatTurn>): ChatTurn => ({ id: 't1-aa', role: 'ai', proposals: [], status: 'draft', ...over });
const steps = (...ids: string[]) => ({ steps: ids.map((id) => ({ id, describe: [] })) }) as Pick<ChatDoc, 'steps'>;

describe('card state comes from the history', () => {
  it('draft / applied / undone / reverted / discarded', () => {
    const d = { steps: [{ id: 's1', describe: [] }, { id: 's2', describe: [], reverted: true }] } as Pick<ChatDoc, 'steps'>;
    expect(cardState(turn({ status: 'draft' }), d)).toBe('draft');
    expect(cardState(turn({ status: 'applied', applied_step: 's1' }), d)).toBe('applied');
    expect(cardState(turn({ status: 'applied', applied_step: 's2' }), d)).toBe('reverted');
    expect(cardState(turn({ status: 'reverted', applied_step: 's2' }), d)).toBe('reverted');
    expect(cardState(turn({ status: 'applied', applied_step: 's9' }), d)).toBe('undone'); // ⌘Z elsewhere moved it
    expect(cardState(turn({ status: 'reverted', applied_step: 's1' }), d)).toBe('applied'); // the revert was undone
    expect(cardState(turn({ status: 'discarded' }), d)).toBe('discarded');
    expect(cardState(turn({ status: 'note', card: 'trim' }), d)).toBe('note');
  });
});

describe('undoing a card', () => {
  it('the newest step is a plain undo; an older one is reverted ON ITS OWN', () => {
    const d = steps('s1', 's2', 's3');
    expect(undoPlan(turn({ status: 'applied', applied_step: 's3' }), d)).toEqual({ kind: 'undo' });
    expect(undoPlan(turn({ status: 'applied', applied_step: 's1' }), d)).toEqual({ kind: 'revert', step: 's1' });
    expect(undoPlan(turn({ status: 'draft' }), d)).toEqual({ kind: 'none' });
  });
  it('「回到这一步」 counts the steps it takes back', () => {
    expect(undoToCount(steps('s1', 's2', 's3'), 's1')).toBe(3);
    expect(undoToCount(steps('s1', 's2', 's3'), 's3')).toBe(1);
    expect(undoToCount(steps('s1'), 'nope')).toBe(0);
  });
});

describe('one filled button', () => {
  it('apply when a draft exists, nothing while exporting, connect when offline, else export', () => {
    expect(primaryAction({ draft: true, exporting: false, offline: true })).toBe('apply');
    expect(primaryAction({ draft: true, exporting: true, offline: false })).toBe('none');
    expect(primaryAction({ draft: false, exporting: false, offline: true })).toBe('connect');
    expect(primaryAction({ draft: false, exporting: false, offline: false })).toBe('export');
  });
  it('the newest draft card is the one ⌘↵ applies', () => {
    const ts = [turn({ id: 'a', proposals: [{ id: 'p1', op: { op: 'speed', value: 1.1 } }] }), turn({ id: 'b', status: 'applied', applied_step: 's1' }), turn({ id: 'c', proposals: [{ id: 'p1', op: { op: 'speed', value: 1.2 } }] })];
    expect(latestDraft(ts, steps('s1'))).toBe('c');
    expect(latestDraft(ts.slice(0, 2), steps('s1'))).toBe('a');
    expect(latestDraft([], steps())).toBeNull();
  });
});

describe('timeline markers', () => {
  it('amber for draft ops (with their card), teal for applied cuts and effects; whole-clip effects are no place', () => {
    const d = doc({ cuts: [{ start: 1.4, end: 2.4, index: 0 }], effects: [{ id: 'fx1', effect: 'pop-words', start: 2.8, end: 4, params: {} }] });
    const m = markers(d, [{ turn: 't2', ops: [{ op: 'cut', start: 5, end: 6 }, { op: 'effect_add', effect: 'progress-bar-pil', start: 0, end: 10 }, { op: 'effect_add', effect: 'pop-words', start: 4, params: { text: '底气' } }] }]);
    expect(m.filter((x) => x.tone === 'applied').map((x) => x.kind)).toEqual(['cut', 'fx']);
    const dr = m.filter((x) => x.tone === 'draft');
    expect(dr.map((x) => [x.a, x.b, x.turn])).toEqual([[5, 6, 't2'], [4, 5.2, 't2']]);
  });
});

describe('the empty state is about THIS clip', () => {
  it('pauses, key words from the transcript (title first), a missing 9:16, the cover', () => {
    const s = suggestions(doc());
    expect(s.map((x) => x.kind)).toEqual(['pauses', 'pop', 'platform', 'cover']);
    expect(s[0]).toMatchObject({ kind: 'pauses', n: 2 });
    expect(s[1]).toMatchObject({ kind: 'pop' });
    expect((s[1] as { words: { w: string }[] }).words.map((w) => w.w)).toContain('底气');
    const done = suggestions(doc({ cuts: [{ start: 1.4, end: 2.4, index: 0 }, { start: 3.3, end: 4, index: 1 }], exports: [{ target: 'douyin:vertical' }], cover_edit: { t: 1 } }));
    expect(done.map((x) => x.kind)).toEqual(['pop']);
  });
  it('key words are real CJK words, no stop words, not already popped', () => {
    const w = keyWords(doc({ words: [...words, { w: 'Washington', t: 5, te: 6 }, { w: '其实', t: 6, te: 7 }], effects: [{ id: 'fx1', effect: 'pop-words', start: 0, end: 1, params: { text: '副业' } }] }));
    expect(w.map((x) => x.w)).toEqual(['当中', '底气']);
    expect(w.map((x) => x.w)).not.toContain('Washington');
    expect(w.map((x) => x.w)).not.toContain('副业');
    expect(pauses(words).map((p) => p.start)).toEqual([1.4, 3.3]);
  });
});

describe('slash menu and context', () => {
  it('matches either language; exact commands open a card without the model', () => {
    expect(slashMatches('/')).toEqual(['captions', 'effect', 'trim', 'cover', 'export']);
    expect(slashMatches('/c')).toEqual(['captions', 'cover']);
    expect(slashMatches('/字')).toEqual(['captions']);
    expect(slashMatches('紧凑一点')).toEqual([]);
    expect(slashCommand('/trim')).toBe('trim');
    expect(slashCommand(' /导出 ')).toBe('export');
    expect(slashCommand('/trim the start')).toBeNull();
    expect(cardFor({ op: 'cut', start: 1, end: 2 })).toBe('trim');
    expect(cardFor({ op: 'effect_update', id: 'fx1' })).toBe('effect');
    expect(cardFor({ op: 'caption_text', cue: 'c1', text: 'x' })).toBe('captions');
  });
  it('the selection and the open effect travel with the message', () => {
    expect(contextOf({ a: 2.4, b: 3.3 }, null, doc())).toEqual({ range: [2.4, 3.3], cues: ['c2'] });
    expect(contextOf(null, 'fx2', doc())).toEqual({ effect: 'fx2' });
    expect(contextOf(null, null, doc())).toBeNull();
  });
});

describe('reply details', () => {
  it('model · cost · seconds, and when the fallback card shows', () => {
    expect(costLine({ provider: 'claude-code', model: 'sonnet', cost_usd: 0.012, seconds: 5.6 }, (p) => (p === 'claude-code' ? 'Claude Code' : p))).toBe('Claude Code · sonnet · $0.01 · 6 s');
    expect(costLine({ provider: 'rules', model: null, cost_usd: 0, seconds: 0.2 }, () => 'Rules')).toBe('Rules · $0.00 · 1 s');
    expect(offlineFrom({ warnings: [{ code: 'no-model' }] })).toBe('no-model');
    expect(offlineFrom({ warnings: [{ code: 'llm-failed' }] })).toBe('llm-failed');
    expect(offlineFrom({ warnings: [{ code: 'no-pauses' }] })).toBeNull();
  });
  it('length before -> after, and which compares need a render', () => {
    const l = lengthChange(doc(), [{ op: 'cut', start: 1.4, end: 2.4 }, { op: 'speed', value: 2 }]);
    expect(l.before).toBe(10);
    expect(l.after).toBeCloseTo(4.5);
    expect(needsRender([{ op: 'effect_add', effect: 'pop-words', start: 1 }])).toBe(false);
    expect(needsRender([{ op: 'speed', value: 1.1 }])).toBe(true);
  });
});

describe('client calls of the chat editor', () => {
  const BASE = 'app://desk';
  const mk = () => vi.fn(async (_u: string, _i?: RequestInit) => new Response(JSON.stringify({ ok: true, turn: { id: 't1-ab' }, job: 'abcdef0123' }), { status: 200 }));
  it('revert one step, context, chat turns, export, applied-from-card', async () => {
    const f = mk();
    const c = new EngineClient(BASE, 'tok'.repeat(20), f);
    await c.revertOutput('abcdefabcdef', 'A_换圈子', 's1-abc');
    await c.askOutput('abcdefabcdef', 'A', 'cut this', { range: [1, 2] });
    await c.addChatTurn('abcdefabcdef', 'A', { role: 'user', text: '/trim', card: 'trim', status: 'note' });
    await c.updateChatTurn('abcdefabcdef', 'A', 't1-ab', { status: 'discarded' });
    await c.editOutput('abcdefabcdef', 'A', [{ op: 'speed', value: 1.1 }], 't1-ab');
    await c.exportOutput('abcdefabcdef', 'A', ['primary', 'douyin:vertical']);
    const calls = f.mock.calls.map(([u, i]) => [u.replace(BASE, ''), JSON.parse(String(i!.body))]);
    expect(calls[0]).toEqual([`/api/outputs/abcdefabcdef/${encodeURIComponent('A_换圈子')}/revert`, { step: 's1-abc' }]);
    expect(calls[1][1]).toEqual({ prompt: 'cut this', context: { range: [1, 2] } });
    expect(calls[2][1]).toEqual({ add: { role: 'user', text: '/trim', card: 'trim', status: 'note' } });
    expect(calls[3][1]).toEqual({ turn: 't1-ab', set: { status: 'discarded' } });
    expect(calls[4][1]).toEqual({ ops: [{ op: 'speed', value: 1.1 }], turn: 't1-ab' });
    expect(calls[5]).toEqual(['/api/outputs/abcdefabcdef/A/export', { targets: ['primary', 'douyin:vertical'] }]);
  });
});
