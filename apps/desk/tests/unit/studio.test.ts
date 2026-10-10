// The Studio list model (lib/studio): one row per video across projects, grouped needs you / in progress / ready /
// scheduled; a question about a clip lands on that clip, one about the project on the project's own row.
import { describe, expect, it } from 'vitest';
import { grouped, needsYou, studioRows, visible } from '../../src/renderer/src/lib/studio';
import type { HistoryItem } from '../../src/shared/v02';
import type { CalendarPost, Clip, InboxItem, OpenRequest } from '../../src/shared/v04';

const NOW = 1_800_000_000;
const item = (id: string, x: Partial<HistoryItem> = {}): HistoryItem => ({
  kind: 'project',
  id,
  dir: `/p/${id}`,
  name: `Project ${id}`,
  recipe: 'talkinghead',
  client: null,
  created: NOW - 100,
  updated: NOW - 50,
  counts: { total: 3, green: 3, red: 0, approved: 3, done: 3, failed: 0 },
  status: 'done',
  thumb: null,
  sources: ['engine'],
  opened: false,
  openable: true,
  ...x,
});
const clip = (id: string, x: Partial<Clip> = {}): Clip => ({ id, title: `Clip ${id}`, state: 'done', files: [{ path: `/v/${id}.mp4`, aspect: '9:16' }], cover: null, post: null, duration: 20, ...x });
const post = (item: string, c: string, state: CalendarPost['state'], at = '2026-10-12T19:00'): CalendarPost => ({ id: `${item}-${c}-${state}`, item, clip: c, title: 't', cover: null, platform: 'youtube', at, state });
const ask = (key: string, project: string, clipId: string | null): InboxItem => ({ key, kind: 'confirm', group: 'choose', project: { id: project, name: project }, code: null, params: {}, text: null, options: clipId ? [{ id: '1', text: '', clip_id: clipId }] : [], source: 'engine' });
const req = (id: string, x: Partial<OpenRequest> = {}): OpenRequest => ({ id, state: 'running', mode: 'autopilot', inputs: [], prompt: 'cut it', started: NOW - 10, ...x });

describe('studio rows', () => {
  const items = [item('aaaaaaaaaaaa'), item('bbbbbbbbbbbb', { status: 'in-progress', live: { state: 'running', status: 'running', stage: 'export', progress: 0.5, eta: 240, needs_you: false, heartbeat: NOW } })];
  const clips = {
    aaaaaaaaaaaa: [clip('a1'), clip('a2'), clip('a3')],
    bbbbbbbbbbbb: undefined,
  };
  const posts = [post('aaaaaaaaaaaa', 'a2', 'planned'), post('aaaaaaaaaaaa', 'a3', 'posted', '2026-10-01T19:00')];
  const inbox = [ask('k1', 'aaaaaaaaaaaa', 'a1')];
  const rows = studioRows(items, [req('rrrrrrrrrrrr')], clips, posts, inbox, NOW);

  it('one row per clip; a project without clips yet (or a request) is one row', () => {
    expect(rows.map((r) => r.key).sort()).toEqual(['aaaaaaaaaaaa/a1', 'aaaaaaaaaaaa/a2', 'aaaaaaaaaaaa/a3', 'p:bbbbbbbbbbbb', 'r:rrrrrrrrrrrr']);
    expect(rows.find((r) => r.key === 'aaaaaaaaaaaa/a2')!.pos).toEqual([2, 3]);
  });

  it('groups: the asked clip needs her, running work is in progress, scheduled and posted ones are scheduled', () => {
    const g = grouped(rows);
    expect(g.you.map((r) => r.key)).toEqual(['aaaaaaaaaaaa/a1']);
    expect(g.you[0].ask?.key).toBe('k1');
    expect(g.run.map((r) => r.key)).toEqual(['p:bbbbbbbbbbbb', 'r:rrrrrrrrrrrr']); // making first, then planning
    expect(g.run[0].p.eta).toBe(240);
    expect(g.ready.map((r) => r.key)).toEqual([]);
    expect(g.scheduled.map((r) => [r.key, r.posted])).toEqual([
      ['aaaaaaaaaaaa/a2', false],
      ['aaaaaaaaaaaa/a3', true],
    ]);
    expect(needsYou(rows)).toBe(1);
    expect(visible(rows, 'all').map((r) => r.group)).toEqual(['you', 'run', 'run', 'scheduled', 'scheduled']);
  });

  it('a question about the whole project is a row of its own; old finished work stays out', () => {
    const r2 = studioRows([item('aaaaaaaaaaaa'), item('cccccccccccc', { updated: NOW - 30 * 86400 })], [], { aaaaaaaaaaaa: [clip('a1')], cccccccccccc: [clip('c1')] }, [], [ask('k2', 'aaaaaaaaaaaa', null)], NOW);
    expect(r2.map((r) => [r.key, r.group])).toEqual([
      ['p:aaaaaaaaaaaa', 'you'],
      ['aaaaaaaaaaaa/a1', 'ready'],
    ]);
  });
});
