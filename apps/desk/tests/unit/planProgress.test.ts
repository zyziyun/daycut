// The plan card while a plan is made: the engine's stage in words, a bar when it knows how far it is, the five steps.
import { afterEach, describe, expect, it } from 'vitest';
import { setLang } from '../../src/renderer/src/i18n';
import { planProgressView, stepOf } from '../../src/renderer/src/lib/planProgress';
import type { IntakeProgress } from '../../src/shared/v04';

const FILE = 'AIGC 短视频生成评测综述.mp4';
const states = (p: IntakeProgress) => planProgressView(p)!.steps.map((s) => `${s.id}:${s.state}`);

describe('plan progress card', () => {
  afterEach(() => setLang('en'));

  it('shows nothing new until the engine reports (older engines keep the plain card)', () => {
    expect(planProgressView(null)).toBeNull();
    expect(planProgressView(undefined)).toBeNull();
  });

  it('mid-transcription: file, clock and a determinate bar', () => {
    setLang('en');
    const v = planProgressView({ stage: 'transcribe', file: FILE, done_s: 250, total_s: 764, seen: ['scan', 'probe', 'listen', 'faces', 'transcribe'], files: 27 })!;
    expect(v.label).toBe(`Transcribing ${FILE}`);
    expect(v.detail).toBe('4:10 / 12:44');
    expect(v.fraction).toBeCloseTo(250 / 764, 5);
    expect(v.steps.map((s) => `${s.id}:${s.state}`)).toEqual(['scan:done', 'media:done', 'transcribe:current', 'model:pending', 'write:pending']);
    expect(v.steps[0].note).toBe('27 files found');
  });

  it('reading files: file i of n, the bar moves per file', () => {
    setLang('en');
    const v = planProgressView({ stage: 'faces', file: 'talk.mp4', i: 3, n: 4, seen: ['scan', 'probe', 'listen', 'faces'] })!;
    expect(v.label).toBe('Looking for faces in talk.mp4');
    expect(v.detail).toBe('file 3 of 4');
    expect(v.fraction).toBe(0.5);
    expect(stepOf('listen')).toBe('media');
    expect(planProgressView({ stage: 'probe', file: 'a.mp4', i: 1, n: 1, cached: true })!.label).toBe('Already read a.mp4 before');
  });

  it('a transcript made earlier: said so, no bar', () => {
    setLang('en');
    const v = planProgressView({ stage: 'transcribe', file: FILE, cached: 'shared', total_s: 764, done_s: 764 })!;
    expect(v.label).toBe(`Using the transcript made earlier for ${FILE}`);
    expect(v.fraction).toBeNull();
    expect(v.steps.find((s) => s.id === 'transcribe')!.note).toBe('used the earlier transcript');
    // remembered after moving on to the model
    const later = planProgressView({ stage: 'model', provider: 'claude-code', reused: true, seen: ['scan', 'probe', 'transcribe', 'model'] })!;
    expect(later.steps.find((s) => s.id === 'transcribe')).toMatchObject({ state: 'done', note: 'used the earlier transcript' });
  });

  it('the AI call names the provider; transcription that never ran was not needed', () => {
    setLang('en');
    const p: IntakeProgress = { stage: 'model', provider: 'claude-code', seen: ['scan', 'probe', 'listen', 'model'] };
    const v = planProgressView(p)!;
    expect(v.label).toBe('Asking Claude Code for a plan');
    expect(v.fraction).toBeNull();
    expect(states(p)).toEqual(['scan:done', 'media:done', 'transcribe:skipped', 'model:current', 'write:pending']);
    expect(v.steps[2].note).toBe('not needed');
    expect(planProgressView({ stage: 'model' })!.label).toBe('Asking the AI for a plan');
    expect(states({ stage: 'write', seen: ['scan', 'probe', 'transcribe', 'model', 'write'] })).toEqual(['scan:done', 'media:done', 'transcribe:done', 'model:done', 'write:current']);
  });

  it('a clock never runs past the end; 简体中文', () => {
    setLang('zh-CN');
    const v = planProgressView({ stage: 'transcribe', file: FILE, done_s: 900, total_s: 764 })!;
    expect(v.label).toBe(`正在转写 ${FILE}`);
    expect(v.detail).toBe('12:44 / 12:44');
    expect(v.fraction).toBe(1);
    expect(planProgressView({ stage: 'model', provider: 'codex' })!.label).toBe('正在请 Codex 出方案');
    expect(planProgressView({ stage: 'scan', files: 3 })!.detail).toBe('找到 3 个文件');
  });
});
