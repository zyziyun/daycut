// v0.2 happy path in mock mode (no keys, no network): first-run wizard -> client (agency mode) -> new batch from a
// raw recording (AI segment planning, segment review) -> estimate -> pilot -> full run -> in-review edits
// (caption fix with faithful check, hook swap, trim, undo, re-render affected) -> delivery package -> metrics
// + weekly_metrics.csv export. Native dialogs are stubbed in the main process.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-v02-'));
const recording = path.join(tmp, 'raw-lecture.mp4');
const csvOut = path.join(tmp, 'weekly_metrics.csv');

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  fs.writeFileSync(recording, 'not really a video');
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_MOCK_STEP: '0.01', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: '', DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//);
  await app.evaluate(
    ({ dialog }, files) => {
      dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: [files.recording] })) as typeof dialog.showOpenDialog;
      dialog.showSaveDialog = (async () => ({ canceled: false, filePath: files.csvOut })) as typeof dialog.showSaveDialog;
    },
    { recording, csvOut },
  );
});

test.afterAll(async () => {
  await app?.close();
});

async function api<T>(pathname: string, body?: unknown): Promise<T> {
  return page.evaluate(
    async ({ pathname, body }) => {
      const info = await window.desk.engineInfo();
      const r = await fetch(info.baseUrl + pathname, {
        method: body === undefined ? 'GET' : 'POST',
        headers: { Authorization: `Bearer ${info.token}`, 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      return r.json();
    },
    { pathname, body },
  ) as Promise<T>;
}

test('first-run wizard: keys card, models, default platforms, finish', async () => {
  await expect(page.getByTestId('first-run')).toBeVisible({ timeout: 30000 });
  await page.getByTestId('fr-next').click(); // welcome -> keys
  await expect(page.getByTestId('keys-card')).toBeVisible();
  const keyStatus = await page.evaluate(() => window.desk.secrets.status());
  expect(Object.keys(keyStatus.keys).sort()).toEqual(['anthropic', 'deepseek', 'glm', 'kimi', 'openai', 'openrouter', 'qwen']);
  await page.getByTestId('fr-next').click(); // -> models
  await page.getByTestId('fr-next').click(); // -> platforms
  await page.getByRole('button', { name: /TikTok/ }).click();
  await page.getByTestId('fr-next').click(); // -> persona
  await page.getByTestId('fr-next').click(); // finish
  await expect(page.getByTestId('first-run')).toHaveCount(0);
  const s = await page.evaluate(() => window.desk.getSettings());
  expect(s.firstRunDone).toBe(true);
  expect(s.defaultPlatforms).toContain('tiktok');
});

test('client workspace: create, edit client.yaml fields', async () => {
  // clients are an agency feature: Settings -> 「我在帮别人做视频」 -> 客户管理 (a solo creator never sees them)
  await page.evaluate(() => (location.hash = '#/settings'));
  await page.getByTestId('agency-toggle').check();
  await page.getByTestId('open-clients').click();
  await page.getByTestId('new-client').click();
  await page.locator('.modal input').first().fill('E2E 讲师');
  await page.locator('.modal input').nth(1).fill('e2e');
  await page.locator('.modal').getByRole('button', { name: /创建|Create/ }).click();
  await expect(page.getByTestId('crm')).toBeVisible();
  await page.getByRole('button', { name: /严格|Strict/ }).click();
  await page.getByRole('button', { name: /^\+ (添加|Add)$/ }).click();
  await page.getByPlaceholder(/识别成|Heard as/).last().fill('rak');
  await page.getByPlaceholder(/应为|Should be/).last().fill('RAG');
  await page.getByTestId('client-save').click();
  await expect(page.getByText(/已保存 client.yaml|client.yaml saved/)).toBeVisible();
  const c = await api<{ config: { cleanup_profile: string; glossary: { wrong: string }[] } }>('/api/clients/e2e');
  expect(c.config.cleanup_profile).toBe('strict');
  expect(c.config.glossary.map((g) => g.wrong)).toContain('rak');
  await page.getByTestId('crm').getByRole('button', { name: /^(样片|Sample)$/ }).click();
  await expect(page.getByTestId('crm').locator('.step.cur')).toHaveText(/样片|Sample/);
});

let batchId = '';

test('new batch from a raw recording: plan, review segments, estimate, pilot', async () => {
  await page.evaluate(() => (location.hash = '#/new')); // the old form lives under Home → Advanced
  await page.getByTestId('pick-files').click();
  await expect(page.getByTestId('raw-files')).toContainText('raw-lecture.mp4');
  await page.getByTestId('client-select').selectOption('e2e');
  await page.getByTestId('batch-name').fill('e2e-lecture');
  await page.getByRole('radio', { name: /规则选段|Rules/ }).click();
  await page.getByTestId('start-plan').click();
  await expect(page.getByTestId('segment-review')).toBeVisible({ timeout: 30000 });
  const items = page.locator('.segitem');
  const n = await items.count();
  expect(n).toBeGreaterThan(2);
  // reject the second candidate, retitle the first, nudge its start one word later
  await items.nth(1).click();
  await page.getByTestId('seg-toggle').click();
  await items.nth(0).click();
  await page.getByTestId('seg-title').fill('E2E 改过的标题');
  const before = Number(await page.getByTestId('edge-start').getAttribute('aria-valuenow'));
  await page.getByTestId('edge-start').focus();
  await page.keyboard.press('ArrowRight');
  const after = Number(await page.getByTestId('edge-start').getAttribute('aria-valuenow'));
  expect(after).toBeGreaterThan(before);
  await page.getByTestId('create-batch').click();
  await page.getByTestId('to-pilot').click();
  await page.getByTestId('start-pilot').click();
  await page.waitForURL(/#\/b\/[0-9a-f]{12}\/board/);
  batchId = /#\/b\/([0-9a-f]{12})/.exec(page.url())![1];
  const st = await api<{ jobs: { title: string }[] }>(`/api/batches/${batchId}`);
  expect(st.jobs.length).toBe(n - 1);
  expect(st.jobs[0].title).toBe('E2E 改过的标题');
  await expect.poll(async () => (await api<{ meta: { state: string } }>(`/api/batches/${batchId}`)).meta.state, { timeout: 30000 }).toBe('pilot-review');
  await api(`/api/batches/${batchId}/run`, { confirm_pilot: true });
  await expect.poll(async () => (await api<{ meta: { state: string } }>(`/api/batches/${batchId}`)).meta.state, { timeout: 30000 }).toBe('ran');
});

test('job detail: caption fix (faithful check), hook swap, trim, undo, re-render affected', async () => {
  await page.goto(`app://desk/index.html#/b/${batchId}/job/s001`);
  await expect(page.getByTestId('job-editor')).toBeVisible();
  await expect(page.getByTestId('review-timer')).toBeVisible();
  const cue = page.getByTestId('cue-0');
  const text = await cue.inputValue();
  await cue.fill(text + '记得点赞关注收藏转发');
  await cue.press('Enter');
  await expect(page.getByTestId('edit-msg')).toHaveText(/音频里没有|not in the audio/);
  await cue.fill(text.slice(0, -1) + '嘛');
  await cue.press('Enter');
  await expect(page.getByTestId('rerun-bar')).toContainText('export');
  await page.getByTestId('edit-tab-hook').click();
  await page.getByTestId('hook-1').check();
  await expect(page.getByTestId('rerun-bar')).toContainText('compose');
  await page.getByTestId('edit-tab-trim').click();
  await page.getByTestId('edge-start').focus();
  await page.keyboard.press('ArrowRight');
  await page.getByTestId('trim-apply').click();
  await expect(page.getByTestId('rerun-bar')).toContainText('cleanup');
  await page.getByTestId('edit-tab-copy').click();
  await page.getByTestId('copy-title').fill('临时标题');
  await page.getByTestId('copy-save').click();
  await expect(page.getByTestId('edit-msg')).toBeVisible();
  await page.locator('.topbar h1').click(); // leave the input so ⌘Z is the editor's
  await page.keyboard.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z');
  await expect(page.getByTestId('edit-msg')).toHaveText(/已撤销|Undone/);
  const jd = await api<{ edit: { copy: { title: string }; history: unknown[]; pending: string[] } }>(`/api/batches/${batchId}/jobs/s001`);
  expect(jd.edit.copy.title).toBe('E2E 改过的标题');
  expect(jd.edit.history).toHaveLength(3);
  await page.getByTestId('rerun-affected').click();
  await expect.poll(async () => (await api<{ edit: { pending: string[] } }>(`/api/batches/${batchId}/jobs/s001`)).edit.pending.length).toBe(0);
  await expect.poll(async () => (await api<{ job: { state: string } }>(`/api/batches/${batchId}/jobs/s001`)).job.state, { timeout: 20000 }).toBe('done');
});

test('job detail: refusal reason + re-hear, notes panel edit (overlay only), inner cut (word-snapped)', async () => {
  await page.goto(`app://desk/index.html#/b/${batchId}/job/s002`);
  await expect(page.getByTestId('job-editor')).toBeVisible();
  const cue = page.getByTestId('cue-0');
  await cue.fill((await cue.inputValue()) + '记得点赞关注收藏转发');
  await cue.press('Enter');
  await expect(page.getByTestId('cue-refusal-0')).toContainText(/音频里没有|not in the audio/);
  await expect(page.getByTestId('cue-reasr-0')).toBeVisible();
  await cue.press('Escape');
  await page.getByTestId('edit-tab-notes').click();
  await page.getByTestId('notes-text').fill('要点一\n要点二');
  await page.getByTestId('notes-save').click();
  await expect(page.getByTestId('rerun-bar')).toContainText('export');
  await expect(page.getByTestId('rerun-bar')).not.toContainText('cleanup');
  const jd = await api<{ edit: { range: [number, number]; words: { t: number; te: number }[]; notes: string[] } }>(`/api/batches/${batchId}/jobs/s002`);
  expect(jd.edit.notes).toEqual(['要点一', '要点二']);
  const inner = jd.edit.words.filter((w) => w.t > jd.edit.range[0] && w.te < jd.edit.range[1]);
  await page.getByTestId('edit-tab-cut').click();
  await page.getByTestId('cut-start').fill(String(inner[2].t + 0.01));
  await page.getByTestId('cut-end').fill(String(inner[3].te - 0.01));
  await page.getByTestId('cut-apply').click();
  await expect(page.getByTestId('rerun-bar')).toContainText('cleanup');
  await expect(page.getByTestId('cut-list')).toBeVisible();
  const after = await api<{ edit: { cuts: { start: number; end: number }[] } }>(`/api/batches/${batchId}/jobs/s002`);
  expect(after.edit.cuts[0].start).toBeCloseTo(inner[2].t, 2);
  expect(after.edit.cuts[0].end).toBeCloseTo(inner[3].te, 2);
});

test('delivery package: folders, 文案.md, schedule, notes, zip; delivered state', async () => {
  const st = await api<{ jobs: { id: string }[] }>(`/api/batches/${batchId}`);
  for (const j of st.jobs) await api(`/api/batches/${batchId}/timing`, { job: j.id, event: 'stop', what: 'review', active_s: 12 });
  await api(`/api/batches/${batchId}/review/apply`, { decisions: Object.fromEntries(st.jobs.map((j) => [j.id, { decision: 'approve' }])) });
  await page.evaluate((id) => (location.hash = `#/b/${id}/deliver`), batchId);
  await page.getByTestId('deliver').click();
  await expect(page.getByTestId('delivery')).toBeVisible({ timeout: 30000 });
  const d = (await api<{ delivery: { dir: string; zip: string; cleanup: { enabled: boolean } } }>(`/api/batches/${batchId}/deliver`)).delivery;
  const names = fs.readdirSync(d.dir);
  for (const f of ['文案.md', '排期表.csv', '交付说明.md', 'manifest.json', '小红书']) expect(names).toContain(f);
  expect(fs.readFileSync(path.join(d.dir, '文案.md'), 'utf8')).toContain('AI 标识提醒');
  expect(fs.existsSync(d.zip)).toBe(true);
  expect(d.cleanup.enabled).toBe(false); // source cleanup is never on by default
  const c = await api<{ crm: { stage: string } }>('/api/clients/e2e');
  expect(c.crm.stage).toBe('delivered');
});

test('metrics dashboard and weekly_metrics.csv export', async () => {
  await page.evaluate(() => (location.hash = '#/metrics'));
  await expect(page.locator('.tile').first()).toBeVisible();
  await page.locator('select[aria-label="批次"], select[aria-label="Batch"]').selectOption(batchId);
  await expect(page.getByTestId('job-metrics')).toContainText('12s');
  await page.getByTestId('export-weekly').click();
  await expect.poll(() => fs.existsSync(csvOut)).toBe(true);
  expect(fs.readFileSync(csvOut, 'utf8').split('\n')[0]).toBe(
    '周,线索数,沟通数,样片数,确认试点数,交付数,回传数据数,付费数,收入(¥),交付条数,人审秒数中位数/条,返工率,质检红灯率,每条成本($),内容号播放中位数,内容号收藏率,内容号涨粉,工作室号有效线索',
  );
});
