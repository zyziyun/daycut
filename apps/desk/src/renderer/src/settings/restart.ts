// "Restart to apply" is the only pending state Settings keeps: the engine path / Python changed, or an API key
// (the engine reads keys when it starts). Kept outside the sections so switching sections keeps the bar.
import { useSyncExternalStore } from 'react';

export type RestartWhat = 'engine' | 'python' | 'key' | null;
let what: RestartWhat = null;
const subs = new Set<() => void>();

export function markRestart(w: RestartWhat) {
  what = w;
  subs.forEach((f) => f());
}

export function useRestart(): { what: RestartWhat } {
  const w = useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => what,
  );
  return { what: w };
}
