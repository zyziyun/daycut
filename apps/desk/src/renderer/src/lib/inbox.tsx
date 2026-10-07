// The inbox (需要你) for the whole app: sidebar count, Home's short list, the Inbox screen. Refreshes on engine events
// (inbox, batches, run exits) and on file changes in the watched folders.
import { createContext, useContext, useEffect, type ReactNode } from 'react';
import type { InboxItem } from '../../../shared/v04';
import { useEngine, useLoad } from './engine';
import { useHistory } from './history';

interface Ctx {
  items: InboxItem[];
  loading: boolean;
  error: string | null;
  reload(): void;
}

const InboxCtx = createContext<Ctx | null>(null);

export function InboxProvider({ children }: { children: ReactNode }) {
  const { subscribe } = useEngine();
  const { data: hist } = useHistory();
  const { data, error, loading, reload } = useLoad((c) => c.inbox(), []);
  useEffect(
    () =>
      subscribe((e) => {
        if (e.type === 'inbox' || e.type === 'batches' || e.type === 'run-exit' || e.type === 'job-edit') reload();
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [subscribe],
  );
  useEffect(() => {
    if (hist) reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hist?.at]);
  return <InboxCtx.Provider value={{ items: data?.items ?? [], loading: loading && !data, error, reload }}>{children}</InboxCtx.Provider>;
}

export function useInbox(): Ctx {
  const c = useContext(InboxCtx);
  if (!c) throw new Error('InboxProvider missing');
  return c;
}
