// Spawns the Python desk engine (engine/server.py) as a sidecar bound to 127.0.0.1 on a random port, with a
// per-launch bearer token. The token lives only in this process, the engine's environment and the renderer's
// memory (handed over through the preload bridge); it is never logged or written to disk.
import { spawn, type ChildProcess } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import type { EngineInfo, EngineMode } from '../shared/types';
import { prependPath } from './runtime';

export interface EngineConfig {
  engineDir: string; // folder holding server.py
  enginePath?: string; // the video-studio repo (lib/ goes on PYTHONPATH)
  python: string;
  dataDir: string;
  allowedOrigins: string[];
  mock?: boolean;
  /** extra variables (bundled runtime, downloaded assets) */
  env?: Record<string, string>;
  /** folders put in front of PATH / PYTHONPATH */
  path?: string[];
  pythonPath?: string[];
  /** bundled runtime: ignore PYTHONPATH / PYTHONHOME inherited from the user's shell */
  isolatePython?: boolean;
  /** ask for this port (a restart keeps the old one so the page's CSP stays valid); the engine falls back to a
   * random port when it is taken */
  port?: number;
}

export function newToken(): string {
  return crypto.randomBytes(32).toString('hex');
}

export function pythonCandidates(): string[] {
  const home = os.homedir();
  return [
    process.env.DESK_PYTHON ?? '',
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

export function defaultEnginePath(appPath: string, preferred?: string, bundled?: string): string | undefined {
  for (const p of [preferred, process.env.VSTUDIO_ENGINE_PATH, bundled, path.resolve(appPath, '..', 'video-studio')]) {
    if (p && fs.existsSync(path.join(p, 'lib', 'vstudio'))) return p;
  }
  return undefined;
}

export class EngineProcess {
  private child: ChildProcess | null = null;
  info: EngineInfo | null = null;
  lastError: string | null = null;
  private log: string[] = [];

  constructor(private cfg: EngineConfig) {}

  recentLog(): string[] {
    return this.log.slice(-200);
  }

  start(timeoutMs = 30000): Promise<EngineInfo> {
    const token = newToken();
    let env: NodeJS.ProcessEnv = {
      ...process.env,
      ...this.cfg.env,
      DESK_TOKEN: token,
      DESK_ALLOWED_ORIGINS: this.cfg.allowedOrigins.join(','),
      DESK_DATA_DIR: this.cfg.dataDir,
      PYTHONUNBUFFERED: '1',
    };
    if (this.cfg.isolatePython) {
      delete env.PYTHONPATH;
      delete env.PYTHONHOME;
    }
    // Finder-launched apps get a minimal PATH; a system ffmpeg usually lives in Homebrew
    const extraPath = process.platform === 'darwin' ? ['/opt/homebrew/bin', '/usr/local/bin'] : [];
    env = prependPath(env, [...(this.cfg.path ?? []), ...extraPath]);
    const pyPath = [...(this.cfg.pythonPath ?? [])];
    if (this.cfg.enginePath) {
      env.VSTUDIO_ENGINE_PATH = this.cfg.enginePath;
      pyPath.push(path.join(this.cfg.enginePath, 'lib'));
    }
    if (env.PYTHONPATH) pyPath.push(env.PYTHONPATH);
    if (pyPath.length) env.PYTHONPATH = pyPath.join(path.delimiter);
    if (this.cfg.mock) env.DESK_ENGINE_MOCK = '1';
    if (this.cfg.port) env.DESK_PORT = String(this.cfg.port);
    else delete env.DESK_PORT;
    const child = spawn(this.cfg.python, [path.join(this.cfg.engineDir, 'server.py')], {
      env,
      stdio: ['pipe', 'pipe', 'pipe'],
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
            const msg = JSON.parse(line) as { ready: boolean; port?: number; mode?: EngineMode; note?: string; error?: string };
            if (!msg.ready || !msg.port) return done(new Error(msg.error ?? 'engine failed to start'));
            this.info = { baseUrl: `http://127.0.0.1:${msg.port}`, token, mode: msg.mode ?? 'mock', note: msg.note ?? null };
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
        this.child = null;
        done(new Error(`engine exited (${code}): ${this.log.slice(-5).join(' | ')}`));
      });
    });
  }

  private push(line: string) {
    this.log.push(line);
    if (this.log.length > 1000) this.log.splice(0, 500);
  }

  /** Stop the engine; resolves once the process has exited (SIGKILL after 3 s), so its port is free again. */
  stop(): Promise<void> {
    const c = this.child;
    this.child = null;
    this.info = null;
    if (!c || c.exitCode !== null || c.signalCode !== null) return Promise.resolve();
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
