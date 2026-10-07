// ux-core renderer logic: the editor split (presets, min sizes, saved layout + the old ce.chatW), pending transcript
// cuts (toggle / restore, runs, ops by word index with the words signature, pauses, undo stack), paragraphs and the
// word at a time, kept ranges -> the player's skip list, applied cuts -> markers, caption-only fixes, the links of
// the object model (project › clip › post), the triage queue order, ⌘[ / ⌘], Home's ideas and the Inbox's words.
import { describe, expect, it } from 'vitest';
import type { HistoryItem } from '../../src/shared/v02';
import type { InboxItem, Word } from '../../src/shared/v04';
import { setLang } from '../../src/renderer/src/i18n';
import { homeIdeas } from '../../src/renderer/src/lib/homeIdeas';
import { answerOf, inboxSub, inboxTitle, optionLabel, secsLabel } from '../../src/renderer/src/lib/inboxView';
import { backForwardKey, clipHref, inboxHref, itemTarget, postHref } from '../../src/renderer/src/lib/nav';
import { parseRoute, routeQuery } from '../../src/renderer/src/lib/router';
import { loadDrafts, step } from '../../src/renderer/src/lib/textCuts';
import {
  addGaps,
  addWords,
  appliedRuns,
  defaultTab,
  draftCount,
  draftOps,
  draftSpans,
  EMPTY_DRAFTS,
  fixInCue,
  joinWords,
  keepToCuts,
  keptSeconds,
  paragraphs,
  segments,
  selectionInfo,
  spaceBefore,
  textLang,
  wordsText,
  toggleGap,
  toggleRange,
  wordIndexAt,
  wordRuns,
} from '../../src/renderer/src/lib/transcript';
import { clampChat, clampStage, DEFAULT_LAYOUT, loadLayout, presetOf, PRESETS, saveLayout } from '../../src/renderer/src/lib/useSplit';

const W: Word[] = [
  { w: '去给', t: 0.0, te: 0.4 },
  { w: 'Lakeside', t: 0.45, te: 0.9 },
  { w: 'City', t: 0.92, te: 1.0 },
  { w: 'College，', t: 1.02, te: 1.6 },
  { w: '那个', t: 1.7, te: 2.0 },
  { w: '宣讲', t: 3.1, te: 3.5 },
  { w: '的时候。', t: 3.5, te: 4.0 },
  { w: '我', t: 6.0, te: 6.2 },
];

function store(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
}

describe('the editor split (useSplit)', () => {
  it('keeps both panes usable and knows its presets', () => {
    expect(PRESETS).toEqual({ watch: 0.7, balanced: 0.5, edit: 0.34 });
    expect(clampStage(0.95, 1000)).toBeCloseTo(0.82, 2); // lower pane >= 180 px
    expect(clampStage(0.05, 1000)).toBeCloseTo(0.24, 2); // player >= 240 px
    expect(clampStage(0.5, 1000)).toBe(0.5);
    expect(presetOf(0.341)).toBe('edit');
    expect(presetOf(0.6)).toBeNull();
    expect(clampChat(200)).toBe(320);
    expect(clampChat(900)).toBe(560);
  });
  it('saves the layout and reads the old chat width once', () => {
    const s = store({ 'ce.chatW': '470' });
    const l = loadLayout(s);
    expect(l).toEqual({ ...DEFAULT_LAYOUT, chatW: 470 });
    saveLayout({ ...l, stage: 0.34, preset: 'edit', tab: 'timeline', chatCollapsed: true }, s);
    expect(loadLayout(s)).toEqual({ stage: 0.34, preset: 'edit', tab: 'timeline', chatW: 470, chatCollapsed: true });
    expect(loadLayout(store({ 'ce.layout': '{bad json', 'ce.chatW': '9999' })).chatW).toBe(560);
    expect(loadLayout(store({ 'ce.layout': JSON.stringify({ tab: 'nope', stage: 7 }) }))).toMatchObject({ tab: null, stage: 0.85 });
  });
});

