// Runs the app with the Studio off (DESK_STUDIO=0): the pages before the Studio (2026-10 review step 7) stay
// supported behind its flag, and this spec covers them.
// Project-level 让 AI 改 (window hidden, mock engine): on the PROJECT page the panel targets every clip. The real
// incident — 「把副业复盘01，02，03都去掉」 on finished (flattened) clips — is answered within seconds with a
// re-render card (the work-script line, copy instructions for Claude Code) instead of minutes of "Thinking…";
// a project-wide change gives one card per clip + apply to all; the staged progress shows elapsed time and
// Cancel stops it. Both languages, no missing keys.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-pai-'));
const watch = path.join(tmp, 'demos');
const fuye = path.join(watch, 'fuye');
const NAMES = ['A_换圈子', 'B_自媒体', 'C_底气'];

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.mkdirSync(path.join(fuye, 'final'), { recursive: true });
  fs.mkdirSync(path.join(fuye, 'work'), { recursive: true });
  for (const n of NAMES) {
    execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x240:rate=30:duration=3', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', path.join(fuye, 'final', `${n}.mp4`)]);
  }
  fs.writeFileSync(path.join(fuye, 'work', 'clipdefs.py'), 'CLIPS = dict(\n  A=dict(kicker="副业复盘"),\n)\n');
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_PROJECT_ASK_DELAY: '5', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_STUDIO: '0', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
  await page.evaluate(() => sessionStorage.setItem('v4.pview', 'grid')); // All projects as the grid (the control room: autopilot.spec)
  await page.evaluate(() => localStorage.setItem('i18n.strict', '1'));
});

test.afterAll(async () => {
  await closeApp(app);
});

const panel = () => page.getByTestId('ai-panel');
const say = async (text: string) => {
  await page.getByTestId('ai-input').fill(text);
  await page.getByTestId('ai-input').press('Enter');
};

test('the project page panel targets every clip; burned-in text -> re-render card within seconds', async () => {
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('project-card').filter({ hasText: 'fuye' }).click();
  await expect(page.getByTestId('clip-card')).toHaveCount(3);
  if (!(await panel().count())) await page.getByTestId('toggle-ai').click();
  await expect(panel()).toHaveAttribute('data-scope', 'project');
  await expect(page.getByTestId('pai-scope')).toContainText('3');
  const t0 = Date.now();
  await say('把副业复盘01，02，03都去掉，这不是一组视频，是单独放的');
  const card = page.getByTestId('pai-needs-rerender');
  await expect(card).toBeVisible({ timeout: 5000 });
  expect(Date.now() - t0).toBeLessThan(5000);
  await expect(card).toHaveAttribute('data-code', 'burned-text');
  for (const n of NAMES) await expect(card).toContainText(n.split('_')[1]);
  await expect(page.getByTestId('pai-group')).toHaveCount(0);
  await expect(card.getByTestId('pai-path')).toHaveAttribute('data-kind', 'rerender-scripts');
  await card.locator('[data-testid=pai-action][data-kind=copy-prompt]').click();
  const clip = await app.evaluate(({ clipboard }) => clipboard.readText());
  expect(clip).toContain('副业复盘');
  expect(clip).toContain('clipdefs.py');
  await expect(card.locator('[data-testid=pai-action][data-kind=open-file]')).toHaveCount(1);
  await expect(panel()).not.toContainText('⟦');
});

test('a project-wide change: staged progress with elapsed time, one card per clip, apply to all, undo', async () => {
  await say('所有片子都 1.2 倍速');
  await expect(page.locator('[data-testid=pai-stage][data-stage=ask]')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('[data-testid=pai-stage][data-stage=read]')).toContainText('3');
  await expect(page.getByTestId('pai-elapsed')).toBeVisible();
  await expect(page.getByTestId('pai-cancel')).toBeEnabled();
  const groups = page.getByTestId('pai-group');
  await expect(groups).toHaveCount(3, { timeout: 10000 });
  await expect(page.getByTestId('pai-status')).toHaveCount(0);
  await expect(groups.first().getByTestId('ai-proposal')).toContainText('1.2');
  await page.getByTestId('pai-apply-all').click();
  await expect(page.getByTestId('pai-undo')).toHaveCount(3);
  await groups.first().getByTestId('pai-undo').click();
  await expect(page.getByTestId('pai-apply')).toHaveCount(1);
  await expect(page.getByTestId('ai-answered-by').last()).toBeVisible();
});

test('Cancel stops a running request', async () => {
  await say('所有片子都 1.1 倍速');
  await expect(page.locator('[data-testid=pai-stage][data-stage=ask]')).toBeVisible({ timeout: 5000 });
  await page.getByTestId('pai-cancel').click();
  await expect(page.getByTestId('pai-status')).toHaveCount(0, { timeout: 5000 });
  await expect(page.getByTestId('pai-reply').last()).toContainText(/Cancelled|已取消/);
});

test('the panel in 简体中文: no missing keys', async () => {
  await page.evaluate(async () => window.desk.setSettings({ lang: 'zh-CN' }));
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('project-card').filter({ hasText: 'fuye' }).click();
  await expect(page.getByTestId('clip-card')).toHaveCount(3);
  if (!(await panel().count())) await page.getByTestId('toggle-ai').click();
  await say('把副业复盘01，02，03都去掉');
  await expect(page.getByTestId('pai-needs-rerender')).toContainText('烧进', { timeout: 5000 });
  await expect(page.getByTestId('pai-needs-rerender')).toContainText('复制给 Claude Code 的指令');
  await expect(panel()).not.toContainText('⟦');
});
