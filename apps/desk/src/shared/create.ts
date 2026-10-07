// Create page (创作): renderer types that mirror the engine's vstudio.create JSON (model / views / costs) and a thin
// client over the desk engine's /api/create/* routes. Pure: shared by the renderer and unit tests.

export type Lang3 = 'en' | 'zh' | 'fr';
export type L10n = Partial<Record<Lang3, string>> & { en: string };
export interface Msg {
  code: string;
  params: Record<string, unknown>;
}

export type FormatId = 'series-ad' | 'product-spot' | 'interview' | 'talk-show' | 'sketch' | 'record';
export const FORMAT_IDS: FormatId[] = ['series-ad', 'product-spot', 'interview', 'talk-show', 'sketch', 'record'];

export interface Format {
  id: FormatId;
  order: number;
  icon: string;
  labels: L10n;
  blurb: L10n;
  recipe: 'ai-video' | 'talkinghead';
  aspect: string;
  length_s: [number, number];
  episodes: number;
  engine: L10n;
  beats: { id: string; labels: L10n; repeat?: number }[];
  cast_slots: { id: string; role: L10n; faces?: boolean; own?: boolean }[];
  sources: Record<string, string>;
  rules: { always: L10n[]; never: L10n[] };
}

export interface CastMember {
  id: string;
  name: string;
  essence: string;
  look: string;
  own?: boolean;
  look_refs?: string[];
  face_locked?: string;
  voice?: { engine?: string; ref?: string };
}

export interface Bible {
  engine: string;
  beats: { id: string; label: string; n?: number | null }[];
  cast: CastMember[];
  rules: { always: string[]; never: string[] };
  languages: string[];
  aspect: string;
  length_s: number;
  ai_generated?: boolean;
}

export interface Idea {
  id: string;
  title: string;
  logline: string;
  notes?: string;
  est_cny: number;
  picked?: boolean;
  episode?: string;
}

export interface SeriesDraft {
  format: FormatId;
  recipe: string;
  name: string;
  lang: string;
  bible: Bible;
  ideas: Idea[];
  episodes: number;
  budget_cny: number | null;
  platforms: string[];
  source: 'ai' | 'rules';
}

export interface SeriesSummary {
  id: string;
  name: string;
  format: FormatId;
  episodes: number;
  planned: number | null;
  last: number;
  budget: number | null;
  spent: number;
  status: Msg | null;
  cover: string | null;
  sample: boolean;
}

export interface Ladder {
  stills?: string;
  animatic?: string;
  drafts?: string;
  finals?: string;
  assemble?: string;
}

export interface EpisodeRow {
  id: string;
  no: number;
  title: string;
  logline: string;
  shots: number;
  status: Msg;
  state: string;
  ladder: Ladder | null;
  cover: string | null;
  handoff: Handoff | null;
}

export interface Spend {
  month: string;
  cap: number | null;
  used: number;
  series?: { budget: number | null; spent: number };
  lines?: Record<string, unknown>[];
}

export interface SeriesView {
  id: string;
  name: string;
  format: Format;
  recipe: string;
  meta: { format: FormatId; budget_cny: number | null; languages: string[]; episodes: number | null; lang: string; sample?: boolean };
  platforms: string[];
  bible: Bible;
  ideas: Idea[];
  episodes: EpisodeRow[];
  spend: Spend;
  counts: { making: number; ready: number };
}

export type SourceKind = 'cloud' | 'mcp' | 'manual' | 'local' | 'record' | 'card' | 'reuse' | 'placeholder';

export interface Route {
  no: string;
  source: string;
  kind: SourceKind;
  provider: string | null;
  model: string | null;
  why: string;
  hard: boolean;
  hard_rank?: number;
  cny: number | null;
  credits: number | null;
  connected: boolean;
  label: string | null;
}

export interface SourceOption {
  source: string;
  kind: SourceKind;
  provider: string | null;
  model: string | null;
  label: string | null;
  cny: number | null;
  credits: number | null;
  note: string;
  connected: boolean;
}