describe('pending transcript cuts', () => {
  it('Delete marks whole words; Delete on pending words restores them', () => {
    let d = toggleRange(EMPTY_DRAFTS, 3, 1);
    expect(Object.keys(d.words).map(Number)).toEqual([1, 2, 3]);
    d = toggleRange(d, 2, 2); // all pending -> restored
    expect(Object.keys(d.words).map(Number)).toEqual([1, 3]);
    d = toggleRange(d, 1, 3); // mixed -> all pending again
    expect(wordRuns(d)).toEqual([[1, 3, 'transcript']]);
    d = addWords(d, [4], 'filler');
    expect(wordRuns(d)).toEqual([[1, 4, 'transcript']]); // a run is a filler run only when every word is
    expect(wordRuns(addWords(EMPTY_DRAFTS, [4], 'filler'))).toEqual([[4, 4, 'filler']]);
  });
  it('becomes one set of ops by word index (+ the words signature), pauses tightened to 0.25 s', () => {
    let d = toggleRange(EMPTY_DRAFTS, 1, 3);
    d = toggleGap(d, 4); // the 1.1 s pause after 那个
    const ops = draftOps(W, d, 'abc123');
    expect(ops).toEqual([
      { op: 'cut', start: 0.42, end: 1.63, words: [1, 3], why: 'transcript', sig: 'abc123' },
      { op: 'cut', start: 2.125, end: 2.975, gap: 4, keep: 0.25, why: 'pause', sig: 'abc123' },
    ]);
    expect(draftCount(d)).toBe(2);
    expect(draftSpans(W, d).map(([a, b]) => Math.round((b - a) * 100) / 100)).toEqual([1.21, 0.85]);
    // a pause inside a run of cut words is not a separate cut
    const both = addGaps(toggleRange(EMPTY_DRAFTS, 4, 5), [4]);
    expect(draftOps(W, both).map((o) => (o as { why: string }).why)).toEqual(['transcript']);
    expect(draftCount(both)).toBe(1);
  });
  it('has its own undo stack (⌘Z before the engine), kept per clip', () => {
    let s = loadDrafts('x', store());
    s = step(s, { kind: 'set', next: toggleRange(s.cur, 0, 0) });
    s = step(s, { kind: 'set', next: toggleRange(s.cur, 5, 6) });
    expect(Object.keys(s.cur.words)).toEqual(['0', '5', '6']);
    s = step(s, { kind: 'undo' });
    expect(Object.keys(s.cur.words)).toEqual(['0']);
    s = step(s, { kind: 'redo' });
    expect(Object.keys(s.cur.words)).toEqual(['0', '5', '6']);
    expect(step(s, { kind: 'set', next: s.cur })).toBe(s); // no-op sets are not undo steps
    s = step(s, { kind: 'clear' });
    expect(s).toEqual({ cur: EMPTY_DRAFTS, undo: [], redo: [] });
    const st = store({ 'ce.drafts.a/b': JSON.stringify({ cur: { words: { 2: 'filler' }, gaps: [1] }, undo: [], redo: [] }) });
    expect(loadDrafts('ce.drafts.a/b', st).cur).toEqual({ words: { 2: 'filler' }, gaps: [1] });
    expect(loadDrafts('ce.drafts.a/b', store({ 'ce.drafts.a/b': '{' })).cur).toEqual(EMPTY_DRAFTS);
  });
});

