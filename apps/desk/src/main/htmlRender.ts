// HTML -> PNG for the engine, rendered by this app's own Chromium (offscreen window). The Lite (Mac App Store) build
// cannot download or run a separate Chrome (App Review 2.4.5: no downloaded executables; a sandboxed child cannot
// start another browser), so the engine's vstudio.render.html_to_png posts here instead when VSTUDIO_HTML_RENDER_URL
// is set (designed covers, slides, title cards).
//   POST /render  Authorization: Bearer <token>
//   {file, query?, width, height, scale?, wait?, transparent?, out}  ->  {ok: true, out, width, height}
// Only local .html files the app may read are loaded (file://, no network: every other request is cancelled), into
// an in-memory session with no preload and JavaScript sandboxed; the PNG is written where the engine asked, which must
// be next to the page or inside the app's own data. Bound to 127.0.0.1, one random port and token per launch.
import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { BrowserWindow, session } from 'electron';

export interface RenderJob {
  file: string;
  query?: string;
  width: number;
  height: number;
  scale?: number;
  wait?: number;
  transparent?: boolean;
  out: string;
}

const MAX_SIDE = 8192;

/** Validate a request body -> a job, or an error text. Pure (tests). */
export function parseJob(body: unknown, readable: (f: string) => boolean): RenderJob | string {
  if (!body || typeof body !== 'object') return 'a JSON object';
  const b = body as Record<string, unknown>;
  const str = (k: string) => (typeof b[k] === 'string' ? (b[k] as string) : '');
  const file = str('file');
  const out = str('out');
  if (!path.isAbsolute(file) || !/\.html?$/i.test(file)) return 'file: an absolute .html path';
  if (!path.isAbsolute(out) || !/\.png$/i.test(out)) return 'out: an absolute .png path';
  if (!readable(file)) return 'file: not readable by this app';
  if (!readable(out) && path.dirname(out) !== path.dirname(file)) return 'out: must be next to the page or in the app data';
  const num = (k: string, lo: number, hi: number, def?: number) => {
    const v = b[k] === undefined ? def : Number(b[k]);
    return v !== undefined && Number.isFinite(v) && v >= lo && v <= hi ? v : undefined;
  };
  const width = num('width', 1, MAX_SIDE);
  const height = num('height', 1, MAX_SIDE);
  const scale = num('scale', 0.25, 4, 1);
  const wait = num('wait', 0, 30000, 500);
  if (!width || !height || scale === undefined || wait === undefined) return 'width / height (1-8192), scale (0.25-4), wait (0-30000 ms)';
  const query = str('query');
  if (query.length > 4096) return 'query: too long';
  return { file, out, width: Math.round(width), height: Math.round(height), scale, wait, transparent: b.transparent === true, ...(query ? { query } : {}) };
}

export class HtmlRenderService {
  readonly token = crypto.randomBytes(24).toString('hex');
  url: string | null = null;
  private server: http.Server | null = null;
  private queue: Promise<unknown> = Promise.resolve();

  constructor(private o: { log: (m: string) => void; readable: (f: string) => boolean }) {}

  start(): Promise<void> {
    const ses = session.fromPartition('html-render'); // in memory, never the app's own session
    ses.webRequest.onBeforeRequest((d, cb) => cb({ cancel: !d.url.startsWith('file://') && !d.url.startsWith('data:') && !d.url.startsWith('blob:') }));
    ses.setPermissionRequestHandler((_wc, _p, cb) => cb(false));
    this.server = http.createServer((req, res) => void this.handle(req, res));
    return new Promise((resolve, reject) => {
      this.server!.once('error', reject);
      this.server!.listen(0, '127.0.0.1', () => {
        this.url = `http://127.0.0.1:${(this.server!.address() as AddressInfo).port}/render`;
        resolve();
      });
    });
  }

  stop() {
    this.server?.close();
    this.server = null;
  }

  private async handle(req: http.IncomingMessage, res: http.ServerResponse) {
    const reply = (code: number, body: unknown) => {
      // one request per connection: an early refusal leaves the body unread, which must not leak into a next request
      res.writeHead(code, { 'content-type': 'application/json', connection: 'close' });
      res.end(JSON.stringify(body));
      req.resume(); // drain whatever was not read
    };
    const auth = String(req.headers.authorization ?? '');
    const want = `Bearer ${this.token}`;
    if (auth.length !== want.length || !crypto.timingSafeEqual(Buffer.from(auth), Buffer.from(want))) return reply(401, { ok: false, error: 'token' });
    if (req.method !== 'POST' || req.url !== '/render' || req.headers.origin) return reply(404, { ok: false, error: 'not found' });
    let raw = '';
    for await (const c of req) {
      raw += c;
      if (raw.length > 64 * 1024) return reply(413, { ok: false, error: 'too large' });
    }
    let job: RenderJob | string;
    try {
      job = parseJob(JSON.parse(raw), this.o.readable);
    } catch {
      job = 'a JSON object';
    }
    if (typeof job === 'string') return reply(400, { ok: false, error: job });
    const j = job;
    // one page at a time: covers are small, and a burst must not open dozens of renderers
    const run = this.queue.then(() => this.render(j));
    this.queue = run.catch(() => undefined);
    try {
      const r = await run;
      reply(200, { ok: true, out: j.out, ...r });
    } catch (e) {
      this.o.log(`[html] render failed: ${(e as Error).message}`);
      reply(500, { ok: false, error: (e as Error).message });
    }
  }

  private async render(j: RenderJob): Promise<{ width: number; height: number }> {
    const w = new BrowserWindow({
      show: false,
      width: j.width,
      height: j.height,
      useContentSize: true,
      frame: false,
      transparent: !!j.transparent,
      backgroundColor: j.transparent ? '#00000000' : '#ffffff',
      webPreferences: {
        offscreen: { deviceScaleFactor: j.scale ?? 1 },
        partition: 'html-render',
        sandbox: true,
        contextIsolation: true,
        nodeIntegration: false,
        webviewTag: false,
        spellcheck: false,
        backgroundThrottling: false,
      },
    });
    try {
      const wc = w.webContents;
      wc.setWindowOpenHandler(() => ({ action: 'deny' }));
      wc.on('will-navigate', (e) => e.preventDefault());
      const url = pathToFileURL(j.file).href + (j.query ? `?${j.query}` : '');
      await Promise.race([wc.loadURL(url), new Promise((_r, rej) => setTimeout(() => rej(new Error('page load timed out')), 60000))]);
      // web fonts + the page's own layout scripts (the --virtual-time-budget of the Chrome path)
      await wc.executeJavaScript('document.fonts ? document.fonts.ready.then(() => true) : true', true).catch(() => true);
      await new Promise((r) => setTimeout(r, j.wait ?? 500));
      const img = await wc.capturePage();
      const size = img.getSize();
      fs.mkdirSync(path.dirname(j.out), { recursive: true });
      fs.writeFileSync(j.out, img.toPNG());
      return size;
    } finally {
      w.destroy();
    }
  }
}
