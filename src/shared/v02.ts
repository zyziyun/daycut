// v0.2 shapes (PRODUCT_V02.md): clients, segment planning, in-review edits, delivery, metrics. Served by the
// desk engine (engine/desk_engine/studio.py), which calls the video-studio command when it exists and its own
// implementation otherwise. Pure helpers (word snapping, segment edits) live here so they are unit-tested.

export const FUNNEL = ['lead', 'contacted', 'sample', 'pilot', 'delivered', 'data', 'paid'] as const;
export type FunnelStage = (typeof FUNNEL)[number] | 'lost';
export const CLEANUP_PROFILES = ['gentle', 'standard', 'strict'] as const;
export const COVER_STYLES = ['frame', 'collage', 'face', 'text'] as const;
export const PROVIDERS = ['claude', 'openai', 'none'] as const;
export type Provider = (typeof PROVIDERS)[number];
export const V02_COMMANDS = ['plan-segments', 'client', 'job-edit', 'job-rerun', 'deliver', 'metrics', 'timing'] as const;

export interface Capabilities {
  mode: 'real' | 'mock';
  source: string | null;
  commands: Record<(typeof V02_COMMANDS)[number], boolean>;
  fallback: { plan: boolean; edit: boolean; rerun: boolean };
}

export interface GlossaryEntry {
  wrong: string;
  right: string;
  source?: string;
  batch?: string;
  job?: string;
}

export interface ClientConfig {
  name: string;
  style: string;
  platforms: string[];
  tags: string[];
  glossary: GlossaryEntry[];
  fillers: { extra: string[]; keep: string[] };
  brand: { accent?: string; highlight?: string; ink?: string };
  cover_style: (typeof COVER_STYLES)[number];
  cleanup_profile: (typeof CLEANUP_PROFILES)[number];
  notes: string;
}

export interface PostData {
  platform: string;
  url?: string;
  plays?: number;
  saves?: number;
  likes?: number;
  comments?: number;
  followers?: number;
  batch?: string;
  posted?: string;
  at: string;
}

export interface Crm {
  stage: FunnelStage | null;
  history: { stage: FunnelStage; at: string }[];
  revenue: { at: string; amount: number }[];
  posts: PostData[];
  price_next: number | null;
  note: string;
  lost: boolean;
}

export interface ClientSummary {
  slug: string;
  name: string;
  platforms: string[];
  stage: FunnelStage | null;
  batches: number;
  glossary: number;
}

export interface ClientDetail {
  slug: string;
  dir: string;
  config: Partial<ClientConfig>;
  effective: ClientConfig;
  batches: string[];
  crm: Crm;
}

export type ClientPatch = Partial<ClientConfig> & { glossary_add?: GlossaryEntry[] };

export interface CrmPatch {
  stage?: FunnelStage;
  revenue?: number;
  price_next?: number;
  note?: string;
  date?: string;
  post?: Omit<PostData, 'at'>;
}

// ---------------------------------------------------------------- planning
export interface Word {
  w: string;
  t: number;
  te: number;
}

export interface HookSpan {
  start: number;
  end: number;
  text: string;
}

export interface Segment {
  id: string;
  start: number;
  end: number;
  title: string;
  chapter?: string;
  hook?: HookSpan | null;
  hook_candidates?: HookSpan[];
  notes?: string[];
  tags?: string[];
  why?: string;
  risk?: string;
  score?: number;
  body?: string;
}

export interface PlanRequest {
  source: string;
  count: number;
  min: number;
  max: number;
  provider: Provider;
  platforms?: string[];
  client?: string;
}

export interface PlanState {
  id: string;
  state: 'running' | 'done' | 'error';
  progress: string;
  error: string | null;
  request: PlanRequest;
  result: { source: string; duration: number | null; provider: string; segments: Segment[]; words: Word[]; draft?: string } | null;
}

export interface PlanBatchBody {
  name: string;
  segments: Segment[];
  platforms: string[];
  client?: string;
  budget?: { max_usd?: number; max_hours?: number; max_storage_gb?: number };
  out_dir?: string;
}

// ---------------------------------------------------------------- job edits
export type EditOp = 'caption' | 'trim' | 'hook' | 'cover' | 'copy';

export type EditBody =
  | { op: 'caption'; cue: number; text: string }
  | { op: 'trim'; start: number; end: number }
  | { op: 'hook'; pick: number }
  | { op: 'cover'; t: number | null; text: string }
  | { op: 'copy'; title: string; body: string; tags: string[] };

