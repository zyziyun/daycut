// Starting a video is never stuck (her 0.2.3: "首页现在的状态就回不去了" - Home showed only "Couldn't make a plan ·
// Something went wrong" and Start over led back to the same failure; the request had no files and the planner said
// "no inputs"). Now from the Studio's ＋ New video (2026-10 review step 7: Home's job moved there). Test engine,
// isolated profile, window hidden. The engine's first plan fails like a planner timeout (DESK_MOCK_PLAN_FAIL=1):
//   - a failed plan becomes a failed request row under Needs you, with the reason in plain words and Details; ＋ New
//     video stays free; Start over drops it and puts her words back in the composer
//   - the next request plans and runs as usual
//   - a request with no files is planned from its words; one that cuts footage waits for the recording (no failure),
//     adding it plans and runs it; one that names her Notion waits for the pages, a pasted link goes on
//   - after a restart, a request that was planning when the app quit is a failure she can try again; Home is free
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-home-'));
const recording = path.join(tmp, 'talk_1009.mp4');
const profile = path.join(tmp, 'profile');

test.describe.configure({ mode: 'serial' });

async function launch(fail: string) {
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: {
      ...process.env,
      DESK_ENGINE_MOCK: '1',
      DESK_MOCK_STEP: '0.2',
      DESK_MOCK_PLAN_FAIL: fail,
      DESK_USER_DATA: profile,
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
  await page.evaluate(async () => {
    localStorage.setItem('i18n.strict', '1');
    await window.desk.setSettings({ lang: 'en' });
  });
  await page.reload();
  await page.waitForURL(/^app:\/\/desk\//);
}

test.beforeAll(async () => {
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=180x320:rate=30:duration=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', recording]);
  await launch('1');
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const api = <T,>(p: string, body?: unknown) =>
  page.evaluate(
    async ([u, b]) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + u, {
        method: b === undefined ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${info.token}`, 'content-type': 'application/json' },
        body: b === undefined ? undefined : JSON.stringify(b),
      });
      return r.json();
    },
    [p, body] as const,
  ) as Promise<T>;

async function send(prompt: string) {
  await hash('#/');
  await expect(page.getByTestId('studio')).toBeVisible({ timeout: 30000 });
  if (!(await page.getByTestId('studio-composer').isVisible())) await page.getByTestId('studio-new').click();
  await page.getByTestId('composer-input').fill(prompt);
  await page.getByTestId('make-plan').click();
  await expect(page.getByTestId('studio-composer')).toHaveCount(0, { timeout: 15000 }); // sent: the box closes
}

/** The Studio as she should always find it: the list, ＋ New video free (an empty composer), no plan blocking it. */
async function studioIsFree() {
  await hash('#/');
  await expect(page.getByTestId('studio')).toBeVisible({ timeout: 30000 });
  await expect(page.getByTestId('studio-new')).toBeVisible();
  await page.getByTestId('studio-new').click();
  await expect(page.getByTestId('composer-input')).toHaveValue('');
  await page.getByTestId('studio-new').click(); // closed again
}

const row = (text: string) => page.getByTestId('studio-row').filter({ hasText: text });
const needsYou = (text: string) => page.locator('[data-testid=studio-group-you] [data-testid=studio-row]').filter({ hasText: text });
const ready = (text: string) => page.locator('[data-testid=studio-group-ready] [data-testid=studio-row]').filter({ hasText: text });

test('a failed plan never blocks the Studio: it is a failed request with the reason; Start over brings her words back', async () => {
  test.setTimeout(120000);
  const prompt = '做一期时间管理的科普视频';
  await send(prompt);
  await expect(row(prompt)).toHaveAttribute('data-tone', 'error', { timeout: 30000 });
  await expect(row(prompt)).toHaveAttribute('data-group', 'you'); // the one thing to look at, under Needs you
  await row(prompt).click();
  const card = page.getByTestId('plan-card');
  await expect(card).toHaveAttribute('data-state', 'error');
  await expect(page.getByTestId('plan-failed-reason')).toContainText('took too long to answer');
  await expect(page.getByTestId('plan-failed-reason')).not.toContainText('Something went wrong');
  await page.getByTestId('plan-failed-details').locator('summary').click();
  await expect(page.getByTestId('plan-failed-details')).toContainText('What happened: claude-code: timed out after 235 s');
  await studioIsFree();
  // Start over: the request goes, her words are back in ＋ New video
  await row(prompt).click();
  await page.getByTestId('plan-start-over').click();
  await expect(page.getByTestId('studio-composer')).toBeVisible();
  await expect(page.getByTestId('composer-input')).toHaveValue(prompt);
  await expect(row(prompt)).toHaveCount(0);
});

test('the next request plans and runs: a request with no files is made from its words, never "no inputs"', async () => {
  test.setTimeout(120000);
  const prompt = '做一期时间管理的科普视频';
  await expect(page.getByTestId('composer-input')).toHaveValue(prompt);
  await page.getByTestId('make-plan').click();
  await expect(page.getByTestId('studio-composer')).toHaveCount(0, { timeout: 15000 });
  await expect(ready('讲解').or(ready(prompt.slice(0, 8)))).not.toHaveCount(0, { timeout: 60000 });
  await expect(page.locator('[data-testid=studio-row][data-tone=error]')).toHaveCount(0);
});

test('a cut with no recording waits for it (no failure); adding the recording plans and runs it', async () => {
  test.setTimeout(120000);
  const prompt = '把这条口播剪干净，去气口';
  await send(prompt);
  await expect(needsYou(prompt)).toHaveCount(1, { timeout: 30000 });
  await expect(needsYou(prompt)).toContainText('Waiting for you');
  await needsYou(prompt).click();
  const card = page.getByTestId('plan-card');
  await expect(card).toHaveAttribute('data-state', 'needs');
  await expect(page.getByTestId('plan-need')).toContainText('Add the recordings you want cut');
  await expect(page.getByTestId('plan-need-go-on')).toHaveCount(0); // nothing to make without them
  await expect(page.getByTestId('plan-need-drop')).toBeVisible();
  // what a drop / "Add files" sends (the OS file dialog is not driven here)
  const open = await api<{ items: { id: string; prompt: string }[] }>('/api/intake/open');
  const id = open.items.find((x) => x.prompt === prompt)!.id;
  await api(`/api/intake/${id}/add`, { inputs: [recording] });
  await expect(ready('talk_1009')).not.toHaveCount(0, { timeout: 60000 });
  await expect(needsYou(prompt)).toHaveCount(0, { timeout: 15000 });
});

test('her Notion with nothing to read waits for the pages; a pasted link goes on', async () => {
  test.setTimeout(120000);
  const prompt = '阅读我的notion，尝试做一下有丰富交互的科普经验类视频，做ip';
  await send(prompt);
  await expect(needsYou(prompt.slice(0, 12))).toHaveCount(1, { timeout: 30000 });
  await needsYou(prompt.slice(0, 12)).click();
  await expect(page.getByTestId('plan-need')).toContainText('Which Notion pages?');
  await expect(page.getByTestId('plan-need-go-on')).toBeVisible();
  await page.getByTestId('plan-need-links').fill('https://www.notion.so/me/IP-1a2b3c4d5e6f708192a3b4c5d6e7f809');
  await page.getByTestId('plan-need-send').click();
  await expect(page.getByTestId('toast').filter({ hasText: 'planning again' })).toBeVisible();
  await expect(needsYou(prompt.slice(0, 12))).toHaveCount(0, { timeout: 60000 });
  await expect(page.locator('[data-testid=studio-row][data-tone=error]')).toHaveCount(0);
});

test('after a restart, a request that was planning when the app quit is a failure to try again; the Studio is free', async () => {
  test.setTimeout(180000);
  await closeApp(app);
  const dir = path.join(profile, 'engine-data', 'intake');
  fs.mkdirSync(dir, { recursive: true });
  const id = '7d25b0d015f4';
  fs.writeFileSync(path.join(dir, `${id}.job.json`), JSON.stringify({ id, state: 'running', step: 'plan', prompt: '做一期讲解：番茄工作法', inputs: [], started: Date.now() / 1000 - 30, mode: 'autopilot' }));
  await launch('0');
  await studioIsFree();
  const r = row('番茄工作法');
  await expect(r).toHaveAttribute('data-tone', 'error', { timeout: 30000 });
  await r.click();
  await expect(page.getByTestId('plan-failed-reason')).toContainText('Reelfold was closed while this was being planned');
  await page.getByTestId('plan-retry').click();
  await expect(ready('番茄工作法').or(page.locator('[data-testid=studio-row][data-tone=run]'))).not.toHaveCount(0, { timeout: 60000 });
  await expect(page.locator('[data-testid=studio-row][data-tone=error]').filter({ hasText: '番茄工作法' })).toHaveCount(0);
  await studioIsFree();
});
