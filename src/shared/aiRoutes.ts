// AI accounts & models: the providers the desk knows, which provider each AI task uses (default + per-task overrides
// + an ordered fallback list), how those choices become the engine's routes file (VSTUDIO_LLM_ROUTES_FILE, read on
// every engine call), and the "Claude's login expired, Codex answered" notice. Pure: shared by main, renderer, tests.

export const PROVIDER_IDS = [
  'claude-code',
  'codex',
  'anthropic',
  'openai',
  'deepseek',
  'qwen',
  'kimi',
  'glm',
  'openrouter',
  'ollama',
  'lmstudio',
  'vllm',
] as const;
export type ProviderId = (typeof PROVIDER_IDS)[number];
export type ProviderKind = 'subscription-cli' | 'api' | 'local';

export const PROVIDERS: Record<ProviderId, { kind: ProviderKind; name: string; secret?: KeyName }> = {
  'claude-code': { kind: 'subscription-cli', name: 'Claude Code' },
  codex: { kind: 'subscription-cli', name: 'Codex' },
  anthropic: { kind: 'api', name: 'Anthropic API', secret: 'anthropic' },
  openai: { kind: 'api', name: 'OpenAI API', secret: 'openai' },
  deepseek: { kind: 'api', name: 'DeepSeek', secret: 'deepseek' },
  qwen: { kind: 'api', name: 'Qwen', secret: 'qwen' },
  kimi: { kind: 'api', name: 'Kimi', secret: 'kimi' },
  glm: { kind: 'api', name: 'GLM', secret: 'glm' },
  openrouter: { kind: 'api', name: 'OpenRouter', secret: 'openrouter' },
  ollama: { kind: 'local', name: 'Ollama' },
  lmstudio: { kind: 'local', name: 'LM Studio' },
  vllm: { kind: 'local', name: 'vLLM' },
};

/** API keys kept in the OS keychain (Electron safeStorage) and handed to the engine as these variables only. */
export const KEY_NAMES = ['anthropic', 'openai', 'deepseek', 'qwen', 'kimi', 'glm', 'openrouter'] as const;
export type KeyName = (typeof KEY_NAMES)[number];
export const KEY_ENV: Record<KeyName, string> = {
  anthropic: 'ANTHROPIC_API_KEY',
  openai: 'OPENAI_API_KEY',
  deepseek: 'DEEPSEEK_API_KEY',
  qwen: 'DASHSCOPE_API_KEY',
  kimi: 'MOONSHOT_API_KEY',
  glm: 'ZHIPUAI_API_KEY',
  openrouter: 'OPENROUTER_API_KEY',
};

/** The desk's AI tasks -> the engine's routing task names. */
export const AI_TASKS = {
  plan: 'intake',
  segments: 'segment_plan',
  proofread: 'proofread',
  glossary: 'glossary',
  copy: 'copy',
  edit: 'output_edit',
} as const;
export type AiTask = keyof typeof AI_TASKS;
export const AI_TASK_IDS = Object.keys(AI_TASKS) as AiTask[];

export interface RouteChoice {
  provider: ProviderId | 'none';
  model?: string | null;
  fallback: ProviderId[];
}
/** Saved in the desk settings. A task without an entry follows the default. */
export interface AiRoutes {
  default: RouteChoice;
  tasks: Partial<Record<AiTask, RouteChoice>>;
}

export function isProvider(x: unknown): x is ProviderId {
  return typeof x === 'string' && (PROVIDER_IDS as readonly string[]).includes(x);
}

function cleanChoice(c: Partial<RouteChoice> | undefined | null): RouteChoice | null {
  if (!c || !(isProvider(c.provider) || c.provider === 'none')) return null;
  const fb = (c.fallback ?? []).filter((x, i, a) => isProvider(x) && x !== c.provider && a.indexOf(x) === i).slice(0, 4);
  return { provider: c.provider, model: c.model ? String(c.model).slice(0, 120) : null, fallback: fb };
}

/** The engine's `python -m vstudio.llm route --json` (persona / client values) -> the initial desk choices. */
export function routesFromEngine(engine: Record<string, { provider?: string; model?: string | null; fallback?: unknown }> | null | undefined): AiRoutes {
  const pick = (r?: { provider?: string; model?: string | null; fallback?: unknown }): RouteChoice | null =>
    r
      ? cleanChoice({
          provider: (r.provider === 'none' ? 'none' : r.provider) as ProviderId,
          model: r.model ?? null,
          fallback: (Array.isArray(r.fallback) ? r.fallback : []).map((x) => (typeof x === 'object' && x ? (x as { provider?: string }).provider : x)) as ProviderId[],
        })
      : null;
  const def = pick(engine?.default) ?? { provider: 'claude-code', model: null, fallback: ['codex'] };
  const tasks: AiRoutes['tasks'] = {};
  for (const k of AI_TASK_IDS) {
    const c = pick(engine?.[AI_TASKS[k]]);
    if (c && !sameChoice(c, def)) tasks[k] = c;
  }
  return { default: def, tasks };
}

export function sameChoice(a: RouteChoice, b: RouteChoice): boolean {
  return a.provider === b.provider && (a.model ?? null) === (b.model ?? null) && a.fallback.join() === b.fallback.join();
}

/** The choice a task uses (its own entry, else the default). */
export function effective(routes: AiRoutes, task: AiTask): RouteChoice {
  return routes.tasks[task] ?? routes.default;
}

