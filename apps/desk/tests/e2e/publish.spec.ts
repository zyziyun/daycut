// Runs the app with the Studio off (DESK_STUDIO=0): the pages before the Studio (2026-10 review step 7) stay
// supported behind its flag, and this spec covers them.
// Solo creator first + publishing (window hidden, mock engine, isolated profile, a fuye-like work folder with
// tiny real videos): the top-left is the app name (no workspace / account switcher); clients appear only with
// Settings -> 「我在帮别人做视频」; publishing accounts (name, default times, remove) on 发布 -> 账号; a work
// folder packaged for several platforms (clips x platforms -> files, covers, copy, checks) -> confirm the code ->
// calendar slots -> mark as posted updates the calendar. No platform page is opened (no network).
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-pub-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const fin = path.join(fuye, 'final');
  fs.mkdirSync(fin, { recursive: true });
  const lavfi = (w: number, h: number) => ['-f', 'lavfi', '-i', `testsrc2=size=${w}x${h}:rate=30:duration=4`, '-f', 'lavfi', '-i', 'sine=frequency=440:duration=4', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac'];
  for (const n of ['A_换圈子', 'B_自媒体']) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', ...lavfi(240, 320), path.join(fin, `${n}.mp4`)]);
    execFileSync('ffmpeg', ['-v', 'error', '-y', ...lavfi(180, 320), path.join(fin, `${n}_9x16.mp4`)]);
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-i', path.join(fin, `${n}.mp4`), '-frames:v', '1', path.join(fin, `${n}_cover.jpg`)]);
  }
  fs.writeFileSync(
    path.join(fin, 'post.md'),
    '# 发布文案\n\n## A_换圈子.mp4  ·  封面 A_换圈子_cover.jpg\n\n同一个行业待越久，思路越窄，换个圈子看看\n\n正文第一段。\n\n#副业 #程序员 #自媒体 #职业规划 #个人成长 #认知提升\n\n## B_自媒体.mp4\n\n再小的博主，也是博主\n\n正文。\n\n#自媒体\n',
  );
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_STUDIO: '0', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => sessionStorage.setItem('v4.pview', 'grid')); // All projects as the grid (the control room: autopilot.spec)
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);

test('the top-left is the app, not a workspace; clients only in agency mode', async () => {
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('app-brand')).toContainText('Reelfold');
  await expect(page.getByTestId('workspace')).toHaveCount(0);
  await expect(page.locator('nav.side')).not.toContainText(/My account|自己的账号|Workspace|工作区/);
  await hash('#/projects');
  await expect(page.getByTestId('projects')).toBeVisible();
  await expect(page.getByTestId('projects-client')).toHaveCount(0);
  await hash('#/settings');
  await expect(page.getByTestId('settings-nav')).toBeVisible();
  await expect(page.locator('nav.side')).not.toContainText(/All projects|全部项目/); // Settings has its own sub-nav
  const toggle = page.getByTestId('agency-toggle');
  await expect(toggle).not.toBeChecked();
  await expect(page.getByTestId('open-clients')).toHaveCount(0);
  await toggle.check();
  await expect(page.getByTestId('open-clients')).toBeVisible();
  await page.getByTestId('settings-back').click();
  await expect(page.getByTestId('projects')).toBeVisible(); // back to where she was
  await expect(page.getByTestId('projects-client')).toBeVisible();
  await hash('#/settings');
  await page.getByTestId('agency-toggle').uncheck();
  await expect(page.getByTestId('open-clients')).toHaveCount(0);
  await hash('#/clients'); // without agency mode the clients screen is not reachable
  await expect(page.getByTestId('settings-general')).toBeVisible();
  await hash('#/settings/accounts');
  await expect(page.getByTestId('settings-channels')).toBeVisible();
});

