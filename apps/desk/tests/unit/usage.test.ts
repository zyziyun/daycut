// Opt-in anonymous usage counts (src/main/usage.ts): consent off = no network at all, the exact payload shape,
// the offline queue, once-per-day / once-ever events, delete + reset, and the env gate (dev / tests / CI never send).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { validateIpc } from '../../src/shared/ipc';
import { buildEvent, UsageReporter, usageAllowedByEnv, type UsageDeps } from '../../src/main/usage';

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-usage-'));
type Call = { url: string; method: string; body: unknown };

function setup({ consent, online, ...over }: Partial<Omit<UsageDeps, 'consent'>> & { consent?: boolean; online?: boolean } = {}) {
  const calls: Call[] = [];
  const net = { online: online ?? true, status: 202 };
  const fetchMock = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined });
    if (!net.online) throw new TypeError('fetch failed');
    return new Response(JSON.stringify({ ok: true, deleted: 3 }), { status: init?.method === 'DELETE' ? 200 : net.status });
  });
  const state = { consent: consent ?? true, now: new Date('2026-10-14T09:30:00Z') };
  const dir = over.dir ?? tmp();
  const r = new UsageReporter({
    dir,
    consent: () => state.consent,
    allowed: true,
    version: '0.2.0',
    platform: 'darwin',
    arch: 'arm64',
    lang: () => 'zh-CN',
    fetch: fetchMock as unknown as typeof fetch,
    now: () => state.now,
    ...over,
  });
  return { r, calls, fetchMock, net, state, dir, file: path.join(dir, 'usage.json') };
}

