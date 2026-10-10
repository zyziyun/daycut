// 「排期发布」 on a clip: the next free slot - the first day (today on) with nothing scheduled yet, at each platform's
// own time; today only while every one of those times is still ahead (half an hour to spare). Pure (unit-tested).
import type { CalendarPost } from '../../../shared/v04';

const pad = (n: number) => String(n).padStart(2, '0');
const isoDay = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

export function nextFreeDay(posts: Pick<CalendarPost, 'at' | 'enabled'>[], now: Date, times: string[], maxDays = 60): string {
  const taken = new Set(posts.filter((p) => p.enabled !== false).map((p) => p.at.slice(0, 10)));
  const soon = new Date(now.getTime() + 30 * 60000);
  const hm = `${pad(soon.getHours())}:${pad(soon.getMinutes())}`;
  const sameDay = isoDay(soon) === isoDay(now);
  for (let k = 0; k < maxDays; k++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + k);
    const day = isoDay(d);
    if (taken.has(day)) continue;
    if (k === 0 && (!sameDay || times.some((x) => x <= hm))) continue;
    return day;
  }
  return isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() + maxDays));
}
