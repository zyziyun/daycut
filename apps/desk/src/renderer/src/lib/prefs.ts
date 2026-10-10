// App-wide preferences the screens read without prop drilling (set by App whenever settings load or change).
// agencyMode = Settings -> 「我在帮别人做视频」: only then do clients appear anywhere in the UI.
// askAiEdits = Settings -> "Ask before applying AI edits": the editor's AI changes wait for Apply (default off).
import { useSyncExternalStore } from 'react';

let agency = false;
let askAi = false;
const subs = new Set<() => void>();

export function setPrefs(p: { agencyMode?: boolean; askAiEdits?: boolean }) {
  const a = !!p.agencyMode;
  const b = !!p.askAiEdits;
  if (a === agency && b === askAi) return;
  agency = a;
  askAi = b;
  for (const f of subs) f();
}

export function agencyMode(): boolean {
  return agency;
}

export function askAiEdits(): boolean {
  return askAi;
}

function sub(f: () => void) {
  subs.add(f);
  return () => {
    subs.delete(f);
  };
}

export function useAgencyMode(): boolean {
  return useSyncExternalStore(sub, () => agency);
}

export function useAskAiEdits(): boolean {
  return useSyncExternalStore(sub, () => askAi);
}
