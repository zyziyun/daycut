// Autopilot + the control room (window hidden, test engine, isolated profile):
//   Home sends two requests back to back (Home is free again at once) -> both show up in All projects and run side
//   by side to finished clips with no plan to confirm and no question; the Inbox stays empty; the control room shows
//   each one's pipeline, what the AI decided (one decision taken back lands in the Inbox) and its clips (a clip opens
//   the player + editor); a third request waits in line while two run; Settings › "Ask me first" brings the plan to
//   confirm back (Start in the control room, a pilot of one); the Publish board's cards open their clip.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-ap-'));
const recording = path.join(tmp, 'live_1005.mp4');

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', recording]);
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_MOCK_STEP: '0.3',
      DESK_MAX_RUNS: '2',
      DESK_USER_DATA: path.join(tmp, 'profile'),
      VSTUDIO_HOME: path.join(tmp, 'vhome'),
      DESK_HISTORY_WATCH: '',
      DESK_HIDE_WINDOW: '1',
      DESK_SHARED_CACHE: path.join(tmp, 'cache'),
      DESK_HF_HUB: '',
      DESK_SKIP_FIRST_RUN: '1',
      VITE_DEV_SERVER_URL: '',
    },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);

async function send(prompt: string) {
  await page.evaluate((f) => sessionStorage.setItem('v4.composer', JSON.stringify({ prompt: '', files: [f] })), recording);
  await hash('#/inbox');
  await hash('#/');
  await expect(page.getByTestId('composer-files')).toContainText('live_1005.mp4');
  await page.getByTestId('composer-input').fill(prompt);
  await page.getByTestId('make-plan').click();
  // sent: the box is free again at once, the toast says where it went
  await expect(page.getByTestId('composer-input')).toHaveValue('', { timeout: 15000 });
  await expect(page.getByTestId('composer-files')).toHaveCount(0);
  await expect(page.getByTestId('toast').filter({ hasText: prompt.slice(0, 20) })).toBeVisible();
}

test('two requests back to back: both become projects and finish on autopilot with no confirmation', async () => {
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 30000 });
  await send('把这条直播剪成 2 条小红书切片');
  await send('再剪 3 条抖音切片，每条 30 秒');
  await page.getByTestId('nav-projects').click();
  await expect(page.getByTestId('hub')).toBeVisible();
  // (the test engine also lists its own demo batch: only ours are counted)
  const rows = page.getByTestId('hub-row').filter({ hasText: 'live_1005' });
  await expect(rows).toHaveCount(2, { timeout: 30000 });
  // both run side by side (two run slots): at some point both are in Running together
  await expect(page.getByTestId('hub-group-run').getByTestId('hub-row').filter({ hasText: 'live_1005' })).toHaveCount(2, { timeout: 30000 });
  // ... and both reach Ready on their own: no plan card, no Start, no question
  await expect(page.getByTestId('hub-group-ready').getByTestId('hub-row').filter({ hasText: 'live_1005' })).toHaveCount(2, { timeout: 90000 });
  await expect(page.getByTestId('plan-start')).toHaveCount(0);
  await page.getByTestId('nav-inbox').click();
  await expect(page.getByTestId('inbox')).toBeVisible();
  await expect(page.getByTestId('inbox-item').filter({ hasText: 'live_1005' })).toHaveCount(0);
});

