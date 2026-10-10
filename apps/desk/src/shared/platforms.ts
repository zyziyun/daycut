// The platform registry the whole UI orders by: platform pickers, the publish page tabs, the accounts list,
// calendar chips. Three groups, in this order: English / global, Chinese, other-language platforms. Within a group
// the platforms the creator has an account for come first, then the fixed order below.
//
// Values mirror vstudio.platform (engine) - lengths / hashtag norms / link handling are sourced in the engine's
// references/PLATFORMS.md. Labels: en / zh / fr (fr is used when a French UI locale exists; en otherwise).

export type PlatformGroup = 'global' | 'zh' | 'intl';
export const GROUPS: PlatformGroup[] = ['global', 'zh', 'intl'];

/** How the platform treats a URL in the post text. */
export type LinkRule =
  | 'clickable' // a link in the text is a real link (LinkedIn, Facebook, X, YouTube description, Reddit, Weibo, Dailymotion)
  | 'not-clickable' // shown as plain text: use the bio / profile link (Instagram, TikTok, Shorts, Kwai, Snapchat)
  | 'link-field' // a separate destination-link field, not the text (Pinterest)
  | 'avoid'; // not clickable AND outside links count as 导流 (小红书, 抖音, 视频号, B站, 快手, 知乎)

export interface PlatformInfo {
  id: string;
  group: PlatformGroup;
  labels: { en: string; zh: string; fr: string };
  /** chip mark: a short glyph on a coloured square (not the trademarked logo) */
  mark: { g: string; bg: string; fg?: string };
  /** the account / channel this platform posts through, when it is a format of another (YouTube Shorts -> youtube) */
  accountOf?: string;
  copy: {
    /** 0 = no title field (the title becomes the first line of the text) */
    titleMax: number;
    titleRequired?: boolean;
    textMax: number;
    count?: 'chars' | 'x-weighted';
    /** hashtags actually used (more are left out); hard = the platform refuses more */
    hashtags: { max: number; hard?: boolean; format?: string };
    links: LinkRule;
  };
}

