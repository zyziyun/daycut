// Create page: client paths + bodies, routes (round trip, flag off -> home), recorder IPC schemas, the media
// permission predicate, the CSP addition, money formatting, the teleprompter pace, and no hard-coded copy in create/.
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { CreateClient, swatch, yuan } from '../../src/shared/create';
import { EngineClient } from '../../src/shared/engineClient';
import { validateIpc } from '../../src/shared/ipc';
import { allowMedia, createFlagFrom, MAX_CHUNK } from '../../src/shared/recIpc';
import { buildCsp } from '../../src/main/security';
import { createHref, parseCreate, type CreateRoute } from '../../src/renderer/src/create/routes';
import { setCreatePrefs } from '../../src/renderer/src/create/flag';
import { href, parseRoute } from '../../src/renderer/src/lib/router';
import { lineSeconds } from '../../src/renderer/src/create/record/recModel';
import { pickMime } from '../../src/renderer/src/create/record/useRecorder';

function fakeFetch(reply: unknown = { ok: true }, status = 200) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const f = async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(reply), { status });
  };
  return { f, calls };
}

describe('CreateClient', () => {
  it('maps calls to /api/create/* with the right bodies', async () => {
    const { f, calls } = fakeFetch();
    const c = new EngineClient('app://desk', 'tok', f).create;
    await c.formats();
    await c.plan({ prompt: 'series ad', budget_cny: 60, lang: 'zh' });
    await c.setSource('fp-e04', '07', 'cloud:veo/veo-3.1-fast');
    await c.estimate('fp-e04', 'finals', ['07', '11']);
    await c.run('fp-e04', { stage: 'finals', estimate_id: 'est-0123456789', confirm_code: 'deadbeef', max_cny: 68 });
    await c.handoff('fp-e04', ['zh', 'en'], false);
    await c.ingest('/Users/me/.config/vstudio/recordings/x', 'project:talkinghead');
    await c.setCap(300);
    expect(calls.map((x) => `${x.init?.method} ${x.url.replace('app://desk', '')}`)).toEqual([
      'GET /api/create/formats',
      'POST /api/create/plan',
      'POST /api/create/episodes/fp-e04/shots/07',
      'GET /api/create/episodes/fp-e04/estimate?stage=finals&only=07,11',
      'POST /api/create/episodes/fp-e04/run',
      'POST /api/create/episodes/fp-e04/handoff',
      'POST /api/create/record/ingest',
      'POST /api/create/spend/cap',
    ]);
    expect(JSON.parse(String(calls[4].init?.body))).toEqual({ stage: 'finals', estimate_id: 'est-0123456789', confirm_code: 'deadbeef', max_cny: 68 });
    expect((calls[0].init?.headers as Record<string, string>).Authorization).toBe('Bearer tok');
  });

  it('refuses bad ids, shots, sources and confirm codes before any request', () => {
    const { f, calls } = fakeFetch();
    const c = new CreateClient((m, p, b) => f(p, { method: m, body: JSON.stringify(b) }).then((r) => r.json()));
    expect(() => c.episode('../etc')).toThrow();
    expect(() => c.setSource('ep-e01', '7a', 'record')).toThrow();
    expect(() => c.setSource('ep-e01', '07', 'https://evil.example')).toThrow();
    expect(() => c.run('ep-e01', { stage: 'finals', confirm_code: 'XYZ' })).toThrow();
    expect(calls).toEqual([]);
  });

  it('formats money and source swatches', () => {
    expect(yuan(53)).toBe('¥53');
    expect(yuan(5)).toBe('¥5');
    expect(yuan(3.41)).toBe('¥3.4');
    expect(yuan(null)).toBe('¥–');
    expect(swatch('mcp', 'kling-mcp')).toBe('kling');
    expect(swatch('cloud', 'minimax')).toBe('hailuo');
    expect(swatch('manual', 'jimeng')).toBe('seed');
    expect(swatch('record')).toBe('record');
  });
});

describe('Create routes', () => {
  afterEach(() => setCreatePrefs({ createPage: false }));

  it('round-trips every screen', () => {
    const rs: CreateRoute[] = [
      { screen: 'home' },
      { screen: 'series', sid: 'if-ads', tab: 'bible' },
      { screen: 'series', sid: 'if-ads', tab: 'making' },
      { screen: 'episode', eid: 'if-ads-e04', tab: 'storyboard' },
      { screen: 'episode', eid: 'if-ads-e04', tab: 'takes' },
      { screen: 'record' },
      { screen: 'record', eid: 'if-ads-e04', shot: '07' },
      { screen: 'record', sid: 'if-ads' },
    ];
    setCreatePrefs({ createPage: true });
    for (const r of rs) {
      const h = createHref(r);
      const top = parseRoute(h);
      expect(top.name).toBe('create');
      expect(parseCreate(top.name === 'create' ? top.path : [])).toEqual(r);
      expect(href(top)).toBe(h);
    }
    // Settings › Video generation is a section of the settings sub-nav (settings/registry.ts)
    expect(parseRoute('#/settings/video')).toEqual({ name: 'settings', section: 'video' });
    expect(parseCreate(['e', 'BAD!'])).toEqual({ screen: 'home' });
  });

  it('with the flag off every create hash lands on Home (and video settings on Settings)', () => {
    setCreatePrefs({ createPage: false });
    expect(parseRoute('#/create')).toEqual({ name: 'home' });
    expect(parseRoute('#/create/e/if-ads-e04/storyboard')).toEqual({ name: 'home' });
    expect(parseRoute('#/settings/video')).toEqual({ name: 'settings', section: 'video' }); // hidden: the shell shows General
    expect(parseRoute('#/inbox')).toEqual({ name: 'inbox' });
  });
});

