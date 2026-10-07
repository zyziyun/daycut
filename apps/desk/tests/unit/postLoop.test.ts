// The publish loop: due posts on a fake clock, the scheduler (one notification per post, overdue on launch, the
// API path with publishAt / retries / fallback), which file and text a post gets, the success signal, title
// counting, session-cookie login detection, the text selectors, and YouTube over mocked HTTP.
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { loadAdapters } from '../../src/main/publish/adapters';
import { ApiVault } from '../../src/main/publish/api/vault';
import { YouTubeApi, ytMeta, YT_SCOPE } from '../../src/main/publish/api/youtube';
import { probeLogin } from '../../src/main/publish/loginProbe';
import { PublishScheduler } from '../../src/main/publish/scheduler';
import { saveCapture } from '../../src/main/publish/capture';
import { sessionLoginState } from '../../src/shared/channels';
import { partitionFor, validateIpc } from '../../src/shared/ipc';
import { parseAdapter } from '../../src/shared/publish/adapterSchema';
import { copyForPost, duePosts, localDate, pickFile, postedSignal, titleLength, upcomingPosts } from '../../src/shared/publish/postNow';
import { findJs, parseSelector, selectorError } from '../../src/shared/publish/selectors';
import type { CalendarPost } from '../../src/shared/v04';

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-loop-'));
const post = (id: string, at: string, extra: Partial<CalendarPost> = {}): CalendarPost => ({ id, item: 'aaaaaaaaaaaa', clip: 'A', title: '再小的博主，也是博主', cover: null, platform: 'xiaohongshu', at, state: 'ready', ...extra });
const adapters = loadAdapters([path.resolve(__dirname, '../../adapters')]).adapters;
const by = Object.fromEntries(adapters.map((a) => [a.id, a]));
/** a fake crypto: reversible, like safeStorage with a keychain */
const crypto = { isEncryptionAvailable: () => true, encryptString: (s: string) => Buffer.from(`enc:${s}`), decryptString: (b: Buffer) => b.toString().replace(/^enc:/, '') };

describe('due posts', () => {
  const now = new Date(2026, 9, 7, 20, 5); // Wed 7 Oct 2026, 20:05 local
  it('local "at" times; due = time passed, not posted, switched on, within 14 days', () => {
    expect(localDate('2026-10-07T20:00').getHours()).toBe(20);
    const ps = [post('p1', '2026-10-07T20:00'), post('p2', '2026-10-07T20:30'), post('p3', '2026-10-07T19:00', { state: 'posted' }), post('p4', '2026-10-06T09:00', { enabled: false }), post('p5', '2026-09-01T09:00'), post('p6', '2026-10-05T08:00')];
    expect(duePosts(ps, now).map((p) => p.id)).toEqual(['p6', 'p1']);
    expect(upcomingPosts(ps, now, 30 * 60_000).map((p) => p.id)).toEqual(['p2']);
  });
});

