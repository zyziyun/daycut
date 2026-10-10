// HTTP client for the desk engine. Used by the renderer (token from preload) and by the main process. Both address it
// as app://desk/api/...: the renderer's fetch goes to main's app:// protocol handler, main's own client gets a fetch
// that talks to the engine's socket directly (src/main/engineTransport.ts). The engine never listens on a port the
// page could reach.
import type { WatermarkDoc, WatermarkSettings } from './watermark';
import type {
  ApplyResult,
  BatchStatus,
  BatchSummary,
  CreateBatchBody,
  DecisionsBody,
  EngineEvent,
  Estimate,
  JobDetail,
  ManifestResponse,
  PackageResult,
  Recipe,
  ReviewItem,
  RunOptions,
  StreamEvent,
} from './types';
import type {
  Capabilities,
  ClientDetail,
  ClientPatch,
  ClientSummary,
  Crm,
  CrmPatch,
  DeliveryRecord,
  EditBody,
  EditResult,
  HistoryConfig,
  HistoryDetail,
  HistoryDoc,
  SampleInfo,
  MetricsDoc,
  PlanBatchBody,
  PlanRequest,
  PlanState,
  WeeklyDoc,
} from './v02';
import type { AskContext, ChatTurn, ExportJob } from './chatEdit';
import type { StripInfo, TranscribeState } from './timeline';
import type { WeekPlan, WeekPlanStart } from './weekPlan';
import type { ShareJob, ShareOptions, ShareRequest } from './share';
import type { AskResult, AutopilotDoc, CalendarDoc, CalendarPost, ClipsDoc, NewPost, SchedulePlan, EditOp, EffectDef, EngineMsg, InboxDoc, IntakeJob, IntakePlan, OpenRequest, OutputDoc, PreviewEdl, ProjectAskJob, Retimed } from './v04';

import { CreateClient } from './create';

export class EngineError extends Error {
  constructor(
    public status: number,
    message: string,
    /** engine refusals: a code + params the UI localises, and the engine's Chinese text */
    public code?: string,
    public params?: Record<string, unknown>,
    public messageZh?: string,
  ) {
    super(message);
    this.name = 'EngineError';
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** Where the UI reaches the engine: same origin as the app page (main forwards it to the engine). */
export const ENGINE_BASE = 'app://desk';

const ID_RE = /^[0-9a-f]{12}$/;
const JOB_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const CLIENT_RE = /^[a-z0-9][a-z0-9_-]{0,39}$/;

function cid(slug: string): string {
  if (!CLIENT_RE.test(slug)) throw new EngineError(400, `bad client ${slug}`);
  return slug;
}

function pid(id: string): string {
  if (!ID_RE.test(id)) throw new EngineError(400, `bad plan id ${id}`);
  return id;
}

function bid(id: string): string {
  if (!ID_RE.test(id)) throw new EngineError(400, `bad batch id ${id}`);
  return id;
}

function jid(id: string): string {
  if (!JOB_RE.test(id)) throw new EngineError(400, `bad job id ${id}`);
  return encodeURIComponent(id);
}

/** Clip ids are file stems (Chinese allowed): no separators, never a path. */
export function clipId(id: string): string {
  if (!/^[\p{L}\p{N}_][\p{L}\p{N}_ .()+-]{0,119}$/u.test(id) || id.includes('..')) throw new EngineError(400, `bad clip id ${id}`);
  return encodeURIComponent(id);
}

export class EngineClient {
  constructor(
    private baseUrl: string,
    private token: string,
    private fetchImpl: FetchLike = (...a) => fetch(...a),
  ) {
    if (baseUrl !== ENGINE_BASE) throw new EngineError(0, `engine must be on ${ENGINE_BASE}`);
  }

  private async req<T>(method: 'GET' | 'POST', path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
    const headers: Record<string, string> = { Authorization: `Bearer ${this.token}` };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    let r: Response;
    try {
      r = await this.fetchImpl(this.baseUrl + path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal,
      });
    } catch (e) {
      throw new EngineError(0, `engine unreachable: ${(e as Error).message}`);
    }
    const text = await r.text();
    let data: unknown;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      throw new EngineError(r.status, `bad response from engine (${r.status})`);
    }
    if (!r.ok) {
      const d = (data && typeof data === 'object' ? data : {}) as { error?: unknown; code?: unknown; params?: unknown; message_zh?: unknown };
      const msg = (d.error ? String(d.error) : '') || r.statusText;
      throw new EngineError(
        r.status,
        msg,
        typeof d.code === 'string' ? d.code : undefined,
        d.params && typeof d.params === 'object' ? (d.params as Record<string, unknown>) : undefined,
        typeof d.message_zh === 'string' ? d.message_zh : undefined,
      );
    }
    return data as T;
  }

