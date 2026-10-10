// The Studio (2026-10 review steps 6-8), window hidden, mock engine (desk implementation), isolated profile, the Studio
// flag on (DESK_STUDIO=1): one list of every video (needs you / in progress / ready / scheduled; filters; dots, where
// each one is, time left) and the selected video's one page (layout A); the old pages land in it; ↑ ↓ and ⌘1–9
// switch; ⌘N starts a new video; the AI bar. Screenshots go to test-results/studio.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
let fuyeId = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-studio-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');
const SHOTS = process.env.DESK_SHOTS_DIR ?? path.resolve(import.meta.dirname, '../../test-results/studio');
fs.mkdirSync(SHOTS, { recursive: true });

const PICKS = `# PICKS

| # | Source span | Len | Title (小红书 units) | Why | Opening line (hook) |
|---|---|---|---|---|---|
| A 换圈子 | 7:30 | 1:24 | 同一个行业待越久，思路越窄 (13) | x | y |
| C 底气 | 5:01 | 0:50 | 副业给我的不是钱，是底气 (12) | x | y |

## Edits inside the spans (creator should confirm)
- **A** starts at 你在副业当中, skipping 「这也是挺丰富人生的一个事情」.
- **C** drops the hedge 「或者说也可能是」.
`;

function ffmpeg(args: string[]) {
  execFileSync('ffmpeg', ['-v', 'error', '-y', ...args]);
}

function heartbeat(dir: string, rec: Record<string, unknown> = {}) {
  fs.mkdirSync(path.join(dir, '.vstudio'), { recursive: true });
  const now = Date.now() / 1000;
  fs.writeFileSync(path.join(dir, '.vstudio', 'status.json'), JSON.stringify({ status: 'running', stage: 'render', progress: 0.42, message: 'Cutting clip 3 of 6', eta: 360, started: now - 90, heartbeat: now, pid: process.pid, host: os.hostname(), updated_by: 'workflow', ...rec }));
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(path.join(fuye, 'final'), { recursive: true });
  const lavfi = (d: number) => ['-f', 'lavfi', '-i', `testsrc2=size=240x320:rate=30:duration=${d}`, '-f', 'lavfi', '-i', `sine=frequency=330:duration=${d}`, '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'];
  const clips = ['A_换圈子', 'B_自媒体', 'C_底气'];
  for (const c of clips) {
    ffmpeg([...lavfi(6), path.join(fuye, 'final', `${c}.mp4`)]);
    ffmpeg(['-i', path.join(fuye, 'final', `${c}.mp4`), '-ss', '1', '-frames:v', '1', path.join(fuye, 'final', `${c}_cover.jpg`)]);
  }
  const W = [
    { word: '你在', start: 0.3, end: 0.7 },
    { word: '副业', start: 0.7, end: 1.1 },
    { word: '当中，', start: 1.1, end: 1.5 },
    { word: '其实', start: 2.2, end: 2.6 },
    { word: '是', start: 2.6, end: 2.8 },
    { word: '底气。', start: 2.8, end: 3.4 },
  ];
  fs.writeFileSync(path.join(fuye, 'final', 'A_换圈子.mp4.asr.json'), JSON.stringify({ segments: [{ start: 0.3, end: 3.4, words: W }] }));
  fs.writeFileSync(path.join(fuye, 'final', 'post.md'), clips.map((c, i) => `## ${c}.mp4  ·  封面 ${c}_cover.jpg\n\n${['同一个行业待越久，思路越窄', '再小的博主，也是博主', '副业给我的不是钱，是底气'][i]}\n\n正文。\n\n#副业\n`).join('\n'));
  fs.writeFileSync(path.join(fuye, 'PICKS.md'), PICKS);
  const live = path.join(watch, 'AI short');
  fs.mkdirSync(path.join(live, 'final'), { recursive: true });
  fs.writeFileSync(path.join(live, 'REPORT.md'), '# AI short\n');
  heartbeat(live, { message: 'Making shots 4 of 12' });
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_STUDIO: '1', DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.setSettings({ lang: 'en', theme: 'studio-dark', defaultPlatforms: ['youtube', 'tiktok', 'xiaohongshu'] });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
  fuyeId = await api<string>(async ({ base, auth }) => {
    for (let i = 0; i < 60; i++) {
      const h = await (await fetch(base + '/api/history', { headers: auth })).json();
      const it = (h.items as { id: string; name: string }[]).find((x) => x.name === 'fuye');
      if (it) return it.id;
      await new Promise((r) => setTimeout(r, 500));
    }
    return '';
  });
  expect(fuyeId).toMatch(/^[0-9a-f]{12}$/);
});

test.afterAll(async () => {
  await closeApp(app);
});

