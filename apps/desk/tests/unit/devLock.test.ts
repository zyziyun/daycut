// npm run dev single-instance guard: a previous run recorded in the pidfile is stopped (its process group), a
// port held by a foreign process is never touched (the next free port is used), stale pidfiles are harmless.
import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
// @ts-expect-error  plain ESM script without typings
import * as L from '../../scripts/devLock.mjs';

const kids: ChildProcess[] = [];
afterEach(() => {
  for (const k of kids.splice(0)) {
    try {
      process.kill(-k.pid!, 'SIGKILL');
    } catch {
      /* gone */
    }
  }
});

async function freePort(): Promise<number> {
  return new Promise((resolve) => {
    const s = net.createServer();
    s.listen(0, '127.0.0.1', () => {
      const p = (s.address() as net.AddressInfo).port;
      s.close(() => resolve(p));
    });
  });
}

/** A detached node process (its own process group) that listens on `port`. */
async function holder(port: number): Promise<ChildProcess> {
  const k = spawn(process.execPath, ['-e', `require('net').createServer().listen(${port}, '127.0.0.1', () => console.log('up')); setInterval(() => {}, 1000)`], { detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
  kids.push(k);
  await new Promise<void>((r) => k.stdout!.once('data', () => r()));
  return k;
}

describe('dev single-instance guard', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'devlock-'));

  it('pidfile path is per repo and stable', () => {
    expect(L.pidfilePath('/a/repo', tmp)).toBe(L.pidfilePath('/a/repo/', tmp));
    expect(L.pidfilePath('/a/repo', tmp)).not.toBe(L.pidfilePath('/b/repo', tmp));
  });

  it('stops the previous run recorded in the pidfile (its process group) and frees the port', async () => {
    const port = await freePort();
    const k = await holder(port);
    const file = path.join(tmp, 'prev.json');
    L.writePidfile(file, { pid: k.pid, pgid: k.pid, port, startedBy: 'dev.mjs' });
    expect(await L.portFree(port, '127.0.0.1')).toBe(false);
    const r = await L.takeOver({ root: tmp, port, file, log: () => undefined, host: '127.0.0.1', isDev: (cmd: string) => cmd.includes('createServer') });
    expect(r.stopped).toEqual([k.pid]);
    expect(r.port).toBe(port);
    expect(L.alive(k.pid)).toBe(false);
  }, 15000);

  it('never touches a foreign process on the port: uses the next free port', async () => {
    const port = await freePort();
    const k = await holder(port);
    const r = await L.takeOver({ root: tmp, port, file: path.join(tmp, 'none.json'), log: () => undefined, host: '127.0.0.1' });
    expect(r.stopped).toEqual([]);
    expect(r.port).toBeGreaterThan(port);
    expect(L.alive(k.pid)).toBe(true);
  }, 15000);

  it('a recycled pid in the pidfile (not a dev run) is never killed', async () => {
    const port = await freePort();
    const k = await holder(port);
    const file = path.join(tmp, 'recycled.json');
    L.writePidfile(file, { pid: k.pid, pgid: k.pid, port: 1, startedBy: 'dev.mjs' });
    const r = await L.takeOver({ root: tmp, port: await freePort(), file, log: () => undefined, host: '127.0.0.1' });
    expect(r.stopped).toEqual([]);
    expect(L.alive(k.pid)).toBe(true);
  }, 15000);

  it('stale pidfile (dead pid) and clearPidfile only removes our own record', async () => {
    const file = path.join(tmp, 'stale.json');
    L.writePidfile(file, { pid: 999999, pgid: 999999, port: 1, startedBy: 'dev.mjs' });
    const port = await freePort();
    const r = await L.takeOver({ root: tmp, port, file, log: () => undefined, host: '127.0.0.1' });
    expect(r).toEqual({ stopped: [], port });
    L.clearPidfile(file, 12345);
    expect(fs.existsSync(file)).toBe(true);
    L.clearPidfile(file, 999999);
    expect(fs.existsSync(file)).toBe(false);
  });
});
