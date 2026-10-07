// The confirmation rule (DESIGN v0.2 #4): only items of a package manifest the creator confirmed - identified
// by its content hash (the confirmation code) - can be filled into a platform. Any change to the manifest gives
// a new code, so an old confirmation no longer matches and filling is refused.
import type { Manifest, ManifestItem, ManifestVerify } from '../types';
import { adapterFor, type Adapter } from './adapterSchema';

export interface Confirmation {
  batchId: string;
  code: string;
  items: number;
  confirmedAt: string;
}

export interface FillRequest {
  batchId: string;
  code: string;
  job: string;
  platform: string; // package key, e.g. tiktok-vertical
  adapterId: string;
}

export type GateResult =
  | { ok: true; item: ManifestItem; adapter: Adapter }
  | { ok: false; reason: GateReason; detail?: string };

export type GateReason =
  | 'no-manifest'
  | 'manifest-changed'
  | 'code-mismatch'
  | 'not-confirmed'
  | 'item-not-in-manifest'
  | 'adapter-mismatch'
  | 'adapter-todo';

export function checkFill(
  req: FillRequest,
  manifest: Manifest | null,
  verify: ManifestVerify,
  confirmations: Confirmation[],
  adapters: Adapter[],
): GateResult {
  if (!manifest) return { ok: false, reason: 'no-manifest' };
  // 1. the manifest on disk still hashes to its own code (nobody edited it after `package`)
  if (!verify.ok || verify.code !== manifest.confirmation_code) {
    return { ok: false, reason: 'manifest-changed', detail: verify.reason ?? undefined };
  }
  // 2. the request is about this exact manifest
  if (req.code !== manifest.confirmation_code) return { ok: false, reason: 'code-mismatch' };
  // 3. the creator confirmed this exact code for this batch
  if (!confirmations.some((c) => c.batchId === req.batchId && c.code === req.code)) {
    return { ok: false, reason: 'not-confirmed' };
  }
  // 4. the item is listed
  const item = manifest.items.find((i) => i.job === req.job && i.platform === req.platform);
  if (!item) return { ok: false, reason: 'item-not-in-manifest' };
  // 5. the adapter posts this platform and is not a placeholder
  const adapter = adapters.find((a) => a.id === req.adapterId);
  if (!adapter || adapterFor(item.platform, [adapter]) === undefined) {
    return { ok: false, reason: 'adapter-mismatch' };
  }
  if (adapter.status === 'todo') return { ok: false, reason: 'adapter-todo' };
  return { ok: true, item, adapter };
}

/** Resolve a manifest-relative file inside the package folder; refuses anything that escapes it. */
export function resolveInside(dir: string, rel: string, sep = '/'): string | null {
  if (!rel || rel.includes('\0') || rel.startsWith('/') || /^[A-Za-z]:/.test(rel)) return null;
  const parts: string[] = [];
  for (const p of rel.split(/[\\/]+/)) {
    if (p === '' || p === '.') continue;
    if (p === '..') return null;
    parts.push(p);
  }
  if (!parts.length) return null;
  return dir.replace(/[\\/]+$/, '') + sep + parts.join(sep);
}