test('publishing accounts: name, default times, login state, remove', async () => {
  // added through the API (the UI's 添加账号 would open the platform's real login page)
  await page.evaluate(async () => {
    await window.desk.publish.addAccount('douyin', 'main');
    await window.desk.publish.addAccount('x-web', 'main');
  });
  await hash('#/publish/accounts');
  await expect(page.getByTestId('channels')).toBeVisible();
  const row = page.locator('[data-testid="channel-platform"][data-adapter="douyin"] [data-testid="channel-row"]');
  await expect(row).toHaveCount(1);
  // no session cookie in the account's own (empty, temp-profile) partition: signed out
  await expect(row.getByTestId('channel-state')).toHaveAttribute('data-state', 'out');
  await row.getByTestId('channel-edit').click();
  await page.getByTestId('channel-name').fill('@我的抖音');
  await page.getByTestId('channel-times').fill('12:30, 20:00');
  await page.getByTestId('channel-save').click();
  await expect(row).toContainText('@我的抖音');
  await expect(row).toContainText('12:30 · 20:00');
  const xrow = page.locator('[data-testid="channel-platform"][data-adapter="x-web"] [data-testid="channel-row"]');
  await xrow.getByTestId('channel-remove').click();
  await page.getByRole('checkbox').uncheck(); // keep the (empty) session; nothing to sign out of in a test
  await page.getByTestId('channel-remove-ok').click();
  await expect(xrow).toHaveCount(0);
  await hash('#/settings/accounts');
  await expect(page.getByTestId('settings-channel')).toContainText('@我的抖音');
  await hash('#/publish');
  await expect(page.getByTestId('pub-accounts')).toBeVisible();
});

test('package a work folder for platforms -> confirm the code -> calendar slots -> mark posted', async () => {
  // the project id from its card link in 全部项目
  await hash('#/projects');
  const card = page.locator('a[data-testid="project-card"]').filter({ hasText: 'fuye' }).first();
  await expect(card).toBeVisible({ timeout: 30000 });
  const item = (await card.getAttribute('href'))!.match(/#\/p\/([0-9a-f]{12})/)![1];
  await hash(`#/b/${item}/publish`);
  const pkg = page.getByTestId('pkg-card');
  await expect(pkg).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('pkg-clip')).toHaveCount(2);
  for (const pf of ['x', 'instagram']) await pkg.locator(`[data-testid="pkg-platform"][data-pf="${pf}"]`).click();
  await pkg.locator('input[type="date"]').fill(iso(new Date()));
  await expect(page.getByTestId('pkg-go')).toContainText(/8/);
  await page.getByTestId('pkg-go').click();
  await expect(page.getByTestId('pub-review-list')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('pub-review-list').click();
  await expect(page.locator('.modal, [role="dialog"]').first()).toContainText('xiaohongshu-vertical');
  await page.getByTestId('pub-confirm-ok').click();
  await expect(page.locator('.page')).toContainText(/8 posts on the calendar|已排进日历 8 条/, { timeout: 30000 });
  // per-platform files: the 9:16 version for 抖音, the 3:4 master for 小红书, copy adapted per platform
  await page.locator('button.tab[data-adapter="douyin"]').click();
  const it = page.locator('[data-testid="pub-item"][data-platform="douyin-vertical"]').first();
  await expect(it).toBeVisible();
  await it.click();
  await expect(page.getByTestId('pkg-item-checks')).toContainText(/AI-content label|AI 生成内容/);
  await page.getByTestId('pub-mark-posted').click();
  await page.getByTestId('pub-posted-ok').click();
  await expect(page.locator('.page')).toContainText(/also on the calendar|日历也同步了/, { timeout: 15000 });
  await expect(it).toContainText(/Posted|已发布/);
  // Instagram: 6 hashtags on a 5-max platform -> a check on the item
  await page.locator('button.tab[data-adapter="instagram"]').click();
  await page.locator('[data-testid="pub-item"][data-job="A_换圈子"]').click();
  await expect(page.getByTestId('pkg-item-checks').locator('[data-code="hashtags-over"]')).toBeVisible();
  // the board: one card per clip per day (2 clips x 4 platforms = 8 rows, 2 cards), the 抖音 row posted
  await hash('#/publish');
  await expect(page.getByTestId('pub-post')).toHaveCount(2, { timeout: 15000 });
  const posts = await page.evaluate(async () => {
    const info = await window.desk.engineInfo();
    return (await (await fetch(info.baseUrl + '/api/calendar', { headers: { Authorization: `Bearer ${info.token}` } })).json()).posts as { platform: string; state: string }[];
  });
  expect(posts).toHaveLength(8);
  expect(posts.some((p) => p.platform === 'douyin' && p.state === 'posted')).toBe(true);
});
