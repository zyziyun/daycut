// An agent working in a project folder reports what it is doing (`python -m vstudio.project touch DIR --status running
// --stage S --progress P --message M` -> DIR/.vstudio/status.json, read by the engine's history as `live`). The
// project page and the All-projects card show it instead of a static "Working on it": the message, the step, the
// progress and how fresh the heartbeat is. Pure (unit-tested).
import type { LiveStatus } from '../../../shared/v02';
import type { InboxItem } from '../../../shared/v04';
import { t } from '../i18n';

/** A heartbeat older than this reads "no update for …" instead of "updated … ago". */
export const STALE_S = 120;

export interface LiveLine {
  message: string;
  stage: string;
  /** 0-100, or null when the run gave no progress */
  pct: number | null;
  /** seconds since the last heartbeat, or null */
  age: number | null;
  stale: boolean;
}

/** The live line for a project, or null when there is nothing live to say (no message, step or progress). */
export function liveLine(live: LiveStatus | null | undefined, now = Date.now() / 1000): LiveLine | null {
  if (!live || (live.state !== 'running' && live.state !== 'waiting')) return null;
  const message = (live.message ?? '').trim();
  const stage = (live.stage ?? '').trim();
  const p = typeof live.progress === 'number' && isFinite(live.progress) ? live.progress : null;
  if (!message && !stage && p == null) return null;
  const pct = p == null ? null : Math.round(Math.min(1, Math.max(0, p > 1 ? p / 100 : p)) * 100);
  const age = live.heartbeat ? Math.max(0, now - live.heartbeat) : (live.age ?? null);
  return { message, stage, pct, age, stale: age != null && age > STALE_S };
}

/** "12 s" / "3 min" / "2 h" */
export function agoText(sec: number): string {
  if (sec < 60) return t('live.seconds', { n: Math.max(1, Math.round(sec)) });
  if (sec < 3600) return t('time.minutes', { n: Math.round(sec / 60) });
  return t('time.hours', { n: Math.round(sec / 3600) });
}

/** "Step: render · updated 12 s ago" (the second half of the live line) */
export function liveMeta(l: LiveLine): string {
  const parts: string[] = [];
  if (l.stage) parts.push(t('live.stage', { stage: l.stage }));
  if (l.pct != null) parts.push(`${l.pct}%`);
  if (l.age != null) parts.push(t(l.stale ? 'live.stale' : 'live.updated', { ago: agoText(l.age) }));
  return parts.join(' · ');
}

/** The decisions waiting in a project that are not clip reviews (checkpoints, confirms, spends): the Review tab and
 * the review screen list them instead of "Nothing to review here" while the badge says "Needs you". */
export function pendingFor(items: InboxItem[], id: string): InboxItem[] {
  return items.filter((x) => x.project.id === id && x.kind !== 'review' && x.kind !== 'failed');
}

