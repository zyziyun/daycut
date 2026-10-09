// Live history for the whole app (全部项目 view, the 进行中 lane, the sidebar badge). Refreshes on engine events and
// on file changes in the watched folders (main-process fs.watch -> 'history:changed'); a slow timer runs only
// while something is live, so a dead external run flips to 中断 / interrupted. No polling otherwise.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { HistoryDoc, HistoryItem } from '../../../shared/v02';
import type { OpenRequest } from '../../../shared/v04';
import { useEngine, useLoad } from './engine';

interface Ctx {
  data: HistoryDoc | null;
  error: string | null;
  reload(): void;
  live: HistoryItem[];
  /** the archived projects (GET /api/history?archived=1), loaded once something asks for them (wantArchived) */
  archived: HistoryDoc | null;
  wantArchived(): void;
  /** requests from Home that are not projects yet (planning, a plan waiting for her Start, a failure) */
  requests: OpenRequest[];
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

/** How often the registry stamp is checked while the app is visible (another process registered a project). */
export const STAMP_POLL_MS = 10_000;

/** Reload when the registry stamp moved; the first stamp seen only arms it. -> the stamp to remember. */
export function stampChanged(prev: string | null, next: string | null | undefined): { reload: boolean; stamp: string | null } {
  if (!next) return { reload: false, stamp: prev };
  return { reload: prev !== null && prev !== next, stamp: next };
}

export function HistoryProvider({ children }: { children: ReactNode }) {
  const { subscribe, client } = useEngine();
  const { data, error, reload: reloadMain } = useLoad((c) => c.history(), []);
  // the archived list is read only once the Archived tab / an archived project page asks for it, then kept fresh with
  // the main list
  const [want, setWant] = useState(false);
  const wantRef = useRef(false);
  const arch = useLoad((c) => (want ? c.history({ archived: true }) : Promise.resolve(null)), [want]);
  const reloadArch = arch.reload;
  const reqs = useLoad((c) => c.openRequests().catch(() => ({ items: [] as OpenRequest[] })), []);
  const reloadReqs = reqs.reload;
  const reload = useCallback(() => {
    reloadMain();
    reloadReqs();
    if (wantRef.current) reloadArch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const wantArchived = useCallback(() => {
    wantRef.current = true;
    setWant(true);
  }, []);
  // a project registered / re-registered by another process (an agent's `vstudio.project register` / `touch`) shows
  // up without navigating away and back: a cheap registry stamp is polled while the window is visible, and the list
  // reloads when the window comes back to the front
  const stampRef = useRef<string | null>(null);
  useEffect(() => {
    if (!client) return;
    let alive = true;
    const check = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
      client
        .historyStamp?.()
        .then((r) => {
          const d = stampChanged(stampRef.current, r?.stamp);
          stampRef.current = d.stamp;
          if (alive && d.reload) reload();
        })
        .catch(() => undefined); // an older engine without /api/history/stamp: events still refresh
    };
    check();
    const tm = window.setInterval(check, STAMP_POLL_MS);
    const onShow = () => {
      if (document.visibilityState !== 'hidden') reload();
    };
    window.addEventListener('focus', onShow);
    document.addEventListener('visibilitychange', onShow);
    return () => {
      alive = false;
      window.clearInterval(tm);
      window.removeEventListener('focus', onShow);
      document.removeEventListener('visibilitychange', onShow);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client]);

  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'batches' || e.type === 'run-exit' || e.type === 'run-start') reload();
        else if (e.type === 'intake') reloadReqs(); // a request planning: its progress / state
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
    // only absolute folders can be watched; a registry entry with a relative dir is skipped, not sent (main rejects it)
    return [...r].filter((d) => typeof d === 'string' && (d.startsWith('/') || /^[A-Za-z]:[\\/]/.test(d))).slice(0, 20);
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

  const requests = useMemo(() => reqs.data?.items ?? [], [reqs.data]);
  return <HistoryCtx.Provider value={{ data, error, reload, live, archived: arch.data, wantArchived, requests }}>{children}</HistoryCtx.Provider>;
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
