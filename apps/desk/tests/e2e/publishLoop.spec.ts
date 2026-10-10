// The publish loop end to end in the real app with the REAL engine sidecar (no mock engine), an isolated temp
// profile, window hidden. Only the network is faked: the 小红书 account's own session partition answers
// https://creator.xiaohongshu.com from the local mock page (tests/e2e/fixture/mocks/xiaohongshu.html) - the app's
// code (adapter, scheduler, notification, fill over CDP, success watch, cookie login check) runs as shipped.
//   - login state from the account's session cookie (any page of the platform), Douyin she does not use: no nag
//   - the drawer: only her platforms in Where (+ Add platform), the title edited inline, 小红书's 20-char counter
//   - a post whose time has passed: overdue on launch (banner), one "Time to post" notification; clicking it opens
//     the post page, which fills the upload form by itself; her click on 发布 -> posted (via assisted)
//   - Settings: Open at login, YouTube API (not connected), TikTok / X / Instagram documented as not yet
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-loop-'));
const watch = path.join(tmp, 'demos');
const work = path.join(watch, 'fuye');
const SHOTS = process.env.PUBTEST_SHOTS || path.join(tmp, 'shots');
const MOCKS = path.resolve(import.meta.dirname, 'fixture/mocks');
const pad = (n: number) => String(n).padStart(2, '0');
const at = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const fin = path.join(work, 'final');
  fs.mkdirSync(fin, { recursive: true });
  let md = '# 发布文案\n\n';
  for (const n of ['A_小博主', 'B_自媒体']) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x240:rate=30:duration=2', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(fin, `${n}.mp4`)]);
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', path.join(fin, `${n}.mp4`), '-frames:v', '1', path.join(fin, `${n}_cover.jpg`)]);
    md += `## ${n}.mp4  ·  封面 ${n}_cover.jpg\n\n${n} 的标题\n\n副业对我最大的价值，是链接到主业里遇不到的人。\n\n#副业 #自媒体\n\n`;
  }
  fs.writeFileSync(path.join(fin, 'post.md'), md);
  // the real engine sidecar: no DESK_ENGINE_MOCK
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  // record notifications instead of showing them (and keep them so the test can click one)
  await app.evaluate(({ Notification }) => {
    const g = globalThis as unknown as { __notes: { title: string; body: string; n: unknown }[] };
    g.__notes = [];
    Notification.prototype.show = function (this: Electron.Notification) {
      g.__notes.push({ title: this.title, body: this.body, n: this });
    };
  });
  // the 小红书 account's partition reaches the local mock instead of the internet (test-side interception only)
  await app.evaluate(async ({ session }, mocks) => {
    const fsm = process.mainModule!.require('node:fs') as typeof fs;
    const pathm = process.mainModule!.require('node:path') as typeof path;
    const ses = session.fromPartition('persist:xiaohongshu-main');
    ses.protocol.handle('https', (req) => {
      const u = new URL(req.url);
      if (u.hostname !== 'creator.xiaohongshu.com') return new Response('offline in tests', { status: 404 });
      const file = u.pathname.endsWith('_common.js') ? '_common.js' : 'xiaohongshu.html';
      return new Response(fsm.readFileSync(pathm.join(mocks, file)), { headers: { 'content-type': file.endsWith('.js') ? 'text/javascript' : 'text/html; charset=utf-8' } });
    });
    const dy = session.fromPartition('persist:douyin-main');
    dy.protocol.handle('https', () => new Response('offline in tests', { status: 404 }));
  }, MOCKS);
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.publish.addAccount('xiaohongshu', 'main');
    await window.desk.publish.addAccount('douyin', 'main'); // added once, not one of her platforms
    await window.desk.setSettings({ defaultPlatforms: ['xiaohongshu:full'] });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  const info = await page.evaluate(() => window.desk.engineInfo());
  expect(info.mode).toBe('real');
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const api = <T,>(p: string, body?: unknown) =>
  page.evaluate(
    async ([u, b]) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + u, { method: b ? 'POST' : 'GET', headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' }, body: b ? JSON.stringify(b) : undefined });
      return r.json();
    },
    [p, body] as const,
  ) as Promise<T>;
