// Assisted fill orchestration: gate (confirmed manifest hash) -> resolve + re-hash the files -> open the
// platform's upload page in the account's session -> run the fill plan over CDP. Never clicks publish.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { WebContents } from 'electron';
import { loginState } from '../../shared/channels';
import type { EngineClient } from '../../shared/engineClient';
import { hostAllowed, uploadUrlFor, type Adapter } from '../../shared/publish/adapterSchema';
import { planFill } from '../../shared/publish/fillPlan';
import { checkFill, resolveInside, type FillRequest, type GateReason } from '../../shared/publish/gating';
import { copyForPlatform } from '../../shared/publish/postCopy';
import type { PublishBrowser } from './browser';
import { runFill, type StepResult } from './cdpFill';
import type { PublishStore } from './store';

export type FillOutcome =
  | { ok: true; results: StepResult[]; job: string; platform: string }
  | { ok: false; reason: GateReason | 'file-missing' | 'file-changed' | 'login-required' | 'debugger-busy' | 'page-failed' | 'bad-param'; detail?: string };

export function sha256File(p: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash('sha256');
    fs.createReadStream(p)
      .on('data', (d) => h.update(d))
      .on('end', () => resolve(h.digest('hex')))
      .on('error', reject);
  });
}

function waitLoaded(wc: WebContents, timeoutMs = 30000): Promise<void> {
  return new Promise((resolve) => {
    if (!wc.isLoading()) return resolve();
    const t = setTimeout(resolve, timeoutMs);
    wc.once('did-stop-loading', () => {
      clearTimeout(t);
      resolve();
    });
  });
}

function onUploadPage(url: string, a: Adapter, target = a.uploadUrl): boolean {
  try {
    const u = new URL(url);
    const up = new URL(target);
    return hostAllowed(u.hostname, a.allowedHosts) && u.pathname.startsWith(up.pathname.replace(/\/$/, ''));
  } catch {
    return false;
  }
}

export async function assistedFill(
  deps: {
    client: EngineClient;
    store: PublishStore;
    adapters: Adapter[];
    browser: PublishBrowser;
    onStep?: (r: StepResult) => void;
  },
  req: FillRequest & { account: string; params?: Record<string, string> },
): Promise<FillOutcome> {
  const m = await deps.client.manifest(req.batchId);
  const gate = checkFill(req, m.manifest, m.verify, deps.store.confirmations(req.batchId), deps.adapters);
  if (!gate.ok) return { ok: false, reason: gate.reason, detail: gate.detail };
  const { item, adapter } = gate;
  const dir = m.dir!;
  const video = resolveInside(dir, item.files.video, path.sep);
  if (!video || !fs.existsSync(video)) return { ok: false, reason: 'file-missing', detail: item.files.video };
  if ((await sha256File(video)) !== item.sha256) return { ok: false, reason: 'file-changed', detail: item.files.video };
  const cover = item.files.cover ? resolveInside(dir, item.files.cover, path.sep) : null;
  const postPath = item.files.post ? resolveInside(dir, item.files.post, path.sep) : null;
  const md = postPath && fs.existsSync(postPath) ? fs.readFileSync(postPath, 'utf8') : '';
  const copy = copyForPlatform(md, item.title, adapter.fields.title !== null);

  let target: string;
  try {
    target = uploadUrlFor(adapter, req.params); // Reddit: r/<subreddit>/submit when she typed one
  } catch (e) {
    return { ok: false, reason: 'bad-param', detail: (e as Error).message };
  }
  const entry = deps.browser.open(adapter, req.account, 'upload');
  const wc = entry.view.webContents;
  await waitLoaded(wc);
  if (!onUploadPage(wc.getURL(), adapter, target)) {
    await wc.loadURL(target).catch(() => undefined);
    await waitLoaded(wc);
  }
  if (loginState(wc.getURL() || adapter.uploadUrl, adapter, null) === 'out' || /login|signin|passport/i.test(new URL(wc.getURL() || adapter.uploadUrl).pathname)) {
    return { ok: false, reason: 'login-required' };
  }
  if (!onUploadPage(wc.getURL(), adapter, target)) return { ok: false, reason: 'page-failed', detail: wc.getURL() };

  const steps = planFill(adapter, { videoPath: video, coverPath: cover && fs.existsSync(cover) ? cover : null, copy });
  const dbg = wc.debugger;
  let attachedHere = false;
  try {
    if (!dbg.isAttached()) {
      dbg.attach('1.3');
      attachedHere = true;
    }
  } catch (e) {
    return { ok: false, reason: 'debugger-busy', detail: (e as Error).message };
  }
  try {
    const results = await runFill((method, params) => dbg.sendCommand(method, params), steps, { onStep: deps.onStep });
    return { ok: true, results, job: item.job, platform: item.platform };
  } finally {
    if (attachedHere && dbg.isAttached()) dbg.detach();
  }
}
