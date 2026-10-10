// The Studio list (2026-10 review step 6): one row per VIDEO - every clip of every recent project, plus a row for a
// request still being planned and for a project that has no clips yet - in four groups: needs you (要你看), in
// progress (进行中), ready to post (可以发), scheduled (已排期, posted ones too). Pure (unit-tested): the Studio, its
// keys (↑ ↓ ⌘1–9), the Dock badge and the notifications share it.
import type { HistoryItem } from '../../../shared/v02';
import type { CalendarPost, Clip, InboxItem, OpenRequest } from '../../../shared/v04';
import { itemPipeline, requestPipeline, type Pipeline } from './pipeline';
import { clipStatus } from './status';

import { STUDIO_GROUPS as GROUPS } from '../../../shared/videoStatus';

export type StudioGroup = (typeof GROUPS)[number];
export type StudioFilter = 'all' | StudioGroup;
export const STUDIO_GROUPS: StudioGroup[] = [...GROUPS];
export const STUDIO_FILTERS: StudioFilter[] = ['all', ...STUDIO_GROUPS];

export interface StudioRow {
  /** `<project>/<clip>` | `p:<project>` | `r:<request>` */
  key: string;
  kind: 'clip' | 'project' | 'request';
  item: string | null;
  clip: string | null;
  title: string;
  /** the project's name (the row's second line says which project, 1/3) */
  project: string | null;
  /** n of N clips in its project */
  pos: [number, number] | null;
  thumb: string | null;
  video: string | null;
  duration: number | null;
  group: StudioGroup;
  /** the dot: run (making), you (waits for her), error, done, off (queued) */
  tone: 'run' | 'you' | 'error' | 'done' | 'off';
  p: Pipeline;
  /** the question waiting for her about this video (the page shows it at the top) */
  ask: InboxItem | null;
  /** its next post (scheduled) or its last one (posted) */
  post: CalendarPost | null;
  posted: boolean;
  /** sort: newest first inside a group */
  at: number;
  i?: HistoryItem;
  r?: OpenRequest;
}

const RECENT_S = 14 * 86400;

/** The inbox items about one clip (an option names it, or the item lists its job) and the ones about its project. */
export function asksFor(items: InboxItem[], project: string, clip: string | null): InboxItem[] {
  return items.filter((x) => x.project.id === project && (clip == null ? !clipOf(x) : clipOf(x) === clip));
}

/** The clip an inbox item is about (its first option with a clip, else its only job), or null for the project. */
export function clipOf(x: InboxItem): string | null {
  const o = (x.options ?? []).find((y) => y.clip_id);
  if (o?.clip_id) return o.clip_id;
  return x.jobs?.length === 1 ? x.jobs[0] : null;
}

function clipGroup(c: Clip, mine: CalendarPost[], ask: boolean, projectRunning: boolean): { group: StudioGroup; tone: StudioRow['tone']; post: CalendarPost | null; posted: boolean } {
  const st = clipStatus(c);
  const made = c.files.length > 0 && c.state !== 'running' && c.state !== 'queued' && c.state !== 'planned';
  const on = mine.filter((p) => p.enabled !== false);
  const next = on.filter((p) => p.state !== 'posted').sort((a, b) => a.at.localeCompare(b.at))[0] ?? null;
  const last = on.filter((p) => p.state === 'posted').sort((a, b) => b.at.localeCompare(a.at))[0] ?? null;
  if (ask || st === 'you') return { group: 'you', tone: 'you', post: next, posted: false };
  if (st === 'error') return { group: 'you', tone: 'error', post: null, posted: false };
  if (!made) return { group: 'run', tone: c.state === 'running' || projectRunning ? 'run' : 'off', post: null, posted: false };
  if (next) return { group: 'scheduled', tone: 'done', post: next, posted: false };
  if (last) return { group: 'scheduled', tone: 'done', post: last, posted: true };
  return { group: 'ready', tone: 'done', post: null, posted: false };
}

/**
 * Every video, grouped. `clips[project]`: the project's clips once loaded (undefined: not loaded yet -> one project
 * row). Projects finished more than 14 days ago are left out unless something about them still waits for her.
 */
