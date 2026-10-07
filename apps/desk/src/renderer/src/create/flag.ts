// The Create page flag (Settings.createPage; DESK_CREATE=1/0 overrides it in main for tests). Off: no nav item, every
// #/create… hash lands on Home, no /api/create call is ever made, and the recorder permissions stay denied.
import { useSyncExternalStore } from 'react';

let on = false;
let local = false;
const subs = new Set<() => void>();

export function setCreatePrefs(p: { createPage?: boolean; createLocalGen?: boolean }) {
  const next = !!p.createPage;
  const nextLocal = next && !!p.createLocalGen;
  if (next === on && nextLocal === local) return;
  on = next;
  local = nextLocal;
  for (const f of subs) f();
}

export function createEnabled(): boolean {
  return on;
}

export function localGenEnabled(): boolean {
  return local;
}

export function useCreateEnabled(): boolean {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => on,
  );
}
