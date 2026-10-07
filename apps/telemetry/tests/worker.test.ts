import { beforeEach, describe, expect, it } from 'vitest';
import { handle, MAX_EVENTS_PER_INSTALL_DAY, MAX_REQUESTS_PER_MINUTE, resetRateLimits, scheduledWork, type Env } from '../src/index';
import { cleanEvent, MAX_BODY_BYTES } from '../src/schema';
import { fakeD1 } from './fakeD1';

const NOW = new Date('2026-10-14T12:00:00Z'); // a Wednesday
const TODAY = '2026-10-14';
const A = '11111111-1111-4111-8111-111111111111';
const B = '22222222-2222-4222-9222-222222222222';
const ME = '33333333-3333-4333-a333-333333333333';
const TOKEN = 'test-stats-token-0123456789';

const ev = (id: string, e: string, day = TODAY, n?: Record<string, unknown>, extra: Record<string, unknown> = {}) => ({
  id,
  v: '0.2.0',
  os: 'darwin',
  arch: 'arm64',
  locale: 'zh-CN',
  ev: e,
  day,
  ...(n ? { n } : {}),
  ...extra,
});

let db: ReturnType<typeof fakeD1>;
let env: Env;
let ip = 0;

beforeEach(() => {
  db = fakeD1();
  env = { DB: db, STATS_TOKEN: TOKEN };
  resetRateLimits();
});

function req(method: string, path: string, body?: unknown, headers: Record<string, string> = {}) {
  return new Request(`https://t.reelfold.com${path}`, {
    method,
    headers: { 'content-type': 'application/json', 'cf-connecting-ip': `203.0.113.${ip++ % 250}`, ...headers },
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
  });
}
const ping = (events: unknown[], now = NOW) => handle(req('POST', '/api/v1/ping', { events }), env, now);
const stats = async (now = NOW) => (await handle(req('GET', '/api/v1/stats', undefined, { authorization: `Bearer ${TOKEN}` }), env, now)).json() as Promise<Record<string, any>>;
const all = () => db.raw.prepare('SELECT * FROM events ORDER BY rowid').all() as Record<string, unknown>[];

describe('schema', () => {
  it('accepts exactly the documented fields and drops everything else', () => {
    const c = cleanEvent(ev(A, 'batch_done', TODAY, { clips: 12, formats: 3, minutes_in: 72, path: '/Users/me/a.mp4', count: 9 }, { file: 'a.mp4', ip: '1.2.3.4' }), TODAY);
    expect(c).toEqual({
      install_id: A,
      day: TODAY,
      event: 'batch_done',
      version: '0.2.0',
      os: 'darwin',
      arch: 'arm64',
      locale: 'zh-CN',
      clips: 12,
      formats: 3,
      minutes_in: 72,
      count: null, // not a batch_done number: not read
      platform_count: null,
    });
  });
  it.each([
    ['bad id', { ...ev(A, 'app_open'), id: 'not-a-uuid' }],
    ['unknown event', ev(A, 'clicked_button')],
    ['text in a number', ev(A, 'export_done', TODAY, { count: 'my video.mp4' })],
    ['negative', ev(A, 'export_done', TODAY, { count: -1 })],
    ['fraction', ev(A, 'export_done', TODAY, { count: 1.5 })],
    ['huge', ev(A, 'batch_done', TODAY, { clips: 1e9 })],
    ['a timestamp, not a day', { ...ev(A, 'app_open'), day: '2026-10-14T12:00:00Z' }],
    ['too old', ev(A, 'app_open', '2026-09-01')],
    ['in the future', ev(A, 'app_open', '2026-10-20')],
    ['unknown os', { ...ev(A, 'app_open'), os: 'Macintosh; Intel Mac OS X 10_15_7' }],
    ['unknown locale', { ...ev(A, 'app_open'), locale: 'zh-CN-u-ca-chinese' }],
    ['bad version', { ...ev(A, 'app_open'), v: '0.2.0 (build /Users/me)' }],
  ])('drops an event with %s', (_name, e) => {
    expect(cleanEvent(e, TODAY)).toBeNull();
  });
});

