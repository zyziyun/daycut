// IPC contract between the renderer (via preload) and the main process. Every invoke payload is validated in
// main with these schemas before anything happens; unknown channels are rejected by construction.
import { z } from 'zod';

const batchId = z.string().regex(/^[0-9a-f]{12}$/);
const jobId = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/);
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

export const ipcSchemas = {
  'engine:info': z.undefined(),
  'engine:restart': z.undefined(),
  'dialog:openFile': z.strictObject({ kind: z.enum(['video', 'segments']) }),
  'dialog:openFolder': z.undefined(),
  'shell:openExternal': z.strictObject({ url: httpsUrl }),
  'shell:showItem': z.strictObject({ path: absPath }),
  'clipboard:write': z.strictObject({ text: z.string().max(20000) }),
  'settings:get': z.undefined(),
  'settings:set': z.strictObject({
    enginePath: absPath.optional(),
    python: absPath.optional(),
    lang: z.enum(['zh', 'en']).optional(),
    theme: z.enum(['studio-dark', 'notebook-light']).optional(),
  }),
  'publish:adapters': z.undefined(),
  'publish:accounts': z.undefined(),
  'publish:addAccount': z.strictObject({ adapterId, account: accountName }),
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
  'publish:fill': z.strictObject({ batchId, code, job: jobId, platform: packageKey, adapterId, account: accountName }),
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
export const IPC_EVENTS = ['publish:state', 'publish:fillStep', 'engine:status'] as const;
export type IpcEvent = (typeof IPC_EVENTS)[number];

export function partitionFor(adapter: string, account: string): string {
  adapterId.parse(adapter);
  accountName.parse(account);
  return `persist:${adapter}-${account}`;
}