export interface Cue {
  i: number;
  start: number;
  end: number;
  text: string;
  heard: string;
}

export interface EditHistoryEntry {
  n: number;
  op: EditOp;
  args: Record<string, unknown>;
  before: Record<string, unknown>;
  at: number;
  rerun: string[];
  glossary_added: GlossaryEntry | null;
}

export interface JobEditInfo {
  range: [number, number] | null;
  words: Word[];
  cues: Cue[];
  hooks: HookSpan[];
  hook_pick: number | null;
  cover: { t: number | null; text: string; file: string | null };
  copy: { title: string; body: string; tags: string[] };
  history: EditHistoryEntry[];
  pending: string[];
  reruns: number;
  can_edit: boolean;
  can_rerun: boolean;
  client: string | null;
}

export interface EditResult {
  ok: boolean;
  faithful: boolean;
  reason: string | null;
  ratio?: number;
  rerun: string[];
  pending?: string[];
  history?: EditHistoryEntry[];
  glossary_added: GlossaryEntry | null;
  undone?: EditHistoryEntry;
}

// ---------------------------------------------------------------- delivery
export interface DeliveryRecord {
  batch: string;
  client: string | null;
  at: number;
  date: string;
  dir: string;
  zip: string | null;
  items: number;
  jobs: number;
  duration_s: number | null;
  cleanup: { enabled: boolean; days: number | null; due: number | null; done: boolean };
  manifest?: { items: { path: string; sha256: string; bytes: number }[] } | null;
}

// ---------------------------------------------------------------- metrics
export interface MetricsSummary {
  jobs: number;
  reviewed: number;
  review_s_total: number;
  review_s_median: number | null;
  rework_rate: number | null;
  red_rate: number | null;
  cost_total: number;
  cost_per_clip: number | null;
  deliveries: number;
  delivered_items: number;
  delivered_clips: number;
  turnaround_h?: number | null;
}

export interface JobMetrics {
  id: string;
  title: string;
  state: string;
  qc: string | null;
  cost: number;
  review_s: number;
  reruns: number;
  edits: number;
  rejected: boolean;
  rework: number;
}

export interface MetricsDoc {
  scope: 'batch' | 'client' | 'all';
  source: 'desk' | 'engine';
  summary: MetricsSummary;
  jobs?: JobMetrics[];
  batches?: { batch: string; name: string; client: string | null; jobs: number; review_s_median: number | null; rework_rate: number | null; red_rate: number | null; cost_per_clip: number | null; delivered_clips: number; turnaround_h: number | null }[];
  crm?: Crm;
  clients?: (ClientSummary & { crm: Crm })[];
  name?: string;
}

export const WEEKLY_COLUMNS = [
  '周', '线索数', '沟通数', '样片数', '确认试点数', '交付数', '回传数据数', '付费数', '收入(¥)', '交付条数',
  '人审秒数中位数/条', '返工率', '质检红灯率', '每条成本($)', '内容号播放中位数', '内容号收藏率', '内容号涨粉', '工作室号有效线索',
] as const;
export const MANUAL_WEEKLY_COLUMNS = WEEKLY_COLUMNS.slice(14);

export interface WeeklyDoc {
  csv: string;
  rows: Record<string, string | number>[];
  columns: string[];
  source: 'desk' | 'engine';
}

// ---------------------------------------------------------------- pure helpers
/** Nearest word start (edge "start") or word end (edge "end"); t unchanged without words. Mirrors
 * desk_engine/planning.py snap(). */
export function snapToWord(t: number, words: Word[], edge: 'start' | 'end'): number {
  if (!words.length) return t;
  let best = edge === 'start' ? words[0].t : words[0].te;
  for (const w of words) {
    const v = edge === 'start' ? w.t : w.te;
    if (Math.abs(v - t) < Math.abs(best - t)) best = v;
  }
  return best;
}

/** Move an edge to the previous / next word edge (keyboard nudge). */
export function nudgeEdge(t: number, words: Word[], edge: 'start' | 'end', dir: -1 | 1): number {
  const edges = words.map((w) => (edge === 'start' ? w.t : w.te));
  if (dir > 0) return edges.find((v) => v > t + 1e-3) ?? t;
  for (let i = edges.length - 1; i >= 0; i--) if (edges[i] < t - 1e-3) return edges[i];
  return t;
}

