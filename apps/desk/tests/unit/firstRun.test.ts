// First ten minutes: the one-time downloads as one bar + time left, default platforms per UI language, the plan
// sentence when no AI planned it (UI language, never the engine's Chinese template), the sample's project names, and
// the copy of the first-run module in every language.
import { afterEach, describe, expect, it } from 'vitest';
import type { AssetGroupStatus } from '../../src/shared/assets';
import type { IntakePlan } from '../../src/shared/v04';
import { LOCALES, setLang } from '../../src/renderer/src/i18n';
import { firstRunEn, firstRunFr, firstRunZh } from '../../src/renderer/src/i18n/locales/firstRun';
import { defaultPlatformsFor, downloadSummary, etaText, fmtBytes, nameAsSample, planSentence, speedOf } from '../../src/renderer/src/lib/firstRun';

const g = (id: string, bytes: number, x: Partial<AssetGroupStatus> = {}): AssetGroupStatus => ({ id, required: true, installed: false, bytes, licence: '', ...x });

afterEach(() => setLang('en'));

describe('downloadSummary', () => {
  it('adds installed groups in full and the running one by its bytes; optional groups do not count', () => {
    const s = downloadSummary({
      busy: true,
      groups: [g('core', 60e6, { installed: true }), g('asr-mlx-fast', 460e6, { progress: { received: 100e6, total: 460e6, file: 'w' } }), g('asr-mlx', 1.6e9, { required: false })],
    });
    expect(s).toMatchObject({ state: 'downloading', done: 160e6, total: 520e6, missing: ['asr-mlx-fast'] });
    expect(s.pct).toBeCloseTo(160 / 520);
  });
  it('queued counts as downloading; nothing missing is done; an error without activity is failed', () => {
    expect(downloadSummary({ busy: true, groups: [g('core', 1, { queued: true })] }).state).toBe('downloading');
    expect(downloadSummary({ busy: false, groups: [g('core', 1, { installed: true })] }).state).toBe('done');
    expect(downloadSummary({ busy: false, groups: [g('core', 1, { error: 'sha256 mismatch' })] })).toMatchObject({ state: 'failed', error: 'sha256 mismatch' });
    expect(downloadSummary({ busy: false, groups: [g('core', 1)] }).state).toBe('waiting');
    expect(downloadSummary(null).state).toBe('done');
  });
});

describe('time left', () => {
  it('speed needs a trend of at least 1.5 s', () => {
    expect(speedOf([])).toBeNull();
    expect(speedOf([[0, 0], [1000, 10e6]])).toBeNull();
    expect(speedOf([[0, 0], [2000, 20e6]])).toBe(10e6);
  });
  it('says minutes, or less than a minute, or nothing without a speed', () => {
    expect(etaText(600e6, 10e6)).toBe(' · about 1 min left');
    expect(etaText(1.2e9, 10e6)).toContain('2 min');
    expect(etaText(100e6, 10e6)).toContain('less than a minute');
    expect(etaText(100e6, null)).toBe('');
  });
  it('sizes in MB / GB', () => {
    expect(fmtBytes(463_664_664)).toBe('464 MB');
    expect(fmtBytes(1.6e9)).toBe('1.6 GB');
    expect(fmtBytes(0)).toBe('0 MB');
  });
});

describe('defaultPlatformsFor', () => {
  it('Chinese UI -> Xiaohongshu, any other -> TikTok + Shorts; her own choice is kept', () => {
    expect(defaultPlatformsFor('zh-CN')).toEqual(['xiaohongshu:full']);
    expect(defaultPlatformsFor('en', ['xiaohongshu:full'])).toEqual(['tiktok', 'youtube-shorts']);
    expect(defaultPlatformsFor('fr', [])).toEqual(['tiktok', 'youtube-shorts']);
    expect(defaultPlatformsFor('en', ['bilibili'])).toEqual(['bilibili']);
  });
});

const plan = (projects: Partial<IntakePlan['projects'][number]>[]): IntakePlan =>
  ({
    version: 1,
    kind: 'vstudio.intake.plan',
    id: 'p',
    prompt: 'x',
    planner: { provider: 'none', fallback: true },
    materials: [{ id: 'f1', path: '/x/reelfold-sample.mp4', name: '', kind: 'video' }],
    projects: projects.map((p, i) => ({ id: `p${i}`, recipe: 'talkinghead', name: 'talkinghead-1', items: { method: 'single', count: 1 }, params: {}, checkpoints: [], estimate: {}, ...p })),
    series: null,
    questions: [],
    risks: [],
    warnings: [],
    estimate: {},
    summary_zh: '我会做 1 个项目',
  }) as IntakePlan;

describe('planSentence (no AI planned it)', () => {
  const pf = (id: string) => ({ tiktok: 'TikTok', 'youtube-shorts': 'YouTube Shorts' })[id] ?? id;
  it('one talking-head edit in English, with what it does and where it goes', () => {
    const s = planSentence(plan([{ params: { cleanup_profile: 'standard', speed: 1.1, platforms: ['tiktok', 'youtube-shorts'] } }]), pf);
    expect(s).toContain('One cleaned-up edit from reelfold-sample.mp4');
    expect(s).toContain('pauses and filler words cut');
    expect(s).toContain('1.1× speed');
    expect(s).toContain('captions');
    expect(s).toContain('TikTok');
    expect(s).not.toMatch(/[一-鿿]/);
  });
  it('captions off and speed 1 are not mentioned; several projects are counted', () => {
    const one = planSentence(plan([{ params: { speed: 1, captions: false } }]), pf);
    expect(one).not.toContain('speed');
    expect(one).not.toContain('captions');
    expect(planSentence(plan([{}, { recipe: 'longform-to-short', recipe_label: 'Clips', items: { method: 'planner', count: 5 } }]), pf)).toMatch(/^2 projects/);
  });
  it('French', () => {
    setLang('fr');
    expect(planSentence(plan([{ params: { platforms: ['tiktok'] } }]), pf)).toContain('Un montage nettoyé');
  });
});

describe('nameAsSample', () => {
  it('names every project as the sample (numbered when there are several)', () => {
    expect(nameAsSample(plan([{}]), 'Sample').projects.map((p) => p.name)).toEqual(['Sample']);
    expect(nameAsSample(plan([{}, {}]), 'Sample').projects.map((p) => p.name)).toEqual(['Sample 1', 'Sample 2']);
  });
});

describe('first-run copy', () => {
  it('every key in every language, no engine words in what she reads first', () => {
    for (const m of [firstRunZh, firstRunFr]) expect(Object.keys(m).sort()).toEqual(Object.keys(firstRunEn).sort());
    for (const l of Object.values(LOCALES)) {
      for (const k of ['fr.noAiBody', 'dl.body', 'sample.trySub', 'assets.group.asr-mlx-fast'] as const) {
        expect(l.messages[k]).not.toMatch(/Whisper|MediaPipe|engine|引擎|moteur|sidecar|127\.0\.0\.1/i);
      }
    }
  });
});
