// Recorder IPC (Create page): zod schemas merged into ipcSchemas, plus the pure permission predicate main uses.
// Every rec:* handler refuses while the Create flag is off.
import { z } from 'zod';

export const REC_TRACKS = ['camera', 'mic', 'screen'] as const;
export type RecTrack = (typeof REC_TRACKS)[number];
export const MAX_CHUNK = 8 * 1024 * 1024;
const sessionId = z.string().regex(/^\d{8}-\d{6}-[a-z0-9-]{1,40}$/);
const line = z.string().max(500).refine((v) => !/\p{Cc}/u.test(v.replace(/\n/g, '')), 'line');

export const recIpcSchemas = {
  'rec:status': z.undefined(),
  'rec:ask': z.strictObject({ kind: z.enum(['camera', 'microphone']) }),
  'rec:openPrivacy': z.strictObject({ pane: z.enum(['camera', 'microphone', 'screen']) }),
  'rec:begin': z.strictObject({
    slug: z.string().regex(/^[a-z0-9][a-z0-9-]{0,39}$/),
    title: z.string().max(120).optional(),
    script: z.array(line).max(300),
    tracks: z.array(z.enum(REC_TRACKS)).min(1).max(3),
    series: z.string().regex(/^[a-z0-9][a-z0-9-]{0,47}$/).optional(),
    episode: z.string().regex(/^[a-z0-9][a-z0-9-]{0,47}$/).optional(),
    shot: z.string().regex(/^\d{2,3}$/).optional(),
    mime: z.partialRecord(z.enum(REC_TRACKS), z.string().max(80)).optional(),
    /** false = keep the raw sound (no studio-sound pass at ingest) */
    studio: z.boolean().optional(),
    /** the Record visit this take belongs to (Takes lists the takes of one visit) */
    group: z.string().regex(/^[a-z0-9]{6,32}$/).optional(),
    /** a pickup (补录) for a clip, not a take of its own */
    pickup: z.boolean().optional(),
  }),
  'rec:chunk': z.strictObject({
    sessionId,
    track: z.enum(REC_TRACKS),
    seq: z.number().int().min(0).max(1_000_000),
    data: z.instanceof(Uint8Array).refine((b) => b.byteLength > 0 && b.byteLength <= MAX_CHUNK, 'chunk: 1 byte - 8 MB'),
    startMs: z.number().int().min(0).optional(),
  }),
  'rec:mark': z.strictObject({
    sessionId,
    t: z.number().min(0).max(36000),
    kind: z.enum(['line', 'retake']),
    line: z.number().int().min(0).max(300),
  }),
  'rec:end': z.strictObject({ sessionId, secs: z.number().min(0).max(36000).optional() }),
  /** a take she deleted: its folder goes to the Trash (recoverable), never while it records */
  'rec:discard': z.strictObject({ sessionId }),
  'rec:recover': z.undefined(),
  /** the finished takes of one Record visit, newest first */
  'rec:list': z.strictObject({ group: z.string().regex(/^[a-z0-9]{6,32}$/) }),
  /** screens + windows she can share (thumbnails), or access 'denied' (macOS Screen Recording is off for the app) */
  'rec:screens': z.undefined(),
  /** the source the next getDisplayMedia shares (from rec:screens; used once, within 30 s) */
  'rec:screenPick': z.strictObject({ id: z.string().min(1).max(200) }),
} as const;

/** Allow a permission only for media (camera / mic / the screen she picked) from the app's own UI with the Create
 * flag on. Everything else keeps the default deny (platform pages have their own handler).
 * A screen share (getDisplayMedia) asks for 'media' with NO media types (Electron 44): refusing that empty list was
 * why "Share a screen too" did nothing in 0.2.4. What is shared is still decided by the display-media handler, which
 * only hands over the source she chose in the app's picker. */
export function allowMedia(o: { flag: boolean; fromMainWindow: boolean; isAppUrl: boolean; permission: string; mediaTypes?: string[] }): boolean {
  if (!o.flag || !o.fromMainWindow || !o.isAppUrl || o.permission !== 'media') return false;
  return (o.mediaTypes ?? []).every((t) => t === 'video' || t === 'audio');
}

export interface TakeInfo {
  id: string;
  dir: string;
  created: string | null;
  /** seconds recorded (pauses left out) */
  secs: number;
  /** the take was opened in the editor (final/recording.mp4) */
  edited: boolean;
  /** script lines reached / in the script; lines said again */
  lines: number;
  total: number;
  retakes: number;
}

export interface ScreenSource {
  id: string;
  name: string;
  kind: 'screen' | 'window';
  /** data: URL (a small thumbnail), '' when there is none */
  thumb: string;
}
export type ScreensReply = { access: 'granted'; sources: ScreenSource[] } | { access: 'denied'; sources: [] };

/** DESK_CREATE=1 / 0 (tests) beats the saved setting. */
export function createFlagFrom(saved: boolean | undefined, env: string | undefined): boolean {
  if (env === '1') return true;
  if (env === '0') return false;
  return saved !== false;
}