export function studioRows(
  items: HistoryItem[],
  requests: OpenRequest[],
  clips: Record<string, Clip[] | undefined>,
  posts: CalendarPost[],
  inbox: InboxItem[],
  now = Date.now() / 1000,
): StudioRow[] {
  const out: StudioRow[] = [];
  for (const r of requests) {
    const p = requestPipeline(r);
    const you = p.state === 'failed' || p.state === 'plan-ready' || p.state === 'you';
    out.push({
      key: `r:${r.id}`,
      kind: 'request',
      item: null,
      clip: null,
      title: r.name || r.prompt || '',
      project: null,
      pos: null,
      thumb: null,
      video: null,
      duration: null,
      group: you ? 'you' : 'run',
      tone: p.state === 'failed' ? 'error' : you ? 'you' : 'run',
      p,
      ask: null,
      post: null,
      posted: false,
      at: r.started ?? now,
      r,
    });
  }
  const deciding = new Set(inbox.filter((x) => x.kind !== 'failed' && x.project.id).map((x) => x.project.id!));
  for (const i of items) {
    const p = itemPipeline(i, posts, deciding.has(i.id));
    const at = i.updated ?? i.created ?? 0;
    const projAsks = asksFor(inbox, i.id, null);
    const old = now - at > RECENT_S && p.state !== 'you' && p.state !== 'failed' && p.state !== 'run' && p.state !== 'queued';
    if (old) continue;
    const cl = (clips[i.id] ?? []).filter((c) => !c.extra);
    const projectRow = (): StudioRow => ({
      key: `p:${i.id}`,
      kind: 'project',
      item: i.id,
      clip: null,
      title: i.name,
      project: null,
      pos: null,
      thumb: i.thumb ?? null,
      video: null,
      duration: null,
      group: p.state === 'you' || p.state === 'failed' ? 'you' : p.state === 'run' || p.state === 'queued' || p.state === 'idle' ? 'run' : p.state === 'scheduled' || p.state === 'out' ? 'scheduled' : 'ready',
      tone: p.state === 'failed' ? 'error' : p.state === 'you' ? 'you' : p.state === 'run' ? 'run' : p.state === 'queued' || p.state === 'idle' ? 'off' : 'done',
      p,
      ask: projAsks[0] ?? null,
      post: null,
      posted: p.state === 'out',
      at,
      i,
    });
    if (!cl.length) {
      out.push(projectRow());
      continue;
    }
    // a question about the whole project (a plan to approve, a budget) is a row of its own: no clip to pin it on
    if (projAsks.length) out.push({ ...projectRow(), group: 'you', tone: 'you' });
    const running = p.state === 'run';
    cl.forEach((c, k) => {
      const ask = asksFor(inbox, i.id, c.id)[0] ?? null;
      const mine = posts.filter((x) => x.item === i.id && x.clip === c.id);
      const g = clipGroup(c, mine, !!ask, running);
      out.push({
        key: `${i.id}/${c.id}`,
        kind: 'clip',
        item: i.id,
        clip: c.id,
        title: c.title,
        project: i.name,
        pos: cl.length > 1 ? [k + 1, cl.length] : null,
        thumb: c.cover,
        video: c.files[0]?.path ?? null,
        duration: c.duration,
        group: g.group,
        tone: g.tone,
        p: g.group === 'run' ? p : { ...p, state: g.group === 'scheduled' ? (g.posted ? 'out' : 'scheduled') : g.group === 'ready' ? 'ready' : p.state },
        ask,
        post: g.post,
        posted: g.posted,
        at: at - k / 1000, // a project's clips in their own order
        i,
      });
    });
  }
  return out;
}

/** Rows in screen order: needs you, in progress (making first, then queued), ready, scheduled; newest first. */
export function grouped(rows: StudioRow[]): Record<StudioGroup, StudioRow[]> {
  const g: Record<StudioGroup, StudioRow[]> = { you: [], run: [], ready: [], scheduled: [] };
  for (const r of rows) g[r.group].push(r);
  for (const k of STUDIO_GROUPS) g[k].sort((a, b) => b.at - a.at);
  g.run.sort((a, b) => runRank(a) - runRank(b) || b.at - a.at);
  // scheduled: the next post first, posted ones after
  g.scheduled.sort((a, b) => Number(a.posted) - Number(b.posted) || (a.posted ? (b.post?.at ?? '').localeCompare(a.post?.at ?? '') : (a.post?.at ?? '').localeCompare(b.post?.at ?? '')));
  return g;
}

function runRank(r: StudioRow): number {
  if (r.kind === 'request') return 1;
  if (r.tone === 'run') return 0;
  return 2 + (r.i?.queued ?? 0) / 1000;
}

/** The rows a filter shows, in screen order (`all`: every group in turn). */
export function visible(rows: StudioRow[], f: StudioFilter): StudioRow[] {
  const g = grouped(rows);
  return f === 'all' ? STUDIO_GROUPS.flatMap((k) => g[k]) : g[f];
}

/** How many videos wait for her (the Dock badge, the filter count). */
export function needsYou(rows: StudioRow[]): number {
  return rows.filter((r) => r.group === 'you').length;
}

/** Time left in a group (seconds), when the engine says for the running ones. */
export function timeLeft(rows: StudioRow[]): number | null {
  const s = new Set<string>();
  let n = 0;
  for (const r of rows) {
    const k = r.item ?? r.key;
    if (r.p.eta && !s.has(k)) {
      s.add(k);
      n = Math.max(n, r.p.eta);
    }
  }
  return n || null;
}