type Row = { id: string; clip: string; platform: string; at: string; state: string; title: string; via?: string; title_custom?: boolean };
const rows = async () => (await api<{ posts: Row[] }>('/api/calendar')).posts;
let item = '';

test('login state comes from the account’s session: signed in on any page; Douyin she does not use never nags', async () => {
  await hash('#/settings/accounts');
  await expect(page.getByTestId('settings-channels')).toBeVisible({ timeout: 30000 });
  await expect(page.locator('[data-testid="settings-channel"][data-adapter="xiaohongshu"] [data-testid="channel-state"]')).toHaveAttribute('data-state', 'out');
  // she signs in inside the built-in browser: the platform sets its session cookie in that account's partition
  await app.evaluate(async ({ session }) => {
    await session.fromPartition('persist:xiaohongshu-main').cookies.set({ url: 'https://creator.xiaohongshu.com', name: 'galaxy_creator_session_id', value: 'test-session', domain: '.xiaohongshu.com', expirationDate: Date.now() / 1000 + 86400 });
  });
  await page.waitForTimeout(5200); // the accounts list re-checks at most every 5 s
  await hash('#/settings/general');
  await hash('#/settings/accounts');
  await expect(page.locator('[data-testid="settings-channel"][data-adapter="xiaohongshu"] [data-testid="channel-state"]')).toHaveAttribute('data-state', 'in', { timeout: 15000 });
  await expect(page.locator('[data-testid="settings-channel"][data-adapter="douyin"]')).toHaveAttribute('data-in-use', 'false');
  await expect(page.getByTestId('settings-signed-count')).toHaveText('1 of 1 signed in');
  await page.screenshot({ path: path.join(SHOTS, 'settings-accounts.png') });
  await hash('#/settings/general');
  await expect(page.getByTestId('settings-status')).toBeVisible();
  await expect(page.getByTestId('settings-status')).not.toContainText(/Douyin|signed out/);
});

test('the drawer: only her platforms in Where, the title edited inline with 小红书’s counter', async () => {
  const hist = await api<{ items: { id: string; dir: string }[] }>('/api/history');
  item = hist.items.find((i) => i.dir === work)!.id;
  const tomorrow = new Date(Date.now() + 86400_000);
  tomorrow.setHours(20, 0, 0, 0);
  await api('/api/calendar/many', { posts: [{ item, clip: 'B_自媒体', platform: 'xiaohongshu', at: at(tomorrow) }] });
  await hash('#/publish');
  const card = page.locator('[data-testid="pub-post"][data-clip="B_自媒体"]');
  if (tomorrow.getDay() === 1) await page.getByTestId('pb-next').click(); // tomorrow is next week's Monday
  await card.locator('.pc-top').click(); // the time row opens the drawer (the cover opens the clip)
  const d = page.getByTestId('pb-drawer');
  await expect(d.getByTestId('pb-where')).toHaveCount(1);
  await expect(d.locator('[data-testid="pb-where"][data-pf="douyin"]')).toHaveCount(0);
  await expect(d.getByTestId('pb-where-add')).toBeVisible();
  await d.getByTestId('pb-title').fill('再小的博主，也是博主');
  await d.getByTestId('pb-title').press('Enter');
  await expect.poll(async () => (await rows()).find((r) => r.clip === 'B_自媒体')?.title).toBe('再小的博主，也是博主');
  await expect(d.locator('[data-testid="pb-title-counts"] > span[data-pf="xiaohongshu"]')).toContainText('10/20');
  // 小红书's own title: too long is marked, not cut. It starts from the card title once the board has the saved one
  // (the field is keyed on it: typing before that refresh lands would be reset, which a slow runner hits)
  await expect(d.getByTestId('pb-post-title')).toHaveValue('再小的博主，也是博主');
  await d.getByTestId('pb-post-title').fill('再小的博主也是博主再小的博主也是博主再小的博主');
  await d.getByTestId('pb-post-title').press('Enter');
  await expect(d.getByTestId('pb-title-counter')).toContainText('23 / 20');
  await expect.poll(async () => (await rows()).find((r) => r.clip === 'B_自媒体')?.title_custom).toBe(true);
  await page.screenshot({ path: path.join(SHOTS, 'drawer-title.png') });
  await d.getByTestId('pb-title-reset').click();
  await expect.poll(async () => (await rows()).find((r) => r.clip === 'B_自媒体')?.title).toBe('再小的博主，也是博主');
  await d.getByTestId('pb-done').click();
});

