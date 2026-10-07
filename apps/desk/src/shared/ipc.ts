// IPC contract between the renderer (via preload) and the main process. Every invoke payload is validated in
// main with these schemas before anything happens; unknown channels are rejected by construction.
import { z } from 'zod';
import { AI_TASK_IDS, KEY_NAMES, PROVIDER_IDS } from './aiRoutes';
import { recIpcSchemas } from './recIpc';
import { supportIpcSchemas } from './supportIpc';

const batchId = z.string().regex(/^[0-9a-f]{12}$/);
/** batch job ids, and work-folder clip ids (file stems like A_换圈子: letters / digits of any script, . _ -) */
const jobId = z.string().regex(/^[\p{L}\p{N}][\p{L}\p{N}._-]{0,127}$/u);
const code = z.string().regex(/^[0-9a-f]{12}$/);
const adapterId = z.string().regex(/^[a-z][a-z0-9-]{1,30}$/);
/** Becomes part of a session partition name: persist:<adapter>-<account>. */
export const accountName = z.string().regex(/^[a-z0-9][a-z0-9_-]{0,31}$/, 'account: a-z 0-9 _ - (max 32)');
const packageKey = z.string().regex(/^[a-z][a-z-]{1,40}$/);
const absPath = z
  .string()
  .min(2)
  .max(4096)
  .refine((p) => p.startsWith('/') || /^[A-Za-z]:\\/.test(p), 'absolute path required')
  .refine((p) => !p.includes('\0'), 'bad path');
const httpsUrl = z
  .string()
  .max(2048)
  .url()
  .refine((u) => new URL(u).protocol === 'https:', 'https only');

/** Platform ids as the engine takes them: tiktok, xiaohongshu:full, youtube-shorts:vertical. */
export const platformId = z.string().regex(/^[a-z][a-z-]{0,30}(:[a-z]{3,12})?$/);
/** API keys: printable ASCII without spaces. The value only ever travels renderer -> main, never back. */
const secretValue = z.string().regex(/^[\x21-\x7e]{8,400}$/, 'key: 8-400 printable characters, no spaces');
export const SECRET_NAMES = KEY_NAMES;
const provider = z.enum(PROVIDER_IDS);
const routeChoice = z.strictObject({
  provider: z.enum([...PROVIDER_IDS, 'none']),
  model: z.string().max(120).nullable().optional(),
  fallback: z.array(provider).max(4),
});
const aiRoutes = z.strictObject({
  default: routeChoice,
  tasks: z.strictObject(Object.fromEntries(AI_TASK_IDS.map((k) => [k, routeChoice.optional()])) as Record<(typeof AI_TASK_IDS)[number], z.ZodOptional<typeof routeChoice>>),
});
const usageInt = z.number().int().min(0).max(100_000);
const termId = z.string().regex(/^[0-9a-f]{12}$/);
const termSize = z.number().int().min(10).max(500);
const fileName = z.string().regex(/^[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff ._()-]{0,79}\.(csv|md|txt)$/, 'file name');