  /** Create page routes (/api/create/*) */
  get create(): CreateClient {
    return new CreateClient((m, p, b) => this.req(m, p, b));
  }

  health() {
    return this.req<{ ok: boolean; mode: string; engine_path: string | null }>('GET', '/api/health');
  }
  recipes() {
    return this.req<Recipe[]>('GET', '/api/recipes');
  }
  roots() {
    return this.req<string[]>('GET', '/api/roots');
  }
  batches() {
    return this.req<BatchSummary[]>('GET', '/api/batches');
  }
  createBatch(b: CreateBatchBody) {
    return this.req<{ id: string; dir: string; jobs: string[] }>('POST', '/api/batches', b);
  }
  importBatch(dir: string) {
    return this.req<{ id: string; dir: string }>('POST', '/api/batches/import', { dir });
  }
  status(id: string) {
    return this.req<BatchStatus>('GET', `/api/batches/${bid(id)}`);
  }
  estimate(id: string) {
    return this.req<Estimate>('GET', `/api/batches/${bid(id)}/estimate`);
  }
  run(id: string, opts: RunOptions = {}) {
    return this.req<{ started: boolean; status?: string; over?: string[] }>('POST', `/api/batches/${bid(id)}/run`, opts);
  }
  cancel(id: string) {
    return this.req<{ cancelled: boolean }>('POST', `/api/batches/${bid(id)}/cancel`, {});
  }
  review(id: string) {
    return this.req<ReviewItem[]>('GET', `/api/batches/${bid(id)}/review`);
  }
  applyReview(id: string, d: DecisionsBody) {
    return this.req<ApplyResult>('POST', `/api/batches/${bid(id)}/review/apply`, d);
  }
  package(id: string, opts: { per_day?: number; start?: string; times?: string[] } = {}) {
    return this.req<PackageResult>('POST', `/api/batches/${bid(id)}/package`, opts);
  }
  /** a work folder / project: chosen clips x platforms -> per-platform package (engine workpkg.py) */
  packageWork(id: string, opts: { clips: string[]; platforms: string[]; per_day?: number; start?: string; times?: string[]; times_by_platform?: Record<string, string[]> }) {
    return this.req<{ dir: string; items: number; confirmation_code: string; checks: number }>('POST', `/api/batches/${bid(id)}/package`, opts);
  }
  manifest(id: string) {
    return this.req<ManifestResponse>('GET', `/api/batches/${bid(id)}/package`);
  }
  events(id: string, n = 50, job?: string) {
    const q = new URLSearchParams({ n: String(n) });
    if (job) q.set('job', job);
    return this.req<EngineEvent[]>('GET', `/api/batches/${bid(id)}/events?${q}`);
  }
  job(id: string, job: string) {
    return this.req<JobDetail>('GET', `/api/batches/${bid(id)}/jobs/${jid(job)}`);
  }

