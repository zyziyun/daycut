// AI accounts & models (main process): provider status from `python -m vstudio.llm auth status`, CLI login / logout
// in an in-app terminal (the command comes from the engine, never from the page; API keys / base URLs are removed
// from its environment so the CLI uses the user's own subscription), the tiny `llm test` round-trip, and the routing
// choices (saved in the desk settings, written to <userData>/llm-routes.json, which the engine reads on every call).
// No password, token or key ever passes through here in clear except keychain keys going into the engine's env.
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type { BrowserWindow } from 'electron';
import { normalizeRoutes, routesFile, routesFromEngine, stripEnv, type AiRoutes, type AuthStatusMsg } from '../shared/aiRoutes';
import type { IpcChannel, IpcPayload } from '../shared/ipc';
import { extraBinDirs } from './engine';
import { prependPath } from './runtime';
import type { SettingsStore } from './settings';
import { ptyProblem, startTerminal, type TermSession } from './terminal';
import { devOnly } from './testHooks';
import { CAPS } from '../shared/edition';

type Handle = <C extends IpcChannel>(channel: C, fn: (p: IpcPayload<C>) => unknown) => void;

export interface AiDeps {
  userData: string;
  settings: () => SettingsStore;
  win: () => BrowserWindow | null;
  /** python + the environment of a process that imports vstudio (keychain keys included) */
  python: () => { python: string; env: NodeJS.ProcessEnv };
  log: (m: string) => void;
}

export function routesFilePath(userData: string) {
  return path.join(userData, 'llm-routes.json');
}

/** Write (or remove, when the creator has no own choices) the engine's routes file. */
export function writeRoutesFile(userData: string, routes: AiRoutes | undefined | null) {
  const f = routesFilePath(userData);
  if (!routes) {
    fs.rmSync(f, { force: true });
    return;
  }
  fs.mkdirSync(userData, { recursive: true });
  const tmp = f + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(routesFile(routes), null, 1));
  fs.renameSync(tmp, f);
}

/** DESK_AI_MOCK=<dir>: status.json / login.json / routes.json / test.json stand in for the engine (tests). */
function mockDir(): string | null {
  return devOnly('DESK_AI_MOCK') || null;
}
function readMock<T>(name: string): T | null {
  const d = mockDir();
  if (!d) return null;
  try {
    return JSON.parse(fs.readFileSync(path.join(d, name), 'utf8')) as T;
  } catch {
    return null;
  }
}

/** `python -m vstudio.llm <args>` -> parsed JSON stdout (stdout / stderr are never logged: they may hold an email). */
export function runLlm(py: { python: string; env: NodeJS.ProcessEnv }, args: string[], timeoutMs: number, routesFileEnv?: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const env = { ...py.env, ...(routesFileEnv !== undefined ? { VSTUDIO_LLM_ROUTES_FILE: routesFileEnv } : {}) };
    const child = spawn(py.python, ['-m', 'vstudio.llm', ...args], { env, stdio: ['ignore', 'pipe', 'pipe'], cwd: os.tmpdir(), windowsHide: true });
    let out = '';
    let err = '';
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => (err += d));
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);
    child.on('error', (e) => {
      clearTimeout(timer);
      reject(e);
    });
    child.on('exit', (code) => {
      clearTimeout(timer);
      const start = out.indexOf('{');
      try {
        resolve(JSON.parse(out.slice(Math.max(0, start))));
      } catch {
        if (timedOut) reject(new Error(`vstudio.llm ${args[0]} timed out after ${Math.round(timeoutMs / 1000)} s`));
        else reject(new Error(`vstudio.llm ${args[0]} failed (${code}): ${err.trim().split('\n').slice(-1)[0] ?? ''}`.slice(0, 300)));
      }
    });
  });
}

/** auth status with the claude-code round-trip, and without it (fallback when the round-trip hangs) */
export const STATUS_PROBE_MS = 45_000;
export const STATUS_QUICK_MS = 25_000;

/** A status failure as a code: the engine itself is broken / it took too long / anything else. */
export function statusErrorCode(msg: string): 'engine' | 'timeout' | 'failed' {
  if (/timed out/i.test(msg)) return 'timeout';
  if (/No module named|ModuleNotFoundError|ImportError|ENOENT|EACCES|spawn /i.test(msg)) return 'engine';
  return 'failed';
}

let term: TermSession | null = null;
let lastStatus: AuthStatusMsg | null = null;

