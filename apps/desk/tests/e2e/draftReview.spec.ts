// "Check what's kept" in the real app with the REAL engine sidecar (no mock engine), an isolated temp profile, window
// hidden. Two promo-recut projects on a tiny synthetic talk (fixture/promo_project.py: tone-burst words + the engine
// tests' fake transcriber, the only fakes; no AI account, so the engine drafts by its rules). Found in her 0.2.3 Inbox
// ("这都啥"): "Keep spans · promo.config.yaml" with a File box, Open in editor and the raw YAML of the SYNTHETIC
// example, under a grey "0" instead of a picture. Now:
//   - the step reads "Check what's kept" with her transcript, kept / cut sentences, a plain summary - no YAML, no
//     file path, no raw seconds anywhere in the Inbox; the row has a picture (a frame of her recording)
//   - a click on a sentence cuts it; "Use my selection" answers with exactly what she keeps and the run goes on
//   - her stuck project (the item still the example, nothing drafted) offers "Draft it for me"; the draft appears
//   - "Advanced: open the file" is the only way to the config
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
let fx: { drafted: { dir: string }; stuck: { dir: string } };
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-draft-'));
const REPO = path.resolve(import.meta.dirname, '../../../..');
const engineEnv = {
  VSTUDIO_HOME: path.join(tmp, 'vhome'),
  VSTUDIO_BATCH_BENCH: path.join(tmp, 'bench.json'),
  VSTUDIO_DEFAULT_PERSONA: '1',
  VSTUDIO_TEST_TRUTH: path.join(tmp, 'truth.json'),
  VSTUDIO_LLM_PROVIDER: 'none',
  ...Object.fromEntries(['SEGMENT_PLAN', 'PROOFREAD', 'GLOSSARY', 'COPY', 'SCRIPT', 'PLANNER', 'INTAKE', 'OUTPUT_EDIT'].map((t) => [`VSTUDIO_LLM_${t}_PROVIDER`, 'none'])),
};
// what must never reach her Inbox
const RAW = /promo\.config|\.yaml|cut\.body|KEEP spans|SYNTHETIC|raw seconds|\/items\/|Open in editor|How to write it/;

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  test.setTimeout(300000);
  const env: NodeJS.ProcessEnv = { ...process.env, ...engineEnv, PYTHONPATH: path.join(REPO, 'lib') };
  for (const k of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'VSTUDIO_PERSONA']) delete env[k];
  const out = execFileSync(process.env.DESK_PYTHON || 'python3', [path.join(import.meta.dirname, 'fixture/promo_project.py'), tmp], { env, encoding: 'utf8' });
  fx = JSON.parse(out.trim().split('\n').pop()!);
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...env, PYTHONPATH: '', DESK_ENGINE_MOCK: '', DESK_USER_DATA: path.join(tmp, 'profile'), DESK_HISTORY_WATCH: '', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
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
  expect((await page.evaluate(() => window.desk.engineInfo())).mode).toBe('real');
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const row = (name: string) => page.getByTestId('inbox-item').filter({ hasText: name });

test('the drafted keep spans read as her transcript in plain words: no YAML, no path, a picture', async () => {
  test.setTimeout(120000);
  await hash('#/inbox');
  await expect(row('AIGC drafted')).toHaveCount(1, { timeout: 30000 });
  await expect(row('AIGC stuck')).toHaveCount(1);
  await expect(row('AIGC drafted')).toContainText('Check what’s kept');
  await expect(row('AIGC drafted')).toContainText('Keeps all 0:07');
  // a frame of her recording, not the first letter of the project's name
  await expect(row('AIGC drafted').locator('video, img')).toHaveCount(1);
  await row('AIGC drafted').click();
  const pane = page.getByTestId('inbox-preview');
  await expect(pane.getByRole('heading')).toHaveText('Check what’s kept');
  await expect(pane.getByTestId('draft-summary')).toContainText('the AI wasn’t available to choose cuts');
  const sents = pane.getByTestId('draft-sentence');
  await expect(sents).toHaveCount(4);
  await expect(sents.nth(2)).toHaveText(/顺便说一下Hedra/);
  expect(await page.getByTestId('inbox').innerText()).not.toMatch(RAW);
  await expect(page.getByTestId('inbox-confirm')).toHaveText(/Looks good/);
});

test('cutting sentences by clicking them answers with exactly what she keeps; the run goes on', async () => {
  test.setTimeout(240000);
  const pane = page.getByTestId('inbox-preview');
  const sents = pane.getByTestId('draft-sentence');
  await sents.nth(0).click();
  await sents.nth(2).click();
  await expect(sents.nth(0)).toHaveAttribute('data-keep', '0');
  await expect(sents.nth(2)).toHaveAttribute('data-keep', '0');
  await expect(pane.getByTestId('draft-summary')).toContainText('your selection');
  await expect(page.getByTestId('inbox-confirm')).toHaveText(/Use my selection/);
  await page.getByTestId('inbox-confirm').click();
  await expect(page.locator('.toast.error')).toHaveCount(0);
  // the cut is hers: the config holds the two kept sentences, the review says so
  const cfg = path.join(fx.drafted.dir, 'items', 'AIGC-talk', 'promo.config.yaml');
  await expect.poll(() => fs.readFileSync(cfg, 'utf8'), { timeout: 30000 }).toContain('adjusted by you');
  const body = fs.readFileSync(cfg, 'utf8').match(/body:\s*\n?((?:\s*-?\s*\[[^\]]*\]\s*)+)/)?.[0] ?? '';
  expect(body.match(/\[/g)?.length).toBeGreaterThanOrEqual(2);
  // the run continues by itself (next stop: the filler cuts or later - not the keep step again)
  await expect.poll(async () => (await row('AIGC drafted').allInnerTexts()).join(' '), { timeout: 180000, intervals: [2000] }).not.toContain('Check what’s kept');
});

test('her stuck project (still the example, nothing drafted) offers "Draft it for me" - never the YAML', async () => {
  test.setTimeout(180000);
  await row('AIGC stuck').click();
  const pane = page.getByTestId('inbox-preview');
  await expect(pane.getByTestId('inbox-draft')).toHaveAttribute('data-state', 'template');
  await expect(pane.getByTestId('draft-none')).toContainText('The AI drafts it from your recording');
  expect(await page.getByTestId('inbox').innerText()).not.toMatch(RAW);
  await expect(pane.getByTestId('draft-advanced')).toHaveCount(0);       // nothing of hers to open
  await expect(page.getByTestId('inbox-confirm')).toHaveText(/Draft it for me/);
  await page.getByTestId('inbox-confirm').click();
  // drafted in the background (rules: keeps all, said plainly), then the transcript shows
  await expect(page.getByTestId('inbox-preview').getByTestId('draft-sentence')).toHaveCount(4, { timeout: 120000 });
  await expect(page.getByTestId('inbox-preview').getByTestId('draft-summary')).toContainText('Keeps all');
  expect(await page.getByTestId('inbox').innerText()).not.toMatch(RAW);
  const cfg = fs.readFileSync(path.join(fx.stuck.dir, 'items', 'AIGC-talk', 'promo.config.yaml'), 'utf8');
  expect(cfg).not.toContain('SYNTHETIC');
  // Advanced is there now, folded away
  await expect(page.getByTestId('inbox-preview').getByTestId('draft-advanced')).toBeVisible();
  await expect(page.getByTestId('inbox-preview').getByTestId('draft-open-file')).toBeHidden();
});