  // ---------------------------------------------------------------- v0.2 (PRODUCT_V02.md)
  capabilities() {
    return this.req<Capabilities>('GET', '/api/capabilities');
  }
  clients() {
    return this.req<ClientSummary[]>('GET', '/api/clients');
  }
  client(slug: string) {
    return this.req<ClientDetail>('GET', `/api/clients/${cid(slug)}`);
  }
  createClient(body: ClientPatch & { slug: string; name: string }) {
    cid(body.slug);
    return this.req<ClientDetail>('POST', '/api/clients', body);
  }
  updateClient(slug: string, patch: ClientPatch) {
    return this.req<ClientDetail>('POST', `/api/clients/${cid(slug)}`, patch);
  }
  setCrm(slug: string, patch: CrmPatch) {
    return this.req<Crm>('POST', `/api/clients/${cid(slug)}/crm`, patch);
  }
  setBatchClient(id: string, client: string | null) {
    return this.req<{ id: string; client: string | null }>('POST', `/api/batches/${bid(id)}/client`, { client: client ? cid(client) : null });
  }
  startPlan(body: PlanRequest) {
    return this.req<{ id: string }>('POST', '/api/plans', body);
  }
  plan(id: string) {
    return this.req<PlanState>('GET', `/api/plans/${pid(id)}`);
  }
  planToBatch(id: string, body: PlanBatchBody) {
    return this.req<{ id: string; dir: string; jobs: string[] }>('POST', `/api/plans/${pid(id)}/batch`, body);
  }
  editJob(id: string, job: string, body: EditBody) {
    return this.req<EditResult>('POST', `/api/batches/${bid(id)}/jobs/${jid(job)}/edit`, body);
  }
  undoJob(id: string, job: string) {
    return this.req<EditResult>('POST', `/api/batches/${bid(id)}/jobs/${jid(job)}/undo`, {});
  }
  rerunJob(id: string, job: string) {
    return this.req<{ started: boolean; stages: string[] }>('POST', `/api/batches/${bid(id)}/jobs/${jid(job)}/rerun`, {});
  }
  timing(id: string, body: { job: string; event: 'start' | 'stop'; what: 'review'; active_s?: number }) {
    jid(body.job);
    return this.req<{ ok: boolean; job_s: number }>('POST', `/api/batches/${bid(id)}/timing`, body);
  }
  deliver(id: string, body: { client?: string; zip?: boolean; cleanup_days?: number | null }) {
    return this.req<DeliveryRecord>('POST', `/api/batches/${bid(id)}/deliver`, body);
  }
  delivery(id: string) {
    return this.req<{ delivery: DeliveryRecord | null }>('GET', `/api/batches/${bid(id)}/deliver`);
  }
  setCleanup(id: string, body: { enabled: boolean; days?: number | null }) {
    return this.req<DeliveryRecord>('POST', `/api/batches/${bid(id)}/deliver/cleanup`, body);
  }
  metrics(scope: { batch?: string; client?: string } = {}) {
    const q = new URLSearchParams();
    if (scope.batch) q.set('batch', bid(scope.batch));
    if (scope.client) q.set('client', cid(scope.client));
    const qs = q.toString();
    return this.req<MetricsDoc>('GET', `/api/metrics${qs ? `?${qs}` : ''}`);
  }
  weekly() {
    return this.req<WeeklyDoc>('GET', '/api/metrics/weekly');
  }
  setWeekly(week: string, values: Record<string, number | string | null>) {
    return this.req<WeeklyDoc>('POST', '/api/metrics/weekly', { week, values });
  }
  history(f: { q?: string; status?: string; kind?: 'batch' | 'project' | 'work'; type?: string; client?: string; archived?: boolean } = {}) {
    const q = new URLSearchParams();
    if (f.archived) q.set('archived', '1');
    if (f.q) q.set('q', f.q.slice(0, 200));
    if (f.status) q.set('status', f.status);
    if (f.kind) q.set('kind', f.kind);
    if (f.type) q.set('type', f.type);
    if (f.client) q.set('client', f.client.slice(0, 200));
    const qs = q.toString();
    return this.req<HistoryDoc>('GET', `/api/history${qs ? `?${qs}` : ''}`);
  }
  /** changes whenever a project / batch registry changes (another process registered a project) */
  historyStamp() {
    return this.req<{ stamp: string }>('GET', '/api/history/stamp');
  }
  historyConfig() {
    return this.req<HistoryConfig>('GET', '/api/history/config');
  }
  setHistoryWatch(watch: string[]) {
    return this.req<HistoryConfig>('POST', '/api/history/config', { watch });
  }
  openHistory(dir: string) {
    return this.req<{ id: string; dir: string; name: string }>('POST', '/api/history/open', { dir });
  }
  /** archive projects (never deletes files; refused while one of them is running) */
  archiveHistory(dirs: string[]) {
    return this.req<{ ok: boolean; archived: string[]; at: number; deleted: false }>('POST', '/api/history/archive', { dirs });
  }
  /** archived projects back into All projects, as they were */
  restoreHistory(dirs: string[]) {
    return this.req<{ ok: boolean; restored: string[] }>('POST', '/api/history/restore', { dirs });
  }
  /** @deprecated the old 「remove from list」: archiveHistory */
  hideHistory(dir: string) {
    return this.req<{ ok: boolean; deleted: false }>('POST', '/api/history/hide', { dir });
  }
  historyItem(id: string) {
    return this.req<HistoryDetail>('GET', `/api/history/item/${bid(id)}`);
  }
  adoptHistory(id: string, body: { recipe?: string; title?: string } = {}) {
    return this.req<{ ok: boolean; dir: string; type: string; recipe: string | null }>('POST', `/api/history/item/${bid(id)}/adopt`, body);
  }
  /** @deprecated restoreHistory */
  unhideOne(dir: string) {
    return this.req<{ ok: boolean }>('POST', '/api/history/unhide-one', { dir });
  }
  renameHistory(dir: string, name: string) {
    return this.req<{ ok: boolean; name: string }>('POST', '/api/history/rename', { dir, name: name.slice(0, 80) });
  }
  /** agency mode: the client a project is for ('' = her own) */
  setHistoryClient(dir: string, client: string) {
    return this.req<{ ok: boolean; client: string | null }>('POST', '/api/history/client', { dir, client: client.slice(0, 80) });
  }
  unhideHistory() {
    return this.req<HistoryConfig>('POST', '/api/history/unhide', {});
  }
  /** the built-in sample recording ("Try with a sample"), copied where the engine can work on it */
  sample() {
    return this.req<SampleInfo>('GET', '/api/sample');
  }
  /** delete a project made from the sample (refused for anything else) */
  removeSample(dir: string) {
    return this.req<{ ok: boolean; removed: string }>('POST', '/api/sample/remove', { dir });
  }
  cleanupDue() {
    return this.req<{ batch: string; paths: string[]; outside?: string[]; due?: number }[]>('GET', '/api/cleanup/due');
  }
  cleanupDone(batch: string, paths: string[]) {
    return this.req<{ ok: boolean }>('POST', '/api/cleanup/done', { batch: bid(batch), paths });
  }

