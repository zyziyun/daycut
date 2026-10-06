// Per-platform "assisted fill" adapter files (adapters/*.json). Strict schema: there is deliberately no way to
// express a click - the app only sets the video file and types text; the creator presses publish herself.
import { z } from 'zod';

const selectorList = z.array(z.string().min(1).max(300)).min(1).max(12);

const fileField = z.strictObject({
  selectors: selectorList,
  /** Wait up to this long for the input to appear (ms). */
  timeoutMs: z.number().int().min(0).max(120000).optional(),
});

const textField = z.strictObject({
  selectors: selectorList,
  kind: z.enum(['input', 'contenteditable']),
  maxLength: z.number().int().min(1).max(100000).optional(),
  /** Replace what is already there (TikTok pre-fills the caption with the file name). */
  clear: z.boolean().default(true),
  timeoutMs: z.number().int().min(0).max(120000).optional(),
  /** How the platform counts this text: chars, or X's weighted count (CJK / emoji = 2, URL = 23). */
  count: z.enum(['chars', 'x-weighted']).default('chars'),
  /** Warn (never cut) above this length - e.g. X 280 for standard accounts, more for Premium. */
  softMax: z.number().int().min(1).max(100000).optional(),
});

const tagsField = z.strictObject({
  /** append: add "#tag " to the description; separate: type into the tag input, one per Enter-less pass. */
  mode: z.enum(['append-to-description', 'separate']),
  selectors: selectorList.optional(),
  format: z.string().max(40).default('#{tag} '),
  max: z.number().int().min(0).max(100).optional(),
  /** separate mode: press Enter after each tag (B站 creates a tag chip per Enter). Enter is the only key ever sent. */
  submit: z.enum(['none', 'enter']).default('none'),
  /** The platform refuses more hashtags than max (Instagram: 5 per post, caption + tags together). */
  hardMax: z.boolean().default(false),
});

const hostPattern = z
  .string()
  .regex(/^(\*\.)?[a-z0-9-]+(\.[a-z0-9-]+)+$/, 'host like example.com or *.example.com');

export const adapterSchema = z
  .strictObject({
    $schema: z.string().optional(),
    id: z.string().regex(/^[a-z][a-z0-9-]{1,30}$/),
    name: z.string().min(1).max(60),
    nameZh: z.string().min(1).max(60),
    /** verified: selectors checked against the live page on lastVerified; unverified: best guess; todo: no fill. */
    status: z.enum(['verified', 'unverified', 'todo']),
    lastVerified: z.string().regex(/^\d{4}-\d{2}-\d{2}$/).nullable(),
    /** vstudio platform names this adapter can post (package key "<platform>-<orientation>"). */
    packagePlatforms: z.array(z.string().regex(/^[a-z][a-z-]{0,30}$/)).min(1),
    uploadUrl: z.string().url().startsWith('https://'),
    loginUrl: z.string().url().startsWith('https://'),
    /** Hosts the embedded browser treats as this platform (popups, posted-URL check). */
    allowedHosts: z.array(hostPattern).min(1).max(30),
    fields: z.strictObject({
      file: fileField,
      title: textField.nullable(),
      description: textField.nullable(),
      tags: tagsField.nullable(),
      cover: fileField.nullable(),
    }),
    /** Highlighted (outline) so the creator finds it. Never clicked by the app. */
    publishButton: z.strictObject({ selectors: selectorList }).nullable(),
    disclosure: z.strictObject({
      zh: z.string().min(1).max(600),
      en: z.string().min(1).max(600),
    }),
    /** What the creator clicks herself before / while the fill runs (e.g. Instagram: Create -> Post, then Next). */
    guide: z.strictObject({ zh: z.string().min(1).max(600), en: z.string().min(1).max(600) }).nullable().default(null),
    /** Choices the app never makes for her (B站 分区 / 自制·转载, 视频号 原创声明 ...), shown as a checklist. */
    herChoices: z.strictObject({ zh: z.array(z.string().max(120)).max(10), en: z.array(z.string().max(120)).max(10) }).nullable().default(null),
    notes: z.array(z.string().max(400)).max(20).default([]),
  })
  .superRefine((a, ctx) => {
    if (a.status !== 'todo' && a.fields.description === null && a.fields.title === null) {
      ctx.addIssue({ code: 'custom', message: 'a fillable adapter needs a title or description field' });
    }
    if (a.fields.tags?.mode === 'separate' && !a.fields.tags.selectors) {
      ctx.addIssue({ code: 'custom', message: 'tags.mode separate needs selectors' });
    }
    for (const u of [a.uploadUrl, a.loginUrl]) {
      if (!hostAllowed(new URL(u).hostname, a.allowedHosts)) {
        ctx.addIssue({ code: 'custom', message: `${u} is outside allowedHosts` });
      }
    }
  });

export type Adapter = z.infer<typeof adapterSchema>;
export type TextField = z.infer<typeof textField>;

export function hostAllowed(host: string, patterns: string[]): boolean {
  host = host.toLowerCase();
  return patterns.some((p) => (p.startsWith('*.') ? host === p.slice(2) || host.endsWith(p.slice(1)) : host === p));
}

export function parseAdapter(json: unknown): { ok: true; adapter: Adapter } | { ok: false; error: string } {
  const r = adapterSchema.safeParse(json);
  if (r.success) return { ok: true, adapter: r.data };
  return { ok: false, error: r.error.issues.map((i) => `${i.path.join('.') || '(root)'}: ${i.message}`).join('; ') };
}

const ORIENTATIONS = ['vertical', 'full', 'horizontal', 'square', 'reels', 'feed'];

/** "tiktok-vertical" -> "tiktok"; "youtube-shorts-vertical" -> "youtube-shorts"; "instagram-reels" -> "instagram";
 * "x-square" -> "x"; "wechat-channels-vertical" -> "wechat-channels". */
export function basePlatform(packageKey: string): string {
  const i = packageKey.lastIndexOf('-');
  if (i > 0 && ORIENTATIONS.includes(packageKey.slice(i + 1))) return packageKey.slice(0, i);
  return packageKey;
}

export function adapterFor(packageKey: string, adapters: Adapter[]): Adapter | undefined {
  const base = basePlatform(packageKey);
  return adapters.find((a) => a.packagePlatforms.includes(base));
}