/** Words whose midpoint is inside [a, b] (binary search; words are sorted by t). */
export function wordsIn(words: Word[], a: number, b: number): Word[] {
  let lo = 0;
  let hi = words.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].te < a) lo = mid + 1;
    else hi = mid;
  }
  const out: Word[] = [];
  for (let i = lo; i < words.length && words[i].t <= b; i++) {
    const m = (words[i].t + words[i].te) / 2;
    if (m >= a && m <= b) out.push(words[i]);
  }
  return out;
}

export function joinWords(ws: Word[]): string {
  let s = '';
  for (const w of ws) {
    if (s && /[A-Za-z0-9]$/.test(s) && /^[A-Za-z0-9]/.test(w.w)) s += ' ';
    s += w.w;
  }
  return s;
}

/** Set one edge of a segment, snapped to a word edge, keeping at least minLen seconds. */
export function setEdge<S extends { start: number; end: number }>(seg: S, edge: 'start' | 'end', t: number, words: Word[], minLen = 3): S {
  const v = snapToWord(t, words, edge);
  if (edge === 'start') return v <= seg.end - minLen ? { ...seg, start: v } : seg;
  return v >= seg.start + minLen ? { ...seg, end: v } : seg;
}

export interface ReviewedSegment extends Segment {
  accepted: boolean;
}

/** Accepted segments in time order, ready for POST /api/plans/<id>/batch. */
export function acceptedSegments(segs: ReviewedSegment[]): Segment[] {
  return segs
    .filter((s) => s.accepted && s.title.trim() && s.end > s.start)
    .sort((a, b) => a.start - b.start)
    .map(({ accepted: _a, ...s }) => ({ ...s, title: s.title.trim() }));
}

/** Segments that overlap another accepted one (shown as a warning; the engine accepts overlaps). */
export function overlaps(segs: ReviewedSegment[]): Set<string> {
  const acc = segs.filter((s) => s.accepted).sort((a, b) => a.start - b.start);
  const out = new Set<string>();
  for (let i = 1; i < acc.length; i++) {
    if (acc[i].start < acc[i - 1].end) {
      out.add(acc[i].id);
      out.add(acc[i - 1].id);
    }
  }
  return out;
}

/** Human reason for a rejected caption edit (engine reason codes). */
export const FAITHFUL_REASONS = ['empty', 'adds-words', 'differs-from-audio', 'punctuation', 'matches-audio', 'term-fix'] as const;

export function median(xs: number[]): number | null {
  const v = xs.filter((x) => Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = v.length >> 1;
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

// ---------------------------------------------------------------- history (past work, auto-discovered)
/** .vstudio/status.json of a job / batch / project folder, as the engine reads it (stale running -> interrupted). */
export interface LiveStatus {
  state: 'running' | 'waiting' | 'done' | 'failed' | 'interrupted';
  status: string;
  stage?: string | null;
  progress?: number | null;
  message?: string | null;
  eta?: number | null;
  started?: number | null;
  heartbeat?: number | null;
  finished?: number | null;
  age?: number | null;
  needs_you: boolean;
  updated_by?: string | null;
}
export const WORK_TYPES = ['talkinghead', 'slices', 'explainer', 'photo-story', 'vlog', 'podcast', 'aigc', 'script', 'batch', 'promo', 'slides', 'other'] as const;
export interface HistoryItem {
  kind: 'batch' | 'project' | 'work';
  type?: string;
  live?: LiveStatus | null;
  adopted?: boolean;
  id: string;
  dir: string;
  name: string;
  recipe: string | null;
  client: string | null;
  series?: string | null;
  created: number | null;
  updated: number | null;
  counts: { total: number; green: number; red: number; approved: number; done: number; failed: number };
  status: string;
  thumb: string | null;
  deliveries?: number;
  sources: ('desk' | 'engine' | 'watch')[];
  opened: boolean;
  openable: boolean;
  error?: string;
}
export interface HistoryDoc {
  items: HistoryItem[];
  watch: string[];
  at: number;
  running?: number;
}
export interface HistoryDetail extends HistoryItem {
  log?: { path: string; text: string } | null;
  detail?: {
    outputs: string[];
    covers: string[];
    sheets: string[];
    posts: { path: string; text: string }[];
    notes: { path: string; text: string }[];
    sources: string[];
    record: Record<string, unknown> | null;
  };
}
export interface HistoryConfig {
  watch: string[];
  hidden: number;
  default_watch: string[];
}
