// Settings (ux/settings-redesign A), window hidden, mock engine, isolated profile: the sub-nav replaces the app
// sidebar (Back returns where she was), every section renders, controls apply at once and persist, demo mode is
// said once, the engine path / Python change asks for "Restart now" (the native file dialog is stubbed in main),
// downloads have their own buttons, diagnostics copy a report without secrets, and the language switch includes
// Français with no missing message in any section.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-set-'));
const python = execFileSync('python3', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim();

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: path.join(tmp, 'demos'), DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => localStorage.setItem('i18n.strict', '1'));
});

test.afterAll(async () => {
  await app?.close();
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const settings = () => page.evaluate(() => window.desk.getSettings());
const noMissing = async () => expect(await page.evaluate(() => document.body.innerText.match(/⟦[^⟧]+⟧|\b(?:s2|set|aiacc)\.[a-zA-Z][\w.-]+/g))).toBeNull();

test('its own sub-nav with status dots and the version; Back returns where she was', async () => {
  await hash('#/inbox');
  await expect(page.getByTestId('inbox')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('nav-settings').click();
  await expect(page.getByTestId('settings-nav')).toBeVisible();
  await expect(page.getByTestId('nav-home')).toHaveCount(0); // the app sidebar is replaced
  for (const s of ['general', 'ai', 'accounts', 'advanced']) await expect(page.getByTestId(`snav-${s}`)).toBeVisible();
  await expect(page.getByTestId('settings-version')).toContainText('Reelfold 0.2.0');
  await expect(page.getByTestId('snav-advanced')).toHaveAttribute('data-dot', 'warn'); // demo mode
  await expect(page.getByTestId('settings-status')).toContainText('Demo mode');
  await expect(page.getByTestId('settings-privacy')).toContainText('Your video files stay on this Mac; only text is sent to the AI you choose.');
  await expect(page.locator('.s2-page')).not.toContainText(/\/Users\/|\/private\/|\/var\/|\/tmp\//); // no raw paths
  await page.getByTestId('settings-back').click();
  await expect(page.getByTestId('inbox')).toBeVisible();
});

test('General applies at once and persists: theme, accent, tidy-up, agency mode', async () => {
  await hash('#/settings/general');
  await page.getByTestId('theme-dark').click();
  await expect.poll(async () => (await settings()).theme).toBe('studio-dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'studio-dark');
  await page.getByTestId('accent-red').click();
  await expect.poll(async () => (await settings()).accent).toBe('red');
  await page.getByTestId('tidy').selectOption('30');
  await expect.poll(async () => (await settings()).cleanupDays).toBe(30);
  await page.getByTestId('agency-toggle').check();
  await expect.poll(async () => (await settings()).agencyMode).toBe(true);
  await expect(page.getByTestId('open-clients')).toBeVisible();
  // a fresh window reads the same
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('agency-toggle')).toBeChecked({ timeout: 30000 });
  await expect(page.getByTestId('tidy')).toHaveValue('30');
  await expect(page.getByTestId('theme-dark')).toHaveAttribute('aria-checked', 'true');
  await page.getByTestId('agency-toggle').uncheck();
  await page.getByTestId('theme-light').click();
  await page.getByTestId('accent-teal').click();
  await expect.poll(async () => (await settings()).theme).toBe('notebook-light');
});

test('Publishing lists the accounts with their state; Sign in goes to the built-in browser page', async () => {
  await page.evaluate(() => window.desk.publish.addAccount('douyin', 'main'));
  await hash('#/settings/accounts');
  await expect(page.getByTestId('settings-channel')).toHaveCount(1);
  await expect(page.getByTestId('settings-channel').getByTestId('channel-state')).toHaveAttribute('data-state', 'out'); // no session cookie
  await expect(page.getByTestId('open-channels')).toHaveAttribute('href', '#/publish/accounts');
});

test('Advanced: collapsed sections, engine in words, Python change -> Restart now', async () => {
  await hash('#/settings/advanced');
  await expect(page.getByTestId('settings-engine')).toHaveCount(0); // collapsed
  await page.getByTestId('adv-engine').locator('button').first().click();
  await expect(page.getByTestId('demo-warning')).toBeVisible();
  await expect(page.getByTestId('engine-words')).not.toContainText('/');
  await expect(page.getByTestId('restart-bar')).toHaveCount(0);
  await app.evaluate(({ dialog }, p) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [p] })) as typeof dialog.showOpenDialog;
  }, python);
  await page.getByTestId('change-python').click();
  await expect(page.getByTestId('restart-bar')).toContainText('You changed the Python');
  expect((await settings()).python).toBe(python);
  // still there after switching sections (nothing restarted under her)
  await page.getByTestId('snav-general').click();
  await page.getByTestId('snav-advanced').click();
  await expect(page.getByTestId('restart-bar')).toBeVisible();
  const before = await page.evaluate(async () => (await window.desk.engineInfo()).token);
  await page.getByTestId('restart-now').click();
  await expect.poll(async () => page.evaluate(async () => (await window.desk.engineInfo()).token).catch(() => before), { timeout: 30000 }).not.toBe(before);
  await page.waitForURL(/^app:\/\/desk\//);
  await expect(page.getByTestId('settings-advanced')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('restart-bar')).toHaveCount(0);
});

test('Advanced: downloads per row, diagnostics report has no secrets', async () => {
  await hash('#/settings/advanced');
  await page.getByTestId('adv-downloads').locator('button').first().click();
  await expect(page.getByTestId('assets-card')).toBeVisible();
  await expect(page.getByTestId('assets-card').locator('input[type="checkbox"]')).toHaveCount(0); // no tick-then-download
  await page.getByTestId('adv-diag').locator('button').first().click();
  await page.getByTestId('diag-copy').click();
  const report = await app.evaluate(({ clipboard }) => clipboard.readText());
  expect(report).toContain('Reelfold 0.2.0');
  expect(report).toMatch(/Engine: mock/);
  expect(report).not.toMatch(/\btoken\b|Bearer|\bsk-[A-Za-z0-9]{8}/i);
});

test('AI: the current AI, the fallback sentence, per-job page, keys and local sheets', async () => {
  await hash('#/settings/ai');
  await expect(page.getByTestId('ai-accounts')).toBeVisible();
  await expect(page.getByTestId('ai-switch')).toBeVisible();
  await expect(page.getByTestId('ai-fallback-sentence')).toBeVisible();
  await page.getByTestId('ai-perjob').click();
  await expect(page).toHaveURL(/#\/settings\/ai\/jobs$/);
  await expect(page.getByTestId('ai-routes')).toBeVisible();
  await page.getByTestId('ai-jobs-back').click();
  await page.getByTestId('ai-add-key').click();
  await expect(page.getByTestId('ai-keys-sheet')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByTestId('ai-local-setup').click();
  await expect(page.getByTestId('ai-local-sheet')).toBeVisible();
  await page.keyboard.press('Escape');
});

for (const lang of ['zh-CN', 'fr', 'en'] as const) {
  test(`language ${lang}: switched from General, every section has its messages`, async () => {
    await hash('#/settings/general');
    await page.getByTestId(`lang-${lang}`).click();
    await expect.poll(async () => (await settings()).lang).toBe(lang);
    await expect(page.locator('html')).toHaveAttribute('lang', lang === 'zh-CN' ? 'zh-CN' : lang);
    for (const s of ['general', 'ai', 'ai/jobs', 'accounts', 'advanced']) {
      await hash(`#/settings/${s}`);
      await page.waitForTimeout(400);
      await noMissing();
    }
    if (lang === 'zh-CN') {
      await hash('#/settings/general');
      await expect(page.getByTestId('settings-privacy')).toContainText('视频文件留在本机；只有文字会发给你选的 AI。');
      await expect(page.getByTestId('settings-back')).toContainText('返回千剪');
    }
    if (lang === 'fr') {
      await hash('#/settings/general');
      await expect(page.getByTestId('settings-nav')).toContainText('Général');
      await expect(page.getByTestId('lang-fr')).toHaveAttribute('aria-checked', 'true');
    }
  });
}
