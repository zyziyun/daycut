// Shared AI accounts state for the renderer: the routes (which provider each task uses) and the last provider
// status, kept in one small store so the settings page, the 让 AI 改 chip and the composer chip agree.
import { useEffect, useSyncExternalStore } from 'react';
import { effective, type AiRoutes, type AiTask, type AuthRow, type AuthStatusMsg, type ProviderId, type RouteChoice } from '../../../shared/aiRoutes';
import type { AiRoutesMsg } from '../../../shared/deskApi';

interface State {
  routes: AiRoutesMsg | null;
  status: AuthStatusMsg | null;
  checking: boolean;
}

let state: State = { routes: null, status: null, checking: false };
const subs = new Set<() => void>();
function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  subs.forEach((f) => f());
}
const subscribe = (f: () => void) => {
  subs.add(f);
  return () => subs.delete(f);
};

let routesLoading: Promise<void> | null = null;
let listening = false;
function ensureRoutes() {
  if (!listening && window.desk?.on) {
    listening = true;
    window.desk.on('ai:routes', (m) => set({ routes: m as AiRoutesMsg }));
  }
  if (state.routes || routesLoading || !window.desk?.ai) return;
  routesLoading = window.desk.ai
    .routes()
    .then((r) => set({ routes: r }))
    .catch(() => undefined)
    .finally(() => {
      routesLoading = null;
    });
}

/** Ask main for the status (cached there unless refresh). probe=false: no claude round-trip. */
export async function refreshStatus(opts: { refresh?: boolean; probe?: boolean; providers?: string[] } = {}) {
  if (!window.desk?.ai) return;
  set({ checking: true });
  try {
    set({ status: await window.desk.ai.status(opts) });
  } finally {
    set({ checking: false });
  }
}

export async function saveRoutes(r: AiRoutes | null) {
  set({ routes: await window.desk.ai.setRoutes(r) });
}

/** Switch one task (or the default) to a provider; null = follow the default again. Explicit, persisted. */
export async function switchProvider(task: AiTask | 'default', provider: ProviderId | 'none' | null) {
  const cur = state.routes?.routes;
  if (!cur) return;
  const next: AiRoutes = { default: { ...cur.default }, tasks: { ...cur.tasks } };
  if (task === 'default') {
    if (!provider) return;
    next.default = { ...next.default, provider, model: provider === cur.default.provider ? cur.default.model : null, fallback: cur.default.fallback.filter((x) => x !== provider) };
  } else if (!provider) {
    delete next.tasks[task];
  } else {
    const base: RouteChoice = effective(cur, task);
    next.tasks[task] = { provider, model: provider === base.provider ? base.model : null, fallback: base.fallback.filter((x) => x !== provider) };
  }
  await saveRoutes(next);
}

export function useAi() {
  const s = useSyncExternalStore(subscribe, () => state);
  useEffect(() => {
    ensureRoutes();
  }, []);
  return s;
}

export function rowOf(status: AuthStatusMsg | null, p: string | null | undefined): AuthRow | undefined {
  return status?.providers.find((r) => r.provider === p);
}

/** test hook */
export function _resetAiStore() {
  state = { routes: null, status: null, checking: false };
}
