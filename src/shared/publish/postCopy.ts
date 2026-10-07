// post.md (written by vstudio.publish.post_body) -> title / description / tags for assisted fill.
// Layout: [title, ""], [hook, ""], body..., ["", "#tag #tag"]  (B站 uses a "标签：a, b" line instead).

export interface PostCopy {
  title: string;
  description: string;
  tags: string[];
}

const TAG_LINE = /^(#[^\s#]+\s*)+$/u;
const BILI_TAGS = /^标签[:：]\s*(.+)$/u;

/** keepFirstLine: the platform has no title field (X, Instagram) - without a manifest title the first line is the
 * hook of the post text, not a title to drop. */
export function parsePostCopy(md: string, manifestTitle = '', opts: { keepFirstLine?: boolean } = {}): PostCopy {
  const lines = md.replace(/\r\n/g, '\n').trim().split('\n');
  let title = manifestTitle.trim();
  if (lines.length && title && lines[0].trim() === title) {
    lines.shift();
  } else if (!title && !opts.keepFirstLine && lines.length > 1 && lines[1].trim() === '') {
    title = lines.shift()!.trim();
  }
  let tags: string[] = [];
  while (lines.length && lines[lines.length - 1].trim() === '') lines.pop();
  const last = lines.length ? lines[lines.length - 1].trim() : '';
  if (TAG_LINE.test(last)) {
    tags = last.split(/\s+/).map((t) => t.replace(/^#/, '')).filter(Boolean);
    lines.pop();
  } else {
    const m = BILI_TAGS.exec(last);
    if (m) {
      tags = m[1].split(/[,，、\s]+/).filter(Boolean);
      lines.pop();
    }
  }
  const description = lines.join('\n').trim();
  return { title, description, tags };
}

/** The copy assisted fill types into one platform: post.md parsed; no title field (X, Instagram) -> the title is
 * the hook, the first line of the post text. */
export function copyForPlatform(md: string, manifestTitle: string, hasTitleField: boolean): PostCopy {
  const copy = parsePostCopy(md, manifestTitle, { keepFirstLine: !hasTitleField });
  if (!hasTitleField && copy.title && !copy.description.startsWith(copy.title)) {
    copy.description = copy.description ? `${copy.title}\n\n${copy.description}` : copy.title;
  }
  return copy;
}

export function formatTags(tags: string[], format = '#{tag} ', max?: number): string {
  return tags
    .slice(0, max ?? tags.length)
    .map((t) => format.replace('{tag}', t))
    .join('')
    .trimEnd();
}

// ---------------------------------------------------------------- platform text checks (warn, never cut)
// twitter-text v3 (github.com/twitter/twitter-text config/v3.json): these code point ranges weigh 1, everything else
// (CJK, most symbols) 2; an emoji sequence 2; any URL 23. Mirrors vstudio.platform.x_weighted_len.
const X_LIGHT: [number, number][] = [
  [0, 4351],
  [8192, 8205],
  [8208, 8223],
  [8242, 8247],
];
const URL_RE = /(?:https?:\/\/|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ai|co|dev|app|me|tv|ly|gg|cn|xyz)(?:\/\S*)?/giu;
const EMOJI_RE =
  /(?:[\u{1F1E6}-\u{1F1FF}]{2}|[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2300}-\u{23FF}](?:\u{FE0F}|[\u{1F3FB}-\u{1F3FF}])*(?:\u{200D}[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}](?:\u{FE0F}|[\u{1F3FB}-\u{1F3FF}])*)*)\u{FE0F}?/gu;

const LINK_RE = /(?:https?:\/\/|www\.)\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ai|co|dev|app|me|tv|ly|gg|cn|xyz|fr|es)(?:\/\S*)?/iu;

export function xWeightedLength(text: string): number {
  let n = 0;
  let t = (text ?? '').normalize('NFC');
  t = t.replace(URL_RE, () => {
    n += 22;
    return ' ';
  });
  t = t.replace(EMOJI_RE, () => {
    n += 1;
    return '\u0000';
  });
  for (const ch of t) {
    const c = ch.codePointAt(0)!;
    n += X_LIGHT.some(([a, b]) => c >= a && c <= b) ? 1 : 2;
  }
  return n;
}

/** Distinct #hashtags in a text (lower-cased), in order. */
export function hashtagsIn(text: string): string[] {
  const out: string[] = [];
  for (const m of (text ?? '').matchAll(/(?<![\p{L}\p{N}_&/#])#([^\s#.,!?;:，。！？；：、()（）[\]{}"'<>]+)/gu)) {
    const k = m[1].toLowerCase();
    if (!out.includes(k)) out.push(k);
  }
  return out;
}

export interface CopyCheck {
  code: 'text-over' | 'hashtags-over' | 'title-required' | 'link-not-clickable' | 'link-field' | 'link-avoid' | 'no-hashtags';
  field: 'title' | 'description' | 'tags';
  n: number;
  max: number;
  hard?: boolean;
}

/** Per-platform copy rules from the shared registry (src/shared/platforms.ts): required title, link handling,
 * platforms without hashtags. */
export interface CopyRules {
  titleRequired?: boolean;
  links?: 'clickable' | 'not-clickable' | 'link-field' | 'avoid';
  noHashtags?: boolean;
}

/** What the platform will complain about once the copy is filled: weighted / char length over the soft max, more
 * hashtags than allowed (description #tags + the tags the fill appends, counted together); with ``rules``: a
 * missing required title, a link in the text where it is not clickable / belongs in a link field / costs reach,
 * hashtags on a platform that does not use them (Reddit, Pinterest). */
export function checkCopy(fields: { title: unknown; description: unknown; tags: unknown }, copy: PostCopy, rules: CopyRules = {}): CopyCheck[] {
  type TF = { maxLength?: number; softMax?: number; count?: 'chars' | 'x-weighted' } | null;
  type TG = { mode: string; max?: number; hardMax?: boolean } | null;
  const out: CopyCheck[] = [];
  const tg = fields.tags as TG;
  const appended = tg ? copy.tags.slice(0, tg.max ?? copy.tags.length) : [];
  for (const [field, text] of [
    ['title', copy.title],
    ['description', tg?.mode === 'append-to-description' && appended.length ? `${copy.description}\n\n${formatTags(appended)}` : copy.description],
  ] as const) {
    const f = fields[field] as TF;
    if (!f || !text) continue;
    const max = f.softMax ?? f.maxLength;
    const n = f.count === 'x-weighted' ? xWeightedLength(text) : Array.from(text).length;
    if (max && n > max) out.push({ code: 'text-over', field, n, max });
  }
  if (rules.titleRequired && fields.title && !copy.title.trim()) out.push({ code: 'title-required', field: 'title', n: 0, max: 0 });
  if (rules.links && rules.links !== 'clickable' && LINK_RE.test(copy.description)) out.push({ code: rules.links === 'link-field' ? 'link-field' : `link-${rules.links}`, field: 'description', n: 0, max: 0 });
  if (rules.noHashtags && (copy.tags.length || hashtagsIn(copy.description).length)) out.push({ code: 'no-hashtags', field: 'tags', n: copy.tags.length + hashtagsIn(copy.description).length, max: 0 });
  if (tg?.max) {
    const all = [...new Set([...hashtagsIn(copy.description), ...appended.map((x) => x.toLowerCase())])];
    const dropped = copy.tags.length - appended.length;
    if (all.length > tg.max || dropped > 0) out.push({ code: 'hashtags-over', field: 'tags', n: Math.max(all.length, copy.tags.length), max: tg.max, hard: tg.hardMax });
  }
  return out;
}
