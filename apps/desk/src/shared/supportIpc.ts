// Feedback + problem reports IPC: zod schemas merged into ipcSchemas (main/support.ts handles them). Nothing here
// sends anything: the renderer builds the redacted text, she reviews it and opens a prefilled GitHub page.
import { z } from 'zod';
import type { Problem, SupportEnv } from './support';

export const supportIpcSchemas = {
  /** versions + OS (+ home, only for redaction) and the crash-report setting */
  'support:env': z.undefined(),
  /** problems not yet dismissed + the recent ones (all redacted) */
  'support:problems': z.undefined(),
  'support:dismiss': z.strictObject({ id: z.string().regex(/^[a-z0-9]{4,24}$/).optional() }),
  /** a renderer error / a failed job the UI saw (redacted again in main) */
  'support:report': z.strictObject({
    kind: z.enum(['renderer', 'job']),
    code: z.string().max(80),
    message: z.string().max(2000),
    stack: z.string().max(8000).optional(),
  }),
  /** Settings › Help: "Send crash reports automatically" (default off; no effect without a sender) */
  'support:setAuto': z.strictObject({ on: z.boolean() }),
} as const;

export interface SupportApi {
  env(): Promise<SupportEnv>;
  problems(): Promise<{ items: Problem[]; recent: Problem[] }>;
  dismiss(id?: string): Promise<void>;
  report(p: { kind: 'renderer' | 'job'; code: string; message: string; stack?: string }): Promise<void>;
  setAuto(on: boolean): Promise<SupportEnv>;
}
