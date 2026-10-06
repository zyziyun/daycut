// X / Instagram / 视频号 / B站 adapters: schema, platform keys, gating, fill plans and copy checks.
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { runFill, type Send } from '../../src/main/publish/cdpFill';
import { adapterFor, basePlatform, hostAllowed, parseAdapter, type Adapter } from '../../src/shared/publish/adapterSchema';
import { planFill } from '../../src/shared/publish/fillPlan';
import { checkFill, type Confirmation } from '../../src/shared/publish/gating';
import { checkCopy, hashtagsIn, parsePostCopy, xWeightedLength } from '../../src/shared/publish/postCopy';
import { platformId } from '../../src/shared/ipc';
import type { Manifest, ManifestVerify } from '../../src/shared/types';

const dir = path.resolve(__dirname, '../../adapters');
const raw = (f: string) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
const load = (f: string): Adapter => {
  const r = parseAdapter(raw(f));
  if (!r.ok) throw new Error(r.error);
  return r.adapter;
};
const X = load('x.json');
const IG = load('instagram.json');
const WC = load('wechat-channels.json');
const BILI = load('bilibili.json');
const ALL = [X, IG, WC, BILI];

describe('new platform adapters', () => {
  it('are valid, unverified, never click, and leave her choices to her', () => {
    for (const a of ALL) {
      expect(a.status).toBe('unverified');
      expect(a.lastVerified).toBeNull();
      expect(a.notes.some((n) => /UNVERIFIED/.test(n))).toBe(true);
      expect(a.guide?.zh.length).toBeGreaterThan(10);
      expect(a.herChoices?.en.length).toBeGreaterThan(0);
      expect(JSON.stringify(a)).not.toMatch(/"click"/);
    }
    expect(BILI.herChoices!.zh.join()).toMatch(/分区/);
    expect(BILI.herChoices!.zh.join()).toMatch(/自制/);
    expect(IG.publishButton).toBeNull(); // Share has no stable selector: not even highlighted
  });

  it('map package keys (incl. x-square, instagram-reels / -feed, wechat-channels-vertical) to the adapter', () => {
    expect(basePlatform('x-square')).toBe('x');
    expect(basePlatform('instagram-reels')).toBe('instagram');
    expect(basePlatform('instagram-feed')).toBe('instagram');
    expect(basePlatform('wechat-channels-vertical')).toBe('wechat-channels');
    expect(adapterFor('x-vertical', ALL)?.id).toBe('x-web');
    expect(adapterFor('x-horizontal', ALL)?.id).toBe('x-web');
    expect(adapterFor('instagram-feed', ALL)?.id).toBe('instagram');
    expect(adapterFor('wechat-channels-horizontal', ALL)?.id).toBe('wechat-channels');
    expect(adapterFor('bilibili-vertical', ALL)?.id).toBe('bilibili');
    for (const p of ['x', 'x:square', 'instagram:reels', 'wechat-channels', 'bilibili:vertical']) expect(platformId.safeParse(p).success).toBe(true);
  });

  it('posted URLs are accepted on the platform hosts only', () => {
    expect(hostAllowed('x.com', X.allowedHosts)).toBe(true);
    expect(hostAllowed('www.instagram.com', IG.allowedHosts)).toBe(true);
    expect(hostAllowed('weixin.qq.com', WC.allowedHosts)).toBe(true);
    expect(hostAllowed('b23.tv', BILI.allowedHosts)).toBe(true);
    expect(hostAllowed('evil-x.com', X.allowedHosts)).toBe(false);
  });

  it('cannot gain a click or an Enter-anything through the new fields', () => {
    const a = raw('bilibili.json');
    expect(parseAdapter({ ...a, fields: { ...a.fields, tags: { ...a.fields.tags, submit: 'click' } } }).ok).toBe(false);
    expect(parseAdapter({ ...a, herChoices: { zh: ['x'], en: ['x'], click: ['b'] } }).ok).toBe(false);
  });

  it('are gated by the confirmed manifest like the others', () => {
    const manifest: Manifest = {
      batch: 'demo',
      schedule: { per_day: 1, start: '2026-10-06', times: ['09:00'] },
      confirmation_code: 'bbbbbbbbbbbb',
      items: [{ job: 's001', platform: 'x-vertical', title: 'a', date: '2026-10-06', time: '09:00', files: { video: 'x-vertical/001_s001/video.mp4' }, sha256: 'x', bytes: 1, duration: 1 }],
    };
    const ok: ManifestVerify = { ok: true, code: 'bbbbbbbbbbbb', stored: 'bbbbbbbbbbbb' };
    const conf: Confirmation[] = [{ batchId: 'b1', code: 'bbbbbbbbbbbb', items: 1, confirmedAt: '' }];
    const req = { batchId: 'b1', code: 'bbbbbbbbbbbb', job: 's001', platform: 'x-vertical', adapterId: 'x-web' };
    expect(checkFill(req, manifest, ok, conf, ALL).ok).toBe(true);
    expect(checkFill({ ...req, adapterId: 'instagram' }, manifest, ok, conf, ALL)).toMatchObject({ ok: false, reason: 'adapter-mismatch' });
    expect(checkFill(req, manifest, ok, [], ALL)).toMatchObject({ ok: false, reason: 'not-confirmed' });
  });
});

