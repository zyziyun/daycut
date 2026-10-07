// Engine connection for the renderer: EngineClient (token from the preload bridge) + the SSE stream.
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { EngineClient } from '../../../shared/engineClient';
import type { EngineInfo, StreamEvent } from '../../../shared/types';

interface Ctx {
  client: EngineClient | null;
  info: EngineInfo | null;
  error: string | null;
  connected: boolean;
  subscribe(fn: (e: StreamEvent) => void): () => void;
  reconnect(): void;
}

const EngineCtx = createContext<Ctx | null>(null);

export function EngineProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<EngineInfo | null>(null);
  const [client, setClient] = useState<EngineClient | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const subs = useRef(new Set<(e: StreamEvent) => void>());
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let alive = true;
    window.desk
      .engineInfo()
      .then((i) => {
        if (!alive) return;
        setInfo(i);
        setClient(new EngineClient(i.baseUrl, i.token));
        setError(null);
      })
      .catch((e: Error) => alive && setError(e.message));
    const off = window.desk.on('engine:status', (d) => {
      const s = d as { ok: boolean; error?: string };
      if (!s.ok) setError(s.error ?? 'engine stopped');
      else setNonce((n) => n + 1);
    });
    return () => {
      alive = false;
      off();
    };
  }, [nonce]);

  useEffect(() => {
    if (!client) return;
    const ac = new AbortController();
    let stop = false;
    (async () => {
      while (!stop) {
        try {
          setConnected(true);
          await client.stream((e) => subs.current.forEach((fn) => fn(e)), ac.signal);
        } catch {
          /* reconnect below */
        }
        setConnected(false);
        if (stop) break;
        await new Promise((r) => setTimeout(r, 1500));
      }
    })();
    return () => {
      stop = true;
      ac.abort();
    };
  }, [client]);

  const subscribe = useCallback((fn: (e: StreamEvent) => void) => {
    subs.current.add(fn);
    return () => {
      subs.current.delete(fn);
    };
  }, []);

  return (
    <EngineCtx.Provider value={{ client, info, error, connected, subscribe, reconnect: () => setNonce((n) => n + 1) }}>
      {children}
    </EngineCtx.Provider>
  );
}

export function useEngine(): Ctx {
  const c = useContext(EngineCtx);
  if (!c) throw new Error('EngineProvider missing');
  return c;
}

/** Load data with the engine client; reload() re-fetches. */
export function useLoad<T>(fn: (c: EngineClient) => Promise<T>, deps: unknown[]) {
  const { client } = useEngine();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    setLoading(true);
    fn(client)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, n, ...deps]);
  return { data, setData, error, loading, reload: () => setN((x) => x + 1) };
}