export interface Take {
  file: string;
  unit?: string;
  provider?: string;
  model?: string;
  at?: string;
}

export interface Shot {
  no: string;
  beat: string;
  dur: number;
  faces: string[];
  camera: string;
  action: string;
  lines: { who: string; text: string }[];
  card?: string | null;
  source?: string | null;
  still?: string;
  route: Route;
  takes: Take[];
  pick?: string | null;
  options: SourceOption[];
}

export interface EstimateLine {
  provider: string;
  model: string;
  label: string;
  kind: SourceKind;
  shots: string[];
  units: number;
  seconds_video: number;
  seconds_billed: number;
  native_units: number | null;
  cny: number;
  manual: boolean;
  verified: boolean;
}

export interface Estimate {
  id: string;
  stage: string;
  episode: string;
  lines: EstimateLine[];
  free: Record<string, number>;
  subtotal_cny: number;
  retry_pct: number;
  retry_cny: number;
  max_cny: number;
  unknown: string[];
  confirm_code: string | null;
  expires_at: number;
  hard_first: string[];
  n_paid: number;
  n_manual: number;
  only?: string[] | null;
  budget: { budget: number | null; spent: number; left_after: number | null };
  month: { cap: number | null; used: number; left_after: number | null };
  warnings?: Msg[];
}

export interface Handoff {
  dir: string;
  file: string;
  clip: string;
  /** the desk's history item id of the delivered work folder (open in the editor: #/p/<id>/clip/<clip>) */
  item_id: string;
  languages: { lang: string; kind: 'original' | 'bilingual' | 'translated'; state: 'ready' | 'check'; n_check: number; platforms: string[] }[];
  posts: { lang: string; platforms: string[]; at: string; clip: string }[];
  spent: number;
  approved: number;
  under: number | null;
  ai_label: boolean;
  at: string;
}

export interface RunUnit {
  state: string;
  provider: string;
  shots: string[];
  code?: string;
  task?: string;
  cny?: number;
  hard?: boolean;
}

export interface EpisodeView {
  id: string;
  series: string;
  series_name: string;
  no: number;
  title: string;
  logline: string;
  state: string;
  script?: { beats: { beat: string; lines: { who: string; text: string }[] }[]; source: string };
  shots: Shot[];
  format: Format;
  bible: { cast: CastMember[]; aspect: string; length_s: number; languages: string[] };
  policy: Record<string, string | boolean>;
  warnings: Msg[];
  estimate: Estimate;
  next: { step: 'stills' | 'animatic' | 'finals' | 'pick' | 'making' | 'assemble' | 'ready'; n?: number; cny?: number };
  status: Msg;
  connected: string[];
  runtime: number;
  ladder?: Ladder;
  run?: { state: string; units: Record<string, RunUnit>; alerts?: (Msg & { at: number })[]; paused?: Msg; approved_cny?: number; spent_cny?: number };
  handoff?: Handoff | null;
  picks?: Record<string, string>;
  animatic?: string | null;
  lint?: Msg[];
  manual_prompts_file?: string | null;
}

export type CellState = 'ok' | 'run' | 'local' | 'you' | 'bad' | 'q' | 'pick';

export interface MakingRow {
  id: string;
  series: string;
  no: number;
  title: string;
  stage: string | null;
  state: string;
  cells: { no: string; state: CellState; still?: string; n_takes: number; provider?: string | null }[];
  spent: number;
  pick: number;
  done: number;
  total: number;
  paused?: Msg | null;
  eta_min?: number | null;
}

export interface MakingView {
  rows: MakingRow[];
  alerts: (Msg & { at: number; episode: string; episode_no: number; series: string })[];
  spent: number;
  approved: number;
  running: Record<string, number>;
  eta: string | null;
  limits: Record<string, number>;
}

