// Drive an app over CDP without a listening port in the app: Chromium's --remote-debugging-pipe (CDP messages on fds
// 3 / 4, NUL-separated), bridged to a WebSocket served by THIS (test) process for Playwright's connectOverCDP. The
// Mac App Store build has no network.server entitlement, so its sandbox refuses --remote-debugging-port's listening
// socket; the pipe needs none.
import { spawn, type ChildProcess } from 'node:child_process';
import type { AddressInfo } from 'node:net';
import { createRequire } from 'node:module';
import type { Readable, Writable } from 'node:stream';

// the ws server Playwright itself ships (no extra dev dependency)
const { wsServer: WebSocketServer } = createRequire(import.meta.url)('playwright-core/lib/utilsBundle') as {
  wsServer: new (o: { host: string; port: number }) => {
    on(ev: 'listening', fn: () => void): void;
    on(ev: 'connection', fn: (ws: { send(s: string): void; on(ev: string, fn: (m: unknown) => void): void; close(): void }) => void): void;
    address(): AddressInfo;
    close(): void;
  };
};

export interface PipedApp {
  proc: ChildProcess;
  /** ws://127.0.0.1:<port>/ for chromium.connectOverCDP */
  endpoint: string;
  stop(): void;
}

export async function spawnWithCdpPipe(exe: string, args: string[], env: NodeJS.ProcessEnv): Promise<PipedApp> {
  const proc = spawn(exe, [...args, '--remote-debugging-pipe'], { env, stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const toApp = proc.stdio[3] as Writable;
  const fromApp = proc.stdio[4] as Readable;
  toApp.on('error', () => undefined); // the app quit
  const wss = new WebSocketServer({ host: '127.0.0.1', port: 0 });
  await new Promise<void>((r) => wss.on('listening', r));
  let client: { send(s: string): void } | null = null;
  const early: string[] = [];
  let buf = Buffer.alloc(0);
  fromApp.on('data', (d: Buffer) => {
    buf = Buffer.concat([buf, d]);
    for (let i = buf.indexOf(0); i >= 0; i = buf.indexOf(0)) {
      const msg = buf.subarray(0, i).toString('utf8');
      buf = buf.subarray(i + 1);
      if (client) client.send(msg);
      else early.push(msg);
    }
  });
  wss.on('connection', (ws) => {
    client = ws;
    for (const m of early.splice(0)) ws.send(m);
    ws.on('message', (m) => toApp.write(String(m) + '\0'));
    ws.on('close', () => (client = null));
  });
  proc.once('exit', () => wss.close());
  return { proc, endpoint: `ws://127.0.0.1:${wss.address().port}/`, stop: () => wss.close() };
}
