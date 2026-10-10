// No mock in the product (qa/BUGS.md "mock-in-product"): when the planning engine does not answer, "Make a plan"
// says so with Try again and makes nothing (it used to write fake projects and fake pilot results); Try again plans
// for real and the card says how long planning really took. Test engine (DESK_ENGINE_MOCK=1, dev build only),
// hidden window, isolated profile.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-nomock-'));

test.beforeAll(async () => {
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_MOCK_STEP: '0.05',
      DESK_MOCK_PLAN_DELAY: '2.5',
      DESK_MOCK_INTAKE_DOWN: '1',
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

test('the planner did not answer: a clear reason and Try again, nothing made; Try again plans', async () => {
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 30000 });
  await page.evaluate(() => window.desk.setSettings({ autopilot: false })); // the plan card itself (no apply)
  await page.getByTestId('composer-input').fill('做一期时间管理的讲解视频'); // words only: planned (a cut with no recording waits for it)
  await page.getByTestId('make-plan').click();
  await page.getByTestId('toast-action').first().click();
  await expect(page.getByTestId('plan-failed-reason')).toContainText(/planner didn’t answer/i, { timeout: 15000 });
  await expect(page.getByTestId('plan-retry')).toBeVisible();
  expect(fs.existsSync(path.join(tmp, 'vhome', 'projects.json'))).toBe(false); // no fake project was written
  await page.getByTestId('plan-retry').click();
  await expect(page.getByTestId('plan-summary')).toBeVisible({ timeout: 15000 });
  // the real time it took (the test planner waits 2.5 s), not the planner's own 0.1 s
  await expect(page.getByTestId('plan-took')).toHaveText(/ in [2-9] s/);
  expect(fs.existsSync(path.join(tmp, 'vhome', 'projects.json'))).toBe(false); // planning alone writes no project
});