describe('consent off', () => {
  it('sends nothing, queues nothing, makes no id', async () => {
    const { r, fetchMock, file } = setup({ consent: false });
    r.track('app_open');
    r.track('batch_done', { clips: 3 });
    r.track('export_done', { count: 2 });
    r.track('publish_package', { platform_count: 4 });
    await r.flush();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(r.status()).toMatchObject({ on: false, installId: null, queued: 0 });
    expect(fs.existsSync(file)).toBe(false);
  });
  it('a build that may not send (dev / tests / CI) sends nothing even with consent', async () => {
    const { r, fetchMock } = setup({ allowed: false });
    r.track('app_open');
    await r.flush();
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it('turning sharing off empties the queue', async () => {
    const { r, state, fetchMock } = setup({ online: false });
    r.track('batch_done', { clips: 1 });
    await r.flush();
    expect(r.status().queued).toBe(2); // first_batch_done + batch_done
    state.consent = false;
    r.consentChanged(false);
    expect(r.status().queued).toBe(0);
    const before = fetchMock.mock.calls.length;
    r.track('app_open');
    await r.flush();
    expect(fetchMock.mock.calls.length).toBe(before);
  });
});

describe('env gate', () => {
  it.each([
    [{}, true, true],
    [{}, false, false], // dev build
    [{ CI: 'true' }, true, false],
    [{ GITHUB_ACTIONS: 'true' }, true, false],
    [{ VITEST: 'true' }, true, false],
    [{ DESK_USER_DATA: '/tmp/x' }, true, false], // isolated test profile
    [{ DESK_HIDE_WINDOW: '1' }, true, false],
    [{ REELFOLD_USAGE: '1' }, false, true], // explicit opt-in for a dev build / test
    [{ REELFOLD_USAGE: '1', CI: 'true' }, true, true],
    [{ REELFOLD_USAGE: '0' }, true, false],
  ])('%j packaged=%s -> %s', (env, packaged, want) => {
    expect(usageAllowedByEnv(env as NodeJS.ProcessEnv, packaged)).toBe(want);
  });
});

describe('payload', () => {
  it('has exactly the documented fields', async () => {
    const { r, calls } = setup();
    r.track('app_open');
    r.track('batch_done', { clips: 12.4, formats: 3, minutes_in: 71.6 });
    r.track('export_done', { count: 5, clips: 99 } as never);
    r.track('publish_package', { platform_count: 4 });
    await r.flush();
    const sent = calls.flatMap((c) => (c.body as { events: unknown[] }).events);
    const id = r.status().installId;
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    const base = { id, v: '0.2.0', os: 'darwin', arch: 'arm64', locale: 'zh-CN', day: '2026-10-14' };
    expect(sent).toEqual([
      { ...base, ev: 'app_open' },
      { ...base, ev: 'first_batch_done' },
      { ...base, ev: 'batch_done', n: { clips: 12, formats: 3, minutes_in: 72 } },
      { ...base, ev: 'export_done', n: { count: 5 } }, // numbers of other events are not sent
      { ...base, ev: 'publish_package', n: { platform_count: 4 } },
    ]);
    expect(calls.every((c) => c.url === 'https://t.reelfold.com/api/v1/ping' && c.method === 'POST')).toBe(true);
  });
  it('snapshot of one event', () => {
    expect(
      buildEvent({ id: '11111111-1111-4111-8111-111111111111', version: '0.2.0', platform: 'darwin', arch: 'arm64', lang: 'fr', ev: 'batch_done', now: new Date('2026-10-14T23:59:59Z'), n: { clips: 8, formats: 2, minutes_in: 30 } }),
    ).toMatchInlineSnapshot(`
      {
        "arch": "arm64",
        "day": "2026-10-14",
        "ev": "batch_done",
        "id": "11111111-1111-4111-8111-111111111111",
        "locale": "fr",
        "n": {
          "clips": 8,
          "formats": 2,
          "minutes_in": 30,
        },
        "os": "darwin",
        "v": "0.2.0",
      }
    `);
  });
  it('the renderer can only pass small integers for three events', () => {
    expect(() => validateIpc('usage:track', { ev: 'batch_done', n: { clips: 3 } })).not.toThrow();
    expect(() => validateIpc('usage:track', { ev: 'batch_done', n: { clips: '/Users/me/a.mp4' } })).toThrow();
    expect(() => validateIpc('usage:track', { ev: 'batch_done', n: { title: 'x' } })).toThrow();
    expect(() => validateIpc('usage:track', { ev: 'app_open' })).toThrow();
    expect(() => validateIpc('usage:track', { ev: 'export_done', n: { count: 1.5 } })).toThrow();
    expect(() => validateIpc('usage:track', { ev: 'export_done', path: '/x' })).toThrow();
  });
});

describe('once per day / once ever', () => {
  it('app_open once a day; first_batch_done once', async () => {
    const { r, calls, state } = setup();
    r.track('app_open');
    r.track('app_open');
    r.track('batch_done');
    r.track('batch_done');
    state.now = new Date('2026-10-15T08:00:00Z');
    r.track('app_open');
    await r.flush();
    await r.flush();
    const evs = calls.flatMap((c) => (c.body as { events: { ev: string; day: string }[] }).events.map((e) => `${e.ev}@${e.day}`));
    expect(evs).toEqual(['app_open@2026-10-14', 'first_batch_done@2026-10-14', 'batch_done@2026-10-14', 'batch_done@2026-10-14', 'app_open@2026-10-15']);
  });
  it('the demo engine never counts batches', async () => {
    const { r, calls } = setup({ demo: () => true });
    r.track('batch_done', { clips: 2 });
    await r.flush();
    expect(calls).toHaveLength(0);
  });
});

describe('offline queue', () => {
  it('keeps events on disk while offline and sends them later, also after a restart', async () => {
    const a = setup({ online: false });
    a.r.track('app_open');
    a.r.track('export_done', { count: 2 });
    await a.r.flush();
    expect(a.r.status().queued).toBe(2);
    expect(JSON.parse(fs.readFileSync(a.file, 'utf8')).queue).toHaveLength(2);
    // next launch, online
    const b = setup({ dir: a.dir });
    expect(b.r.status().queued).toBe(2);
    await b.r.flush();
    expect(b.r.status().queued).toBe(0);
    expect((b.calls[0].body as { events: unknown[] }).events).toHaveLength(2);
    expect(b.r.status().lastSentDay).toBe('2026-10-14');
  });
  it('keeps the queue on a server error, drops events the server will never take, drops stale ones', async () => {
    const { r, net, state, calls } = setup();
    net.status = 503;
    r.track('app_open');
    await r.flush();
    expect(r.status().queued).toBe(1);
    net.status = 400;
    await r.flush();
    expect(r.status().queued).toBe(0);
    net.status = 503;
    r.track('export_done', { count: 1 });
    await r.flush();
    state.now = new Date('2026-11-14T09:00:00Z'); // a month later: too old for the server
    net.status = 202;
    const n = calls.length;
    await r.flush();
    expect(calls.length).toBe(n);
    expect(r.status().queued).toBe(0);
  });
  it('never throws into the caller and never waits for the network', () => {
    const { r } = setup({ fetch: (() => new Promise(() => undefined)) as unknown as typeof fetch });
    const t0 = Date.now();
    r.track('app_open');
    expect(Date.now() - t0).toBeLessThan(50);
  });
});

describe('delete and reset', () => {
  it('DELETE by install id, then a new id', async () => {
    const { r, calls } = setup();
    r.track('app_open');
    await r.flush();
    const id = r.status().installId!;
    const res = await r.deleteData();
    expect(res).toMatchObject({ ok: true, deleted: 3 });
    expect(calls.at(-1)).toMatchObject({ url: `https://t.reelfold.com/api/v1/installs/${id}`, method: 'DELETE' });
    expect(res.status.installId).not.toBe(id);
    expect(res.status.installId).toMatch(/^[0-9a-f-]{36}$/);
  });
  it('offline: nothing deleted, the id is kept so she can try again', async () => {
    const { r, net } = setup();
    r.track('app_open');
    await r.flush();
    const id = r.status().installId;
    net.online = false;
    const res = await r.deleteData();
    expect(res).toMatchObject({ ok: false, error: 'offline' });
    expect(res.status.installId).toBe(id);
  });
  it('reset gives a new id and drops what was queued', async () => {
    const { r } = setup({ online: false });
    r.track('app_open');
    await r.flush();
    const id = r.status().installId;
    const st = r.resetId();
    expect(st.installId).not.toBe(id);
    expect(st.queued).toBe(0);
  });
});
