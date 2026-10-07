// The numbers (GET /api/v1/stats) and the per-day aggregates (daily cron). Every query leaves out the installs in
// internal_installs (the maintainer's own Mac, test machines).
//
// Definitions (also in scripts/metrics/usage.py and the maintainer's notes):
//   installs ever       install ids ever seen (the app sends nothing until its user turns sharing on)
//   DAU                 installs with any event yesterday (the last complete UTC day)
//   WAU / MAU           installs with any event in the last 7 / 30 days (today included)
//   real users          installs that finished at least one batch (first_batch_done or batch_done)
//   active real users   installs with a finished batch in the last 7 days
//   retained            installs with a finished batch in at least 2 different weeks (weeks start on Monday)
import type { D1Database } from './d1';
import { addDays, MAX_AGE_DAYS } from './schema';

const NOT_INTERNAL = 'install_id NOT IN (SELECT install_id FROM internal_installs)';
const BATCH = "event IN ('batch_done', 'first_batch_done')";
/** Monday of the day's week, YYYY-MM-DD */
const WEEK = "date(day, '-6 days', 'weekday 1')";

async function n(db: D1Database, sql: string, ...args: unknown[]): Promise<number> {
  const r = await db.prepare(sql).bind(...args).first<{ n: number | null }>();
  return Number(r?.n ?? 0);
}

async function rows<T>(db: D1Database, sql: string, ...args: unknown[]): Promise<T[]> {
  return (await db.prepare(sql).bind(...args).all<T>()).results;
}

/** Rebuild daily_agg for the days that may still change (late, queued events), up to yesterday. */
export async function rollup(db: D1Database, today: string) {
  const from = addDays(today, -(MAX_AGE_DAYS + 1));
  await db.batch([
    db.prepare('DELETE FROM daily_agg WHERE day >= ? AND day < ?').bind(from, today),
    db
      .prepare(
        `INSERT INTO daily_agg (day, event, version, os, locale, events, installs, clips, minutes_in, count, platform_count)
         SELECT day, event, version, os, locale, COUNT(*), COUNT(DISTINCT install_id),
                COALESCE(SUM(clips), 0), COALESCE(SUM(minutes_in), 0), COALESCE(SUM(count), 0), COALESCE(SUM(platform_count), 0)
         FROM events WHERE day >= ? AND day < ? AND ${NOT_INTERNAL}
         GROUP BY day, event, version, os, locale`,
      )
      .bind(from, today),
    // new installs per first day (version / os / locale of that first day's first row)
    db
      .prepare(
        `INSERT OR REPLACE INTO daily_agg (day, event, version, os, locale, events, installs)
         SELECT i.first_day, 'new_install', e.version, e.os, e.locale, COUNT(*), COUNT(*)
         FROM installs i
         JOIN events e ON e.rowid = (SELECT rowid FROM events WHERE install_id = i.install_id AND day = i.first_day LIMIT 1)
         WHERE i.first_day >= ? AND i.first_day < ? AND i.install_id NOT IN (SELECT install_id FROM internal_installs)
         GROUP BY i.first_day, e.version, e.os, e.locale`,
      )
      .bind(from, today),
  ]);
}

export interface Stats {
  day: string;
  definitions: Record<string, string>;
  installs_ever: number;
  dau: number;
  wau: number;
  mau: number;
  real_users: number;
  active_real_users_7d: number;
  retained_users: number;
  internal_installs: number;
  weekly: { week: string; active: number; new_installs: number; batch_users: number; batches: number; clips_made: number; exports: number; clips_exported: number; packages: number }[];
  by_version: { version: string; installs: number }[];
  by_locale: { locale: string; installs: number }[];
  by_os: { os: string; arch: string; installs: number }[];
}