describe('fill plans', () => {
  const md = 'One recording, ten clips.\n\nHere is how it works.\n\n#video #editing #ai\n';
  it('X: no title field - the whole text (with 2 tags) goes into the post box, not clipped by chars', () => {
    const copy = parsePostCopy(md, '', { keepFirstLine: true });
    expect(parsePostCopy(md, '').title).toBe('One recording, ten clips.'); // platforms with a title field
    const steps = planFill(X, { videoPath: '/p/v.mp4', copy });
    const d = steps.find((s) => s.field === 'description');
    expect(d && d.kind === 'text' && d.text).toBe('One recording, ten clips.\n\nHere is how it works.\n\n#video #editing');
    expect(steps.map((s) => s.field)).toEqual(['file', 'description', 'publish']);
    const long = planFill(X, { videoPath: '/v', copy: { title: '', description: '中'.repeat(400), tags: [] } });
    const t = long.find((s) => s.field === 'description');
    expect(t && t.kind === 'text' && t.text.length).toBe(400); // warn, never cut (Premium posts can be longer)
  });

  it('Instagram: the file waits up to 2 min for her Create -> Post, caption keeps <= 5 tags, nothing highlighted', () => {
    const steps = planFill(IG, { videoPath: '/p/v.mp4', copy: { title: 'T', description: 'cap', tags: ['a', 'b', 'c', 'd', 'e', 'f'] } });
    expect(steps[0]).toMatchObject({ field: 'file', timeoutMs: 120000 });
    const d = steps.find((s) => s.field === 'description');
    expect(d && d.kind === 'text' && d.text).toBe('cap\n\n#a #b #c #d #e');
    expect(steps.some((s) => s.kind === 'highlight')).toBe(false);
  });

  it('B站: title, description, one tag per Enter, cover; 视频号: short title + description with #topics', () => {
    const copy = { title: '标题', description: '简介', tags: ['口播', '剪辑'] };
    const steps = planFill(BILI, { videoPath: '/v', coverPath: '/c.jpg', copy });
    expect(steps.map((s) => s.field)).toEqual(['file', 'title', 'description', 'tags', 'cover', 'publish']);
    const tg = steps.find((s) => s.field === 'tags');
    expect(tg && tg.kind === 'text' && tg.items).toEqual(['口播', '剪辑']);
    const w = planFill(WC, { videoPath: '/v', copy: { title: '一个超过十六个字的短标题会被截断到十六个字', description: '描述', tags: ['话题'] } });
    const tt = w.find((s) => s.field === 'title');
    expect(tt && tt.kind === 'text' && Array.from(tt.text).length).toBe(16);
    const dd = w.find((s) => s.field === 'description');
    expect(dd && dd.kind === 'text' && dd.text).toBe('描述\n\n#话题');
  });

  it('types each B站 tag and presses Enter after it (Enter is the only key)', async () => {
    const calls: { method: string; params?: Record<string, unknown> }[] = [];
    const send: Send = async (method, params) => {
      calls.push({ method, params });
      if (method === 'Page.getFrameTree') return { frameTree: { frame: { id: 'f0' } } };
      if (method === 'Page.createIsolatedWorld') return { executionContextId: 1 };
      if (method === 'Runtime.evaluate') return { result: { type: 'object', subtype: 'node', objectId: 'o1' } };
      if (method === 'Runtime.callFunctionOn') return { result: { value: true } };
      return {};
    };
    const steps = planFill(BILI, { videoPath: '/v', copy: { title: '', description: '', tags: ['口播', '剪辑'] } }).filter((s) => s.field === 'tags');
    const res = await runFill(send, steps, { sleep: async () => undefined });
    expect(res).toEqual([{ field: 'tags', kind: 'text', status: 'ok' }]);
    const seq = calls.filter((c) => c.method === 'Input.insertText' || c.method === 'Input.dispatchKeyEvent').map((c) => (c.method === 'Input.insertText' ? c.params!.text : `${c.params!.type}:${c.params!.key}`));
    expect(seq).toEqual(['口播', 'keyDown:Enter', 'keyUp:Enter', '剪辑', 'keyDown:Enter', 'keyUp:Enter']);
    const ev = calls.find((c) => c.method === 'Runtime.evaluate');
    expect(String(ev!.params!.expression)).toContain('shadowRoot');
  });
});

describe('copy checks (warn, never cut)', () => {
  it('weights X text like twitter-text v3', () => {
    expect(xWeightedLength('hello')).toBe(5);
    expect(xWeightedLength('你好')).toBe(4);
    expect(xWeightedLength('see https://example.com/a/very/long/path?x=1')).toBe(27);
    expect(xWeightedLength('😀')).toBe(2);
    expect(xWeightedLength('👍🏽')).toBe(2);
    expect(xWeightedLength('👨‍👩‍👧')).toBe(2);
    expect(xWeightedLength('hello 你好 https://example.com/very/long/path 😀👍🏽 👨‍👩‍👧')).toBe(42); // same as the engine
  });

  it('flags X over 280 weighted and Instagram over 5 hashtags (caption + appended)', () => {
    expect(checkCopy(X.fields, { title: '', description: '中'.repeat(140), tags: [] })).toEqual([]);
    const x = checkCopy(X.fields, { title: '', description: '中'.repeat(141), tags: [] });
    expect(x).toEqual([{ code: 'text-over', field: 'description', n: 282, max: 280 }]);
    expect(checkCopy(IG.fields, { title: '', description: 'cap #a #b', tags: ['c', 'd'] })).toEqual([]);
    const ig = checkCopy(IG.fields, { title: '', description: 'cap #a #b #x', tags: ['c', 'd', 'e'] });
    expect(ig).toEqual([{ code: 'hashtags-over', field: 'tags', n: 6, max: 5, hard: true }]);
    expect(hashtagsIn('a #One #one #二')).toEqual(['one', '二']);
    const b = checkCopy(BILI.fields, { title: 'x'.repeat(81), description: '', tags: [] });
    expect(b[0]).toMatchObject({ code: 'text-over', field: 'title', n: 81, max: 80 });
  });
});
