// "Time to post" for one 发布 board row: open the platform's upload page in the account's own session, set the
// rendered file made for that platform, type the title / text / tags, outline the Publish button - and then watch
// the page: when she has pressed Publish herself (a success URL or text from the adapter), the row becomes
// "posted" with the post's link when the page shows one. The app never clicks Publish.
import fs from 'node:fs';
import type { WebContents } from 'electron';
import type { EngineClient } from '../../shared/engineClient';
import { loginState } from '../../shared/channels';
import { adapterFor, type Adapter } from '../../shared/publish/adapterSchema';
import { planFill } from '../../shared/publish/fillPlan';
import { copyForPost, pickFile, postedSignal } from '../../shared/publish/postNow';
import type { CalendarPost } from '../../shared/v04';
import type { PublishBrowser } from './browser';
import { runFill, type StepResult } from './cdpFill';
import { onUploadPage, waitLoaded } from './fill';
import { probeLogin } from './loginProbe';

export type PostFillOutcome =
  | { ok: true; postId: string; adapterId: string; account: string; results: StepResult[]; video: string; cover: string | null }
  | { ok: false; reason: 'no-post' | 'posted' | 'no-adapter' | 'adapter-todo' | 'no-account' | 'no-file' | 'file-missing' | 'login-required' | 'page-failed' | 'debugger-busy'; detail?: string; adapterId?: string; account?: string };

export interface PostFillDeps {
  client: EngineClient;
  adapters: Adapter[];
  browser: PublishBrowser;
  accounts: Record<string, string[]>;
  onStep?: (r: StepResult & { postId: string }) => void;
  /** she pressed Publish and the page said so */
  onPosted?: (postId: string, url: string | null) => void;
  log?: (msg: string) => void;
}

/** What the success check reads in the platform page (isolated world): the text and the links, nothing typed. */
const SUCCESS_JS = `(() => ({ text: (document.body && document.body.innerText || '').slice(0, 20000), links: [...document.querySelectorAll('a[href]')].slice(0, 400).map((a) => a.href) }))()`;

const watchers = new Map<number, () => void>();

/** Watch one platform page until it shows the adapter's success signal (or 45 minutes pass / the page closes). */
export function watchPosted(wc: WebContents, adapter: Adapter, onPosted: (url: string | null) => void, opts: { timeoutMs?: number; pollMs?: number } = {}): () => void {
  watchers.get(wc.id)?.();
  if (!adapter.success) return () => undefined;
  let done = false;
  const check = async () => {
    if (done || wc.isDestroyed()) return;
    let page = { text: '', links: [] as string[] };
    try {
      page = (await wc.executeJavaScriptInIsolatedWorld(1002, [{ code: SUCCESS_JS }])) as typeof page;
    } catch {
      /* navigating */
    }
    if (done || wc.isDestroyed()) return;
    const sig = postedSignal(wc.getURL(), page.text, page.links, adapter.success);
    if (sig.posted) {
      stop();
      onPosted(sig.url);
    }
  };
  const nav = () => void check();
  const timer = setInterval(nav, opts.pollMs ?? 2000);
  const limit = setTimeout(() => stop(), opts.timeoutMs ?? 45 * 60_000);
  wc.on('did-navigate', nav);
  wc.on('did-navigate-in-page', nav);
  const stop = () => {
    if (done) return;
    done = true;
    clearInterval(timer);
    clearTimeout(limit);
    if (!wc.isDestroyed()) {
      wc.removeListener('did-navigate', nav);
      wc.removeListener('did-navigate-in-page', nav);
    }
    watchers.delete(wc.id);
  };
  wc.once('destroyed', stop);
  watchers.set(wc.id, stop);
  return stop;
}

export async function fillScheduledPost(deps: PostFillDeps, req: { postId: string; account?: string }): Promise<PostFillOutcome> {
  const cal = await deps.client.calendar(undefined, { queue: false });
  const post: CalendarPost | undefined = cal.posts.find((p) => p.id === req.postId);
  if (!post) return { ok: false, reason: 'no-post' };
  if (post.state === 'posted') return { ok: false, reason: 'posted' };
  const adapter = adapterFor(post.platform.split(':')[0], deps.adapters);
  if (!adapter) return { ok: false, reason: 'no-adapter', detail: post.platform };
  if (adapter.status === 'todo') return { ok: false, reason: 'adapter-todo', adapterId: adapter.id };
  const accounts = deps.accounts[adapter.id] ?? [];
  const account = req.account && accounts.includes(req.account) ? req.account : accounts[0];
  if (!account) return { ok: false, reason: 'no-account', adapterId: adapter.id };

  const clips = await deps.client.clips(post.item);
  const clip = clips.clips.find((c) => c.id === post.clip);
  const file = clip ? pickFile(clip.files, post.platform) : null;
  if (!clip || !file) return { ok: false, reason: 'no-file', detail: post.clip, adapterId: adapter.id, account };
  if (!fs.existsSync(file.path)) return { ok: false, reason: 'file-missing', detail: file.path, adapterId: adapter.id, account };
  const cover = clip.cover && fs.existsSync(clip.cover) ? clip.cover : null;
  const copy = copyForPost(post, adapter.fields.title !== null, [clip.title, clip.post?.title ?? ''].filter(Boolean));

  const entry = deps.browser.open(adapter, account, 'upload');
  const wc = entry.view.webContents;
  await waitLoaded(wc);
  if (!onUploadPage(wc.getURL(), adapter)) {
    await wc.loadURL(adapter.uploadUrl).catch(() => undefined);
    await waitLoaded(wc);
  }
  const ses = wc.session;
  const byCookie = await probeLogin(ses, adapter);
  if (byCookie === 'out' || loginState(wc.getURL() || adapter.uploadUrl, adapter, null) === 'out') {
    return { ok: false, reason: 'login-required', adapterId: adapter.id, account };
  }
  if (!onUploadPage(wc.getURL(), adapter)) return { ok: false, reason: 'page-failed', detail: wc.getURL(), adapterId: adapter.id, account };

  const steps = planFill(adapter, { videoPath: file.path, coverPath: cover, copy });
  const dbg = wc.debugger;
  let attachedHere = false;
  try {
    if (!dbg.isAttached()) {
      dbg.attach('1.3');
      attachedHere = true;
    }
  } catch (e) {
    return { ok: false, reason: 'debugger-busy', detail: (e as Error).message, adapterId: adapter.id, account };
  }
  let results: StepResult[];
  try {
    results = await runFill((method, params) => dbg.sendCommand(method, params), steps, { onStep: (r) => deps.onStep?.({ ...r, postId: post.id }) });
  } finally {
    if (attachedHere && dbg.isAttached()) dbg.detach();
  }
  if (results.some((r) => r.field === 'file' && r.status === 'ok')) {
    await deps.client.updatePost(post.id, { state: 'filled' });
    watchPosted(wc, adapter, (url) => {
      void deps.client
        .updatePost(post.id, { state: 'posted', via: 'assisted', ...(url ? { url } : {}) })
        .then(() => deps.onPosted?.(post.id, url))
        .catch((e) => deps.log?.(`[publish] could not mark ${post.id} posted: ${(e as Error).message}`));
    });
  }
  return { ok: true, postId: post.id, adapterId: adapter.id, account, results, video: file.path, cover };
}
