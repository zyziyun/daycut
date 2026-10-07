// Platforms added 2026-10: the shared registry (order, groups, labels, copy rules), YouTube as one channel with two
// formats, the new adapters (schema, unverified, never click, gating), Reddit's subreddit param, copy checks.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { loadAdapters } from '../../src/main/publish/adapters';
import { adapterFor, basePlatform, parseAdapter, uploadUrlFor } from '../../src/shared/publish/adapterSchema';
import { planFill } from '../../src/shared/publish/fillPlan';
import { checkFill } from '../../src/shared/publish/gating';
import { checkCopy } from '../../src/shared/publish/postCopy';
import { PLATFORMS, PLATFORM_IDS, accountPlatform, linksIn, platformLabel, sortPlatforms } from '../../src/shared/platforms';
import { platformKey, SCHEDULE_PLATFORMS } from '../../src/renderer/src/v4/PlatformIcon';
import { en } from '../../src/renderer/src/i18n/locales/en';
import { zhCN } from '../../src/renderer/src/i18n/locales/zh-CN';
import type { Manifest } from '../../src/shared/types';

const dir = path.resolve(__dirname, '../../adapters');
const { adapters, errors } = loadAdapters([dir]);
const by = Object.fromEntries(adapters.map((a) => [a.id, a]));
const NEW = ['facebook', 'linkedin', 'threads', 'reddit', 'pinterest', 'snapchat', 'kuaishou', 'weibo', 'zhihu', 'dailymotion', 'kwai'];

describe('platform registry', () => {
  it('orders English / global, then Chinese, then other languages', () => {
    expect(PLATFORM_IDS).toEqual([
      'youtube', 'youtube-shorts', 'tiktok', 'instagram', 'x', 'facebook', 'linkedin', 'threads', 'reddit', 'pinterest', 'snapchat',
      'xiaohongshu', 'douyin', 'wechat-channels', 'bilibili', 'kuaishou', 'weibo', 'zhihu',
      'dailymotion', 'kwai',
    ]);
    expect(SCHEDULE_PLATFORMS).toEqual(PLATFORM_IDS);
    const groups = PLATFORMS.map((p) => p.group);
    expect(groups.join(',')).toMatch(/^(global,)+(zh,)+(intl,?)+$/);
  });

  it('floats connected accounts to the top within their group only', () => {
    const ids = ['kwai', 'douyin', 'x', 'weibo', 'tiktok', 'youtube-shorts', 'unknown'];
    expect(sortPlatforms(ids, (x) => x)).toEqual(['youtube-shorts', 'tiktok', 'x', 'douyin', 'weibo', 'kwai', 'unknown']);
    expect(sortPlatforms(ids, (x) => x, ['weibo', 'x'])).toEqual(['x', 'youtube-shorts', 'tiktok', 'weibo', 'douyin', 'kwai', 'unknown']);
    // a YouTube channel connects both formats
    expect(sortPlatforms(['tiktok', 'youtube-shorts'], (x) => x, ['youtube'])).toEqual(['youtube-shorts', 'tiktok']);
    expect(accountPlatform('youtube-shorts')).toBe('youtube');
  });

  it('every platform has en / zh / fr labels and a pf.* message in both UI locales', () => {
    for (const p of PLATFORMS) {
      for (const l of ['en', 'zh', 'fr'] as const) expect(p.labels[l].length, `${p.id} ${l}`).toBeGreaterThan(0);
      expect((en as Record<string, string>)[`pf.${p.id}`], p.id).toBeTruthy();
      expect((zhCN as Record<string, string>)[`pf.${p.id}`], p.id).toBeTruthy();
    }
    expect(platformLabel('weibo', 'zh-CN')).toBe('微博');
    expect(platformLabel('wechat-channels', 'fr')).toMatch(/WeChat/);
    for (const g of ['global', 'zh', 'intl']) expect((en as Record<string, string>)[`pf.group.${g}`]).toBeTruthy();
  });

  it('marks resolve for adapter ids and package keys', () => {
    expect(platformKey('youtube-studio')).toBe('youtube');
    expect(platformKey('facebook-reels')).toBe('facebook');
    expect(platformKey('pinterest-feed')).toBe('pinterest');
    expect(platformKey('kuaishou:vertical')).toBe('kuaishou');
  });

  it('finds links', () => {
    expect(linksIn('see https://a.co/x and example.fr')).toEqual(['https://a.co/x', 'example.fr']);
    expect(linksIn('no links here.')).toEqual([]);
  });
});

