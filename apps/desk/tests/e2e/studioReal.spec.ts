// The Studio with the REAL engine sidecar (no mock engine), isolated temp profile, window hidden, the Studio flag on.
// A tiny synthetic talk (fixture/real_project.py: tone-burst words + the engine tests' fake transcriber, the only
// fakes) that the engine parks at a filler question: the Studio lists that clip under Needs you with the question in
// plain words, answering it on its page continues the run (the row moves on by itself), the review before publishing
// is answered in a row (连着看), and the made clip opens as its one page with its words.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
let project = '';
let id = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-studioreal-'));
const REPO = path.resolve(import.meta.dirname, '../../../..');
const SHOTS = process.env.DESK_SHOTS_DIR ?? path.resolve(import.meta.dirname, '../../test-results/studio');
fs.mkdirSync(SHOTS, { recursive: true });
const engineEnv = {
  VSTUDIO_HOME: path.join(tmp, 'vhome'),
  VSTUDIO_BATCH_BENCH: path.join(tmp, 'bench.json'),
  VSTUDIO_DEFAULT_PERSONA: '1',
  VSTUDIO_TEST_TRUTH: path.join(tmp, 'truth.json'),
  VSTUDIO_LLM_PROVIDER: 'none',
  ...Object.fromEntries(['SEGMENT_PLAN', 'PROOFREAD', 'GLOSSARY', 'COPY', 'SCRIPT', 'PLANNER', 'INTAKE', 'OUTPUT_EDIT'].map((t) => [`VSTUDIO_LLM_${t}_PROVIDER`, 'none'])),
};

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  test.setTimeout(300000);
  const env: NodeJS.ProcessEnv = { ...process.env, ...engineEnv, PYTHONPATH: path.join(REPO, 'lib') };
  for (const k of ['ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'VSTUDIO_PERSONA']) delete env[k];
  const out = execFileSync(process.env.DESK_PYTHON || 'python3', [path.join(import.meta.dirname, 'fixture/real_project.py'), tmp], { env, encoding: 'utf8' });
  const fx = JSON.parse(out.trim().split('\n').pop()!) as { dir: string; pending: string[][] };
  expect(fx.pending).toEqual([['talk', 'filler']]);
  project = fx.dir;
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...env, PYTHONPATH: '', DESK_STUDIO: '1', DESK_ENGINE_MOCK: '', DESK_USER_DATA: path.join(tmp, 'profile'), DESK_HISTORY_WATCH: '', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
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
  await expect
    .poll(async () => (await api<{ items: { id: string; dir: string }[] }>('/api/history')).items.find((i) => fs.realpathSync(i.dir) === fs.realpathSync(project))?.id ?? '', { timeout: 60000 })
    .not.toBe('');
  id = (await api<{ items: { id: string; dir: string }[] }>('/api/history')).items.find((i) => fs.realpathSync(i.dir) === fs.realpathSync(project))!.id;
});

test.afterAll(async () => {
  await closeApp(app);
});

const hash = (h: string) => page.evaluate((x) => (location.hash = x), h);
const shot = (name: string) => page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
const api = <T,>(p: string) =>
  page.evaluate(async (u) => {
    const info = await window.desk.engineInfo();
    const r = await fetch(info.baseUrl + u, { headers: { Authorization: `Bearer ${info.token}` } });
    return r.json();
  }, p) as Promise<T>;
const row = () => page.locator(`[data-testid=studio-row][data-row="${id}/talk"]`);

test('the parked clip is under Needs you with its question in words; answering it on its page continues the run', async () => {
  test.setTimeout(300000);
  await hash('#/');
  await expect(page.getByTestId('studio')).toBeVisible({ timeout: 30000 });
  await expect(row()).toHaveAttribute('data-group', 'you', { timeout: 60000 });
  await expect(row()).toContainText(/然后|filler|Cut/i);
  await row().click();
  const q = page.getByTestId('inbox-preview');
  await expect(q).toHaveAttribute('data-kind', 'filler-confirm', { timeout: 30000 });
  await expect(page.getByTestId('inbox-option')).toContainText('Cut “然后”');
  await shot('R1-studio-question');
  await page.getByTestId('inbox-confirm').click();
  await expect(page.locator('.toast.error, [data-error="true"]')).toHaveCount(0);
  // the run goes on by itself: the clip is made (its page opens in place) and stops at the review before publishing,
  // pinned on the page - still Needs you, now that question
  await expect(page.getByTestId('editor')).toHaveAttribute('data-layout', 'studio', { timeout: 180000 });
  await expect(page.getByTestId('studio-question')).toBeVisible({ timeout: 60000 });
  await expect(row()).toHaveAttribute('data-group', 'you');
  await shot('R1b-studio-made-review');
});

test('the review in a row (连着看) publishes it; the made clip opens as one page with its words', async () => {
  test.setTimeout(240000);
  await page.getByTestId('studio-f-all').click();
  await page.getByTestId('studio-in-row').click();
  await expect(page.getByTestId('focus')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('focus-approve').click();
  await page.getByTestId('focus-save').click();
  await expect
    .poll(async () => (await api<{ items: { id: string; live?: { state?: string } }[] }>('/api/history')).items.find((i) => i.id === id)?.live?.state, { timeout: 150000, intervals: [2000] })
    .toBe('done');
  await hash('#/studio');
  await expect(row()).toHaveAttribute('data-group', 'ready', { timeout: 60000 });
  await row().click();
  await expect(page.getByTestId('editor')).toHaveAttribute('data-layout', 'studio', { timeout: 30000 });
  await expect(page.locator('[data-testid=transcript-body] .w').first()).toBeVisible({ timeout: 30000 }); // words on open
  await expect(page.getByTestId('transcript-listen')).toHaveCount(0);
  await shot('R2-studio-clip-real');
});