export async function computeStats(db: D1Database, today: string, weeks = 12): Promise<Stats> {
  const yesterday = addDays(today, -1);
  const d7 = addDays(today, -6);
  const d30 = addDays(today, -29);
  // installs ever: aggregated first days (rolled up, up to yesterday) + installs first seen today
  const rolled = await n(db, "SELECT SUM(installs) AS n FROM daily_agg WHERE event = 'new_install'");
  const fresh = await n(db, `SELECT COUNT(*) AS n FROM installs WHERE first_day >= ? AND ${NOT_INTERNAL}`, today);
  const sinceWeek = addDays(today, -7 * weeks);
  const weekly = await rows<Stats['weekly'][number]>(
    db,
    `SELECT ${WEEK} AS week,
            COUNT(DISTINCT install_id) AS active,
            COUNT(DISTINCT CASE WHEN ${BATCH} THEN install_id END) AS batch_users,
            SUM(CASE WHEN event = 'batch_done' THEN 1 ELSE 0 END) AS batches,
            COALESCE(SUM(CASE WHEN event = 'batch_done' THEN clips END), 0) AS clips_made,
            SUM(CASE WHEN event = 'export_done' THEN 1 ELSE 0 END) AS exports,
            COALESCE(SUM(CASE WHEN event = 'export_done' THEN count END), 0) AS clips_exported,
            SUM(CASE WHEN event = 'publish_package' THEN 1 ELSE 0 END) AS packages
     FROM events WHERE day >= ? AND ${NOT_INTERNAL} GROUP BY week ORDER BY week`,
    sinceWeek,
  );
  const newByWeek = new Map(
    (await rows<{ week: string; n: number }>(db, `SELECT date(first_day, '-6 days', 'weekday 1') AS week, COUNT(*) AS n FROM installs WHERE first_day >= ? AND ${NOT_INTERNAL} GROUP BY week`, sinceWeek)).map((r) => [
      r.week,
      Number(r.n),
    ]),
  );
  return {
    day: today,
    definitions: {
      installs_ever: 'install ids ever seen (only installs that turned sharing on)',
      dau: `installs active on ${yesterday} (UTC)`,
      wau: `installs active ${d7}..${today}`,
      mau: `installs active ${d30}..${today}`,
      real_users: 'installs that finished at least one batch',
      active_real_users_7d: `installs that finished a batch ${d7}..${today}`,
      retained_users: 'installs that finished batches in at least 2 different weeks',
    },
    installs_ever: rolled + fresh,
    dau: await n(db, `SELECT COUNT(DISTINCT install_id) AS n FROM events WHERE day = ? AND ${NOT_INTERNAL}`, yesterday),
    wau: await n(db, `SELECT COUNT(DISTINCT install_id) AS n FROM events WHERE day >= ? AND ${NOT_INTERNAL}`, d7),
    mau: await n(db, `SELECT COUNT(DISTINCT install_id) AS n FROM events WHERE day >= ? AND ${NOT_INTERNAL}`, d30),
    real_users: await n(db, `SELECT COUNT(DISTINCT install_id) AS n FROM events WHERE ${BATCH} AND ${NOT_INTERNAL}`),
    active_real_users_7d: await n(db, `SELECT COUNT(DISTINCT install_id) AS n FROM events WHERE ${BATCH} AND day >= ? AND ${NOT_INTERNAL}`, d7),
    retained_users: await n(
      db,
      `SELECT COUNT(*) AS n FROM (SELECT install_id FROM events WHERE ${BATCH} AND ${NOT_INTERNAL} GROUP BY install_id HAVING COUNT(DISTINCT ${WEEK}) >= 2)`,
    ),
    internal_installs: await n(db, 'SELECT COUNT(*) AS n FROM internal_installs'),
    weekly: weekly.map((w) => ({ ...w, new_installs: newByWeek.get(w.week) ?? 0 })),
    // each install counted once, with what it sent most recently (last 30 days)
    by_version: await rows(
      db,
      `SELECT version, COUNT(*) AS installs FROM (SELECT install_id, version, MAX(day) FROM events WHERE day >= ? AND ${NOT_INTERNAL} GROUP BY install_id)
       GROUP BY version ORDER BY installs DESC`,
      d30,
    ),
    by_locale: await rows(
      db,
      `SELECT locale, COUNT(*) AS installs FROM (SELECT install_id, locale, MAX(day) FROM events WHERE day >= ? AND ${NOT_INTERNAL} GROUP BY install_id)
       GROUP BY locale ORDER BY installs DESC`,
      d30,
    ),
    by_os: await rows(
      db,
      `SELECT os, arch, COUNT(*) AS installs FROM (SELECT install_id, os, arch, MAX(day) FROM events WHERE day >= ? AND ${NOT_INTERNAL} GROUP BY install_id)
       GROUP BY os, arch ORDER BY installs DESC`,
      d30,
    ),
  };
}
