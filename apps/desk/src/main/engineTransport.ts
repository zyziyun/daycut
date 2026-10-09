// How the main process reaches the engine sidecar, and how the UI reaches it through main.
//
// The engine listens on a Unix domain socket in the app's own temp folder (macOS / Linux): no TCP port, so the Mac App
// Store build needs no network.server entitlement and nothing on the network or in a browser can reach it. Windows
// keeps 127.0.0.1 on a random port (CPython has no AF_UNIX there). Either way only this process connects:
//   - main's own EngineClient uses engineFetch();
//   - the UI calls app://desk/api/* (same origin as the page, so no CORS and no engine port in the CSP); the app://
//     protocol handler forwards those requests with forwardToEngine(), streaming the answer (the SSE event stream).
// The per-launch bearer token still guards every request: the UI sends it, main passes it through unchanged.
import crypto from 'node:crypto';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { Readable } from 'node:stream';
import { ENGINE_BASE } from '../shared/engineClient';

export type EngineTarget = { socketPath: string } | { port: number };

/** sun_path is 104 bytes on macOS (108 on Linux), the terminating NUL included. */
export const MAX_SOCKET_PATH = 103;

/** A fresh socket path for one app session: in the temp folder (in the Mac App Store build that is the app's sandbox
 * container, <home>/Library/Containers/<bundle id>/Data/tmp), short enough for sun_path. Windows: null (TCP). */
export function engineSocketPath(name = 'rf-engine', dir = os.tmpdir(), platform: NodeJS.Platform = process.platform): string | null {
  if (platform === 'win32') return null;
  // a POSIX path whatever the host (macOS / Linux only; also keeps the unit test platform-neutral)
  const p = path.posix.join(dir, `${name}-${crypto.randomBytes(4).toString('hex')}.sock`);
  if (Buffer.byteLength(p) > MAX_SOCKET_PATH) throw new Error(`socket path too long for this system (${Buffer.byteLength(p)} > ${MAX_SOCKET_PATH} bytes): ${p}`);
  return p;
}

/** The engine's own HTTP request for `pathAndQuery` (/api/...). Resolves with a web Response whose body streams. */
export function engineRequest(target: EngineTarget, pathAndQuery: string, init: { method?: string; headers?: Record<string, string>; body?: Buffer | string | null; signal?: AbortSignal | null } = {}): Promise<Response> {
  return new Promise<Response>((resolve, reject) => {
    if (!pathAndQuery.startsWith('/api/')) return reject(new Error(`not an engine path: ${pathAndQuery}`));
    const headers: Record<string, string> = { ...init.headers };
    // the engine's DNS-rebinding guard wants this exact Host over TCP; on a socket it is not checked
    headers.host = 'port' in target ? `127.0.0.1:${target.port}` : 'engine';
    const body = init.body ?? null;
    if (body !== null) headers['content-length'] = String(Buffer.byteLength(body));
    const where = 'port' in target ? { host: '127.0.0.1', port: target.port } : { socketPath: target.socketPath };
    const req = http.request({ ...where, method: init.method ?? 'GET', path: pathAndQuery, headers, agent: false }, (res) => {
      const h = new Headers();
      for (const [k, v] of Object.entries(res.headers)) {
        if (v === undefined) continue;
        for (const one of Array.isArray(v) ? v : [v]) h.append(k, one);
      }
      const status = res.statusCode ?? 502;
      const noBody = [101, 204, 205, 304].includes(status) || init.method === 'HEAD';
      if (noBody) res.resume();
      const stream = noBody ? null : (Readable.toWeb(res) as unknown as ReadableStream<Uint8Array>);
      resolve(new Response(stream, { status, statusText: res.statusMessage, headers: h }));
    });
    const signal = init.signal;
    const onAbort = () => req.destroy(Object.assign(new Error('aborted'), { name: 'AbortError' }));
    req.once('error', reject);
    if (signal?.aborted) return onAbort();
    if (signal) {
      signal.addEventListener('abort', onAbort, { once: true });
      req.once('close', () => signal.removeEventListener('abort', onAbort));
    }
    req.end(body ?? undefined);
  });
}

/** fetch() for main's EngineClient: `url` is ENGINE_BASE + /api/... */
export function engineFetch(target: () => EngineTarget | null) {
  return async (url: string, init: RequestInit = {}): Promise<Response> => {
    if (!url.startsWith(ENGINE_BASE + '/')) throw new Error(`not an engine URL: ${url}`);
    const t = target();
    if (!t) throw new Error('engine not running');
    const headers: Record<string, string> = {};
    new Headers(init.headers).forEach((v, k) => (headers[k] = v));
    const body = init.body === undefined || init.body === null ? null : typeof init.body === 'string' ? init.body : Buffer.from(await new Response(init.body).arrayBuffer());
    return engineRequest(t, url.slice(ENGINE_BASE.length), { method: init.method, headers, body, signal: init.signal });
  };
}

/** Request headers passed on to the engine (the token, the page's Origin for its allow-list, content negotiation). */
const FORWARD = ['authorization', 'content-type', 'origin', 'accept', 'last-event-id', 'access-control-request-method', 'access-control-request-headers'];

/** app://desk/api/* from the UI -> the engine; the answer (also a never-ending event stream) is streamed back. */
export async function forwardToEngine(target: EngineTarget | null, req: Request): Promise<Response> {
  const u = new URL(req.url);
  if (!target) return Response.json({ error: 'engine unreachable: not running' }, { status: 503 });
  const headers: Record<string, string> = {};
  for (const k of FORWARD) {
    const v = req.headers.get(k);
    if (v !== null) headers[k] = v;
  }
  const body = req.method === 'GET' || req.method === 'HEAD' || req.method === 'OPTIONS' ? null : Buffer.from(await req.arrayBuffer());
  try {
    return await engineRequest(target, u.pathname + u.search, { method: req.method, headers, body, signal: req.signal });
  } catch (e) {
    return Response.json({ error: `engine unreachable: ${(e as Error).message}` }, { status: 502 });
  }
}
