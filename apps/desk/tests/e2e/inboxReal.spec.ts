// Runs the app with the Studio off (DESK_STUDIO=0): the pages before the Studio (2026-10 review step 7) stay
// supported behind its flag, and this spec covers them.
// Inbox -> run -> review in the real app with the REAL engine sidecar (no mock engine), an isolated temp profile,
// window hidden. The project is a tiny synthetic talk (fixture/real_project.py: tone-burst words + the engine tests'
// fake transcriber, the only fakes) that the engine parks at a filler question. Found while recording the real app:
//   - the filler card was a bare word: it reads as a cut with the words around it, listed once (no second
//     "A decision is waiting" item from the run's status)
//   - answering failed ("'6' is not of type 'integer'") and never continued the run: the run goes on to the review
//     before publishing, whose options name the platforms (never "0…5")
//   - #/p/<id>/focus said "Nothing to review here" for that review: the clip is there, Approve publishes it
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { closeApp } from './closeApp';

let app: ElectronApplication;
let page: Page;
let project = '';
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-inboxreal-'));
const REPO = path.resolve(import.meta.dirname, '../../../..');
const engineEnv = {
  VSTUDIO_HOME: path.join(tmp, 'vhome'),
  VSTUDIO_BATCH_BENCH: path.join(tmp, 'bench.json'),
  VSTUDIO_DEFAULT_PERSONA: '1',
  VSTUDIO_TEST_TRUTH: path.join(tmp, 'truth.json'),
  // no AI account in tests: every model task the engine routes (titles at export, proofreading ...) answers "none",
  // ahead of the desk's own routes (which would pick the creator's signed-in Codex / Claude Code)
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
    env: { ...env, PYTHONPATH: '', DESK_ENGINE_MOCK: '', DESK_USER_DATA: path.join(tmp, 'profile'), DESK_HISTORY_WATCH: '', DESK_STUDIO: '0', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
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
const api = <T,>(p: string) =>
  page.evaluate(async (u) => {
    const info = await window.desk.engineInfo();
    const r = await fetch(info.baseUrl + u, { headers: { Authorization: `Bearer ${info.token}` } });
    return r.json();
  }, p) as Promise<T>;

test('the filler question: once, with the words around the cut; answering it continues the run', async () => {
  test.setTimeout(240000);
  await hash('#/inbox');
  await expect(page.getByTestId('inbox-item')).toHaveCount(1, { timeout: 30000 });
  await expect(page.getByTestId('inbox-preview')).toHaveAttribute('data-kind', 'filler-confirm');
  const opt = page.getByTestId('inbox-option');
  await expect(opt).toHaveCount(1);
  await expect(opt).toContainText('Cut “然后”');
  await expect(opt).toContainText('方法⟨然后⟩来看');
  await page.getByTestId('inbox-confirm').click();
  await expect(page.locator('.toast.error, [data-error="true"]')).toHaveCount(0);
  // the run goes on by itself and stops at the review before publishing (one item, the platforms by name)
  await expect(page.getByTestId('inbox-preview')).toHaveAttribute('data-kind', 'publish', { timeout: 180000 });
  await expect(page.getByTestId('inbox-item')).toHaveCount(1);
  const labels = await page.getByTestId('inbox-option').allInnerTexts();
  expect(labels.length).toBeGreaterThan(0);
  expect(labels.join(' ')).toContain('Xiaohongshu');
  for (const l of labels) expect(l.trim()).not.toMatch(/^\d+$/);
});

test('#/p/<id>/focus shows the clip waiting at its review; Approve publishes it and the project finishes', async () => {
  test.setTimeout(180000);
  const hist = await api<{ items: { id: string; dir: string }[] }>('/api/history');
  const id = hist.items.find((i) => fs.realpathSync(i.dir) === fs.realpathSync(project))?.id;
  expect(id).toBeTruthy();
  await hash(`#/p/${id}/focus`);
  await expect(page.getByTestId('focus')).toBeVisible({ timeout: 30000 });
  await expect(page.getByText('Nothing to review here.')).toHaveCount(0);
  await page.getByTestId('focus-approve').click();
  await page.getByTestId('focus-save').click();
  await expect
    .poll(async () => (await api<{ items: { id: string; live?: { state?: string } }[] }>('/api/history')).items.find((i) => i.id === id)?.live?.state, { timeout: 150000, intervals: [2000] })
    .toBe('done');
  await hash('#/inbox');
  await expect(page.getByTestId('inbox-item')).toHaveCount(0, { timeout: 30000 });
});
