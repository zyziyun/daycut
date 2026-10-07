// AI accounts & models (window hidden, mock engine, isolated profile, mocked CLI status via DESK_AI_MOCK):
// Settings -> the page shows Claude Code "login expired" and Codex "logged in" -> 登录 opens the in-app terminal,
// the (fake) login command exits -> the status is checked again (logged in · Max) -> switch the default provider ->
// the 让 AI 改 panel's provider chip and the composer chip show it; both languages, no missing keys.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-ai-'));
const mock = path.join(tmp, 'ai-mock');
const watch = path.join(tmp, 'demos');
const work = path.join(watch, 'aiwork');

const row = (provider: string, kind: string, state: string, extra: Record<string, unknown> = {}) => ({
  provider,
  kind,
  state,
  ready: ['logged-in', 'configured', 'ready'].includes(state),
  can_login: kind === 'subscription-cli',
  can_logout: kind === 'subscription-cli',
  install: { url: 'https://example.com/install', command: 'install it' },
  ...extra,
});
const status = (claude: string) => ({
  providers: [
    row('claude-code', 'subscription-cli', claude, { verified: true, account: { email: 'me@example.com', plan: 'max', auth_method: 'claude.ai' }, version: '2.1.153 (Claude Code)' }),
    row('codex', 'subscription-cli', 'logged-in', { account: { auth_method: 'chatgpt' } }),
    row('anthropic', 'api', 'not-configured', { key_env: 'ANTHROPIC_API_KEY' }),
    row('deepseek', 'api', 'not-configured', { key_env: 'DEEPSEEK_API_KEY' }),
    row('ollama', 'local', 'server-down', { base_url: 'http://localhost:11434/v1' }),
  ],
});

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(mock, { recursive: true });
  fs.writeFileSync(path.join(mock, 'status.json'), JSON.stringify(status('expired')));
  fs.writeFileSync(path.join(mock, 'status-ok.json'), JSON.stringify(status('logged-in')));
  const persona = { provider: 'claude-code', model: null, fallback: ['codex'] };
  fs.writeFileSync(
    path.join(mock, 'routes.json'),
    JSON.stringify(Object.fromEntries(['default', 'segment_plan', 'proofread', 'glossary', 'copy', 'intake', 'output_edit'].map((k) => [k, persona]))),
  );
  // the "CLI login": prints, waits for a pasted code, then the login is fixed (status-ok.json) and it exits
  const script = `printf 'Opening your browser to sign in\\r\\nPaste code: '; read code; printf "got %s\\r\\n" "$code"; cp '${path.join(mock, 'status-ok.json')}' '${path.join(mock, 'status.json')}'; exit 0`;
  // Windows: the same login as a .cmd (what an npm-installed CLI is there), so the sheet runs it through cmd.exe
  const cmdFile = path.join(mock, 'login.cmd');
  fs.writeFileSync(cmdFile, ['@echo off', 'echo Opening your browser to sign in', 'set /p code=Paste code: ', 'echo got %code%', `copy /y "${path.join(mock, 'status-ok.json')}" "${path.join(mock, 'status.json')}" >nul`, 'exit /b 0', ''].join('\r\n'));
  const command = process.platform === 'win32' ? [cmdFile] : ['/bin/sh', '-c', script];
  fs.writeFileSync(path.join(mock, 'login.json'), JSON.stringify({ 'claude-code:login': { command, display: 'claude auth login', env_unset: ['ANTHROPIC_API_KEY'] } }));
  // one clip for the 让 AI 改 panel
  fs.mkdirSync(path.join(work, 'final'), { recursive: true });
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=3', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(work, 'final', 'A_test.mp4')]);
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_AI_MOCK: mock,
      DESK_USER_DATA: path.join(tmp, 'profile'),
      VSTUDIO_HOME: path.join(tmp, 'vhome'),
      DESK_HISTORY_WATCH: watch,
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
const card = (p: string) => page.getByTestId(`provider-${p}`);

test('settings -> AI: expired Claude login, Codex logged in, keys / local servers in their sheets', async () => {
  await hash('#/settings');
  await page.getByTestId('snav-ai').click();
  await expect(page.getByTestId('ai-accounts')).toBeVisible();
  await expect(page.getByTestId('snav-ai')).toHaveAttribute('data-dot', 'warn', { timeout: 15000 }); // the AI in use needs her
  await expect(card('claude-code').getByTestId('provider-pill')).toHaveAttribute('data-state', 'expired', { timeout: 15000 });
  await expect(card('claude-code').getByTestId('provider-pill')).toHaveText(/Login expired/);
  await expect(card('claude-code').getByTestId('login-claude-code')).toHaveText('Sign in again');
  await expect(card('codex').getByTestId('provider-pill')).toHaveAttribute('data-state', 'logged-in');
  await expect(page.getByTestId('ai-fallback-sentence')).toHaveText(/tries Codex → simple rules/);
  // API keys and local models live in their sheets
  await page.getByTestId('ai-add-key').click();
  await expect(card('deepseek').getByTestId('provider-pill')).toHaveText('Not set up');
  await page.keyboard.press('Escape');
  await page.getByTestId('ai-local-setup').click();
  await expect(card('ollama').getByTestId('provider-pill')).toHaveText('Local server not running');
  await page.keyboard.press('Escape');
  // the fallback order: one sentence on the page, the editor in a sheet
  await page.getByTestId('ai-order').click();
  await expect(page.getByTestId('route-default-provider')).toHaveValue('claude-code'); // the persona's routes
  await expect(page.getByTestId('route-default-fallbacks').getByTestId('fallback-item')).toHaveText(/Codex/);
  await page.keyboard.press('Escape');
  // General's status line: the mock engine is demo mode, which outranks the AI (one thing at a time)
  await page.getByTestId('snav-general').click();
  await expect(page.getByTestId('settings-status')).toHaveAttribute('data-tone', 'warn');
  await page.getByTestId('snav-ai').click();
});