describe('new platform adapters', () => {
  it('are valid, unverified (Kwai: todo, no web upload), never click', () => {
    expect(errors).toEqual([]);
    for (const id of NEW) {
      const a = by[id];
      expect(a, id).toBeTruthy();
      expect(a.status).toBe(id === 'kwai' ? 'todo' : 'unverified');
      expect(a.lastVerified).toBeNull();
      expect(JSON.stringify(a)).not.toMatch(/"click"/);
      expect(a.disclosure.zh.length).toBeGreaterThan(10);
      expect(a.guide?.en.length).toBeGreaterThan(10);
      expect(adapterFor(`${a.packagePlatforms[0]}-vertical`, adapters)?.id).toBe(id);
    }
    expect(by.reddit.fields.title?.maxLength).toBe(300);
    expect(by.reddit.fields.tags).toBeNull(); // no hashtags on Reddit
    expect(by.pinterest.fields.tags).toBeNull();
    expect(by.weibo.fields.tags?.format).toBe('#{tag}# ');
    expect(by.threads.fields.description?.softMax).toBe(500);
    expect(by.zhihu.herChoices?.zh.join()).toMatch(/领域/);
    expect(by.reddit.herChoices?.en.join()).toMatch(/subreddit/i);
  });

  it('YouTube is one card for long-form and Shorts', () => {
    const yt = by['youtube-studio'];
    expect(yt.name).toBe('YouTube');
    expect(yt.packagePlatforms).toEqual(['youtube', 'youtube-shorts']);
    expect(adapterFor('youtube-horizontal', adapters)?.id).toBe('youtube-studio');
    expect(adapterFor('youtube-shorts-vertical', adapters)?.id).toBe('youtube-studio');
    expect(basePlatform('facebook-reels')).toBe('facebook');
  });

  it('Reddit: the typed subreddit picks the upload page; bad values never reach a URL', () => {
    const r = by.reddit;
    expect(uploadUrlFor(r)).toBe('https://www.reddit.com/submit');
    expect(uploadUrlFor(r, { subreddit: 'aivideo' })).toBe('https://www.reddit.com/r/aivideo/submit');
    expect(uploadUrlFor(r, { subreddit: 'r/AIfilm' })).toBe('https://www.reddit.com/r/AIfilm/submit');
    expect(() => uploadUrlFor(r, { subreddit: '../evil' })).toThrow();
    expect(() => uploadUrlFor(r, { subreddit: 'a?b=1' })).toThrow();
    const raw = JSON.parse(fs.readFileSync(path.join(dir, 'reddit.json'), 'utf8'));
    expect(parseAdapter({ ...raw, params: [{ ...raw.params[0], uploadUrl: 'https://evil.example/r/{value}' }] }).ok).toBe(false);
    expect(parseAdapter({ ...raw, params: [{ ...raw.params[0], click: true }] }).ok).toBe(false);
  });

  it('gating: Kwai (todo) cannot be filled; a new platform can after confirmation', () => {
    const man: Manifest = {
      batch: 'b1', schedule: {}, confirmation_code: 'abc123abc123',
      items: [
        { job: 'c1', platform: 'kwai-vertical', title: 't', files: { video: 'v.mp4' }, sha256: 'x', bytes: 1 },
        { job: 'c1', platform: 'linkedin-horizontal', title: 't', files: { video: 'v.mp4' }, sha256: 'x', bytes: 1 },
      ],
    } as unknown as Manifest;
    const conf = [{ batchId: 'b1', code: 'abc123abc123', items: 2, confirmedAt: '2026-10-06' }];
    const v = { ok: true, code: 'abc123abc123' } as never;
    const kw = checkFill({ batchId: 'b1', code: 'abc123abc123', job: 'c1', platform: 'kwai-vertical', adapterId: 'kwai' }, man, v, conf, adapters);
    expect(kw).toMatchObject({ ok: false, reason: 'adapter-todo' });
    const li = checkFill({ batchId: 'b1', code: 'abc123abc123', job: 'c1', platform: 'linkedin-horizontal', adapterId: 'linkedin' }, man, v, conf, adapters);
    expect(li.ok).toBe(true);
    const wrong = checkFill({ batchId: 'b1', code: 'abc123abc123', job: 'c1', platform: 'linkedin-horizontal', adapterId: 'reddit' }, man, v, conf, adapters);
    expect(wrong).toMatchObject({ ok: false, reason: 'adapter-mismatch' });
  });

  it('fill plans: Reddit title + text, no tags; Weibo #topic#; never a click step', () => {
    const copy = { title: 'My AI short', description: 'Made it.', tags: ['ai', 'film'] };
    const rd = planFill(by.reddit, { videoPath: '/v.mp4', copy });
    expect(rd.map((s) => s.field)).toEqual(['file', 'title', 'description', 'publish']);
    expect(rd.every((s) => s.kind !== ('click' as never))).toBe(true);
    const wb = planFill(by.weibo, { videoPath: '/v.mp4', copy });
    expect(wb.find((s) => s.field === 'description')?.kind === 'text' && (wb.find((s) => s.field === 'description') as { text: string }).text).toMatch(/#ai# #film#$/);
  });
});

describe('copy rules per platform', () => {
  const rules = (id: string) => {
    const c = PLATFORMS.find((p) => p.id === id)!.copy;
    return { titleRequired: c.titleRequired, links: c.links, noHashtags: c.hashtags.max === 0 };
  };
  it('links: LinkedIn / Facebook fine, Instagram not clickable, Pinterest link field, 小红书 avoid', () => {
    const copy = { title: '', description: 'read more at https://example.com', tags: [] };
    expect(checkCopy(by.linkedin.fields, copy, rules('linkedin'))).toEqual([]);
    expect(checkCopy(by.facebook.fields, copy, rules('facebook'))).toEqual([]);
    expect(checkCopy(by.instagram.fields, copy, rules('instagram')).map((c) => c.code)).toContain('link-not-clickable');
    expect(checkCopy(by.pinterest.fields, { ...copy, title: 't' }, rules('pinterest')).map((c) => c.code)).toContain('link-field');
    expect(checkCopy(by.xiaohongshu.fields, { ...copy, title: 't' }, rules('xiaohongshu')).map((c) => c.code)).toContain('link-avoid');
  });
  it('Reddit: title required, hashtags not used', () => {
    const c = checkCopy(by.reddit.fields, { title: '', description: 'x #ai', tags: ['ai'] }, rules('reddit')).map((x) => x.code);
    expect(c).toEqual(expect.arrayContaining(['title-required', 'no-hashtags']));
  });
  it('every new check code has a message in en and zh', () => {
    for (const k of ['yt-vertical-only', 'shorts-horizontal', 'title-required', 'link-not-clickable', 'link-field', 'link-avoid', 'no-hashtags', 'subreddit']) {
      expect((en as Record<string, string>)[`pkg.c.${k}`], k).toBeTruthy();
      expect((zhCN as Record<string, string>)[`pkg.c.${k}`], k).toBeTruthy();
    }
  });
});
