import { describe, expect, it, vi } from 'vitest';
import { EngineClient, EngineError, parseSSE } from '../../src/shared/engineClient';

const BASE = 'app://desk';
const TOKEN = 'tok'.repeat(20);

function mockFetch(status: number, body: unknown) {
  return vi.fn(async (_url: string, _init?: RequestInit) => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status }));
}

describe('EngineClient (mocked fetch)', () => {
  it('sends the bearer token and parses JSON', async () => {
    const f = mockFetch(200, [{ id: 'abcdefabcdef', name: 'x' }]);
    const c = new EngineClient(BASE, TOKEN, f);
    const r = await c.batches();
    expect(r[0].name).toBe('x');
    const [url, init] = f.mock.calls[0];
    expect(url).toBe(`${BASE}/api/batches`);
    expect((init!.headers as Record<string, string>).Authorization).toBe(`Bearer ${TOKEN}`);
  });

  it('posts JSON bodies', async () => {
    const f = mockFetch(200, { started: true });
    const c = new EngineClient(BASE, TOKEN, f);
    await c.run('abcdefabcdef', { pilot: 3 });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe(`${BASE}/api/batches/abcdefabcdef/run`);
    expect(init!.method).toBe('POST');
    expect(JSON.parse(String(init!.body))).toEqual({ pilot: 3 });
    expect((init!.headers as Record<string, string>)['Content-Type']).toBe('application/json');
  });

  it('maps engine errors to EngineError with the message', async () => {
    const c = new EngineClient(BASE, TOKEN, mockFetch(400, { error: 'name: letters, digits' }));
    await expect(c.createBatch({ name: '../x', recipe: 'r', platforms: [] })).rejects.toMatchObject({ status: 400, message: 'name: letters, digits' });
    const c2 = new EngineClient(BASE, TOKEN, mockFetch(500, 'not json'));
    await expect(c2.health()).rejects.toBeInstanceOf(EngineError);
    const c3 = new EngineClient(BASE, TOKEN, vi.fn(async () => Promise.reject(new Error('ECONNREFUSED'))));
    await expect(c3.health()).rejects.toMatchObject({ status: 0 });
  });

  it('refuses bad ids before any request', async () => {
    const f = mockFetch(200, {});
    const c = new EngineClient(BASE, TOKEN, f);
    expect(() => c.status('../../x')).toThrow(EngineError);
    expect(() => c.job('abcdefabcdef', '../x')).toThrow(EngineError);
    expect(f).not.toHaveBeenCalled();
  });

  it('only talks to the engine route app://desk/api (forwarded by main)', () => {
    expect(() => new EngineClient('http://example.com:1', TOKEN)).toThrow();
    expect(() => new EngineClient('http://127.0.0.1:4321', TOKEN)).toThrow();
    expect(() => new EngineClient('app://other', TOKEN)).toThrow();
  });

  it('encodes query parameters', async () => {
    const f = mockFetch(200, []);
    await new EngineClient(BASE, TOKEN, f).events('abcdefabcdef', 10, 's001.h1');
    expect(f.mock.calls[0][0]).toBe(`${BASE}/api/batches/abcdefabcdef/events?n=10&job=s001.h1`);
  });

  it('parses SSE chunks across boundaries', () => {
    const a = parseSSE(': connected\n\nevent: log\ndata: {"type":"log","line":"a"}\n\nevent: st');
    expect(a.events).toEqual([{ type: 'log', line: 'a' }]);
    expect(a.rest).toBe('event: st');
    const b = parseSSE(a.rest + 'atus\ndata: {"type":"status"}\n\n: ping\n\n');
    expect(b.events).toEqual([{ type: 'status' }]);
    expect(b.rest).toBe('');
    expect(parseSSE('data: {bad json}\n\n').events).toEqual([]);
  });

  it('streams events from a fetch body', async () => {
    const enc = new TextEncoder();
    const body = new ReadableStream({
      start(c) {
        c.enqueue(enc.encode('data: {"type":"batches"}\n\nda'));
        c.enqueue(enc.encode('ta: {"type":"log","batch":"b","line":"x"}\n\n'));
        c.close();
      },
    });
    const f = vi.fn(async () => new Response(body, { status: 200 }));
    const got: unknown[] = [];
    await new EngineClient(BASE, TOKEN, f).stream((e) => got.push(e), new AbortController().signal);
    expect(got).toEqual([{ type: 'batches' }, { type: 'log', batch: 'b', line: 'x' }]);
  });
});
