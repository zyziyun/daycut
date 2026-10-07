// Publish board model (one card per clip per day, calm status, queue by project, overflow, typed times, plan
// summary) and the Settings registry / words (no raw paths) + no hard-coded copy in the new screens.
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import type { CalendarPost, SchedulePlan } from '../../src/shared/v04';
import { setLang } from '../../src/renderer/src/i18n';
import { groupPosts, groupStatus, overflowAt, parseWhen, queueByProject, weekStart } from '../../src/renderer/src/publish/model';
import { daysText, planSummary } from '../../src/renderer/src/publish/NlBar';
import { registerSettingsSection, settingsSections } from '../../src/renderer/src/settings/registry';
import { engineWords, pythonWords } from '../../src/renderer/src/settings/words';

const P = (o: Partial<CalendarPost>): CalendarPost => ({ id: Math.random().toString(16).slice(2, 14), item: 'a'.repeat(12), clip: 'A', title: 'A 标题', cover: null, platform: 'xiaohongshu', at: '2026-10-07T20:00', state: 'planned', ...o });

afterEach(() => setLang('en'));

describe('publish board model', () => {
  it('one card per clip per day; earliest switched-on time; platforms in account order; warnings of switched-on rows', () => {
    const g = groupPosts(
      [
        P({ platform: 'douyin', at: '2026-10-07T20:00' }),
        P({ platform: 'x', at: '2026-10-07T09:00', enabled: false, warnings: [{ kind: 'caption_too_long', platform: 'x' }] }),
        P({ platform: 'xiaohongshu', at: '2026-10-07T12:00', warnings: [{ kind: 'slot_clash', platform: 'xiaohongshu' }] }),
        P({ clip: 'A', at: '2026-10-08T20:00' }),
        P({ clip: 'B', at: '2026-10-07T19:00', stats: { views: 10 } }),
        P({ clip: 'B', platform: 'douyin', at: '2026-10-07T19:00', stats: { views: 5 } }),
      ],
      ['x', 'xiaohongshu', 'douyin'],
    );
    expect(g.map((x) => `${x.clip} ${x.day} ${x.time}`)).toEqual(['A 2026-10-07 12:00', 'B 2026-10-07 19:00', 'A 2026-10-08 20:00']);
    expect(g[0].platforms).toEqual(['xiaohongshu', 'douyin']); // x is switched off
    expect(g[0].posts).toHaveLength(3);
    expect(g[0].warnings.map((w) => w.kind)).toEqual(['slot_clash']);
    expect(g[1].views).toBe(15);
    expect(g[2].views).toBeNull();
  });

  it('calm status: all posted, one filled form waiting, all ready, else draft', () => {
    expect(groupStatus([P({ state: 'posted' }), P({ state: 'posted' })])).toBe('posted');
    expect(groupStatus([P({ state: 'filled' }), P({ state: 'ready' })])).toBe('filled');
    expect(groupStatus([P({ state: 'ready' }), P({ state: 'posted' })])).toBe('ready');
    expect(groupStatus([P({ state: 'ready' }), P({ state: 'planned' })])).toBe('draft');
    expect(groupStatus([P({ state: 'planned', enabled: false }), P({ state: 'ready' })])).toBe('ready');
    expect(groupStatus([P({ status: 'filled' })])).toBe('filled');
  });

  it('queue grouped by project in order', () => {
    const q = (item: string, clip: string, project: string) => ({ item, clip, title: clip, project, cover: null, aspects: [] });
    const g = queueByProject([q('a', '1', 'fuye'), q('b', '2', 'rag'), q('a', '3', 'fuye')]);
    expect(g.map((x) => `${x.project}:${x.clips.map((c) => c.clip).join(',')}`)).toEqual(['fuye:1,3', 'rag:2']);
  });

  it('overflow: where the text stops fitting (X weighs CJK as 2)', () => {
    expect(overflowAt('abc', 'x', 280)).toBe(-1);
    expect(overflowAt('中'.repeat(141), 'x', 280)).toBe(140);
    expect(overflowAt('a'.repeat(1001), 'xiaohongshu', 1000)).toBe(1000);
    expect(overflowAt('a'.repeat(5000), 'reddit', null)).toBe(-1);
  });

  it('typed times: next Friday evening, 明天晚上8点, demain 20h, same time tomorrow', () => {
    const tue = new Date(2026, 9, 6, 10, 0); // Tue Oct 6
    expect(parseWhen('next Friday evening', tue)).toEqual({ day: '2026-10-16', time: '20:00' });
    expect(parseWhen('Friday 7pm', tue)).toEqual({ day: '2026-10-09', time: '19:00' });
    expect(parseWhen('明天晚上8点', tue)).toEqual({ day: '2026-10-07', time: '20:00' });
    expect(parseWhen('下周五 12:30', tue)).toEqual({ day: '2026-10-16', time: '12:30' });
    expect(parseWhen('demain 20h', tue)).toEqual({ day: '2026-10-07', time: '20:00' });
    expect(parseWhen('same time tomorrow', tue)).toEqual({ day: '2026-10-07' });
    expect(parseWhen('21:15', tue)).toEqual({ time: '21:15' });
    expect(parseWhen('whenever', tue)).toBeNull();
    expect(weekStart(tue).getDate()).toBe(5);
  });

  it('plan summary in every language', () => {
    const p = { ok: true, reason: null, text: '', start: '2026-10-12', drafts: [1, 2, 3, 4, 5].map(() => ({ item: 'a', clip: 'b', platform: 'xiaohongshu', at: '2026-10-12T20:00' })), adjustments: [], platforms: ['xiaohongshu'], time: '20:00', days: [0, 1, 2, 3, 4], per_day: 1 } as SchedulePlan;
    expect(planSummary(p)).toBe('5 new posts on Xiaohongshu · Mon–Fri at 20:00 · weekends off');
    setLang('zh-CN');
    expect(planSummary(p)).toBe('在小红书新增 5 条 · 周一至周五 20:00 · 周末不发');
    setLang('fr');
    expect(planSummary(p)).toContain('5 nouvelles publications');
    setLang('en');
    expect(daysText([0, 2, 4])).toBe('Mon, Wed, Fri');
    expect(daysText([5, 6])).toBe('weekends');
  });
});