/** Validated copy of untrusted routes (IPC). Throws on a bad default. */
export function normalizeRoutes(r: unknown): AiRoutes {
  const o = (r ?? {}) as Partial<AiRoutes>;
  const def = cleanChoice(o.default);
  if (!def) throw new Error('routes: default provider required');
  const tasks: AiRoutes['tasks'] = {};
  for (const k of AI_TASK_IDS) {
    const c = cleanChoice(o.tasks?.[k]);
    if (c) tasks[k] = c;
  }
  return { default: def, tasks };
}

type EngineEntry = { provider: string; model?: string; fallback?: string[] };
/** The engine's routes file. Every task gets an explicit entry - "follow the default" is written out - because the
 * engine ranks the persona's llm.tasks above any default: an omitted task would silently use the persona's route. */
export function routesFile(r: AiRoutes): { default: EngineEntry; tasks: Record<string, EngineEntry> } {
  const entry = (c: RouteChoice): EngineEntry => ({ provider: c.provider, ...(c.model ? { model: c.model } : {}), ...(c.fallback.length ? { fallback: c.fallback } : {}) });
  const tasks: Record<string, EngineEntry> = {};
  for (const k of AI_TASK_IDS) tasks[AI_TASKS[k]] = entry(effective(r, k));
  // tasks the desk has no control for (scripts, the batch planner) follow the default too
  for (const extra of ['script', 'planner']) tasks[extra] = entry(r.default);
  return { default: entry(r.default), tasks };
}

/** Engine fallback record (vstudio.llm complete -> output ai / intake planner). */
export interface FallbackInfo {
  from: string;
  to: string;
  code: string;
  error?: string;
}

/** The notice for a run that did not use the chosen provider, or null. key + vars for t(). */
export function fallbackNotice(fb: FallbackInfo | null | undefined): { key: 'aiacc.fb.expired' | 'aiacc.fb.notLoggedIn' | 'aiacc.fb.notInstalled' | 'aiacc.fb.failed'; from: string; to: string; provider: string; login: boolean } | null {
  if (!fb || !fb.from || !fb.to || fb.from === fb.to) return null;
  const key =
    fb.code === 'auth-expired'
      ? 'aiacc.fb.expired'
      : fb.code === 'not-logged-in'
        ? 'aiacc.fb.notLoggedIn'
        : fb.code === 'not-installed'
          ? 'aiacc.fb.notInstalled'
          : 'aiacc.fb.failed';
  const login = PROVIDERS[fb.from as ProviderId]?.kind === 'subscription-cli' && (fb.code === 'auth-expired' || fb.code === 'not-logged-in');
  return { key, from: providerName(fb.from), to: providerName(fb.to), provider: fb.from, login };
}

export function providerName(p: string | null | undefined): string {
  if (!p) return '';
  if (p === 'rules' || p === 'none') return p;
  return PROVIDERS[p as ProviderId]?.name ?? p;
}

// ---------------------------------------------------------------- status rows (python -m vstudio.llm auth status)
export type AuthState =
  | 'logged-in'
  | 'expired'
  | 'not-logged-in'
  | 'not-installed'
  | 'configured'
  | 'not-configured'
  | 'ready'
  | 'server-down'
  | 'no-models'
  | 'error';

export interface EngineMsgLite {
  code: string;
  params?: Record<string, unknown>;
  message?: string;
  message_zh?: string;
}

export interface AuthRow {
  provider: string;
  kind: ProviderKind | 'unknown';
  state: AuthState;
  ready: boolean;
  installed?: boolean | null;
  version?: string | null;
  verified?: boolean;
  account?: { email?: string | null; plan?: string | null; auth_method?: string | null; org?: string | null } | null;
  key_env?: string | null;
  base_url?: string | null;
  models?: string[] | null;
  can_login?: boolean;
  can_logout?: boolean;
  install?: { url: string; command: string } | null;
  message?: EngineMsgLite | null;
  detail?: string | null;
}

export interface AuthStatusMsg {
  providers: AuthRow[];
  at: number;
  error?: string;
}

/** Pill tone + message key for a status row. */
export function pill(row: AuthRow | undefined): { tone: 'ok' | 'warn' | 'bad' | 'off'; key: string } {
  switch (row?.state) {
    case 'logged-in':
      return { tone: 'ok', key: 'aiacc.st.loggedIn' };
    case 'expired':
      return { tone: 'bad', key: 'aiacc.st.expired' };
    case 'not-logged-in':
      return { tone: 'warn', key: 'aiacc.st.notLoggedIn' };
    case 'not-installed':
      return { tone: 'off', key: 'aiacc.st.notInstalled' };
    case 'configured':
      return { tone: row.ready ? 'ok' : 'warn', key: row.ready ? 'aiacc.st.configured' : 'aiacc.st.needsPackage' };
    case 'not-configured':
      return { tone: 'off', key: 'aiacc.st.notConfigured' };
    case 'ready':
      return { tone: 'ok', key: 'aiacc.st.localUp' };
    case 'server-down':
      return { tone: 'off', key: 'aiacc.st.localDown' };
    case 'no-models':
      return { tone: 'warn', key: 'aiacc.st.noModels' };
    case undefined:
      return { tone: 'off', key: 'aiacc.st.checking' };
    default:
      return { tone: 'bad', key: 'aiacc.st.error' };
  }
}

/** Variables a login terminal runs without ("X_*" = every X_ variable), so the CLI uses the user's own login. */
export function stripEnv(env: Record<string, string | undefined>, unset: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(env)) {
    if (v === undefined) continue;
    if (unset.some((u) => k === u || (u.endsWith('*') && k.startsWith(u.slice(0, -1))))) continue;
    out[k] = v;
  }
  return out;
}
