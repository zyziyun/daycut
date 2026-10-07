// Thin hooks over EngineClient.create (useLoad / useEngine patterns): load, run background jobs, readable errors.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CreateClient, CreateJob, Msg } from '../../../shared/create';
import { EngineError } from '../../../shared/engineClient';
import { has, t, tk } from '../i18n';
import { useEngine, useLoad } from '../lib/engine';

export function useCreate(): CreateClient | null {
  const { client } = useEngine();
  return useMemo(() => client?.create ?? null, [client]);
}

export function useCreateLoad<T>(fn: (c: CreateClient) => Promise<T>, deps: unknown[]) {
  return useLoad((c) => fn(c.create), deps);
}

/** An engine refusal or failure in the UI language. */
export function errText(e: unknown): string {
  if (e instanceof EngineError && e.code && has(e.code)) return tk(e.code, (e.params ?? {}) as Record<string, string | number>);
  if (e && typeof e === 'object' && 'code' in e && typeof (e as Msg).code === 'string') return msgText(e as Msg);
  const m = e instanceof Error ? e.message : String(e);
  if (/engine-missing|vstudio not importable/.test(m)) return t('create.err.engine');
  return t('create.err.generic', { error: m.slice(0, 200) });
}

export function msgText(m: Msg | null | undefined): string {
  if (!m) return '';
  const params: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(m.params ?? {})) params[k] = Array.isArray(v) ? v.join(', ') : typeof v === 'number' ? v : String(v ?? '');
  return has(m.code) ? tk(m.code, params) : m.code;
}

export class JobError extends Error {
  constructor(public msg: Msg) {
    super(msg.code);
  }
}

/** Poll a background job until it finishes -> its result (JobError on failure). ``limitMs``: give up waiting
 *  (JobError create.job-timeout) - the engine and the sidecar stop it on their side too; nothing spins forever. */
export async function waitJob<T>(c: CreateClient, id: string, onTick?: (j: CreateJob<T>) => void, every = 400, limitMs?: number): Promise<T> {
  const t0 = Date.now();
  for (;;) {
    const j = await c.job<T>(id);
    onTick?.(j);
    if (j.state === 'done') return j.result as T;
    if (j.state === 'error') throw new JobError(j.error ?? { code: 'create.failed', params: {} });
    if (limitMs && Date.now() - t0 > limitMs) throw new JobError({ code: 'create.job-timeout', params: { seconds: Math.round(limitMs / 1000) } });
    await new Promise((r) => setTimeout(r, every));
  }
}

/** The latest ``create.step`` event of a job (plan progress), or null. */
export function lastStep(j: CreateJob<unknown>): Record<string, unknown> | null {
  for (let i = j.events.length - 1; i >= 0; i--) if (j.events[i]?.event === 'create.step') return j.events[i] as Record<string, unknown>;
  return null;
}

/** Run one action at a time with busy / error state: run(() => c.something()). */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  useEffect(
    () => () => {
      alive.current = false;
    },
    [],
  );
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      if (alive.current) setError(e instanceof JobError ? msgText(e.msg) : errText(e));
      return undefined;
    } finally {
      if (alive.current) setBusy(false);
    }
  }, []);
  return { busy, error, setError, run };
}

/** Re-run ``fn`` on every Create stream event (job progress) and every ``ms`` while ``active``. */
export function useCreateRefresh(fn: () => void, active: boolean, ms = 1500) {
  const { subscribe } = useEngine();
  const f = useRef(fn);
  f.current = fn;
  useEffect(() => {
    const off = subscribe((e) => {
      if ((e as { type?: string }).type === 'create') f.current();
    });
    return off;
  }, [subscribe]);
  useEffect(() => {
    if (!active) return;
    const tm = window.setInterval(() => f.current(), ms);
    return () => window.clearInterval(tm);
  }, [active, ms]);
}
