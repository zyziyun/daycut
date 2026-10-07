// Live history for the whole app (全部项目 view, the 进行中 lane, the sidebar badge). Refreshes on engine events and
// on file changes in the watched folders (main-process fs.watch -> 'history:changed'); a slow timer runs only
// while something is live, so a dead external run flips to 中断 / interrupted. No polling otherwise.
import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react';
import type { HistoryDoc, HistoryItem } from '../../../shared/v02';
import { useEngine, useLoad } from './engine';

interface Ctx {
  data: HistoryDoc | null;
  error: string | null;
  reload(): void;
  live: HistoryItem[];
}

const HistoryCtx = createContext<Ctx | null>(null);

/** Live lane: running / waiting first, then runs interrupted in the last 24 h. */
export function liveItems(items: HistoryItem[], now = Date.now() / 1000): HistoryItem[] {
  const rank = (i: HistoryItem) => (i.live?.needs_you ? 0 : i.live?.state === 'running' ? 1 : i.live?.state === 'waiting' ? 2 : 3);
  return items
    .filter((i) => {
      const s = i.live?.state;
      if (s === 'running' || s === 'waiting') return true;
      return s === 'interrupted' && now - (i.live?.heartbeat ?? 0) < 86400;
    })
    .sort((a, b) => rank(a) - rank(b) || (b.live?.heartbeat ?? 0) - (a.live?.heartbeat ?? 0));
}

export function HistoryProvider({ children }: { children: ReactNode }) {
  const { subscribe } = useEngine();
  const { data, error, reload } = useLoad((c) => c.history(), []);

  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'batches' || e.type === 'run-exit' || e.type === 'run-start') reload();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe],
  );
  useEffect(() => {
    try {
      return window.desk.on('history:changed', () => reload());
    } catch {
      return undefined; // an older preload (dev reload before restart): engine events still refresh
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const live = useMemo(() => liveItems(data?.items ?? []), [data]);
  const roots = useMemo(() => {
    const r = new Set(data?.watch ?? []);
    for (const i of live) r.add(i.dir); // live jobs outside the watched folders (engine registry) too
    return [...r].slice(0, 20);
  }, [data, live]);
  const key = roots.join('\n');
  useEffect(() => {
    if (!data) return;
    window.desk.watchHistory?.(roots).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, !!data]);
  const anyLive = live.some((i) => i.live?.state === 'running' || i.live?.state === 'waiting');
  useEffect(() => {
    if (!anyLive) return;
    const tm = setInterval(reload, 60_000);
    return () => clearInterval(tm);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyLive]);

  return <HistoryCtx.Provider value={{ data, error, reload, live }}>{children}</HistoryCtx.Provider>;
}

export function useHistory(): Ctx {
  const c = useContext(HistoryCtx);
  if (!c) throw new Error('HistoryProvider missing');
  return c;
}

export function fmtDuration(s: number | null | undefined): string {
  if (s == null || !isFinite(s) || s < 0) return '—';
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  return h ? `${h}h${String(m % 60).padStart(2, '0')}m` : m ? `${m}m${String(Math.floor(s % 60)).padStart(2, '0')}s` : `${Math.floor(s)}s`;
}
