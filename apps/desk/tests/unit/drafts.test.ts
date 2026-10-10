// The Inbox's draft review in words (lib/inboxView): her clicks on the keep-spans transcript become exactly the KEEP
// spans the engine writes (same merge rule as vstudio.project.adapters.promo), the summaries read in her language,
// a plan's error in plain words, and a request waiting for her files sits in "Needs you".
import { afterEach, describe, expect, it } from 'vitest';
import type { DraftSegment, OpenRequest } from '../../src/shared/v04';
import { setLang } from '../../src/renderer/src/i18n';
import { draftSummary, keptChanged, keptOf, keptSeconds, keptSpans, mmss } from '../../src/renderer/src/lib/inboxView';
import { hubGroups, requestPipeline } from '../../src/renderer/src/lib/pipeline';
import { plainError } from '../../src/renderer/src/v4/PlanCard';

afterEach(() => setLang('en'));

const segs: DraftSegment[] = [
  { i: 1, t: 0.4, te: 1.6, text: '大家好嗯。', keep: false, label: '没讲完的开场' },
  { i: 2, t: 1.8, te: 4.0, text: '今天讲可灵。', keep: true },
  { i: 3, t: 4.3, te: 6.0, text: '顺便说一下Hedra。', keep: false, label: 'Hedra 那段' },
  { i: 4, t: 6.2, te: 7.4, text: '最后总结一下。', keep: true },
];

describe('keep spans from her clicks', () => {
  it('the AI draft as it is, her toggles on top', () => {
    expect([...keptOf(segs, null)]).toEqual([2, 4]);
    expect(keptChanged(segs, null)).toBe(false);
    const mine = { 3: true };
    expect([...keptOf(segs, mine)]).toEqual([2, 3, 4]);
    expect(keptChanged(segs, mine)).toBe(true);
    expect(keptChanged(segs, { 2: true })).toBe(false); // the same as the AI's
  });
  it('kept neighbours merge into one span (< 0.8 s apart), padded 50 ms like the engine', () => {
    expect(keptSpans(segs, keptOf(segs, null))).toEqual([[1.75, 4.05], [6.15, 7.45]]);
    expect(keptSpans(segs, keptOf(segs, { 3: true }))).toEqual([[1.75, 7.45]]);
    expect(keptSeconds(segs, keptOf(segs, null))).toBeCloseTo(3.4);
  });
  it('summaries in her language: lengths as m:ss, cut labels listed', () => {
    expect(mmss(580)).toBe('9:40');
    const m = { code: 'draft.keep', params: { kept: 580, total: 764, cuts: ['the unfinished opening', 'the Hedra part'] } };
    expect(draftSummary(m)).toBe('Keeps 9:40 of 12:44 — cuts the unfinished opening, the Hedra part');
    expect(draftSummary({ code: 'draft.pkg.pip', params: { n: 2, of: 3, at: [80, 245] } })).toBe('Screen recordings full screen with you small in the corner: 2 of 3');
    expect(draftSummary({ code: 'draft.kv', params: { label: 'Product', value: 'Inkwell' } })).toBe('Product: Inkwell');
    setLang('fr');
    expect(draftSummary(m)).toBe('Garde 9:40 sur 12:44 — coupe the unfinished opening et the Hedra part');
    setLang('zh-CN');
    expect(draftSummary({ code: 'draft.keep-all', params: { total: 764 } })).toBe('全部保留（12:44）——AI 没找到要剪的');
  });
});

describe('requests from Home', () => {
  it("a plan's error in words she can read: no CLI prefix, no exception class, no paths", () => {
    expect(plainError('vstudio.intake plan exited 1: PlanError: no inputs (files / folders) given')).toBe('no inputs (files / folders) given');
    expect(plainError('vstudio.intake plan exited 1: TimeoutError: claude-code: timed out after 235 s')).toBe('claude-code: timed out after 235 s');
    expect(plainError('could not open /Users/me/Downloads/a.mp4')).toBe('could not open …');
  });
  it('one waiting for her files is in Needs you, not Running', () => {
    const r: OpenRequest = { id: 'abcdefabcdef', state: 'needs', mode: 'autopilot', inputs: [], needs: [{ code: 'intake.need.footage' }] };
    expect(requestPipeline(r).state).toBe('you');
    const g = hubGroups([], [r], [], new Set());
    expect(g.you.map((x) => x.id)).toEqual(['abcdefabcdef']);
    expect(g.run).toEqual([]);
  });
});
