// History: past work in a watched folder shows up on the Batches page without an import; search filters it;
// "remove from list" hides it and leaves the files alone. Mock engine, isolated profile and registries.
import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let app: ElectronApplication;
let page: Page;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vsdesk-history-'));
const watch = path.join(tmp, 'demos');

function fakeBatch(dir: string, name: string, delivered: boolean) {
  fs.mkdirSync(path.join(dir, 'jobs', 'ep01', 'preview'), { recursive: true });
  const py = `
import json, sqlite3, sys
con = sqlite3.connect(sys.argv[1] + '/batch.db')
con.executescript("""CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE jobs (id TEXT PRIMARY KEY, ord INTEGER, state TEXT, qc TEXT, review TEXT, created REAL, updated REAL);
CREATE TABLE deliveries (n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, client TEXT);""")
con.execute("INSERT INTO meta VALUES ('spec', ?)", (json.dumps(dict(name=sys.argv[2], recipe='longform-split')),))
con.execute("INSERT INTO jobs VALUES ('ep01', 0, 'done', 'green', NULL, 1, 2)")
if sys.argv[3] == '1':
    con.execute("INSERT INTO deliveries(ts, client) VALUES (1, '自己的账号')")
con.commit()
`;
  execFileSync('python3', ['-c', py, dir, name, delivered ? '1' : '0']);
}

test.describe.configure({ mode: 'serial' });

const fuye = path.join(watch, 'fuye');
const statusFile = path.join(fuye, '.vstudio', 'status.json');

/** What an external run (Claude Code + the skill, a terminal) writes: vstudio.batch.livestatus. */
function heartbeat(rec: Record<string, unknown>) {
  fs.mkdirSync(path.dirname(statusFile), { recursive: true });
  const now = Date.now() / 1000;
  fs.writeFileSync(statusFile, JSON.stringify({ status: 'running', stage: 'render', progress: 0.4, message: 'clip B', eta: 120, started: now - 90, heartbeat: now, pid: process.pid, host: os.hostname(), updated_by: 'workflow', ...rec }));
}

test.beforeAll(async () => {
  fakeBatch(path.join(watch, 'batch-rag'), 'rag', true);
  fakeBatch(path.join(watch, 'client-a', 'batch-promo'), 'promo', false);
  // a plain work folder made with the skill (no batch.db / project.yaml)
  const th = path.join(watch, '01-talkinghead');
  fs.mkdirSync(path.join(th, 'final'), { recursive: true });
  fs.writeFileSync(path.join(th, 'REPORT.md'), '# 01-talkinghead: 口播精剪\n');
  fs.writeFileSync(path.join(th, 'final', 'xhs_3x4.mp4'), 'not really a video');
  fs.writeFileSync(path.join(th, 'final', 'post.md'), '进亚麻不适应？\n正文 #职场');
  fs.mkdirSync(path.join(fuye, 'work'), { recursive: true });
  fs.writeFileSync(path.join(fuye, 'work', 'compose.py'), '');
  fs.writeFileSync(path.join(fuye, 'work', 'render.log'), 'frame 1\nframe 2\nrendering clip B');
  app = await electron.launch({
    args: [path.resolve(import.meta.dirname, '../..')],
    env: { ...process.env, DESK_ENGINE_MOCK: '1', DESK_USER_DATA: path.join(tmp, 'profile'), VSTUDIO_HOME: path.join(tmp, 'vhome'), DESK_HISTORY_WATCH: watch, DESK_HIDE_WINDOW: '1', DESK_SHARED_CACHE: path.join(tmp, 'cache'), DESK_HF_HUB: '', DESK_SKIP_FIRST_RUN: '1', VITE_DEV_SERVER_URL: '' },
  });
  page = await app.firstWindow();
  await page.waitForURL(/^app:\/\/desk\//);
});

test.afterAll(async () => {
  await app?.close();
});

test('全部项目: past work from a watched folder, search, remove from list (undo) keeps files', async () => {
  await page.getByTestId('nav-projects').click();
  const cards = page.getByTestId('project-card');
  await expect(cards).toHaveCount(5, { timeout: 30000 }); // 4 found folders + the mock engine's demo batch
  await expect(page.getByTestId('projects-grid')).toContainText('rag');
  await page.getByTestId('projects-search').fill('promo');
  await expect(cards).toHaveCount(1);
  await cards.first().click({ button: 'right' });
  await page.getByTestId('menu-remove').click();
  await expect(cards).toHaveCount(0);
  await page.getByTestId('toast-undo').click(); // undo toast for every destructive action
  await expect(cards).toHaveCount(1);
  await cards.first().click({ button: 'right' });
  await page.getByTestId('menu-remove').click();
  await page.getByTestId('projects-search').fill('');
  await expect(cards).toHaveCount(4);
  expect(fs.existsSync(path.join(watch, 'client-a', 'batch-promo', 'batch.db'))).toBe(true);
});

test('a work folder: the whole card opens it, one card per clip with its caption, nothing written', async () => {
  await page.getByTestId('projects-type').selectOption('talkinghead');
  const cards = page.getByTestId('project-card');
  await expect(cards).toHaveCount(1);
  await cards.first().click(); // B1: the whole card is the link
  await expect(page.getByTestId('clip-card')).toHaveCount(1);
  await expect(page.getByTestId('post-copy')).toContainText('进亚麻不适应');
  const th = path.join(watch, '01-talkinghead');
  expect(fs.readdirSync(th).sort()).toEqual(['REPORT.md', 'final']); // B3: no 转成项目 button, nothing adopted by looking
});

test('进行中: an external run shows live on Home, 出错 when its heartbeat stops, 需要你 at a checkpoint', async () => {
  await page.getByTestId('nav-home').click();
  heartbeat({});
  const lane = page.getByTestId('live-lane');
  await expect(lane).toContainText('clip B', { timeout: 15000 }); // fs watch -> refresh, no polling
  await expect(lane.getByTestId('live-state')).toHaveText(/运行中|Running/);
  await expect(page.getByTestId('running-badge')).toHaveText('1');
  heartbeat({ pid: 999999, heartbeat: Date.now() / 1000 - 3600 }); // the external process died an hour ago
  await expect(lane.getByTestId('live-row')).toHaveCount(0, { timeout: 15000 });
  await expect(page.getByTestId('running-badge')).toHaveCount(0);
  await page.getByTestId('nav-projects').click();
  await page.getByTestId('projects-type').selectOption('');
  await expect(page.getByTestId('project-card').filter({ hasText: 'fuye' }).getByTestId('status')).toHaveText(/出错|Error/);
  heartbeat({ status: 'waiting', needs_you: true, message: 'checkpoint: hooks' });
  await page.getByTestId('nav-home').click();
  // parked at a checkpoint: not "running" any more - it waits in the Inbox (Home shows the top of it)
  const row = page.getByTestId('home-inbox-row').filter({ hasText: 'fuye' });
  await expect(row).toBeVisible({ timeout: 15000 });
  await expect(lane).toHaveCount(0);
  await row.getByTestId('home-inbox-act').click();
  await page.getByTestId('inbox-preview').getByTestId('crumb-project').click();
  await expect(page.getByTestId('project-title')).toHaveText('fuye');
  await page.getByTestId('tab-files').click();
  await expect(page.getByTestId('log-tail')).toContainText('rendering clip B');
});
