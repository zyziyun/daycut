// Share for review (engine: lib/vstudio/project/share.py, desk sidecar: engine/desk_engine/share.py).
import type { EngineMsg } from './v04';

export type ShareQuality = 'small' | 'standard' | 'high';

export interface PrivacyWarning extends Omit<EngineMsg, 'params'> {
  level: 'warn' | 'info';
  params?: { clips?: string[] | null } & Record<string, unknown>;
}

export interface ShareOptions {
  item: string;
  title: string;
  out_root: string;
  clips: { id: string; title: string; cover: string | null; duration: number | null; versions: string[]; caption: boolean }[];
  privacy: { ok: boolean; warnings: PrivacyWarning[]; needs_ack: boolean };
}

export interface ShareRequest {
  clips?: string[];
  quality?: ShareQuality;
  footer?: boolean;
  title?: string;
  expiry_note?: string;
  owner_name?: string;
  zip?: boolean;
  ack?: boolean;
}

export interface ShareResult {
  share: string;
  dir: string;
  index: string;
  zip: string | null;
  bytes: number;
  zip_bytes: number | null;
  clips: { id: string; title: string; versions: number }[];
}

export interface ShareJob {
  id: string;
  state: 'running' | 'done' | 'failed';
  done: number;
  total: number;
  result: ShareResult | null;
  error: EngineMsg | null;
}