describe('scheduler', () => {
  const mk = (posts: CalendarPost[], clock: { t: Date }, extra: Partial<ConstructorParameters<typeof PublishScheduler>[0]> = {}) => {
    const notified: string[][] = [];
    const posted: string[] = [];
    const s = new PublishScheduler({
      load: async () => posts,
      now: () => clock.t,
      notify: (fresh) => notified.push(fresh.map((p) => p.id)),
      markPosted: async (p) => void posted.push(p.id),
      stateFile: path.join(tmp(), 'scheduler.json'),
      ...extra,
    });
    return { s, notified, posted };
  };

  it('announces each post once when its time comes; overdue ones at launch; moving a post re-announces it', async () => {
    const clock = { t: new Date(2026, 9, 7, 19, 59) };
    const ps = [post('p1', '2026-10-07T20:00'), post('old', '2026-10-06T21:00')];
    const { s, notified } = mk(ps, clock);
    let r = await s.tick();
    expect(r.due.map((p) => p.id)).toEqual(['old']); // came due while the app was closed
    expect(notified).toEqual([['old']]);
    clock.t = new Date(2026, 9, 7, 20, 0, 30);
    r = await s.tick();
    expect(r.due.map((p) => p.id)).toEqual(['old', 'p1']);
    expect(notified).toEqual([['old'], ['p1']]);
    await s.tick();
    expect(notified.length).toBe(2); // once
    ps[0] = { ...ps[0], at: '2026-10-07T20:00' };
    ps[1] = { ...ps[1], at: '2026-10-07T18:00' }; // she moved it: a new time is a new announcement
    await s.tick();
    expect(notified[2]).toEqual(['old']);
    ps[0] = { ...ps[0], state: 'posted' };
    r = await s.tick();
    expect(r.due.map((p) => p.id)).toEqual(['old']);
  });

  it('the state survives a restart (no second notification for the same post)', async () => {
    const clock = { t: new Date(2026, 9, 7, 21, 0) };
    const file = path.join(tmp(), 's.json');
    const ps = [post('p1', '2026-10-07T20:00')];
    const n1: string[] = [];
    const a = new PublishScheduler({ load: async () => ps, now: () => clock.t, notify: (f) => n1.push(...f.map((p) => p.id)), markPosted: async () => undefined, stateFile: file });
    await a.tick();
    const n2: string[] = [];
    const b = new PublishScheduler({ load: async () => ps, now: () => clock.t, notify: (f) => n2.push(...f.map((p) => p.id)), markPosted: async () => undefined, stateFile: file });
    const r = await b.tick();
    expect(n1).toEqual(['p1']);
    expect(n2).toEqual([]);
    expect(r.due.map((p) => p.id)).toEqual(['p1']); // still due (she has not posted it)
  });

  it('API posts upload an hour ahead with publishAt, never show as hers; failures retry, then fall back to her', async () => {
    const clock = { t: new Date(2026, 9, 7, 19, 30) };
    const yt = post('y1', '2026-10-07T20:00', { platform: 'youtube' });
    const calls: { id: string; at: Date | null }[] = [];
    let fail = false;
    const { s, notified, posted } = mk([yt, post('x1', '2026-10-07T20:00')], clock, {
      api: {
        wants: (p) => p.platform === 'youtube',
        publish: async (p, at) => {
          calls.push({ id: p.id, at });
          return fail ? { ok: false, error: 'quotaExceeded' } : { ok: true, url: 'https://youtu.be/abc' };
        },
      },
    });
    await s.tick();
    expect(calls).toEqual([{ id: 'y1', at: localDate('2026-10-07T20:00') }]);
    expect(posted).toEqual(['y1']);
    await s.tick();
    expect(calls.length).toBe(1);
    clock.t = new Date(2026, 9, 7, 20, 1);
    const r = await s.tick();
    expect(r.due.map((p) => p.id)).toEqual(['x1']); // y1 went through the API
    expect(notified.flat()).toEqual(['x1']);

    // failing API: retried (not announced) until 3 tries, then she gets the notification
    const clock2 = { t: new Date(2026, 9, 8, 9, 5) };
    const y2 = post('y2', '2026-10-08T09:00', { platform: 'youtube' });
    calls.length = 0;
    fail = true;
    const m = mk([y2], clock2, { api: { wants: () => true, publish: async (p, at) => (calls.push({ id: p.id, at }), { ok: false, error: 'quotaExceeded' }) } });
    await m.s.tick();
    expect(calls[0].at).toBeNull(); // late: public now, no publishAt
    expect(m.notified).toEqual([]);
    clock2.t = new Date(2026, 9, 8, 9, 20);
    await m.s.tick();
    clock2.t = new Date(2026, 9, 8, 9, 35);
    const last = await m.s.tick();
    expect(calls.length).toBe(3);
    expect(last.due.map((p) => p.id)).toEqual(['y2']);
    expect(m.notified).toEqual([['y2']]);
    expect(m.s.apiState('y2')).toMatchObject({ status: 'failed', tries: 3, detail: 'quotaExceeded' });
  });

  it('more than apiGraceMs late: no automatic upload, she decides', async () => {
    const clock = { t: new Date(2026, 9, 8, 18, 0) };
    const publish = vi.fn();
    const { s, notified } = mk([post('y3', '2026-10-08T09:00', { platform: 'youtube' })], clock, { api: { wants: () => true, publish } });
    await s.tick();
    expect(publish).not.toHaveBeenCalled();
    expect(notified).toEqual([['y3']]);
  });
});

