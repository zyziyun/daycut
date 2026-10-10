// Orca-style attention (2026-10 review step 8): the Dock badge = the Studio's Needs you count; a notification when a
// video starts waiting for her opens that video with its question; one when a run finishes opens its first clip.
import { afterEach, describe, expect, it } from 'vitest';
import { setLang } from '../../src/renderer/src/i18n';
import { needsYou, studioRows } from '../../src/renderer/src/lib/studio';
import { attentionChanges } from '../../src/renderer/src/lib/attention';
import { setStudioPrefs } from '../../src/renderer/src/lib/studioFlag';
import type { HistoryItem } from '../../src/shared/v02';
import type { Clip, InboxItem } from '../../src/shared/v04';

const NOW = 1_800_000_000;
const P = 'aaaaaaaaaaaa';
const item = (x: Partial<HistoryItem> = {}): HistoryItem => ({ kind: 'project', id: P, dir: `/p/${P}`, name: 'Talk', recipe: 'talkinghead', client: null, created: NOW - 100, updated: NOW - 50, counts: { total: 2, green: 2, red: 0, approved: 2, done: 2, failed: 0 }, status: 'done', thumb: null, sources: ['engine'], opened: false, openable: true, ...x });
const clip = (id: string, x: Partial<Clip> = {}): Clip => ({ id, title: `Clip ${id}`, state: 'done', files: [{ path: `/v/${id}.mp4`, aspect: '9:16' }], cover: null, post: null, duration: 20, ...x });
const ask = (key: string, c: string): InboxItem => ({ key, kind: 'filler-confirm', group: 'choose', project: { id: P, name: 'Talk' }, code: null, params: {}, text: 'Cut “然后”', options: [{ id: '1', text: '', clip_id: c }], source: 'engine' });
const running = { state: 'running' as const, status: 'running', stage: 'export', progress: 0.5, eta: 60, needs_you: false, heartbeat: NOW };

describe('attention', () => {
  afterEach(() => (setLang('en'), setStudioPrefs({ studio: false })));

  it('a new question: one notification that opens that clip with the question pinned; the badge counts it', () => {
    setStudioPrefs({ studio: true });
    const before = studioRows([item()], [], { [P]: [clip('c1'), clip('c2')] }, [], [], NOW);
    const after = studioRows([item()], [], { [P]: [clip('c1'), clip('c2')] }, [], [ask('q1', 'c2')], NOW);
    const n = attentionChanges(before, after);
    expect(n).toHaveLength(1);
    expect(n[0].route).toBe(`#/studio/${P}/c2?item=q1`);
    expect(n[0].title).toContain('Clip c2');
    expect(needsYou(after)).toBe(1);
    expect(attentionChanges(after, after)).toEqual([]); // told once
    expect(attentionChanges(null, after)).toEqual([]); // nothing on the first look
  });

  it('a run that finishes: one notification that opens its first made clip', () => {
    setStudioPrefs({ studio: true });
    const before = studioRows([item({ status: 'in-progress', live: running })], [], { [P]: undefined }, [], [], NOW);
    const after = studioRows([item()], [], { [P]: [clip('c1'), clip('c2')] }, [], [], NOW);
    const n = attentionChanges(before, after);
    expect(n.map((x) => x.route)).toEqual([`#/studio/${P}/c1`]);
    expect(n[0].body).toBe('2 videos are ready to look at.');
  });
});