describe('recorder IPC + permissions', () => {
  it('validates rec:* payloads (chunk size, tracks, session ids)', () => {
    const ok = { sessionId: '20261006-120000-side-hustle', track: 'camera', seq: 0, data: new Uint8Array([1, 2, 3]) };
    expect(validateIpc('rec:chunk', ok)).toMatchObject({ track: 'camera', seq: 0 });
    expect(() => validateIpc('rec:chunk', { ...ok, data: new Uint8Array(MAX_CHUNK + 1) })).toThrow();
    expect(() => validateIpc('rec:chunk', { ...ok, data: new Uint8Array(0) })).toThrow();
    expect(() => validateIpc('rec:chunk', { ...ok, track: 'speaker' })).toThrow();
    expect(() => validateIpc('rec:chunk', { ...ok, sessionId: '../../etc' })).toThrow();
    expect(() => validateIpc('rec:begin', { slug: 'Bad Slug', script: [], tracks: ['camera'] })).toThrow();
    expect(validateIpc('rec:begin', { slug: 'ep4', script: ['Line one.'], tracks: ['camera', 'mic'] })).toMatchObject({ slug: 'ep4' });
    expect(() => validateIpc('rec:mark', { sessionId: ok.sessionId, t: -1, kind: 'retake', line: 0 })).toThrow();
    expect(validateIpc('secrets:set', { name: 'kling', value: 'x'.repeat(1200) })).toMatchObject({ name: 'kling' });
    expect(() => validateIpc('secrets:set', { name: 'minimax', value: 'x'.repeat(401) })).toThrow();
  });

  it('allows camera / mic only from our window and origin with the flag on', () => {
    const base = { flag: true, fromMainWindow: true, isAppUrl: true, permission: 'media', mediaTypes: ['video', 'audio'] };
    expect(allowMedia(base)).toBe(true);
    expect(allowMedia({ ...base, flag: false })).toBe(false);
    expect(allowMedia({ ...base, fromMainWindow: false })).toBe(false);
    expect(allowMedia({ ...base, isAppUrl: false })).toBe(false);
    expect(allowMedia({ ...base, permission: 'geolocation' })).toBe(false);
    // getDisplayMedia asks for 'media' with no types (Electron 44): the screen she picked must get through
    expect(allowMedia({ ...base, mediaTypes: [] })).toBe(true);
    expect(allowMedia({ ...base, mediaTypes: [], flag: false })).toBe(false);
    expect(allowMedia({ ...base, mediaTypes: ['video', 'screen'] })).toBe(false);
    expect(createFlagFrom(undefined, undefined)).toBe(true);
    expect(createFlagFrom(false, undefined)).toBe(false);
    expect(createFlagFrom(true, '0')).toBe(false);
    expect(createFlagFrom(false, '1')).toBe(true);
  });

  it('adds blob: to media-src only with the Create page on', () => {
    expect(buildCsp({ dev: false })).toContain("media-src 'self' vsmedia:;");
    expect(buildCsp({ dev: false, create: true })).toContain("media-src 'self' vsmedia: blob:;");
  });

  it('picks a recording format and paces the prompter', () => {
    expect(pickMime(['video/webm;codecs=vp9', 'video/webm'], (x) => x === 'video/webm')).toBe('video/webm');
    expect(pickMime(['a'], () => false)).toBeUndefined();
    expect(lineSeconds('one two three four five six seven')).toBeCloseTo(3, 0);
    expect(lineSeconds('我的副业上个月赚了三百一十二块')).toBeGreaterThan(1.2);
  });
});

describe('no hard-coded copy in create/', () => {
  it('every user-facing string comes from the locale files', () => {
    const root = path.resolve(import.meta.dirname, '../../src/renderer/src/create');
    const offenders: string[] = [];
    const walk = (d: string) => {
      for (const f of fs.readdirSync(d)) {
        const p = path.join(d, f);
        if (fs.statSync(p).isDirectory()) walk(p);
        else if (f.endsWith('.tsx')) {
          const src = fs.readFileSync(p, 'utf8').replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
          src.split('\n').forEach((line, i) => {
            if (/[一-鿿]/.test(line)) offenders.push(`${f}:${i + 1} CJK: ${line.trim()}`);
            const jsxText = line.match(/[^=]>\s*([A-Za-z][A-Za-z ,.'!?]{2,})\s*<\//);
            if (jsxText) offenders.push(`${f}:${i + 1} text: ${jsxText[1]}`);
            const attr = line.match(/\b(placeholder|title|aria-label)="([A-Za-z][^"]{2,})"/);
            if (attr) offenders.push(`${f}:${i + 1} ${attr[1]}: ${attr[2]}`);
          });
        }
      }
    };
    walk(root);
    expect(offenders).toEqual([]);
  });
});