async function api<T, A = undefined>(fn: (o: { base: string; auth: Record<string, string>; arg: A }) => Promise<T>, arg?: A): Promise<T> {
  const info = await page.evaluate(() => window.desk.engineInfo());
  const o = { base: info.baseUrl, auth: { Authorization: `Bearer ${info.token}` } as Record<string, string>, arg: arg as A };
  return page.evaluate(fn as (o: unknown) => Promise<T>, o);
}
const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const shot = async (name: string) => {
  await page.waitForTimeout(260);
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};
async function noMissingKeys() {
  const text = await page.evaluate(() => document.body.innerText);
  expect(text.match(/⟦[^⟧]+⟧/g) ?? []).toEqual([]);
  expect(text.match(/\b(st|ci|hub|te|inbox)\.[a-zA-Z][\w.-]+/g) ?? []).toEqual([]);
}

test('the Studio is where the app opens: every video in one list, grouped; what needs her first, open on the right', async () => {
  await hash('#/');
  await expect(page.getByTestId('studio')).toBeVisible({ timeout: 30000 });
  await expect(page).toHaveURL(/#\/studio/);
  await expect(page.getByTestId('nav-studio')).toHaveAttribute('aria-current', 'page');
  await expect(page.getByTestId('nav-home')).toHaveCount(0);
  await expect(page.getByTestId('nav-inbox')).toHaveCount(0);
  await expect(page.getByTestId('nav-projects')).toHaveCount(0);
  const rows = page.getByTestId('studio-row');
  await expect(rows.first()).toBeVisible({ timeout: 30000 });
  await expect(page.locator('[data-testid=studio-row][data-kind=clip]')).toHaveCount(3, { timeout: 30000 }); // one row per clip
  await expect(page.getByTestId('studio-group-you')).toBeVisible();
  await expect(page.getByTestId('studio-group-run')).toContainText('AI short'); // a run with no clips yet: one row
  // nothing chosen: the first row opens
  await expect(page.getByTestId('studio-page')).not.toBeEmpty();
  await noMissingKeys();
  await shot('S1-studio');
});

test('a clip opens as one page: title, player, cover, captions, versions, transcript, post, one AI bar', async () => {
  await page.locator(`[data-testid=studio-row][data-row="${fuyeId}/A_换圈子"]`).click();
  await expect(page).toHaveURL(new RegExp(`#/studio/${fuyeId}/`));
  const ed = page.getByTestId('editor');
  await expect(ed).toHaveAttribute('data-layout', 'studio');
  await expect(page.getByTestId('editor-title')).toHaveText('同一个行业待越久，思路越窄');
  await expect(page.getByTestId('studio-where')).toContainText('fuye');
  await expect(page.getByTestId('ci-covers')).toBeVisible();
  await expect(page.getByTestId('ci-versions')).toBeVisible();
  await expect(page.locator('[data-testid=transcript-body] .w').first()).toHaveText('你在');
  await expect(page.getByTestId('ci-schedule')).toBeVisible();
  await expect(page.getByTestId('studio-ai-input')).toBeVisible();
  await expect(page.getByTestId('chat-panel')).toBeHidden(); // the conversation opens from the bar
  await expect(page.getByTestId('studio-question')).toBeVisible(); // its question sits on the page
  await expect(page.locator('.btn.primary:visible')).toHaveCount(1); // the question's answer is the one filled button
  await expect(page.getByTestId('studio-schedule')).not.toHaveClass(/primary/);
  await noMissingKeys();
  await shot('S2-clip-page');
});

test('filters; the Inbox, All projects and the old editor link land in the Studio', async () => {
  await page.getByTestId('studio-f-you').click();
  for (const g of await page.getByTestId('studio-row').evaluateAll((els) => els.map((e) => e.getAttribute('data-group')))) expect(g).toBe('you');
  await page.getByTestId('studio-f-all').click();
  await hash('#/inbox');
  await expect(page).toHaveURL(/#\/studio\?f=you|#\/studio\//);
  await expect(page.getByTestId('studio-f-you')).toHaveAttribute('aria-selected', 'true');
  await page.getByTestId('studio-f-all').click();
  await hash(`#/p/${fuyeId}/clip/${encodeURIComponent('B_自媒体')}`);
  await expect(page.getByTestId('studio')).toBeVisible();
  await expect(page.getByTestId('editor-title')).toHaveText('再小的博主，也是博主');
  await expect(page.locator(`[data-testid=studio-row][data-row="${fuyeId}/B_自媒体"]`)).toHaveAttribute('aria-current', 'true');
  await hash('#/projects');
  await expect(page.getByTestId('studio')).toBeVisible();
});

test('↑ ↓ and ⌘1–9 switch videos; the page follows', async () => {
  await page.locator(`[data-testid=studio-row][data-row="${fuyeId}/A_换圈子"]`).click();
  await expect(page.getByTestId('editor-title')).toHaveText('同一个行业待越久，思路越窄');
  await page.locator('.st-list').click({ position: { x: 5, y: 5 } }).catch(() => undefined);
  const keys = await page.getByTestId('studio-row').evaluateAll((els) => els.map((e) => e.getAttribute('data-row')));
  const k = keys.indexOf(`${fuyeId}/A_换圈子`);
  await page.keyboard.press('ArrowDown');
  await expect(page.locator(`[data-testid=studio-row][data-row="${keys[k + 1]}"]`)).toHaveAttribute('aria-current', 'true');
  await page.keyboard.press('ArrowUp');
  await expect(page.locator(`[data-testid=studio-row][data-row="${keys[k]}"]`)).toHaveAttribute('aria-current', 'true');
  await page.keyboard.press('ControlOrMeta+1');
  await expect(page.locator(`[data-testid=studio-row][data-row="${keys[0]}"]`)).toHaveAttribute('aria-current', 'true');
});

test('⌘N: a new video from the top of the list; it is a row at once', async () => {
  await page.keyboard.press('ControlOrMeta+n');
  await expect(page.getByTestId('studio-composer')).toBeVisible();
  await page.getByTestId('composer-input').fill('Cut the talk into three clips for Shorts');
  await shot('S3-new-video');
  await page.getByTestId('composer-input').press('ControlOrMeta+Enter');
  await expect(page.getByTestId('studio-composer')).toHaveCount(0, { timeout: 15000 });
  await expect(page.locator('[data-testid=studio-row][data-kind=request], [data-testid=studio-row][data-kind=project]').filter({ hasText: /Cut the talk|three clips/i }).first()).toBeVisible({ timeout: 30000 });
});

test('zh-CN + fr: the Studio and a clip page read in her language', async () => {
  for (const lang of ['zh-CN', 'fr'] as const) {
    await page.evaluate(async (l) => window.desk.setSettings({ lang: l }), lang);
    await hash(`#/studio/${fuyeId}/${encodeURIComponent('A_换圈子')}`);
    await page.reload();
    await expect(page.getByTestId('studio')).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId('editor')).toHaveAttribute('data-layout', 'studio');
    await noMissingKeys();
    await shot(`S4-${lang}`);
  }
  await page.evaluate(async () => window.desk.setSettings({ lang: 'en' }));
});

test('Orca-style attention: the Dock badge is the Needs you count; a new question notifies and opens that clip; ⌘K jumps to any video', async () => {
  test.setTimeout(120000);
  await page.evaluate(async () => window.desk.setSettings({ lang: 'en' }));
  await hash('#/studio?f=all');
  await page.reload();
  await expect(page.getByTestId('studio')).toBeVisible({ timeout: 30000 });
  const youCount = async () => Number((await page.getByTestId('studio-you-count').innerText()).trim());
  await expect.poll(youCount, { timeout: 30000 }).toBeGreaterThan(0);
  if (process.platform === 'darwin') await expect.poll(() => app.evaluate(({ app: a }) => a.getBadgeCount()), { timeout: 15000 }).toBe(await youCount());
  // what the app asks the system to show (the window is hidden in tests: the notification itself is not drawn)
  await app.evaluate(({ ipcMain }) => {
    const g = globalThis as unknown as { __notes: unknown[] };
    g.__notes = [];
    ipcMain.removeHandler('notify:show');
    ipcMain.handle('notify:show', (_e, p) => void g.__notes.push(p));
  });
  // a new project lands with a question about one of its clips
  const two = path.join(watch, 'fuye2');
  fs.cpSync(fuye, two, { recursive: true });
  fs.rmSync(path.join(two, '.vstudio'), { recursive: true, force: true });
  const notes = () => app.evaluate(() => (globalThis as unknown as { __notes: { title: string; route?: string }[] }).__notes);
  await expect.poll(async () => (await notes()).map((n) => n.route ?? ''), { timeout: 60000 }).toContainEqual(expect.stringMatching(/^#\/studio\/[0-9a-f]{12}\/A_%E6%8D%A2%E5%9C%88%E5%AD%90\?item=/));
  const n = (await notes()).find((x) => /\/A_%E6/.test(x.route ?? ''))!;
  expect(n.title).toContain('Needs you');
  // clicking it in the system: main sends the route; the app opens that clip with its question on the page
  await app.evaluate(({ BrowserWindow }, r) => BrowserWindow.getAllWindows()[0].webContents.send('notify:open', { route: r }), n.route!);
  await expect(page.getByTestId('editor')).toHaveAttribute('data-layout', 'studio', { timeout: 15000 });
  await expect(page).toHaveURL(/#\/studio\/[0-9a-f]{12}\/A_/);
  await expect(page.getByTestId('studio-question')).toBeVisible();
  if (process.platform === 'darwin') await expect.poll(() => app.evaluate(({ app: a }) => a.getBadgeCount()), { timeout: 15000 }).toBe(await youCount());
  // ⌘K: every video, by title
  await page.keyboard.press('ControlOrMeta+k');
  await page.getByTestId('palette-input').fill('博主');
  await expect(page.getByTestId('palette-item').filter({ hasText: '再小的博主' }).first()).toBeVisible();
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('editor-title')).toHaveText('再小的博主，也是博主');
  await shot('S5-attention');
});