export const ipcSchemas = {
  'engine:info': z.undefined(),
  'engine:restart': z.undefined(),
  'dialog:openFile': z.strictObject({ kind: z.enum(['video', 'segments', 'persona', 'python', 'board']) }),
  'dialog:openFiles': z.strictObject({ kind: z.enum(['video', 'any']) }),
  'dialog:openFolder': z.undefined(),
  'shell:openExternal': z.strictObject({ url: httpsUrl }),
  'shell:showItem': z.strictObject({ path: absPath }),
  /** Settings › Advanced › Help and diagnostics: the app's own log folder (<userData>/logs) */
  'shell:openLogs': z.undefined(),
  'clipboard:write': z.strictObject({ text: z.string().max(20000) }),
  'settings:get': z.undefined(),
  'settings:set': z.strictObject({
    enginePath: absPath.optional(),
    python: absPath.optional(),
    lang: z.enum(['en', 'zh-CN', 'fr']).optional(),
    theme: z.enum(['studio-dark', 'notebook-light']).optional(),
    accent: z.enum(['teal', 'red']).optional(),
    defaultPlatforms: z.array(platformId).min(1).max(8).optional(),
    cleanupDays: z.number().int().min(0).max(365).optional(),
    agencyMode: z.boolean().optional(),
    createPage: z.boolean().optional(),
    createLocalGen: z.boolean().optional(),
    usagePings: z.enum(['on', 'off']).optional(),
    openAtLogin: z.boolean().optional(),
  }),
  // opt-in anonymous usage counts (main/usage.ts): small integers only, never text
  'usage:status': z.undefined(),
  'usage:track': z.strictObject({
    ev: z.enum(['batch_done', 'export_done', 'publish_package']),
    n: z
      .strictObject({
        clips: usageInt.optional(),
        formats: usageInt.optional(),
        minutes_in: usageInt.optional(),
        count: usageInt.optional(),
        platform_count: usageInt.optional(),
      })
      .optional(),
  }),
  'usage:resetId': z.undefined(),
  'usage:delete': z.undefined(),
  // ---------------- v0.2: first run, keys (OS keychain via safeStorage), persona, exports
  'firstRun:complete': z.strictObject({ defaultPlatforms: z.array(platformId).min(1).max(8), skipped: z.boolean().optional() }),
  'secrets:status': z.undefined(),
  'secrets:set': z.strictObject({ name: z.enum(SECRET_NAMES), value: z.string() }).superRefine((v, ctx) => {
    // OAuth access tokens (Kling MCP) are longer than API keys
    const ok = v.name === 'kling' ? /^[\x21-\x7e]{8,4096}$/.test(v.value) : secretValue.safeParse(v.value).success;
    if (!ok) ctx.addIssue({ code: 'custom', path: ['value'], message: 'key: 8-400 printable characters, no spaces' });
  }),
  'secrets:clear': z.strictObject({ name: z.enum(SECRET_NAMES) }),
  'persona:import': z.strictObject({ path: absPath.refine((p) => /\.ya?ml$/i.test(p), '.yaml / .yml only') }),
  'persona:clear': z.undefined(),
  'file:saveText': z.strictObject({ defaultName: fileName, text: z.string().max(5_000_000) }),
  'publish:adapters': z.undefined(),
  'publish:accounts': z.undefined(),
  'publish:addAccount': z.strictObject({ adapterId, account: accountName }),
  'publish:channels': z.undefined(),
  'publish:updateChannel': z.strictObject({
    adapterId,
    account: accountName,
    name: z.string().max(60).refine((v) => !/\p{Cc}/u.test(v), 'name').optional(),
    times: z.array(z.string().regex(/^([01]\d|2[0-3]):[0-5]\d$/)).max(6).optional(),
  }),
  'publish:removeAccount': z.strictObject({ adapterId, account: accountName, signOut: z.boolean() }),
  'publish:open': z.strictObject({ adapterId, account: accountName, page: z.enum(['upload', 'login']) }),
  'publish:setBounds': z.strictObject({
    x: z.number().int().min(0).max(20000),
    y: z.number().int().min(0).max(20000),
    width: z.number().int().min(0).max(20000),
    height: z.number().int().min(0).max(20000),
  }),
  'publish:hide': z.undefined(),
  'publish:navigate': z.strictObject({ action: z.enum(['back', 'forward', 'reload', 'upload', 'login']) }),
  'publish:confirmPackage': z.strictObject({ batchId, code }),
  'publish:confirmations': z.strictObject({ batchId }),
  'publish:fill': z.strictObject({
    batchId,
    code,
    job: jobId,
    platform: packageKey,
    adapterId,
    account: accountName,
    /** adapter params the creator typed (Reddit: subreddit); checked against the adapter's pattern in main */
    params: z.record(z.string().regex(/^[a-z]{2,20}$/), z.string().max(40)).optional(),
  }),
  'publish:markPosted': z.strictObject({
    batchId,
    code,
    job: jobId,
    platform: packageKey,
    adapterId,
    account: accountName,
    url: httpsUrl.optional(),
  }),
  'publish:caption': z.strictObject({ batchId, job: jobId, platform: packageKey }),
  'publish:postedLog': z.strictObject({ batchId: batchId.optional() }),
  // the publish loop: due posts (ticks the scheduler), fill one scheduled post, capture the open page, official APIs
  'publish:due': z.undefined(),
  'publish:fillPost': z.strictObject({ postId: z.string().regex(/^[0-9a-f]{12}$/), account: accountName.optional() }),
  'publish:capture': z.undefined(),
  'publish:apiStatus': z.undefined(),
  'publish:apiClient': z.strictObject({ id: z.literal('youtube'), clientId: z.string().min(10).max(220), clientSecret: z.string().min(8).max(220) }),
  'publish:apiConnect': z.strictObject({ id: z.literal('youtube') }),
  'publish:apiDisconnect': z.strictObject({ id: z.literal('youtube'), forgetClient: z.boolean().optional() }),
  'publish:apiAuto': z.strictObject({ id: z.literal('youtube'), auto: z.boolean() }),
  'assets:status': z.undefined(),
  'assets:install': z.strictObject({ ids: z.array(z.string().regex(/^[a-z0-9-]{1,40}$/)).max(20).optional() }),
  'assets:cancel': z.strictObject({ id: z.string().regex(/^[a-z0-9-]{1,40}$/).optional() }).optional(),
  'update:check': z.undefined(),
  'update:install': z.undefined(),
  'history:watch': z.strictObject({ roots: z.array(absPath).max(20) }),
  'cleanup:confirm': z.strictObject({ batchId }),
  // AI accounts & models: status, CLI login terminal (command from the engine), routes
  'ai:status': z.strictObject({ refresh: z.boolean().optional(), probe: z.boolean().optional(), providers: z.array(provider).max(12).optional() }),
  'ai:test': z.strictObject({ provider }),
  'ai:terminal': z.strictObject({
    provider: z.enum(['claude-code', 'codex']),
    action: z.enum(['login', 'logout']),
    variant: z.enum(['console', 'sso', 'device']).optional(),
    cols: termSize,
    rows: termSize,
  }),
  'term:input': z.strictObject({ id: termId, data: z.string().max(8192) }),
  'term:resize': z.strictObject({ id: termId, cols: termSize, rows: termSize }),
  'term:kill': z.strictObject({ id: termId }),
  'ai:routes': z.undefined(),
  'ai:setRoutes': z.strictObject({ routes: aiRoutes.nullable() }),
  // v0.4: a system notification when a run finishes or needs the creator (shown only while the window is not focused)
  'notify:show': z.strictObject({ title: z.string().min(1).max(120), body: z.string().max(300), route: z.string().regex(/^#\/[A-Za-z0-9/_.%-]{0,200}$/).optional() }),
  // Create recorder (refused in main while the Create flag is off)
  ...recIpcSchemas,
  // feedback + problem reports (main/support.ts)
  ...supportIpcSchemas,
} as const;

export type IpcChannel = keyof typeof ipcSchemas;
export type IpcPayload<C extends IpcChannel> = z.infer<(typeof ipcSchemas)[C]>;

export const IPC_CHANNELS = Object.keys(ipcSchemas) as IpcChannel[];

export class IpcValidationError extends Error {
  constructor(channel: string, detail: string) {
    super(`invalid ${channel} payload: ${detail}`);
    this.name = 'IpcValidationError';
  }
}

export function validateIpc<C extends IpcChannel>(channel: C, payload: unknown): IpcPayload<C> {
  if (!Object.prototype.hasOwnProperty.call(ipcSchemas, channel)) throw new IpcValidationError(String(channel), 'unknown channel');
  const r = ipcSchemas[channel].safeParse(payload);
  if (!r.success) {
    throw new IpcValidationError(channel, r.error.issues.map((i) => `${i.path.join('.') || '(root)'} ${i.message}`).join('; '));
  }
  return r.data as IpcPayload<C>;
}

/** Events main -> renderer. */
export const IPC_EVENTS = ['publish:state', 'publish:fillStep', 'engine:status', 'publish:due', 'publish:posted', 'publish:channels'] as const;
export type IpcEvent = (typeof IPC_EVENTS)[number];

export function partitionFor(adapter: string, account: string): string {
  adapterId.parse(adapter);
  accountName.parse(account);
  return `persist:${adapter}-${account}`;
}
