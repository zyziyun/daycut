// Spawns the Python desk engine (engine/server.py) as a sidecar listening on a Unix domain socket in the app's temp
// folder (Windows: 127.0.0.1 on a random port), with a per-launch bearer token. Only this process connects to it
// (engineTransport.ts); the UI goes through app://desk/api. The token lives only in this process, the engine's
// environment and the renderer's memory (handed over through the preload bridge); it is never logged or written to disk.
import { spawn, type ChildProcess } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import { CAPS } from '../shared/edition';
import { ENGINE_BASE } from '../shared/engineClient';
import type { EngineInfo, EngineMode } from '../shared/types';
import type { EngineTarget } from './engineTransport';
import { prependPath } from './runtime';
import { devOnly } from './testHooks';

export interface EngineConfig {
  engineDir: string; // folder holding server.py
  enginePath?: string; // the video-studio repo (lib/ goes on PYTHONPATH)
  python: string;
  dataDir: string;
  allowedOrigins: string[];
  mock?: boolean;
  /** the sidecar exited without being asked to (crash report: exit code + the last log lines) */
  onCrash?: (code: number | null, tail: string[]) => void;
  /** extra variables (bundled runtime, downloaded assets) */
  env?: Record<string, string>;
  /** folders put in front of PATH / PYTHONPATH */
  path?: string[];
  pythonPath?: string[];
  /** bundled runtime: ignore PYTHONPATH / PYTHONHOME inherited from the user's shell */
  isolatePython?: boolean;
  /** the Unix socket the engine listens on (engineSocketPath()); null / unset: 127.0.0.1 on a random port (Windows) */
  socketPath?: string | null;
  /** the engine died on its own after it was up (crash, OOM, killed): not called for stop() / a failed start */
  onDied?: (detail: string) => void;
}

export function newToken(): string {
  return crypto.randomBytes(32).toString('hex');
}

export function pythonCandidates(): string[] {
  const home = os.homedir();
  return [
    devOnly('DESK_PYTHON') ?? '',
    path.join(home, 'miniconda3/bin/python3'),
    path.join(home, 'anaconda3/bin/python3'),
    '/opt/homebrew/bin/python3',
    '/usr/local/bin/python3',
    '/usr/bin/python3',
  ].filter(Boolean);
}

export function findPython(preferred?: string): string {
  for (const p of [preferred ?? '', ...pythonCandidates()]) {
    if (p && fs.existsSync(p)) return p;
  }
  return process.platform === 'win32' ? 'python' : 'python3';
}

// Dev: the monorepo root (apps/desk -> ../..) holds the engine; a sibling video-studio checkout is the pre-monorepo layout.
export function defaultEnginePath(appPath: string, preferred?: string, bundled?: string): string | undefined {
  const candidates = [preferred, process.env.VSTUDIO_ENGINE_PATH, bundled, path.resolve(appPath, '..', '..'), path.resolve(appPath, '..', 'video-studio')];
  for (const p of candidates) {
    if (p && fs.existsSync(path.join(p, 'lib', 'vstudio'))) return p;
  }
  return undefined;
}

/** Folders where a Finder- / Start-menu-launched app finds Homebrew tools and the AI CLIs (claude, codex). On Windows:
 * the native Claude Code installer (~\\.local\\bin), npm's global prefix (%APPDATA%\\npm: claude.cmd / codex.cmd),
 * winget links and scoop shims (an app started before an install keeps the PATH it was started with). */
export function extraBinDirs(platform: NodeJS.Platform = process.platform, env: NodeJS.ProcessEnv = process.env, home = os.homedir()): string[] {
  if (platform === 'win32') {
    const p = path.win32;
    const local = env.LOCALAPPDATA || p.join(home, 'AppData', 'Local');
    return [
      p.join(home, '.local', 'bin'),
      p.join(env.APPDATA || p.join(home, 'AppData', 'Roaming'), 'npm'),
      p.join(local, 'Microsoft', 'WinGet', 'Links'),
      p.join(home, 'scoop', 'shims'),
    ];
  }
  if (platform !== 'darwin') return [path.join(home, '.local/bin')];
  // the Lite (Mac App Store) build is sandboxed: nothing outside the app runs, so no Homebrew / CLI folders
  if (!CAPS.cliLogins) return [];
  return ['/opt/homebrew/bin', '/usr/local/bin', path.join(home, '.local/bin')];
}

/** Windows: Python's UTF-8 mode, so the engine reads / writes files, pipes and CLI output (Chinese titles, captions,
 * prompts) as UTF-8 instead of the ANSI code page (cp936 / cp1252). Elsewhere UTF-8 is already the default. */
export function utf8Env(platform: NodeJS.Platform = process.platform): Record<string, string> {
  return platform === 'win32' ? { PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8' } : {};
}

/** The environment of a Python process that imports vstudio (the sidecar, or a one-off `python -m vstudio.llm`). */
export function engineProcessEnv(cfg: Pick<EngineConfig, 'env' | 'path' | 'pythonPath' | 'isolatePython' | 'enginePath'>, extra: Record<string, string> = {}): NodeJS.ProcessEnv {
  let env: NodeJS.ProcessEnv = { ...process.env, ...utf8Env(), ...cfg.env, ...extra, PYTHONUNBUFFERED: '1' };
  if (cfg.isolatePython) {
    delete env.PYTHONPATH;
    delete env.PYTHONHOME;
  }
  // Finder-launched apps get a minimal PATH; a system ffmpeg usually lives in Homebrew, the AI CLIs in ~/.local/bin
  env = prependPath(env, [...(cfg.path ?? []), ...extraBinDirs()]);
  const pyPath = [...(cfg.pythonPath ?? [])];
  if (cfg.enginePath) {
    env.VSTUDIO_ENGINE_PATH = cfg.enginePath;
    pyPath.push(path.join(cfg.enginePath, 'lib'));
  }
  if (env.PYTHONPATH) pyPath.push(env.PYTHONPATH);
  if (pyPath.length) env.PYTHONPATH = pyPath.join(path.delimiter);
  return env;
}

/** Windows: end a process and everything it started (taskkill /T /F). */
export function killTree(pid: number | undefined) {
  if (!pid) return;
  try {
    spawn(path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'taskkill.exe'), ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true }).on('error', () => {});
  } catch {
    /* already gone */
  }
}

