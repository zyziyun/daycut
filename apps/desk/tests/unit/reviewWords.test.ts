// The 2026-10 review: the engine's own words on screen ("0/1 jobs", "done: 3 jobs", "checkpoint: publish · 步骤：
// s003:export · 100% · no update for 4 min", 「asr」, "第 reelfold-main 条", "Xiaohongshu · vertical") - the desk words
// them itself, from the codes the engine sidecar derives (desk_engine/common.live_words).
import { afterEach, describe, expect, it } from 'vitest';
import type { HistoryItem, LiveStatus } from '../../src/shared/v02';
import type { InboxItem } from '../../src/shared/v04';
import { setLang } from '../../src/renderer/src/i18n';
import { inboxClip, inboxSub, optionLabel } from '../../src/renderer/src/lib/inboxView';
import { clipWords, liveLine, liveMeta, liveText } from '../../src/renderer/src/lib/liveStatus';
import { itemPipeline, stepOfLive, stepOfStage } from '../../src/renderer/src/lib/pipeline';
import { feedLine } from '../../src/renderer/src/v4/ProgressFeed';
import { clipStatus } from '../../src/renderer/src/lib/status';

afterEach(() => setLang('en'));
const now = 1_800_000_000;
const live = (o: Partial<LiveStatus>): LiveStatus => ({ state: 'running', status: 'running', needs_you: false, heartbeat: now - 5, ...o });

describe('the step a run is at comes from the stages running now', () => {
  it('reads the batch runner’s "s003:export" and takes the least advanced clip', () => {
    expect(stepOfStage('s003:export')).toBe('render');
    expect(stepOfStage('s001:asr, s002:cleanup')).toBe('transcribe');
    expect(stepOfStage('reelfold-main:compose')).toBe('render');
    expect(stepOfStage('cp_cover-pick')).toBe('render');
    expect(stepOfStage('cp_filler-confirm')).toBe('cut');
    expect(stepOfLive({ stages: [{ job: 's001', stage: 'export' }, { job: 's002', stage: 'cleanup' }] })).toBe('cut');
    expect(stepOfStage('')).toBeNull();
  });
});

describe('the status line in words', () => {
  it('"0/1 jobs" reads "Clip 1 of 1"; finished and waiting read as sentences', () => {
    expect(liveText(live({ code: 'jobs', params: { done: 0, total: 3 } }))).toBe('Clip 1 of 3');
    expect(liveText(live({ state: 'done', code: 'finished', params: { n: 3 } }))).toBe('3 clips made');
    expect(liveText(live({ state: 'waiting', code: 'checkpoint', params: { kinds: ['publish'] } }))).toBe('Waiting for you: Review before publishing');
    setLang('zh-CN');
    expect(liveText(live({ code: 'jobs', params: { done: 1, total: 3 } }))).toBe('第 2/3 条');
    expect(liveText(live({ state: 'waiting', code: 'checkpoint', params: { kinds: ['publish'] } }))).toBe('等你：发布前看一眼');
    expect(liveText(live({ message: '在渲染宣传片' }))).toBe('在渲染宣传片'); // an agent's own words stay
  });
  it('waiting shows no step, no 100 % and no "no update for …"', () => {
    const l = liveLine(live({ state: 'waiting', code: 'checkpoint', params: { kinds: ['publish'] }, stage: 's003:export', progress: 1, heartbeat: now - 600 }), now)!;
    expect(l).toMatchObject({ stage: '', pct: null, age: null, stale: false });
    expect(liveMeta(l)).toBe('');
    const r = liveLine(live({ code: 'jobs', params: { done: 0, total: 1 }, stage: 's001:asr', progress: 0.2 }), now)!;
    expect([r.message, liveMeta(r)]).toEqual(['Clip 1 of 1', 'Step: Transcribe · 20% · updated 5 s ago']);
  });
});

describe('clips are named, never by their job id', () => {
  const clips = [
    { id: 'reelfold-main', title: 'One recording, a week of posts' },
    { id: 's002', title: 's002' },
  ];
  it('the AI’s decisions name the clip by its title, else its place', () => {
    expect(clipWords('reelfold-main', clips)).toBe('“One recording, a week of posts”');
    expect(clipWords('s002', clips)).toBe('clip 2');
    expect(clipWords('*', clips)).toBeNull();
    setLang('zh-CN');
    expect(clipWords('s002', clips)).toBe('第 2 条');
  });
  it('an Inbox question says which clip; a publish option is the platform in words and the frame shape', () => {
    const x = { kind: 'publish', source: 'engine', clip: { id: 's001', title: '一次录完，一周的内容', n: 1 }, options: [], params: {} } as unknown as InboxItem;
    expect(inboxClip(x)).toBe('“一次录完，一周的内容”');
    expect(inboxSub(x)).toBe('“一次录完，一周的内容”');
    setLang('zh-CN');
    expect(optionLabel({ id: '0', text: 'Xiaohongshu · vertical', platform: 'xiaohongshu', aspect: '3:4' })).toBe('小红书 · 3:4');
  });
  it('a stopped clip is not "ready"; a clip waiting for her needs her', () => {
    expect(clipStatus({ state: 'failed' })).toBe('error');
    expect(clipStatus({ state: 'waiting' })).toBe('you');
  });
});

describe('one status vocabulary; a project waiting for her is filed under Needs you', () => {
  const item = (o: Partial<HistoryItem>): HistoryItem => ({ kind: 'project', id: 'p1', dir: '/p', name: 'p', recipe: null, client: null, created: 0, updated: 0, counts: { total: 2, done: 1, approved: 0, red: 0, failed: 0 }, status: 'in-progress', ...o }) as unknown as HistoryItem;
  it('an Inbox question wins over a run that is still going', () => {
    const p = itemPipeline(item({ live: live({ code: 'jobs', params: { done: 1, total: 2 }, stage: 's002:asr', progress: 0.5 }) }), [], true);
    expect(p.state).toBe('you');
    expect(itemPipeline(item({ live: live({ stage: 's002:asr', progress: 0.5, eta: 90 }) }), [], false)).toMatchObject({ state: 'run', current: 'transcribe', eta: 90 });
  });
  it('the AI deciding between rounds is at that question’s step, in words', () => {
    const l = live({ code: 'deciding', params: { kind: 'cover-pick' }, stages: [{ job: null, stage: 'cp_cover-pick' }], stage: 'cp_cover-pick' });
    expect(itemPipeline(item({ live: l })).current).toBe('render');
    setLang('zh-CN');
    expect(liveText(l)).toBe('AI 正在定：选一张封面');
  });
  it('the run line by line', () => {
    const clips = [{ id: 's001', title: '一次录完' }];
    expect(feedLine({ event: 'stage-start', job: 's001', stage: 'asr' }, clips)).toBe('“一次录完” · Transcribe…');
    expect(feedLine({ event: 'auto-answer', item: 's001', kind: 'cover-pick', by: 'ai' }, clips)).toBe('“一次录完” · the AI decided: Pick a cover');
    expect(feedLine({ event: 'job-done', job: 's001', state: 'failed' }, clips)).toBe('“一次录完” didn’t finish');
    expect(feedLine({ event: 'stage-done', job: 's001', stage: 'asr' }, clips)).toBeNull();
  });
});
