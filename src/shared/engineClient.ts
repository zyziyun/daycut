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
