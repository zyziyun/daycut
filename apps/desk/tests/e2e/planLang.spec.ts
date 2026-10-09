// The plan card's "things for you to decide" follow the UI language (window hidden, mock engine, isolated profile):
// an English request on an English desk used to get its questions in Chinese. For en / 简体中文 / fr the composer
// sends the UI language with the plan request and the box reads in it, each line tagged with that language.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-planlang-'));
const recording = path.join(tmp, 'creator-workshop-screencast.mp4');
const REQUEST = 'Cut this talk into 4 clips for TikTok and Xiaohongshu, vertical';

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.writeFileSync(recording, 'not really a video');
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.02', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await closeApp(app);
});

const CASES = [
  { lang: 'en', html: 'en', heading: 'One thing for you to decide', question: /^Clip 4 is only \d+ s/ },
  { lang: 'zh-CN', html: 'zh-CN', heading: '需要你定的 1 件事', question: /^第 4 条只有 \d+ 秒/ },
  { lang: 'fr', html: 'fr', heading: 'Une chose à décider', question: /^Le clip 4 ne dure que \d+ s/ },
] as const;

for (const c of CASES) {
  test(`${c.lang}: an English request -> the decide box in the UI language`, async () => {
    await page.evaluate((lang) => window.desk.setSettings({ lang }), c.lang);
    await page.evaluate((f) => sessionStorage.setItem('v4.composer', JSON.stringify({ prompt: '', files: [f] })), recording);
    await page.reload();
    await page.waitForURL(/^app:\/\/desk\//);
    await expect(page.locator('html')).toHaveAttribute('lang', c.html);
    await expect(page.getByTestId('composer-files')).toContainText('creator-workshop-screencast.mp4', { timeout: 30000 });
    await page.getByTestId('composer-input').fill(REQUEST);
    await page.getByTestId('make-plan').click();
    const decide = page.getByTestId('plan-decide');
    await expect(decide).toBeVisible({ timeout: 30000 });
    await expect(decide.locator('b')).toHaveText(c.heading);
    const line = decide.locator('div.muted').first();
    await expect(line).toHaveText(c.question);
    await expect(line).toHaveAttribute('lang', c.html);
  });
}
