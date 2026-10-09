// The control room's model (lib/pipeline): an engine stage -> the pipeline step, each project's state (queued,
// running, needs you, ready, scheduled, out), the list groups (requests from Home first in Running while they plan),
// the decisions in plain words, and every new string in the three languages.
import { afterEach, describe, expect, it } from 'vitest';
import { LOCALES, setLang, t, tk } from '../../src/renderer/src/i18n';
import { autopilotEn, autopilotFr, autopilotZh } from '../../src/renderer/src/i18n/locales/autopilot';
import { decisionWords, hubGroups, itemPipeline, requestPipeline, stepOfStage, stepState, STEPS } from '../../src/renderer/src/lib/pipeline';
import type { HistoryItem } from '../../src/shared/v02';
import type { CalendarPost, OpenRequest } from '../../src/shared/v04';

const NOW = 1_800_000_000;
const item = (id: string, x: Partial<HistoryItem> = {}): HistoryItem => ({
  kind: 'project',
  id,
  dir: `/p/${id}`,
  name: id,
  recipe: 'talkinghead',
  client: null,
  created: NOW - 100,
  updated: NOW - 50,
  counts: { total: 2, green: 2, red: 0, approved: 2, done: 2, failed: 0 },
  status: 'in-progress',
  thumb: null,
  sources: ['engine'],
  opened: false,
  openable: true,
  ...x,
});
const running = (stage: string, progress = 0.4, eta = 120) => ({ state: 'running' as const, status: 'running', stage, progress, eta, needs_you: false, heartbeat: NOW });
const post = (item: string, state: CalendarPost['state']): CalendarPost => ({ id: `${item}-${state}`, item, clip: 'c1', title: 't', cover: null, platform: 'tiktok', at: '2026-10-10T20:00', state });
const req = (id: string, x: Partial<OpenRequest> = {}): OpenRequest => ({ id, state: 'running', mode: 'autopilot', inputs: [], prompt: 'cut it', started: NOW - 10, ...x });

describe('pipeline steps', () => {
  it('maps engine stage names onto the nine steps', () => {
    expect(stepOfStage('asr')).toBe('transcribe');
    expect(stepOfStage('cleanup')).toBe('cut');
    expect(stepOfStage('subs')).toBe('captions');
    expect(stepOfStage('compose')).toBe('render');
    expect(stepOfStage('export')).toBe('render');
    expect(stepOfStage('qc')).toBe('check');
    expect(stepOfStage('cp_publish')).toBe('check');
    expect(stepOfStage('copy')).toBe('copy');
    expect(stepOfStage('segment_plan')).toBe('plan');
    expect(stepOfStage('选段')).toBe('plan');
    expect(stepOfStage('')).toBeNull();
    expect(stepOfStage('mystery')).toBeNull();
  });

  it('a running project sits at its stage; earlier steps are done', () => {
    const p = itemPipeline(item('a', { live: running('subs') }));
    expect(p).toMatchObject({ state: 'run', current: 'captions', progress: 0.4, eta: 120 });
    expect(STEPS.map((s) => stepState(s, p))).toEqual(['done', 'done', 'done', 'current', 'todo', 'todo', 'todo', 'todo', 'todo']);
  });

  it('queued, needs you, ready, scheduled and out', () => {
    expect(itemPipeline(item('q', { queued: 2 })).state).toBe('queued');
    expect(itemPipeline(item('w', { live: { ...running('qc'), state: 'waiting', needs_you: true } })).state).toBe('you');
    expect(itemPipeline(item('d', { status: 'done' }), [], true).state).toBe('you'); // the Inbox holds a question
    const done = item('d', { status: 'done' });
    expect(itemPipeline(done).state).toBe('ready');
    expect(itemPipeline(done, [post('d', 'planned')]).state).toBe('scheduled');
    const out = itemPipeline(done, [post('d', 'posted')]);
    expect(out.state).toBe('out');
    expect(STEPS.every((s) => stepState(s, out) === 'done')).toBe(true);
    expect(itemPipeline(item('f', { failure: { state: 'failed', code: 'media', provider: null, error: '', at: NOW, stage: 'compose' } }))).toMatchObject({ state: 'failed', current: 'render' });
  });

  it('a request: planning, a plan waiting (ask me first), a failure', () => {
    expect(requestPipeline(req('r1', { progress: { stage: 'transcribe', done_s: 30, total_s: 60 } }))).toMatchObject({ state: 'planning', current: 'transcribe', progress: 0.5 });
    expect(requestPipeline(req('r2', { state: 'done', mode: 'ask' })).state).toBe('plan-ready');
    expect(requestPipeline(req('r3', { state: 'done', mode: 'autopilot' })).state).toBe('planning'); // being made into projects
    expect(requestPipeline(req('r4', { state: 'error' })).state).toBe('failed');
  });
});