export class EngineProcess {
  private child: ChildProcess | null = null;
  info: EngineInfo | null = null;
  /** where the running engine listens (main connects there; the UI goes through app://desk/api) */
  target: EngineTarget | null = null;
  lastError: string | null = null;
  private log: string[] = [];
  private stopping = false;

  constructor(private cfg: EngineConfig) {}

  recentLog(): string[] {
    return this.log.slice(-200);
  }

  start(timeoutMs = 30000): Promise<EngineInfo> {
    const token = newToken();
    const env = engineProcessEnv(this.cfg, { DESK_TOKEN: token, DESK_ALLOWED_ORIGINS: this.cfg.allowedOrigins.join(','), DESK_DATA_DIR: this.cfg.dataDir });
    // the fake engine only when main decided so (testSwitch): never inherited from the user's environment
    if (this.cfg.mock) env.DESK_ENGINE_MOCK = '1';
    else delete env.DESK_ENGINE_MOCK;
    if (this.cfg.socketPath) env.DESK_SOCKET = this.cfg.socketPath;
    else delete env.DESK_SOCKET;
    const child = spawn(this.cfg.python, [path.join(this.cfg.engineDir, 'server.py')], {
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true, // Windows: no console window for python.exe (its ffmpeg / CLI children share the hidden one)
    });
    this.child = child;
    return new Promise<EngineInfo>((resolve, reject) => {
      let settled = false;
      const done = (err: Error | null, info?: EngineInfo) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        if (err) {
          this.lastError = err.message;
          reject(err);
        } else resolve(info!);
      };
      const timer = setTimeout(() => done(new Error('engine did not start in time')), timeoutMs);
      const rl = readline.createInterface({ input: child.stdout! });
      rl.on('line', (line) => {
        if (!settled && line.startsWith('{')) {
          try {
            const msg = JSON.parse(line) as { ready: boolean; socket?: string; port?: number; mode?: EngineMode; note?: string; error?: string };
            const target: EngineTarget | null = msg.socket ? { socketPath: msg.socket } : msg.port ? { port: msg.port } : null;
            if (!msg.ready || !target) return done(new Error(msg.error ?? 'engine failed to start'));
            if (this.cfg.socketPath && msg.socket !== this.cfg.socketPath) return done(new Error(`engine listens on ${msg.socket ?? msg.port}, not ${this.cfg.socketPath}`));
            this.target = target;
            this.info = { baseUrl: ENGINE_BASE, token, mode: msg.mode ?? 'real', note: msg.note ?? null };
            return done(null, this.info);
          } catch {
            /* not the ready line */
          }
        }
        this.push(line);
      });
      readline.createInterface({ input: child.stderr! }).on('line', (l) => this.push(l));
      child.on('error', (e) => done(new Error(`cannot start ${this.cfg.python}: ${e.message}`)));
      child.on('exit', (code) => {
        this.info = null;
        this.target = null;
        this.child = null;
        // stopped on purpose (restart / quit): not an engine failure
        if (this.stopping) return done(Object.assign(new Error('engine stopped'), { stopped: true }));
        try {
          this.cfg.onCrash?.(code, this.log.slice(-20));
        } catch {
          /* reporting must not break the restart path */
        }
        const detail = `engine exited (${code ?? child.signalCode}): ${this.log.slice(-5).join(' | ')}`;
        // after a successful start nobody awaits the promise any more: tell the owner, or the app keeps saying
        // "Ready" while every request fails with "engine unreachable"
        if (settled) this.cfg.onDied?.(detail);
        done(new Error(detail));
      });
    });
  }

  private push(line: string) {
    this.log.push(line);
    if (this.log.length > 1000) this.log.splice(0, 500);
  }

  /** Stop the engine; resolves once the process has exited (SIGKILL after 3 s), so its socket / port is free again. Closing
   * stdin asks it to stop its runs and exit. Windows has no SIGTERM (kill() is TerminateProcess, which would orphan the
   * runs' ffmpeg / python children): the engine gets 2 s to exit on its own, then its whole tree is ended. */
  stop(): Promise<void> {
    this.stopping = true;
    const c = this.child;
    this.child = null;
    this.info = null;
    this.target = null;
    if (!c || c.exitCode !== null || c.signalCode !== null) return Promise.resolve();
    if (process.platform === 'win32') {
      return new Promise<void>((resolve) => {
        const tree = setTimeout(() => c.exitCode === null && killTree(c.pid), 2000);
        const cap = setTimeout(resolve, 5000);
        c.once('exit', () => {
          clearTimeout(tree);
          clearTimeout(cap);
          resolve();
        });
        c.stdin?.end();
      });
    }
    return new Promise<void>((resolve) => {
      const kill = setTimeout(() => c.exitCode === null && c.kill('SIGKILL'), 3000);
      const cap = setTimeout(resolve, 5000); // never hang a restart on a stuck child
      c.once('exit', () => {
        clearTimeout(kill);
        clearTimeout(cap);
        resolve();
      });
      c.stdin?.end();
      c.kill('SIGTERM');
    });
  }
}