describe('POST /api/v1/ping', () => {
  it('stores valid events, never the address or unknown fields', async () => {
    const r = await ping([ev(A, 'app_open'), ev(A, 'batch_done', TODAY, { clips: 4, formats: 2, minutes_in: 30 }), { junk: true }]);
    expect(r.status).toBe(202);
    expect(await r.json()).toMatchObject({ accepted: 2, dropped: 1 });
    const rows = all();
    expect(rows).toHaveLength(2);
    expect(Object.keys(rows[0]).sort()).toEqual(
      ['arch', 'clips', 'count', 'day', 'event', 'formats', 'install_id', 'locale', 'minutes_in', 'os', 'platform_count', 'received_day', 'version'].sort(),
    );
    expect(JSON.stringify(rows)).not.toContain('203.0.113');
  });
  it('keeps app_open once per install per day and first_batch_done once per install', async () => {
    await ping([ev(A, 'app_open'), ev(A, 'app_open'), ev(A, 'first_batch_done')]);
    await ping([ev(A, 'app_open'), ev(A, 'first_batch_done', '2026-10-13'), ev(A, 'app_open', '2026-10-13')]);
    const rows = all().map((r) => `${r.event}@${r.day}`);
    expect(rows.sort()).toEqual(['app_open@2026-10-13', 'app_open@2026-10-14', 'first_batch_done@2026-10-14']);
  });
  it('rejects bad JSON, empty and oversized bodies', async () => {
    expect((await handle(req('POST', '/api/v1/ping', '{nope'), env, NOW)).status).toBe(400);
    expect((await ping([{ x: 1 }])).status).toBe(400);
    expect((await handle(req('POST', '/api/v1/ping', 'x'.repeat(MAX_BODY_BYTES + 1)), env, NOW)).status).toBe(413);
    expect((await handle(req('GET', '/api/v1/ping'), env, NOW)).status).toBe(405);
  });
  it('caps one install per day', async () => {
    const many = Array.from({ length: 50 }, () => ev(A, 'export_done', TODAY, { count: 1 }));
    for (let i = 0; i < MAX_EVENTS_PER_INSTALL_DAY / 50; i++) expect((await ping(many)).status).toBe(202);
    const r = await ping(many);
    expect(r.status).toBe(429);
    expect(all()).toHaveLength(MAX_EVENTS_PER_INSTALL_DAY);
    expect((await ping([ev(B, 'app_open')])).status).toBe(202); // others are unaffected
  });
  it('rate-limits one address per minute (in memory only)', async () => {
    const from = (i: number) => new Request('https://t.reelfold.com/api/v1/ping', { method: 'POST', headers: { 'cf-connecting-ip': '198.51.100.7' }, body: JSON.stringify(ev(A, 'app_open')) });
    const codes: number[] = [];
    for (let i = 0; i <= MAX_REQUESTS_PER_MINUTE; i++) codes.push((await handle(from(i), env, NOW)).status);
    expect(codes.slice(0, MAX_REQUESTS_PER_MINUTE).every((c) => c === 202)).toBe(true);
    expect(codes.at(-1)).toBe(429);
    expect((await handle(from(0), env, new Date(NOW.getTime() + 61_000))).status).toBe(202); // a minute later
  });
});

describe('DELETE /api/v1/installs/<id>', () => {
  it('deletes every row of that install and nothing else', async () => {
    await ping([ev(A, 'app_open'), ev(A, 'batch_done', TODAY, { clips: 1 }), ev(B, 'app_open')]);
    const r = await handle(req('DELETE', `/api/v1/installs/${A}`), env, NOW);
    expect(r.status).toBe(200);
    expect(await r.json()).toMatchObject({ ok: true, deleted: 2 });
    expect(all().map((x) => x.install_id)).toEqual([B]);
    expect(db.raw.prepare('SELECT install_id FROM installs').all()).toEqual([{ install_id: B }]);
  });
  it('needs a real install id', async () => {
    expect((await handle(req('DELETE', '/api/v1/installs/everything'), env, NOW)).status).toBe(400);
    expect((await handle(req('DELETE', "/api/v1/installs/1' OR '1'='1"), env, NOW)).status).toBe(400);
  });
});

