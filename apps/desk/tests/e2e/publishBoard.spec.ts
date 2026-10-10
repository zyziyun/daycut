// Runs the app with the Studio off (DESK_STUDIO=0): the pages before the Studio (2026-10 review step 7) stay
// supported behind its flag, and this spec covers them.
// 发布 board (ux/publish-redesign A), window hidden, mock engine, isolated profile, a work folder with four tiny
// clips and post copy, three publishing accounts (added through the API; nothing opens a platform page):
// create / read / update / delete on the board — an empty slot, drag from the queue, drag a card to another day and
// back to the queue, the drawer (time, platform on / off, caption + counter + "Shorten for X", back to queue + undo),
// one-sentence schedule (preview as dashed cards, then Apply), Fill my week (+ undo), Confirm, month and data views.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-pb-'));
const watch = path.join(tmp, 'demos');
const work = path.join(watch, 'fuye');
const CLIPS = ['A_换圈子', 'B_自媒体', 'C_底气', 'D_反哺'];
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const monday = (weeks: number) => {
  const d = new Date();
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7) + weeks * 7);
  return d;
};
const dayOf = (weeks: number, k: number) => {
  const d = monday(weeks);
  d.setDate(d.getDate() + k);
  return iso(d);
};

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const fin = path.join(work, 'final');
  fs.mkdirSync(fin, { recursive: true });
  let md = '# 发布文案\n\n';
  for (const n of CLIPS) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x240:rate=30:duration=2', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(fin, `${n}.mp4`)]);
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', path.join(fin, `${n}.mp4`), '-frames:v', '1', path.join(fin, `${n}_cover.jpg`)]);
    md += `## ${n}.mp4  ·  封面 ${n}_cover.jpg\n\n${n} 的标题\n\n正文。\n\n#副业\n\n`;
  }
  fs.writeFileSync(path.join(fin, 'post.md'), md);
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_STUDIO: '0', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    for (const a of ['xiaohongshu', 'douyin', 'x-web']) await window.desk.publish.addAccount(a, 'main');
    await window.desk.publish.updateChannel('xiaohongshu', 'main', { name: '@me', times: ['20:00'] });
    await window.desk.publish.updateChannel('douyin', 'main', { times: ['12:30'] });
    // the board shows the platforms she chose (Platforms for new projects)
    await window.desk.setSettings({ defaultPlatforms: ['xiaohongshu:full', 'douyin', 'x'] });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const api = <T,>(p: string) =>
  page.evaluate(async (u) => {
    const info = await window.desk.engineInfo();
    return (await fetch(info.baseUrl + u, { headers: { Authorization: `Bearer ${info.token}` } })).json();
  }, p) as Promise<T>;
type Row = { id: string; clip: string; platform: string; at: string; state: string; caption?: string; enabled?: boolean };
const rows = async () => (await api<{ posts: Row[] }>('/api/calendar')).posts;
const card = (clip: string) => page.locator(`[data-testid="pub-post"][data-clip="${clip}"]`);
const day = (d: string) => page.locator(`[data-testid="pub-day"][data-day="${d}"]`);

test('the board reads: queue grouped by project, connected platforms only, next week has free slots', async () => {
  await hash('#/publish');
  await expect(page.getByTestId('pub-week')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('pub-queue-item')).toHaveCount(4, { timeout: 30000 });
  await expect(page.getByTestId('pb-qgroup')).toHaveCount(1);
  await expect(page.getByTestId('pb-qgroup')).toContainText('fuye');
  const row = page.getByTestId('pub-platforms');
  for (const pf of ['xiaohongshu', 'douyin', 'x']) await expect(row.locator(`button[data-pf="${pf}"]`)).toBeVisible();
  await expect(row.locator('button[data-pf="tiktok"]')).toHaveCount(0);
  await page.getByTestId('pb-next').click();
  await expect(page.getByTestId('pb-free')).toHaveCount(7);
  await expect(page.getByTestId('pub-confirm')).toHaveCount(0); // nothing to confirm yet: no primary
});

