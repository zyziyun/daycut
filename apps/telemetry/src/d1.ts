// The slice of the Cloudflare D1 API this Worker uses (so it builds without @cloudflare/workers-types; the tests
// provide the same interface on top of node:sqlite).

export interface D1Result<T = Record<string, unknown>> {
  results: T[];
  success: boolean;
  meta: { changes?: number; [k: string]: unknown };
}

export interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  first<T = Record<string, unknown>>(): Promise<T | null>;
  all<T = Record<string, unknown>>(): Promise<D1Result<T>>;
  run(): Promise<D1Result>;
}

export interface D1Database {
  prepare(sql: string): D1PreparedStatement;
  batch(statements: D1PreparedStatement[]): Promise<D1Result[]>;
}

export interface Env {
  DB: D1Database;
  /** the maintainer's secret for GET /api/v1/stats and POST /api/v1/internal (wrangler secret put STATS_TOKEN) */
  STATS_TOKEN?: string;
}
