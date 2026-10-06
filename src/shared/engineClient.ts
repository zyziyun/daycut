// HTTP client for the desk engine. Used by the renderer (token from preload) and by the main process.
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
  MetricsDoc,
  PlanBatchBody,
  PlanRequest,
  PlanState,
  WeeklyDoc,
} from './v02';

export class EngineError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'EngineError';
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

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

export class EngineClient {
  constructor(
    private baseUrl: string,
    private token: string,
    private fetchImpl: FetchLike = (...a) => fetch(...a),
  ) {
    const u = new URL(baseUrl);
    if (u.protocol !== 'http:' || u.hostname !== '127.0.0.1') {
      throw new EngineError(0, 'engine must be on http://127.0.0.1');
    }
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
      const msg = (data && typeof data === 'object' && 'error' in data ? String((data as { error: unknown }).error) : '') || r.statusText;
      throw new EngineError(r.status, msg);
    }
    return data as T;
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
  cleanupDue() {
    return this.req<{ batch: string; paths: string[] }[]>('GET', '/api/cleanup/due');
  }
  cleanupDone(batch: string, paths: string[]) {
    return this.req<{ ok: boolean }>('POST', '/api/cleanup/done', { batch: bid(batch), paths });
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