describe('what a scheduled post sends', () => {
  const files = [
    { path: '/o/A_9x16.mp4', aspect: '9:16' },
    { path: '/o/A_3x4.mp4', aspect: '3:4' },
    { path: '/o/A_16x9.mp4', aspect: '16:9' },
  ];
  it('the file made for the platform, else the aspect it posts', () => {
    expect(pickFile(files, 'xiaohongshu')?.path).toBe('/o/A_3x4.mp4');
    expect(pickFile(files, 'xiaohongshu:full')?.path).toBe('/o/A_9x16.mp4');
    expect(pickFile(files, 'douyin')?.path).toBe('/o/A_9x16.mp4');
    expect(pickFile(files, 'youtube')?.path).toBe('/o/A_16x9.mp4');
    expect(pickFile([...files, { path: '/o/A_dy.mp4', aspect: '9:16', platform: 'douyin' }], 'douyin')?.path).toBe('/o/A_dy.mp4');
    expect(pickFile([], 'x')).toBeNull();
  });
  it('title from the post; the caption without the repeated title; the tag line becomes tags', () => {
    const p = { title: '再小的博主，也是博主', caption: '再小的博主，也是博主\n\n正文第一行\n第二行\n\n#副业 #口播' };
    expect(copyForPost(p, true)).toEqual({ title: '再小的博主，也是博主', description: '正文第一行\n第二行', tags: ['副业', '口播'] });
    expect(copyForPost({ ...p, title: '新标题' }, true, ['再小的博主，也是博主'])).toEqual({ title: '新标题', description: '正文第一行\n第二行', tags: ['副业', '口播'] });
    expect(copyForPost(p, false)).toEqual({ title: '', description: '再小的博主，也是博主\n\n正文第一行\n第二行', tags: ['副业', '口播'] });
  });
  it('小红书 counts latin letters as half', () => {
    expect(titleLength('xiaohongshu', '再小的博主')).toBe(5);
    expect(titleLength('xiaohongshu:full', 'ab 再')).toBe(2.5);
    expect(titleLength('douyin', 'ab 再')).toBe(4);
  });
});

describe('success after her click', () => {
  it('a success URL or text; the post link when the page shows one', () => {
    const s = by.xiaohongshu.success!;
    expect(postedSignal('https://creator.xiaohongshu.com/publish/publish', '上传视频', [], s)).toEqual({ posted: false, url: null });
    expect(postedSignal('https://creator.xiaohongshu.com/publish/success?x=1', '', ['https://www.xiaohongshu.com/explore/66f0a1b2c3d4e5f60718293a?xsec=1'], s)).toEqual({ posted: true, url: 'https://www.xiaohongshu.com/explore/66f0a1b2c3d4e5f60718293a' });
    expect(postedSignal('https://creator.xiaohongshu.com/publish/publish', '发布成功 去看看', [], s)).toEqual({ posted: true, url: null });
    expect(postedSignal('https://x', '发布成功', [], null)).toEqual({ posted: false, url: null });
    expect(postedSignal('https://creator.douyin.com/creator-micro/content/manage', '', ['https://www.douyin.com/video/7412345678901234567'], by.douyin.success!).url).toBe('https://www.douyin.com/video/7412345678901234567');
  });
});

describe('login from session cookies', () => {
  const xhs = by.xiaohongshu;
  it('signed in on any page once the session cookie is set (the creator home too); none = signed out', () => {
    expect(sessionLoginState([{ name: 'galaxy_creator_session_id', value: 'x', domain: '.xiaohongshu.com' }], xhs)).toBe('in');
    expect(sessionLoginState([{ name: 'web_session', value: 'x', domain: '.xiaohongshu.com' }], xhs)).toBe('out'); // a guest cookie
    expect(sessionLoginState([{ name: 'galaxy_creator_session_id', value: '', domain: '.xiaohongshu.com' }], xhs)).toBe('out');
    expect(sessionLoginState([{ name: 'galaxy_creator_session_id', value: 'x', domain: '.xiaohongshu.com', expirationDate: 1000 }], xhs, 2000)).toBe('out');
    expect(sessionLoginState([{ name: 'galaxy_creator_session_id', value: 'x', domain: '.evil.com' }], xhs)).toBe('out');
    expect(sessionLoginState([], { session: null })).toBeNull();
  });
  it('the probe reads only the named cookies of the partition the panel uses', async () => {
    const asked: unknown[] = [];
    const jar = { cookies: { get: async (f: Record<string, unknown>) => (asked.push(f), f.name === 'access-token-creator.xiaohongshu.com' ? [{ name: f.name as string, value: 'secret-value', domain: 'creator.xiaohongshu.com' }] : []) } };
    expect(await probeLogin(jar, xhs)).toBe('in');
    expect(asked.every((f) => typeof (f as { name?: string }).name === 'string')).toBe(true);
    expect(partitionFor('xiaohongshu', 'main')).toBe('persist:xiaohongshu-main');
  });
});