export function registerAiIpc(handle: Handle, d: AiDeps) {
  const send = (ch: string, data: unknown) => {
    try {
      d.win()?.webContents.send(ch, data);
    } catch {
      /* window gone */
    }
  };

  handle('ai:status', async (p) => {
    if (lastStatus && !p?.refresh) return lastStatus;
    const mock = readMock<{ providers: AuthStatusMsg['providers'] }>('status.json');
    const base = ['auth', 'status', '--json', ...(p?.providers ?? []).flatMap((x) => ['--provider', x])];
    const run = (probe: boolean, ms: number) => runLlm(d.python(), probe ? base : [...base, '--no-probe'], ms) as Promise<{ providers: AuthStatusMsg['providers'] }>;
    try {
      let probeTimedOut = false;
      let r: { providers: AuthStatusMsg['providers'] };
      if (mock) r = mock;
      else if (p?.probe === false) r = await run(false, STATUS_QUICK_MS);
      else {
        try {
          r = await run(true, STATUS_PROBE_MS);
        } catch (e) {
          // an expired Claude Code login can take minutes to fail: show what is known without the round-trip
          if (statusErrorCode((e as Error).message) !== 'timeout') throw e;
          probeTimedOut = true;
          r = await run(false, STATUS_QUICK_MS);
        }
      }
      const rows = r.providers ?? [];
      // a partial refresh (one provider) updates that row only
      const merged = p?.providers?.length && lastStatus ? lastStatus.providers.map((x) => rows.find((y) => y.provider === x.provider) ?? x) : rows;
      lastStatus = { providers: merged, at: Date.now(), ...(probeTimedOut ? { probeTimedOut } : {}) };
    } catch (e) {
      // never the raw text (a Python traceback with paths): a code the page words itself
      const code = statusErrorCode((e as Error).message);
      d.log(`[ai] auth status: ${code}`);
      lastStatus = { providers: lastStatus?.providers ?? [], at: Date.now(), error: code };
    }
    return lastStatus;
  });

  handle('ai:test', async (p) => {
    const mock = readMock<Record<string, unknown>>('test.json');
    if (mock) return mock[p.provider] ?? { ok: true, provider: p.provider, model: 'mock' };
    try {
      return await runLlm(d.python(), ['test', '--provider', p.provider, '--timeout', '120'], 150000);
    } catch (e) {
      return { ok: false, provider: p.provider, error: (e as Error).message };
    }
  });

  handle('ai:terminal', async (p) => {
    // the Lite (Mac App Store) build is sandboxed: it cannot run the CLIs she installed, so it has no CLI login
    if (!CAPS.cliLogins) throw new Error('subscription sign-in is in the full version of Reelfold (reelfold.com)');
    term?.kill();
    term = null;
    const mock = readMock<Record<string, { command: string[]; display?: string; env_unset?: string[] }>>('login.json');
    const mocked = mock?.[`${p.provider}:${p.action}`] ?? mock?.[p.provider];
    const r = (mocked
      ? { ok: true, ...mocked }
      : await runLlm(d.python(), ['auth', p.action, '--provider', p.provider, '--json', ...(p.variant ? ['--variant', p.variant] : [])], 30000)) as {
      ok: boolean;
      command?: string[];
      display?: string;
      env_unset?: string[];
      message?: { message?: string; message_zh?: string };
    };
    if (!r.ok || !r.command?.length) throw new Error(r.message?.message ?? 'this provider has no CLI login');
    // the CLI's own environment: the user's shell env + where CLIs live, minus every API key / base URL it could
    // pick up instead of the subscription login (and minus the keychain keys, which are never put here)
    const base = prependPath({ ...process.env }, extraBinDirs()) as Record<string, string | undefined>;
    const env = { ...stripEnv(base, r.env_unset ?? []), TERM: 'xterm-256color', COLORTERM: 'truecolor' };
    const session = startTerminal(r.command, env, { cols: p.cols, rows: p.rows }, {
      onData: (data) => send('term:data', { id: session.id, data }),
      onExit: (code) => {
        if (term?.id === session.id) term = null;
        lastStatus = null; // the next status call re-checks
        send('term:exit', { id: session.id, code, provider: p.provider, action: p.action });
      },
    }, os.homedir(), d.python().python);
    term = session;
    d.log(`[ai] ${p.action} terminal for ${p.provider} (${session.backend}${session.backend !== 'pty' && ptyProblem ? `: ${ptyProblem}` : ''})`);
    return { id: session.id, display: r.display ?? r.command.map((x) => path.basename(x)).join(' '), backend: session.backend };
  });
  handle('term:input', async (p) => {
    if (term?.id === p.id) term.write(p.data);
  });
  handle('term:resize', async (p) => {
    if (term?.id === p.id) term.resize(p.cols, p.rows);
  });
  handle('term:kill', async (p) => {
    if (term?.id === p.id) {
      term.kill();
      term = null;
    }
  });

  const engineRoutes = async () => {
    const mock = readMock<Record<string, { provider?: string; model?: string | null; fallback?: unknown }>>('routes.json');
    if (mock) return mock;
    try {
      // the persona / client values: read without the desk's own routes file
      return (await runLlm(d.python(), ['route', '--json'], 30000, '')) as Record<string, { provider?: string; model?: string | null; fallback?: unknown }>;
    } catch (e) {
      d.log(`[ai] route --json failed: ${(e as Error).message}`);
      return null;
    }
  };
  let initial: AiRoutes | null = null;
  handle('ai:routes', async () => {
    const saved = d.settings().get().aiRoutes ?? null;
    initial ??= routesFromEngine(await engineRoutes());
    return { saved, initial, routes: saved ?? initial };
  });
  handle('ai:setRoutes', async (p) => {
    const routes = p.routes === null ? null : normalizeRoutes(p.routes);
    d.settings().set({ aiRoutes: routes ?? undefined });
    writeRoutesFile(d.userData, routes);
    initial ??= routesFromEngine(await engineRoutes());
    if (!routes) writeRoutesFile(d.userData, initial); // back to the defaults: the engine follows what is shown
    const msg = { saved: routes, initial, routes: routes ?? initial };
    send('ai:routes', msg);
    return msg;
  });
  /** Fresh profile (nothing saved): the engine follows the routes the page shows (persona values, else Claude Code
   * with Codex as fallback), instead of "none" while the page claims Claude Code (P1-6). */
  return {
    primeRoutes: async () => {
      if (d.settings().get().aiRoutes) return;
      initial ??= routesFromEngine(await engineRoutes());
      try {
        writeRoutesFile(d.userData, initial);
      } catch {
        /* read-only profile */
      }
    },
  };
}

/** At start-up: the routes file matches the saved settings (written by an older run, or removed). */
export function syncRoutesFile(userData: string, routes: AiRoutes | undefined) {
  try {
    writeRoutesFile(userData, routes ?? null);
  } catch {
    /* read-only profile: the engine falls back to the persona */
  }
}