test('one title per clip: the AI’s title by default; renamed in the editor header -> the drawer follows', async () => {
  // the clip's title is the AI-written post title, not the file name, and the text does not repeat it
  const clip = (await api<{ clips: { id: string; title: string }[] }>(`/api/outputs/${item}`)).clips.find((c) => c.id === 'B_自媒体')!;
  expect(clip.title).toBe('再小的博主，也是博主'); // the card title edit above renamed the clip itself
  await api(`/api/outputs/${item}/${encodeURIComponent('B_自媒体')}/title`, { title: null });
  const ai = (await api<{ clips: { id: string; title: string }[] }>(`/api/outputs/${item}`)).clips.find((c) => c.id === 'B_自媒体')!;
  expect(ai.title).toBe('B_自媒体 的标题');
  const row = (await api<{ posts: (Row & { caption: string })[] }>('/api/calendar')).posts.find((r) => r.clip === 'B_自媒体')!;
  expect(row.title).toBe('B_自媒体 的标题');
  expect(row.caption.startsWith('副业对我最大的价值')).toBe(true); // 小红书 has a title field: not the text's 1st line

  await hash(`#/p/${item}/clip/${encodeURIComponent('B_自媒体')}`);
  await expect(page.getByTestId('editor-title')).toHaveText('B_自媒体 的标题', { timeout: 30000 });
  await page.getByTestId('editor-title-edit').click();
  await page.getByTestId('editor-title-input').fill('一次录完，一周的内容');
  await page.getByTestId('editor-title-input').press('Enter');
  await expect(page.getByTestId('editor-title')).toHaveText('一次录完，一周的内容');
  await expect.poll(async () => (await rows()).find((r) => r.clip === 'B_自媒体')?.title).toBe('一次录完，一周的内容');
  await page.screenshot({ path: path.join(SHOTS, 'editor-title.png') });

  await hash('#/publish');
  const tomorrow = new Date(Date.now() + 86400_000);
  if (tomorrow.getDay() === 1) await page.getByTestId('pb-next').click();
  const card = page.locator('[data-testid="pub-post"][data-clip="B_自媒体"]');
  await expect(card.locator('.pc-title')).toHaveText('一次录完，一周的内容');
  await card.locator('.pc-top').click();
  const d = page.getByTestId('pb-drawer');
  await expect(d.getByTestId('pb-title')).toHaveValue('一次录完，一周的内容');
  await expect(d.getByTestId('pb-post-title')).toHaveValue('一次录完，一周的内容'); // no own 小红书 title: it follows
  await page.screenshot({ path: path.join(SHOTS, 'drawer-follows-title.png') });
  await d.getByTestId('pb-done').click();
});

