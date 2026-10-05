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

export interface EngineConfig {
  engineDir: string; // folder holding server.py
  enginePath?: string; // the video-studio repo (lib/ goes on PYTHONPATH)
  python: string;
  dataDir: string;
  allowedOrigins: string[];
  mock?: boolean;
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
  return 'python3';
}

export function defaultEnginePath(appPath: string, preferred?: string): string | undefined {
  for (const p of [preferred, process.env.VSTUDIO_ENGINE_PATH, path.resolve(appPath, '..', 'video-studio')]) {
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
    const env: NodeJS.ProcessEnv = {
      ...process.env,
      DESK_TOKEN: token,
      DESK_ALLOWED_ORIGINS: this.cfg.allowedOrigins.join(','),
      DESK_DATA_DIR: this.cfg.dataDir,
      PYTHONUNBUFFERED: '1',
      // Finder-launched apps get a minimal PATH; ffmpeg usually lives in Homebrew
      PATH: ['/opt/homebrew/bin', '/usr/local/bin', process.env.PATH ?? ''].join(':'),
    };
    if (this.cfg.enginePath) {
      env.VSTUDIO_ENGINE_PATH = this.cfg.enginePath;
      const lib = path.join(this.cfg.enginePath, 'lib');
      env.PYTHONPATH = env.PYTHONPATH ? `${lib}${path.delimiter}${env.PYTHONPATH}` : lib;
    }
    if (this.cfg.mock) env.DESK_ENGINE_MOCK = '1';
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

  stop() {
    const c = this.child;
    this.child = null;
    this.info = null;
    if (!c) return;
    c.stdin?.end();
    c.kill('SIGTERM');
    setTimeout(() => c.exitCode === null && c.kill('SIGKILL'), 3000).unref();
  }
}
