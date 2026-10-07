// Publish board model (ux/publish-redesign direction A). The engine keeps one row per clip x platform x time; the
// board shows ONE card per clip per day: its platforms, the earliest time, one calm status and the first problem.
// Pure functions only (unit-tested in tests/unit/publishBoard.test.ts).
import type { CalendarPost, PostWarning, QueueClip } from '../../../shared/v04';
import { xWeightedLength } from '../../../shared/publish/postCopy';

export type GroupStatus = 'draft' | 'ready' | 'filled' | 'posted';

export interface PostGroup {
  key: string;
  item: string;
  clip: string;
  day: string;
  /** earliest switched-on post of the card, "YYYY-MM-DDTHH:MM" */
  at: string;
  time: string;
  title: string;
  cover: string | null;
  project: string | null;
  duration: number | null;
  /** every row of the card (switched off ones too) */
  posts: CalendarPost[];
  /** the switched-on rows */
  on: CalendarPost[];
  platforms: string[];
  status: GroupStatus;
  warnings: PostWarning[];
  views: number | null;
}

export const pad = (n: number) => String(n).padStart(2, '0');
export const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const base = (pf: string) => pf.split(':')[0];

export function weekStart(d: Date, offset = 0): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  const dow = (x.getDay() + 6) % 7; // Monday = 0
  x.setDate(x.getDate() - dow + offset * 7);
  return x;
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d);
  x.setDate(x.getDate() + n);
  return x;
}

