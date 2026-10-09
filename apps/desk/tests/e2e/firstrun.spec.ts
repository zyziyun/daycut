// First ten minutes (window hidden, mock engine, a FRESH profile, no AI logged in): the wizard says "continue without
// AI" out loud and lands on Home; Home offers the built-in sample; one click plans it (planned without AI, said in the
// UI language), Start makes a project labelled as the sample, and the sample can be deleted again.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-firstrun-'));
const mock = path.join(tmp, 'ai');

const row = (provider: string, kind: string, state: string) => ({
  provider,
  kind,
  state,
  ready: false,
  can_login: kind === 'subscription-cli',
  can_logout: false,
  install: { url: 'https://example.com/install', command: 'install it' },
});

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(mock, { recursive: true });
  // a new Mac: Claude Code not installed, Codex installed but nobody signed in, no API keys
  fs.writeFileSync(
    path.join(mock, 'status.json'),
    JSON.stringify({ providers: [row('claude-code', 'subscription-cli', 'not-installed'), row('codex', 'subscription-cli', 'not-logged-in'), row('anthropic', 'api', 'not-configured')] }),
  );
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_MOCK_STEP: '0.02',
      DESK_AI_MOCK: mock,
      DESK_USER_DATA: path.join(tmp, 'profile'),
      VSTUDIO_HOME: path.join(tmp, 'vhome'),
      DESK_HISTORY_WATCH: '',
      DESK_HIDE_WINDOW: '1',
      DESK_SHARED_CACHE: path.join(tmp, 'cache'),
      DESK_HF_HUB: '',
      DESK_SKIP_FIRST_RUN: '',
      DESK_DISABLE_UPDATES: '1',
      VITE_DEV_SERVER_URL: '',
    },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await app?.close();
});

test('fresh profile: welcome -> continue without AI (said out loud) -> platforms -> Home', async () => {
  await expect(page.getByTestId('first-run')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('first-run')).toContainText(/sample/i);
  await page.getByTestId('fr-next').click();
  await expect(page.getByTestId('fr-ai')).toBeVisible();
  await expect(page.getByTestId('fr-sub-claude-code').getByTestId('fr-sub-state')).toHaveAttribute('data-state', 'not-installed', { timeout: 15000 });
  // no AI: the choice is explicit, explained, and it is the one primary button
  await expect(page.getByTestId('fr-no-ai')).toContainText(/captions/i);
  await expect(page.getByTestId('fr-no-ai')).toContainText(/post copy/i);
  await expect(page.locator('[data-testid="first-run"] .btn.primary')).toHaveCount(1);
  await expect(page.getByTestId('fr-next')).toHaveText(/continue without ai/i);
  await page.getByTestId('fr-next').click();
  // English UI: TikTok + YouTube Shorts by default (not Xiaohongshu)
  await expect(page.locator('[data-testid="first-run"] .tab[aria-pressed="true"]')).toHaveText(['YouTube Shorts', 'TikTok']);
  await page.getByTestId('fr-next').click();
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 15000 });
  expect(await page.evaluate(() => location.hash)).toBe('#/');
  const s = await page.evaluate(() => window.desk.getSettings());
  expect(s.firstRunDone).toBe(true);
  expect(s.defaultPlatforms).toEqual(['tiktok', 'youtube-shorts']);
});

test('a fresh profile has no publishing accounts until she adds one (BB-20)', async () => {
  // through the wizard, Home, Publish, its accounts page and Settings: nothing is seeded, nothing "disconnected"
  for (const h of ['#/', '#/publish', '#/publish/accounts', '#/settings', '#/settings/publishing', '#/']) {
    await page.evaluate((x) => (location.hash = x), h);
    await page.waitForTimeout(400);
    await expect(page.locator('body')).not.toContainText(/disconnected|19 accounts/i);
  }
  expect(await page.evaluate(() => window.desk.publish.accounts())).toEqual({});
  const st = await page.evaluate(() => window.desk.getSettings());
  expect(st.accounts ?? {}).toEqual({});
});

test('Try with a sample: planned without AI in the UI language, started, labelled, deletable', async () => {
  test.setTimeout(90000);
  await page.evaluate(() => window.desk.setSettings({ autopilot: false })); // its plan card, then Start
  // first run: the sample card above the starting points; with projects already there (the mock engine lists demo
  // ones): the same action under "More ideas"
  if (await page.getByTestId('home-sample').isVisible()) await page.getByTestId('home-sample').click();
  else {
    await page.getByTestId('home-more-ideas').click();
    await page.getByTestId('idea-sample').click();
  }
  await page.getByTestId('toast-action').first().click({ timeout: 30000 }); // sent: it plans in All projects
  await expect(page.getByTestId('plan-start')).toBeVisible({ timeout: 30000 });
  // the plan says what it does in English (no Chinese template) and that no AI planned it
  const summary = (await page.getByTestId('plan-summary').textContent()) ?? '';
  expect(summary).toContain('reelfold-sample.mp4');
  expect(summary).not.toMatch(/[一-鿿]/);
  await expect(page.getByTestId('plan-no-ai')).toBeVisible();
  await expect(page.getByTestId('plan-card')).not.toContainText('AI plan');
  // the sample file was copied out of the app into the desk's data folder (the engine writes next to its inputs)
  const info = await page.evaluate(async () => {
    const i = await window.desk.engineInfo();
    return (await fetch(i.baseUrl + '/api/sample', { headers: { Authorization: `Bearer ${i.token}` } })).json();
  });
  expect(info.available).toBe(true);
  expect(info.path).toContain(path.join('profile', 'engine-data', 'sample'));

  await page.getByTestId('plan-start').click();
  await page.getByTestId('hub-open').click({ timeout: 30000 });
  await expect(page.getByTestId('project')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('project-title')).toContainText(/Sample/);
  await expect(page.getByTestId('project-sample')).toBeVisible({ timeout: 15000 });

  page.once('dialog', (d) => void d.accept());
  await page.getByTestId('sample-remove').click();
  await expect(page.getByTestId('home')).toBeVisible({ timeout: 15000 });
  await expect
    .poll(async () => (await page.evaluate(async () => {
      const i = await window.desk.engineInfo();
      const h = await (await fetch(i.baseUrl + '/api/history', { headers: { Authorization: `Bearer ${i.token}` } })).json();
      return (h.items as { sample?: boolean }[]).filter((x) => x.sample).length;
    })), { timeout: 15000 })
    .toBe(0);
});

test('the sample delete refuses a project that is not the sample', async () => {
  const r = await page.evaluate(async (dir) => {
    const i = await window.desk.engineInfo();
    const res = await fetch(i.baseUrl + '/api/sample/remove', { method: 'POST', headers: { Authorization: `Bearer ${i.token}`, 'Content-Type': 'application/json' }, body: JSON.stringify({ dir }) });
    return res.status;
  }, path.join(tmp, 'vhome', 'projects', 'nope'));
  expect(r).toBeGreaterThanOrEqual(400);
});

test('the paperclip opens its menu on a real click (it used to close in the same click)', async () => {
  await page.evaluate(() => (location.hash = '#/'));
  await page.getByTestId('composer-attach').click();
  await expect(page.getByTestId('add-files')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('context-menu')).toHaveCount(0);
});