describe('stats', () => {
  it('needs the token; off without the secret', async () => {
    expect((await handle(req('GET', '/api/v1/stats'), env, NOW)).status).toBe(401);
    expect((await handle(req('GET', '/api/v1/stats', undefined, { authorization: 'Bearer wrong-token-0123456789' }), env, NOW)).status).toBe(401);
    expect((await handle(req('GET', '/api/v1/stats', undefined, { authorization: `Bearer ${TOKEN}` }), { DB: db }, NOW)).status).toBe(503);
  });
  it('counts installs, active and real users, retention; excludes internal installs', async () => {
    // A: batches in two weeks (retained); B: opened the app only; ME: the maintainer
    await ping([ev(A, 'app_open', '2026-10-05'), ev(A, 'batch_done', '2026-10-05', { clips: 10, formats: 2, minutes_in: 60 }), ev(A, 'first_batch_done', '2026-10-05')], new Date('2026-10-06T10:00:00Z'));
    await ping([ev(A, 'app_open', '2026-10-13'), ev(A, 'batch_done', '2026-10-13', { clips: 5 }), ev(A, 'export_done', '2026-10-13', { count: 4 })]);
    await ping([ev(B, 'app_open', '2026-10-13'), { ...ev(B, 'app_open'), locale: 'en', v: '0.2.1' }]);
    await ping([ev(ME, 'app_open'), ev(ME, 'batch_done', TODAY, { clips: 99 }), ev(ME, 'publish_package', TODAY, { platform_count: 3 })]);
    let s = await stats();
    expect(s.real_users).toBe(2);
    const mark = await handle(req('POST', '/api/v1/internal', { install_id: ME, note: 'my mac' }, { authorization: `Bearer ${TOKEN}` }), env, NOW);
    expect(mark.status).toBe(200);
    s = await stats();
    expect(s).toMatchObject({ installs_ever: 2, dau: 2, wau: 2, mau: 2, real_users: 1, active_real_users_7d: 1, retained_users: 1, internal_installs: 1 });
    const w = Object.fromEntries(s.weekly.map((x: { week: string }) => [x.week, x]));
    expect(w['2026-10-05']).toMatchObject({ active: 1, new_installs: 1, batch_users: 1, batches: 1, clips_made: 10 });
    expect(w['2026-10-12']).toMatchObject({ active: 2, new_installs: 1, batches: 1, clips_made: 5, exports: 1, clips_exported: 4, packages: 0 });
    expect(s.by_version).toEqual(expect.arrayContaining([{ version: '0.2.0', installs: 1 }, { version: '0.2.1', installs: 1 }]));
    expect(s.by_locale).toEqual(expect.arrayContaining([{ locale: 'zh-CN', installs: 1 }, { locale: 'en', installs: 1 }]));
    expect(JSON.stringify(s)).not.toContain(A); // numbers only, no ids
  });
  it('internal marking needs the token', async () => {
    expect((await handle(req('POST', '/api/v1/internal', { install_id: ME }), env, NOW)).status).toBe(401);
  });
});

describe('daily cron', () => {
  it('drops raw rows after 13 months; installs ever survives through the aggregates', async () => {
    const old = '2025-08-01';
    const ins = db.raw.prepare(
      "INSERT INTO events (install_id, day, event, version, os, arch, locale, received_day) VALUES (?, ?, 'app_open', '0.1.0', 'darwin', 'arm64', 'en', ?)",
    );
    ins.run(B, old, old);
    db.raw.prepare('INSERT INTO installs VALUES (?, ?, ?)').run(B, old, old);
    // the aggregates for that day were made back then
    await scheduledWork(env, '2025-08-02');
    await ping([ev(A, 'app_open')]);
    await scheduledWork(env, TODAY);
    expect(all().map((r) => r.install_id)).toEqual([A]);
    expect(db.raw.prepare('SELECT install_id FROM installs').all()).toEqual([{ install_id: A }]);
    const s = await stats();
    expect(s.installs_ever).toBe(2);
    expect(db.raw.prepare("SELECT installs FROM daily_agg WHERE day = ? AND event = 'new_install'").get(old)).toEqual({ installs: 1 });
  });
});

describe('routing', () => {
  it('health, 404', async () => {
    expect((await handle(req('GET', '/api/v1/health'), env, NOW)).status).toBe(200);
    expect((await handle(req('GET', '/'), env, NOW)).status).toBe(404);
  });
});
