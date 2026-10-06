// `npm run dev` single-instance guard. Each run records itself (pid, process group, port) in a pidfile; the next
// run stops that previous dev process group cleanly (SIGTERM, then SIGKILL after a grace period) before it binds
// the Vite port, instead of crashing with "Port 5173 is already in use". A port held by a dev run of this repo
// that wrote no pidfile (older dev.mjs) is found through lsof and stopped the same way; a port held by anything
// else is never touched - the caller then picks another free port.
import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';

export function pidfilePath(root, dir = os.tmpdir()) {
  const h = crypto.createHash('sha1').update(path.resolve(root)).digest('hex').slice(0, 10);
  return path.join(dir, `video-studio-desk-dev-${h}.json`);
}

export function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 1) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';
  }
}

export function readPidfile(file) {
  try {
    const d = JSON.parse(fs.readFileSync(file, 'utf8'));
    return d && Number.isInteger(d.pid) ? d : null;
  } catch {
    return null;
  }
}

export function writePidfile(file, info) {
  fs.writeFileSync(file, JSON.stringify({ ...info, at: Date.now() }));
}

/** Remove the pidfile only when it is still ours (a newer run may have replaced it). */
export function clearPidfile(file, pid = process.pid) {
  const d = readPidfile(file);
  if (d && d.pid === pid) fs.rmSync(file, { force: true });
}

export function processGroup(pid) {
  try {
    const g = Number(execFileSync('ps', ['-o', 'pgid=', '-p', String(pid)], { encoding: 'utf8' }).trim());
    return Number.isInteger(g) && g > 1 ? g : null;
  } catch {
    return null;
  }
}

export function commandOf(pid) {
  try {
    return execFileSync('ps', ['-o', 'command=', '-p', String(pid)], { encoding: 'utf8' }).trim();
  } catch {
    return '';
  }
}

export function cwdOf(pid) {
  try {
    const out = execFileSync('lsof', ['-a', '-p', String(pid), '-d', 'cwd', '-Fn'], { encoding: 'utf8' });
    const line = out.split('\n').find((l) => l.startsWith('n'));
    return line ? line.slice(1) : '';
  } catch {
    return '';
  }
}

export function listenerPids(port) {
  try {
    const out = execFileSync('lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t'], { encoding: 'utf8' });
    return out.split('\n').map(Number).filter((n) => Number.isInteger(n) && n > 1);
  } catch {
    return [];
  }
}

export function portFree(port, host = 'localhost') {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.once('error', () => resolve(false));
    s.listen({ port, host, exclusive: true }, () => s.close(() => resolve(true)));
  });
}

/** Is `pid` a dev run (node scripts/dev.mjs) of the repo at `root`? */
export function isOurDev(pid, root) {
  const cmd = commandOf(pid);
  if (!/scripts[\\/]dev\.mjs/.test(cmd)) return false;
  const r = path.resolve(root);
  return cmd.includes(r) || path.resolve(cwdOf(pid) || '/') === r;
}

/** SIGTERM the process group (or the single process), wait, then SIGKILL. Never our own group. */
export async function stopRun(pid, { pgid = null, graceMs = 4000, self = process } = {}) {
  const ownGroup = processGroup(self.pid);
  const group = pgid && pgid !== ownGroup ? pgid : null;
  const send = (sig) => {
    try {
      if (group) process.kill(-group, sig);
      else process.kill(pid, sig);
    } catch {
      /* gone */
    }
  };
  send('SIGTERM');
  const t0 = Date.now();
  while (alive(pid) && Date.now() - t0 < graceMs) await new Promise((r) => setTimeout(r, 100));
  if (alive(pid)) send('SIGKILL');
  const t1 = Date.now();
  while (alive(pid) && Date.now() - t1 < 2000) await new Promise((r) => setTimeout(r, 50));
  return !alive(pid);
}

/**
 * Before binding: stop the previous dev run of this repo (pidfile first, then whoever of ours holds `port`).
 * -> { stopped: pid[], port } where `port` is free to use (the preferred one, or the next free one when a
 * foreign process holds it).
 */
export async function takeOver({ root, port = 5173, file = pidfilePath(root), log = console.log, host = 'localhost', isDev = (cmd) => /scripts[\\/]dev\.mjs/.test(cmd) }) {
  const stopped = [];
  const prev = readPidfile(file);
  if (prev && prev.pid !== process.pid && alive(prev.pid)) {
    const cmd = commandOf(prev.pid);
    if (prev.startedBy === 'dev.mjs' && isDev(cmd)) { // a recycled pid is never killed
      log(`[dev] stopping the previous dev run (pid ${prev.pid}, group ${prev.pgid ?? '-'})`);
      if (await stopRun(prev.pid, { pgid: prev.pgid })) stopped.push(prev.pid);
    }
  }
  if (!(await portFree(port, host))) {
    for (const pid of listenerPids(port)) {
      if (pid !== process.pid && isOurDev(pid, root)) {
        log(`[dev] port ${port} is held by an earlier dev run of this repo (pid ${pid}): stopping it`);
        if (await stopRun(pid, { pgid: processGroup(pid) })) stopped.push(pid);
      }
    }
  }
  let use = port;
  for (let i = 0; i < 20 && !(await portFree(use, host)); i++) use += 1;
  if (use !== port) log(`[dev] port ${port} is used by another program; using ${use}`);
  return { stopped, port: use };
}
