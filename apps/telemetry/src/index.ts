// Reelfold usage counts: a Cloudflare Worker on https://t.reelfold.com (custom domain; see wrangler.jsonc) + D1.
//
//   POST   /api/v1/ping                 opt-in usage events from the desktop app ({ events: [...] }, schema.ts)
//   DELETE /api/v1/installs/<uuid>      "Delete my usage data" in the app: every row of that install id
//   GET    /api/v1/stats                Bearer STATS_TOKEN: the numbers (scripts/metrics/usage.py prints them)
//   POST   /api/v1/internal             Bearer STATS_TOKEN: { install_id, internal } marks the maintainer's installs
//   GET    /api/v1/health               "ok"
//   cron (daily)                        per-day aggregates (no install id, kept forever) + 13-month raw retention
//
// Privacy: the IP address is never stored or logged (it only lives in this isolate's memory for a minute, for rate
// limiting); no user agent, no headers, no cookies. Unknown fields in a request are never read (schema.ts).
import type { D1PreparedStatement, Env } from './d1';
import { addDays, cleanBody, isInstallId, MAX_BODY_BYTES, utcDay, type CleanEvent } from './schema';
import { computeStats, rollup } from './stats';

export type { Env } from './d1';

/** raw rows are kept 13 months */
export const RETENTION_DAYS = 396;
/** one install may not add more than this many events per (server) day */
export const MAX_EVENTS_PER_INSTALL_DAY = 200;
/** requests per minute per client address, per isolate (memory only) */
export const MAX_REQUESTS_PER_MINUTE = 30;

const hits = new Map<string, { at: number; n: number }>();

/** In-memory, per-isolate limiter keyed by the connecting address. Nothing is persisted. */
export function rateLimited(key: string, now = Date.now()): boolean {
  if (hits.size > 5000) for (const [k, v] of hits) if (now - v.at > 60_000) hits.delete(k);
  const h = hits.get(key);
  if (!h || now - h.at > 60_000) {
    hits.set(key, { at: now, n: 1 });
    return false;
  }
  h.n++;
  return h.n > MAX_REQUESTS_PER_MINUTE;
}

export function resetRateLimits() {
  hits.clear();
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' },
  });

async function sha256(s: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
}