describe('text selectors', () => {
  it('parse and validate', () => {
    expect(parseSelector('button:has-text(/^\\s*发布\\s*$/)')).toEqual({ css: 'button', kind: 'has-text', regex: { source: '^\\s*发布\\s*$', flags: '' } });
    expect(parseSelector('input:near-text(标题)')).toEqual({ css: 'input', kind: 'near-text', text: '标题' });
    expect(parseSelector('input[type="file"]')).toEqual({ css: 'input[type="file"]', kind: 'css' });
    expect(selectorError('button:has-text(/[/)')).toMatch(/bad regular expression/);
    expect(findJs(['a'], true)).toContain('getClientRects');
    const bad = { ...JSON.parse(fs.readFileSync(path.resolve(__dirname, '../../adapters/douyin.json'), 'utf8')) };
    bad.publishButton = { selectors: ['button:has-text(/(/)'] };
    expect(parseAdapter(bad).ok).toBe(false);
  });
  it('小红书 and 抖音: never a click, title limits, publish button only outlined', () => {
    for (const a of [by.xiaohongshu, by.douyin]) {
      expect(a.status).toBe('unverified');
      expect(a.publishButton?.selectors.some((s) => s.includes('发布'))).toBe(true);
      expect(a.fields.cover).toBeNull();
    }
    expect(by.xiaohongshu.fields.title?.maxLength).toBe(20);
    expect(by.douyin.fields.title?.maxLength).toBe(30);
  });
});

describe('page capture file', () => {
  it('writes a local html file with a header saying what was removed', () => {
    const dir = tmp();
    const f = saveCapture(dir, 'xiaohongshu', { url: 'https://creator.xiaohongshu.com/publish/publish', title: 't', html: '<html></html>', nodes: 3 }, new Date('2026-10-07T12:00:00Z'));
    expect(path.basename(f)).toBe('xiaohongshu-2026-10-07T12-00-00.html');
    expect(fs.readFileSync(f, 'utf8')).toMatch(/No cookies/);
  });
});