export interface ProviderStatus {
  id: string;
  label: L10n;
  kind: 'cloud' | 'mcp' | 'manual' | 'local';
  needs: string[];
  tos: string;
  license: string | null;
  models: string[];
  ready: boolean;
  code: string;
  params: Record<string, unknown>;
  balance?: number | null;
  site?: string;
}

export interface CreateJob<T = unknown> {
  id: string;
  kind: string;
  state: 'running' | 'done' | 'error';
  result: T | null;
  error: Msg | null;
  events: Record<string, unknown>[];
}

// ------------------------------------------------------------------ validation (mirrors the engine's)
export const SID_RE = /^[a-z0-9][a-z0-9-]{0,47}$/;
export const SHOT_RE = /^\d{2,3}$/;
export const SOURCE_RE = /^(cloud|manual|local):[a-z0-9-]+(\/[\w.-]+)?$|^(record|card)$|^reuse:[a-z0-9-]+\/\d{2,3}$/;
export const CODE_RE = /^[0-9a-f]{8}$/;

function sid(v: string): string {
  if (!SID_RE.test(v)) throw new Error(`bad id ${v}`);
  return v;
}
function shot(v: string): string {
  if (!SHOT_RE.test(v)) throw new Error(`bad shot ${v}`);
  return v;
}

export type Req = <T>(method: 'GET' | 'POST', path: string, body?: unknown) => Promise<T>;