describe('the transcript', () => {
  it('paragraphs after a long pause, the word at a time, spacing, selection', () => {
    expect(paragraphs(W).map((p) => [p.i0, p.i1])).toEqual([
      [0, 6],
      [7, 7],
    ]);
    expect(wordIndexAt(W, -1)).toBe(-1);
    expect(wordIndexAt(W, 0.95)).toBe(2);
    expect(wordIndexAt(W, 5)).toBe(6);
    expect(spaceBefore(W[0], W[1])).toBe(false); // 去给Lakeside (Chinese + English run together)
    expect(spaceBefore(W[1], W[2])).toBe(true);
    expect(joinWords(W, 0, 3)).toBe('去给Lakeside City College，');
  });
  it('keeps a space after Latin punctuation, never in Chinese', () => {
    const w = (x: string, t: number) => ({ w: x, t, te: t + 0.2 });
    const en = ['Thanks', 'for', 'the', 'posts.', 'Hi,', 'everyone!', '"Really"', 'works.', '(see', 'it)'].map(w);
    expect(joinWords(en, 0, en.length - 1)).toBe('Thanks for the posts. Hi, everyone! "Really" works. (see it)');
    const zh = ['我们', '今天', '讲', 'RAG，', '然后', '你好。', '再见'].map(w);
    expect(joinWords(zh, 0, zh.length - 1)).toBe('我们今天讲RAG，然后你好。再见');
    expect(joinWords(['3.', '5', 'x'].map(w), 0, 2)).toBe('3.5 x');
    expect(wordsText(en.slice(3, 5))).toBe('posts. Hi,');
    expect(selectionInfo(W, 3, 1)).toEqual({ n: 3, secs: 1.6 - 0.45 });
  });
  it('tags English words en and Chinese words zh-CN, so English is not set as Chinese text', () => {
    expect(['posts.', 'Hi', 'basically,', '"Really"', '3.5'].map(textLang)).toEqual(['en', 'en', 'en', 'en', 'en']);
    expect(['我们', 'RAG，', '你好。', 'カメラ', '「好」'].map(textLang)).toEqual(['zh-CN', 'zh-CN', 'zh-CN', 'zh-CN', 'zh-CN']);
    expect(textLang(null)).toBe('en');
  });
  it('kept ranges <-> what the player skips; applied cuts collapse to a marker', () => {
    const keep = segments(10, [
      { start: 2, end: 3 },
      { start: 2.5, end: 4 },
    ]);
    expect(keep).toEqual([
      [0, 2],
      [4, 10],
    ]);
    expect(keptSeconds(keep)).toBe(8);
    expect(keepToCuts(keep, 10)).toEqual([{ start: 2, end: 4 }]);
    expect(keepToCuts([[1, 9]], 10)).toEqual([
      { start: 0, end: 1 },
      { start: 9, end: 10 },
    ]);
    const runs = appliedRuns(W, [{ start: 0.42, end: 1.63, index: 0 }]);
    expect([...runs.values()].map((r) => [r.i0, r.i1])).toEqual([[1, 3]]);
  });
  it('fixes one word inside its caption line only', () => {
    expect(fixInCue('可能都是疏图同归的', '疏图同归', '殊途同归')).toBe('可能都是殊途同归的');
    expect(fixInCue('别的字幕', '疏图', '殊途')).toBeNull();
  });
  it('opens talking-head clips on the transcript', () => {
    expect(defaultTab({ words: W, duration: 6.5 })).toBe('transcript');
    expect(defaultTab({ words: W.slice(0, 2), duration: 60 })).toBe('timeline');
    expect(defaultTab({ words: [], duration: 30 })).toBe('timeline');
  });
});

const ID = '0123456789ab';
const confirm: InboxItem = {
  key: 'k1',
  kind: 'confirm',
  group: 'choose',
  project: { id: ID, name: 'fuye' },
  code: 'inbox.confirmEdits',
  params: { n: 2 },
  text: null,
  source: 'picks',
  minutes: 1,
  options: [
    { id: 'o0', clip: 'B', clip_id: 'B_自媒体', clip_title: '再小的博主', text: '**B** drops 「还有一个点就是」', label: { code: 'inbox.opt.dropLine', message: 'Drops a filler line' }, secs: -1.6, approx: true, at: 0.5, checked: true },
    {
      id: 'o1',
      clip: 'D',
      text: 'D starts at …',
      label: { code: 'inbox.opt.opener', message: 'Which opening?' },
      choices: [
        { id: 'softer', label: { code: 'inbox.choice.softer', message: 'Keep softer opener' }, secs: 45.6, recommended: true },
        { id: 'stronger', label: { code: 'inbox.choice.stronger', message: 'Use stronger opener' }, secs: 43 },
      ],
      choice: 'softer',
      checked: true,
    },
  ],
};