describe('YouTube Data API (mocked HTTP)', () => {
  it('metadata: private + publishAt ahead, public when late; YouTube’s limits', () => {
    const at = new Date('2026-10-07T12:00:00Z');
    expect(ytMeta({ title: 'a<b>', description: 'd', tags: ['#x', 'y'], publishAt: at })).toEqual({
      snippet: { title: 'ab', description: 'd', tags: ['x', 'y'], categoryId: '22' },
      status: { privacyStatus: 'private', publishAt: '2026-10-07T12:00:00.000Z', selfDeclaredMadeForKids: false },
    });
    expect(ytMeta({ title: 't'.repeat(150), description: '', tags: [], publishAt: null }).snippet.title.length).toBe(100);
    expect(ytMeta({ title: 't', description: '', tags: [], publishAt: null }).status.privacyStatus).toBe('public');
  });

  it('connect: system browser consent with PKCE + loopback, the refresh token goes to the keychain; upload: resumable', async () => {
    const dir = tmp();
    const vault = new ApiVault(dir, crypto, 'darwin');
    const seen: { url: string; init?: RequestInit }[] = [];
    const fetchMock = (async (url: string | URL, init?: RequestInit) => {
      const u = String(url);
      seen.push({ url: u, init });
      if (u === 'https://oauth2.googleapis.com/token') {
        const body = new URLSearchParams(String(init!.body));
        if (body.get('grant_type') === 'authorization_code') {
          expect(body.get('code')).toBe('the-code');
          expect(body.get('code_verifier')!.length).toBeGreaterThan(40);
          expect(body.get('redirect_uri')).toMatch(/^http:\/\/127\.0\.0\.1:\d+$/);
          return new Response(JSON.stringify({ access_token: 'at1', refresh_token: 'rt1', expires_in: 3600, scope: YT_SCOPE }), { status: 200 });
        }
        return new Response(JSON.stringify({ access_token: 'at2', expires_in: 3600 }), { status: 200 });
      }
      if (u.startsWith('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable')) {
        const meta = JSON.parse(String(init!.body));
        expect(meta.status.publishAt).toBe('2026-10-07T12:00:00.000Z');
        expect((init!.headers as Record<string, string>).Authorization).toBe('Bearer at1');
        return new Response('', { status: 200, headers: { Location: 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=U1' } });
      }
      if (u === 'https://www.googleapis.com/upload/youtube/v3/videos?upload_id=U1') {
        expect(init!.method).toBe('PUT');
        return new Response(JSON.stringify({ id: 'vid123', status: { privacyStatus: 'private' } }), { status: 200 });
      }
      if (u.startsWith('https://oauth2.googleapis.com/revoke')) return new Response('', { status: 200 });
      throw new Error(`unexpected ${u}`);
    }) as typeof fetch;
    let consent = '';
    const yt = new YouTubeApi({
      vault,
      fetch: fetchMock,
      // the "browser": Google's consent page redirects back to the loopback port with a code
      openExternal: (url) => {
        consent = url;
        const q = new URL(url).searchParams;
        setTimeout(() => http.get(`${q.get('redirect_uri')}/?code=the-code&state=${q.get('state')}`, (r) => r.resume()), 20);
      },
    });
    expect(() => yt.setClient('not-a-client', 'x')).toThrow(/client ID/);
    yt.setClient('1234-abc.apps.googleusercontent.com', 'GOCSPX-secret');
    expect(yt.status()).toEqual({ hasClient: true, connected: false, connectedAt: null });
    await yt.connect(5000);
    const q = new URL(consent).searchParams;
    expect(new URL(consent).origin).toBe('https://accounts.google.com');
    expect(q.get('scope')).toBe(YT_SCOPE);
    expect(q.get('code_challenge_method')).toBe('S256');
    expect(yt.status().connected).toBe(true);
    // nothing in plain text on disk
    const disk = fs.readFileSync(path.join(dir, 'publish-api.json'), 'utf8');
    expect(JSON.parse(Buffer.from(JSON.parse(disk).youtube, 'base64').toString().replace(/^enc:/, '')).refreshToken).toBe('rt1');
    expect(disk).not.toContain('rt1');

    const file = path.join(dir, 'v.mp4');
    fs.writeFileSync(file, 'video bytes');
    const r = await yt.upload({ file, title: '再小的博主', description: 'd', tags: ['副业'], publishAt: new Date('2026-10-07T12:00:00Z') });
    expect(r).toEqual({ id: 'vid123', url: 'https://youtu.be/vid123', privacy: 'private' });
    await yt.disconnect();
    expect(yt.status().connected).toBe(false);
    expect(seen.some((s) => s.url.startsWith('https://oauth2.googleapis.com/revoke'))).toBe(true);
  });

  it('a consent that comes back with an error or a wrong state is refused', async () => {
    const vault = new ApiVault(tmp(), crypto, 'darwin');
    const yt = new YouTubeApi({
      vault,
      fetch: (async () => new Response('{}')) as typeof fetch,
      openExternal: (url) => {
        const q = new URL(url).searchParams;
        setTimeout(() => http.get(`${q.get('redirect_uri')}/?code=c&state=forged`, (r) => r.resume()), 20);
      },
    });
    yt.setClient('1234-abc.apps.googleusercontent.com', 'GOCSPX-secret');
    await expect(yt.connect(5000)).rejects.toThrow();
    expect(yt.status().connected).toBe(false);
  });

  it('no keychain: nothing is stored', () => {
    const v = new ApiVault(tmp(), { ...crypto, isEncryptionAvailable: () => false }, 'darwin');
    expect(() => v.set('youtube', { clientId: 'x' })).toThrow(/keychain/);
  });
});

describe('IPC for the loop', () => {
  it('validates post ids, client ids and the open-at-login switch', () => {
    expect(() => validateIpc('publish:fillPost', { postId: 'abc' })).toThrow();
    expect(validateIpc('publish:fillPost', { postId: '0123456789ab', account: 'main' })).toEqual({ postId: '0123456789ab', account: 'main' });
    expect(() => validateIpc('publish:apiConnect', { id: 'tiktok' })).toThrow();
    expect(validateIpc('settings:set', { openAtLogin: true })).toEqual({ openAtLogin: true });
  });
});
