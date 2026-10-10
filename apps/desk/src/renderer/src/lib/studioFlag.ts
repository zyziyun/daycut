// The Studio flag (Settings.studio; DESK_STUDIO=1/0 overrides it in main for tests): on, every video is one row of the
// Studio list and opens as one page; Home, the Inbox, All projects and a project's clips land there.
import { useSyncExternalStore } from 'react';

let on = false;
const subs = new Set<() => void>();

export function setStudioPrefs(p: { studio?: boolean }) {
  const next = !!p.studio;
  if (next === on) return;
  on = next;
  for (const f of subs) f();
}

export function studioEnabled(): boolean {
  return on;
}

export function useStudioEnabled(): boolean {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => on,
  );
}