test('Sign in runs the CLI login in the sign-in sheet (code pasted in the sheet); on exit the status is checked again', async () => {
  await card('claude-code').getByTestId('login-claude-code').click();
  const term = page.getByTestId('login-terminal');
  await expect(term).toBeVisible();
  await expect(term).toContainText('Your browser opened');
  await expect(page.getByTestId('term-wait')).toBeVisible();
  // the terminal is folded under Show details
  await page.getByTestId('signin-details').click();
  await expect(term).toContainText('claude auth login');
  await expect(page.locator('.xterm-rows')).toContainText('Paste code', { timeout: 15000 });
  await page.getByTestId('signin-code').fill('abc123');
  await page.getByTestId('signin-code').press('Enter');
  await expect(page.getByTestId('term-exit')).toBeVisible({ timeout: 15000 });
  await expect(card('claude-code').getByTestId('provider-pill')).toHaveText('Working', { timeout: 15000 });
  await expect(card('claude-code').getByTestId('provider-account')).toContainText('me@example.com');
  await page.getByTestId('term-close').click();
  await expect(term).toHaveCount(0);
  await expect(page.getByTestId('snav-ai')).toHaveAttribute('data-dot', 'ok');
});

test('switching the default provider is explicit and shows up where AI runs', async () => {
  await page.getByTestId('ai-order').click();
  await page.getByTestId('route-default-provider').selectOption('codex');
  await expect(page.getByTestId('route-default-fallbacks').getByTestId('fallback-item')).toHaveCount(0);
  await page.getByTestId('route-default-add-fallback').selectOption('claude-code');
  await expect(page.getByTestId('route-default-fallbacks').getByTestId('fallback-item')).toHaveText(/Claude Code/);
  const file = JSON.parse(fs.readFileSync(path.join(tmp, 'profile', 'llm-routes.json'), 'utf8'));
  expect(file.default).toEqual({ provider: 'codex', fallback: ['claude-code'] });
  expect(file.tasks.output_edit.provider).toBe('codex');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('provider-codex')).toBeVisible(); // the card at the top is now Codex
  // per-job routes are a second page
  await page.getByTestId('ai-perjob').click();
  await expect(page.getByTestId('ai-routes')).toBeVisible();
  await page.getByTestId('ai-jobs-back').click();
  await expect(page.getByTestId('ai-perjob')).toBeVisible();

  await hash('#/');
  await expect(page.getByTestId('composer')).toBeVisible();
  await expect(page.getByTestId('composer-provider-chip')).toHaveCount(0); // Home: where AI runs lives in Settings now
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('project-card').filter({ hasText: 'aiwork' }).click();
  await expect(page.getByTestId('clip-card')).toHaveCount(1);
  if (!(await page.getByTestId('ai-panel').count())) await page.getByTestId('toggle-ai').click();
  const chip = page.getByTestId('ai-provider-chip');
  await expect(chip).toHaveAttribute('data-provider', 'codex');
  await expect(chip).toContainText('Codex');
  // quick switcher: this task only
  await chip.click();
  await page.getByTestId('chip-pick-claude-code').click();
  await expect(chip).toHaveAttribute('data-provider', 'claude-code');
  expect(JSON.parse(fs.readFileSync(path.join(tmp, 'profile', 'llm-routes.json'), 'utf8')).tasks.output_edit.provider).toBe('claude-code');
  await page.getByTestId('ai-input').fill('再紧凑一点');
  await page.getByTestId('ai-input').press('Enter');
  await expect(page.getByTestId('ai-answered-by').first()).toBeVisible({ timeout: 15000 });
});

for (const lang of ['zh-CN', 'en'] as const) {
  test(`the AI accounts page in ${lang}: no missing keys`, async () => {
    await page.evaluate(async (l) => {
      localStorage.setItem('i18n.strict', '1');
      await window.desk.setSettings({ lang: l });
    }, lang);
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await hash('#/settings/ai/codex');
    await expect(card('codex').getByTestId('provider-pill')).toHaveAttribute('data-state', 'logged-in', { timeout: 15000 });
    if (lang === 'zh-CN') await expect(page.getByTestId('ai-accounts')).toContainText('和你一起规划');
    const missing = await page.evaluate(() => document.body.innerText.match(/⟦[^⟧]+⟧|\baiacc\.[\w.-]+/g));
    expect(missing).toBeNull();
    await page.evaluate(() => localStorage.removeItem('i18n.strict'));
  });
}