describe('how the pages connect', () => {
  it('one link per object: project › clip (with the moment) › post; the Inbox item', () => {
    expect(clipHref(ID, 'B_自媒体', { t: 0.5, item: 'k1', triage: true })).toBe(`#/p/${ID}/clip/B_%E8%87%AA%E5%AA%92%E4%BD%93?t=0.5&item=k1&triage=1`);
    expect(parseRoute(clipHref(ID, 'B_自媒体', { t: 2 }))).toEqual({ name: 'clip', id: ID, clip: 'B_自媒体' });
    expect(routeQuery(clipHref(ID, 'B', { t: 2.345, item: 'k1' }))).toEqual({ t: '2.35', item: 'k1' });
    expect(parseRoute(postHref('p1'))).toEqual({ name: 'calendar' });
    expect(inboxHref({ item: 'k1' })).toBe('#/inbox?item=k1');
    expect(itemTarget(confirm)).toBe(clipHref(ID, 'B_自媒体', { t: 0.5, item: 'k1' }));
    expect(itemTarget({ ...confirm, options: [], kind: 'review', jobs: ['ep02'] }, true)).toBe('#/inbox?item=k1&triage=1');
  });
  it('⌘[ / ⌘] are back / forward, nothing else', () => {
    expect(backForwardKey({ metaKey: true, ctrlKey: false, altKey: false, shiftKey: false, key: '[' })).toBe(-1);
    expect(backForwardKey({ metaKey: false, ctrlKey: true, altKey: false, shiftKey: false, key: ']' })).toBe(1);
    expect(backForwardKey({ metaKey: true, ctrlKey: false, altKey: false, shiftKey: true, key: '[' })).toBe(0);
    expect(backForwardKey({ metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, key: '[' })).toBe(0);
  });
});

describe('Home ideas and the Inbox in words', () => {
  const item = (o: Partial<HistoryItem>): HistoryItem =>
    ({ kind: 'project', id: o.id ?? 'x', dir: '/x', name: 'x', recipe: null, client: null, created: 0, updated: 0, counts: { total: 0, green: 0, red: 0, approved: 0, done: 0, failed: 0 }, status: 'done', thumb: null, sources: ['desk'], opened: false, openable: true, ...o }) as HistoryItem;
  it('ideas come from her own work first', () => {
    setLang('en');
    const ideas = homeIdeas(
      [item({ id: 'a', name: 'AI short', type: 'aigc', counts: { total: 5, green: 5, red: 0, approved: 5, done: 5, failed: 0 } }), item({ id: 'b', name: 'fuye', counts: { total: 4, green: 2, red: 0, approved: 2, done: 2, failed: 0 } })],
      [{ prompt: 'cut live-1006 into clips' }],
    );
    expect(ideas.map((x) => [x.kind, x.label, x.sub])).toEqual([
      ['series', 'Next AI short', 'episode 6'],
      ['finish', 'Finish fuye', '2 clips left'],
      ['recent', 'cut live-1006 into clips', 'again'],
    ]);
    expect(homeIdeas([], []).map((x) => x.kind)).toEqual(['idea', 'idea', 'idea']);
  });
  it('plain words, plain answers', () => {
    setLang('en');
    expect(inboxTitle(confirm)).toBe('Confirm 2 edits');
    expect(inboxSub(confirm)).toBe('across 2 clips');
    expect(optionLabel(confirm.options![0])).toBe('Drops a filler line');
    expect(secsLabel(confirm.options![0])).toBe('−2 s');
    expect(inboxTitle({ ...confirm, kind: 'budget-approval', code: 'inbox.spend', params: { amount: 18, currency: 'CNY', n: 12 } })).toMatch(/^OK to spend (CN)?¥18(\.00)? on AI shots\?$/);
    expect(answerOf(confirm, new Set(['o1']), {})).toEqual({ approve: ['o1'], keep: ['o0'], choices: { o1: 'softer' } });
    expect(answerOf(confirm, undefined, { o1: 'stronger' })).toEqual({ approve: ['o0', 'o1'], keep: [], choices: { o1: 'stronger' } });
    setLang('zh-CN');
    expect(optionLabel(confirm.options![0])).toBe('删掉一句口头禅');
    expect(inboxTitle(confirm)).toMatch(/2/);
    setLang('en');
  });
});