// glyphs are marks, not copy
export const PLATFORMS: PlatformInfo[] = [
  // ------------------------------------------------ English / global
  { id: 'youtube', group: 'global', labels: { en: 'YouTube', zh: 'YouTube', fr: 'YouTube' }, mark: { g: '▶', bg: '#FF0033' },
    copy: { titleMax: 100, titleRequired: true, textMax: 5000, hashtags: { max: 15 }, links: 'clickable' } },
  { id: 'youtube-shorts', group: 'global', accountOf: 'youtube', labels: { en: 'YouTube Shorts', zh: 'YouTube Shorts', fr: 'YouTube Shorts' }, mark: { g: 'S', bg: '#FF0033' },
    copy: { titleMax: 100, titleRequired: true, textMax: 5000, hashtags: { max: 3 }, links: 'not-clickable' } },
  { id: 'tiktok', group: 'global', labels: { en: 'TikTok', zh: 'TikTok', fr: 'TikTok' }, mark: { g: 'T', bg: '#111111' },
    copy: { titleMax: 55, textMax: 4000, hashtags: { max: 30 }, links: 'not-clickable' } },
  { id: 'instagram', group: 'global', labels: { en: 'Instagram', zh: 'Instagram', fr: 'Instagram' }, mark: { g: 'IG', bg: '#D62976' },
    copy: { titleMax: 0, textMax: 2200, hashtags: { max: 5, hard: true }, links: 'not-clickable' } },
  { id: 'x', group: 'global', labels: { en: 'X', zh: 'X', fr: 'X' }, mark: { g: '𝕏', bg: '#000000' },
    copy: { titleMax: 0, textMax: 280, count: 'x-weighted', hashtags: { max: 2 }, links: 'clickable' } },
  { id: 'facebook', group: 'global', labels: { en: 'Facebook', zh: 'Facebook', fr: 'Facebook' }, mark: { g: 'f', bg: '#1877F2' },
    copy: { titleMax: 0, textMax: 2200, hashtags: { max: 5 }, links: 'clickable' } },
  { id: 'linkedin', group: 'global', labels: { en: 'LinkedIn', zh: '领英 LinkedIn', fr: 'LinkedIn' }, mark: { g: 'in', bg: '#0A66C2' },
    copy: { titleMax: 0, textMax: 3000, hashtags: { max: 3 }, links: 'clickable' } },
  { id: 'threads', group: 'global', labels: { en: 'Threads', zh: 'Threads', fr: 'Threads' }, mark: { g: '@', bg: '#000000' },
    copy: { titleMax: 0, textMax: 500, hashtags: { max: 1, hard: true }, links: 'clickable' } },
  { id: 'reddit', group: 'global', labels: { en: 'Reddit', zh: 'Reddit', fr: 'Reddit' }, mark: { g: 'r', bg: '#FF4500' },
    copy: { titleMax: 300, titleRequired: true, textMax: 40000, hashtags: { max: 0 }, links: 'clickable' } },
  { id: 'pinterest', group: 'global', labels: { en: 'Pinterest', zh: 'Pinterest', fr: 'Pinterest' }, mark: { g: 'P', bg: '#E60023' },
    copy: { titleMax: 100, textMax: 500, hashtags: { max: 0 }, links: 'link-field' } },
  { id: 'snapchat', group: 'global', labels: { en: 'Snapchat', zh: 'Snapchat', fr: 'Snapchat' }, mark: { g: 'Sc', bg: '#FFFC00', fg: '#111111' },
    copy: { titleMax: 0, textMax: 160, hashtags: { max: 3 }, links: 'not-clickable' } },
  // ------------------------------------------------ Chinese
  { id: 'xiaohongshu', group: 'zh', labels: { en: 'Xiaohongshu', zh: '小红书', fr: 'Xiaohongshu' }, mark: { g: '红', bg: '#FF2442' },
    copy: { titleMax: 20, textMax: 1000, hashtags: { max: 10 }, links: 'avoid' } },
  { id: 'douyin', group: 'zh', labels: { en: 'Douyin', zh: '抖音', fr: 'Douyin' }, mark: { g: '抖', bg: '#111111' },
    copy: { titleMax: 55, textMax: 1000, hashtags: { max: 10 }, links: 'avoid' } },
  { id: 'wechat-channels', group: 'zh', labels: { en: 'Channels', zh: '视频号', fr: 'Channels (WeChat)' }, mark: { g: '视', bg: '#FA9D3B' },
    copy: { titleMax: 16, textMax: 1000, hashtags: { max: 10 }, links: 'avoid' } },
  { id: 'bilibili', group: 'zh', labels: { en: 'Bilibili', zh: 'B 站', fr: 'Bilibili' }, mark: { g: 'B', bg: '#00A1D6' },
    copy: { titleMax: 80, titleRequired: true, textMax: 2000, hashtags: { max: 10 }, links: 'avoid' } },
  { id: 'kuaishou', group: 'zh', labels: { en: 'Kuaishou', zh: '快手', fr: 'Kuaishou' }, mark: { g: '快', bg: '#FF4906' },
    copy: { titleMax: 0, textMax: 500, hashtags: { max: 4 }, links: 'avoid' } },
  { id: 'weibo', group: 'zh', labels: { en: 'Weibo', zh: '微博', fr: 'Weibo' }, mark: { g: '微', bg: '#E6162D' },
    copy: { titleMax: 30, textMax: 2000, hashtags: { max: 3, format: '#{tag}# ' }, links: 'clickable' } },
  { id: 'zhihu', group: 'zh', labels: { en: 'Zhihu', zh: '知乎', fr: 'Zhihu' }, mark: { g: '知', bg: '#0066FF' },
    copy: { titleMax: 30, titleRequired: true, textMax: 300, hashtags: { max: 5 }, links: 'avoid' } },
  // ------------------------------------------------ other languages
  { id: 'dailymotion', group: 'intl', labels: { en: 'Dailymotion', zh: 'Dailymotion', fr: 'Dailymotion' }, mark: { g: 'd', bg: '#0A0F1E' },
    copy: { titleMax: 255, titleRequired: true, textMax: 3000, hashtags: { max: 15 }, links: 'clickable' } },
  { id: 'kwai', group: 'intl', labels: { en: 'Kwai', zh: 'Kwai（快手国际版）', fr: 'Kwai' }, mark: { g: 'K', bg: '#FF7E00' },
    copy: { titleMax: 0, textMax: 500, hashtags: { max: 5 }, links: 'not-clickable' } },
];

export const PLATFORM_IDS = PLATFORMS.map((p) => p.id);
const BY_ID = new Map(PLATFORMS.map((p) => [p.id, p]));

export function platformInfo(id: string): PlatformInfo | undefined {
  return BY_ID.get(id);
}

/** YouTube is ONE channel with two formats; the engine keeps them as two targets (youtube / youtube-shorts). */
export const YOUTUBE_FORMATS = [
  { id: 'youtube', format: 'long', aspect: '16:9' },
  { id: 'youtube-shorts', format: 'shorts', aspect: '9:16', maxSeconds: 180 },
] as const;