  // ---------------------------------------------------------------- v0.4: outputs, intake, inbox, calendar
  clips(item: string) {
    return this.req<ClipsDoc>('GET', `/api/outputs/${bid(item)}`);
  }
  output(item: string, clip: string) {
    return this.req<OutputDoc>('GET', `/api/outputs/${bid(item)}/${clipId(clip)}`);
  }
  /** the timeline's filmstrip sprite + audio peaks (made once per file, cached by the engine) */
  outputStrip(item: string, clip: string, signal?: AbortSignal) {
    return this.req<StripInfo>('GET', `/api/outputs/${bid(item)}/${clipId(clip)}/strip`, undefined, signal);
  }
  /** 「听一遍这条片子」: transcribe the output in the background; output-transcribe events follow */
  transcribeOutput(item: string, clip: string) {
    return this.req<TranscribeState>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/transcribe`, {});
  }
  transcribeState(item: string, clip: string) {
    return this.req<TranscribeState>('GET', `/api/outputs/${bid(item)}/${clipId(clip)}/transcribe`);
  }
  /** turn: the chat card these ops come from (marked applied in the clip's transcript) */
  editOutput(item: string, clip: string, ops: EditOp[], turn?: string | null, meta?: { by?: 'user' | 'you' | 'ai'; note?: string }) {
    return this.req<{ ok: boolean; step?: { id: string; describe: EngineMsg[]; retimed?: Retimed | null }; warnings?: EngineMsg[] }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/edit`, {
      ops,
      ...(turn ? { turn } : {}),
      ...(meta ?? {}),
    });
  }
  /** the kept ranges if these pending transcript cuts were applied (live skip preview; nothing is written) */
  previewEdl(item: string, clip: string, ops: EditOp[], signal?: AbortSignal) {
    return this.req<PreviewEdl>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/preview-edl`, { ops }, signal);
  }
  /** context: what she points at (timeline selection, caption cues, the open effect) */
  askOutput(item: string, clip: string, prompt: string, context?: AskContext | null) {
    return this.req<AskResult & { turn?: string | null; context?: AskContext | null; cost_usd?: number | null; seconds?: number | null }>(
      'POST',
      `/api/outputs/${bid(item)}/${clipId(clip)}/ask`,
      context ? { prompt: prompt.slice(0, 500), context } : { prompt: prompt.slice(0, 500) },
    );
  }
  /** project-level 让 AI 改: one request for every clip (or `clips`) of the project -> a background job */
  projectAsk(item: string, prompt: string, clips?: string[] | null, context?: Record<string, unknown> | null) {
    const body: Record<string, unknown> = { prompt: prompt.slice(0, 500) };
    if (clips?.length) body.clips = clips.map(clipId).map(decodeURIComponent);
    if (context) body.context = context;
    return this.req<{ ok: boolean; job: string; clips: string[]; timeout: number }>('POST', `/api/outputs/${bid(item)}/project-ask`, body);
  }
  projectAskJob(job: string) {
    if (!/^[0-9a-f]{10}$/.test(job)) throw new EngineError(400, `bad job ${job}`);
    return this.req<ProjectAskJob>('GET', `/api/project-ask/${job}`);
  }
  /** Cancel: the engine process (and the model CLI it started) is killed */
  stopProjectAsk(job: string) {
    if (!/^[0-9a-f]{10}$/.test(job)) throw new EngineError(400, `bad job ${job}`);
    return this.req<{ ok: boolean; killed: boolean }>('POST', `/api/project-ask/${job}/stop`, {});
  }
  /** needs_rerender action: re-run these recipe items */
  regenerate(item: string, items: string[]) {
    return this.req<{ ok: boolean; started: boolean; simulated?: boolean }>('POST', `/api/outputs/${bid(item)}/regenerate`, { items });
  }
  /** cancel ONE earlier step; the later ones stay (refused with revert-conflict when a later step builds on it) */
  revertOutput(item: string, clip: string, step: string) {
    return this.req<{ ok: boolean; reverted: string }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/revert`, { step });
  }
  addChatTurn(item: string, clip: string, turn: Partial<ChatTurn>) {
    return this.req<{ ok: boolean; turn: ChatTurn }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/chat`, { add: turn });
  }
  updateChatTurn(item: string, clip: string, turn: string, patch: Partial<ChatTurn>) {
    return this.req<{ ok: boolean; turn: ChatTurn }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/chat`, { turn, set: patch });
  }
  /** final renders in the background; progress arrives as output-render events */
  exportOutput(item: string, clip: string, targets: string[], watermark?: boolean) {
    return this.req<ExportJob>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/export`, watermark === undefined ? { targets } : { targets, watermark });
  }
  /** Settings › Watermark: the engine's watermark settings + previews over sample 9:16 / 16:9 frames */
  watermark(previews = true) {
    return this.req<WatermarkDoc>('GET', previews ? '/api/watermark' : '/api/watermark?previews=0');
  }
  setWatermark(patch: Partial<WatermarkSettings>) {
    return this.req<WatermarkDoc>('POST', '/api/watermark', { patch });
  }
  /** a PNG / JPG logo she picked or dropped (copied into the engine's watermark folder) */
  watermarkLogo(path: string) {
    return this.req<WatermarkDoc>('POST', '/api/watermark/logo', { path });
  }
  stopExport(item: string, clip: string, job: string) {
    return this.req<{ ok: boolean }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/export-stop`, { job });
  }
  renderOutput(item: string, clip: string, opts: { quality?: 'preview' | 'final'; targets?: string; with_ops?: EditOp[] } = {}) {
    return this.req<{ ok: boolean; targets: { target: string; file: string; cover?: string; cached?: boolean; duration?: number }[]; simulated?: boolean; compare?: boolean }>(
      'POST',
      `/api/outputs/${bid(item)}/${clipId(clip)}/render`,
      opts,
    );
  }
  undoOutput(item: string, clip: string, steps = 1) {
    return this.req<{ ok: boolean }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/undo`, { steps });
  }
  redoOutput(item: string, clip: string, steps = 1) {
    return this.req<{ ok: boolean }>('POST', `/api/outputs/${bid(item)}/${clipId(clip)}/redo`, { steps });
  }
  effects() {
    return this.req<{ effects: EffectDef[]; engine: string }>('GET', '/api/effects');
  }
  /** platforms: the composer's platform chip (used when the request itself names none); lang: the UI language the
   * plan card's questions and risks are written in */
  startIntake(prompt: string, inputs: string[], platforms?: string[], lang?: string, opts: { mode?: 'autopilot' | 'ask'; sampleName?: string } = {}) {
    return this.req<{ id: string }>('POST', '/api/intake', {
      prompt: prompt.slice(0, 2000),
      inputs,
      ...(platforms?.length ? { platforms } : {}),
      ...(lang ? { lang } : {}),
      ...(opts.mode ? { mode: opts.mode } : {}),
      ...(opts.sampleName ? { sample_name: opts.sampleName.slice(0, 80) } : {}),
    });
  }
  /** requests from Home that are not projects yet (All projects lists them first) */
  openRequests() {
    return this.req<{ items: OpenRequest[] }>('GET', '/api/intake/open');
  }
  /** drop a request that is not a project yet (nothing was made) */
  discardIntake(id: string) {
    return this.req<{ ok: boolean }>('POST', `/api/intake/${pid(id)}/discard`, {});
  }
  /** what a request waited for (``needs``): the files she dropped and / or the links she pasted; planned again */
  addToIntake(id: string, inputs: string[], text?: string) {
    return this.req<{ id: string }>('POST', `/api/intake/${pid(id)}/add`, { inputs, ...(text ? { text: text.slice(0, 2000) } : {}) });
  }
  /** plan a waiting request without what it asked for (her Notion pages ...) */
  goOnIntake(id: string) {
    return this.req<{ id: string }>('POST', `/api/intake/${pid(id)}/go-on`, {});
  }
  /** what the autopilot decided for a project, and whether it is on */
  autopilot(item: string) {
    return this.req<AutopilotDoc>('GET', `/api/autopilot/${bid(item)}`);
  }
  /** take one decision back: the project runs on to it and the Inbox asks her */
  autopilotReopen(item: string, checkpoint: string, sub: string) {
    return this.req<{ ok: boolean; resumed?: boolean }>('POST', `/api/autopilot/${bid(item)}/reopen`, { checkpoint, item: sub });
  }
  /** she changes one taste call the engine made, in place (Undo / Change in the clip editor): the clip is re-made */
  autopilotChange(item: string, checkpoint: string, sub: string, answer: { approve: string[]; keep: string[] }) {
    return this.req<{ ok: boolean; resumed?: boolean }>('POST', `/api/autopilot/${bid(item)}/change`, { checkpoint, item: sub, answer });
  }
  /** autopilot (true) or ask me first (false) for one project */
  autopilotMode(item: string, on: boolean) {
    return this.req<{ ok: boolean; resumed?: boolean }>('POST', `/api/autopilot/${bid(item)}/mode`, { on });
  }
  intake(id: string) {
    return this.req<IntakeJob>('GET', `/api/intake/${pid(id)}`);
  }
  /** a failed plan card's 「Try again」: the same request (or the revision that failed) again */
  retryIntake(id: string) {
    return this.req<{ id: string }>('POST', `/api/intake/${pid(id)}/retry`, {});
  }
  reviseIntake(id: string, prompt: string, lang?: string) {
    return this.req<{ id: string }>('POST', `/api/intake/${pid(id)}/revise`, { prompt: prompt.slice(0, 500), ...(lang ? { lang } : {}) });
  }
  applyIntake(id: string, body: { plan?: IntakePlan; run?: boolean } = {}) {
    return this.req<{ ok: boolean; projects: { dir: string; name: string; recipe: string }[] }>('POST', `/api/intake/${pid(id)}/apply`, body);
  }
  recentPrompts() {
    return this.req<{ id: string; prompt: string; at: string }[]>('GET', '/api/intake/recent');
  }
  stopIntake(id: string) {
    return this.req<{ ok: boolean }>('POST', `/api/intake/${pid(id)}/stop`, {});
  }
  /** re-run a failed pilot; provider pins every model task (「换 Codex 重试」) */
  retryPilot(item: string, provider?: string | null) {
    return this.req<{ ok: boolean }>('POST', '/api/pilot/retry', provider ? { item, provider } : { item });
  }
  inbox() {
    return this.req<InboxDoc>('GET', '/api/inbox');
  }
  answerInbox(keys: string[], answer?: Record<string, unknown>) {
    return this.req<{ ok: boolean; answered: string[] }>('POST', '/api/inbox/answer', answer ? { keys, answer } : { keys });
  }
  undoInbox(keys: string[]) {
    return this.req<{ ok: boolean }>('POST', '/api/inbox/undo', { keys });
  }
  /** an author item's file (or its template / guide) in the default editor */
  openInboxFile(key: string, which: 'file' | 'template' | 'doc' = 'file') {
    return this.req<{ ok: boolean; path: string }>('POST', '/api/inbox/open', { key, which });
  }
  /** an author item drafted again by the engine (in the background): "Draft it for me" / "ask in plain words" */
  redraftInbox(key: string, instruction?: string) {
    return this.req<{ ok: boolean; drafting: boolean }>('POST', '/api/inbox/redraft', { key, ...(instruction ? { instruction: instruction.slice(0, 1000) } : {}) });
  }
  /** share for review: what the dialog offers (clips, versions, privacy warnings) */
  shareOptions(item: string) {
    return this.req<ShareOptions>('GET', `/api/share/${bid(item)}`);
  }
  share(item: string, body: ShareRequest) {
    return this.req<{ ok: boolean; job: string; total: number }>('POST', `/api/share/${bid(item)}`, body);
  }
  shareJob(job: string) {
    if (!/^[0-9a-f]{12}$/.test(job)) throw new EngineError(400, `bad share job ${job}`);
    return this.req<ShareJob>('GET', `/api/share-jobs/${job}`);
  }
  /** a reviewer's code / .reelfold.json text -> Inbox items */
  importFeedback(text: string) {
    return this.req<{ ok: boolean; share: string; title: string | null; reviewer: string; project: string | null; items: number; duplicates: number; unknown: string[] }>('POST', '/api/feedback/import', { text });
  }
  calendar(start?: string, opts: { queue?: boolean } = {}) {
    const q = [start ? `start=${encodeURIComponent(start)}` : '', opts.queue === false ? 'queue=0' : ''].filter(Boolean).join('&');
    return this.req<CalendarDoc>('GET', `/api/calendar${q ? `?${q}` : ''}`);
  }
  schedule(body: { item: string; clip: string; platform?: string; at: string }) {
    return this.req<CalendarPost>('POST', '/api/calendar', { ...body, item: bid(body.item) });
  }
  updatePost(
    id: string,
    body: {
      at?: string;
      state?: CalendarPost['state'];
      remove?: boolean;
      caption?: string | null;
      platform?: string;
      enabled?: boolean;
      stats?: { views?: number; likes?: number };
      title?: string | null;
      platform_title?: string | null;
      url?: string | null;
      via?: 'assisted' | 'api' | 'manual';
    },
  ) {
    return this.req<{ ok: boolean; post: CalendarPost; before: CalendarPost }>('POST', `/api/calendar/${bid(id)}`, body);
  }
  /** several rows at once (all or none): one undo step */
  scheduleMany(posts: NewPost[]) {
    return this.req<{ ok: boolean; posts: CalendarPost[]; ids: string[] }>('POST', '/api/calendar/many', { posts: posts.map((p) => ({ ...p, item: bid(p.item) })) });
  }
  /** back to the queue (calendar rows only, never files) -> the removed rows, for restorePosts (undo) */
  unscheduleMany(ids: string[]) {
    return this.req<{ ok: boolean; removed: CalendarPost[] }>('POST', '/api/calendar/remove', { ids: ids.map(bid) });
  }
  restorePosts(posts: CalendarPost[]) {
    return this.req<{ ok: boolean; ids: string[] }>('POST', '/api/calendar/restore', { posts });
  }
  fillWeek(body: { start: string; platforms: string[]; times: Record<string, string>; clips?: { item: string; clip: string }[]; today?: string }) {
    return this.req<{ ok: boolean; posts: CalendarPost[]; ids: string[]; reason?: 'no_clips' | 'no_free_days' }>('POST', '/api/calendar/fill-week', body);
  }
  /** 「为 X 缩短」: a caption that fits the platform (the post-copy AI, else rules); nothing is saved */
  shortenCaption(body: { text: string; platform: string; max?: number }) {
    return this.req<{ text: string; provider: string; length: number; limit: number }>('POST', '/api/calendar/shorten', body);
  }
  /** preview only: nothing is written */
  planSchedule(body: { text: string; start: string; platforms: string[]; times: Record<string, string>; clips?: { item: string; clip: string }[]; today?: string }) {
    return this.req<SchedulePlan>('POST', '/api/calendar/plan', body);
  }
  // 「一周的帖子」 (weekplan.py)
  startWeekPlan(body: WeekPlanStart) {
    return this.req<WeekPlan>('POST', '/api/weekplan', { ...body, text: (body.text ?? '').slice(0, 300) });
  }
  weekPlans() {
    return this.req<{ plans: WeekPlan[] }>('GET', '/api/weekplan');
  }
  weekPlan(id: string) {
    return this.req<WeekPlan>('GET', `/api/weekplan/${bid(id)}`);
  }
  weekPlanAct(id: string, verb: 'run' | 'confirm' | 'dismiss') {
    return this.req<WeekPlan & { ids?: string[] }>('POST', `/api/weekplan/${bid(id)}/${verb}`, {});
  }
  rewordWeekPlan(id: string, text: string, today?: string) {
    return this.req<WeekPlan & { ok: boolean; reason?: string }>('POST', `/api/weekplan/${bid(id)}/reword`, { text: text.slice(0, 300), ...(today ? { today } : {}) });
  }
  confirmWeek(start: string) {
    return this.req<{ ok: boolean; ready: number }>('POST', '/api/calendar/confirm', { start });
  }

  /** Server-sent events over fetch (EventSource cannot send the Authorization header). Resolves when the
   * stream ends; reconnecting is the caller's job. */
  async stream(onEvent: (e: StreamEvent) => void, signal: AbortSignal): Promise<void> {
    const r = await this.fetchImpl(this.baseUrl + '/api/stream', {
      headers: { Authorization: `Bearer ${this.token}` },
      signal,
    });
    if (!r.ok || !r.body) throw new EngineError(r.status, 'stream failed');
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      buf += dec.decode(value, { stream: true });
      const { events, rest } = parseSSE(buf);
      buf = rest;
      for (const ev of events) onEvent(ev as StreamEvent);
    }
  }
}

/** Split an SSE buffer into complete events (JSON data) and the unfinished rest. Comments are ignored. */
export function parseSSE(buf: string): { events: unknown[]; rest: string } {
  const events: unknown[] = [];
  const blocks = buf.replace(/\r\n/g, '\n').split('\n\n');
  const rest = blocks.pop() ?? '';
  for (const block of blocks) {
    const data = block
      .split('\n')
      .filter((l) => l.startsWith('data:'))
      .map((l) => l.slice(5).trimStart())
      .join('\n');
    if (!data) continue;
    try {
      events.push(JSON.parse(data));
    } catch {
      /* skip malformed event */
    }
  }
  return { events, rest };
}
