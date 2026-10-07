// v0.2 release fixes (review/REVIEW.md §4), mock engine, hidden window, isolated profile:
//   - planning shows the elapsed time and can be stopped;
//   - a pilot that fails (expired Claude Code login in segment planning) is visible: red status + plain reason on
//     the project, an inbox item with 去登录 / 换 Codex 重试, a Failed count in All projects; the retry runs;
//   - the French UI: first run and the main screens render with no missing keys.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-release-'));
const SHOTS = process.env.DESK_SHOTS_DIR; // optional: screenshots of the fixed screens

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_MOCK_STEP: '0.05',
      DESK_MOCK_PLAN_DELAY: '3',
      DESK_MOCK_PILOT_FAIL: 'auth',
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
  await page.evaluate(() => localStorage.setItem('i18n.strict', '1'));
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const shot = async (name: string) => {
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
};

test('planning: elapsed time and a stop button; stop returns to the composer', async () => {
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('composer-input').fill('把这条成片切成小红书切片');
  await page.getByTestId('make-plan').click();
  await expect(page.getByTestId('plan-stop')).toBeVisible({ timeout: 10000 });
  await expect(page.getByTestId('plan-elapsed')).toHaveText(/0:0[1-9]/, { timeout: 5000 });
  await shot('02-planning-elapsed-stop');
  await page.getByTestId('plan-stop').click();
  await expect(page.getByTestId('plan-card')).toHaveCount(0);
  await expect(page.getByTestId('composer-input')).toBeVisible();
});

test('a failed pilot is visible: project, inbox, all projects; retry with Codex runs', async () => {
  test.setTimeout(90000);
  await page.getByTestId('composer-input').fill('把这条成片切成 3 条小红书切片');
  await page.getByTestId('make-plan').click();
  await page.getByTestId('plan-start').click({ timeout: 30000 });
  await expect(page.getByTestId('project-title')).toBeVisible({ timeout: 30000 });

  // project page: red status word + the reason in her words (never the raw 401 / path) + what to do
  const banner = page.getByTestId('project-failed');
  await expect(banner).toBeVisible({ timeout: 30000 });
  await expect(banner).toContainText(/signed out|login expired|登录过期/i);
  await expect(banner).not.toContainText(/401|API Error|\/Users\//);
  await expect(page.locator('.ph [data-testid="status"]')).toHaveAttribute('data-status', 'error');
  await expect(banner.getByTestId('fail-login')).toBeVisible();
  await expect(banner.getByTestId('fail-retry-other')).toContainText('Codex');
  await shot('04-project-failed');

  // inbox: the failure comes first, with the same actions
  await page.getByTestId('nav-inbox').click();
  const item = page.locator('[data-testid="inbox-item"][data-kind="failed"]');
  await expect(item).toHaveCount(1, { timeout: 15000 });
  await expect(page.getByTestId('inbox-item').first()).toHaveAttribute('data-kind', 'failed');
  await expect(item.getByTestId('inbox-failed-reason')).toBeVisible();
  await item.click();
  const pv = page.getByTestId('inbox-preview');
  await expect(pv).toHaveAttribute('data-kind', 'failed');
  await expect(pv.getByTestId('fail-login')).toBeVisible();
  await expect(pv.getByTestId('fail-retry-other')).toBeVisible();
  await shot('03-inbox-failed');

  // all projects: a Failed count
  await page.getByTestId('nav-projects').click();
  await expect(page.getByTestId('projects-filter')).toContainText(/Failed 1|失败 1/);
  await shot('05-projects-failed-count');

  // 换 Codex 重试 from the inbox: the pilot runs again and reaches "needs you"; the failure is gone
  await page.getByTestId('nav-inbox').click();
  await item.click();
  await page.getByTestId('inbox-preview').getByTestId('fail-retry-other').click();
  await expect(page.locator('[data-testid="inbox-item"][data-kind="failed"]')).toHaveCount(0, { timeout: 30000 });
  await page.getByTestId('nav-projects').click();
  await expect(page.getByTestId('projects-filter')).not.toContainText(/Failed|失败/, { timeout: 30000 });
});

test('French: the first-run wizard and the main screens have every message', async () => {
  await page.evaluate(async () => {
    await window.desk.setSettings({ lang: 'fr' });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('engine-status')).toBeVisible({ timeout: 30000 });
  for (const h of ['#/', '#/inbox', '#/projects', '#/publish', '#/settings', '#/settings/ai', '#/welcome']) {
    await hash(h);
    await page.waitForTimeout(700);
    const text = await page.evaluate(() => document.body.innerText);
    expect(text.match(/⟦[^⟧]+⟧/g) ?? [], h).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.lang)).toBe('fr');
  }
  await expect(page.getByTestId('first-run')).toBeVisible();
  await expect(page.getByTestId('first-run')).toContainText('Bienvenue');
  await shot('06-firstrun-fr');
  await page.getByTestId('fr-next').click();
  await expect(page.getByTestId('fr-ai')).toContainText(/abonnement/i);
  await shot('06b-firstrun-fr-ai');
  await page.getByTestId('fr-skip').click();
  await page.evaluate(async () => {
    await window.desk.setSettings({ lang: 'en' });
  });
});