export function dayOf(s: string): Date {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function postStatus(p: CalendarPost): GroupStatus {
  if (p.status) return p.status;
  return p.state === 'planned' ? 'draft' : (p.state as GroupStatus);
}

const RANK: Record<GroupStatus, number> = { draft: 0, ready: 1, filled: 2, posted: 3 };

/** One calm status for a card: all posted -> posted; one filled form waiting -> "press publish"; all ready -> ready. */
export function groupStatus(posts: CalendarPost[]): GroupStatus {
  const on = posts.filter((p) => p.enabled !== false);
  if (!on.length) return 'draft';
  const st = on.map(postStatus);
  if (st.every((s) => s === 'posted')) return 'posted';
  if (st.some((s) => s === 'filled')) return 'filled';
  return st.reduce((a, b) => (RANK[b] < RANK[a] ? b : a), 'posted' as GroupStatus) === 'draft' ? 'draft' : 'ready';
}

export function groupPosts(posts: CalendarPost[], platformOrder: string[] = []): PostGroup[] {
  const by = new Map<string, CalendarPost[]>();
  for (const p of posts) {
    const k = `${p.item}/${p.clip}/${p.at.slice(0, 10)}`;
    const a = by.get(k);
    if (a) a.push(p);
    else by.set(k, [p]);
  }
  const rank = (pf: string) => {
    const i = platformOrder.indexOf(base(pf));
    return i < 0 ? 99 : i;
  };
  const out: PostGroup[] = [];
  for (const [key, rows] of by) {
    rows.sort((a, b) => a.at.localeCompare(b.at) || rank(a.platform) - rank(b.platform));
    const on = rows.filter((p) => p.enabled !== false);
    const first = on[0] ?? rows[0];
    const views = rows.reduce<number | null>((s, p) => (p.stats?.views != null ? (s ?? 0) + p.stats.views : s), null);
    out.push({
      key,
      item: first.item,
      clip: first.clip,
      day: first.at.slice(0, 10),
      at: first.at,
      time: first.at.slice(11, 16),
      title: first.title,
      cover: rows.find((p) => p.cover)?.cover ?? null,
      project: first.project ?? null,
      duration: first.duration ?? null,
      posts: rows,
      on,
      platforms: [...new Set(on.map((p) => base(p.platform)))].sort((a, b) => rank(a) - rank(b)),
      status: groupStatus(rows),
      warnings: on.flatMap((p) => p.warnings ?? []),
      views,
    });
  }
  return out.sort((a, b) => a.at.localeCompare(b.at) || a.title.localeCompare(b.title));
}

export interface QueueGroup {
  item: string;
  project: string;
  clips: QueueClip[];
}

/** 待排期 grouped by project, in the order the engine lists them. */
export function queueByProject(queue: QueueClip[]): QueueGroup[] {
  const out: QueueGroup[] = [];
  for (const q of queue) {
    let g = out.find((x) => x.item === q.item);
    if (!g) out.push((g = { item: q.item, project: q.project || q.item, clips: [] }));
    g.clips.push(q);
  }
  return out;
}

/** Where the text goes over the limit (counted the platform's way: X weighs CJK / emoji as 2): the index of the
 * first character that does not fit, or -1. */
export function overflowAt(text: string, platform: string, limit: number | null | undefined): number {
  if (!limit) return -1;
  const x = base(platform) === 'x';
  if ((x ? xWeightedLength(text) : [...text].length) <= limit) return -1;
  let n = 0;
  let i = 0;
  for (const ch of text) {
    const c = ch.codePointAt(0) ?? 0;
    n += x ? (c <= 4351 || (c >= 8192 && c <= 8205) || (c >= 8208 && c <= 8223) || (c >= 8242 && c <= 8247) ? 1 : 2) : 1;
    if (n > limit) return i;
    i += ch.length;
  }
  return -1;
}

// ---------------------------------------------------------------- "next Friday evening", "明天晚上8点", "demain 20h"
const WD: [RegExp, number][] = [
  [/monday|\bmon\b|lundi|周一|星期一|礼拜一/i, 1],
  [/tuesday|\btue\b|mardi|周二|星期二|礼拜二/i, 2],
  [/wednesday|\bwed\b|mercredi|周三|星期三|礼拜三/i, 3],
  [/thursday|\bthu\b|jeudi|周四|星期四|礼拜四/i, 4],
  [/friday|\bfri\b|vendredi|周五|星期五|礼拜五/i, 5],
  [/saturday|\bsat\b|samedi|周六|星期六|礼拜六/i, 6],
  [/sunday|\bsun\b|dimanche|周日|周天|星期日|星期天|礼拜天/i, 0],
];
const ZH: Record<string, number> = { 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10, 十一: 11, 十二: 12 };

function whenTime(s: string): string | null {
  const pm = /晚上|晚|傍晚|下午|evening|tonight|night|\bpm\b|p\.m\.|soir|après-midi/i.test(s);
  let m = /(\d{1,2})\s*[:：]\s*(\d{2})/.exec(s);
  if (m) {
    let h = +m[1];
    if (pm && h < 12) h += 12;
    return h < 24 && +m[2] < 60 ? `${pad(h)}:${m[2]}` : null;
  }
  m = /(\d{1,2})\s*(am|pm|a\.m\.|p\.m\.)/i.exec(s);
  if (m) return `${pad((+m[1] % 12) + (m[2].toLowerCase().startsWith('p') ? 12 : 0))}:00`;
  m = /(\d{1,2})\s*h\s*(\d{2})?\b/i.exec(s);
  if (m) {
    let h = +m[1];
    if (pm && h < 12) h += 12;
    return h < 24 ? `${pad(h)}:${m[2] ?? '00'}` : null;
  }
  m = /(\d{1,2}|十[一二]?|[一二两三四五六七八九十])\s*点\s*(半|\d{1,2})?/.exec(s);
  if (m) {
    let h = /\d/.test(m[1]) ? +m[1] : ZH[m[1]] ?? NaN;
    if (Number.isNaN(h)) return null;
    if (pm && h < 12) h += 12;
    const mi = m[2] === '半' ? 30 : m[2] ? +m[2] : 0;
    return h < 24 && mi < 60 ? `${pad(h)}:${pad(mi)}` : null;
  }
  if (/noon|中午|midi/i.test(s)) return '12:00';
  if (/morning|早上|上午|matin/i.test(s)) return '09:00';
  if (pm) return '20:00';
  return null;
}

/** A typed time for one post -> {day?, time?} (null when nothing is recognised). `same time` keeps the time. */
export function parseWhen(text: string, from: Date): { day?: string; time?: string } | null {
  const s = text.trim();
  if (!s) return null;
  const today = new Date(from);
  today.setHours(0, 0, 0, 0);
  let day: Date | null = null;
  if (/后天|day after tomorrow|après-demain/i.test(s)) day = addDays(today, 2);
  else if (/明天|tomorrow|demain/i.test(s)) day = addDays(today, 1);
  else if (/今天|今晚|today|tonight|aujourd'hui|ce soir/i.test(s)) day = today;
  else {
    const hit = WD.find(([re]) => re.test(s));
    if (hit) {
      const next = /下周|下个?星期|下礼拜|next|prochain/i.test(s);
      const dow = today.getDay();
      let delta = (hit[1] - dow + 7) % 7;
      if (next) delta = ((hit[1] + 6) % 7) - ((dow + 6) % 7) + 7; // the weekday of next week (Mon-based)
      else if (delta === 0) delta = 7;
      day = addDays(today, delta);
    }
  }
  const time = /same time|同一时间|même heure/i.test(s) ? undefined : whenTime(s);
  if (!day && !time) return null;
  return { ...(day ? { day: iso(day) } : {}), ...(time ? { time } : {}) };
}