/** /api/create/* (EngineClient.create). Every long call returns {job}; poll job(id). */
export class CreateClient {
  constructor(private req: Req) {}
  formats() {
    return this.req<{ formats: Format[] }>('GET', '/api/create/formats');
  }
  providers() {
    return this.req<{ providers: ProviderStatus[]; rates_version: string }>('GET', '/api/create/providers');
  }
  testProvider(id: string) {
    return this.req<{ ok: boolean; code: string; params: Record<string, unknown> }>('POST', `/api/create/providers/${sid(id)}/test`);
  }
  /** mode: auto = the AI writes the plan (a clear create.ai-failed when none answers); template = the format's own
   *  outline, no AI call ("Start from the template"). Progress: ``create.step`` events on the job. */
  plan(body: { prompt?: string; format?: FormatId; budget_cny?: number; platforms?: string[]; lang?: Lang3; mode?: 'auto' | 'template' }) {
    return this.req<{ job: string }>('POST', '/api/create/plan', body);
  }
  createSeries(draft: SeriesDraft) {
    return this.req<{ ok: boolean; series: string; view: SeriesView }>('POST', '/api/create/series', { draft });
  }
  sample(lang: Lang3) {
    return this.req<{ ok: boolean; series: string; episode: string | null }>('POST', '/api/create/sample', { lang });
  }
  listSeries() {
    return this.req<{ series: SeriesSummary[] }>('GET', '/api/create/series');
  }
  series(id: string) {
    return this.req<SeriesView>('GET', `/api/create/series/${sid(id)}`);
  }
  reviseBible(id: string, instruction: string) {
    return this.req<{ job: string }>('POST', `/api/create/series/${sid(id)}/bible`, { instruction });
  }
  patchBible(id: string, patch: Partial<Bible>) {
    return this.req<{ bible: Bible }>('POST', `/api/create/series/${sid(id)}/bible`, { patch });
  }
  moreIdeas(id: string, n = 4) {
    return this.req<{ job: string }>('POST', `/api/create/series/${sid(id)}/ideas`, { n });
  }
  addEpisodes(id: string, ideaIds: string[]) {
    return this.req<{ job: string }>('POST', `/api/create/series/${sid(id)}/episodes`, { idea_ids: ideaIds });
  }
  seriesSettings(id: string, body: { budget_cny?: number | null }) {
    return this.req<SeriesView>('POST', `/api/create/series/${sid(id)}/settings`, body);
  }
  episode(id: string) {
    return this.req<EpisodeView>('GET', `/api/create/episodes/${sid(id)}`);
  }
  setSource(id: string, no: string, source: string) {
    if (!SOURCE_RE.test(source)) throw new Error(`bad source ${source}`);
    return this.req<EpisodeView>('POST', `/api/create/episodes/${sid(id)}/shots/${shot(no)}`, { source });
  }
  route(id: string, instruction: string, apply = false) {
    return this.req<{ changes: { no: string; from: string; to: string }[]; applied: boolean; view: EpisodeView | null }>(
      'POST',
      `/api/create/episodes/${sid(id)}/route`,
      { instruction, apply },
    );
  }
  estimate(id: string, stage = 'finals', only?: string[]) {
    const q = `?stage=${encodeURIComponent(stage)}${only?.length ? `&only=${only.map(shot).join(',')}` : ''}`;
    return this.req<Estimate>('GET', `/api/create/episodes/${sid(id)}/estimate${q}`);
  }
  run(id: string, body: { stage: string; estimate_id?: string; confirm_code?: string; max_cny?: number; allow_unknown?: boolean; only?: string[]; hard_first?: boolean }) {
    if (body.confirm_code !== undefined && !CODE_RE.test(body.confirm_code)) throw new Error('bad confirm code');
    return this.req<{ job: string }>('POST', `/api/create/episodes/${sid(id)}/run`, body);
  }
  stop(id: string) {
    return this.req<{ ok: boolean }>('POST', `/api/create/episodes/${sid(id)}/stop`);
  }
  pick(id: string, no: string, take: string) {
    return this.req<{ ok: boolean }>('POST', `/api/create/episodes/${sid(id)}/takes/${shot(no)}`, { take });
  }
  importTakes(id: string, files: string[]) {
    return this.req<{ ok: boolean; imported: { shot: string; file: string }[] }>('POST', `/api/create/episodes/${sid(id)}/import`, { files });
  }
  prompts(id: string) {
    return this.req<{ prompts: { unit: string; shots: string[]; prompt: string; seconds: number }[] }>('GET', `/api/create/episodes/${sid(id)}/prompts`);
  }
  handoff(id: string, languages: string[], schedule = true) {
    return this.req<{ job: string }>('POST', `/api/create/episodes/${sid(id)}/handoff`, { languages, schedule });
  }
  runs(series?: string) {
    return this.req<MakingView>('GET', `/api/create/runs${series ? `?series=${sid(series)}` : ''}`);
  }
  ingest(sessionDir: string, target = 'project:talkinghead', series?: string) {
    return this.req<{ job: string }>('POST', '/api/create/record/ingest', series ? { session_dir: sessionDir, target, series } : { session_dir: sessionDir, target });
  }
  recover() {
    return this.req<{ recovered: { dir: string; id: string; tracks: string[] }[] }>('POST', '/api/create/record/recover');
  }
  spend(series?: string) {
    return this.req<Spend>('GET', `/api/create/spend${series ? `?series=${sid(series)}` : ''}`);
  }
  setCap(cap: number) {
    return this.req<Spend>('POST', '/api/create/spend/cap', { cap_cny: cap });
  }
  job<T = unknown>(id: string) {
    if (!/^[0-9a-f]{12}$/.test(id)) throw new Error('bad job id');
    return this.req<CreateJob<T>>('GET', `/api/create/jobs/${id}`);
  }
}

/** Money as the UI shows it: ¥53, ¥5.0 (one decimal under ¥10), "free" handled by the caller. */
export function yuan(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '¥–';
  return n < 10 && n % 1 !== 0 ? `¥${n.toFixed(1)}` : `¥${Math.round(n)}`;
}

/** The source swatch colour class for a route / option (8 px chips; tokens in create.css). */
export function swatch(kind: SourceKind | string, provider?: string | null): string {
  if (kind === 'record') return 'record';
  if (kind === 'card') return 'card';
  if (kind === 'reuse') return 'reuse';
  if (kind === 'local' || kind === 'placeholder') return 'local';
  if (provider === 'kling-mcp') return 'kling';
  if (provider === 'minimax') return 'hailuo';
  if (provider === 'veo') return 'veo';
  return 'seed';
}