describe('control room groups', () => {
  it('needs you / running (making, planning, queued) / ready / out / earlier', () => {
    const items = [
      item('run', { live: running('asr') }),
      item('queued', { queued: 1 }),
      item('you', { live: { ...running('qc'), state: 'waiting', needs_you: true } }),
      item('ready', { status: 'done' }),
      item('posted', { status: 'done' }),
      item('old', { status: 'done', updated: NOW - 40 * 86400 }),
    ];
    const g = hubGroups(items, [req('plan1'), req('ask1', { state: 'done', mode: 'ask' })], [post('posted', 'posted')], new Set(), NOW);
    expect(g.you.map((r) => r.id)).toEqual(['ask1', 'you']);
    expect(g.run.map((r) => r.id)).toEqual(['run', 'plan1', 'queued']);
    expect(g.ready.map((r) => r.id)).toEqual(['ready']);
    expect(g.out.map((r) => r.id)).toEqual(['posted']);
    expect(g.earlier.map((r) => r.id)).toEqual(['old']);
  });
});

describe('decisions in words', () => {
  afterEach(() => setLang('en'));
  it('says what was decided, per kind, in each language', () => {
    setLang('en');
    const w = decisionWords({ checkpoint: 'filler', item: 'c1', kind: 'filler-confirm', params: { cut: 3, kept: 1 } });
    expect(tk(w.key, w.params)).toBe('Cut 3 unsure filler words, kept 1');
    expect(tk(decisionWords({ checkpoint: 'hook', item: 'c1', kind: 'hook-pick', params: { pick: -1 } }).key)).toMatch(/No cold open/);
    expect(tk(decisionWords({ checkpoint: 'cover', item: 'c1', kind: 'cover-pick', params: { pick: 0 } }).key, { n: 1 })).toBe('Cover: frame 1');
    setLang('zh-CN');
    expect(tk(w.key, w.params)).toBe('剪掉 3 处拿不准的口癖，保留 1 处');
    setLang('fr');
    expect(t('ap.auto')).toBe('Pilote automatique');
  });

  it('every new string exists in en, zh-CN and fr', () => {
    for (const k of Object.keys(autopilotEn)) {
      expect(autopilotZh[k as keyof typeof autopilotEn]).toBeTruthy();
      expect(autopilotFr[k as keyof typeof autopilotEn]).toBeTruthy();
      for (const l of ['en', 'zh-CN', 'fr'] as const) expect(LOCALES[l].messages[k as keyof typeof autopilotEn]).toBeTruthy();
    }
  });
});

describe('publish cards open their clip', () => {
  it('the cover is a link to the clip page; a posted link shows only for a real http(s) address', async () => {
    const { createElement } = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');
    const { ClipThumbLink, PostLink } = await import('../../src/renderer/src/v4/kit');
    const { clipHref } = await import('../../src/renderer/src/lib/nav');
    const html = renderToStaticMarkup(createElement(ClipThumbLink, { href: clipHref('abcdefabcdef', 'clip 1'), src: null, label: 'Open the clip', testId: 'pc-open-clip' }));
    expect(html).toContain('href="#/p/abcdefabcdef/clip/clip%201"');
    expect(html).toContain('data-testid="pc-open-clip"');
    setLang('en');
    expect(renderToStaticMarkup(createElement(PostLink, { url: 'https://www.tiktok.com/@me/video/1' }))).toContain('View the post');
    expect(renderToStaticMarkup(createElement(PostLink, { url: 'javascript:alert(1)' }))).toBe('');
    expect(renderToStaticMarkup(createElement(PostLink, { url: null }))).toBe('');
  });
});