test('time to post: overdue banner, one notification, click -> the form fills itself; her 发布 click -> posted', async () => {
  const due = new Date(Date.now() - 3 * 60_000);
  const r = await api<{ ids: string[] }>('/api/calendar/many', { posts: [{ item, clip: 'A_小博主', platform: 'xiaohongshu', at: at(due) }] });
  const id = r.ids[0];
  await api(`/api/calendar/${id}`, { title: '再小的博主，也是博主' });
  await hash('#/publish');
  await page.evaluate(() => window.desk.publish.due()); // the scheduler's tick (also runs every 30 s)
  await expect(page.getByTestId('due-banner')).toBeVisible({ timeout: 15000 });
  await expect(page.locator(`[data-testid="due-row"][data-post="${id}"]`)).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, 'due-banner.png') });
  const notes = await app.evaluate(() => (globalThis as unknown as { __notes: { title: string; body: string }[] }).__notes.map((n) => ({ title: n.title, body: n.body })));
  expect(notes).toEqual([{ title: 'Time to post: 再小的博主，也是博主 → Xiaohongshu', body: expect.stringContaining('You press Publish') }]);
  await page.evaluate(() => window.desk.publish.due());
  expect(await app.evaluate(() => (globalThis as unknown as { __notes: unknown[] }).__notes.length)).toBe(1); // once

  // she clicks the notification
  await app.evaluate(() => ((globalThis as unknown as { __notes: { n: { emit: (e: string) => void } }[] }).__notes[0].n.emit('click')));
  await expect(page).toHaveURL(new RegExp(`#/publish/post/${id}`));
  const pn = page.getByTestId('post-now');
  await expect(pn).toHaveAttribute('data-phase', 'filled', { timeout: 60000 });
  await expect(page.locator('[data-testid="post-steps"] li')).toHaveCount(4);
  for (const f of ['file', 'title', 'description', 'publish']) await expect(page.locator(`[data-testid="post-steps"] li[data-field="${f}"]`)).toHaveAttribute('data-status', 'ok');
  expect((await rows()).find((x) => x.id === id)?.state).toBe('filled');
  // what the platform page holds now (the account's view): the video made for 小红书, the title, the text, nothing clicked
  const state = await app.evaluate(async ({ webContents }) => {
    const wc = webContents.getAllWebContents().find((w) => w.getURL().startsWith('https://creator.xiaohongshu.com/'))!;
    return wc.executeJavaScript('window.__state()');
  });
  expect(state).toMatchObject({ file: 'A_小博主.mp4', title: '再小的博主，也是博主', clicked: false, sideClicked: false });
  expect(String(state.desc)).toContain('副业对我最大的价值');
  expect(String(state.desc)).not.toContain('再小的博主，也是博主');
  expect(String(state.outline)).toContain('solid');
  await page.screenshot({ path: path.join(SHOTS, 'post-now-filled.png') });
  const shot = await app.evaluate(async ({ webContents }) => {
    const wc = webContents.getAllWebContents().find((w) => w.getURL().startsWith('https://creator.xiaohongshu.com/'))!;
    return (await wc.capturePage()).toPNG().toString('base64');
  });
  fs.writeFileSync(path.join(SHOTS, 'post-now-platform-view.png'), Buffer.from(shot, 'base64'));

  // she presses 发布 herself; the page says 发布成功 -> posted
  await app.evaluate(async ({ webContents }) => {
    const wc = webContents.getAllWebContents().find((w) => w.getURL().startsWith('https://creator.xiaohongshu.com/'))!;
    await wc.executeJavaScript(`document.querySelector('.x9a1-red').click()`);
  });
  await expect(pn).toHaveAttribute('data-phase', 'posted', { timeout: 15000 });
  await expect.poll(async () => (await rows()).find((x) => x.id === id)).toMatchObject({ state: 'posted', via: 'assisted' });
  await page.screenshot({ path: path.join(SHOTS, 'post-now-posted.png') });
  await hash('#/publish');
  await page.evaluate(() => window.desk.publish.due());
  await expect(page.getByTestId('due-banner')).toHaveCount(0);
});

test('a signed-out account: the fill stops and asks her to sign in (no fake success)', async () => {
  const due = new Date(Date.now() - 60_000);
  await app.evaluate(async ({ session }) => {
    await session.fromPartition('persist:xiaohongshu-main').cookies.remove('https://creator.xiaohongshu.com', 'galaxy_creator_session_id');
  });
  const r = await api<{ ids: string[] }>('/api/calendar/many', { posts: [{ item, clip: 'B_自媒体', platform: 'xiaohongshu', at: at(due) }] });
  const out = await page.evaluate((pid) => window.desk.publish.fillPost(pid), r.ids[0]);
  expect(out).toMatchObject({ ok: false, reason: 'login-required', adapterId: 'xiaohongshu' });
  expect((await rows()).find((x) => x.id === r.ids[0])?.state).toBe('planned');
});

test('Settings: Open at login; YouTube API needs her OAuth client; TikTok / X / Instagram not yet', async () => {
  await hash('#/settings/accounts');
  await expect(page.getByTestId('open-at-login')).toBeVisible();
  await expect(page.getByTestId('api-youtube-client')).toBeVisible();
  for (const id of ['tiktok', 'x', 'instagram']) await expect(page.getByTestId(`api-${id}`)).toContainText('Not yet');
  await page.getByTestId('api-youtube-client').click();
  await expect(page.getByTestId('api-client-sheet')).toBeVisible();
  await page.screenshot({ path: path.join(SHOTS, 'settings-api.png') });
  await page.keyboard.press('Escape');
  await page.getByTestId('open-at-login').click();
  expect((await page.evaluate(() => window.desk.getSettings())).openAtLogin).toBe(true);
});
