// App-wide preferences the screens read without prop drilling (set by App whenever settings load or change).
// agencyMode = Settings -> 「我在帮别人做视频」: only then do clients appear anywhere in the UI.
import { useSyncExternalStore } from 'react';

let agency = false;
const subs = new Set<() => void>();

export function setPrefs(p: { agencyMode?: boolean }) {
  const next = !!p.agencyMode;
  if (next === agency) return;
  agency = next;
  for (const f of subs) f();
}

export function agencyMode(): boolean {
  return agency;
}

export function useAgencyMode(): boolean {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    () => agency,
  );
}