/** constant-time check of "Authorization: Bearer <STATS_TOKEN>" */
export async function authorized(req: Request, env: Env): Promise<boolean> {
  const want = env.STATS_TOKEN ?? '';
  if (want.length < 16) return false;
  const got = (req.headers.get('authorization') ?? '').replace(/^Bearer\s+/i, '');
  const [a, b] = await Promise.all([sha256(got), sha256(want)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function readJson(req: Request): Promise<{ ok: true; body: unknown } | { ok: false; res: Response }> {
  const len = Number(req.headers.get('content-length') ?? '0');
  if (len > MAX_BODY_BYTES) return { ok: false, res: json({ error: 'too large' }, 413) };
  const text = await req.text();
  if (text.length > MAX_BODY_BYTES) return { ok: false, res: json({ error: 'too large' }, 413) };
  try {
    return { ok: true, body: JSON.parse(text) };
  } catch {
    return { ok: false, res: json({ error: 'bad json' }, 400) };
  }
}

const insertSql = `INSERT OR IGNORE INTO events
  (install_id, day, event, version, os, arch, locale, clips, formats, minutes_in, count, platform_count, received_day)
  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`;
const installSql = `INSERT INTO installs (install_id, first_day, last_day) VALUES (?, ?, ?)
  ON CONFLICT (install_id) DO UPDATE SET first_day = min(first_day, excluded.first_day), last_day = max(last_day, excluded.last_day)`;

export async function handlePing(req: Request, env: Env, today: string): Promise<Response> {
  const r = await readJson(req);
  if (!r.ok) return r.res;
  const { rows, dropped } = cleanBody(r.body, today);
  if (!rows.length) return json({ ok: false, accepted: 0, dropped }, 400);
  // per-install daily cap (counted on the server's day)
  const byInstall = new Map<string, CleanEvent[]>();
  for (const e of rows) byInstall.set(e.install_id, [...(byInstall.get(e.install_id) ?? []), e]);
  const stmts: D1PreparedStatement[] = [];
  let limited = 0;
  for (const [id, list] of byInstall) {
    const have = (await env.DB.prepare('SELECT COUNT(*) AS n FROM events WHERE install_id = ? AND received_day = ?').bind(id, today).first<{ n: number }>())?.n ?? 0;
    const room = Math.max(0, MAX_EVENTS_PER_INSTALL_DAY - have);
    const keep = list.slice(0, room);
    limited += list.length - keep.length;
    for (const e of keep) {
      stmts.push(
        env.DB.prepare(insertSql).bind(e.install_id, e.day, e.event, e.version, e.os, e.arch, e.locale, e.clips, e.formats, e.minutes_in, e.count, e.platform_count, today),
      );
    }
    if (keep.length) {
      const days = keep.map((e) => e.day).sort();
      stmts.push(env.DB.prepare(installSql).bind(id, days[0], days[days.length - 1]));
    }
  }
  if (stmts.length) await env.DB.batch(stmts);
  const accepted = rows.length - limited;
  if (!accepted) return json({ ok: false, accepted: 0, dropped, limited }, 429);
  return json({ ok: true, accepted, dropped, limited }, 202);
}

export async function handleDelete(id: string, env: Env): Promise<Response> {
  if (!isInstallId(id)) return json({ error: 'not an install id' }, 400);
  const res = await env.DB.batch([
    env.DB.prepare('DELETE FROM events WHERE install_id = ?').bind(id),
    env.DB.prepare('DELETE FROM installs WHERE install_id = ?').bind(id),
    env.DB.prepare('DELETE FROM internal_installs WHERE install_id = ?').bind(id),
  ]);
  return json({ ok: true, deleted: Number(res[0]?.meta?.changes ?? 0) });
}

export async function handleInternal(req: Request, env: Env, today: string): Promise<Response> {
  const r = await readJson(req);
  if (!r.ok) return r.res;
  const b = r.body as { install_id?: unknown; internal?: unknown; note?: unknown };
  if (!isInstallId(b?.install_id)) return json({ error: 'install_id must be the UUID shown in the app' }, 400);
  const note = typeof b.note === 'string' ? b.note.slice(0, 60) : null;
  if (b.internal === false) await env.DB.prepare('DELETE FROM internal_installs WHERE install_id = ?').bind(b.install_id).run();
  else await env.DB.prepare('INSERT OR REPLACE INTO internal_installs (install_id, note, added_day) VALUES (?, ?, ?)').bind(b.install_id, note, today).run();
  // recent aggregates are rebuilt without (or with) this install
  await rollup(env.DB, today);
  const list = await env.DB.prepare('SELECT install_id, note, added_day FROM internal_installs ORDER BY added_day').all();
  return json({ ok: true, internal: list.results });
}

/** daily cron: per-day aggregates for the recent days, then drop raw rows older than 13 months */
export async function scheduledWork(env: Env, today: string) {
  await rollup(env.DB, today);
  const cutoff = addDays(today, -RETENTION_DAYS);
  await env.DB.batch([
    env.DB.prepare('DELETE FROM events WHERE day < ?').bind(cutoff),
    env.DB.prepare('DELETE FROM installs WHERE last_day < ?').bind(cutoff),
  ]);
}

export async function handle(req: Request, env: Env, now = new Date()): Promise<Response> {
  const url = new URL(req.url);
  const today = utcDay(now);
  const path = url.pathname.replace(/\/+$/, '');
  if (path === '/api/v1/health' && req.method === 'GET') return json({ ok: true });
  const addr = req.headers.get('cf-connecting-ip') ?? 'unknown';
  if (rateLimited(addr, now.getTime())) return json({ error: 'slow down' }, 429);
  if (path === '/api/v1/ping') {
    if (req.method !== 'POST') return json({ error: 'method' }, 405);
    return handlePing(req, env, today);
  }
  const del = path.match(/^\/api\/v1\/installs\/([^/]+)$/);
  if (del) {
    if (req.method !== 'DELETE') return json({ error: 'method' }, 405);
    return handleDelete(decodeURIComponent(del[1]).toLowerCase(), env);
  }
  if (path === '/api/v1/stats' || path === '/api/v1/internal') {
    if (!env.STATS_TOKEN) return json({ error: 'stats are off: set the STATS_TOKEN secret' }, 503);
    if (!(await authorized(req, env))) return json({ error: 'unauthorized' }, 401);
    if (path === '/api/v1/internal') {
      if (req.method !== 'POST') return json({ error: 'method' }, 405);
      return handleInternal(req, env, today);
    }
    if (req.method !== 'GET') return json({ error: 'method' }, 405);
    await rollup(env.DB, today);
    return json(await computeStats(env.DB, today));
  }
  return json({ error: 'not found' }, 404);
}

export default {
  fetch(req: Request, env: Env): Promise<Response> {
    return handle(req, env).catch(() => json({ error: 'server error' }, 500));
  },
  scheduled(_event: unknown, env: Env, ctx: { waitUntil(p: Promise<unknown>): void }) {
    ctx.waitUntil(scheduledWork(env, utcDay(new Date())));
  },
};