test('the control room: pipeline, what the AI decided (take one back -> Inbox), clips open the editor', async () => {
  await page.getByTestId('nav-projects').click();
  const row = page.getByTestId('hub-row').filter({ hasText: 'live_1005 · 3' }).first();
  await row.click();
  const d = page.getByTestId('hub-project');
  await expect(d).toHaveAttribute('data-state', 'ready');
  await expect(page.getByTestId('hub-steps').locator('li[data-state=done]')).toHaveCount(8); // all but "out"
  await expect(page.getByTestId('hub-steps').locator('li[data-step=out]')).toHaveAttribute('data-state', 'todo');
  await expect(page.getByTestId('hub-mode')).toHaveAttribute('data-on', '1');
  const decs = page.getByTestId('hub-decision');
  await expect(decs.first()).toBeVisible();
  await expect(page.getByTestId('hub-decisions')).toContainText('Cut 3 unsure filler words, kept 1');
  await expect(page.getByTestId('hub-decisions')).toContainText('AI · claude-code');
  await expect(page.getByTestId('hub-decisions')).toContainText('Rules');
  await expect(page.getByTestId('hub-clip')).toHaveCount(3);
  // take the cover of clip s01 back: it goes to the Inbox
  await page.locator('[data-testid=hub-decision][data-checkpoint=cover]').first().getByTestId('hub-change').click();
  await expect(page.getByTestId('toast').filter({ hasText: 'Inbox' })).toBeVisible();
  await expect(page.getByTestId('hub-decisions')).toContainText('Waiting for your answer in the Inbox');
  await page.getByTestId('nav-inbox').click();
  await expect(page.getByTestId('inbox-item').filter({ hasText: 'live_1005' })).toHaveCount(1, { timeout: 15000 });
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('hub-row').filter({ hasText: 'live_1005 · 3' }).first().click();
  // a clip opens its own page: player + editor
  await page.getByTestId('hub-clip').first().click();
  await expect(page).toHaveURL(/#\/p\/[0-9a-f]{12}\/clip\//);
  await expect(page.getByTestId('editor')).toBeVisible({ timeout: 30000 });
});

test('three at once: the third waits in line while two run, then runs', async () => {
  test.setTimeout(240000);
  await send('剪 2 条切片 A');
  await send('剪 2 条切片 B');
  await send('剪 2 条切片 C');
  await page.getByTestId('nav-projects').click();
  await expect(page.locator('[data-testid=hub-row][data-state=queued]')).toHaveCount(1, { timeout: 30000 });
  // all three finish (the project whose cover was taken back waits in Needs you: 2 + 3 - 1 ready)
  await expect(page.getByTestId('hub-group-ready').getByTestId('hub-row').filter({ hasText: 'live_1005' })).toHaveCount(4, { timeout: 180000 });
  await expect(page.locator('[data-testid=hub-row][data-state=queued]')).toHaveCount(0);
});

test('Settings › Ask me first: the plan waits in the control room for Start, then a pilot of one', async () => {
  test.setTimeout(180000);
  await hash('#/settings/general');
  await page.getByTestId('mode-ask').click();
  await send('把这条剪成 2 条切片，先问我');
  await page.getByTestId('toast-action').first().click();
  await expect(page.getByTestId('hub-request')).toHaveAttribute('data-mode', 'ask', { timeout: 15000 });
  await expect(page.getByTestId('plan-facts')).toContainText(/2 clips/, { timeout: 30000 });
  // it is a question now: the Inbox says the plan is ready
  await page.getByTestId('nav-inbox').click();
  await expect(page.getByTestId('inbox-item').filter({ hasText: 'Plan ready' })).toHaveCount(1, { timeout: 15000 });
  await page.getByTestId('inbox-item').filter({ hasText: 'Plan ready' }).click();
  await page.getByTestId('nav-projects').click();
  await expect(page.getByTestId('hub-request')).toBeVisible();
  await page.getByTestId('plan-start').click();
  const proj = page.getByTestId('hub-project');
  await expect(proj).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('hub-mode')).toHaveAttribute('data-on', '0');
  // the pilot makes one clip and waits for her look
  await expect(proj).toHaveAttribute('data-state', 'you', { timeout: 60000 });
  // switching it to autopilot finishes it without her
  await page.getByTestId('hub-mode-auto').click();
  await expect(proj).toHaveAttribute('data-state', 'ready', { timeout: 60000 });
  await hash('#/settings/general');
  await page.getByTestId('mode-auto').click();
});

test('Publish: a scheduled card opens its clip; the drawer and the queue do too', async () => {
  await hash('#/projects');
  await page.getByTestId('hub-group-ready').getByTestId('hub-row').first().click();
  await page.getByTestId('hub-schedule').click();
  await expect(page.getByTestId('toast').first()).toBeVisible();
  await page.getByTestId('nav-publish').click();
  // first visit: "Where do you post?" (one account, then back to the board)
  await expect(page.getByTestId('pb-onboarding').or(page.getByTestId('pub-week'))).toBeVisible({ timeout: 15000 });
  if (await page.getByTestId('pb-onboarding').isVisible()) {
    await page.locator('[data-testid="pb-ob-tile"][data-pf="xiaohongshu"]').click();
    await page.getByTestId('pb-ob-continue').click();
    await expect(page).toHaveURL(/#\/publish\/accounts/);
    await hash('#/publish');
  }
  const card = page.getByTestId('pub-post').first();
  await expect(card).toBeVisible({ timeout: 30000 });
  // the drawer (the card's title / time open it): "Open the clip" leads to the clip page
  await card.locator('.pc-title').click();
  await expect(page.getByTestId('pb-drawer')).toBeVisible();
  await page.getByTestId('pb-drawer-clip').click();
  await expect(page).toHaveURL(/#\/p\/[0-9a-f]{12}\/clip\//);
  await page.getByTestId('nav-publish').click();
  // the card's cover opens the clip straight away
  await page.getByTestId('pc-open-clip').first().click();
  await expect(page).toHaveURL(/#\/p\/[0-9a-f]{12}\/clip\//);
  await expect(page.getByTestId('editor')).toBeVisible({ timeout: 30000 });
  // an unscheduled clip in the queue opens its clip too
  await page.getByTestId('nav-publish').click();
  const q = page.getByTestId('pub-queue-item').first();
  if (await q.count()) {
    await q.click();
    await expect(page).toHaveURL(/#\/p\/[0-9a-f]{12}\/clip\//);
  }
});