test('create: an empty slot -> pick a clip -> one card on every connected platform at each account time', async () => {
  await day(dayOf(1, 0)).getByTestId('pb-free').click();
  await expect(page.getByTestId('pb-pick')).toBeVisible();
  await page.getByTestId('pb-pick-item').filter({ hasText: 'A_换圈子' }).click();
  await expect(card('A_换圈子')).toHaveCount(1);
  await expect(card('A_换圈子')).toHaveAttribute('data-platforms', 'x xiaohongshu douyin');
  const r = (await rows()).filter((x) => x.clip === 'A_换圈子');
  expect(r.map((x) => `${x.platform} ${x.at.slice(11)}`).sort()).toEqual(['douyin 12:30', 'x 09:00', 'xiaohongshu 20:00']);
  await expect(card('A_换圈子').locator('.pc-time')).toHaveText('09:00'); // the earliest
  await expect(page.getByTestId('pub-queue-item')).toHaveCount(3);
  await expect(page.getByTestId('pub-confirm')).toContainText('Confirm 1 post');
});

test('create by drag from the queue; update by dragging a card to another day', async () => {
  await page.locator('[data-testid="pub-queue-item"][data-clip="B_自媒体"]').dragTo(day(dayOf(1, 1)));
  await expect(day(dayOf(1, 1)).locator('[data-testid="pub-post"][data-clip="B_自媒体"]')).toBeVisible();
  await card('B_自媒体').dragTo(day(dayOf(1, 3)));
  await expect(day(dayOf(1, 3)).locator('[data-testid="pub-post"][data-clip="B_自媒体"]')).toBeVisible();
  expect((await rows()).filter((x) => x.clip === 'B_自媒体').every((x) => x.at.startsWith(dayOf(1, 3)))).toBe(true);
  await page.getByTestId('toast-undo').last().click(); // undo the move
  await expect(day(dayOf(1, 1)).locator('[data-testid="pub-post"][data-clip="B_自媒体"]')).toBeVisible();
});

test('the drawer: time, platform off / on, caption with the counter, Shorten for X', async () => {
  await card('B_自媒体').locator('.pc-top').click(); // the time row opens the drawer (the cover opens the clip)
  const d = page.getByTestId('pb-drawer');
  await expect(d).toBeVisible();
  await d.getByTestId('pb-time').fill('21:30');
  await expect(card('B_自媒体').locator('.pc-time')).toHaveText('21:30');
  expect((await rows()).filter((x) => x.clip === 'B_自媒体').every((x) => x.at.endsWith('21:30'))).toBe(true);
  // X off, then on again
  await d.locator('[data-testid="pb-where"][data-pf="x"] [data-testid="pb-where-toggle"]').click();
  await expect(card('B_自媒体')).toHaveAttribute('data-platforms', 'xiaohongshu douyin');
  await d.locator('[data-testid="pb-where"][data-pf="x"] [data-testid="pb-where-toggle"]').click();
  await expect(card('B_自媒体')).toHaveAttribute('data-platforms', 'x xiaohongshu douyin');
  // a caption too long for X: counted CJK = 2, marked, a warning on the card, then shortened
  await d.locator('[data-testid="pb-ctab"][data-pf="x"]').click();
  await d.getByTestId('pb-caption').fill('再小的博主也是博主。'.repeat(20));
  await expect(d.getByTestId('pb-counter')).toContainText('400 / 280');
  await expect(card('B_自媒体').getByTestId('pb-warn')).toHaveAttribute('data-kind', 'caption_too_long', { timeout: 10000 });
  await expect(page.getByTestId('pb-look')).toContainText('1 needs a look');
  await d.getByTestId('pb-shorten').click();
  await expect(card('B_自媒体').getByTestId('pb-warn')).toHaveCount(0, { timeout: 10000 });
  const x = (await rows()).find((r) => r.clip === 'B_自媒体' && r.platform === 'x')!;
  expect(x.caption!.length).toBeLessThanOrEqual(140);
  expect(x.caption!.startsWith('再小的博主也是博主。')).toBe(true);
  await d.getByTestId('pb-done').click();
  await expect(d).toHaveCount(0);
});

test('delete: back to queue from the drawer (files untouched) + undo; drag a card back to the queue', async () => {
  const files = fs.readdirSync(path.join(work, 'final')).sort();
  await card('B_自媒体').locator('.pc-top').click(); // the time row opens the drawer (the cover opens the clip)
  await page.getByTestId('pb-back').click();
  await expect(card('B_自媒体')).toHaveCount(0);
  await expect(page.locator('[data-testid="pub-queue-item"][data-clip="B_自媒体"]')).toBeVisible();
  expect(fs.readdirSync(path.join(work, 'final')).sort()).toEqual(files);
  await page.getByTestId('toast-undo').last().click();
  await expect(card('B_自媒体')).toHaveCount(1);
  expect((await rows()).find((r) => r.clip === 'B_自媒体' && r.platform === 'x')!.caption!.startsWith('再小的博主')).toBe(true); // her text came back
  await card('B_自媒体').dragTo(page.getByTestId('pub-queue'));
  await expect(card('B_自媒体')).toHaveCount(0);
  await expect(page.locator('[data-testid="pub-queue-item"][data-clip="B_自媒体"]')).toBeVisible();
});

