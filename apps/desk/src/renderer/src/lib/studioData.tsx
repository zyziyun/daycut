// The Studio's rows for the whole app: the list itself and (step 8) the Dock badge, the notifications that open the
// exact video and ⌘K all read the same rows. Loaded only with the Studio on.
import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { CalendarPost, Clip } from '../../../shared/v04';
import { useEngine, useLoad } from './engine';
import { useHistory } from './history';
import { useInbox } from './inbox';
import { href } from './router';
import { studioRows, type StudioRow } from './studio';
import { useStudioEnabled } from './studioFlag';

interface Ctx {
  rows: StudioRow[];
  posts: CalendarPost[];
  /** history loaded (an empty list means no videos, not "not loaded yet") */
  ready: boolean;
}

const StudioCtx = createContext<Ctx>({ rows: [], posts: [], ready: false });

/** Every recent project's clips, loaded once per project version (a run's new clip shows as soon as it exists). */
function useClipsOf(ids: { id: string; v: string }[], on: boolean) {
  const { client, subscribe } = useEngine();
  const [clips, setClips] = useState<Record<string, Clip[] | undefined>>({});
  const seen = useRef<Record<string, string>>({});
  const [n, setN] = useState(0);
  useEffect(() => subscribe((e) => (e.type === 'output-edit' || e.type === 'calendar' ? ((seen.current = {}), setN((x) => x + 1)) : undefined)), [subscribe]);
  const key = ids.map((x) => `${x.id}:${x.v}`).join('|');
  useEffect(() => {
    if (!client || !on) return;
    let alive = true;
    for (const { id, v } of ids) {
      if (seen.current[id] === v) continue;
      seen.current[id] = v;
      client
        .clips(id)
        .then((d) => alive && setClips((c) => ({ ...c, [id]: d.clips })))
        .catch(() => alive && setClips((c) => ({ ...c, [id]: [] })));
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, key, n, on]);
  return clips;
}

const RECENT_S = 14 * 86400;

export function StudioProvider({ children }: { children: ReactNode }) {
  const on = useStudioEnabled();
  const { data: hist, requests = [] } = useHistory();
  const inbox = useInbox();
  const { subscribe } = useEngine();
  const { data: cal, reload: reloadCal } = useLoad((c) => (on ? c.calendar(undefined, { queue: false }).catch(() => c.calendar()) : Promise.resolve(null)), [on]);
  useEffect(() => subscribe((e) => void (e.type === 'calendar' && reloadCal())), [subscribe]); // eslint-disable-line react-hooks/exhaustive-deps
  const posts = useMemo(() => cal?.posts ?? [], [cal]);
  const items = useMemo(() => hist?.items ?? [], [hist]);
  const recent = useMemo(() => {
    const now = Date.now() / 1000;
    return items.filter((i) => now - (i.updated ?? i.created ?? 0) < RECENT_S || i.live?.state === 'running' || i.live?.state === 'waiting');
  }, [items]);
  const clips = useClipsOf(
    recent.map((i) => ({ id: i.id, v: `${i.updated ?? 0}:${i.status}:${i.live?.state ?? ''}` })),
    on,
  );
  const rows = useMemo(() => (on ? studioRows(recent, requests, clips, posts, inbox.items) : []), [on, recent, requests, clips, posts, inbox.items]);
  const value = useMemo(() => ({ rows, posts, ready: !!hist && !inbox.loading }), [rows, posts, hist, inbox.loading]);
  return <StudioCtx.Provider value={value}>{children}</StudioCtx.Provider>;
}

export function useStudioData(): Ctx {
  return useContext(StudioCtx);
}

/** Where a row opens in the Studio (a question about it: pinned there). */
export function rowHref(r: StudioRow, withAsk = false): string {
  const ask = withAsk && r.ask ? `?item=${encodeURIComponent(r.ask.key)}` : '';
  if (r.kind === 'clip') return href({ name: 'studio', id: r.item!, clip: r.clip! }) + ask;
  if (r.kind === 'project') return href({ name: 'studio', id: r.item! }) + ask;
  return `${href({ name: 'studio' })}?sel=${r.r!.id}`;
}