/** The account / channel a platform id posts through: youtube-shorts -> youtube. */
export function accountPlatform(id: string): string {
  return BY_ID.get(id)?.accountOf ?? id;
}

export function platformLabel(id: string, lang: string): string {
  const p = BY_ID.get(id);
  if (!p) return id;
  if (lang.startsWith('zh')) return p.labels.zh;
  if (lang.startsWith('fr')) return p.labels.fr;
  return p.labels.en;
}

/** Engine names for the same platforms (targets, intake words). */
const ALIASES: Record<string, string> = { shipinhao: 'wechat-channels', channels: 'wechat-channels', 'x-web': 'x', 'youtube-studio': 'youtube', xhs: 'xiaohongshu' };

/** The registry id of a platform / target / profile: 'xiaohongshu:full' -> 'xiaohongshu', 'shipinhao' -> 'wechat-channels'. */
export function basePlatform(id: string): string {
  const b = String(id ?? '').split(':')[0].trim().toLowerCase();
  return ALIASES[b] ?? b;
}

/** (group index, position in the fixed order); unknown ids sort last. Profiles / targets ('douyin:vertical') and
 * engine aliases rank as their platform. */
export function platformRank(id: string): [number, number] {
  const b = basePlatform(id);
  const p = BY_ID.get(b);
  if (!p) return [GROUPS.length, 999];
  return [GROUPS.indexOf(p.group), PLATFORM_IDS.indexOf(b)];
}

/** Platform ids / profiles in registry order (international first, then Chinese, then other), duplicates dropped:
 * the one helper every chip, summary, picker value and list goes through. */
export function orderPlatforms(ids: Iterable<string>, connected: Iterable<string> = []): string[] {
  return sortPlatforms([...new Set(ids)], (x) => x, connected);
}

/** Sort platform ids for display: group order (global, Chinese, other), within a group the connected ones first
 * (`connected`: platform ids she has an account for; a format counts through its account, e.g. youtube-shorts via
 * youtube), then the fixed order. Stable for unknown ids (last, in input order). */
export function sortPlatforms<T>(items: T[], idOf: (x: T) => string, connected: Iterable<string> = []): T[] {
  const conn = new Set([...connected].map((c) => accountPlatform(basePlatform(c))));
  return items
    .map((x, i) => ({ x, i, id: idOf(x) }))
    .sort((a, b) => {
      const [ga, oa] = platformRank(a.id);
      const [gb, ob] = platformRank(b.id);
      const ca = conn.has(accountPlatform(basePlatform(a.id))) ? 0 : 1;
      const cb = conn.has(accountPlatform(basePlatform(b.id))) ? 0 : 1;
      return ga - gb || ca - cb || oa - ob || a.i - b.i;
    })
    .map((e) => e.x);
}

/** What a new profile starts with: international first (her rule), the same pair Create starts from. */
export const FIRST_PLATFORMS = ['tiktok', 'youtube-shorts'];
/** What profiles made before 0.2.5 were seeded with whatever she posted to (not her choice). */
export const OLD_FACTORY_PLATFORMS = ['xiaohongshu:full'];

/** The platforms a new request from Home goes to: her own choice (Settings › New projects, or the chip), else the
 * platforms of her publishing accounts, else the international pair - always in the registry's order (international
 * first). ``accounts``: the adapter ids she has an account for. */
export function homePlatforms(saved: string[] | null | undefined, accounts: string[] = []): string[] {
  const mine = [...new Set((saved ?? []).filter(Boolean))];
  const seeded = mine.length === 1 && mine[0] === OLD_FACTORY_PLATFORMS[0] && !accounts.some((a) => basePlatform(a) === 'xiaohongshu');
  if (mine.length && !seeded) return orderPlatforms(mine, accounts);
  const fromAccounts = [...new Set(accounts.map((a) => basePlatform(a)).filter((a) => BY_ID.has(a)))];
  return orderPlatforms(fromAccounts.length ? fromAccounts : FIRST_PLATFORMS, accounts);
}

/** Every URL-looking run in a text (http(s)://, www., or a bare domain with a common TLD). */
export function linksIn(text: string): string[] {
  return [...(text ?? '').matchAll(/(?:https?:\/\/|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ai|co|dev|app|me|tv|ly|gg|cn|xyz|fr|es)(?:\/\S*)?/giu)].map((m) => m[0]);
}