test('Fill my week fills the free days in one step, and one undo removes them', async () => {
  await page.getByTestId('pb-next').click(); // week +2: all free
  await expect(page.getByTestId('pb-free')).toHaveCount(7);
  await page.getByTestId('pub-ai').click();
  await expect(page.getByTestId('pub-post')).toHaveCount(3); // three clips left in the queue
  await expect(page.getByTestId('pub-queue-item')).toHaveCount(0);
  await page.getByTestId('toast-undo').last().click();
  await expect(page.getByTestId('pub-post')).toHaveCount(0);
  await expect(page.getByTestId('pub-queue-item')).toHaveCount(3);
  await page.getByTestId('pb-prev').click();
});

test('one sentence: preview as dashed cards (nothing written, Apply is the only primary), then Apply', async () => {
  const before = (await rows()).length;
  await page.getByTestId('pb-nl-input').fill('下周每天晚上8点发一条小红书，周末不发');
  await page.getByTestId('pb-nl-input').press('Enter');
  await expect(page.getByTestId('pb-nl-plan')).toHaveAttribute('data-ok', '1');
  await expect(page.getByTestId('pb-nl-summary')).toContainText('3 new posts on Xiaohongshu · Mon–Fri at 20:00 · weekends off');
  await expect(page.getByTestId('pb-proposed')).toHaveCount(3);
  await expect(page.getByTestId('pub-confirm')).toHaveCount(0);
  expect((await rows()).length).toBe(before);
  await page.getByTestId('pb-nl-apply').click();
  await expect(page.getByTestId('pb-proposed')).toHaveCount(0);
  const mine = (await rows()).filter((r) => r.at.slice(11) === '20:00' && r.platform === 'xiaohongshu' && r.clip !== 'A_换圈子');
  expect(mine.length).toBe(3);
  await expect(page.getByTestId('pub-queue-item')).toHaveCount(0);
  // a sentence it cannot read says so
  await page.getByTestId('pb-nl-input').fill('hmm');
  await page.getByTestId('pb-nl-input').press('Enter');
  await expect(page.getByTestId('pb-nl-error')).toBeVisible();
  await page.getByTestId('pb-nl-cancel').click();
});

test('Confirm n posts -> ready; month view; mark posted + views in Data', async () => {
  await page.getByTestId('pb-today').click();
  await page.getByTestId('pb-next').click();
  const confirm = page.getByTestId('pub-confirm');
  await expect(confirm).toBeVisible();
  await confirm.click();
  await expect(card('A_换圈子').getByTestId('pb-status')).toHaveAttribute('data-status', 'ready');
  await card('A_换圈子').locator('.pc-top').click();
  await page.getByTestId('pb-mark-posted').click();
  await expect(card('A_换圈子').getByTestId('pb-status')).toHaveAttribute('data-status', 'posted');
  await page.getByTestId('pb-drawer-close').click();
  await page.getByTestId('pb-view').locator('[data-v="month"]').click();
  await expect(page.getByTestId('pub-month')).toBeVisible();
  await page.getByTestId('pb-view').locator('[data-v="data"]').click();
  await expect(page.getByTestId('pb-data-row')).toHaveCount(1);
  await page.getByTestId('pb-views').click();
  await page.getByTestId('pb-views-input').fill('1204');
  await page.getByTestId('pb-views-input').press('Enter');
  await expect(page.getByTestId('pb-views')).toHaveText('1,204');
  expect((await rows()).some((r) => r.clip === 'A_换圈子' && (r as Row & { stats?: { views?: number } }).stats?.views === 1204)).toBe(true);
  const missing = await page.evaluate(() => document.body.innerText.match(/⟦[^⟧]+⟧/g));
  expect(missing).toBeNull();
  await page.getByTestId('pb-view').locator('[data-v="week"]').click();
});
