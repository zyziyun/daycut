// A D1Database on top of node:sqlite (in memory), with the repo's migrations applied: the Worker's real SQL runs
// in the tests.
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import type { D1Database, D1PreparedStatement, D1Result } from '../src/d1';

const MIGRATIONS = path.resolve(import.meta.dirname, '../migrations');

class Stmt implements D1PreparedStatement {
  constructor(
    private db: DatabaseSync,
    private sql: string,
    private args: unknown[] = [],
  ) {}
  bind(...values: unknown[]): D1PreparedStatement {
    return new Stmt(this.db, this.sql, values);
  }
  private params() {
    return this.args.map((v) => (v === undefined ? null : v)) as (string | number | null)[];
  }
  async first<T>(): Promise<T | null> {
    return (this.db.prepare(this.sql).get(...this.params()) as T | undefined) ?? null;
  }
  async all<T>(): Promise<D1Result<T>> {
    return { results: this.db.prepare(this.sql).all(...this.params()) as T[], success: true, meta: {} };
  }
  async run(): Promise<D1Result> {
    const r = this.db.prepare(this.sql).run(...this.params());
    return { results: [], success: true, meta: { changes: Number(r.changes) } };
  }
  runSync(): D1Result {
    const r = this.db.prepare(this.sql).run(...this.params());
    return { results: [], success: true, meta: { changes: Number(r.changes) } };
  }
}

export function fakeD1(): D1Database & { raw: DatabaseSync } {
  const db = new DatabaseSync(':memory:');
  for (const f of fs.readdirSync(MIGRATIONS).filter((x) => x.endsWith('.sql')).sort()) db.exec(fs.readFileSync(path.join(MIGRATIONS, f), 'utf8'));
  return {
    raw: db,
    prepare: (sql: string) => new Stmt(db, sql),
    // D1 runs a batch as one transaction
    async batch(statements: D1PreparedStatement[]) {
      db.exec('BEGIN');
      try {
        const out = statements.map((s) => (s as Stmt).runSync());
        db.exec('COMMIT');
        return out;
      } catch (e) {
        db.exec('ROLLBACK');
        throw e;
      }
    },
  };
}
