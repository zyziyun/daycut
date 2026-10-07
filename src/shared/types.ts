// Shapes returned by the desk engine (engine/desk_engine). Kept loose where the batch engine is still moving.
import type { JobEditInfo } from './v02';

export type EngineMode = 'real' | 'mock';

export interface EngineInfo {
  baseUrl: string;
  token: string;
  mode: EngineMode;
  note?: string | null;
}

export interface Recipe {
  name: string;
  description: string;
  stages: string[];
}

export type BatchState = 'planned' | 'running' | 'pilot-review' | 'paused' | 'ran' | 'missing' | string;

export interface PackageMeta {
  code: string;
  dir: string;
  items: number;
}

export interface BatchSummary {
  id: string;
  dir: string;
  name: string;
  recipe?: string;
  state: BatchState;
  running: boolean;
  package?: PackageMeta | null;
  pause_reason?: string | null;
  counts?: Record<string, number>;
  error?: string;
  /** v0.2: client workspace slug + delivery state (desk adapter) */
  client?: string | null;
  delivered?: { at: number; items: number; dir: string } | null;
}

export type JobState =
  | 'planned'
  | 'running'
  | 'done'
  | 'failed'
  | 'approved'
  | 'needs-replan'
  | 'packaged'
  | 'dropped'
  | string;

export interface JobRow {
  id: string;
  state: JobState;
  progress: string;
  stage: string;
  qc: 'green' | 'red' | null;
  sample: boolean;
  pilot: boolean;
  review: string;
  duration: number | null;
  cost: number;
  note: string;
  title: string;
  platforms: string[];
  item: string;
  variant: string;
  qc_red: string[];
  qc_warn: string[];
  review_reason: string | null;
}

export interface BatchMeta {
  id: string;
  dir: string;
  name: string;
  recipe: string;
  state: BatchState;
  pause_reason: string | null;
  package: PackageMeta | null;
  pilot_jobs: string[];
  budget: { max_usd?: number; max_hours?: number; max_storage_gb?: number };
  platforms: string[];
  running: boolean;
}

export interface BatchStatus {
  meta: BatchMeta;
  jobs: JobRow[];
}

export interface Estimate {
  jobs: number;
  stages: Record<string, { units: number; seconds: number; bytes: number; n: number; resource: string; measured: boolean }>;
  resources: Record<string, number>;
  machine_s: number;
  wall_s: number;
  storage_bytes: number;
  api_usd: number;
  spent_usd: number;
  free_bytes: number | null;
  limits: Record<string, number>;
  budget: { ok: boolean; over: string[]; budget: Record<string, number> };
  text?: string;
}

export interface ConfirmEdit {
  id: number;
  part: string;
  kind: string;
  text: string;
  t0: number;
  t1: number;
  before: string;
  after: string;
  reason: string;
  confidence?: number;
}

export interface ReviewItem {
  id: string;
  item: string;
  variant: string;
  state: JobState;
  qc: 'green' | 'red' | 'none';
  reasons: string[];
  warnings: string[];
  sample: boolean;
  pilot: boolean;
  review: string | null;
  review_reason: string | null;
  title: string;
  platforms: string[];
  range: [number, number] | null;
  hook: string[];
  duration: number | null;
  sheet: string | null;
  snippet: string | null;
  files: string[];
  confirm: ConfirmEdit[];
  reply: string;
}

export interface Decision {
  decision: 'approve' | 'reject';
  reason?: string;
}

export interface DecisionsBody {
  decisions?: Record<string, Decision>;
  cleanup?: Record<string, string>;
}

export interface ApplyResult {
  approved: string[];
  rejected: string[];
  replied: string[];
  skipped: [string, string][];
}

export interface CleanupEdit {
  id: number;
  t0: number;
  t1: number;
  kind: string;
  text: string;
  action: 'auto' | 'confirm' | 'keep';
  reason: string;
  confidence?: number;
  words: number[];
  cut: boolean;
}

export interface CleanupPart {
  part: 'hook' | 'body' | string;
  words: { w: string; t: number; te: number }[];
  edits: CleanupEdit[];
  stats?: Record<string, number> | null;
}

export interface JobDetail {
  job: {
    id: string;
    item: string;
    variant: string;
    state: JobState;
    qc: string | null;
    qc_reasons: { red?: string[]; warn?: string[]; checks?: unknown[] } | null;
    review: string | null;
    review_reason: string | null;
    pilot: number;
    sample: number;
    cost: number;
    params: Record<string, unknown>;
  };
  stages: { name: string; state: string; seconds: number | null; error: string | null; cached: boolean; attempts: number }[];
  events: EngineEvent[];
  cleanup: { reply: string; parts: CleanupPart[] };
  media: {
    master: string | null;
    sheet: string | null;
    snippet: string | null;
    exports: { platform: string; orientation: string; file: string; cover?: string; post?: string; duration?: number }[];
  };
  /** v0.2: everything the in-review editors need (desk adapter) */
  edit?: JobEditInfo;
}

export interface EngineEvent {
  ts: number;
  job: string | null;
  stage: string | null;
  kind: string;
  msg: string;
}

export interface ManifestItem {
  job: string;
  platform: string; // "<platform>-<orientation>", e.g. tiktok-vertical
  title: string;
  date: string;
  time: string;
  files: { video: string; cover?: string; post?: string };
  sha256: string;
  bytes: number;
  duration: number | null;
}

export interface Manifest {
  batch: string;
  schedule: { per_day: number; start: string; times: string[] };
  items: ManifestItem[];
  confirmation_code: string;
  note?: string;
}

export interface ManifestVerify {
  ok: boolean;
  code?: string;
  stored?: string;
  items?: number;
  reason?: string | null;
}

export interface ManifestResponse {
  manifest: Manifest | null;
  dir: string | null;
  verify: ManifestVerify;
}

export interface PackageResult {
  dir: string;
  code: string;
  items: number;
  jobs: number;
  manifest: string;
}

export interface RunOptions {
  pilot?: number;
  confirm_pilot?: boolean;
  resume?: boolean;
  retry_failed?: boolean;
  jobs?: string[];
}

export interface CreateBatchBody {
  name: string;
  recipe: string;
  source?: string;
  folder?: string;
  segments?: string;
  platforms: string[];
  budget?: { max_usd?: number; max_hours?: number; max_storage_gb?: number };
  out_dir?: string;
  client?: string;
}

export type StreamEvent =
  | { type: 'status'; batch: string; status: BatchStatus; ts: number }
  | { type: 'log'; batch: string; line: string; ts: number }
  | { type: 'run-start'; batch: string; cmd: string[]; ts: number }
  | { type: 'run-exit'; batch: string; code: number; status: string; ts: number }
  | { type: 'batches'; ts: number }
  | { type: 'clients'; ts: number }
  | { type: 'plan'; plan: string; state: string; progress: string; ts: number }
  | { type: 'job-edit'; batch: string; job: string; ts: number }
  | { type: 'output-edit'; item: string; clip: string; ts: number }
  | { type: 'output-transcribe'; item: string; clip: string; state: 'running' | 'done' | 'failed'; error?: string; words?: number; ts: number }
  | { type: 'output-render'; item: string; clip: string; job: string; event: 'target-start' | 'stage-done' | 'target-done' | 'render-done' | 'stopped' | 'failed'; target?: string; stage?: string; progress?: number; file?: string; error?: string; simulated?: boolean; ts: number }
  | { type: 'intake'; id: string; state: string; ts: number }
  | { type: 'inbox'; ts: number }
  | { type: 'calendar'; ts: number };