describe('settings', () => {
  it('the sub-nav is a registry: a feature adds a section in its order', () => {
    const icon = () => null;
    registerSettingsSection({ id: 'zz-adv', order: 90, label: () => 'Advanced', icon, render: () => null });
    registerSettingsSection({ id: 'zz-gen', order: 10, label: () => 'General', icon, render: () => null });
    registerSettingsSection({ id: 'zz-video', order: 25, label: () => 'Video generation', icon, render: () => null });
    const ids = settingsSections().map((s) => s.id).filter((x) => x.startsWith('zz-'));
    expect(ids).toEqual(['zz-gen', 'zz-video', 'zz-adv']);
    registerSettingsSection({ id: 'zz-video', order: 95, label: () => 'Video generation', icon, render: () => null }); // replaced, not doubled
    expect(settingsSections().filter((s) => s.id === 'zz-video')).toHaveLength(1);
  });

  it('paths in words, never raw', () => {
    expect(engineWords('/Users/me/Desktop/reelfold')).toBe('The reelfold folder on your Desktop');
    expect(engineWords('/Users/me/code/reelfold/')).toBe('The reelfold folder in your home folder');
    expect(engineWords('/opt/reelfold')).toBe('The reelfold folder');
    expect(engineWords('/x', true)).toBe('Built into this app');
    expect(engineWords(undefined)).toBe('Not found');
    expect(pythonWords({ resolved: { python: '/a/python3', dataDir: '/d', runtime: 'bundled · Python 3.11.9 · video-studio@abc' } })).toBe('Built in · Python 3.11.9');
    expect(pythonWords({ python: '/opt/homebrew/bin/python3.12', resolved: { python: '/x', dataDir: '/d', runtime: 'system' } })).toBe('Your own · python3.12');
    expect(pythonWords({ resolved: { python: '/x', dataDir: '/d', runtime: 'system' } })).toBe('Found automatically');
    setLang('zh-CN');
    expect(engineWords('/Users/me/Desktop/video-studio')).toBe('桌面上的 video-studio 文件夹');
  });

  it('the new screens have no hard-coded copy', () => {
    const offenders: string[] = [];
    for (const d of ['publish', 'settings']) {
      const dir = path.resolve(import.meta.dirname, '../../src/renderer/src', d);
      for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.tsx'))) {
        const src = fs.readFileSync(path.join(dir, f), 'utf8').replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
        src.split('\n').forEach((line, i) => {
          if (/[一-鿿]/.test(line)) offenders.push(`${d}/${f}:${i + 1} CJK: ${line.trim()}`);
          const jsxText = line.match(/[^=]>\s*([A-Za-z][A-Za-z ,.'!?]{2,})\s*<\//);
          if (jsxText) offenders.push(`${d}/${f}:${i + 1} text: ${jsxText[1]}`);
          const attr = line.match(/\b(placeholder|title|aria-label|data-tip)="([A-Za-z][^"]{2,})"/);
          if (attr) offenders.push(`${d}/${f}:${i + 1} ${attr[1]}: ${attr[2]}`);
        });
      }
    }
    expect(offenders).toEqual([]);
  });
});
