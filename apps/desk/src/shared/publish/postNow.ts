// Closing the loop for one scheduled post (发布 board row): which posts are due, which rendered file goes to the
// platform, and what text the upload form gets. Pure functions (unit-tested in tests/unit/postLoop.test.ts).
import type { CalendarPost, ClipFile } from '../v04';
import { parsePostCopy, type PostCopy } from './postCopy';

/** "YYYY-MM-DDTHH:MM" in the creator's local time -> Date. */
export function localDate(at: string): Date {
  const [d, t = '00:00'] = at.split('T');
  const [y, m, day] = d.split('-').map(Number);
  const [h, mi] = t.split(':').map(Number);
  return new Date(y, m - 1, day, h, mi);
}

/** Posts whose time has come and that nobody posted yet (switched on), oldest first. Older than maxAgeDays: stale,
 * left to the board (she moves or removes them there). */
export function duePosts(posts: CalendarPost[], now: Date, maxAgeDays = 14): CalendarPost[] {
  const t = now.getTime();
  return posts
    .filter((p) => p.enabled !== false && p.state !== 'posted')
    .filter((p) => {
      const at = localDate(p.at).getTime();
      return at <= t && t - at <= maxAgeDays * 86400_000;
    })
    .sort((a, b) => a.at.localeCompare(b.at));
}

/** Posts that become due within `withinMs` (not yet due, not posted, switched on). */
export function upcomingPosts(posts: CalendarPost[], now: Date, withinMs: number): CalendarPost[] {
  const t = now.getTime();
  return posts.filter((p) => {
    if (p.enabled === false || p.state === 'posted') return false;
    const at = localDate(p.at).getTime();
    return at > t && at - t <= withinMs;
  });
}

const ASPECTS: Record<string, Record<string, string[]>> = {
  xiaohongshu: { vertical: ['3:4', '9:16'], full: ['9:16', '3:4'], horizontal: ['16:9'], '': ['3:4', '9:16'] },
  youtube: { horizontal: ['16:9'], '': ['16:9', '9:16'] },
  bilibili: { horizontal: ['16:9'], vertical: ['9:16'], '': ['16:9', '9:16'] },
  instagram: { reels: ['9:16'], feed: ['4:5', '1:1', '3:4'], '': ['9:16'] },
};
const DEFAULT_ASPECTS: Record<string, string[]> = { vertical: ['9:16'], full: ['9:16'], horizontal: ['16:9'], square: ['1:1'], reels: ['9:16'], feed: ['4:5', '1:1'], '': ['9:16', '3:4'] };

/** The rendered version for this platform: one made for it, else the aspect it posts, else the first file. */
export function pickFile(files: ClipFile[], platform: string): ClipFile | null {
  if (!files.length) return null;
  const [base, orient = ''] = platform.split(':');
  const own = files.find((f) => f.platform && (f.platform === base || f.platform === platform || f.platform.startsWith(`${base}-`) || f.platform.startsWith(`${base}:`)));
  if (own) return own;
  const want = ASPECTS[base]?.[orient] ?? ASPECTS[base]?.[''] ?? DEFAULT_ASPECTS[orient] ?? DEFAULT_ASPECTS[''];
  for (const a of want) {
    const f = files.find((x) => x.aspect === a);
    if (f) return f;
  }
  return files[0];
}

/** The text the upload form gets: her caption for this platform (or the clip's post copy), split into description
 * and the trailing #tag line (the adapter formats tags its own way); platforms with a title field get the post's
 * title, and the caption's first paragraph is dropped when it only repeats that title. */
export function copyForPost(post: Pick<CalendarPost, 'title' | 'caption' | 'platform_title'>, hasTitleField: boolean, clipTitles: string[] = []): PostCopy {
  const parsed = parsePostCopy(post.caption ?? '', '', { keepFirstLine: true });
  if (!hasTitleField) return { title: '', description: parsed.description, tags: parsed.tags };
  const title = (post.platform_title || post.title || '').trim();
  let description = parsed.description;
  const paras = description.split(/\n\s*\n/);
  const first = (paras[0] ?? '').trim();
  if (paras.length > 1 && first && [title, (post.title ?? '').trim(), ...clipTitles.map((x) => x.trim())].includes(first)) description = paras.slice(1).join('\n\n').trim();
  return { title, description, tags: parsed.tags };
}

/** The page after her publish click: a success URL, a success text, the new post's link. */
export function postedSignal(
  url: string,
  pageText: string,
  links: string[],
  success: { urls: string[]; texts: string[]; postUrl?: string } | null,
): { posted: boolean; url: string | null } {
  if (!success) return { posted: false, url: null };
  const any = (pats: string[], s: string) => pats.some((p) => new RegExp(p).test(s));
  const posted = any(success.urls, url) || (pageText !== '' && any(success.texts, pageText));
  if (!posted) return { posted: false, url: null };
  let found: string | null = null;
  if (success.postUrl) {
    const re = new RegExp(success.postUrl);
    found = [url, ...links].find((l) => re.test(l)) ?? null;
    if (found) found = re.exec(found)![0];
  }
  return { posted: true, url: found && found.startsWith('https://') ? found : null };
}

/** A title's length counted the platform's way: 小红书 counts CJK / full-width as 1 and latin letters, digits and
 * spaces as 0.5 (vstudio.config.xhs_len); everyone else counts characters. */
export function titleLength(platform: string, title: string): number {
  const base = platform.split(':')[0];
  if (base === 'xiaohongshu') return Array.from(title).reduce((n, c) => n + ((c.codePointAt(0) ?? 0) < 0x2e80 ? 0.5 : 1), 0);
  return Array.from(title).length;
}
